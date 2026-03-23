"""
加载开盘啦涨跌停榜单（kpl_list）到 PostgreSQL。

运行方式：
    # 拉取单日全部 tag（涨停/炸板/跌停/自然涨停/竞价）
    python -m load.kpl_list --date 20240927

    # 拉取单日指定 tag
    python -m load.kpl_list --date 20240927 --tag 涨停 跌停

    # 拉取日期区间（默认全部 tag）
    python -m load.kpl_list --start 20240901 --end 20240930

    # 拉取日期区间，只拉涨停和跌停
    python -m load.kpl_list --start 20240901 --end 20240930 --tag 涨停 跌停

注意：
    - 每次 API 调用只能传递一个 tag，本模块会循环调用
    - upsert 主键 (ts_code, trade_date, tag)，安全可重跑
    - 数据更新时间为次日 8:30，当日数据需次日方可拉取
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import argparse
import datetime
from typing import Optional

from fetch.kpl_list import fetch_by_date, fetch_range, ALL_TAGS
from db import upsert_df

TABLE = "kpl_list"
CONFLICT_COLS = ["ts_code", "trade_date", "tag"]

KEEP_COLS = [
    "ts_code", "trade_date", "tag",
    "name", "lu_time", "ld_time", "open_time", "last_time",
    "lu_desc", "theme",
    "net_change", "bid_amount", "status",
    "bid_change", "bid_turnover", "lu_bid_vol",
    "pct_chg", "bid_pct_chg", "rt_pct_chg",
    "limit_order", "amount", "turnover_rate",
    "free_float", "lu_limit_order",
]


def _upsert(df, label: str = "") -> int:
    if df.empty:
        print(f"[{TABLE}]{f' {label}' if label else ''} 无数据，跳过。")
        return 0
    cols = [c for c in KEEP_COLS if c in df.columns]
    n = upsert_df(df[cols], TABLE, CONFLICT_COLS)
    print(f"[{TABLE}]{f' {label}' if label else ''} upsert {n} 行。")
    return n


def load_date(
    trade_date: str,
    tags: Optional[list[str]] = None,
) -> int:
    """
    拉取单个交易日的开盘啦榜单。

    参数
    ----
    trade_date : YYYYMMDD
    tags       : 要拉取的 tag 列表，默认全部 5 种
    """
    tag_list = tags or ALL_TAGS
    total = 0
    for tag in tag_list:
        print(f"[{TABLE}] 拉取 {trade_date} {tag}...")
        df = fetch_by_date(trade_date, tag=tag)
        total += _upsert(df, f"{trade_date} {tag}")
    return total


def load_date_range(
    start_date: str,
    end_date: Optional[str] = None,
    tags: Optional[list[str]] = None,
) -> int:
    """
    按日期区间拉取开盘啦榜单（每个 tag 独立分批拉取）。

    参数
    ----
    start_date : YYYYMMDD
    end_date   : YYYYMMDD（默认今日）
    tags       : 要拉取的 tag 列表，默认全部 5 种
    """
    tag_list = tags or ALL_TAGS
    today = datetime.date.today().strftime("%Y%m%d")
    end = end_date or today

    total = 0
    for tag in tag_list:
        print(f"\n[{TABLE}] 区间 {start_date}~{end} {tag}...")
        df = fetch_range(start_date, end_date=end, tag=tag)
        total += _upsert(df, f"{start_date}~{end} {tag}")

    print(f"[{TABLE}] 全部 tag 完成，共 upsert {total} 行。")
    return total


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="加载开盘啦涨跌停榜单到数据库")
    parser.add_argument("--date",  help="单日 YYYYMMDD")
    parser.add_argument("--start", help="开始日期 YYYYMMDD")
    parser.add_argument("--end",   help="结束日期 YYYYMMDD")
    parser.add_argument(
        "--tag", nargs="+", dest="tag",
        choices=ALL_TAGS,
        metavar="TAG",
        help=f"板单类型（可多选），默认全部。可选：{' | '.join(ALL_TAGS)}",
    )
    args = parser.parse_args()

    if args.date:
        load_date(args.date, tags=args.tag)
    elif args.start:
        load_date_range(args.start, end_date=args.end, tags=args.tag)
    else:
        parser.print_help()
        sys.exit(1)
