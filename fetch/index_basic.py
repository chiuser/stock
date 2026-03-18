"""
使用 tushare 获取指数基本信息。

tushare 接口文档：https://tushare.pro/document/2?doc_id=94
所需积分：2000
"""

import tushare as ts
import pandas as pd

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import TUSHARE_TOKEN


def _get_pro_api():
    """初始化并返回 tushare Pro API 实例。"""
    if not TUSHARE_TOKEN:
        raise ValueError(
            "未设置 tushare token。请设置环境变量 TUSHARE_TOKEN，"
            "或在 config.py 中填写 TUSHARE_TOKEN。"
        )
    ts.set_token(TUSHARE_TOKEN)
    return ts.pro_api()


def fetch_index_basic(market: str | None = None) -> pd.DataFrame:
    """
    获取指数基本信息。

    参数
    ----
    market : str, optional
        交易所或市场代码，如 'SSE'（上交所）、'SZSE'（深交所）、'CSI'（中证）等。
        为空则返回全部。

    返回
    ----
    pd.DataFrame
        列说明：
          ts_code      指数代码
          name         指数简称
          market       交易所或市场
          publisher    发布方
          index_type   指数风格
          category     指数类别
          base_date    基期
          base_point   基点
          list_date    发布日期
          weight_rule  加权方式
          desc         描述（写入 DB 时映射为 description）
          exp_date     终止日期
    """
    pro = _get_pro_api()

    fields = (
        "ts_code,name,market,publisher,index_type,category,"
        "base_date,base_point,list_date,weight_rule,desc,exp_date"
    )

    params: dict = {"fields": fields}
    if market:
        params["market"] = market

    df = pro.index_basic(**params)

    if df is None or df.empty:
        return pd.DataFrame()

    # 日期列转换
    for col in ["base_date", "list_date", "exp_date"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], format="%Y%m%d", errors="coerce")

    return df.reset_index(drop=True)
