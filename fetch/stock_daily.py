"""
使用 tushare 获取A股个股日线行情数据，包含除权、前复权、后复权三组价格。

tushare 接口文档：
  daily    https://tushare.pro/document/2?doc_id=27  （所需积分：120）
  pro_bar  https://tushare.pro/document/2?doc_id=109 （复权行情封装）

复权说明：
  除权  (unadj)：原始成交价，发生分红/送股后价格跳变。
  前复权 (qfq)  ：以当前价格为基准向历史调整，价格连续，适合技术分析/画图。
  后复权 (hfq)  ：以上市首日价格为基准向当前调整，适合计算实际持有收益率。

实现说明：
  - 除权价格及其他字段（pre_close/change/pct_chg/vol/amount）通过 pro.daily() 获取。
  - 前/后复权的 open/high/low/close 通过 ts.pro_bar(adj='qfq'/'hfq') 获取后合并。
  - ts.pro_bar() 必须指定 ts_code，因此：
      * 按 ts_code 查询时：三组价格均有值。
      * 仅按 trade_date 查询全市场时：qfq/hfq 列为 NaN（需调用方自行循环或用 adj_factor 计算）。
"""

import tushare as ts
import pandas as pd
from typing import Optional

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import TUSHARE_TOKEN

_DAILY_FIELDS = "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"
_PRICE_COLS   = ["open", "high", "low", "close"]


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
    获取个股日线行情，包含除权、前复权、后复权三组 OHLC 价格。

    参数
    ----
    ts_code : str, optional
        股票代码，如 '000001.SZ'。
        指定后同时返回前/后复权价格；不指定时 qfq/hfq 列为 NaN。
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
          open       除权开盘价
          high       除权最高价
          low        除权最低价
          close      除权收盘价
          pre_close  昨收价（除权）
          change     涨跌额
          pct_chg    涨跌幅（%，未复权）
          open_qfq   前复权开盘价
          high_qfq   前复权最高价
          low_qfq    前复权最低价
          close_qfq  前复权收盘价
          open_hfq   后复权开盘价
          high_hfq   后复权最高价
          low_hfq    后复权最低价
          close_hfq  后复权收盘价
          vol        成交量（手）
          amount     成交额（千元）

    示例
    ----
    >>> df = fetch_stock_daily('000001.SZ', start_date='20240101', end_date='20240131')
    >>> print(df[['trade_date', 'close', 'close_qfq', 'close_hfq']].head())
    """
    pro = _get_pro_api()

    # 公共日期参数
    date_params: dict = {}
    if trade_date:
        date_params["trade_date"] = trade_date
    else:
        if start_date:
            date_params["start_date"] = start_date
        if end_date:
            date_params["end_date"] = end_date

    # ── 1. 除权价格（及 pre_close / change / pct_chg / vol / amount） ──
    daily_params = {"fields": _DAILY_FIELDS, **date_params}
    if ts_code:
        daily_params["ts_code"] = ts_code

    df = pro.daily(**daily_params)
    if df is None or df.empty:
        return pd.DataFrame()

    df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")

    # ── 2. 前复权 / 后复权（仅在指定 ts_code 时可用） ──
    for adj in ("qfq", "hfq"):
        suffix = f"_{adj}"
        rename_map = {c: f"{c}{suffix}" for c in _PRICE_COLS}

        if ts_code:
            adj_df = ts.pro_bar(ts_code=ts_code, adj=adj, **date_params)
            if adj_df is not None and not adj_df.empty:
                adj_df["trade_date"] = pd.to_datetime(adj_df["trade_date"], format="%Y%m%d")
                adj_df = (
                    adj_df[["trade_date"] + _PRICE_COLS]
                    .rename(columns=rename_map)
                )
                df = df.merge(adj_df, on="trade_date", how="left")
                continue

        # 无法获取时补 NaN 列
        for new_col in rename_map.values():
            df[new_col] = pd.NA

    # 统一列顺序，与 schema 保持一致
    col_order = [
        "ts_code", "trade_date",
        "open", "high", "low", "close", "pre_close", "change", "pct_chg",
        "open_qfq", "high_qfq", "low_qfq", "close_qfq",
        "open_hfq", "high_hfq", "low_hfq", "close_hfq",
        "vol", "amount",
    ]
    df = df[[c for c in col_order if c in df.columns]]

    df = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    return df
