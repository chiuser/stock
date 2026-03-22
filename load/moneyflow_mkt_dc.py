"""
加载东财大盘资金流向数据（moneyflow_mkt_dc）到 PostgreSQL。

运行方式：
    # 拉取单日
    python -m load.moneyflow_mkt_dc --date 20240927

    # 拉取日期区间
    python -m load.moneyflow_mkt_dc --start 20240901 --end 20240930

    # 全量历史（数据量小，推荐一次性导入）
    python -m load.moneyflow_mkt_dc --start 20230911

注意：
    - 金额单位为元，每日一行，数据量极小
    - upsert 主键 trade_date，安全可重跑
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import argparse
from fetch.moneyflow_mkt_dc import fetch_moneyflow_mkt_dc
from db import get_conn, upsert_df

TABLE = "moneyflow_mkt_dc"
CONFLICT_COLS = ["trade_date"]


def load_date(trade_date: str) -> int:
    df = fetch_moneyflow_mkt_dc(trade_date=trade_date)
    if df.empty:
        print(f"[{TABLE}] {trade_date} 返回空数据，跳过。")
        return 0
    n = upsert_df(df, TABLE, CONFLICT_COLS)
    print(f"[{TABLE}] {trade_date} upsert {n} 行。")
    return n


def load_date_range(start_date: str, end_date: str | None = None) -> int:
    df = fetch_moneyflow_mkt_dc(start_date=start_date, end_date=end_date or "")
    if df.empty:
        print(f"[{TABLE}] 区间内无数据。")
        return 0
    n = upsert_df(df, TABLE, CONFLICT_COLS)
    print(f"[{TABLE}] 全部完成，共 upsert {n} 行。")
    return n


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="加载东财大盘资金流向到数据库")
    parser.add_argument("--date",  help="单日，格式 YYYYMMDD")
    parser.add_argument("--start", help="开始日期，格式 YYYYMMDD")
    parser.add_argument("--end",   help="结束日期，格式 YYYYMMDD（不填则今日）")
    args = parser.parse_args()

    if args.date:
        load_date(args.date)
    elif args.start:
        load_date_range(args.start, args.end)
    else:
        parser.print_help()
        sys.exit(1)
