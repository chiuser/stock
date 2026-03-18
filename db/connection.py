"""
PostgreSQL 连接与通用 upsert 工具。

使用方式：
    from db import get_conn, upsert_df

环境变量（或在 config.py 中设置）：
    DB_HOST      远程服务器地址
    DB_PORT      端口，默认 5432
    DB_NAME      数据库名
    DB_USER      用户名
    DB_PASSWORD  密码
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import psycopg2
from psycopg2.extras import execute_values
import pandas as pd
from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD


def get_conn():
    """返回一个 psycopg2 连接对象。调用方负责关闭。"""
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )


def upsert_df(df: pd.DataFrame, table: str, conflict_cols: list[str]) -> int:
    """
    将 DataFrame 批量 upsert 到指定表。

    冲突时（ON CONFLICT）更新所有非主键列。
    NaN/NaT 自动转换为 None（SQL NULL）。

    参数
    ----
    df            : 要写入的 DataFrame，列名须与表字段一致
    table         : 目标表名
    conflict_cols : 构成唯一键的列名列表（对应 ON CONFLICT(...)）

    返回
    ----
    int : 写入的行数
    """
    if df is None or df.empty:
        return 0

    df = df.where(pd.notnull(df), None)  # NaN → None
    # NaT 在 timestamp 列中不会被 notnull 完全过滤，需额外处理
    df = df.apply(lambda col: col.map(lambda v: None if pd.isnull(v) else v))

    cols = list(df.columns)
    update_cols = [c for c in cols if c not in conflict_cols]

    if update_cols:
        update_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
        on_conflict = (
            f"ON CONFLICT ({', '.join(conflict_cols)}) "
            f"DO UPDATE SET {update_clause}"
        )
    else:
        on_conflict = f"ON CONFLICT ({', '.join(conflict_cols)}) DO NOTHING"

    sql = (
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES %s {on_conflict}"
    )

    rows = [tuple(row) for row in df.itertuples(index=False, name=None)]

    with get_conn() as conn:
        with conn.cursor() as cur:
            execute_values(cur, sql, rows)
        conn.commit()

    return len(rows)
