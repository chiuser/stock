"""
加载同花顺行业/概念板块基础信息（ths_index）到 PostgreSQL。

运行方式：
    # 全量拉取所有板块类型（N/I/S/W/B）
    python -m load.ths_index

    # 只拉取行业板块
    python -m load.ths_index --type N

    # 只拉取概念板块
    python -m load.ths_index --type I

注意：
    - 遍历所有板块类型（N/I/S/W/B），分页拉取，合并后 upsert
    - upsert 主键 ts_code，安全可重跑
    - ths_member 和 ths_daily 依赖本表的板块代码列表
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import argparse
from typing import Optional

from fetch.ths_index import fetch_ths_index, fetch_ths_index_by_type
from db import get_conn, upsert_df

TABLE = "ths_index"
CONFLICT_COLS = ["ts_code"]

KEEP_COLS = [
    "ts_code", "name", "count", "exchange", "list_date", "type",
]


def _upsert(df, tag: str = "") -> int:
    if df.empty:
        print(f"[{TABLE}]{f' {tag}' if tag else ''} 无数据，跳过。")
        return 0
    cols = [c for c in KEEP_COLS if c in df.columns]
    n = upsert_df(df[cols], TABLE, CONFLICT_COLS)
    print(f"[{TABLE}]{f' {tag}' if tag else ''} upsert {n} 行。")
    return n


def load(
    exchange: Optional[str] = None,
    type_: Optional[str] = None,
) -> int:
    """
    全量拉取同花顺板块基础信息。

    参数
    ----
    exchange : 交易所，如 'A'；None = 不过滤
    type_    : 板块类型 N/I/S/W/B；None = 拉取所有类型
    """
    tag = f"type={type_}" if type_ else "全量"
    print(f"[{TABLE}] 开始 {tag} 拉取...")
    df = fetch_ths_index(exchange=exchange, type_=type_)
    return _upsert(df, tag)


def get_ths_codes(type_filter: Optional[list[str]] = None) -> list[str]:
    """
    从 ths_index 读取板块代码列表。

    参数
    ----
    type_filter : 板块类型列表，如 ['N', 'I']；None = 全部

    返回
    ----
    list[str]：板块代码列表
    """
    if type_filter:
        placeholders = ",".join(["%s"] * len(type_filter))
        sql = f"SELECT ts_code FROM ths_index WHERE type IN ({placeholders}) ORDER BY ts_code"
        params = type_filter
    else:
        sql = "SELECT ts_code FROM ths_index ORDER BY ts_code"
        params = []

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        return [r[0] for r in rows]
    except Exception as e:
        print(f"[{TABLE}] 读取板块代码失败：{e}")
        return []


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="加载同花顺板块基础信息到数据库")
    parser.add_argument("--type", dest="type_", metavar="TYPE",
                        choices=["N", "I", "S", "W", "B"],
                        help="板块类型 N=行业 I=概念 S=特色 W=其他 B=大盘")
    parser.add_argument("--exchange", help="交易所，如 A（A股）")
    args = parser.parse_args()

    load(exchange=args.exchange, type_=args.type_)
