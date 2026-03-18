"""
使用 tushare 获取A股分钟K线数据（个股及指数均可）。

tushare 接口文档：https://tushare.pro/document/2?doc_id=109
所需积分：2000
每日最多访问2次，请合理规划调用频率。

支持频率：1min / 5min / 15min / 30min / 60min
对应数据库表：kline_1min / kline_5min / kline_15min / kline_30min / kline_60min
"""

import tushare as ts
import pandas as pd
from typing import Optional, Literal

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import TUSHARE_TOKEN

FREQ_OPTIONS = Literal["1min", "5min", "15min", "30min", "60min"]


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


def fetch_stk_mins(
    ts_code: str,
    freq: str = "1min",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """
    获取分钟K线数据（个股或指数）。

    注意：该接口每日最多访问2次，请避免频繁调用。

    参数
    ----
    ts_code : str
        股票或指数代码，如 '000001.SZ'、'000001.SH'。
    freq : str
        K线频率，可选 '1min'、'5min'、'15min'、'30min'、'60min'。默认 '1min'。
    start_date : str, optional
        开始时间，格式 'YYYY-MM-DD HH:MM:SS'，如 '2024-01-02 09:30:00'。
    end_date : str, optional
        结束时间，格式 'YYYY-MM-DD HH:MM:SS'，如 '2024-01-02 15:00:00'。

    返回
    ----
    pd.DataFrame
        列说明：
          ts_code    股票/指数代码
          trade_time 交易时间（datetime）
          open       开盘价（元）
          close      收盘价（元）
          high       最高价（元）
          low        最低价（元）
          vol        成交量（股）
          amount     成交金额（元）

    示例
    ----
    >>> df = fetch_stk_mins('000001.SZ', freq='5min',
    ...                     start_date='2024-01-02 09:30:00',
    ...                     end_date='2024-01-02 15:00:00')
    >>> print(df.head())
    """
    valid_freqs = {"1min", "5min", "15min", "30min", "60min"}
    if freq not in valid_freqs:
        raise ValueError(f"freq 参数无效：{freq!r}，可选值：{sorted(valid_freqs)}")

    pro = _get_pro_api()

    fields = "ts_code,trade_time,open,close,high,low,vol,amount"

    params = {
        "ts_code": ts_code,
        "freq": freq,
        "fields": fields,
    }
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date

    df = pro.stk_mins(**params)

    if df is None or df.empty:
        return pd.DataFrame()

    df["trade_time"] = pd.to_datetime(df["trade_time"])
    df = df.sort_values("trade_time").reset_index(drop=True)

    return df
