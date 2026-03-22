"""
使用 tushare 获取申万行业分类数据。

tushare 接口：index_classify
所需积分：2000

支持版本：
  SW2014 - 申万2014版（28个一级，104个二级，227个三级）
  SW2021 - 申万2021版（31个一级，134个二级，346个三级）
"""

import tushare as ts
import pandas as pd

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import TUSHARE_TOKEN


def _get_pro_api():
    if not TUSHARE_TOKEN:
        raise ValueError(
            "未设置 tushare token。请设置环境变量 TUSHARE_TOKEN，"
            "或在 config.py 中填写 TUSHARE_TOKEN。"
        )
    ts.set_token(TUSHARE_TOKEN)
    return ts.pro_api()


def fetch_sw_industry(src: str = "SW2021") -> pd.DataFrame:
    """
    获取申万行业分类全量数据（L1 + L2 + L3 合并）。

    参数
    ----
    src : str
        版本，'SW2021'（默认）或 'SW2014'

    返回
    ----
    pd.DataFrame
        列说明：
          index_code    指数代码，如 801010.SI
          industry_name 行业名称
          parent_code   父级代码（一级为 '0'）
          level         层级 L1/L2/L3
          industry_code 行业代码，如 110000
          is_pub        是否发布指数（'1'/'0'）
          src           版本标识
    """
    pro = _get_pro_api()

    fields = "index_code,industry_name,parent_code,level,industry_code,is_pub,src"
    dfs = []

    for level in ("L1", "L2", "L3"):
        df = pro.index_classify(level=level, src=src, fields=fields)
        if df is not None and not df.empty:
            dfs.append(df)

    if not dfs:
        return pd.DataFrame()

    result = pd.concat(dfs, ignore_index=True)

    # 确保 src 列存在（部分版本 tushare 不一定返回该列）
    if "src" not in result.columns:
        result["src"] = src

    # 统一 is_pub 为字符串
    result["is_pub"] = result["is_pub"].astype(str)

    # 去重（防止 API 偶发重复行）
    result = result.drop_duplicates(subset=["index_code", "src"])

    return result.reset_index(drop=True)
