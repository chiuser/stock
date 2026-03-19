"""
加载 stock_daily_basic（个股每日基本指标）到远程 PostgreSQL。

运行方式：
    # 按交易日区间循环拉取全市场（推荐）
    python -m load.stock_daily_basic --start 20240101 --end 20241231

    # 按单个交易日拉取全市场
    python -m load.stock_daily_basic --date 20241231

    # 按股票代码 + 日期范围
    python -m load.stock_daily_basic --code 000001.SZ --start 20240101 --end 20241231
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import argparse
import pandas as pd
from datetime import date
from fetch import fetch_stock_daily_basic
from db import upsert_df

TABLE = "stock_daily_basic"
CONFLICT_COLS = ["ts_code", "trade_date"]


def load(
    ts_code: str | None = None,
    trade_date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> int:
    """
    拉取每日基本指标并写入 stock_daily_basic 表。

    用法组合（同 tushare 接口）：
      - trade_date               → 单日全市场
      - ts_code + start/end_date → 单股历史区间
    """
    mode = f"trade_date={trade_date}" if trade_date else f"ts_code={ts_code}, {start_date}~{end_date}"
    print(f"[stock_daily_basic] 拉取中... {mode}")

    df = fetch_stock_daily_basic(
        ts_code=ts_code,
        trade_date=trade_date,
        start_date=start_date,
        end_date=end_date,
    )
    if df.empty:
        print("[stock_daily_basic] 返回空数据，跳过写入。")
        return 0

    n = upsert_df(df, TABLE, CONFLICT_COLS)
    print(f"[stock_daily_basic] upsert {n} 行。")
    return n


def load_date_range(start_date: str, end_date: str | None = None) -> int:
    """
    按交易日区间循环拉取全市场每日基本指标。

    逐个工作日调用 load(trade_date=...)，每次一个 API 请求获取全市场数据。
    节假日 tushare 返回空，自动跳过。

    参数
    ----
    start_date : 开始日期，格式 YYYYMMDD
    end_date   : 结束日期，格式 YYYYMMDD；默认为今天
    """
    if end_date is None:
        end_date = date.today().strftime("%Y%m%d")

    # pd.bdate_range 只生成工作日（周一~周五），节假日由空返回自动跳过
    dates = pd.bdate_range(
        start=pd.to_datetime(start_date, format="%Y%m%d"),
        end=pd.to_datetime(end_date, format="%Y%m%d"),
    )

    total = 0
    for i, dt in enumerate(dates, 1):
        d = dt.strftime("%Y%m%d")
        print(f"[stock_daily_basic] [{i}/{len(dates)}] {d}")
        total += load(trade_date=d)

    print(f"[stock_daily_basic] 全部完成，共 upsert {total} 行。")
    return total


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="加载每日基本指标到数据库")
    parser.add_argument("--code",  help="股票代码，如 000001.SZ")
    parser.add_argument("--date",  help="单日全市场 YYYYMMDD")
    parser.add_argument("--start", help="开始日期 YYYYMMDD")
    parser.add_argument("--end",   help="结束日期 YYYYMMDD")
    args = parser.parse_args()

    if args.date:
        load(trade_date=args.date)
    elif args.start and not args.code:
        load_date_range(start_date=args.start, end_date=args.end)
    else:
        load(
            ts_code=args.code,
            trade_date=args.date,
            start_date=args.start,
            end_date=args.end,
        )
