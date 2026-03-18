"""
加载 stock_basic（股票基本资料）到远程 PostgreSQL。

运行方式：
    python -m load.stock_basic
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fetch import fetch_stock_basic
from db import upsert_df

TABLE = "stock_basic"
CONFLICT_COLS = ["ts_code"]

# 表中实际存储的列（与 schema.sql 保持一致，排除 updated_at）
KEEP_COLS = [
    "ts_code", "symbol", "name", "area", "industry",
    "fullname", "enname", "cnspell", "market", "exchange",
    "curr_type", "list_status", "list_date", "delist_date", "is_hs",
]


def load(list_status: str = "L") -> int:
    """
    获取股票基本资料并写入 stock_basic 表。

    参数
    ----
    list_status : 'L' 上市（默认）| 'D' 退市 | 'P' 暂停
    """
    print(f"[stock_basic] 正在拉取数据（list_status={list_status}）...")
    df = fetch_stock_basic(list_status=list_status)
    if df.empty:
        print("[stock_basic] 返回空数据，跳过写入。")
        return 0

    df = df[[c for c in KEEP_COLS if c in df.columns]]

    print(f"[stock_basic] 获取 {len(df)} 行，正在写入 {TABLE}...")
    n = upsert_df(df, TABLE, CONFLICT_COLS)
    print(f"[stock_basic] 完成，upsert {n} 行。")
    return n


if __name__ == "__main__":
    load()
