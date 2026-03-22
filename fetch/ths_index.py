"""
使用 tushare 获取同花顺行业和概念板块基础信息（ths_index）。

tushare 接口：ths_index
描述：获取同花顺行业板块/概念板块/大盘指数基础信息
限量：单次最大 1000 行，总量不限
所需积分：2000

板块类型（type 参数）
-------------------
N  = 行业板块（同花顺行业分类）
I  = 概念板块
S  = 同花顺特色
W  = 概念等其他板块
B  = 大盘指数

输出字段
--------
ts_code, name, count, exchange, list_date, type

拉取策略
--------
遍历所有板块类型，分页拉取，合并去重后写库。
"""

import time
from typing import Optional

import tushare as ts
import pandas as pd

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import TUSHARE_TOKEN

_PAGE_SIZE = 900   # 保守低于接口上限 1000

_TYPES = ["N", "I", "S", "W", "B"]

_COLS = [
    "ts_code", "name", "count", "exchange", "list_date", "type",
]


def _get_pro_api():
    if not TUSHARE_TOKEN:
        raise ValueError(
            "未设置 tushare token。请设置环境变量 TUSHARE_TOKEN，"
            "或在 config.py 中填写 TUSHARE_TOKEN。"
        )
    ts.set_token(TUSHARE_TOKEN)
    return ts.pro_api()


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    cols = [c for c in _COLS if c in df.columns]
    df = df[cols].copy()
    if "list_date" in df.columns:
        df["list_date"] = pd.to_datetime(df["list_date"], format="%Y%m%d", errors="coerce")
    return df


def fetch_ths_index(
    exchange: Optional[str] = None,
    type_: Optional[str] = None,
) -> pd.DataFrame:
    """
    拉取同花顺行业/概念板块基础信息。

    参数
    ----
    exchange : 交易所，如 'A'（A股），None = 不过滤
    type_    : 板块类型 N/I/S/W/B，None = 拉取全部类型

    返回
    ----
    pd.DataFrame
    """
    pro = _get_pro_api()
    types_to_fetch = [type_] if type_ else _TYPES
    all_frames = []

    for t in types_to_fetch:
        offset = 0
        while True:
            kwargs: dict = {"type": t, "limit": _PAGE_SIZE, "offset": offset}
            if exchange:
                kwargs["exchange"] = exchange

            try:
                df = pro.ths_index(**kwargs)
            except Exception as e:
                print(f"[ths_index] type={t} offset={offset} 出错：{e}")
                break

            if df is None or df.empty:
                break
            all_frames.append(df)
            print(f"[ths_index] type={t} offset={offset} → {len(df)} 行")
            if len(df) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE
            time.sleep(0.2)

    if not all_frames:
        return pd.DataFrame()

    result = pd.concat(all_frames, ignore_index=True)
    result = _clean(result)
    return result.drop_duplicates(subset=["ts_code"]).reset_index(drop=True)


def fetch_ths_index_by_type(type_: str) -> pd.DataFrame:
    """
    拉取单个类型的同花顺板块基础信息。

    参数
    ----
    type_ : 板块类型，如 'N'（行业）、'I'（概念）

    返回
    ----
    pd.DataFrame
    """
    return fetch_ths_index(type_=type_)
