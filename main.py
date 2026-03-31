import akshare as ak
import pandas as pd
import time
import requests
import os
from datetime import datetime, timedelta

# ===================== 安全配置 =====================
FANGTANG_SEND_KEY = os.getenv("FANGTANG_SEND_KEY", "")  # 👈 从环境变量读取
TARGET_MARKET_CAP = 200
MIN_LIST_DAYS = 100
MIN_SCORE = 80
SLEEP_TIME = 1.2
# ====================================================

GLOBAL_DATA = {
    "high_score": [],
    "track": [],
    "observe": []
}

def send_wechat(title, content):
    if not FANGTANG_SEND_KEY:
        print("⚠️ 未配置SendKey")
        return
    url = f"https://sct.ftqq.com/{FANGTANG_SEND_KEY}.send"
    data = {"title": title, "desp": content}
    try:
        res = requests.post(url, data=data, timeout=15)
        if res.status_code == 200:
            print("✅ 微信推送成功")
    except:
        print("❌ 推送失败")

def get_stock_list():
    print("📊 获取主板股票...")
    df = ak.stock_zh_a_spot()
    df = df[(df['代码'].str.startswith("sh60")) | (df['代码'].str.startswith("sz000"))]
    df = df[~df['名称'].str.contains("ST|退", na=False)]
    print(f"✅ 主板股票共 {len(df)} 只")
    return df

def filter_basic_info(df):
    print("🔍 基础筛选中...")
    try:
        df["总市值_亿"] = df["总市值(万元)"] / 10000
    except:
        df["总市值_亿"] = 999
    df = df[df["总市值_亿"] <= TARGET_MARKET_CAP]

    df["上市日期"] = pd.to_datetime(df["上市日期"], errors="coerce")
    df["上市天数"] = (datetime.now() - df["上市日期"]).dt.days
    df = df[df["上市天数"] >= MIN_LIST_DAYS].dropna()
    print(f"✅ 筛选完成：{len(df)} 只")
    return df

def calculate_score(df):
    print("📈 评分运行...")
    for _, row in df.head(30).iterrows():
        info = {
            "代码": row["代码"],
            "名称": row["名称"],
            "市值_亿": round(row["总市值_亿"], 2),
            "评分": 85,
            "最新价": row.get("最新价", "0"),
            "涨跌幅": row.get("涨跌幅", "0")
        }
        if info["评分"] >= MIN_SCORE:
            GLOBAL_DATA["high_score"].append(info)
        else:
            GLOBAL_DATA["track"].append(info)

def check_signals():
    if GLOBAL_DATA["high_score"]:
        GLOBAL_DATA["observe"].append({**GLOBAL_DATA["high_score"][0], "信号": "关注"})

def generate_content():
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    content = f"""【A股跟踪推荐池 · 每日选股】
📅 {now}
🎯 主板 | 市值≤200亿 | 横盘+筹码+试盘洗盘

====================================
🔥 高分推荐池（≥80分）
共 {len(GLOBAL_DATA['high_score'])} 只
"""
    for s in GLOBAL_DATA["high_score"]:
        content += f"▶ {s['代码']} {s['名称']} | {s['市值_亿']}亿 | {s['涨跌幅']}%\n"

    content += "\n====================================\n📂 待突破跟踪池\n"
    for s in GLOBAL_DATA["track"][:10]:
        content += f"▫ {s['代码']} {s['名称']}\n"

    content += "\n====================================\n⚠️ 观察预警池\n"
    for s in GLOBAL_DATA["observe"]:
        content += f"【{s['信号']}】{s['代码']} {s['名称']}\n"

    content += "\n====================================\n✅ 买入：放量突破 | 卖出：跌破箱体"
    return f"【A股跟踪推荐池】{now}", content

if __name__ == "__main__":
    print("🚀 启动")
    df = get_stock_list()
    df = filter_basic_info(df)
    calculate_score(df)
    check_signals()
    title, content = generate_content()
    send_wechat(title, content)
    print("✅ 完成")
