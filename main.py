import akshare as ak
import pandas as pd
import time
import requests
from datetime import datetime, timedelta

# ===================== 核心配置（必须修改）=====================
FANGTANG_SEND_KEY = "SCT303030TMwGN5ubOvqH1oVX20G0Hqg9s"  # 替换成你自己的SendKey
BATCH_SIZE = 30
SLEEP_TIME = 1.2
TARGET_MARKET_CAP = 200
MIN_LIST_DAYS = 100
MIN_SCORE = 80
# =================================================================

GLOBAL_DATA = {
    "high_score": [],
    "track": [],
    "observe": []
}

def send_wechat(title, content):
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
    print("📊 获取沪深主板股票列表...")
    df_all = ak.stock_zh_a_spot()
    df_main = df_all[
        (df_all['代码'].str.startswith('sh60')) | 
        (df_all['代码'].str.startswith('sz000'))
    ]
    df_main = df_main[~df_main['名称'].str.contains('ST', na=False)]
    df_main = df_main[~df_main['名称'].str.contains('退', na=False)]
    print(f"✅ 筛选出主板股票共 {len(df_main)} 只")
    return df_main

def filter_basic_info(df_stock):
    print("🔍 基础筛选（市值+上市天数）...")
    df_stock['总市值_亿'] = df_stock['总市值'] / 10000
    df_filter = df_stock[df_stock['总市值_亿'] <= TARGET_MARKET_CAP].copy()
    today = datetime.now()
    df_filter['上市日期'] = pd.to_datetime(df_filter['上市日期'], errors='coerce')
    df_filter['上市天数'] = (today - df_filter['上市日期']).dt.days
    df_filter = df_filter[df_filter['上市天数'] >= MIN_LIST_DAYS].dropna(subset=['上市天数'])
    print(f"✅ 基础筛选完成，剩余 {len(df_filter)} 只（市值≤200亿+上市≥100天）")
    return df_filter

def calculate_technical_score(df_stock):
    print("📈 计算技术形态评分...")
    scores = []
    results = []
    for idx, row in df_stock.iterrows():
        code = row['代码']
        name = row['名称']
        market_cap = row['总市值_亿']
        list_days = row['上市天数']
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
        
        df_60d = df_k.tail(60)
        max_price = df_60d['最高'].max()
        min_price = df_60d['最低'].min()
        amplitude = (max_price - min_price) / min_price * 100
        if amplitude <= 15:
            score_horizontal = 30
        elif amplitude <= 20:
            score_horizontal = 20
        elif amplitude <= 25:
            score_horizontal = 10
        else:
            score_horizontal = 0
        
        try:
            cost_df = ak.stock_cost_price_hist(symbol=code.replace('sh', '').replace('sz', ''))
            if not cost_df.empty and len(cost_df) >= 1:
                cost90 = cost_df.iloc[-1]['成本90']
                cost10 = cost_df.iloc[-1]['成本10']
                cost50 = cost_df.iloc[-1]['成本50']
                concentration = (cost90 - cost10) / cost50 * 100
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
        
        df_20d = df_k.tail(20)
        avg_volume_20 = df_20d['成交量'].mean()
        trial_signal = False
        for _, k_row in df_20d.iterrows():
            if k_row['成交量'] >= avg_volume_20 * 2:
                if k_row['收盘'] < k_row['开盘'] and (k_row['最高'] - k_row['收盘']) / (k_row['收盘'] - k_row['最低'] + 0.001) > 0.5:
                    trial_signal = True
                    break
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
                        box_bottom = min_price
                        if (df_wash['最低'] >= box_bottom * 0.98).all():
                            wash_signal = True
        if trial_signal and wash_signal:
            score_trial_wash = 25
        elif trial_signal or wash_signal:
            score_trial_wash = 12
        else:
            score_trial_wash = 0
        
        score_market = 10 if market_cap <= 100 else 5
        score_list = 5 if list_days >= 365 else 2 if list_days >= 100 else 0
        total_score = score_horizontal + score_chip + score_trial_wash + score_market + score_list
        scores.append(total_score)
        result_detail = f"振幅{amplitude:.1f}%|筹码集中度{concentration:.1f}%|试盘{trial_signal}|洗盘{wash_signal}"
        results.append(result_detail)
        
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
        time.sleep(SLEEP_TIME)
    
    df_stock['评分'] = scores
    df_stock['形态详情'] = results
    return df_stock

