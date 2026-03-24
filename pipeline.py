"""
数据管道主入口：从 Tushare 拉取数据并写入远程 PostgreSQL。

运行方式
--------
# 查看帮助
python pipeline.py --help

# 仅更新股票基本资料
python pipeline.py --table stock_basic

# 更新指数日线（默认使用 config.INDEX_CODES，可指定日期范围）
python pipeline.py --table index_daily --start 20240101 --end 20241231

# 更新指定股票的日线 + 每日指标
python pipeline.py --table stock_daily stock_daily_basic --code 000001.SZ 600519.SH --start 20240101

# 按单个交易日更新全市场每日指标
python pipeline.py --table stock_daily_basic --date 20241231

# 更新指数基本信息（需先执行，index_daily 依赖此表）
python pipeline.py --table index_basic

# 更新所有表（stock_basic + index_basic + 全部指数日线，不含个股——个股数量太大需分批）
python pipeline.py --table all --start 20240101

# 更新个股周线（所有股票）
python pipeline.py --table stock_weekly --start 20200101

# 同时更新周线和月线，只拉指定股票
python pipeline.py --table stock_weekly stock_monthly --code 000001.SZ 600519.SH

# 拉取单月券商金股
python pipeline.py --table broker_recommend --month 202506

# 拉取历史所有月份的券商金股（首次全量导入）
python pipeline.py --table broker_recommend --month-start 202001 --month-end 202506

# 拉取单日全市场个股资金流向
python pipeline.py --table moneyflow_dc --date 20241011

# 拉取个股资金流向历史区间（逐日全市场）
python pipeline.py --table moneyflow_dc --start 20230911 --end 20241231

# 拉取单只股票的个股资金流向
python pipeline.py --table moneyflow_dc --code 000001.SZ --start 20230911

# 拉取单日板块资金流向（行业+概念+地域全部）
python pipeline.py --table moneyflow_ind_dc --date 20240927

# 拉取板块资金流向历史区间
python pipeline.py --table moneyflow_ind_dc --start 20240901 --end 20240930

# 拉取大盘资金流向历史区间
python pipeline.py --table moneyflow_mkt_dc --start 20230911 --end 20241231

环境变量
--------
DB_HOST      远程服务器 IP / 域名
DB_PORT      端口（默认 5432）
DB_NAME      数据库名
DB_USER      用户名
DB_PASSWORD  密码

示例（设置环境变量后运行）
--------------------------
export DB_HOST=your.server.ip
export DB_PORT=5432
export DB_NAME=stock
export DB_USER=postgres
export DB_PASSWORD=your_password
python pipeline.py --table index_daily --start 20200101
"""

import argparse
import sys

from load import (
    load_stock_basic,
    load_index_basic,
    load_index_daily,
    load_stock_daily,
    load_stock_daily_basic,
    load_stock_daily_basic_date_range,
    load_stk_weekly_monthly,
    load_broker_recommend_month,
    load_broker_recommend_range,
    load_moneyflow_dc_date,
    load_moneyflow_dc_range,
    load_moneyflow_dc_code,
    load_moneyflow_ind_dc_date,
    load_moneyflow_ind_dc_range,
    load_moneyflow_mkt_dc_date,
    load_moneyflow_mkt_dc_range,
    load_sw_industry,
    load_sw_industry_member,
    load_sw_industry_member_by_l3,
    load_sw_industry_member_by_ts,
    load_sw_industry_daily_date,
    load_sw_industry_daily_range,
    load_sw_industry_daily_backfill,
    load_ci_industry_member,
    load_ci_industry_member_by_ts,
    load_ci_industry_daily_date,
    load_ci_industry_daily_range,
    load_ci_industry_daily_backfill,
    load_ths_index,
    load_ths_member,
    load_ths_member_by_code,
    load_ths_daily_date,
    load_ths_daily_range,
    load_ths_daily_backfill,
    load_dc_index_date,
    load_dc_index_range,
    load_dc_member_date,
    load_dc_member_range,
    load_dc_daily_date,
    load_dc_daily_range,
    load_dc_daily_backfill,
    load_limit_list_ths_date,
    load_limit_list_ths_range,
    load_kpl_list_date,
    load_kpl_list_range,
    load_hot_list_ths_latest,
    load_hot_list_ths_by_date,
    load_hot_list_ths_range,
)

