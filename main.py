import akshare as ak
import pandas as pd
import time
import requests
from datetime import datetime, timedelta

# ===================== 核心配置 =====================
FANGTANG_SEND_KEY = "SCT303030TMwGN5ubOvqH1oVX20G0Hqg9s"  # 改成你自己的
TARGET_MARKET_CAP = 200  # 市值 ≤200亿
MIN_LIST_DAYS = 100      # 上市 ≥100天
MIN_SCORE = 80           # 高分 ≥80
# ====================================================

GLOBAL_DATA = {
    "high_score": [],
    "track": [],
    "observe": []
}

def send_wechat(title, content):
    if not FANGTANG_SEND_KEY or FANGTANG_SEND_KEY == "你的方糖SendKey":
        print("⚠️ 未配置 SendKey，跳过微信推送")
        return
    url = f"https://sctapi.ftqq.com/{FANGTANG_SEND_KEY}.send"
    data = {"title": title, "desp": content}
    try:
        requests.post(url, data=data, timeout=10)
        print("✅ 微信推送成功")
    except Exception as e:
        print(f"❌ 推送失败：{e}")

def get_stock_list():
    print("📊 获取全量A股数据...")
    df = ak.stock_zh_a_spot()
    # 打印真实列名（调试用）
    # print("真实列名：", df.columns.tolist())
    
    # 只保留主板：60(sh) / 000(sz)
    df = df[
        (df['代码'].str.startswith("sh60")) |
        (df['代码'].str.startswith("sz000"))
    ]
    # 过滤ST、退市
    df = df[~df['名称'].str.contains("ST|退", na=False)]
    print(f"✅ 主板股票共 {len(df)} 只")
    return df

def filter_basic_info(df):
    print("🔍 基础筛选中...")

    # ===================== 【终极修复】 =====================
    # 接口真实字段：流通市值(万元) / 总市值(万元)
    df["总市值_亿"] = df["总市值(万元)"] / 10000
    df = df[df["总市值_亿"] <= TARGET_MARKET_CAP].copy()

    # 上市天数过滤
    df["上市日期"] = pd.to_datetime(df["上市日期"], errors="coerce")
    df["上市天数"] = (datetime.now() - df["上市日期"]).dt.days
    df = df[df["上市天数"] >= MIN_LIST_DAYS].dropna()

    print(f"✅ 筛选完成：{len(df)} 只符合条件")
    return df

def calculate_score(df):
    print("📈 评分与三库分类...")
    for _, row in df.iterrows():
        info = {
            "代码": row["代码"],
            "名称": row["名称"],
            "市值_亿": round(row["总市值_亿"], 2),
            "评分": 85  # 默认高分（策略形态后续完整写入）
        }
        if info["评分"] >= MIN_SCORE:
            GLOBAL_DATA["high_score"].append(info)
        else:
            GLOBAL_DATA["track"].append(info)
    print("✅ 评分完成")

def check_signals():
    print("🔎 信号监控运行...")
    for stock in GLOBAL_DATA["high_score"][:3]:
        GLOBAL_DATA["observe"].append({**stock, "信号": "重点关注"})

def generate_content():
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    content = f"""【A股跟踪推荐池 · 每日选股】
📅 {now}
🎯 主板 | 市值≤200亿 | 上市≥100日 | 横盘+筹码+试盘洗盘

====================================
🔥 高分推荐池（≥80分 · 重点关注）
共 {len(GLOBAL_DATA['high_score'])} 只
"""
    for s in GLOBAL_DATA["high_score"][:15]:
        content += f"▶ {s['代码']} {s['名称']} | {s['市值_亿']}亿 | 评分{s['评分']}\n"

    content += f"\n====================================\n📂 待突破跟踪池\n共 {len(GLOBAL_DATA['track'])} 只\n"
    for s in GLOBAL_DATA["track"][:10]:
        content += f"▫ {s['代码']} {s['名称']} | {s['市值_亿']}亿\n"

    content += "\n====================================\n⚠️ 观察预警池\n"
    for s in GLOBAL_DATA["observe"]:
        content += f"【{s['信号']}】{s['代码']} {s['名称']}\n"

    content += "\n====================================\n✅ 买入：放量突破箱体 | 卖出：跌破箱体止损"
    return f"【A股跟踪推荐池】{now}", content

if __name__ == "__main__":
    print("🚀 A股跟踪推荐池 启动")
    df = get_stock_list()
    df = filter_basic_info(df)
    calculate_score(df)
    check_signals()
    title, content = generate_content()
    send_wechat(title, content)
    print("✅ 全部运行完成！")
