"""
加载 index_daily（指数日线行情）到远程 PostgreSQL。

运行方式：
    python -m load.index_daily --start 20240101 --end 20241231
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import argparse
import pandas as pd
from fetch import fetch_index_daily
from db import upsert_df
from config import INDEX_CODES

TABLE = "index_daily"
CONFLICT_COLS = ["ts_code", "trade_date"]


def load(
    ts_codes: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> int:
    """
    获取指数日线并写入 index_daily 表。

    参数
    ----
    ts_codes   : 指数代码列表；为 None 时使用 config.INDEX_CODES 全部指数
    start_date : 开始日期，格式 YYYYMMDD
    end_date   : 结束日期，格式 YYYYMMDD
    """
    if ts_codes is None:
        ts_codes = list(INDEX_CODES.values())

    total = 0
    for code in ts_codes:
        print(f"[index_daily] 拉取 {code}  {start_date or '历史最早'} ~ {end_date or '今日'}...")
        df = fetch_index_daily(code, start_date=start_date, end_date=end_date)
        if df.empty:
            print(f"[index_daily] {code} 返回空数据，跳过。")
            continue

        n = upsert_df(df, TABLE, CONFLICT_COLS)
        print(f"[index_daily] {code} upsert {n} 行。")
        total += n

    print(f"[index_daily] 全部完成，共 upsert {total} 行。")
    return total


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="加载指数日线到数据库")
    parser.add_argument("--codes",  nargs="+", help="指数代码，如 000001.SH 000300.SH")
    parser.add_argument("--start",  help="开始日期 YYYYMMDD")
    parser.add_argument("--end",    help="结束日期 YYYYMMDD")
    args = parser.parse_args()

    load(ts_codes=args.codes, start_date=args.start, end_date=args.end)
