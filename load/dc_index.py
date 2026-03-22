"""
加载东方财富概念板块每日快照数据（dc_index）到 PostgreSQL。

运行方式：
    # 拉取指定日期全量板块（行业+概念+地域）
    python -m load.dc_index --date 20250103

    # 拉取日期区间
    python -m load.dc_index --start 20250101 --end 20250131

    # 只拉取概念板块
    python -m load.dc_index --date 20250103 --idx-type 概念板块

注意：
    - idx_type 接口要求必填，本模块自动遍历全部类型（行业板块/概念板块/地域板块）
    - upsert 主键 (ts_code, trade_date)，安全可重跑
    - dc_member 和 dc_daily 可与本表通过 (ts_code, trade_date) 关联
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import argparse
from typing import Optional

from fetch.dc_index import fetch_dc_index, fetch_dc_index_date_range
from db import get_conn, upsert_df

TABLE = "dc_index"
CONFLICT_COLS = ["ts_code", "trade_date"]

KEEP_COLS = [
    "ts_code", "trade_date", "name", "leading", "leading_code",
    "pct_change", "leading_pct", "total_mv", "turnover_rate",
    "up_num", "down_num", "idx_type", "level",
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
    idx_type: Optional[str] = None,
) -> int:
    """
    拉取并写入单日全量板块快照。

    参数
    ----
    trade_date : 交易日期，格式 YYYYMMDD
    idx_type   : 板块类型（行业板块/概念板块/地域板块），None = 全部
    """
    tag = f"{trade_date}" + (f" idx_type={idx_type}" if idx_type else "")
    df = fetch_dc_index(trade_date=trade_date, idx_type=idx_type)
    return _upsert(df, tag)


def load_date_range(
    start_date: str,
    end_date: Optional[str] = None,
    idx_type: Optional[str] = None,
) -> int:
    """
    拉取并写入日期区间内的板块快照数据。

    参数
    ----
    start_date : 开始日期，格式 YYYYMMDD
    end_date   : 结束日期，格式 YYYYMMDD；不填则使用今日
    idx_type   : 板块类型，None = 全部
    """
    df = fetch_dc_index_date_range(start_date, end_date, idx_type=idx_type)
    if df.empty:
        print(f"[{TABLE}] 区间内无数据。")
        return 0
    n = upsert_df(df[[c for c in KEEP_COLS if c in df.columns]], TABLE, CONFLICT_COLS)
    print(f"[{TABLE}] 区间全部完成，共 upsert {n} 行。")
    return n


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="加载东方财富板块快照数据到数据库")
    parser.add_argument("--date",     help="单日，格式 YYYYMMDD")
    parser.add_argument("--start",    help="开始日期，格式 YYYYMMDD")
    parser.add_argument("--end",      help="结束日期，格式 YYYYMMDD（不填则今日）")
    parser.add_argument("--idx-type", dest="idx_type",
                        choices=["行业板块", "概念板块", "地域板块"],
                        help="板块类型（不填则拉全部）")
    args = parser.parse_args()

    if args.date:
        load_date(args.date, args.idx_type)
    elif args.start:
        load_date_range(args.start, args.end, args.idx_type)
    else:
        parser.print_help()
        sys.exit(1)
