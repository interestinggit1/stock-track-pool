import akshare as ak
import pandas as pd
import time
import requests
import os
from datetime import datetime, timedelta

# ===================== 核心配置（安全读取，无明文密钥）=====================
FANGTANG_SEND_KEY = os.getenv("FANGTANG_SEND_KEY", "")  # 从GitHub加密环境变量读取
TARGET_MARKET_CAP = 200  # 总市值≤200亿
MIN_LIST_DAYS = 100      # 上市超100天
MIN_SCORE = 80           # 高分票阈值
SLEEP_TIME = 1.2         # 防反爬间隔
# ==========================================================================

# 三库数据结构
GLOBAL_DATA = {
    "high_score": [],   # 🏆 高分推荐池（≥80分）
    "track": [],        # 📂 待突破跟踪池（60-79分）
    "observe": []       # 🚨 信号预警池（突破/破位）
}

def send_wechat(title, content):
    """方糖微信推送（安全版，兜底内容确保收到）"""
    if not FANGTANG_SEND_KEY:
        print("⚠️  未配置SendKey（环境变量未传入）")
        return
    
    if not content:
        content = "📭 今日暂无符合条件股票，策略运行正常。"

    url = f"https://sctapi.ftqq.com/{FANGTANG_SEND_KEY}.send"
    data = {"title": title, "desp": content}
    try:
        res = requests.post(url, data=data, timeout=15)
        if res.status_code == 200:
            print("✅ 微信推送成功")
        else:
            print(f"❌ 推送失败，状态码：{res.status_code}")
    except Exception as e:
        print(f"❌ 推送异常：{str(e)}")

def get_stock_list():
    """获取沪深主板股票，过滤ST/退市"""
    print("📊 获取沪深主板股票列表...")
    df_all = ak.stock_zh_a_spot()
    
    # 过滤主板：60开头(沪市)、000开头(深市)
    df_main = df_all[
        (df_all['代码'].str.startswith('sh60')) | 
        (df_all['代码'].str.startswith('sz000'))
    ]
    # 过滤ST、退市股
    df_main = df_main[~df_main['名称'].str.contains('ST|退', na=False)]
    print(f"✅ 筛选出主板股票共 {len(df_main)} 只")
    return df_main

def filter_basic_info(df_stock):
    """基础筛选：市值≤200亿 + 上市超100天（适配真实字段+容错）"""
    print("🔍 基础筛选（市值+上市天数）...")
    
    # 适配AkShare真实字段：总市值(万元)，容错处理
    try:
        df_stock['总市值_亿'] = df_stock['总市值(万元)'] / 10000
    except KeyError:
        print("⚠️  未找到'总市值(万元)'字段，使用默认市值")
        df_stock['总市值_亿'] = 999.9
    
    # 筛选市值≤200亿
    df_filter = df_stock[df_stock['总市值_亿'] <= TARGET_MARKET_CAP].copy()
    
    # 计算上市天数，容错处理
    try:
        df_filter['上市日期'] = pd.to_datetime(df_filter['上市日期'], errors='coerce')
        df_filter['上市天数'] = (datetime.now() - df_filter['上市日期']).dt.days
        df_filter = df_filter[df_filter['上市天数'] >= MIN_LIST_DAYS].dropna(subset=['上市天数'])
    except KeyError:
        print("⚠️  未找到'上市日期'字段，跳过上市天数筛选")
    
    print(f"✅ 基础筛选完成，剩余 {len(df_filter)} 只（市值≤200亿+上市≥100天）")
    return df_filter

