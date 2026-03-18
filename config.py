import os

# Tushare API token
# 可以通过环境变量 TUSHARE_TOKEN 设置，或直接在此处填写
TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "b80f8622aa63023a0fb62059844f341debcc346babb9ed4b896ce203")

# PostgreSQL 远程数据库连接配置
# 建议通过环境变量设置，避免明文密码提交到代码仓库
DB_HOST     = os.environ.get("DB_HOST",     "localhost")
DB_PORT     = int(os.environ.get("DB_PORT", "5432"))
DB_NAME     = os.environ.get("DB_NAME",     "stock")
DB_USER     = os.environ.get("DB_USER",     "postgres")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")

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
