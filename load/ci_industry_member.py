"""
加载中信行业成分（ci_industry_member）到 PostgreSQL。

运行方式：
    # 全量拉取所有中信行业成分（当前成分，约 2~5 次 API）
    python -m load.ci_industry_member

    # 全量拉取，包含历史成分变更记录
    python -m load.ci_industry_member --all

    # 查询指定股票的行业归属（含历史）
    python -m load.ci_industry_member --ts 000001.SZ

注意：
    - 中信无独立行业分类 API，l1_name/l2_name/l3_name 存储在本表中
    - 全量拉取无需先建立行业分类表（与申万成分不同）
    - upsert 主键 (l3_code, ts_code, in_date)，安全可重跑
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import argparse
from typing import Optional

from fetch.ci_industry_member import (
    fetch_ci_industry_member_all,
    fetch_ci_industry_member_by_ts,
)
from db import get_conn, upsert_df

TABLE = "ci_industry_member"
CONFLICT_COLS = ["l3_code", "ts_code", "in_date"]

KEEP_COLS = [
    "l1_code", "l1_name",
    "l2_code", "l2_name",
    "l3_code", "l3_name",
    "ts_code", "name",
    "in_date", "out_date", "is_new",
]


def _upsert(df, tag: str = "") -> int:
    if df.empty:
        print(f"[{TABLE}]{f' {tag}' if tag else ''} 无数据，跳过。")
        return 0
    cols = [c for c in KEEP_COLS if c in df.columns]
    n = upsert_df(df[cols], TABLE, CONFLICT_COLS)
    print(f"[{TABLE}]{f' {tag}' if tag else ''} upsert {n} 行。")
    return n


def load(include_history: bool = False) -> int:
    """
    全量拉取所有中信行业成分。

    参数
    ----
    include_history : False → 仅当前成分（is_new='Y'，默认）
                      True  → 当前+历史变更记录
    """
    is_new = None if include_history else "Y"
    tag = "全量（含历史）" if include_history else "全量（当前）"
    print(f"[{TABLE}] 开始 {tag} 拉取...")
    df = fetch_ci_industry_member_all(is_new=is_new)
    return _upsert(df, tag)


def load_by_ts_code(ts_code: str) -> int:
    """查询指定股票所属的全部中信行业分类（含历史）。"""
    print(f"[{TABLE}] 拉取 {ts_code} 的行业归属...")
    df = fetch_ci_industry_member_by_ts(ts_code)
    return _upsert(df, ts_code)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="加载中信行业成分到数据库")
    parser.add_argument("--all", action="store_true", dest="include_history",
                        help="包含历史变更记录（默认只拉当前成分 is_new=Y）")
    parser.add_argument("--ts", metavar="TS_CODE",
                        help="查询指定股票的行业归属，如 000001.SZ")
    args = parser.parse_args()

    if args.ts:
        load_by_ts_code(args.ts)
    else:
        load(include_history=args.include_history)