def check_signal(df_stock):
    print("🔎 检查买卖信号...")
    for idx, row in df_stock.iterrows():
        code = row['代码']
        score = row['评分']
        if score < 60:
            continue
        try:
            df_k = ak.stock_zh_a_hist(symbol=code.replace('sh', '').replace('sz', ''), period="daily", 
                                     start_date=(datetime.now() - timedelta(days=100)).strftime("%Y%m%d"),
                                     end_date=datetime.now().strftime("%Y%m%d"))
            if len(df_k) < 60:
                continue
            df_60d = df_k.tail(60)
            box_top = df_60d['最高'].max()
            box_bottom = df_60d['最低'].min()
            current_price = row['最新价']
            current_volume = row['成交量']
            avg_volume_20 = df_60d.tail(20)['成交量'].mean()
        except Exception as e:
            continue
        
        if current_price >= box_top * 1.01 and current_volume >= avg_volume_20 * 1.5:
            GLOBAL_DATA["observe"].append({
                **row.to_dict(),
                "信号": "买入突破"
            })
        elif current_price <= box_bottom * 0.97 and (df_60d.tail(2)['收盘'] < box_bottom).sum() >= 1:
            GLOBAL_DATA["observe"].append({
                **row.to_dict(),
                "信号": "卖出破位"
            })

def generate_push_content():
    today = datetime.now().strftime("%Y-%m-%d")
    now_time = datetime.now().strftime("%H:%M:%S")
    title = f"【A股跟踪推荐池】每日选股结果（{today}）"
    content = f"""【A股跟踪推荐池 · 每日选股结果】
📅 日期：{today}
⏱ 时间：{now_time}
🎯 策略：主板+市值≤200亿+60日横盘+筹码单峰+试盘洗盘

====================================
🔥 今日高分推荐池（≥{MIN_SCORE}分 · 重点关注）
共 {len(GLOBAL_DATA['high_score'])} 只
------------------------------------
"""
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
    if GLOBAL_DATA['observe']:
        for stock in GLOBAL_DATA['observe']:
            signal = stock.get('信号', '未知信号')
            content += f"【{signal}】{stock['代码']}  {stock['名称']}  💰{stock['市值_亿']}亿  现价{stock['最新价']}\n"
    else:
        content += "无\n"
    
    content += f"""
====================================
✅ 策略规则回顾
• 沪深主板 | 总市值≤{TARGET_MARKET_CAP}亿 | 上市≥{MIN_LIST_DAYS}天
• 60日窄幅横盘 | 筹码单峰密集 | 试盘放量→缩量洗盘
• 买入：放量突破箱体上沿 | 卖出：跌破箱体下沿严格止损

💡 核心提示：高分票优先建仓，跟踪池耐心等待突破信号！
    """
    return title, content

def save_data_to_csv():
    print("💾 保存数据到本地...")
    try:
        if GLOBAL_DATA['high_score']:
            pd.DataFrame(GLOBAL_DATA['high_score']).to_csv("高分推荐池.csv", index=False, encoding="utf-8-sig")
        if GLOBAL_DATA['track']:
            pd.DataFrame(GLOBAL_DATA['track']).to_csv("待突破跟踪池.csv", index=False, encoding="utf-8-sig")
        if GLOBAL_DATA['observe']:
            pd.DataFrame(GLOBAL_DATA['observe']).to_csv("观察预警池.csv", index=False, encoding="utf-8-sig")
        print("✅ 数据保存完成")
    except Exception as e:
        print(f"❌ 数据保存失败：{str(e)}")

if __name__ == "__main__":
    print("🚀 A股跟踪推荐池系统启动")
    df_list = get_stock_list()
    df_filter = filter_basic_info(df_list)
    df_scored = calculate_technical_score(df_filter)
    check_signal(df_scored)
    save_data_to_csv()
    title, content = generate_push_content()
    send_wechat(title, content)
    print("✅ 任务全部完成")
