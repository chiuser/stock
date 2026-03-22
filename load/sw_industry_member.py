"""
加载申万行业成分构成（sw_industry_member）到 PostgreSQL。

运行方式：
    # 全量拉取 SW2021 所有 L3 的成分（含历史记录）
    python -m load.sw_industry_member

    # 拉取 SW2014 版本
    python -m load.sw_industry_member --src SW2014

    # 两个版本都拉
    python -m load.sw_industry_member --src all

    # 只拉某个 L3 行业的成分
    python -m load.sw_industry_member --l3 850531.SI

    # 查询某只股票所属的全部行业（含历史）
    python -m load.sw_industry_member --ts 000001.SZ

注意：
    - 全量拉取约调用 346 次 API（SW2021）或 227 次（SW2014），耗时较长
    - upsert 主键 (l3_code, ts_code, in_date)，安全可重跑
    - 首次全量拉取前，请确保 sw_industry_class 表已有数据
      （先运行 python pipeline.py --table sw_industry）
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import argparse
from typing import Optional

from fetch.sw_industry_member import (
    fetch_sw_industry_member,
    fetch_sw_industry_members_by_l3_list,
)
from db import get_conn, upsert_df

TABLE = "sw_industry_member"
CONFLICT_COLS = ["l3_code", "ts_code", "in_date"]

KEEP_COLS = [
    "l1_code", "l2_code", "l3_code",
    "ts_code", "name",
    "in_date", "out_date", "is_new",
]


def _get_l3_codes(src: str) -> list[str]:
    """从 sw_industry_class 表读取指定版本的 L3 代码列表。"""
    sql = "SELECT index_code FROM sw_industry_class WHERE level = 'L3' AND src = %s ORDER BY index_code"
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (src,))
                rows = cur.fetchall()
        codes = [r[0] for r in rows]
        return codes
    except Exception as e:
        print(f"[sw_industry_member] 读取 sw_industry_class 失败：{e}")
        return []


def _upsert(df, tag: str = "") -> int:
    if df.empty:
        print(f"[{TABLE}]{f' {tag}' if tag else ''} 无数据，跳过。")
        return 0
    cols = [c for c in KEEP_COLS if c in df.columns]
    df = df[cols]
    n = upsert_df(df, TABLE, CONFLICT_COLS)
    print(f"[{TABLE}]{f' {tag}' if tag else ''} upsert {n} 行。")
    return n


def load(src: str = "SW2021", sleep_sec: float = 0.5) -> int:
    """
    全量拉取指定版本所有 L3 行业的成分，写入数据库。

    参数
    ----
    src       : 'SW2021'（默认）、'SW2014' 或 'all'
    sleep_sec : 两次 API 调用间隔（秒），默认 0.5

    返回
    ----
    int : 总写入行数
    """
    if src == "all":
        total = 0
        for s in ("SW2021", "SW2014"):
            total += load(s, sleep_sec)
        return total

    print(f"[{TABLE}] 开始全量拉取 {src}...")
    l3_codes = _get_l3_codes(src)
    if not l3_codes:
        print(f"[{TABLE}] 未找到 {src} 的 L3 代码。"
              "请先运行：python pipeline.py --table sw_industry")
        return 0

    print(f"[{TABLE}] 共 {len(l3_codes)} 个 L3 行业，开始逐一拉取...")
    df = fetch_sw_industry_members_by_l3_list(l3_codes, sleep_sec=sleep_sec)
    return _upsert(df, src)


def load_by_l3(l3_code: str) -> int:
    """拉取单个 L3 行业的全部成分（含历史）。"""
    print(f"[{TABLE}] 拉取 L3={l3_code} 的成分...")
    df = fetch_sw_industry_member(l3_code=l3_code)
    return _upsert(df, l3_code)


def load_by_ts_code(ts_code: str) -> int:
    """查询某只股票所属的全部行业分类（含历史）。"""
    print(f"[{TABLE}] 拉取 {ts_code} 的行业归属...")
    df = fetch_sw_industry_member(ts_code=ts_code)
    return _upsert(df, ts_code)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="加载申万行业成分到数据库")
    parser.add_argument("--src",   default="SW2021",
                        choices=["SW2021", "SW2014", "all"],
                        help="版本（默认 SW2021）")
    parser.add_argument("--l3",    metavar="L3_CODE",
                        help="只拉取指定 L3 行业代码的成分，如 850531.SI")
    parser.add_argument("--ts",    metavar="TS_CODE",
                        help="查询指定股票的行业归属，如 000001.SZ")
    parser.add_argument("--sleep", type=float, default=0.5,
                        help="API 调用间隔秒数（默认 0.5）")
    args = parser.parse_args()

    if args.l3:
        load_by_l3(args.l3)
    elif args.ts:
        load_by_ts_code(args.ts)
    else:
        load(src=args.src, sleep_sec=args.sleep)
