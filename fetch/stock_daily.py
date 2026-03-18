"""
使用 tushare 获取A股个股日线行情数据，包含除权、前复权、后复权三组价格。

tushare 接口文档：
  daily       https://tushare.pro/document/2?doc_id=27   （所需积分：120）
  adj_factor  https://tushare.pro/document/2?doc_id=28   （所需积分：100）

复权计算方式：
  设 f  = 当日复权因子，f_latest = 最新（最近一个交易日）复权因子
  后复权价 = 除权价 × f
  前复权价 = 除权价 × f / f_latest

复权说明：
  除权  (unadj)：原始成交价，发生分红/送股后价格跳变。
  前复权 (qfq)  ：以当前价格为基准向历史调整，价格连续，适合技术分析/画图。
  后复权 (hfq)  ：以上市首日价格为基准向当前调整，适合计算实际持有收益率。

实现说明：
  - 除权价格及其他字段（pre_close/change/pct_chg/vol/amount）通过 pro.daily() 获取。
  - 复权因子通过 pro.adj_factor() 获取后手动计算，不依赖 ts.pro_bar()。
  - pro.adj_factor() 必须指定 ts_code，因此：
      * 按 ts_code 查询时：三组价格均有值。
      * 仅按 trade_date 查询全市场时：qfq/hfq 列为 NaN（需调用方自行循环或预建因子表）。
"""

import datetime
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


def _apply_adj_factor(df: pd.DataFrame, ts_code: str, pro) -> pd.DataFrame:
    """
    通过 pro.adj_factor() 计算前/后复权价格并合并到 df。

    df 须含 trade_date（datetime）列及 _PRICE_COLS 各列。
    结果新增 open/high/low/close 的 _qfq 和 _hfq 后缀列。
    """
    # 查询范围内的因子（用于逐日乘价格）
    min_date = df["trade_date"].min().strftime("%Y%m%d")
    adj_df = pro.adj_factor(ts_code=ts_code, start_date=min_date)

    if adj_df is None or adj_df.empty:
        for col in _PRICE_COLS:
            df[f"{col}_qfq"] = pd.NA
            df[f"{col}_hfq"] = pd.NA
        return df

    adj_df["trade_date"] = pd.to_datetime(adj_df["trade_date"], format="%Y%m%d")

    # 前复权分母：单独取「今天以前最近一条」复权因子，避免被默认行数限制截断
    today = datetime.date.today().strftime("%Y%m%d")
    adj_latest = pro.adj_factor(ts_code=ts_code, end_date=today, limit=1)
    if adj_latest is not None and not adj_latest.empty:
        latest_factor = float(adj_latest["adj_factor"].iloc[0])
    else:
        latest_factor = float(adj_df.sort_values("trade_date").iloc[-1]["adj_factor"])

    df = df.merge(adj_df[["trade_date", "adj_factor"]], on="trade_date", how="left")

    for col in _PRICE_COLS:
        df[f"{col}_hfq"] = (df[col] * df["adj_factor"]).round(4)
        df[f"{col}_qfq"] = (df[col] * df["adj_factor"] / latest_factor).round(4)

    df = df.drop(columns=["adj_factor"])
    return df


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

    # 1. 除权价格
    daily_params = {"fields": _DAILY_FIELDS, **date_params}
    if ts_code:
        daily_params["ts_code"] = ts_code

    df = pro.daily(**daily_params)
    if df is None or df.empty:
        return pd.DataFrame()

    df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")

    # 2. 复权价格（仅在指定 ts_code 时可用）
    if ts_code:
        df = _apply_adj_factor(df, ts_code, pro)
    else:
        for col in _PRICE_COLS:
            df[f"{col}_qfq"] = pd.NA
            df[f"{col}_hfq"] = pd.NA

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
