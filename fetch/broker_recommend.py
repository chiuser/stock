"""
使用 tushare 获取券商每月金股（荐股）数据。

tushare 接口文档：broker_recommend
  所需积分：6000
  限量：单次最大 1000 行（单月数据通常 200~400 行），可按月循环提取

输入参数：
  month : str，月度，格式 YYYYMM（必填）

输出字段：
  month, broker, ts_code, name
"""

import time
import collections
import threading
from typing import Optional

import tushare as ts
import pandas as pd

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import TUSHARE_TOKEN

# 限速：每分钟最多 100 次（积分门槛较高接口，保守限速）
_RATE_LIMIT = 100
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
    if not TUSHARE_TOKEN:
        raise ValueError(
            "未设置 tushare token。请设置环境变量 TUSHARE_TOKEN，"
            "或在 config.py 中填写 TUSHARE_TOKEN。"
        )
    ts.set_token(TUSHARE_TOKEN)
    return ts.pro_api()


def fetch_broker_recommend(month: str) -> pd.DataFrame:
    """
    获取指定月份的券商金股列表。

    参数
    ----
    month : str
        月度，格式 YYYYMM，如 '202106'

    返回
    ----
    pd.DataFrame，列：month, broker, ts_code, name

    示例
    ----
    >>> df = fetch_broker_recommend('202106')
    >>> print(df.head())
    """
    if len(month) != 6 or not month.isdigit():
        raise ValueError(f"month 格式须为 YYYYMM，当前值：{month!r}")

    pro = _get_pro_api()
    _rate_limit_wait()
    df = pro.broker_recommend(month=month)

    if df is None or df.empty:
        return pd.DataFrame()

    df = df[["month", "broker", "ts_code", "name"]].copy()
    return df.reset_index(drop=True)


def fetch_broker_recommend_range(
    start_month: str,
    end_month: Optional[str] = None,
) -> pd.DataFrame:
    """
    批量获取多个月份的券商金股，返回合并后的 DataFrame。

    参数
    ----
    start_month : str
        起始月度，格式 YYYYMM
    end_month : str, optional
        结束月度，格式 YYYYMM；缺省时使用当前自然月

    返回
    ----
    pd.DataFrame，列：month, broker, ts_code, name
    """
    import datetime

    def _parse(m: str):
        return datetime.date(int(m[:4]), int(m[4:]), 1)

    def _fmt(d: datetime.date):
        return d.strftime("%Y%m")

    def _next_month(d: datetime.date):
        if d.month == 12:
            return datetime.date(d.year + 1, 1, 1)
        return datetime.date(d.year, d.month + 1, 1)

    today = datetime.date.today()
    end = _parse(end_month) if end_month else datetime.date(today.year, today.month, 1)
    cur = _parse(start_month)

    frames = []
    while cur <= end:
        m = _fmt(cur)
        print(f"[broker_recommend] 拉取 {m} ...")
        try:
            df = fetch_broker_recommend(m)
            if not df.empty:
                frames.append(df)
                print(f"[broker_recommend] {m} 取得 {len(df)} 行。")
            else:
                print(f"[broker_recommend] {m} 返回空数据，跳过。")
        except Exception as e:
            print(f"[broker_recommend] {m} 出错：{e}")
        cur = _next_month(cur)

    if frames:
        return pd.concat(frames, ignore_index=True)
    return pd.DataFrame()
