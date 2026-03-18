"""调试：查看 adj_factor 实际返回的值"""
import tushare as ts
import datetime
from config import TUSHARE_TOKEN

ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()
today = datetime.date.today().strftime('%Y%m%d')

print("=== pro.adj_factor(ts_code='000001.SZ') 不带日期 ===")
r = pro.adj_factor(ts_code='000001.SZ')
print(f"  行数={len(r)}, 列={list(r.columns)}")
if not r.empty:
    print("  头3行:\n", r.head(3).to_string(index=False))
    print("  尾3行:\n", r.tail(3).to_string(index=False))

print()
print(f"=== pro.adj_factor(ts_code='000001.SZ', start_date='20250101', end_date={today!r}) ===")
r2 = pro.adj_factor(ts_code='000001.SZ', start_date='20250101', end_date=today)
print(f"  行数={len(r2)}")
if not r2.empty:
    print(r2.to_string(index=False))

print()
print("=== pro.adj_factor(ts_code='000001.SZ', start_date='20200101', end_date='20250110') ===")
r3 = pro.adj_factor(ts_code='000001.SZ', start_date='20200101', end_date='20250110')
print(f"  行数={len(r3)}")
if not r3.empty:
    print("  尾5行（最近的因子）:\n", r3.sort_values('trade_date').tail(5).to_string(index=False))
    latest = r3.sort_values('trade_date').iloc[-1]
    print(f"\n  latest_factor = {latest['adj_factor']}  (date={latest['trade_date']})")
    on_day = r3[r3['trade_date'] == '20250102']
    if not on_day.empty:
        f_on_day = on_day['adj_factor'].iloc[0]
        print(f"  adj_factor on 20250102 = {f_on_day}")
        print(f"  => close_qfq = 11.43 * {f_on_day} / {latest['adj_factor']} = {11.43 * f_on_day / latest['adj_factor']:.4f}")