def calculate_technical_score(df_stock):
    """计算综合评分：横盘+筹码+试盘+洗盘+市值+上市天数（完整策略）"""
    print("📈 计算技术形态评分...")
    scores = []
    results = []
    
    for idx, row in df_stock.iterrows():
        code = row['代码']
        name = row['名称']
        market_cap = row['总市值_亿']
        list_days = row.get('上市天数', 365)  # 兜底
        
        # 1. 获取近60日K线数据
        try:
            pure_code = code.replace('sh', '').replace('sz', '')
            df_k = ak.stock_zh_a_hist(
                symbol=pure_code, 
                period="daily", 
                start_date=(datetime.now() - timedelta(days=120)).strftime("%Y%m%d"),
                end_date=datetime.now().strftime("%Y%m%d")
            )
            if len(df_k) < 60:
                scores.append(0)
                results.append("数据不足")
                continue
        except Exception as e:
            scores.append(0)
            results.append(f"K线获取失败：{str(e)[:10]}")
            continue
        
        # 2. 近60日窄幅横盘评分（30分）
        df_60d = df_k.tail(60)
        max_price = df_60d['最高'].max()
        min_price = df_60d['最低'].min()
        amplitude = (max_price - min_price) / min_price * 100  # 振幅百分比
        
        if amplitude <= 15:
            score_horizontal = 30
        elif amplitude <= 20:
            score_horizontal = 20
        elif amplitude <= 25:
            score_horizontal = 10
        else:
            score_horizontal = 0
        
        # 3. 筹码单峰密集评分（30分）
        try:
            cost_df = ak.stock_cost_price_hist(symbol=pure_code)
            if not cost_df.empty and len(cost_df) >= 1:
                cost90 = cost_df.iloc[-1]['成本90']
                cost10 = cost_df.iloc[-1]['成本10']
                cost50 = cost_df.iloc[-1]['成本50']
                concentration = (cost90 - cost10) / cost50 * 100  # 筹码集中度
                
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
            concentration = 0
        
        # 4. 试盘放量+缩量洗盘评分（25分）
        df_20d = df_k.tail(20)
        avg_volume_20 = df_20d['成交量'].mean()
        trial_signal = False
        
        # 试盘：单日成交量≥2倍均量，且冲高回落（长上影）
        for _, k_row in df_20d.iterrows():
            if k_row['成交量'] >= avg_volume_20 * 2:
                if k_row['收盘'] < k_row['开盘'] and (k_row['最高'] - k_row['收盘']) / (k_row['收盘'] - k_row['最低'] + 0.001) > 0.5:
                    trial_signal = True
                    break
        
        # 洗盘：试盘后5-10日，成交量≤0.5倍均量，股价不破箱体下沿
        wash_signal = False
        if trial_signal:
            trial_dates = df_20d[df_20d['成交量'] >= avg_volume_20 * 2].index.tolist()
            if trial_dates:
                trial_date = trial_dates[-1]
                wash_start = trial_date + 1
                wash_end = min(trial_date + 10, len(df_20d) - 1)
                if wash_start < wash_end:
                    df_wash = df_20d.iloc[wash_start:wash_end+1]
                    if (df_wash['成交量'] <= avg_volume_20 * 0.5).all():
                        if (df_wash['最低'] >= min_price * 0.98).all():
                            wash_signal = True
        
        if trial_signal and wash_signal:
            score_trial_wash = 25
        elif trial_signal or wash_signal:
            score_trial_wash = 12
        else:
            score_trial_wash = 0
        
        # 5. 市值+上市天数基础分（15分）
        score_market = 10 if market_cap <= 100 else 5  # 市值≤100亿得10分
        score_list = 5 if list_days >= 365 else 2 if list_days >= 100 else 0  # 上市超1年得5分
        
        # 综合总分
        total_score = score_horizontal + score_chip + score_trial_wash + score_market + score_list
        scores.append(total_score)
        
        # 形态详情
        result_detail = f"振幅{amplitude:.1f}%|筹码集中度{concentration:.1f}%|试盘{trial_signal}|洗盘{wash_signal}"
        results.append(result_detail)
        
        # 三库分类
        stock_info = {
            "代码": code,
            "名称": name,
            "市值_亿": round(market_cap, 2),
            "上市天数": int(list_days),
            "振幅_60d": round(amplitude, 2),
            "筹码集中度": round(concentration, 2),
            "评分": total_score,
            "最新价": row.get('最新价', 0),
            "涨跌幅": row.get('涨跌幅', 0)
        }
        
        if total_score >= MIN_SCORE:
            GLOBAL_DATA["high_score"].append(stock_info)
        elif total_score >= 60:
            GLOBAL_DATA["track"].append(stock_info)
        
        time.sleep(SLEEP_TIME)  # 防反爬
    
    df_stock['评分'] = scores
    df_stock['形态详情'] = results
    return df_stock

def check_buy_sell_signal(df_stock):
    """检查买卖信号：放量突破上沿/跌破箱体下沿"""
    print("🔎 检查买卖信号...")
    for idx, row in df_stock.iterrows():
        code = row['代码']
        score = row['评分']
        if score < 60:
            continue  # 低分票不跟踪
        
        try:
            pure_code = code.replace('sh', '').replace('sz', '')
            df_k = ak.stock_zh_a_hist(
                symbol=pure_code,
                period="daily",
                start_date=(datetime.now() - timedelta(days=100)).strftime("%Y%m%d"),
                end_date=datetime.now().strftime("%Y%m%d")
            )
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
        
        # 买入信号：放量突破箱体上沿（收盘价突破+成交量≥1.5倍均量）
        if current_price >= box_top * 1.01 and current_volume >= avg_volume_20 * 1.5:
            GLOBAL_DATA["observe"].append({
                **row.to_dict(),
                "信号": "买入突破"
            })
        # 卖出信号：跌破箱体下沿（收盘价跌破+连续2日确认）
        elif current_price <= box_bottom * 0.97 and (df_60d.tail(2)['收盘'] < box_bottom).sum() >= 1:
            GLOBAL_DATA["observe"].append({
                **row.to_dict(),
                "信号": "卖出破位"
            })

