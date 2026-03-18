"""
使用 tushare 获取A股股票基本资料。

tushare 接口文档：https://tushare.pro/document/2?doc_id=25
所需积分：无（基础接口）
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


def fetch_stock_basic(
    list_status: str = "L",
    exchange: Optional[str] = None,
    ts_code: Optional[str] = None,
) -> pd.DataFrame:
    """
    获取A股股票基本资料。

    参数
    ----
    list_status : str
        上市状态，'L' 上市（默认）、'D' 退市、'P' 暂停上市。
    exchange : str, optional
        交易所代码，'SSE' 上交所、'SZSE' 深交所。为空则返回全部。
    ts_code : str, optional
        指定单只股票代码，如 '000001.SZ'。

    返回
    ----
    pd.DataFrame
        列说明：
          ts_code      TS代码
          symbol       股票代码
          name         股票名称
          area         地域
          industry     所属行业
          fullname     股票全称
          enname       英文全称
          cnspell      拼音缩写
          market       市场类型（主板/创业板/科创板等）
          exchange     交易所代码
          curr_type    交易货币
          list_status  上市状态
          list_date    上市日期（datetime）
          delist_date  退市日期（datetime，可为 NaT）
          is_hs        是否沪深港通标的（N/H/S）
          act_name     实际控制人名称
          act_ent_type 实际控制人企业性质

    示例
    ----
    >>> df = fetch_stock_basic()
    >>> print(df[['ts_code', 'name', 'industry']].head())
    """
    pro = _get_pro_api()

    fields = (
        "ts_code,symbol,name,area,industry,cnspell,market,list_date,"
        "act_name,act_ent_type,fullname,enname,exchange,curr_type,"
        "list_status,delist_date,is_hs"
    )

    params = {
        "fields": fields,
        "list_status": list_status,
    }
    if exchange:
        params["exchange"] = exchange
    if ts_code:
        params["ts_code"] = ts_code

    df = pro.stock_basic(**params)

    if df is None or df.empty:
        return pd.DataFrame()

    # 日期列转换
    df["list_date"] = pd.to_datetime(df["list_date"], format="%Y%m%d", errors="coerce")
    df["delist_date"] = pd.to_datetime(df["delist_date"], format="%Y%m%d", errors="coerce")

    return df.reset_index(drop=True)
