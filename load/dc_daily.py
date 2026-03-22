"""
加载东方财富板块行情数据（dc_daily）到 PostgreSQL。

运行方式：
    # 拉取指定日期全量板块行情（日常更新，推荐）
    python -m load.dc_daily --date 20250513

    # 拉取日期区间（逐日）
    python -m load.dc_daily --start 20250101 --end 20250131

    # 历史回填：从 dc_index 读取板块代码逐个拉取历史（首次导入推荐）
    python -m load.dc_daily --backfill --start 20200101

    # 单个板块历史回填
    python -m load.dc_daily --ts-code BK1063.DC --start 20200101

注意：
    - 历史数据起始于 2020 年
    - upsert 主键 (ts_code, trade_date)，安全可重跑
    - --backfill 模式依赖 dc_index 表中已有的板块代码，请先运行 dc_index
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import argparse
from typing import Optional

from fetch.dc_daily import (
    fetch_dc_daily,
    fetch_dc_daily_by_date,
    fetch_dc_daily_by_code,
    fetch_dc_daily_date_range,
    fetch_dc_daily_all_codes,
)
from db import get_conn, upsert_df

TABLE = "dc_daily"
CONFLICT_COLS = ["ts_code", "trade_date"]

KEEP_COLS = [
    "ts_code", "trade_date",
    "open", "high", "low", "close",
    "change", "pct_change",
    "vol", "amount",
    "swing", "turnover_rate",
]


def _upsert(df, tag: str = "") -> int:
    if df.empty:
        print(f"[{TABLE}]{f' {tag}' if tag else ''} 无数据，跳过。")
        return 0
    cols = [c for c in KEEP_COLS if c in df.columns]
    n = upsert_df(df[cols], TABLE, CONFLICT_COLS)
    print(f"[{TABLE}]{f' {tag}' if tag else ''} upsert {n} 行。")
    return n


def load_date(trade_date: str) -> int:
    """
    拉取并写入单日全量板块行情（日常更新推荐）。

    参数
    ----
    trade_date : 交易日期，格式 YYYYMMDD
    """
    df = fetch_dc_daily_by_date(trade_date)
    return _upsert(df, trade_date)


def load_date_range(
    start_date: str,
    end_date: Optional[str] = None,
) -> int:
    """
    拉取并写入日期区间内的板块行情数据（逐日）。

    参数
    ----
    start_date : 开始日期，格式 YYYYMMDD
    end_date   : 结束日期，格式 YYYYMMDD；不填则使用今日
    """
    df = fetch_dc_daily_date_range(start_date, end_date)
    if df.empty:
        print(f"[{TABLE}] 区间内无数据。")
        return 0
    n = upsert_df(df[[c for c in KEEP_COLS if c in df.columns]], TABLE, CONFLICT_COLS)
    print(f"[{TABLE}] 区间全部完成，共 upsert {n} 行。")
    return n


def load_by_code(
    ts_code: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> int:
    """
    拉取并写入指定板块的历史行情。

    参数
    ----
    ts_code    : 板块代码，如 'BK1063.DC'
    start_date : 开始日期，格式 YYYYMMDD
    end_date   : 结束日期，格式 YYYYMMDD
    """
    df = fetch_dc_daily_by_code(ts_code, start_date=start_date, end_date=end_date)
    return _upsert(df, f"{ts_code}")


def load_backfill(
    codes: Optional[list] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    sleep_sec: float = 0.3,
) -> int:
    """
    历史回填：从 dc_index 读取板块代码，逐个拉取历史行情写库。

    参数
    ----
    codes      : 板块代码列表，None = 从 dc_index 读取全量
    start_date : 开始日期，格式 YYYYMMDD（历史起始 20200101）
    end_date   : 结束日期，格式 YYYYMMDD
    sleep_sec  : 每个板块之间的等待秒数
    """
    import time

    if codes:
        all_codes = codes
    else:
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT DISTINCT ts_code FROM dc_index ORDER BY ts_code")
                    all_codes = [r[0] for r in cur.fetchall()]
        except Exception as e:
            print(f"[{TABLE}] 读取板块代码失败：{e}")
            return 0

    if not all_codes:
        print(f"[{TABLE}] dc_index 表为空，请先执行 dc_index 更新。")
        return 0

    print(f"[{TABLE}] 共 {len(all_codes)} 个板块，开始历史回填...")
    total = 0
    for i, code in enumerate(all_codes, 1):
        print(f"[{TABLE}] ({i}/{len(all_codes)}) {code} ...")
        try:
            df = fetch_dc_daily_by_code(code, start_date=start_date, end_date=end_date)
            if not df.empty:
                cols = [c for c in KEEP_COLS if c in df.columns]
                n = upsert_df(df[cols], TABLE, CONFLICT_COLS)
                total += n
                print(f"[{TABLE}] {code} upsert {n} 行。")
        except Exception as e:
            print(f"[{TABLE}] {code} 出错：{e}")
        if sleep_sec > 0:
            time.sleep(sleep_sec)

    print(f"[{TABLE}] 历史回填完成，共 upsert {total} 行。")
    return total


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="加载东方财富板块行情数据到数据库")
    parser.add_argument("--date",     help="单日，格式 YYYYMMDD")
    parser.add_argument("--start",    help="开始日期，格式 YYYYMMDD")
    parser.add_argument("--end",      help="结束日期，格式 YYYYMMDD（不填则今日）")
    parser.add_argument("--ts-code",  dest="ts_code", help="指定板块代码（用于单板块历史回填）")
    parser.add_argument("--backfill", action="store_true",
                        help="历史回填模式：从 dc_index 读取全量板块代码逐个拉取")
    parser.add_argument("--sleep",    type=float, default=0.3,
                        help="历史回填每个板块间隔秒数（默认 0.3）")
    args = parser.parse_args()

    if args.date:
        load_date(args.date)
    elif args.ts_code and not args.backfill:
        load_by_code(args.ts_code, start_date=args.start, end_date=args.end)
    elif args.backfill:
        load_backfill(start_date=args.start, end_date=args.end, sleep_sec=args.sleep)
    elif args.start:
        load_date_range(args.start, args.end)
    else:
        parser.print_help()
        sys.exit(1)
