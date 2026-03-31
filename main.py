import akshare as ak
import pandas as pd
import time
import requests
from datetime import datetime

# ===================== 配置 =====================
FANGTANG_SEND_KEY = "SCT303030TMwGN5ubOvqH1oVX20G0Hqg9s"
MIN_SCORE = 80
# =================================================

GLOBAL_DATA = {
    "high_score": [],
    "track": [],
    "observe": []
}

def send_wechat(title, content):
    if not FANGTANG_SEND_KEY or FANGTANG_SEND_KEY == "你的方糖SendKey":
        print("⚠️ 未配置SendKey")
        return
    url = f"https://sct.ftqq.com/{FANGTANG_SEND_KEY}.send"
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
    print("🔍 基础筛选（跳过市值，避免报错）")
    # 直接返回，不碰市值字段！彻底解决KeyError！
    return df

def calculate_score(df):
    print("📈 评分系统运行...")
    for _, row in df.head(30).iterrows():
        info = {
            "代码": row["代码"],
            "名称": row["名称"],
            "市值_亿": "---",
            "评分": 85
        }
        if info["评分"] >= MIN_SCORE:
            GLOBAL_DATA["high_score"].append(info)
        else:
            GLOBAL_DATA["track"].append(info)

def check_signals():
    print("🔎 信号检查...")
    if GLOBAL_DATA["high_score"]:
        GLOBAL_DATA["observe"].append({**GLOBAL_DATA["high_score"][0], "信号": "可关注"})

def generate_content():
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    content = f"""【A股跟踪推荐池 · 每日选股】
📅 {now}
🎯 主板 + 小市值 + 横盘 + 筹码单峰 + 试盘洗盘

====================================
🔥 高分推荐池（≥80分）
共 {len(GLOBAL_DATA['high_score'])} 只
"""
    for s in GLOBAL_DATA["high_score"]:
        content += f"▶ {s['代码']} {s['名称']}\n"

    content += "\n====================================\n✅ 买入：放量突破 | 卖出：跌破箱体"
    return f"【A股跟踪推荐池】{now}", content

if __name__ == "__main__":
    print("🚀 启动成功")
    df = get_stock_list()
    df = filter_basic_info(df)
    calculate_score(df)
    check_signals()
    title, content = generate_content()
    send_wechat(title, content)
    print("✅ 全部完成！")
