"""
使用 tushare 获取A股指数日线行情数据。

tushare 接口文档：https://tushare.pro/document/2?doc_id=171
所需积分：2000（指数日线行情）
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

# 限速：每分钟最多 300 次请求（滑动窗口）
_RATE_LIMIT = 250
_WINDOW = 60.0
_rate_lock = threading.Lock()
_call_times: collections.deque = collections.deque()


def _rate_limit_wait():
    with _rate_lock:
        now = time.monotonic()
        # 移除窗口外的记录
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


def fetch_index_daily(
    ts_code: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    trade_date: Optional[str] = None,
) -> pd.DataFrame:
    """
    获取指数日线行情数据。

    参数
    ----
    ts_code : str
        指数代码，例如 '000001.SH'（上证指数）、'000300.SH'（沪深300）。
    start_date : str, optional
        开始日期，格式 'YYYYMMDD'，例如 '20240101'。
    end_date : str, optional
        结束日期，格式 'YYYYMMDD'，例如 '20241231'。
    trade_date : str, optional
        指定单个交易日，格式 'YYYYMMDD'。与 start_date/end_date 互斥。

    返回
    ----
    pd.DataFrame
        列说明：
          ts_code    指数代码
          trade_date 交易日期
          open       开盘价
          high       最高价
          low        最低价
          close      收盘价
          pre_close  昨收价
          change     涨跌额
          pct_chg    涨跌幅（%）
          vol        成交量（手）
          amount     成交额（千元）

    示例
    ----
    >>> df = fetch_index_daily('000001.SH', start_date='20240101', end_date='20240131')
    >>> print(df.head())
    """
    pro = _get_pro_api()

    params = {"ts_code": ts_code}
    if trade_date:
        params["trade_date"] = trade_date
    else:
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

    _rate_limit_wait()
    df = pro.index_daily(**params)

    if df is None or df.empty:
        return pd.DataFrame()

    # 按日期升序排列，并重置索引
    df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
    df = df.sort_values("trade_date").reset_index(drop=True)

    return df
