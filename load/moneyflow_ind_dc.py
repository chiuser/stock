"""
加载东财板块资金流向数据（moneyflow_ind_dc）到 PostgreSQL。

运行方式：
    # 拉取单日所有板块（行业+概念+地域）
    python -m load.moneyflow_ind_dc --date 20240927

    # 拉取日期区间内的板块数据
    python -m load.moneyflow_ind_dc --start 20240901 --end 20240930

    # 只拉取行业类数据
    python -m load.moneyflow_ind_dc --start 20240901 --end 20240930 --type 行业

注意：
    - 金额单位为元
    - upsert 主键 (trade_date, ts_code)，安全可重跑
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import argparse
from fetch.moneyflow_ind_dc import fetch_moneyflow_ind_dc, fetch_moneyflow_ind_dc_date_range
from db import get_conn, upsert_df

TABLE = "moneyflow_ind_dc"
CONFLICT_COLS = ["trade_date", "ts_code"]


def load_date(trade_date: str, content_type: str | None = None) -> int:
    df = fetch_moneyflow_ind_dc(trade_date=trade_date, content_type=content_type)
    if df.empty:
        print(f"[{TABLE}] {trade_date} 返回空数据，跳过。")
        return 0
    n = upsert_df(df, TABLE, CONFLICT_COLS)
    print(f"[{TABLE}] {trade_date} upsert {n} 行。")
    return n


def load_date_range(
    start_date: str,
    end_date: str | None = None,
    content_type: str | None = None,
) -> int:
    df = fetch_moneyflow_ind_dc_date_range(start_date, end_date, content_type)
    if df.empty:
        print(f"[{TABLE}] 区间内无数据。")
        return 0
    n = upsert_df(df, TABLE, CONFLICT_COLS)
    print(f"[{TABLE}] 全部完成，共 upsert {n} 行。")
    return n


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="加载东财板块资金流向到数据库")
    parser.add_argument("--date",  help="单日，格式 YYYYMMDD")
    parser.add_argument("--start", help="开始日期，格式 YYYYMMDD")
    parser.add_argument("--end",   help="结束日期，格式 YYYYMMDD（不填则今日）")
    parser.add_argument("--type",  dest="content_type",
                        help="板块类型：行业 / 概念 / 地域（不填则拉全部）")
    args = parser.parse_args()

    if args.date:
        load_date(args.date, args.content_type)
    elif args.start:
        load_date_range(args.start, args.end, args.content_type)
    else:
        parser.print_help()
        sys.exit(1)
