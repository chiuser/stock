"""
加载个股周线/月线行情到 PostgreSQL。

运行方式：
    # 拉取 stock_basic 中所有股票的周线（从历史最早到今日）
    python -m load.stk_weekly_monthly --freq week

    # 拉取所有股票的月线，指定日期范围
    python -m load.stk_weekly_monthly --freq month --start 20200101 --end 20241231

    # 仅拉取指定股票的周线
    python -m load.stk_weekly_monthly --freq week --code 000001.SZ 600519.SH

    # 同时拉取周线和月线
    python -m load.stk_weekly_monthly --freq week month
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import argparse
import time
from fetch.stk_weekly_monthly import fetch_stk_weekly_monthly
from db import get_conn, upsert_df

# freq → 目标表名
_TABLE = {
    "week":  "stock_weekly",
    "month": "stock_monthly",
}
CONFLICT_COLS = ["ts_code", "trade_date"]


def _get_codes_from_db() -> list[str]:
    """从 stock_basic 表读取所有股票代码。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT ts_code FROM stock_basic ORDER BY ts_code")
            rows = cur.fetchall()
    return [r[0] for r in rows]


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
    ts_codes   : 股票代码列表；为 None 时从 stock_basic 读取全部
    start_date : 开始日期 YYYYMMDD
    end_date   : 结束日期 YYYYMMDD
    sleep_sec  : 每只股票拉取后额外等待秒数
    """
    if freq not in _TABLE:
        raise ValueError(f"freq 必须为 'week' 或 'month'，当前值：{freq!r}")

    table = _TABLE[freq]
    label = "周线" if freq == "week" else "月线"

    if ts_codes is None:
        ts_codes = _get_codes_from_db()
        if not ts_codes:
            print(f"[{table}] stock_basic 表为空，请先运行 load.stock_basic。")
            return 0

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
        except Exception as e:
            print(f"[{table}] {code} 出错：{e}")

        if sleep_sec > 0:
            time.sleep(sleep_sec)

    print(f"[{table}] 全部完成，共 upsert {total} 行。")
    return total


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="加载个股周线/月线到数据库")
    parser.add_argument(
        "--freq", nargs="+", required=True, choices=["week", "month"],
        help="行情频率：week（周线）或 month（月线），可同时指定两个",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--code",      nargs="+", help="股票代码，如 000001.SZ 600519.SH")
    group.add_argument("--code-file", help="包含股票代码的文件，每行一个")
    parser.add_argument("--start",  help="开始日期 YYYYMMDD")
    parser.add_argument("--end",    help="结束日期 YYYYMMDD")
    parser.add_argument("--sleep",  type=float, default=0.3, help="每只股票额外间隔秒数（默认 0.3）")
    args = parser.parse_args()

    if args.code_file:
        with open(args.code_file) as f:
            codes = [line.strip() for line in f if line.strip()]
    else:
        codes = args.code  # None 时自动从 DB 读取

    for freq in args.freq:
        load(freq, ts_codes=codes, start_date=args.start, end_date=args.end, sleep_sec=args.sleep)
