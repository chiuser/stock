"""
加载同花顺行业/概念板块指数日线行情（ths_daily）到 PostgreSQL。

运行方式：
    # 拉取单个交易日所有板块指数（日常更新，1次API）
    python -m load.ths_daily --date 20230705

    # 按日期区间逐日拉取（补少量缺失日期）
    python -m load.ths_daily --start 20230701 --end 20230731

    # 历史全量回填（按代码逐个拉取，API 调用次数少，推荐首次导入）
    python -m load.ths_daily --backfill

    # 历史全量回填，限定日期范围
    python -m load.ths_daily --backfill --start 20200101 --end 20231231

    # 指定代码回填
    python -m load.ths_daily --codes 885650.TI 885001.TI --start 20200101

注意：
    - 日常更新（--date）只需 1 次 API，拉取当日全部板块行情
    - --backfill 模式从 ths_index 读取全量代码（需先有板块基础数据）
    - upsert 主键 (ts_code, trade_date)，安全可重跑
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import argparse
import datetime
from typing import Optional

from fetch.ths_daily import (
    fetch_ths_daily_by_date,
    fetch_ths_daily_by_code,
    fetch_ths_daily_all_codes,
)
from load.ths_index import get_ths_codes
from db import upsert_df

TABLE = "ths_daily"
CONFLICT_COLS = ["ts_code", "trade_date"]

KEEP_COLS = [
    "ts_code", "trade_date",
    "open", "high", "low", "close", "pre_close",
    "change", "pct_chg",
    "avg_price", "turnover_rate",
    "total_mv", "float_mv",
    "vol", "amount",
    "up_count", "down_count",
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
    """拉取单个交易日所有同花顺板块指数行情（1 次 API）。"""
    print(f"[{TABLE}] 拉取 {trade_date} 所有板块行情...")
    df = fetch_ths_daily_by_date(trade_date)
    return _upsert(df, trade_date)


def load_date_range(
    start_date: str,
    end_date: Optional[str] = None,
) -> int:
    """
    按日期区间逐日拉取，适合补录少量缺失日期（≤30天区间）。
    """
    def _parse(d: str) -> datetime.date:
        return datetime.date(int(d[:4]), int(d[4:6]), int(d[6:]))

    today = datetime.date.today()
    end  = _parse(end_date) if end_date else today
    cur  = _parse(start_date)
    delta = datetime.timedelta(days=1)

    total = 0
    while cur <= end:
        d = cur.strftime("%Y%m%d")
        try:
            n = load_date(d)
            total += n
        except Exception as e:
            print(f"[{TABLE}] {d} 出错：{e}")
        cur += delta

    print(f"[{TABLE}] 区间 {start_date}~{end_date or today} 完成，共 upsert {total} 行。")
    return total


def load_backfill(
    codes: Optional[list[str]] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    sleep_sec: float = 0.3,
) -> int:
    """
    历史全量回填：按代码逐个拉取，API 调用次数少。
    推荐用于首次全量导入或大范围历史补录。

    参数
    ----
    codes      : 代码列表；为 None 时从 ths_index 读取全量板块代码
    start_date : 开始日期 YYYYMMDD
    end_date   : 结束日期 YYYYMMDD
    sleep_sec  : 两次 API 调用间隔秒数
    """
    if codes is None:
        codes = get_ths_codes()
        if not codes:
            print(f"[{TABLE}] 未找到同花顺板块代码。"
                  "请先运行：python pipeline.py --table ths_index")
            return 0

    print(f"[{TABLE}] 开始回填，共 {len(codes)} 个代码，"
          f"区间 {start_date or '历史最早'} ~ {end_date or '今日'}...")
    df = fetch_ths_daily_all_codes(codes, start_date=start_date,
                                   end_date=end_date, sleep_sec=sleep_sec)
    return _upsert(df, f"{start_date or '全量'}~{end_date or '今日'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="加载同花顺板块指数日线行情到数据库")
    parser.add_argument("--date",     help="单日 YYYYMMDD（日常更新推荐）")
    parser.add_argument("--start",    help="开始日期 YYYYMMDD")
    parser.add_argument("--end",      help="结束日期 YYYYMMDD")
    parser.add_argument("--backfill", action="store_true",
                        help="历史回填模式（按代码逐个拉取，从 ths_index 取代码列表）")
    parser.add_argument("--codes",    nargs="+", metavar="CODE",
                        help="指定板块代码，如 885650.TI 885001.TI")
    parser.add_argument("--sleep",    type=float, default=0.3,
                        help="回填模式 API 调用间隔秒数（默认 0.3）")
    args = parser.parse_args()

    if args.date:
        load_date(args.date)
    elif args.backfill or args.codes:
        load_backfill(
            codes=args.codes,
            start_date=args.start,
            end_date=args.end,
            sleep_sec=args.sleep,
        )
    elif args.start:
        load_date_range(args.start, args.end)
    else:
        parser.print_help()
        sys.exit(1)
