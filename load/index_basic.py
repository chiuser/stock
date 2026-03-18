"""
加载 index_basic（指数基本信息）到远程 PostgreSQL。

运行方式：
    python -m load.index_basic
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fetch import fetch_index_basic
from db import upsert_df

TABLE = "index_basic"
CONFLICT_COLS = ["ts_code"]

KEEP_COLS = [
    "ts_code", "name", "market", "publisher", "index_type", "category",
    "base_date", "base_point", "list_date", "weight_rule", "description", "exp_date",
]


def load(market: str | None = None) -> int:
    """
    获取指数基本信息并写入 index_basic 表。

    参数
    ----
    market : str, optional
        市场代码，如 'SSE'/'SZSE'/'CSI'。为空则拉取全部。
    """
    print(f"[index_basic] 正在拉取数据{f'（market={market}）' if market else '（全部市场）'}...")
    df = fetch_index_basic(market=market)
    if df.empty:
        print("[index_basic] 返回空数据，跳过写入。")
        return 0

    # Tushare 返回字段名为 desc，表字段为 description
    if "desc" in df.columns:
        df = df.rename(columns={"desc": "description"})

    df = df[[c for c in KEEP_COLS if c in df.columns]]

    print(f"[index_basic] 获取 {len(df)} 行，正在写入 {TABLE}...")
    n = upsert_df(df, TABLE, CONFLICT_COLS)
    print(f"[index_basic] 完成，upsert {n} 行。")
    return n


if __name__ == "__main__":
    load()
