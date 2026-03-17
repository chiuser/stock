import os

# Tushare API token
# 可以通过环境变量 TUSHARE_TOKEN 设置，或直接在此处填写
TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "")

# 常用A股指数代码
INDEX_CODES = {
    "上证指数": "000001.SH",
    "深证成指": "399001.SZ",
    "沪深300": "000300.SH",
    "上证50":   "000016.SH",
    "中证500":  "000905.SH",
    "创业板指": "399006.SZ",
}
