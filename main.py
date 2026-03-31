import akshare as ak
import pandas as pd
import time
import requests
from datetime import datetime, timedelta

# ===================== 核心配置（可按需修改）=====================
FANGTANG_SEND_KEY = "SCT303030TMwGN5ubOvqH1oVX20G0Hqg9s"  # 替换成你的方糖SendKey
BATCH_SIZE = 30  # 每批读取30只，稳定防反爬
SLEEP_TIME = 1.2  # 批次间隔1.2秒
TARGET_MARKET_CAP = 200  # 市值≤200亿
MIN_LIST_DAYS = 100  # 上市超100天
MIN_SCORE = 80  # 高分票评分阈值
# =================================================================

# 全局数据存储（三库）
GLOBAL_DATA = {
    "high_score": [],  # 高分推荐池（≥80分）
    "track": [],       # 待突破跟踪池（60-79分）
    "observe": []      # 观察预警池（突破/破位信号）
}

def send_wechat(title, content):
    """方糖推送微信（核心函数）"""
    if not FANGTANG_SEND_KEY or FANGTANG_SEND_KEY == "你的方糖SendKey":
        print("⚠️  未配置方糖SendKey，跳过微信推送")
        return
    url = f"https://sctapi.ftqq.com/{FANGTANG_SEND_KEY}.send"
    data = {"title": title, "desp": content}
    try:
        res = requests.post(url, data=data, timeout=15)
        if res.status_code == 200:
            print("✅ 微信推送成功")
        else:
            print(f"❌ 微信推送失败，状态码：{res.status_code}")
    except Exception as e:
        print(f"❌ 微信推送异常：{str(e)}")

def get_stock_list():
    """获取沪深主板股票列表（过滤创业板/科创板/北交所/ST）"""
    print("📊 获取沪深主板股票列表...")
    # 获取全量A股
    df_all = ak.stock_zh_a_spot()
    # 过滤主板：60开头（沪市）、000开头（深市）
    df_main = df_all[
        (df_all['代码'].str.startswith('sh60')) | 
        (df_all['代码'].str.startswith('sz000'))
    ]
    # 过滤ST、退市
    df_main = df_main[~df_main['名称'].str.contains('ST', na=False)]
    df_main = df_main[~df_main['名称'].str.contains('退', na=False)]
    print(f"✅ 筛选出主板股票共 {len(df_main)} 只")
    return df_main

def filter_basic_info(df_stock):
    """基础筛选：市值≤200亿 + 上市超100天"""
    print("🔍 基础筛选（市值+上市天数）...")
    # 转换市值为亿
    df_stock['总市值_亿'] = df_stock['总市值'] / 10000
    # 筛选市值≤200亿
    df_filter = df_stock[df_stock['总市值_亿'] <= TARGET_MARKET_CAP].copy()
    
    # 计算上市天数
    today = datetime.now()
    df_filter['上市日期'] = pd.to_datetime(df_filter['上市日期'], errors='coerce')
    df_filter['上市天数'] = (today - df_filter['上市日期']).dt.days
    # 筛选上市≥100天
    df_filter = df_filter[df_filter['上市天数'] >= MIN_LIST_DAYS].dropna(subset=['上市天数'])
    
    print(f"✅ 基础筛选完成，剩余 {len(df_filter)} 只（市值≤200亿+上市≥100天）")
    return df_filter

