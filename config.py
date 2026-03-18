import os

# Tushare API token
# 可以通过环境变量 TUSHARE_TOKEN 设置，或直接在此处填写
TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "b80f8622aa63023a0fb62059844f341debcc346babb9ed4b896ce203")

# 常用A股指数代码
INDEX_CODES = {
    "上证指数": "000001.SH",
    "深证成指": "399001.SZ",
    "沪深300": "000300.SH",
    "上证50":   "000016.SH",
    "中证500":  "000905.SH",
    "创业板指": "399006.SZ",
}

# 常用A股股票代码（示例）
STOCK_CODES = {
    "贵州茅台": "600519.SH",
    "中国平安": "601318.SH",
    "招商银行": "600036.SH",
    "宁德时代": "300750.SZ",
    "比亚迪":   "002594.SZ",
    "五粮液":   "000858.SZ",
}
