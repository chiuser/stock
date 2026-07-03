"""Runtime configuration for attendance database features."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_env_file(path: str | Path, *, override: bool = False) -> bool:
    """Load a simple KEY=value env file without adding a dotenv dependency."""
    env_path = Path(path)
    if not env_path.exists():
        return False
    with env_path.open(encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if not key:
                continue
            if override or key not in os.environ:
                os.environ[key] = _clean_env_value(value)
    return True


def normalize_database_url(url: str) -> str:
    normalized = url.strip()
    if normalized.startswith("postgresql://"):
        normalized = normalized.replace("postgresql://", "postgresql+psycopg://", 1)
    return normalized


@dataclass(frozen=True)
class AttendanceDbSettings:
    database_url: str
    attendance_db_enabled: bool = True
    attendance_notify_dedup_enabled: bool = True
    attendance_notify_dedup_window_seconds: int = 7200
    attendance_report_timezone: str = "Asia/Shanghai"
    attendance_daily_report_enabled: bool = True
    attendance_daily_report_time: str = "22:00"
    attendance_daily_report_title: str = "每日入场情况统计"
    attendance_db_connect_timeout_seconds: int = 3
    attendance_sql_echo: bool = False

    @classmethod
    def from_env(cls) -> "AttendanceDbSettings":
        return cls(
            database_url=os.environ.get("DATABASE_URL", "").strip(),
            attendance_db_enabled=_env_bool("ATTENDANCE_DB_ENABLED", True),
            attendance_notify_dedup_enabled=_env_bool("ATTENDANCE_NOTIFY_DEDUP_ENABLED", True),
            attendance_notify_dedup_window_seconds=_env_int(
                "ATTENDANCE_NOTIFY_DEDUP_WINDOW_SECONDS",
                7200,
                minimum=0,
            ),
            attendance_report_timezone=os.environ.get("ATTENDANCE_REPORT_TIMEZONE", "Asia/Shanghai").strip()
            or "Asia/Shanghai",
            attendance_daily_report_enabled=_env_bool("ATTENDANCE_DAILY_REPORT_ENABLED", True),
            attendance_daily_report_time=os.environ.get("ATTENDANCE_DAILY_REPORT_TIME", "22:00").strip()
            or "22:00",
            attendance_daily_report_title=os.environ.get(
                "ATTENDANCE_DAILY_REPORT_TITLE",
                "每日入场情况统计",
            ).strip()
            or "每日入场情况统计",
            attendance_db_connect_timeout_seconds=_env_int(
                "ATTENDANCE_DB_CONNECT_TIMEOUT_SECONDS",
                3,
                minimum=1,
            ),
            attendance_sql_echo=_env_bool("ATTENDANCE_SQL_ECHO", False),
        )

    @property
    def database_url_configured(self) -> bool:
        return bool(self.database_url.strip())

    @property
    def sqlalchemy_database_url(self) -> str:
        return normalize_database_url(self.database_url)


def _clean_env_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return value


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _env_int(name: str, default: int, *, minimum: int | None = None) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        return default
    if minimum is not None and value < minimum:
        return default
    return value