def calculate_technical_score(df_stock):
    """计算综合评分（核心：横盘+筹码+试盘+洗盘）"""
    print("📈 计算技术形态评分...")
    scores = []
    results = []
    
    for idx, row in df_stock.iterrows():
        code = row['代码']
        name = row['名称']
        market_cap = row['总市值_亿']
        list_days = row['上市天数']
        
        # 1. 获取近60日K线数据
        try:
            df_k = ak.stock_zh_a_hist(symbol=code.replace('sh', '').replace('sz', ''), period="daily", 
                                     start_date=(datetime.now() - timedelta(days=100)).strftime("%Y%m%d"),
                                     end_date=datetime.now().strftime("%Y%m%d"))
            if len(df_k) < 60:
                scores.append(0)
                results.append("数据不足")
                continue
        except Exception as e:
            scores.append(0)
            results.append(f"K线获取失败：{str(e)[:10]}")
            continue
        
        # 2. 近60日窄幅横盘评分（权重30分）
        df_60d = df_k.tail(60)
        max_price = df_60d['最高'].max()
        min_price = df_60d['最低'].min()
        amplitude = (max_price - min_price) / min_price * 100  # 振幅百分比
        # 振幅≤15%得30分，每超5%扣10分，最低0分
        if amplitude <= 15:
            score_horizontal = 30
        elif amplitude <= 20:
            score_horizontal = 20
        elif amplitude <= 25:
            score_horizontal = 10
        else:
            score_horizontal = 0
        
        # 3. 筹码单峰密集评分（权重30分）
        try:
            # 获取筹码分布（90%成本）
            cost_df = ak.stock_cost_price_hist(symbol=code.replace('sh', '').replace('sz', ''))
            if not cost_df.empty and len(cost_df) >= 1:
                # 计算集中度：(COST90 - COST10)/COST50
                cost90 = cost_df.iloc[-1]['成本90']
                cost10 = cost_df.iloc[-1]['成本10']
                cost50 = cost_df.iloc[-1]['成本50']
                concentration = (cost90 - cost10) / cost50 * 100
                # 集中度≤10%得30分，每超5%扣10分
                if concentration <= 10:
                    score_chip = 30
                elif concentration <= 15:
                    score_chip = 20
                elif concentration <= 20:
                    score_chip = 10
                else:
                    score_chip = 0
            else:
                score_chip = 0
        except Exception as e:
            score_chip = 0
        
        # 4. 试盘放量+缩量洗盘评分（权重25分）
        df_20d = df_k.tail(20)
        avg_volume_20 = df_20d['成交量'].mean()
        # 试盘：近20日出现单日成交量≥2倍均量，且冲高回落
        trial_signal = False
        for _, k_row in df_20d.iterrows():
            if k_row['成交量'] >= avg_volume_20 * 2:
                # 冲高回落：收盘价<开盘价，且上影线较长
                if k_row['收盘'] < k_row['开盘'] and (k_row['最高'] - k_row['收盘']) / (k_row['收盘'] - k_row['最低'] + 0.001) > 0.5:
                    trial_signal = True
                    break
        # 洗盘：试盘后5-10日，成交量≤0.5倍均量，股价不破箱体下沿
        wash_signal = False
        if trial_signal:
            # 找到试盘日
            trial_dates = df_20d[df_20d['成交量'] >= avg_volume_20 * 2].index.tolist()
            if trial_dates:
                trial_date = trial_dates[-1]
                # 洗盘区间：试盘日后5-10日
                wash_start = trial_date + 1
                wash_end = min(trial_date + 10, len(df_20d) - 1)
                if wash_start < wash_end:
                    df_wash = df_20d.iloc[wash_start:wash_end+1]
                    # 成交量≤0.5倍均量
                    if (df_wash['成交量'] <= avg_volume_20 * 0.5).all():
                        # 股价不破箱体下沿
                        box_bottom = min_price
                        if (df_wash['最低'] >= box_bottom * 0.98).all():
                            wash_signal = True
        # 评分
        if trial_signal and wash_signal:
            score_trial_wash = 25
        elif trial_signal or wash_signal:
            score_trial_wash = 12
        else:
            score_trial_wash = 0
        
        # 5. 市值+上市天数基础分（权重15分）
        # 市值≤100亿得10分，100-200亿得5分
        score_market = 10 if market_cap <= 100 else 5
        # 上市≥365天得5分，100-365天得2分
        score_list = 5 if list_days >= 365 else 2 if list_days >= 100 else 0
        
        # 综合总分
        total_score = score_horizontal + score_chip + score_trial_wash + score_market + score_list
        scores.append(total_score)
        
        # 记录形态结果
        result_detail = f"振幅{amplitude:.1f}%|筹码集中度{concentration:.1f}%|试盘{trial_signal}|洗盘{wash_signal}"
        results.append(result_detail)
        
        # 加入三库
        stock_info = {
            "代码": code,
            "名称": name,
            "市值_亿": round(market_cap, 2),
            "上市天数": int(list_days),
            "振幅_60d": round(amplitude, 2),
            "筹码集中度": round(concentration, 2) if 'concentration' in locals() else 0,
            "评分": total_score,
            "形态详情": result_detail
        }
        if total_score >= MIN_SCORE:
            GLOBAL_DATA["high_score"].append(stock_info)
        elif total_score >= 60:
            GLOBAL_DATA["track"].append(stock_info)
        
        # 控制频率，避免反爬
        time.sleep(SLEEP_TIME)
    
    # 添加评分到原数据
    df_stock['评分'] = scores
    df_stock['形态详情'] = results
    return df_stock

