"""
使用 tushare 获取开盘啦涨跌停榜单（kpl_list）。

tushare 接口：kpl_list
描述：获取开盘啦涨停、炸板、跌停等榜单数据
限量：单次最大 8000 条
所需积分：8000（每分钟 600 次，总量不限）
注意：数据更新时间为次日 8:30

tag 可选值
----------
涨停      当日涨停股（默认）
炸板      曾涨停后开板
跌停      当日跌停股
自然涨停  自然涨停（非一字板）
竞价      竞价阶段涨停

拉取策略
--------
- 涨停/跌停：极端行情可达 ~500 只/天，按 15 天分批（15×500=7500 < 8000）
- 炸板/自然涨停/竞价：数据量较少，按 30 天分批
- 每批内若数据量仍超页大小，自动 offset 翻页
"""

import time
import collections
import datetime
import threading
from typing import Optional

import tushare as ts
import pandas as pd

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import TUSHARE_TOKEN

# 8000 积分：每分钟 600 次
_RATE_LIMIT = 600
_WINDOW = 60.0
_rate_lock = threading.Lock()
_call_times: collections.deque = collections.deque()

_PAGE_SIZE = 7500  # 保守低于接口上限 8000

ALL_TAGS = ["涨停", "炸板", "跌停", "自然涨停", "竞价"]

# 按 tag 分批天数：涨停/跌停数据量大用 15 天，其余用 30 天
_CHUNK_DAYS: dict[str, int] = {
    "涨停": 15,
    "跌停": 15,
    "炸板": 30,
    "自然涨停": 30,
    "竞价": 30,
}

_ALL_FIELDS = ",".join([
    "ts_code", "name", "trade_date",
    "lu_time", "ld_time", "open_time", "last_time",
    "lu_desc", "tag", "theme",
    "net_change", "bid_amount", "status",
    "bid_change", "bid_turnover", "lu_bid_vol",
    "pct_chg", "bid_pct_chg", "rt_pct_chg",
    "limit_order", "amount", "turnover_rate",
    "free_float", "lu_limit_order",
])

_COLS = _ALL_FIELDS.split(",")


def _rate_limit_wait():
    with _rate_lock:
        now = time.monotonic()
        while _call_times and _call_times[0] < now - _WINDOW:
            _call_times.popleft()
        if len(_call_times) >= _RATE_LIMIT:
            sleep_for = _WINDOW - (now - _call_times[0])
            if sleep_for > 0:
                time.sleep(sleep_for)
        _call_times.append(time.monotonic())


def _get_pro_api():
    if not TUSHARE_TOKEN:
        raise ValueError(
            "未设置 tushare token。请设置环境变量 TUSHARE_TOKEN，"
            "或在 config.py 中填写 TUSHARE_TOKEN。"
        )
    ts.set_token(TUSHARE_TOKEN)
    return ts.pro_api()


def _split_theme(val) -> Optional[list]:
    """将板块字符串拆分为数组，兼容顿号和逗号分隔。"""
    if val is None or (isinstance(val, float) and pd.isnull(val)):
        return None
    s = str(val).strip()
    if not s:
        return None
    # 兼容「、」「，」「,」三种分隔符
    for sep in ["、", "，", ","]:
        if sep in s:
            return [x.strip() for x in s.split(sep) if x.strip()]
    return [s]


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    cols = [c for c in _COLS if c in df.columns]
    df = df[cols].copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d", errors="coerce")
    # theme 字符串拆分为 Python list（写入 PostgreSQL TEXT[]）
    if "theme" in df.columns:
        df["theme"] = df["theme"].apply(_split_theme)
    return df


def _fetch_chunk(
    pro,
    start_date: str,
    end_date: str,
    tag: str,
) -> pd.DataFrame:
    """拉取一个日期区间的指定 tag 榜单（自动翻页）。"""
    frames = []
    offset = 0
    while True:
        _rate_limit_wait()
        df = pro.kpl_list(
            start_date=start_date,
            end_date=end_date,
            tag=tag,
            fields=_ALL_FIELDS,
            limit=_PAGE_SIZE,
            offset=offset,
        )
        if df is None or df.empty:
            break
        frames.append(df)
        if len(df) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE

    if not frames:
        return pd.DataFrame()
    return _clean(pd.concat(frames, ignore_index=True))


def _parse_date(d: str) -> datetime.date:
    return datetime.date(int(d[:4]), int(d[4:6]), int(d[6:]))


def fetch_by_date(trade_date: str, tag: str = "涨停") -> pd.DataFrame:
    """
    拉取指定交易日、指定 tag 的榜单数据。

    参数
    ----
    trade_date : YYYYMMDD
    tag        : 涨停 | 炸板 | 跌停 | 自然涨停 | 竞价
    """
    pro = _get_pro_api()
    return _fetch_chunk(pro, trade_date, trade_date, tag)


def fetch_range(
    start_date: str,
    end_date: Optional[str] = None,
    tag: str = "涨停",
) -> pd.DataFrame:
    """
    按日期区间、指定 tag 拉取榜单（自动按 tag 分批，每批最多 chunk_days 天）。

    参数
    ----
    start_date : YYYYMMDD
    end_date   : YYYYMMDD（默认今日）
    tag        : 涨停 | 炸板 | 跌停 | 自然涨停 | 竞价
    """
    pro = _get_pro_api()
    today = datetime.date.today()
    end = _parse_date(end_date) if end_date else today
    cur = _parse_date(start_date)
    chunk_days = _CHUNK_DAYS.get(tag, 15)
    delta_chunk = datetime.timedelta(days=chunk_days - 1)
    delta_day = datetime.timedelta(days=1)

    frames = []
    while cur <= end:
        chunk_end = min(cur + delta_chunk, end)
        s = cur.strftime("%Y%m%d")
        e = chunk_end.strftime("%Y%m%d")
        print(f"[kpl_list] {s}~{e} {tag}...")
        try:
            df = _fetch_chunk(pro, s, e, tag)
            if not df.empty:
                frames.append(df)
                print(f"[kpl_list] {s}~{e} {tag} → {len(df)} 行")
            else:
                print(f"[kpl_list] {s}~{e} {tag} → 空数据")
        except Exception as exc:
            print(f"[kpl_list] {s}~{e} {tag} 出错：{exc}")
        cur = chunk_end + delta_day

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)
