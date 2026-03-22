"""
加载券商每月金股（荐股）数据到 PostgreSQL。

运行方式：
    # 拉取单个月份
    python -m load.broker_recommend --month 202106

    # 拉取一段时间范围内所有月份（推荐首次全量导入）
    python -m load.broker_recommend --start 202001 --end 202412

    # 只拉取当前月份（适合每月自动更新）
    python -m load.broker_recommend --start 202506

注意：
    - 每次 upsert 会用 (month, broker, ts_code) 唯一键去重/覆盖，安全可重跑。
    - 单月数据通常 200~400 行，远低于接口单次 1000 行限制，无需分页。
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import argparse
from fetch.broker_recommend import fetch_broker_recommend, fetch_broker_recommend_range
from db import get_conn, upsert_df

TABLE = "broker_recommend"
CONFLICT_COLS = ["month", "broker", "ts_code"]


def load_month(month: str) -> int:
    """拉取并写入单个月份的券商金股数据。"""
    df = fetch_broker_recommend(month)
    if df.empty:
        print(f"[{TABLE}] {month} 返回空数据，跳过。")
        return 0
    n = upsert_df(df, TABLE, CONFLICT_COLS)
    print(f"[{TABLE}] {month} upsert {n} 行。")
    return n


def load_range(start_month: str, end_month: str | None = None) -> int:
    """拉取并写入多个月份的券商金股数据。"""
    df = fetch_broker_recommend_range(start_month, end_month)
    if df.empty:
        print(f"[{TABLE}] 范围内无数据。")
        return 0
    n = upsert_df(df, TABLE, CONFLICT_COLS)
    print(f"[{TABLE}] 全部完成，共 upsert {n} 行。")
    return n


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="加载券商每月金股到数据库")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--month", help="指定单个月份，格式 YYYYMM，如 202106"
    )
    group.add_argument(
        "--start", help="起始月份，格式 YYYYMM；与 --end 配合拉取月份区间"
    )
    parser.add_argument(
        "--end", help="结束月份，格式 YYYYMM；不填则默认为当前月"
    )
    args = parser.parse_args()

    if args.month:
        load_month(args.month)
    else:
        load_range(args.start, args.end)
