"""
接口字段探查：打印各接口实际返回的所有列名和数据类型。

运行方式：
    python example.py

用于在建表前确认各接口的完整字段列表。
"""

import tushare as ts
from config import TUSHARE_TOKEN

ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()


def inspect(name, fn):
    print(f"\n{'='*60}")
    print(f"[字段探查] {name}")
    print("-" * 60)
    try:
        df = fn()
        if df is None or df.empty:
            print("  返回空数据，无法探查字段")
            return
        print(f"  共 {len(df.columns)} 个字段:")
        for col in df.columns:
            sample = df[col].iloc[0] if len(df) > 0 else "N/A"
            print(f"    {col:<25} dtype={str(df[col].dtype):<12} 示例={sample}")
        print(f"\n  前2行数据:")
        print(df.head(2).to_string(index=False))
    except Exception as e:
        print(f"  错误: {e}")


# 1. 股票基本资料 —— 不指定 fields，获取所有字段
inspect(
    "stock_basic — 股票基本资料",
    lambda: pro.stock_basic(
        list_status="L",
        fields="ts_code,symbol,name,area,industry,cnspell,market,list_date,act_name,act_ent_type,fullname,enname,exchange,curr_type,list_status,delist_date,is_hs",
    ),
)

# 2. 指数基本资料
inspect(
    "index_basic — 指数基本资料",
    lambda: pro.index_basic(
        market="SSE",
        fields="ts_code,name,market,publisher,category,base_date,base_point,list_date,index_type,fullname,weight_rule,desc,exp_date",
    ),
)

# 3. 个股日线行情
inspect(
    "daily — 个股日线行情",
    lambda: pro.daily(ts_code="000001.SZ", start_date="20250101", end_date="20250110"),
)

# 4. 每日基本指标
inspect(
    "daily_basic — 每日基本指标",
    lambda: pro.daily_basic(ts_code="000001.SZ", trade_date="20250110"),
)

# 5. 指数日线行情
inspect(
    "index_daily — 指数日线行情",
    lambda: pro.index_daily(ts_code="000001.SH", start_date="20250101", end_date="20250110"),
)

# 6. 分钟K线（只探查1min，字段结构各频率相同）
inspect(
    "stk_mins — 分钟K线 freq=1min",
    lambda: pro.stk_mins(
        ts_code="000001.SZ",
        freq="1min",
        start_date="2025-01-06 09:00:00",
        end_date="2025-01-06 15:30:00",
    ),
)
