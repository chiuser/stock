"""
加载同花顺行业/概念板块成分股（ths_member）到 PostgreSQL。

运行方式：
    # 全量拉取所有板块的成分股（从 ths_index 获取代码列表）
    python -m load.ths_member

    # 只拉取行业板块（type=N）的成分股
    python -m load.ths_member --type N

    # 拉取指定板块的成分股
    python -m load.ths_member --ts-code 885650.TI

注意：
    - 需先运行 ths_index 入库（本模块从 ths_index 读取板块代码）
    - upsert 主键 (ts_code, con_code, in_date)，安全可重跑
    - 约需较长时间（板块数量 × API 调用）
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import argparse
from typing import Optional

from fetch.ths_member import fetch_ths_member, fetch_ths_members_all
from load.ths_index import get_ths_codes
from db import upsert_df

TABLE = "ths_member"
CONFLICT_COLS = ["ts_code", "con_code", "in_date"]

KEEP_COLS = [
    "ts_code", "con_code", "con_name", "weight", "in_date", "out_date",
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
    type_filter: Optional[list[str]] = None,
    sleep_sec: float = 0.3,
) -> int:
    """
    全量拉取所有板块成分股。

    参数
    ----
    type_filter : 板块类型列表，如 ['N', 'I']；None = 全部类型
    sleep_sec   : API 调用间隔秒数
    """
    codes = get_ths_codes(type_filter=type_filter)
    if not codes:
        print(f"[{TABLE}] 未找到板块代码。"
              "请先运行：python pipeline.py --table ths_index")
        return 0

    type_tag = f"type={'|'.join(type_filter)}" if type_filter else "全量"
    print(f"[{TABLE}] 开始 {type_tag} 拉取，共 {len(codes)} 个板块...")
    df = fetch_ths_members_all(codes, sleep_sec=sleep_sec)
    return _upsert(df, type_tag)


def load_by_code(ts_code: str) -> int:
    """拉取单个板块的成分股。"""
    print(f"[{TABLE}] 拉取 {ts_code} 的成分股...")
    df = fetch_ths_member(ts_code)
    return _upsert(df, ts_code)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="加载同花顺板块成分股到数据库")
    parser.add_argument("--type", dest="type_", metavar="TYPE", nargs="+",
                        choices=["N", "I", "S", "W", "B"],
                        help="板块类型，可多选，如 N I（默认全部）")
    parser.add_argument("--ts-code", metavar="TS_CODE",
                        help="拉取指定板块的成分股，如 885650.TI")
    parser.add_argument("--sleep", type=float, default=0.3,
                        help="API 调用间隔秒数（默认 0.3）")
    args = parser.parse_args()

    if args.ts_code:
        load_by_code(args.ts_code)
    else:
        load(type_filter=args.type_, sleep_sec=args.sleep)