TABLES = [
    "stock_basic", "index_basic", "index_daily",
    "stock_daily", "stock_daily_basic",
    "stock_weekly", "stock_monthly",
    "broker_recommend",
    "moneyflow_dc", "moneyflow_ind_dc", "moneyflow_mkt_dc",
    "sw_industry", "sw_industry_member", "sw_industry_daily",
    "ci_industry_member", "ci_industry_daily",
    "ths_index", "ths_member", "ths_daily",
    "dc_index", "dc_member", "dc_daily",
    "limit_list_ths",
    "kpl_list",
    "hot_list_ths",
]

# 同花顺涨跌停榜单 limit_type 可选值
_LIMIT_LIST_TYPES = ["涨停池", "连板池", "冲刺涨停", "炸板池", "跌停池"]

# 开盘啦涨跌停榜单 tag 可选值
_KPL_TAGS = ["涨停", "炸板", "跌停", "自然涨停", "竞价"]


def main():
    parser = argparse.ArgumentParser(
        description="Tushare → PostgreSQL 数据管道",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--table", nargs="+", required=True,
        choices=TABLES + ["all"],
        help="要更新的表，支持多个，'all' 表示全部（个股除外）",
    )
    parser.add_argument("--code",  nargs="+", help="股票代码列表（用于 stock_daily / stock_daily_basic）")
    parser.add_argument("--codes-file", help="包含股票代码的文件，每行一个")
    parser.add_argument("--start", help="开始日期 YYYYMMDD")
    parser.add_argument("--end",   help="结束日期 YYYYMMDD")
    parser.add_argument("--date",  help="单日 YYYYMMDD（用于 stock_daily_basic 全市场模式）")
    parser.add_argument("--month",       help="单月 YYYYMM（用于 broker_recommend）")
    parser.add_argument("--month-start", help="起始月份 YYYYMM（用于 broker_recommend 月份区间）")
    parser.add_argument("--month-end",   help="结束月份 YYYYMM（用于 broker_recommend 月份区间，不填则当前月）")
    parser.add_argument("--sleep", type=float, default=0.3,
                        help="个股批量拉取时每只间隔秒数（默认 0.3）")
    parser.add_argument("--sw-src", default="SW2021",
                        choices=["SW2021", "SW2014", "all"],
                        help="申万行业版本（默认 SW2021，用于 sw_industry / sw_industry_member）")
    parser.add_argument("--sw-l3", metavar="L3_CODE",
                        help="只拉取指定 L3 行业成分（用于 sw_industry_member），如 850531.SI")
    parser.add_argument("--backfill", action="store_true",
                        help="历史回填模式（用于 sw/ci_industry_daily），按代码逐个拉取，API调用最少")
    parser.add_argument("--ci-history", action="store_true",
                        help="拉取中信行业成分时包含历史变更记录（默认只拉当前成分）")
    parser.add_argument("--ths-type", nargs="+",
                        choices=["N", "I", "S", "W", "B"],
                        help="同花顺板块类型 N=行业 I=概念 S=特色 W=其他 B=大盘（默认全部）")
    parser.add_argument("--limit-type", nargs="+", dest="limit_type",
                        choices=_LIMIT_LIST_TYPES,
                        metavar="TYPE",
                        help=f"涨跌停榜单类型（可多选），默认全部。"
                             f"可选：{' | '.join(_LIMIT_LIST_TYPES)}")
    parser.add_argument("--tag", nargs="+", dest="kpl_tag",
                        choices=_KPL_TAGS,
                        metavar="TAG",
                        help=f"开盘啦榜单类型（可多选），默认全部。"
                             f"可选：{' | '.join(_KPL_TAGS)}")
    args = parser.parse_args()

    tables = TABLES if "all" in args.table else args.table

    # 读取股票代码列表
    codes: list[str] = []
    if args.codes_file:
        with open(args.codes_file) as f:
            codes = [line.strip() for line in f if line.strip()]
    elif args.code:
        codes = args.code

    for table in tables:
        print(f"\n{'='*60}")
        print(f"  开始处理表：{table}")
        print(f"{'='*60}")

        if table == "stock_basic":
            load_stock_basic()

        elif table == "index_basic":
            load_index_basic()

        elif table == "index_daily":
            load_index_daily(
                ts_codes=codes or None,
                start_date=args.start,
                end_date=args.end,
            )

        elif table == "stock_daily":
            load_stock_daily(
                ts_codes=codes or None,
                start_date=args.start,
                end_date=args.end,
                sleep_sec=args.sleep,
            )

        elif table == "stock_daily_basic":
            if args.date:
                # 单日全市场
                load_stock_daily_basic(trade_date=args.date)
            elif args.start and not codes:
                # 日期区间，按交易日循环拉全市场（推荐）
                load_stock_daily_basic_date_range(
                    start_date=args.start,
                    end_date=args.end,
                )
            elif codes:
                # 按股票逐个拉
                for code in codes:
                    load_stock_daily_basic(
                        ts_code=code,
                        start_date=args.start,
                        end_date=args.end,
                    )
            else:
                print("[pipeline] stock_daily_basic 请指定 --start（全市场区间）"
                      "、--date（全市场单日）或 --code + --start/--end（单股区间）。")
                sys.exit(1)

        elif table in ("stock_weekly", "stock_monthly"):
            freq = "week" if table == "stock_weekly" else "month"
            load_stk_weekly_monthly(
                freq=freq,
                ts_codes=codes or None,
                start_date=args.start,
                end_date=args.end,
                sleep_sec=args.sleep,
            )

        elif table == "broker_recommend":
            month_start = args.month_start
            month_end   = args.month_end
            month_single = args.month
            if month_single:
                load_broker_recommend_month(month_single)
            elif month_start:
                load_broker_recommend_range(month_start, month_end)
            else:
                print("[pipeline] broker_recommend 请指定 --month（单月）或 --month-start（月份区间）。")
                sys.exit(1)

        elif table == "moneyflow_dc":
            if args.date:
                load_moneyflow_dc_date(args.date)
            elif codes and args.start:
                for code in codes:
                    load_moneyflow_dc_code(code, args.start, args.end)
            elif args.start:
                load_moneyflow_dc_range(args.start, args.end)
            else:
                print("[pipeline] moneyflow_dc 请指定 --date（单日）、--start（区间）或 --code + --start（单股）。")
                sys.exit(1)

        elif table == "moneyflow_ind_dc":
            if args.date:
                load_moneyflow_ind_dc_date(args.date)
            elif args.start:
                load_moneyflow_ind_dc_range(args.start, args.end)
            else:
                print("[pipeline] moneyflow_ind_dc 请指定 --date（单日）或 --start（区间）。")
                sys.exit(1)

        elif table == "moneyflow_mkt_dc":
            if args.date:
                load_moneyflow_mkt_dc_date(args.date)
            elif args.start:
                load_moneyflow_mkt_dc_range(args.start, args.end)
            else:
                print("[pipeline] moneyflow_mkt_dc 请指定 --date（单日）或 --start（区间）。")
                sys.exit(1)

        elif table == "sw_industry":
            load_sw_industry(src=args.sw_src)

        elif table == "sw_industry_member":
            if codes:
                # 按股票代码查询行业归属
                for code in codes:
                    load_sw_industry_member_by_ts(code)
            elif getattr(args, "sw_l3", None):
                load_sw_industry_member_by_l3(args.sw_l3)
            else:
                load_sw_industry_member(src=args.sw_src, sleep_sec=args.sleep)

        elif table == "ci_industry_member":
            if codes:
                for code in codes:
                    load_ci_industry_member_by_ts(code)
            else:
                load_ci_industry_member(
                    include_history=getattr(args, "ci_history", False)
                )

        elif table == "ci_industry_daily":
            if args.date:
                load_ci_industry_daily_date(args.date)
            elif getattr(args, "backfill", False) or codes:
                load_ci_industry_daily_backfill(
                    codes=codes or None,
                    start_date=args.start,
                    end_date=args.end,
                    sleep_sec=args.sleep,
                )
            elif args.start:
                load_ci_industry_daily_range(args.start, args.end)
            else:
                print("[pipeline] ci_industry_daily 请指定 --date（单日）、"
                      "--start（日期区间）或 --backfill（历史回填）。")
                sys.exit(1)

        elif table == "ths_index":
            load_ths_index(type_=getattr(args, "ths_type", None))

        elif table == "ths_member":
            if codes:
                for code in codes:
                    load_ths_member_by_code(code)
            else:
                load_ths_member(
                    type_filter=getattr(args, "ths_type", None),
                    sleep_sec=args.sleep,
                )

        elif table == "ths_daily":
            if args.date:
                load_ths_daily_date(args.date)
            elif getattr(args, "backfill", False) or codes:
                load_ths_daily_backfill(
                    codes=codes or None,
                    start_date=args.start,
                    end_date=args.end,
                    sleep_sec=args.sleep,
                )
            elif args.start:
                load_ths_daily_range(args.start, args.end)
            else:
                print("[pipeline] ths_daily 请指定 --date（单日）、"
                      "--start（日期区间）或 --backfill（历史回填）。")
                sys.exit(1)

        elif table == "sw_industry_daily":
            if args.date:
                # 日常更新：单日，1次API
                load_sw_industry_daily_date(args.date)
            elif getattr(args, "backfill", False) or codes:
                # 历史回填：按代码逐个拉取（API调用少）
                load_sw_industry_daily_backfill(
                    codes=codes or None,
                    start_date=args.start,
                    end_date=args.end,
                    sleep_sec=args.sleep,
                )
            elif args.start:
                # 短期区间：按日期逐日拉取
                load_sw_industry_daily_range(args.start, args.end)
            else:
                print("[pipeline] sw_industry_daily 请指定 --date（单日）、"
                      "--start（日期区间）或 --backfill（历史回填）。")
                sys.exit(1)

        elif table == "dc_index":
            if args.date:
                load_dc_index_date(args.date)
            elif args.start:
                load_dc_index_range(args.start, args.end)
            else:
                print("[pipeline] dc_index 请指定 --date（单日）或 --start（日期区间）。")
                sys.exit(1)

        elif table == "dc_member":
            if args.date:
                ts_code = codes[0] if len(codes) == 1 else None
                load_dc_member_date(args.date, ts_code=ts_code)
            elif args.start:
                ts_code = codes[0] if len(codes) == 1 else None
                load_dc_member_range(args.start, args.end, ts_code=ts_code, sleep_sec=args.sleep)
            else:
                print("[pipeline] dc_member 请指定 --date（单日）或 --start（日期区间）。")
                sys.exit(1)

        elif table == "dc_daily":
            if args.date:
                load_dc_daily_date(args.date)
            elif getattr(args, "backfill", False) or codes:
                load_dc_daily_backfill(
                    codes=codes or None,
                    start_date=args.start,
                    end_date=args.end,
                    sleep_sec=args.sleep,
                )
            elif args.start:
                load_dc_daily_range(args.start, args.end)
            else:
                print("[pipeline] dc_daily 请指定 --date（单日）、"
                      "--start（日期区间）或 --backfill（历史回填）。")
                sys.exit(1)

        elif table == "limit_list_ths":
            limit_types = getattr(args, "limit_type", None) or None
            if args.date:
                load_limit_list_ths_date(args.date, limit_types=limit_types)
            elif args.start:
                load_limit_list_ths_range(
                    args.start, end_date=args.end, limit_types=limit_types
                )
            else:
                print("[pipeline] limit_list_ths 请指定 --date（单日）或 --start（日期区间）。"
                      "\n           可选 --limit-type 指定板单类型，默认拉全部 5 种。")
                sys.exit(1)

        elif table == "kpl_list":
            kpl_tags = getattr(args, "kpl_tag", None) or None
            if args.date:
                load_kpl_list_date(args.date, tags=kpl_tags)
            elif args.start:
                load_kpl_list_range(
                    args.start, end_date=args.end, tags=kpl_tags
                )
            else:
                print("[pipeline] kpl_list 请指定 --date（单日）或 --start（日期区间）。"
                      "\n           可选 --tag 指定板单类型，默认拉全部 5 种。")
                sys.exit(1)

        elif table == "hot_list_ths":
            if args.start:
                # 日期区间：逐日拉取（定时任务 start=end=today；手动补数时遍历多天）
                load_hot_list_ths_range(args.start, end_date=args.end)
            elif args.date:
                load_hot_list_ths_by_date(args.date)
            else:
                print("[pipeline] hot_list_ths 请指定 --start（日期区间）或 --date（单日）。")
                sys.exit(1)

    print(f"\n{'='*60}")
    print("  所有任务完成。")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
