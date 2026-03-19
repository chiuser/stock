"""
使用 tushare 获取A股个股每日基本指标（市值、PE、PB 等）。

tushare 接口文档：https://tushare.pro/document/2?doc_id=32
所需积分：120
"""

import time
import collections
import threading

import tushare as ts
import pandas as pd
from typing import Optional

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import TUSHARE_TOKEN

# 限速：每分钟最多 250 次请求（滑动窗口）
_RATE_LIMIT = 250
_WINDOW = 60.0
_rate_lock = threading.Lock()
_call_times: collections.deque = collections.deque()


def _rate_limit_wait():
    with _rate_lock:
        now = time.monotonic()
        while _call_times and _call_times[0] < now - _WINDOW:
            _call_times.popleft()
        if len(_call_times) >= _RATE_LIMIT:
            sleep_for = _WINDOW - (now - _call_times[0])
            if sleep_for > 0:
                time.sleep(sleep_for)
        _call_times.append(time.monotonic())


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


def fetch_stock_daily_basic(
    ts_code: Optional[str] = None,
    trade_date: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """
    获取个股每日基本指标（市值、换手率、PE、PB 等）。

    参数
    ----
    ts_code : str, optional
        股票代码，如 '000001.SZ'。
    trade_date : str, optional
        交易日期，格式 'YYYYMMDD'。指定后返回该日全市场数据。
    start_date : str, optional
        开始日期，格式 'YYYYMMDD'。
    end_date : str, optional
        结束日期，格式 'YYYYMMDD'。

    返回
    ----
    pd.DataFrame
        列说明：
          ts_code          股票代码
          trade_date       交易日期（datetime）
          close            当日收盘价（元）
          turnover_rate    换手率（%）
          turnover_rate_f  换手率（自由流通股，%）
          volume_ratio     量比
          pe               市盈率（总市值/净利润，亏损为空）
          pe_ttm           市盈率TTM
          pb               市净率（总市值/净资产）
          ps               市销率
          ps_ttm           市销率TTM
          dv_ratio         股息率（%）
          dv_ttm           股息率TTM
          total_share      总股本（万股）
          float_share      流通股本（万股）
          free_share       自由流通股本（万股）
          total_mv         总市值（万元）
          circ_mv          流通市值（万元）

    示例
    ----
    >>> df = fetch_stock_daily_basic('000001.SZ', start_date='20240101', end_date='20240131')
    >>> print(df[['ts_code', 'trade_date', 'pe', 'pb', 'total_mv']].head())
    """
    pro = _get_pro_api()

    fields = (
        "ts_code,trade_date,close,turnover_rate,turnover_rate_f,volume_ratio,"
        "pe,pe_ttm,pb,ps,ps_ttm,dv_ratio,dv_ttm,"
        "total_share,float_share,free_share,total_mv,circ_mv"
    )

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

    _rate_limit_wait()
    df = pro.daily_basic(**params)

    if df is None or df.empty:
        return pd.DataFrame()

    df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
    df = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)

    return df
