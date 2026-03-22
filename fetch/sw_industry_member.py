"""
使用 tushare 获取申万行业成分构成（分级）。

tushare 接口：index_member_all
所需积分：2000
限量：单次最大 2000 行，总量不限

支持按 L3/L2/L1 代码查询某分类的全部成分股，
也支持按股票代码查询其所属行业分类（含历史记录）。
"""

import time
from typing import Optional

import tushare as ts
import pandas as pd

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import TUSHARE_TOKEN

_PAGE_SIZE = 1900   # 保守低于接口上限 2000

_COLS_OUT = [
    "l1_code", "l2_code", "l3_code",
    "ts_code", "name",
    "in_date", "out_date", "is_new",
]

_SENTINEL_DATE = "19000101"   # in_date 为 NULL 时的哨兵值


def _get_pro_api():
    if not TUSHARE_TOKEN:
        raise ValueError(
            "未设置 tushare token。请设置环境变量 TUSHARE_TOKEN，"
            "或在 config.py 中填写 TUSHARE_TOKEN。"
        )
    ts.set_token(TUSHARE_TOKEN)
    return ts.pro_api()


def fetch_sw_industry_member(
    l1_code: Optional[str] = None,
    l2_code: Optional[str] = None,
    l3_code: Optional[str] = None,
    ts_code: Optional[str] = None,
    is_new:  Optional[str] = None,
) -> pd.DataFrame:
    """
    单次查询申万行业成分（最多 2000 行）。

    参数
    ----
    l1_code / l2_code / l3_code : str, optional
        按行业层级筛选
    ts_code : str, optional
        按股票代码查询其所属行业
    is_new : str, optional
        'Y' 仅当前成分；'N' 仅已删除；None/'' 全部（历史+当前）

    返回
    ----
    pd.DataFrame
        列：l1_code, l2_code, l3_code, ts_code, name,
            in_date(DATE), out_date(DATE), is_new
    """
    pro = _get_pro_api()

    kwargs: dict = {}
    if l1_code: kwargs["l1_code"] = l1_code
    if l2_code: kwargs["l2_code"] = l2_code
    if l3_code: kwargs["l3_code"] = l3_code
    if ts_code: kwargs["ts_code"] = ts_code
    if is_new:  kwargs["is_new"]  = is_new

    frames = []
    offset = 0
    while True:
        df = pro.index_member_all(**kwargs, limit=_PAGE_SIZE, offset=offset)
        if df is None or df.empty:
            break
        frames.append(df)
        if len(df) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE

    if not frames:
        return pd.DataFrame()

    result = pd.concat(frames, ignore_index=True)

    # 统一列顺序，只取需要的列
    cols = [c for c in _COLS_OUT if c in result.columns]
    result = result[cols].copy()

    # 日期列转换
    for col in ("in_date", "out_date"):
        if col in result.columns:
            result[col] = pd.to_datetime(result[col], format="%Y%m%d", errors="coerce")

    # in_date 不能为 NULL（主键列），用哨兵日期填充
    if "in_date" in result.columns:
        sentinel = pd.Timestamp(_SENTINEL_DATE)
        result["in_date"] = result["in_date"].fillna(sentinel)

    return result.reset_index(drop=True)


def fetch_sw_industry_members_by_l3_list(
    l3_codes: list[str],
    sleep_sec: float = 0.5,
) -> pd.DataFrame:
    """
    批量获取一组 L3 行业代码的全部成分（历史+当前）。

    参数
    ----
    l3_codes  : 三级行业指数代码列表（从 sw_industry_class 取）
    sleep_sec : 每次 API 调用间隔（默认 0.5s）

    返回
    ----
    pd.DataFrame（所有 L3 结果合并，去重）
    """
    frames = []
    total = len(l3_codes)

    for i, code in enumerate(l3_codes, 1):
        try:
            df = fetch_sw_industry_member(l3_code=code)
            if not df.empty:
                frames.append(df)
                print(f"[sw_industry_member] ({i}/{total}) {code} → {len(df)} 行")
            else:
                print(f"[sw_industry_member] ({i}/{total}) {code} → 空（暂无成分）")
        except Exception as e:
            print(f"[sw_industry_member] ({i}/{total}) {code} 出错：{e}")

        if i < total:
            time.sleep(sleep_sec)

    if not frames:
        return pd.DataFrame()

    result = pd.concat(frames, ignore_index=True)
    return result.drop_duplicates(
        subset=["l3_code", "ts_code", "in_date"]
    ).reset_index(drop=True)
