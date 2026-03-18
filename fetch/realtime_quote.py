"""
使用 tushare 获取A股实时行情数据。

tushare 实时行情接口无需积分，使用旧版免费 API：
    ts.get_realtime_quotes(symbols)

支持股票和指数，代码格式自动转换：
    tushare Pro 格式  ->  实时行情格式
    000001.SH         ->  sh000001
    600519.SH         ->  sh600519
    000001.SZ         ->  sz000001
"""

import tushare as ts
import pandas as pd
from typing import Union

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import TUSHARE_TOKEN


def _to_realtime_symbol(ts_code: str) -> str:
    """
    将 tushare Pro 格式代码转换为实时行情格式。

    示例：
        '000001.SH' -> 'sh000001'
        '600519.SH' -> 'sh600519'
        '000001.SZ' -> 'sz000001'
    """
    code, market = ts_code.split(".")
    return market.lower() + code


def fetch_realtime_quotes(
    ts_codes: Union[str, list],
) -> pd.DataFrame:
    """
    获取A股实时行情数据（股票或指数均可）。

    参数
    ----
    ts_codes : str 或 list
        tushare Pro 格式的证券代码，单个字符串或列表。
        例如：'000001.SH' 或 ['000001.SH', '600519.SH', '000001.SZ']

    返回
    ----
    pd.DataFrame
        列说明：
          ts_code    原始代码（如 000001.SH）
          name       名称
          price      当前价（元）
          pre_close  昨收价（元）
          open       开盘价（元）
          high       最高价（元）
          low        最低价（元）
          bid        买一价（元）
          ask        卖一价（元）
          volume     成交量（手）
          amount     成交额（万元）
          pct_chg    涨跌幅（%）
          change     涨跌额（元）
          time       时间

    示例
    ----
    >>> df = fetch_realtime_quotes(['000001.SH', '600519.SH'])  # doctest: +SKIP
    >>> print(df[['ts_code', 'name', 'price', 'pct_chg']])  # doctest: +SKIP
    """
    if not TUSHARE_TOKEN:
        raise ValueError(
            "未设置 tushare token。请设置环境变量 TUSHARE_TOKEN，"
            "或在 config.py 中填写 TUSHARE_TOKEN。"
        )
    ts.set_token(TUSHARE_TOKEN)

    if isinstance(ts_codes, str):
        ts_codes = [ts_codes]

    symbols = [_to_realtime_symbol(c) for c in ts_codes]

    df = ts.get_realtime_quotes(symbols)

    if df is None or df.empty:
        return pd.DataFrame()

    # 保留并重命名所需字段
    rename_map = {
        "code":   "symbol",
        "name":   "name",
        "price":  "price",
        "pre_close": "pre_close",
        "open":   "open",
        "high":   "high",
        "low":    "low",
        "bid":    "bid",
        "ask":    "ask",
        "volume": "volume",
        "amount": "amount",
        "date":   "date",
        "time":   "time",
    }
    existing = {k: v for k, v in rename_map.items() if k in df.columns}
    df = df[list(existing.keys())].rename(columns=existing)

    # 还原原始 ts_code 映射
    # tushare get_realtime_quotes 返回的 code 列只含 6 位数字（如 '000001'），
    # 用 6 位 code 作为映射 key
    code_to_tscode = {c.split(".")[0]: c for c in ts_codes}
    df.insert(0, "ts_code", df["symbol"].map(code_to_tscode))
    df = df.drop(columns=["symbol"])

    # 数值列转换
    numeric_cols = ["price", "pre_close", "open", "high", "low", "bid", "ask", "volume", "amount"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 计算涨跌额与涨跌幅
    if "price" in df.columns and "pre_close" in df.columns:
        df["change"] = (df["price"] - df["pre_close"]).round(2)
        df["pct_chg"] = ((df["change"] / df["pre_close"]) * 100).round(2)

    # 成交量单位：股 -> 手（100股/手）
    if "volume" in df.columns:
        df["volume"] = (pd.to_numeric(df["volume"], errors="coerce") / 100).round().astype("Int64")

    # 成交额单位：元 -> 万元
    if "amount" in df.columns:
        df["amount"] = (df["amount"] / 10000).round(2)

    return df.reset_index(drop=True)