def generate_push_content():
    """生成微信推送内容（布局微调版，层次分明）"""
    today = datetime.now().strftime("%Y-%m-%d")
    now_time = datetime.now().strftime("%H:%M")
    
    title = f"【A股跟踪推荐池】{today} 每日选股结果"
    
    # 🏆 高分推荐池内容
    high_content = ""
    if GLOBAL_DATA['high_score']:
        for stock in GLOBAL_DATA['high_score']:
            high_content += f"▶ {stock['代码']} {stock['名称']} | 💰{stock['市值_亿']}亿 | ⭐{stock['评分']}分 | 📈{stock['涨跌幅']}%\n"
    else:
        high_content = "暂无\n"
    
    # 📂 待突破跟踪池内容
    track_content = ""
    if GLOBAL_DATA['track']:
        for stock in GLOBAL_DATA['track'][:10]:  # 只展示前10只，避免过长
            track_content += f"▫ {stock['代码']} {stock['名称']} | 💰{stock['市值_亿']}亿 | ⭐{stock['评分']}分\n"
    else:
        track_content = "暂无\n"
    
    # 🚨 信号预警池内容
    observe_content = ""
    if GLOBAL_DATA['observe']:
        for stock in GLOBAL_DATA['observe']:
            signal = stock.get('信号', '未知信号')
            observe_content += f"【{signal}】{stock['代码']} {stock['名称']} | 💰{stock['总市值_亿']}亿 | 现价{stock['最新价']}\n"
    else:
        observe_content = "暂无\n"
    
    content = f"""【A股跟踪推荐池 · 每日选股结果】
📅 日期：{today}
⏱ 时间：{now_time}
🎯 策略：主板+市值≤200亿+60日横盘+筹码单峰+试盘洗盘

====================================
🏆 高分推荐池（≥{MIN_SCORE}分 · 重点建仓）
共 {len(GLOBAL_DATA['high_score'])} 只
------------------------------------
{high_content}
====================================
📂 待突破跟踪池（60-{MIN_SCORE-1}分 · 每日盯盘）
共 {len(GLOBAL_DATA['track'])} 只
------------------------------------
{track_content}
====================================
🚨 信号预警
共 {len(GLOBAL_DATA['observe'])} 只
------------------------------------
{observe_content}
====================================
✅ 交易纪律
• 买入：放量突破箱体上沿
• 卖出：有效跌破箱体下沿严格止损

💡 提示：优先关注高分推荐池，跟踪池耐心等突破！
    """
    return title, content

def save_data_to_csv():
    """保存三库数据到CSV，方便下载查看"""
    print("💾 保存数据到本地...")
    try:
        if GLOBAL_DATA['high_score']:
            pd.DataFrame(GLOBAL_DATA['high_score']).to_csv("高分推荐池.csv", index=False, encoding="utf-8-sig")
        if GLOBAL_DATA['track']:
            pd.DataFrame(GLOBAL_DATA['track']).to_csv("待突破跟踪池.csv", index=False, encoding="utf-8-sig")
        if GLOBAL_DATA['observe']:
            pd.DataFrame(GLOBAL_DATA['observe']).to_csv("信号预警池.csv", index=False, encoding="utf-8-sig")
        print("✅ 数据保存完成")
    except Exception as e:
        print(f"❌ 数据保存失败：{str(e)}")

if __name__ == "__main__":
    print("🚀 A股跟踪推荐池系统启动")
    try:
        df_list = get_stock_list()
        df_filter = filter_basic_info(df_list)
        df_scored = calculate_technical_score(df_filter)
        check_buy_sell_signal(df_scored)
        save_data_to_csv()
        title, content = generate_push_content()
        send_wechat(title, content)
        print("✅ 任务全部完成")
    except Exception as e:
        print(f"❌ 运行出错：{e}")
        send_wechat("【A股跟踪推荐池】运行异常", f"错误信息：{e}")
