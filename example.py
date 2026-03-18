"""
fetch 模块功能演示：调用各接口并打印结果。

运行方式：
    python example.py
"""

from fetch import (
    fetch_stock_basic,
    fetch_stock_daily,
    fetch_stock_daily_basic,
    fetch_index_daily,
    fetch_stk_mins,
)


def show(title, df, cols=None):
    print(f"\n{'='*60}")
    print(f"[示例] {title}")
    print("-" * 60)
    if df is None or df.empty:
        print("  返回空数据")
        return
    print(f"  共 {len(df)} 行，{len(df.columns)} 列")
    display = df[cols] if cols else df
    print(display.head(3).to_string(index=False))


# ── 1. 股票基本资料 ─────────────────────────────────────────
df_basic = fetch_stock_basic(list_status="L")
show(
    "stock_basic — 股票基本资料（上市股票，前3行）",
    df_basic,
    cols=["ts_code", "name", "market", "industry", "list_date", "is_hs"],
)

# ── 2. 个股日线（含三组复权价格） ───────────────────────────
df_daily = fetch_stock_daily(
    ts_code="000001.SZ",
    start_date="20250101",
    end_date="20250110",
)
show(
    "stock_daily — 平安银行日线（除权 vs 前复权 vs 后复权）",
    df_daily,
    cols=["trade_date", "close", "close_qfq", "close_hfq",
          "open", "open_qfq", "open_hfq", "vol"],
)

# ── 3. 每日基本指标 ─────────────────────────────────────────
df_basic_daily = fetch_stock_daily_basic(
    ts_code="000001.SZ",
    start_date="20250101",
    end_date="20250110",
)
show(
    "stock_daily_basic — 平安银行每日指标",
    df_basic_daily,
    cols=["trade_date", "close", "pe_ttm", "pb", "turnover_rate", "total_mv", "circ_mv"],
)

# ── 4. 指数日线行情 ─────────────────────────────────────────
df_index = fetch_index_daily(
    ts_code="000001.SH",
    start_date="20250101",
    end_date="20250110",
)
show(
    "index_daily — 上证指数日线",
    df_index,
    cols=["trade_date", "open", "high", "low", "close", "pct_chg", "vol"],
)

# ── 5. 分钟K线（注意：每日限访2次） ────────────────────────
print(f"\n{'='*60}")
print("[示例] stk_mins — 分钟K线（每日限访2次，已跳过自动调用）")
print("-" * 60)
print("  如需测试，手动取消注释：")
print("  df_mins = fetch_stk_mins('000001.SZ', freq='5min',")
print("                           start_date='2025-01-06 09:30:00',")
print("                           end_date='2025-01-06 11:30:00')")
print("  show('stk_mins', df_mins)")

# df_mins = fetch_stk_mins(
#     ts_code="000001.SZ",
#     freq="5min",
#     start_date="2025-01-06 09:30:00",
#     end_date="2025-01-06 11:30:00",
# )
# show("stk_mins — 平安银行5分钟K线", df_mins)
