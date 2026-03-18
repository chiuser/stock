"""
使用 tushare 获取A股个股日线行情数据（未复权）。

tushare 接口文档：https://tushare.pro/document/2?doc_id=27
所需积分：120
"""

import tushare as ts
import pandas as pd
from typing import Optional

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import TUSHARE_TOKEN


def _get_pro_api():
    """初始化并返回 tushare Pro API 实例。"""
    if not TUSHARE_TOKEN:
        raise ValueError(
            "未设置 tushare token。请设置环境变量 TUSHARE_TOKEN，"
            "或在 config.py 中填写 TUSHARE_TOKEN。\n"
            "注册地址：https://tushare.pro/register"
        )
    ts.set_token(TUSHARE_TOKEN)
    return ts.pro_api()


def fetch_stock_daily(
    ts_code: Optional[str] = None,
    trade_date: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """
    获取个股日线行情数据（未复权）。

    参数
    ----
    ts_code : str, optional
        股票代码，如 '000001.SZ'。与 trade_date 配合可查单日全市场。
    trade_date : str, optional
        交易日期，格式 'YYYYMMDD'。指定后返回该日全市场行情。
    start_date : str, optional
        开始日期，格式 'YYYYMMDD'。
    end_date : str, optional
        结束日期，格式 'YYYYMMDD'。

    返回
    ----
    pd.DataFrame
        列说明：
          ts_code    股票代码
          trade_date 交易日期（datetime）
          open       开盘价（元）
          high       最高价（元）
          low        最低价（元）
          close      收盘价（元）
          pre_close  昨收价（元）
          change     涨跌额（元）
          pct_chg    涨跌幅（%，未复权）
          vol        成交量（手）
          amount     成交额（千元）

    示例
    ----
    >>> df = fetch_stock_daily('000001.SZ', start_date='20240101', end_date='20240131')
    >>> print(df.head())
    """
    pro = _get_pro_api()

    fields = "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"

    params = {"fields": fields}
    if ts_code:
        params["ts_code"] = ts_code
    if trade_date:
        params["trade_date"] = trade_date
    else:
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

    df = pro.daily(**params)

    if df is None or df.empty:
        return pd.DataFrame()

    df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
    df = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)

    return df
