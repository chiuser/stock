"""
加载申万行业分类（sw_industry_class）到 PostgreSQL。

运行方式：
    python -m load.sw_industry               # 默认拉取 SW2021
    python -m load.sw_industry --src SW2014  # 拉取 SW2014 版本
    python -m load.sw_industry --src all     # 拉取两个版本
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fetch.sw_industry import fetch_sw_industry
from db import upsert_df

TABLE = "sw_industry_class"
CONFLICT_COLS = ["index_code", "src"]

KEEP_COLS = [
    "index_code", "industry_name", "parent_code",
    "level", "industry_code", "is_pub", "src",
]


def load(src: str = "SW2021") -> int:
    """
    获取申万行业分类并写入 sw_industry_class 表。

    参数
    ----
    src : str
        版本，'SW2021'（默认）、'SW2014' 或 'all'（两个版本均拉取）

    返回
    ----
    int : 写入行数
    """
    if src == "all":
        total = 0
        for s in ("SW2021", "SW2014"):
            total += load(s)
        return total

    print(f"[sw_industry] 正在拉取申万行业分类（{src}）...")
    df = fetch_sw_industry(src=src)

    if df.empty:
        print(f"[sw_industry] {src} 返回空数据，跳过写入。")
        return 0

    df = df[[c for c in KEEP_COLS if c in df.columns]]

    print(f"[sw_industry] 获取 {len(df)} 行（{src}），正在写入 {TABLE}...")
    n = upsert_df(df, TABLE, CONFLICT_COLS)
    print(f"[sw_industry] 完成，upsert {n} 行。")
    return n


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="加载申万行业分类到数据库")
    parser.add_argument("--src", default="SW2021",
                        choices=["SW2021", "SW2014", "all"],
                        help="版本（默认 SW2021）")
    args = parser.parse_args()
    load(src=args.src)
