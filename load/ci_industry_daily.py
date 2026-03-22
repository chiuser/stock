"""
加载中信行业指数日线行情（ci_industry_daily）到 PostgreSQL。

运行方式：
    # 拉取单个交易日所有中信行业指数（日常更新，1次API）
    python -m load.ci_industry_daily --date 20230705

    # 按日期区间逐日拉取（补少量缺失日期）
    python -m load.ci_industry_daily --start 20230701 --end 20230731

    # 历史全量回填（按代码逐个拉取，API 调用次数少，推荐首次导入）
    python -m load.ci_industry_daily --backfill

    # 历史全量回填，限定日期范围
    python -m load.ci_industry_daily --backfill --start 20200101 --end 20231231

    # 指定代码回填
    python -m load.ci_industry_daily --codes CI005001.CI CI005002.CI --start 20200101

注意：
    - 日常更新（--date）只需 1 次 API，拉取当日全部中信行业行情（约 440 条）
    - --backfill 模式从 ci_industry_member 读取全量 CI 代码（需先有成分数据）
    - upsert 主键 (ts_code, trade_date)，安全可重跑
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import argparse
import datetime
from typing import Optional

from fetch.ci_industry_daily import (
    fetch_ci_daily_by_date,
    fetch_ci_daily_by_code,
    fetch_ci_daily_all_codes,
)
from db import get_conn, upsert_df

TABLE = "ci_industry_daily"
CONFLICT_COLS = ["ts_code", "trade_date"]

KEEP_COLS = [
    "ts_code", "trade_date",
    "open", "low", "high", "close", "pre_close",
    "change", "pct_change",
    "vol", "amount",
]


def _upsert(df, tag: str = "") -> int:
    if df.empty:
        print(f"[{TABLE}]{f' {tag}' if tag else ''} 无数据，跳过。")
        return 0
    cols = [c for c in KEEP_COLS if c in df.columns]
    n = upsert_df(df[cols], TABLE, CONFLICT_COLS)
    print(f"[{TABLE}]{f' {tag}' if tag else ''} upsert {n} 行。")
    return n


def _get_ci_codes() -> list[str]:
    """从 ci_industry_member 读取全量中信行业指数代码（L1+L2+L3 去重）。"""
    sql = """
        SELECT DISTINCT code FROM (
            SELECT l1_code AS code FROM ci_industry_member WHERE l1_code IS NOT NULL
            UNION
            SELECT l2_code FROM ci_industry_member WHERE l2_code IS NOT NULL
            UNION
            SELECT l3_code FROM ci_industry_member WHERE l3_code IS NOT NULL
        ) t
        ORDER BY code
    """
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchall()
        return [r[0] for r in rows]
    except Exception as e:
        print(f"[{TABLE}] 读取 ci_industry_member 失败：{e}")
        return []


def load_date(trade_date: str) -> int:
    """拉取单个交易日所有中信行业指数行情（1 次 API）。"""
    print(f"[{TABLE}] 拉取 {trade_date} 所有行业行情...")
    df = fetch_ci_daily_by_date(trade_date)
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
    codes      : 代码列表；为 None 时从 ci_industry_member 读取全量 CI 代码
    start_date : 开始日期 YYYYMMDD
    end_date   : 结束日期 YYYYMMDD
    sleep_sec  : 两次 API 调用间隔秒数
    """
    if codes is None:
        codes = _get_ci_codes()
        if not codes:
            print(f"[{TABLE}] 未找到中信行业代码。"
                  "请先运行：python pipeline.py --table ci_industry_member")
            return 0

    print(f"[{TABLE}] 开始回填，共 {len(codes)} 个代码，"
          f"区间 {start_date or '历史最早'} ~ {end_date or '今日'}...")
    df = fetch_ci_daily_all_codes(codes, start_date=start_date,
                                  end_date=end_date, sleep_sec=sleep_sec)
    return _upsert(df, f"{start_date or '全量'}~{end_date or '今日'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="加载中信行业指数日线行情到数据库")
    parser.add_argument("--date",     help="单日 YYYYMMDD（日常更新推荐）")
    parser.add_argument("--start",    help="开始日期 YYYYMMDD")
    parser.add_argument("--end",      help="结束日期 YYYYMMDD")
    parser.add_argument("--backfill", action="store_true",
                        help="历史回填模式（按代码逐个拉取，从 ci_industry_member 取代码列表）")
    parser.add_argument("--codes",    nargs="+", metavar="CODE",
                        help="指定行业代码，如 CI005001.CI CI005002.CI")
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
