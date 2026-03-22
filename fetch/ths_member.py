"""
使用 tushare 获取同花顺行业/概念板块成分股（ths_member）。

tushare 接口：ths_member
描述：按板块代码查询成分股
限量：单次最大 1000 行，总量不限
所需积分：2000

输出字段
--------
ts_code（板块代码）, code（成分股代码）, name（成分股名称）,
weight（权重）, in_date（纳入日期）, out_date（移出日期，部分接口有）

拉取策略
--------
单次按板块代码查询，需先从 ths_index 获取全量板块代码后遍历拉取。
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

_COLS = [
    "ts_code", "code", "name", "weight", "in_date", "out_date",
]

_SENTINEL_DATE = "19000101"


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
    for col in ("in_date", "out_date"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], format="%Y%m%d", errors="coerce")
    # in_date 作为 PK 列不能为 NULL，用哨兵日期填充
    if "in_date" in df.columns:
        df["in_date"] = df["in_date"].fillna(pd.Timestamp(_SENTINEL_DATE))
    return df


def fetch_ths_member(ts_code: str) -> pd.DataFrame:
    """
    按板块代码拉取同花顺板块全部成分股（自动分页）。

    参数
    ----
    ts_code : 板块代码，如 '885650.TI'

    返回
    ----
    pd.DataFrame
    """
    pro = _get_pro_api()
    frames = []
    offset = 0

    while True:
        try:
            df = pro.ths_member(ts_code=ts_code, limit=_PAGE_SIZE, offset=offset)
        except Exception as e:
            print(f"[ths_member] {ts_code} offset={offset} 出错：{e}")
            break

        if df is None or df.empty:
            break
        frames.append(df)
        if len(df) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE

    if not frames:
        return pd.DataFrame()

    result = pd.concat(frames, ignore_index=True)
    return _clean(result)


def fetch_ths_members_all(
    ts_codes: list[str],
    sleep_sec: float = 0.3,
) -> pd.DataFrame:
    """
    批量拉取多个板块的成分股，适合全量导入。

    参数
    ----
    ts_codes  : 板块代码列表（从 ths_index 取）
    sleep_sec : 两次 API 调用间隔秒数

    返回
    ----
    pd.DataFrame，去重后合并
    """
    frames = []
    total = len(ts_codes)

    for i, code in enumerate(ts_codes, 1):
        try:
            df = fetch_ths_member(code)
            if not df.empty:
                frames.append(df)
                print(f"[ths_member] ({i}/{total}) {code} → {len(df)} 行")
            else:
                print(f"[ths_member] ({i}/{total}) {code} → 空数据")
        except Exception as e:
            print(f"[ths_member] ({i}/{total}) {code} 出错：{e}")

        if i < total:
            time.sleep(sleep_sec)

    if not frames:
        return pd.DataFrame()

    result = pd.concat(frames, ignore_index=True)
    return result.drop_duplicates(
        subset=["ts_code", "code", "in_date"]
    ).reset_index(drop=True)
