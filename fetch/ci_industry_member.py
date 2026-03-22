"""
使用 tushare 获取中信行业成分数据。

tushare 接口：ci_index_member
描述：按三级分类提取中信行业成分，可提供某个分类的所有成分，
      也可按股票代码提取所属行业分类，参数灵活
限量：单次最大 5000 行，总量不限制
所需积分：5000

与申万行业成分的关键差异
------------------------
- 中信行业无独立分类 API（无类似 index_classify 的接口），
  因此 l1_name/l2_name/l3_name 直接存储在成员表中（反范式）
- 单次上限更大（5000 vs 2000），可直接分页全量拉取

拉取策略
--------
全量模式：不指定任何 l_code / ts_code，依靠 limit+offset 分页，
         约 2~5 次 API 调用可获取全部当前成分

按股票模式：指定 ts_code，获取该股票在所有行业中的归属
"""

import time
from typing import Optional

import tushare as ts
import pandas as pd

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import TUSHARE_TOKEN

_PAGE_SIZE = 4800   # 保守低于接口上限 5000

_COLS = [
    "l1_code", "l1_name",
    "l2_code", "l2_name",
    "l3_code", "l3_name",
    "ts_code", "name",
    "in_date", "out_date", "is_new",
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
    """统一列类型：日期转 DATE，只保留 _COLS 中的列。"""
    if df is None or df.empty:
        return pd.DataFrame()
    cols = [c for c in _COLS if c in df.columns]
    df = df[cols].copy()
    for col in ("in_date", "out_date"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], format="%Y%m%d", errors="coerce")
    # in_date 不能为 NULL（PK 列），用哨兵日期填充
    if "in_date" in df.columns:
        df["in_date"] = df["in_date"].fillna(pd.Timestamp(_SENTINEL_DATE))
    return df


def fetch_ci_industry_member_all(is_new: Optional[str] = None) -> pd.DataFrame:
    """
    全量分页获取中信行业成分（不指定行业代码，拉取全部）。

    参数
    ----
    is_new : 'Y' 仅当前成分；'N' 仅已删除；None 全部（历史+当前）

    返回
    ----
    pd.DataFrame
    """
    pro = _get_pro_api()
    frames = []
    offset = 0

    while True:
        kwargs: dict = {"limit": _PAGE_SIZE, "offset": offset}
        if is_new:
            kwargs["is_new"] = is_new

        df = pro.ci_index_member(**kwargs)
        if df is None or df.empty:
            break
        frames.append(df)
        print(f"[ci_industry_member] offset={offset} → {len(df)} 行")
        if len(df) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE
        time.sleep(0.3)

    if not frames:
        return pd.DataFrame()

    result = pd.concat(frames, ignore_index=True)
    result = _clean(result)
    return result.drop_duplicates(
        subset=["l3_code", "ts_code", "in_date"]
    ).reset_index(drop=True)


def fetch_ci_industry_member_by_ts(ts_code: str) -> pd.DataFrame:
    """
    查询指定股票所属的全部中信行业分类（含历史）。

    参数
    ----
    ts_code : 股票代码，如 '000001.SZ'

    返回
    ----
    pd.DataFrame
    """
    pro = _get_pro_api()
    frames = []
    offset = 0

    while True:
        df = pro.ci_index_member(ts_code=ts_code, limit=_PAGE_SIZE, offset=offset)
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
