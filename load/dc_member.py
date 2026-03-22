"""
加载东方财富板块成分股数据（dc_member）到 PostgreSQL。

运行方式：
    # 拉取指定日期全量成分（数据量大，约数万条）
    python -m load.dc_member --date 20250102

    # 拉取指定板块的成分
    python -m load.dc_member --date 20250102 --ts-code BK1184.DC

    # 拉取日期区间（逐日，建议指定板块代码限制数据量）
    python -m load.dc_member --start 20250101 --end 20250131 --ts-code BK1184.DC

注意：
    - upsert 主键 (trade_date, ts_code, con_code)，安全可重跑
    - 成分可每日变动，本表保存完整历史快照
    - 全量拉取（不指定板块）单日数据量极大（所有板块×成分数），慎用
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import argparse
from typing import Optional

from fetch.dc_member import fetch_dc_member, fetch_dc_member_date_range
from db import get_conn, upsert_df

TABLE = "dc_member"
CONFLICT_COLS = ["trade_date", "ts_code", "con_code"]

KEEP_COLS = ["trade_date", "ts_code", "con_code", "name"]


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
    ts_code: Optional[str] = None,
) -> int:
    """
    拉取并写入单日板块成分数据。

    参数
    ----
    trade_date : 交易日期，格式 YYYYMMDD
    ts_code    : 板块代码，None = 全量（数据量大）
    """
    tag = f"{trade_date}" + (f" ts_code={ts_code}" if ts_code else " 全量")
    df = fetch_dc_member(trade_date=trade_date, ts_code=ts_code)
    return _upsert(df, tag)


def load_date_range(
    start_date: str,
    end_date: Optional[str] = None,
    ts_code: Optional[str] = None,
    sleep_sec: float = 0.5,
) -> int:
    """
    拉取并写入日期区间内的板块成分数据。

    参数
    ----
    start_date : 开始日期，格式 YYYYMMDD
    end_date   : 结束日期，格式 YYYYMMDD；不填则使用今日
    ts_code    : 板块代码，None = 全量
    sleep_sec  : 逐日请求间隔秒数
    """
    df = fetch_dc_member_date_range(start_date, end_date, ts_code=ts_code, sleep_sec=sleep_sec)
    if df.empty:
        print(f"[{TABLE}] 区间内无数据。")
        return 0
    n = upsert_df(df[[c for c in KEEP_COLS if c in df.columns]], TABLE, CONFLICT_COLS)
    print(f"[{TABLE}] 区间全部完成，共 upsert {n} 行。")
    return n


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="加载东方财富板块成分股数据到数据库")
    parser.add_argument("--date",     help="单日，格式 YYYYMMDD")
    parser.add_argument("--start",    help="开始日期，格式 YYYYMMDD")
    parser.add_argument("--end",      help="结束日期，格式 YYYYMMDD（不填则今日）")
    parser.add_argument("--ts-code",  dest="ts_code", help="板块代码，如 BK1184.DC（不填则全量）")
    parser.add_argument("--sleep",    type=float, default=0.5,
                        help="逐日请求间隔秒数（默认 0.5）")
    args = parser.parse_args()

    if args.date:
        load_date(args.date, args.ts_code)
    elif args.start:
        load_date_range(args.start, args.end, ts_code=args.ts_code, sleep_sec=args.sleep)
    else:
        parser.print_help()
        sys.exit(1)
