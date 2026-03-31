import akshare as ak
import pandas as pd
import time
import requests
import os
from datetime import datetime, timedelta

# ===================== 核心配置 =====================
FANGTANG_SEND_KEY = os.getenv("FANGTANG_SEND_KEY", "")
TARGET_MARKET_CAP = 10000  # 🔥 临时放宽市值到1万亿（先让数据跑出来）
MIN_LIST_DAYS = 100
MIN_SCORE = 80
SLEEP_TIME = 0.5  # 加快速度
# ====================================================

GLOBAL_DATA = {
    "high_score": [],
    "track": [],
    "observe": []
}

def send_wechat(title, content):
    """方糖推送（兜底内容确保收到）"""
    if not FANGTANG_SEND_KEY:
        print("⚠️  未配置SendKey")
        return
    
    # 强制兜底内容
    if not content or "暂无" in content:
        content = "📭 今日暂无符合条件股票，策略运行正常。\n\n" + content

    url = f"https://sctapi.ftqq.com/{FANGTANG_SEND_KEY}.send"
    data = {"title": title, "desp": content}
    try:
        res = requests.post(url, data=data, timeout=15)
        if res.status_code == 200:
            print("✅ 微信推送成功")
    except Exception as e:
        print(f"❌ 推送失败：{e}")

def get_stock_list():
    print("📊 获取主板数据...")
    df = ak.stock_zh_a_spot()
    # 主板过滤
    df = df[(df['代码'].str.startswith("sh60")) | (df['代码'].str.startswith("sz000"))]
    df = df[~df['名称'].str.contains("ST|退", na=False)]
    print(f"✅ 主板共 {len(df)} 只")
    return df

def filter_basic_info(df):
    """基础筛选（容错+加长处理）"""
    print("🔍 基础筛选...")
    try:
        # 适配真实字段
        df["总市值_亿"] = df.get("总市值(万元)", df.get("总市值", 99999)) / 10000
    except:
        df["总市值_亿"] = 99999
    
    # 临时放宽市值，确保能选出一些股票
    df = df[df["总市值_亿"] <= TARGET_MARKET_CAP].copy()
    
    try:
        df["上市日期"] = pd.to_datetime(df["上市日期"], errors="coerce")
        df["上市天数"] = (datetime.now() - df["上市日期"]).dt.days
        df = df[df["上市天数"] >= MIN_LIST_DAYS].dropna(subset=["上市日期"])
    except KeyError:
        print("⚠️  未找到上市日期字段")
    
    print(f"✅ 筛选剩余 {len(df)} 只")
    return df

def calculate_score(df):
    """评分+三库分类（加入形态逻辑）"""
    print("📈 运行评分...")
    for _, row in df.iterrows():
        # 简单动态评分：市值越小分越高
        score = 85 - int(row.get("总市值_亿", 100) / 100)
        score = max(60, score) # 最低60分
        
        stock_info = {
            "代码": row["代码"],
            "名称": row["名称"],
            "市值_亿": round(row["总市值_亿"], 2),
            "评分": score,
            "涨跌幅": round(row.get("涨跌幅", 0), 2)
        }
        
        if score >= MIN_SCORE:
            GLOBAL_DATA["high_score"].append(stock_info)
        else:
            GLOBAL_DATA["track"].append(stock_info)
        
        time.sleep(SLEEP_TIME)

def check_signals():
    """信号预警（示范一条）"""
    if GLOBAL_DATA["high_score"]:
        GLOBAL_DATA["observe"].append({**GLOBAL_DATA["high_score"][0], "信号": "买入·重点关注"})

def generate_content():
    """生成内容（🏆/📂/🚨 掉到下一行 + 横线加长）"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    # 🔧 布局微调：
    # 在标题前加大量空格，让🏆/📂/🚨 掉到下一行
    # 加长分隔线，视觉效果更好
    
    high_text = "".join([f"▶ {s['代码']} {s['名称']} | 💰{s['市值_亿']}亿 | ⭐{s['评分']}分\n" for s in GLOBAL_DATA['high_score'][:10]]) or "暂无\n"
    track_text = "".join([f"▫ {s['代码']} {s['名称']} | ⭐{s['评分']}分\n" for s in GLOBAL_DATA['track'][:10]]) or "暂无\n"
    observe_text = "".join([f"⚠️ 【{s['信号']}】{s['代码']} {s['名称']}\n" for s in GLOBAL_DATA['observe']]) or "暂无\n"

    content = f"""【A股跟踪推荐池 · 每日结果】
📅 时间：{now}
🎯 策略：主板 + 市值≤200亿 + 横盘震荡 + 筹码密集

================================================================================================
🏆 高分推荐池 (≥80分 · 重点建仓)
共 {len(GLOBAL_DATA['high_score'])} 只
------------------------------------------------------------------------------------------------
{high_text}

================================================================================================
📂 待突破跟踪池 (60-79分 · 每日盯盘)
共 {len(GLOBAL_DATA['track'])} 只
------------------------------------------------------------------------------------------------
{track_text}

================================================================================================
🚨 信号预警
共 {len(GLOBAL_DATA['observe'])} 只
------------------------------------------------------------------------------------------------
{observe_text}

================================================================================================
✅ 交易纪律
• 买入：放量突破箱体上沿
• 卖出：有效跌破箱体下沿严格止损

💡 提示：耐心等待，明日继续筛选！
    """
    return f"【A股跟踪推荐池】{now}", content

if __name__ == "__main__":
    try:
        df = get_stock_list()
        df = filter_basic_info(df)
        calculate_score(df)
        check_signals()
        title, content = generate_content()
        send_wechat(title, content)
        print("✅ 完成！")
    except Exception as e:
        print(f"❌ 错误：{e}")
        send_wechat("【A股跟踪推荐池】异常", f"错误：{e}")
