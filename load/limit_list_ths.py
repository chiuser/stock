"""
加载同花顺涨跌停榜单（limit_list_ths）到 PostgreSQL。

运行方式：
    # 拉取单日全部类型（涨停池/连板池/冲刺涨停/炸板池/跌停池）
    python -m load.limit_list_ths --date 20241125

    # 拉取单日指定类型
    python -m load.limit_list_ths --date 20241125 --limit-type 涨停池 连板池

    # 拉取日期区间（默认全部类型）
    python -m load.limit_list_ths --start 20241101 --end 20241130

    # 拉取日期区间，只拉涨停池和跌停池
    python -m load.limit_list_ths --start 20241101 --end 20241130 --limit-type 涨停池 跌停池

注意：
    - 每次 API 调用只能传递一个 limit_type，本模块会循环调用
    - upsert 主键 (trade_date, ts_code, limit_type)，安全可重跑
    - 历史数据从 20231101 开始提供
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import argparse
import datetime
from typing import Optional

from fetch.limit_list_ths import (
    fetch_limit_list_by_date,
    fetch_limit_list_range,
    ALL_LIMIT_TYPES,
)
from db import upsert_df

TABLE = "limit_list_ths"
CONFLICT_COLS = ["trade_date", "ts_code", "limit_type"]

KEEP_COLS = [
    "trade_date", "ts_code", "limit_type",
    "name", "price", "pct_chg", "open_num", "lu_desc", "tag", "status",
    "first_lu_time", "last_lu_time", "first_ld_time", "last_ld_time",
    "limit_order", "limit_amount", "turnover_rate", "free_float",
    "lu_limit_order", "limit_up_suc_rate", "turnover",
    "rise_rate", "sum_float", "market_type",
]


def _upsert(df, tag: str = "") -> int:
    if df.empty:
        print(f"[{TABLE}]{f' {tag}' if tag else ''} 无数据，跳过。")
        return 0
    cols = [c for c in KEEP_COLS if c in df.columns]
    n = upsert_df(df[cols], TABLE, CONFLICT_COLS)
    print(f"[{TABLE}]{f' {tag}' if tag else ''} upsert {n} 行。")
    return n


def load_date(
    trade_date: str,
    limit_types: Optional[list[str]] = None,
) -> int:
    """
    拉取单个交易日的涨跌停榜单。

    参数
    ----
    trade_date  : YYYYMMDD
    limit_types : 要拉取的类型列表，默认全部 5 种类型
    """
    types = limit_types or ALL_LIMIT_TYPES
    total = 0
    for lt in types:
        print(f"[{TABLE}] 拉取 {trade_date} {lt}...")
        df = fetch_limit_list_by_date(trade_date, limit_type=lt)
        total += _upsert(df, f"{trade_date} {lt}")
    return total


def load_date_range(
    start_date: str,
    end_date: Optional[str] = None,
    limit_types: Optional[list[str]] = None,
) -> int:
    """
    按日期区间拉取涨跌停榜单。

    参数
    ----
    start_date  : YYYYMMDD
    end_date    : YYYYMMDD（默认今日）
    limit_types : 要拉取的类型列表，默认全部 5 种
    """
    types = limit_types or ALL_LIMIT_TYPES
    today = datetime.date.today().strftime("%Y%m%d")
    end = end_date or today

    total = 0
    for lt in types:
        print(f"\n[{TABLE}] 区间 {start_date}~{end} {lt}...")
        df = fetch_limit_list_range(start_date, end_date=end, limit_type=lt)
        total += _upsert(df, f"{start_date}~{end} {lt}")

    print(f"[{TABLE}] 全部类型完成，共 upsert {total} 行。")
    return total


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="加载同花顺涨跌停榜单到数据库")
    parser.add_argument("--date",       help="单日 YYYYMMDD")
    parser.add_argument("--start",      help="开始日期 YYYYMMDD")
    parser.add_argument("--end",        help="结束日期 YYYYMMDD")
    parser.add_argument(
        "--limit-type", nargs="+", dest="limit_type",
        choices=ALL_LIMIT_TYPES,
        metavar="TYPE",
        help=f"板单类型（可多选），默认全部。可选：{' | '.join(ALL_LIMIT_TYPES)}",
    )
    args = parser.parse_args()

    if args.date:
        load_date(args.date, limit_types=args.limit_type)
    elif args.start:
        load_date_range(args.start, end_date=args.end, limit_types=args.limit_type)
    else:
        parser.print_help()
        sys.exit(1)
