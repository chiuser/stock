"""
使用示例：获取指数日线行情数据
"""

from fetch import fetch_index_daily
from config import INDEX_CODES

# 获取上证指数最近一段时间的日线数据
df = fetch_index_daily(
    ts_code=INDEX_CODES["上证指数"],  # 000001.SH
    start_date="20250101",
    end_date="20250317",
)

print(f"获取到 {len(df)} 条数据")
print(df[["trade_date", "open", "high", "low", "close", "pct_chg", "vol"]].to_string(index=False))
