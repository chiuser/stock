"""
加载 stock_daily（个股日线行情，含三组复权价格）到远程 PostgreSQL。

运行方式：
    # 拉取 stock_basic 中所有股票（不指定代码）
    python -m load.stock_daily --start 20240101 --end 20241231

    # 单只或多只股票，指定日期范围
    python -m load.stock_daily --code 000001.SZ 600519.SH --start 20240101 --end 20241231

    # 从文件读取股票列表（每行一个 ts_code）
    python -m load.stock_daily --code-file codes.txt --start 20240101
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import argparse
import time
from fetch import fetch_stock_daily
from db import get_conn, upsert_df

TABLE = "stock_daily"
CONFLICT_COLS = ["ts_code", "trade_date"]


def _get_codes_from_db() -> list[str]:
    """从 stock_basic 表读取所有股票代码。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT ts_code FROM stock_basic ORDER BY ts_code")
            rows = cur.fetchall()
    return [r[0] for r in rows]


def load(
    ts_codes: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    sleep_sec: float = 0.0,
) -> int:
    """
    批量拉取个股日线并写入 stock_daily 表。

    参数
    ----
    ts_codes   : 股票代码列表；为 None 时从 stock_basic 表读取全部股票
    start_date : 开始日期 YYYYMMDD
    end_date   : 结束日期 YYYYMMDD
    sleep_sec  : 每只股票拉取后的额外等待秒数（限速已内置，一般无需设置）
    """
    if ts_codes is None:
        ts_codes = _get_codes_from_db()
        if not ts_codes:
            print("[stock_daily] stock_basic 表为空，请先运行 load_stock_basic。")
            return 0

    total = 0
    for i, code in enumerate(ts_codes, 1):
        print(f"[stock_daily] ({i}/{len(ts_codes)}) 拉取 {code}  "
              f"{start_date or '历史最早'} ~ {end_date or '今日'}...")
        try:
            df = fetch_stock_daily(ts_code=code, start_date=start_date, end_date=end_date)
            if df.empty:
                print(f"[stock_daily] {code} 返回空数据，跳过。")
                continue
            n = upsert_df(df, TABLE, CONFLICT_COLS)
            print(f"[stock_daily] {code} upsert {n} 行。")
            total += n
        except Exception as e:
            print(f"[stock_daily] {code} 出错：{e}")

        if sleep_sec > 0:
            time.sleep(sleep_sec)

    print(f"[stock_daily] 全部完成，共 upsert {total} 行。")
    return total


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="加载个股日线到数据库")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--code",      nargs="+", help="股票代码，如 000001.SZ 600519.SH")
    group.add_argument("--code-file", help="包含股票代码的文件，每行一个")
    parser.add_argument("--start",    help="开始日期 YYYYMMDD")
    parser.add_argument("--end",      help="结束日期 YYYYMMDD")
    parser.add_argument("--sleep",    type=float, default=0.0, help="每只股票额外间隔秒数（默认 0）")
    args = parser.parse_args()

    if args.code_file:
        with open(args.code_file) as f:
            codes = [line.strip() for line in f if line.strip()]
    else:
        codes = args.code  # None 时自动从 DB 读取

    load(codes, start_date=args.start, end_date=args.end, sleep_sec=args.sleep)
