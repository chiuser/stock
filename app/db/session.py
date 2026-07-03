"""SQLAlchemy connection management for attendance storage."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Connection, Engine

from app.db.config import AttendanceDbSettings


class AttendanceDbError(RuntimeError):
    """Base class for attendance database runtime failures."""


class AttendanceDbDisabled(AttendanceDbError):
    """Raised when DB work is requested while ATTENDANCE_DB_ENABLED=false."""


class AttendanceDbNotConfigured(AttendanceDbError):
    """Raised when DB work is requested without DATABASE_URL."""


_ENGINE: Engine | None = None
_ENGINE_KEY: tuple[str, int, bool] | None = None


def get_engine(settings: AttendanceDbSettings | None = None) -> Engine:
    cfg = settings or AttendanceDbSettings.from_env()
    if not cfg.attendance_db_enabled:
        raise AttendanceDbDisabled("attendance database writes are disabled")
    if not cfg.database_url_configured:
        raise AttendanceDbNotConfigured("DATABASE_URL is required when attendance DB is enabled")

    global _ENGINE, _ENGINE_KEY
    url = cfg.sqlalchemy_database_url
    key = (url, cfg.attendance_db_connect_timeout_seconds, cfg.attendance_sql_echo)
    if _ENGINE is not None and _ENGINE_KEY == key:
        return _ENGINE
    if _ENGINE is not None:
        _ENGINE.dispose()

    _ENGINE = create_engine(
        url,
        echo=cfg.attendance_sql_echo,
        pool_pre_ping=True,
        connect_args={"connect_timeout": cfg.attendance_db_connect_timeout_seconds},
    )
    _ENGINE_KEY = key
    return _ENGINE


@contextmanager
def transaction(settings: AttendanceDbSettings | None = None) -> Iterator[Connection]:
    engine = get_engine(settings)
    with engine.begin() as conn:
        yield conn


def dispose_engine() -> None:
    global _ENGINE, _ENGINE_KEY
    if _ENGINE is not None:
        _ENGINE.dispose()
    _ENGINE = None
    _ENGINE_KEY = None
