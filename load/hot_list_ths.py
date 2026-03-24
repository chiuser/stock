"""
加载同花顺热榜（hot_list_ths）到 PostgreSQL。

运行方式：
    # 拉取当前最新快照（全部9种市场类型，is_new=Y）
    python -m load.hot_list_ths

    # 拉取指定日期的全部快照（is_new=N，用于补数据）
    python -m load.hot_list_ths --date 20260323

    # 拉取指定日期、仅热股和ETF
    python -m load.hot_list_ths --date 20260323 --market 热股 ETF

注意：
    - upsert 主键 (trade_date, data_type, rank_time, ts_code)，安全可重跑
    - fetch_latest 使用 is_new=Y，每次返回该时刻的最新排名快照
    - 取某日最新热榜查询：
        SELECT * FROM hot_list_ths
        WHERE trade_date = '2026-03-23' AND data_type = '热股'
          AND rank_time = (
              SELECT MAX(rank_time) FROM hot_list_ths
              WHERE trade_date = '2026-03-23' AND data_type = '热股'
          )
        ORDER BY rank;
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import argparse
from typing import Optional

from fetch.hot_list_ths import fetch_latest, fetch_by_date, ALL_MARKETS
from db import upsert_df

TABLE = "hot_list_ths"
CONFLICT_COLS = ["trade_date", "data_type", "rank_time", "ts_code"]

KEEP_COLS = [
    "trade_date", "data_type", "rank_time", "ts_code",
    "ts_name", "rank", "pct_change", "current_price",
    "concept", "rank_reason", "hot",
]


def _upsert(df, label: str = "") -> int:
    if df.empty:
        print(f"[{TABLE}]{f' {label}' if label else ''} 无数据，跳过。")
        return 0
    cols = [c for c in KEEP_COLS if c in df.columns]
    n = upsert_df(df[cols], TABLE, CONFLICT_COLS)
    print(f"[{TABLE}]{f' {label}' if label else ''} upsert {n} 行。")
    return n


def load_latest(markets: Optional[list[str]] = None) -> int:
    """
    拉取当前最新热榜快照（is_new=Y），供定时任务每15分钟调用。
    每次调用写入一批以当前 rank_time 为标识的快照行。

    参数
    ----
    markets : 要拉取的市场类型列表，默认全部9种
    """
    market_list = markets or ALL_MARKETS
    total = 0
    for market in market_list:
        print(f"[{TABLE}] 拉取最新 {market}...")
        df = fetch_latest(market)
        total += _upsert(df, f"latest {market}")
    print(f"[{TABLE}] 全部完成，共 upsert {total} 行。")
    return total


def load_by_date(trade_date: str, markets: Optional[list[str]] = None) -> int:
    """
    拉取指定日期的全部快照（is_new=N），适合补拉历史数据。

    参数
    ----
    trade_date : YYYYMMDD
    markets    : 要拉取的市场类型列表，默认全部9种
    """
    market_list = markets or ALL_MARKETS
    total = 0
    for market in market_list:
        print(f"[{TABLE}] 拉取 {trade_date} {market} 全量快照...")
        df = fetch_by_date(trade_date, market)
        total += _upsert(df, f"{trade_date} {market}")
    print(f"[{TABLE}] 全部 market 完成，共 upsert {total} 行。")
    return total


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="加载同花顺热榜到数据库")
    parser.add_argument("--date",   help="指定交易日 YYYYMMDD（不填则拉最新快照）")
    parser.add_argument(
        "--market", nargs="+", dest="market",
        choices=ALL_MARKETS,
        metavar="MARKET",
        help=f"市场类型（可多选），默认全部。可选：{' | '.join(ALL_MARKETS)}",
    )
    args = parser.parse_args()

    if args.date:
        load_by_date(args.date, markets=args.market)
    else:
        load_latest(markets=args.market)
