"""
加载东财个股资金流向数据（moneyflow_dc）到 PostgreSQL。

运行方式：
    # 拉取单日全市场
    python -m load.moneyflow_dc --date 20241011

    # 拉取日期区间（每日全市场，逐日循环）
    python -m load.moneyflow_dc --start 20230911 --end 20241231

    # 拉取单只股票的历史区间
    python -m load.moneyflow_dc --code 000001.SZ --start 20230911 --end 20241231

注意：
    - 数据起始日期为 20230911
    - upsert 主键 (trade_date, ts_code)，安全可重跑
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import argparse
from fetch.moneyflow_dc import fetch_moneyflow_dc, fetch_moneyflow_dc_date_range
from db import get_conn, upsert_df

TABLE = "moneyflow_dc"
CONFLICT_COLS = ["trade_date", "ts_code"]


def load_date(trade_date: str) -> int:
    df = fetch_moneyflow_dc(trade_date=trade_date)
    if df.empty:
        print(f"[{TABLE}] {trade_date} 返回空数据，跳过。")
        return 0
    n = upsert_df(df, TABLE, CONFLICT_COLS)
    print(f"[{TABLE}] {trade_date} upsert {n} 行。")
    return n


def load_date_range(start_date: str, end_date: str | None = None) -> int:
    df = fetch_moneyflow_dc_date_range(start_date, end_date)
    if df.empty:
        print(f"[{TABLE}] 区间内无数据。")
        return 0
    n = upsert_df(df, TABLE, CONFLICT_COLS)
    print(f"[{TABLE}] 全部完成，共 upsert {n} 行。")
    return n


def load_code_range(ts_code: str, start_date: str, end_date: str | None = None) -> int:
    df = fetch_moneyflow_dc(ts_code=ts_code, start_date=start_date, end_date=end_date or "")
    if df.empty:
        print(f"[{TABLE}] {ts_code} 返回空数据，跳过。")
        return 0
    n = upsert_df(df, TABLE, CONFLICT_COLS)
    print(f"[{TABLE}] {ts_code} upsert {n} 行。")
    return n


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="加载东财个股资金流向到数据库")
    parser.add_argument("--date",  help="单日，格式 YYYYMMDD")
    parser.add_argument("--start", help="开始日期，格式 YYYYMMDD")
    parser.add_argument("--end",   help="结束日期，格式 YYYYMMDD（不填则今日）")
    parser.add_argument("--code",  help="单只股票代码，如 000001.SZ（需配合 --start）")
    args = parser.parse_args()

    if args.date:
        load_date(args.date)
    elif args.code and args.start:
        load_code_range(args.code, args.start, args.end)
    elif args.start:
        load_date_range(args.start, args.end)
    else:
        parser.print_help()
        sys.exit(1)
