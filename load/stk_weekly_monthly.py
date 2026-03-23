"""
加载个股周线/月线行情到 PostgreSQL。

运行方式：
    # 拉取全市场周线（从 start 到 end，按周分段请求）
    python -m load.stk_weekly_monthly --freq week --start 20190101 --end 20250826

    # 拉取全市场月线
    python -m load.stk_weekly_monthly --freq month --start 20190101 --end 20250826

    # 仅拉取指定股票的周线（按股票代码逐只请求）
    python -m load.stk_weekly_monthly --freq week --code 000001.SZ 600519.SH

    # 同时拉取周线和月线
    python -m load.stk_weekly_monthly --freq week month --start 20190101
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import argparse
import time
from datetime import datetime, timedelta
from fetch.stk_weekly_monthly import fetch_stk_weekly_monthly
from db import get_conn, upsert_df

# freq → 目标表名
_TABLE = {
    "week":  "stock_weekly",
    "month": "stock_monthly",
}
CONFLICT_COLS = ["ts_code", "trade_date"]

# 每段覆盖的天数：周线 7 天（约 1 周），月线 31 天（约 1 月）
# 确保全市场（~5000只）单次返回行数不超过接口上限 6000 行
_CHUNK_DAYS = {
    "week": 7,
    "month": 31,
}


def _date_chunks(start: str, end: str, days: int):
    """将 [start, end] 日期区间按 days 天切分，yield (chunk_start, chunk_end) 字符串对。"""
    s = datetime.strptime(start, "%Y%m%d")
    e = datetime.strptime(end, "%Y%m%d")
    while s <= e:
        chunk_end = min(s + timedelta(days=days - 1), e)
        yield s.strftime("%Y%m%d"), chunk_end.strftime("%Y%m%d")
        s += timedelta(days=days)


def _load_by_date_range(
    freq: str,
    start_date: str,
    end_date: str,
    sleep_sec: float,
) -> int:
    """按日期区间分段拉取全市场数据（不指定 ts_code）。"""
    table = _TABLE[freq]
    label = "周线" if freq == "week" else "月线"
    chunk_days = _CHUNK_DAYS[freq]
    chunks = list(_date_chunks(start_date, end_date, chunk_days))

    total = 0
    for i, (s, e) in enumerate(chunks, 1):
        print(f"[{table}] ({i}/{len(chunks)}) 拉取{label} {s} ~ {e}...")
        try:
            df = fetch_stk_weekly_monthly(freq=freq, start_date=s, end_date=e)
            if df.empty:
                print(f"[{table}] {s}~{e} 返回空数据，跳过。")
            else:
                n = upsert_df(df, table, CONFLICT_COLS)
                print(f"[{table}] {s}~{e} upsert {n} 行。")
                total += n
        except Exception as exc:
            print(f"[{table}] {s}~{e} 出错：{exc}")

        if sleep_sec > 0:
            time.sleep(sleep_sec)

    print(f"[{table}] 全部完成，共 upsert {total} 行。")
    return total


def _load_by_codes(
    freq: str,
    ts_codes: list[str],
    start_date: str | None,
    end_date: str | None,
    sleep_sec: float,
) -> int:
    """按股票代码逐只拉取（单股全量历史远低于 6000 行，无需分段）。"""
    table = _TABLE[freq]
    label = "周线" if freq == "week" else "月线"

    total = 0
    for i, code in enumerate(ts_codes, 1):
        print(f"[{table}] ({i}/{len(ts_codes)}) 拉取{label} {code}  "
              f"{start_date or '历史最早'} ~ {end_date or '今日'}...")
        try:
            df = fetch_stk_weekly_monthly(
                freq=freq,
                ts_code=code,
                start_date=start_date,
                end_date=end_date,
            )
            if df.empty:
                print(f"[{table}] {code} 返回空数据，跳过。")
                continue
            n = upsert_df(df, table, CONFLICT_COLS)
            print(f"[{table}] {code} upsert {n} 行。")
            total += n
        except Exception as exc:
            print(f"[{table}] {code} 出错：{exc}")

        if sleep_sec > 0:
            time.sleep(sleep_sec)

    print(f"[{table}] 全部完成，共 upsert {total} 行。")
    return total


def load(
    freq: str,
    ts_codes: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    sleep_sec: float = 0.3,
) -> int:
    """
    批量拉取周线或月线并写入对应表。

    参数
    ----
    freq       : 'week' 或 'month'
    ts_codes   : 股票代码列表；为 None 时拉取全市场（按日期分段）
    start_date : 开始日期 YYYYMMDD（全市场模式必填）
    end_date   : 结束日期 YYYYMMDD；不填则默认为今日
    sleep_sec  : 每次请求后额外等待秒数
    """
    if freq not in _TABLE:
        raise ValueError(f"freq 必须为 'week' 或 'month'，当前值：{freq!r}")

    if ts_codes:
        return _load_by_codes(freq, ts_codes, start_date, end_date, sleep_sec)

    # 全市场模式：必须有 start_date
    if not start_date:
        raise ValueError("全市场模式必须指定 start_date（YYYYMMDD）")
    if not end_date:
        end_date = datetime.today().strftime("%Y%m%d")

    return _load_by_date_range(freq, start_date, end_date, sleep_sec)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="加载个股周线/月线到数据库")
    parser.add_argument(
        "--freq", nargs="+", required=True, choices=["week", "month"],
        help="行情频率：week（周线）或 month（月线），可同时指定两个",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--code",      nargs="+", help="股票代码，如 000001.SZ 600519.SH")
    group.add_argument("--code-file", help="包含股票代码的文件，每行一个")
    parser.add_argument("--start",  help="开始日期 YYYYMMDD（全市场模式必填）")
    parser.add_argument("--end",    help="结束日期 YYYYMMDD（不填则默认今日）")
    parser.add_argument("--sleep",  type=float, default=0.3, help="每次请求额外间隔秒数（默认 0.3）")
    args = parser.parse_args()

    if args.code_file:
        with open(args.code_file) as f:
            codes = [line.strip() for line in f if line.strip()]
    else:
        codes = args.code  # None 时走全市场日期分段模式

    for freq in args.freq:
        load(freq, ts_codes=codes, start_date=args.start, end_date=args.end, sleep_sec=args.sleep)
