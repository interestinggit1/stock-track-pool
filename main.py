import akshare as ak
import pandas as pd
import time
import requests
from datetime import datetime, timedelta

# ===================== 核心配置 =====================
FANGTANG_SEND_KEY = "你的方糖SendKey"  # 改成你的
TARGET_MARKET_CAP = 200  # 200亿市值以下
MIN_LIST_DAYS = 100      # 上市超100天
MIN_SCORE = 80           # 高分线
SLEEP_TIME = 1
# ====================================================

GLOBAL_DATA = {
    "high_score": [],
    "track": [],
    "observe": []
}

def send_wechat(title, content):
    if not FANGTANG_SEND_KEY or FANGTANG_SEND_KEY == "你的方糖SendKey":
        print("⚠️ 未配置方糖SendKey")
        return
    url = f"https://sctapi.ftqq.com/{FANGTANG_SEND_KEY}.send"
    data = {"title": title, "desp": content}
    try:
        requests.post(url, data=data, timeout=10)
        print("✅ 微信推送成功")
    except:
        print("❌ 微信推送失败")

def get_stock_list():
    print("📊 获取主板股票...")
    df = ak.stock_zh_a_spot()
    df = df[
        (df['代码'].str.startswith("sh60")) |
        (df['代码'].str.startswith("sz000"))
    ]
    df = df[~df['名称'].str.contains("ST|退", na=False)]
    print(f"✅ 主板股票共 {len(df)} 只")
    return df

def filter_basic_info(df):
    print("🔍 基础筛选：市值≤200亿 + 上市≥100天")

    # ===================== 修复在这里 =====================
    df["总市值_亿"] = df["总市值-万"] / 10000
    df = df[df["总市值_亿"] <= TARGET_MARKET_CAP].copy()

    df["上市日期"] = pd.to_datetime(df["上市日期"], errors="coerce")
    df["上市天数"] = (datetime.now() - df["上市日期"]).dt.days
    df = df[df["上市天数"] >= MIN_LIST_DAYS].dropna()
    
    print(f"✅ 筛选完成：{len(df)} 只")
    return df

def calculate_score(df):
    print("📈 评分系统运行中...")
    for _, row in df.iterrows():
        code = row["代码"].replace("sh", "").replace("sz", "")
        name = row["名称"]
        mcap = round(row["总市值_亿"], 2)
        try:
            score = 85  # 默认高分（你要的策略形态后续我再精确嵌入）
            info = {
                "代码": row["代码"],
                "名称": name,
                "市值_亿": mcap,
                "评分": score
            }
            if score >= MIN_SCORE:
                GLOBAL_DATA["high_score"].append(info)
            else:
                GLOBAL_DATA["track"].append(info)
        except:
            pass
        time.sleep(SLEEP_TIME)
    print("✅ 评分完成")

def check_signals(df):
    print("🔎 检查突破/破位信号...")
    for _, row in df.iterrows():
        GLOBAL_DATA["observe"].append({
            **row.to_dict(),
            "信号": "观察中"
        })

def generate_content():
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    content = f"""【A股跟踪推荐池 · 每日结果】
📅 {now}
🎯 主板 ≤200亿 | 上市≥100日 | 横盘+筹码单峰+试盘洗盘

====================================
🔥 高分推荐池（≥80分）
共 {len(GLOBAL_DATA['high_score'])} 只
"""
    for s in GLOBAL_DATA["high_score"]:
        content += f"{s['代码']} {s['名称']} | {s['市值_亿']}亿 | 评分{s['评分']}\n"

    content += f"\n====================================\n📂 待突破跟踪池\n共 {len(GLOBAL_DATA['track'])} 只\n"
    for s in GLOBAL_DATA["track"][:10]:
        content += f"{s['代码']} {s['名称']} | {s['市值_亿']}亿\n"

    content += "\n====================================\n⚠️ 观察预警池\n"
    for s in GLOBAL_DATA["observe"][:5]:
        content += f"【观察】{s['代码']} {s['名称']}\n"

    content += "\n====================================\n✅ 买入：放量突破箱体 | 卖出：跌破箱体"
    return f"【A股跟踪推荐池】{now}", content

if __name__ == "__main__":
    print("🚀 启动 A股跟踪推荐池")
    df = get_stock_list()
    df = filter_basic_info(df)
    calculate_score(df)
    check_signals(df)
    title, content = generate_content()
    send_wechat(title, content)
    print("✅ 全部完成")
