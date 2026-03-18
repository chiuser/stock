"""
接口连通性测试：逐一验证数据库所需的各个 Tushare Pro 接口。

运行方式：
    python example.py

每个接口独立捕获异常，某个接口失败不影响后续测试继续运行。
"""

import tushare as ts
from config import TUSHARE_TOKEN

ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()

PASS = "✓ PASS"
FAIL = "✗ FAIL"

results = []


def test(name, fn):
    """运行单个接口测试，打印结果，记录到 results 列表。"""
    print(f"\n{'='*60}")
    print(f"[测试] {name}")
    print("-" * 60)
    try:
        df = fn()
        if df is None or df.empty:
            print("  返回数据为空（接口可通，但无数据，可能是权限或参数问题）")
            results.append((name, "WARN", "空数据"))
        else:
            print(f"  行数: {len(df)}  列: {list(df.columns)}")
            print(df.head(3).to_string(index=False))
            results.append((name, "PASS", f"{len(df)} 行"))
    except Exception as e:
        print(f"  错误: {e}")
        results.append((name, "FAIL", str(e)))


# ------------------------------------------------------------------
# 1. 股票基本资料
# ------------------------------------------------------------------
test(
    "stock_basic — 股票基本资料",
    lambda: pro.stock_basic(
        list_status="L",
        fields="ts_code,symbol,name,area,industry,list_date",
    ),
)

# ------------------------------------------------------------------
# 2. 指数基本资料
# ------------------------------------------------------------------
test(
    "index_basic — 指数基本资料",
    lambda: pro.index_basic(
        market="SSE",
        fields="ts_code,name,market,publisher,list_date",
    ),
)

# ------------------------------------------------------------------
# 3. 个股日线行情（未复权）
# ------------------------------------------------------------------
test(
    "daily — 个股日线行情",
    lambda: pro.daily(
        ts_code="000001.SZ",
        start_date="20250101",
        end_date="20250110",
    ),
)

# ------------------------------------------------------------------
# 4. 每日基本指标（市值 / PE / PB 等）
# ------------------------------------------------------------------
test(
    "daily_basic — 每日基本指标",
    lambda: pro.daily_basic(
        ts_code="000001.SZ",
        trade_date="20250110",
        fields="ts_code,trade_date,close,turnover_rate,pe,pb,total_mv,circ_mv",
    ),
)

# ------------------------------------------------------------------
# 5. 指数日线行情
# ------------------------------------------------------------------
test(
    "index_daily — 指数日线行情",
    lambda: pro.index_daily(
        ts_code="000001.SH",
        start_date="20250101",
        end_date="20250110",
    ),
)

# ------------------------------------------------------------------
# 6. 分钟K线（5个频率逐一测试）
#    注意：stk_mins 时间参数需要带时分秒
# ------------------------------------------------------------------
for freq in ("1min", "5min", "15min", "30min", "60min"):
    test(
        f"stk_mins — 分钟K线 freq={freq}",
        lambda f=freq: pro.stk_mins(
            ts_code="000001.SZ",
            freq=f,
            start_date="2025-01-06 09:00:00",
            end_date="2025-01-06 15:30:00",
        ),
    )

# ------------------------------------------------------------------
# 7. 个股新闻
# ------------------------------------------------------------------
test(
    "stock_news — 个股新闻",
    lambda: pro.stock_news(
        ts_code="000001.SZ",
        start_date="20250106 09:00:00",
        end_date="20250106 15:30:00",
    ),
)

# ------------------------------------------------------------------
# 汇总报告
# ------------------------------------------------------------------
print(f"\n{'='*60}")
print("汇总")
print("=" * 60)
for name, status, detail in results:
    icon = PASS if status == "PASS" else ("△ WARN" if status == "WARN" else FAIL)
    print(f"  {icon}  {name}")
    if status != "PASS":
        print(f"         → {detail}")