def check_signal(df_stock):
    """检查买卖信号（突破上沿/跌破下沿），加入观察预警池"""
    print("🔎 检查买卖信号...")
    for idx, row in df_stock.iterrows():
        code = row['代码']
        score = row['评分']
        if score < 60:
            continue  # 跳过低分票
        
        # 获取近60日数据
        try:
            df_k = ak.stock_zh_a_hist(symbol=code.replace('sh', '').replace('sz', ''), period="daily", 
                                     start_date=(datetime.now() - timedelta(days=100)).strftime("%Y%m%d"),
                                     end_date=datetime.now().strftime("%Y%m%d"))
            if len(df_k) < 60:
                continue
            df_60d = df_k.tail(60)
            box_top = df_60d['最高'].max()  # 箱体上沿
            box_bottom = df_60d['最低'].min()  # 箱体下沿
            current_price = row['最新价']
            current_volume = row['成交量']
            avg_volume_20 = df_60d.tail(20)['成交量'].mean()
        except Exception as e:
            continue
        
        # 买入信号：放量突破箱体上沿（收盘价突破，成交量≥1.5倍均量）
        if current_price >= box_top * 1.01 and current_volume >= avg_volume_20 * 1.5:
            GLOBAL_DATA["observe"].append({
                **row.to_dict(),
                "信号": "买入突破"
            })
        # 卖出信号：跌破箱体下沿（收盘价跌破，且连续2日确认，简化为当日跌破+跌幅≥3%）
        elif current_price <= box_bottom * 0.97 and (df_60d.tail(2)['收盘'] < box_bottom).sum() >= 1:
            GLOBAL_DATA["observe"].append({
                **row.to_dict(),
                "信号": "卖出破位"
            })

def generate_push_content():
    """生成微信推送内容（按你确认的模板）"""
    today = datetime.now().strftime("%Y-%m-%d")
    now_time = datetime.now().strftime("%H:%M:%S")
    
    # 标题
    title = f"【A股主板策略】每日选股结果（{today}）"
    
    # 内容
    content = f"""【A股主板策略 · 每日选股结果】
📅 日期：{today}
⏱ 时间：{now_time}
🎯 策略：主板+市值≤200亿+60日横盘+筹码单峰+试盘洗盘

====================================
🔥 今日高分推荐池（≥{MIN_SCORE}分 · 重点关注）
共 {len(GLOBAL_DATA['high_score'])} 只
------------------------------------
"""
    # 高分票详情
    if GLOBAL_DATA['high_score']:
        for stock in GLOBAL_DATA['high_score']:
            content += f"{stock['代码']}  {stock['名称']}  💰{stock['市值_亿']}亿  ⭐评分{stock['评分']}\n"
    else:
        content += "无\n"
    
    content += f"""
====================================
📂 待突破跟踪池（60-{MIN_SCORE-1}分 · 每日跟踪）
共 {len(GLOBAL_DATA['track'])} 只
------------------------------------
"""
    # 跟踪票详情
    if GLOBAL_DATA['track']:
        for stock in GLOBAL_DATA['track']:
            content += f"{stock['代码']}  {stock['名称']}  💰{stock['市值_亿']}亿  ⭐评分{stock['评分']}\n"
    else:
        content += "无\n"
    
    content += f"""
====================================
⚠️  观察预警池（突破/破位信号）
共 {len(GLOBAL_DATA['observe'])} 只
------------------------------------
"""
    # 信号详情
    if GLOBAL_DATA['observe']:
        for stock in GLOBAL_DATA['observe']:
            signal = stock.get('信号', '未知信号')
            content += f"【{signal}】{stock['代码']}  {stock['名称']}  💰{stock['市值_亿']}亿  现价{stock['最新价']}\n"
    else:
        content += "无\n"
    
    content += f"""
====================================
✅ 策略规则回顾
• 沪深主板 | 总市值≤{TARGET_MARKET_CAP}亿 | 上市≥100天
• 60日窄幅横盘 | 筹码单峰密集 | 试盘放量→缩量洗盘
• 买入：放量突破箱体上沿 | 卖出：跌破箱体下沿严格止损

💡 核心提示：高分票优先建仓，跟踪池耐心等待突破信号！
    """
    return title, content

def save_data_to_csv():
    """保存三库数据到本地CSV（方便下载查看）"""
    print("💾 保存数据到本地...")
    try:
        # 高分票
        if GLOBAL_DATA['high_score']:
            pd.DataFrame(GLOBAL_DATA['high_score']).to_csv("高分推荐池.csv", index=False, encoding="utf-8-sig")
        # 跟踪票
        if GLOBAL_DATA['track']:
            pd.DataFrame(GLOBAL_DATA['track']).to_csv("待突破跟踪池.csv", index=False, encoding="utf-8-sig")
        # 观察票
        if GLOBAL_DATA['observe']:
            pd.DataFrame(GLOBAL_DATA['observe']).to_csv("观察预警池.csv", index=False, encoding="utf-8-sig")
        print("✅ 数据保存完成：高分推荐池.csv、待突破
