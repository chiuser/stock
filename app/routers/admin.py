"""
数据更新监控 & 配置管理 API

路由前缀: /api/admin
所有接口均需要 JWT 认证。
"""

import os
import re
import sys
import signal
import time as _time
import subprocess
import datetime
from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from app.routers.auth import decode_token

router = APIRouter()
_bearer = HTTPBearer()

# 配置文件和调度脚本路径（相对于项目根目录）
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_CONFIG_FILE  = _PROJECT_ROOT / "scripts" / "update_config.yaml"
_SCHEDULER    = _PROJECT_ROOT / "scripts" / "daily_update.py"


def _get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    return decode_token(creds.credentials)


# ------------------------------------------------------------------ #
# 工具函数
# ------------------------------------------------------------------ #

def _load_config() -> dict:
    if not _CONFIG_FILE.exists():
        raise HTTPException(status_code=404, detail=f"配置文件不存在: {_CONFIG_FILE}")
    with open(_CONFIG_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _get_log_dir(config: dict) -> Path:
    g = config.get("global", {})
    log_dir_cfg = g.get("log_dir", "logs/daily_update")
    log_dir = Path(log_dir_cfg)
    if not log_dir.is_absolute():
        project_root = Path(g.get("project_root", _PROJECT_ROOT)).expanduser()
        log_dir = project_root / log_dir_cfg
    return log_dir


def _parse_scheduler_log(log_path: Path) -> dict:
    """
    解析调度器日志，返回每个 task / stage 的事件列表。

    返回结构: { name: [ {type, ts, msg?}, ... ] }
    type 取值: start | success | failed | skipped | triggered | stage_done
    """
    if not log_path.exists():
        return {}

    pattern = re.compile(
        r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \[(\w+)\] \[(.+?)\] (.+)$"
    )
    events: dict[str, list] = {}

    with open(log_path, encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            m = pattern.match(line)
            if not m:
                continue
            ts_str, level, name, msg = m.groups()
            bucket = events.setdefault(name, [])

            if "开始执行:" in msg:
                bucket.append({"type": "start", "ts": ts_str})
            elif "dry-run" in msg.lower():
                bucket.append({"type": "success", "ts": ts_str, "msg": "[dry-run]"})
            elif "完成 ✓" in msg:
                bucket.append({"type": "success", "ts": ts_str})
            elif "失败 ✗" in msg or "TIMEOUT" in msg:
                bucket.append({"type": "failed", "ts": ts_str, "msg": msg})
            elif "跳过 —" in msg:
                bucket.append({"type": "skipped", "ts": ts_str, "msg": msg})
            elif "触发 —" in msg:
                bucket.append({"type": "triggered", "ts": ts_str, "msg": msg})
            elif "阶段结束 —" in msg:
                bucket.append({"type": "stage_done", "ts": ts_str, "msg": msg})

    return events


def _task_status_from_events(events: list[dict]) -> dict:
    """从事件列表中推断任务最新状态。"""
    # 找最后一次 start 的位置，从那里开始取
    last_start = None
    for i, ev in enumerate(events):
        if ev["type"] == "start":
            last_start = i

    recent = events[last_start:] if last_start is not None else events

    result = {"status": "pending", "started_at": None, "finished_at": None}
    for ev in recent:
        t = ev["type"]
        if t == "start":
            result["status"] = "running"
            result["started_at"] = ev["ts"]
        elif t == "success":
            result["status"] = "success"
            result["finished_at"] = ev["ts"]
        elif t == "failed":
            result["status"] = "failed"
            result["finished_at"] = ev["ts"]
            result["error"] = ev.get("msg", "")

    return result


def _stage_trigger_status(stage_name: str, events: dict) -> dict:
    """从日志中推断 stage 今天是否被触发。"""
    bucket = events.get(stage_name, [])
    for ev in reversed(bucket):
        if ev["type"] == "triggered":
            return {"triggered": True, "reason": ev.get("msg", "触发")}
        if ev["type"] == "skipped":
            return {"triggered": False, "reason": ev.get("msg", "跳过")}
    return {"triggered": None, "reason": "尚未执行"}


def _read_log_tail(log_path: Path, n: int = 30) -> list[str]:
    if not log_path.exists():
        return []
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return [l.rstrip("\n") for l in lines[-n:]]
    except Exception:
        return []


# ------------------------------------------------------------------ #
# 最新数据日期（带缓存）
# ------------------------------------------------------------------ #

# 需要查询的 (缓存 key, 数据库表名, 日期列名)
_DATE_QUERIES: list[tuple[str, str, str]] = [
    ("index_daily",       "index_daily",       "trade_date"),
    ("stock_daily",       "stock_daily",        "trade_date"),
    ("stock_daily_basic", "stock_daily_basic",  "trade_date"),
    ("moneyflow_dc",      "moneyflow_dc",       "trade_date"),
    ("stock_weekly",      "stock_weekly",       "trade_date"),
    ("stock_monthly",     "stock_monthly",      "trade_date"),
    ("broker_recommend",  "broker_recommend",   "month"),
]

# 任务名 → 缓存 key（用于在 stage 内寻找代表性日期）
_TASK_DATE_KEY: dict[str, str] = {t[0]: t[0] for t in _DATE_QUERIES}

_date_cache: dict = {"ts": 0.0, "data": {}}
_DATE_CACHE_TTL = 60   # 秒


def _get_latest_dates() -> dict[str, str | None]:
    """查询各表 MAX(date_col)，60 秒缓存。DB 不可用时静默返回空 dict。"""
    now = _time.monotonic()
    if now - _date_cache["ts"] < _DATE_CACHE_TTL and _date_cache["data"]:
        return _date_cache["data"]

    result: dict[str, str | None] = {}
    try:
        from db.connection import get_conn
        conn = get_conn()
        try:
            cur = conn.cursor()
            for key, table, col in _DATE_QUERIES:
                try:
                    cur.execute(f"SELECT MAX({col})::text FROM {table}")
                    row = cur.fetchone()
                    result[key] = row[0] if row and row[0] else None
                except Exception:
                    conn.rollback()
                    result[key] = None
        finally:
            conn.close()
    except Exception:
        pass

    _date_cache["ts"] = now
    _date_cache["data"] = result
    return result


def _fmt_date_str(s: str) -> str:
    """YYYYMMDD → YYYY-MM-DD, YYYYMM → YYYY-MM, ISO 日期原样返回。"""
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    if len(s) == 6 and s.isdigit():
        return f"{s[:4]}-{s[4:]}"
    return s


def _build_placeholders_adm() -> dict[str, str]:
    today = datetime.date.today()
    week_monday = today - datetime.timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    today_str = today.strftime("%Y%m%d")
    return {
        "{today}":         today_str,
        "{yesterday}":     (today - datetime.timedelta(days=1)).strftime("%Y%m%d"),
        "{week_monday}":   week_monday.strftime("%Y%m%d"),
        "{month_start}":   month_start.strftime("%Y%m%d"),
        "{current_month}": today.strftime("%Y%m"),
        "{date_start}":    today_str,
    }


def _resolve_task_date_range(cmd: list, placeholders: dict) -> str | None:
    """从 task cmd 解析日期范围，返回可读字符串（如 '2026-03-16 ~ 2026-03-22'）。"""
    resolved = [placeholders.get(a, a) for a in cmd]
    params: dict[str, str] = {}
    for i, arg in enumerate(resolved):
        if arg in ("--start", "--end", "--date", "--month") and i + 1 < len(resolved):
            params[arg.lstrip("-")] = resolved[i + 1]
    if not params:
        return None
    if "date" in params:
        return _fmt_date_str(params["date"])
    if "month" in params:
        return _fmt_date_str(params["month"])
    start = params.get("start")
    end   = params.get("end")
    if start and end:
        return _fmt_date_str(start) if start == end else f"{_fmt_date_str(start)} ~ {_fmt_date_str(end)}"
    if start:
        return f"{_fmt_date_str(start)} ~"
    return None


def _stage_latest_date(stage: dict, latest_dates: dict) -> str | None:
    """返回阶段内第一个有 DB 记录的任务的最新数据日期（ISO 格式）。"""
    for task in stage.get("tasks", []):
        key = _TASK_DATE_KEY.get(task["name"])
        if not key:
            continue
        val = latest_dates.get(key)
        if not val:
            continue
        # DATE 列返回 YYYY-MM-DD（psycopg2 已转为 ISO），CHAR(6) 返回 YYYYMM
        if len(val) == 6:
            return f"{val[:4]}-{val[4:]}"
        return val   # 已是 YYYY-MM-DD
    return None


def _check_today_condition(only_on: Optional[list]) -> tuple[bool, str]:
    """与 daily_update.py 中相同的触发条件检查。"""
    if not only_on:
        return True, "无条件限制，每天执行"

    today = datetime.date.today()
    weekday = today.weekday()
    day = today.day
    if today.month == 12:
        nf = today.replace(year=today.year + 1, month=1, day=1)
    else:
        nf = today.replace(month=today.month + 1, day=1)
    days_in_month = (nf - datetime.timedelta(days=1)).day

    matched = []
    for cond in only_on:
        if cond == "weekday" and weekday <= 4:
            matched.append("工作日")
        elif cond == "friday" and weekday == 4:
            matched.append("周五")
        elif cond == "month_early" and 1 <= day <= 5:
            matched.append(f"月初第{day}天")
        elif cond == "month_last" and day >= days_in_month - 4:
            matched.append(f"月末（本月{days_in_month}天）")

    if matched:
        return True, " / ".join(matched)

    cond_names = {
        "weekday": "工作日(周一~周五)",
        "friday": "每周五",
        "month_early": "月初1~5日",
        "month_last": "月末5天",
    }
    cond_str = "、".join(cond_names.get(c, c) for c in only_on)
    return False, f"今日不满足：{cond_str}"


# ------------------------------------------------------------------ #
# 接口 Schema
# ------------------------------------------------------------------ #

class GlobalConfig(BaseModel):
    project_root: str
    python: str
    log_dir: str
    env_file: str = ""


class StageConfigItem(BaseModel):
    name: str
    cron: str
    enabled: bool = True


class SaveConfigRequest(BaseModel):
    global_cfg: GlobalConfig
    stages: list[StageConfigItem]


class TriggerRequest(BaseModel):
    stage: str
    start_date: Optional[str] = None   # YYYYMMDD，覆盖起始日期占位符
    end_date:   Optional[str] = None   # YYYYMMDD，覆盖结束日期占位符


class StopRequest(BaseModel):
    stage: str


# 手动触发进程跟踪（stage_name → Popen），用于防重复执行和停止
_running_procs: dict[str, subprocess.Popen] = {}

# 被手动停止的阶段集合：进程被 SIGTERM 后日志没有完成事件，需要前端覆盖显示
_killed_stages: set[str] = set()


def _stage_date_type(stage: dict) -> str:
    """检测阶段的日期参数类型：'none' | 'range' | 'month'"""
    for task in stage.get("tasks", []):
        cmd_str = " ".join(task.get("cmd", []))
        if "{current_month}" in cmd_str:
            return "month"
        if any(p in cmd_str for p in ("{today}", "{yesterday}", "{week_monday}", "{month_start}", "{date_start}")):
            return "range"
    return "none"


# ------------------------------------------------------------------ #
# GET /api/admin/status
# ------------------------------------------------------------------ #

@router.get("/admin/status")
def get_status(user: dict = Depends(_get_current_user)):
    """返回今日各阶段任务的执行状态。"""
    config = _load_config()
    log_dir = _get_log_dir(config)
    today = datetime.date.today()
    log_file = log_dir / f"scheduler_{today:%Y%m%d}.log"
    events = _parse_scheduler_log(log_file)

    latest_dates  = _get_latest_dates()
    placeholders  = _build_placeholders_adm()

    stages_status = []
    for stage in config.get("stages", []):
        name = stage["name"]
        enabled = stage.get("enabled", True)
        only_on = stage.get("only_on")
        should_run_today, condition_reason = _check_today_condition(only_on)
        trigger_info = _stage_trigger_status(name, events)

        # 检查是否有手动触发进程正在运行
        manual_proc = _running_procs.get(name)
        if manual_proc and manual_proc.poll() is not None:
            _running_procs.pop(name, None)   # 进程已结束，清理
            manual_proc = None
        is_manual_running = manual_proc is not None

        tasks_status = []
        for task in stage.get("tasks", []):
            tname = task["name"]
            task_events = events.get(tname, [])
            st = _task_status_from_events(task_events)

            # 读取 per-task 日志末尾
            task_log = log_dir / f"{tname}_{today:%Y%m%d}.log"
            st["log_tail"] = _read_log_tail(task_log, 20)
            st["name"] = tname
            # 此次更新的日期范围（从 cmd 占位符解析）
            st["date_range"] = _resolve_task_date_range(task.get("cmd", []), placeholders)
            tasks_status.append(st)

        # 如果该阶段曾被手动停止（日志里可能有残留 running 事件）
        # 将未结束的任务标记为 failed，避免状态永远卡在 running
        if name in _killed_stages and not is_manual_running:
            for ts in tasks_status:
                if ts["status"] == "running":
                    ts["status"] = "failed"
                    ts["error"] = "已手动停止"

        stages_status.append({
            "name": name,
            "enabled": enabled,
            "cron": stage.get("cron", ""),
            "only_on": only_on or [],
            "should_run_today": should_run_today,
            "condition_reason": condition_reason,
            "triggered_today": trigger_info["triggered"],
            "trigger_reason": trigger_info["reason"],
            "date_type": _stage_date_type(stage),
            "latest_date": _stage_latest_date(stage, latest_dates),
            "is_manual_running": is_manual_running,
            "tasks": tasks_status,
        })

    return {
        "date": today.isoformat(),
        "weekday": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][today.weekday()],
        "log_file": str(log_file),
        "stages": stages_status,
    }


# ------------------------------------------------------------------ #
# GET /api/admin/config
# ------------------------------------------------------------------ #

@router.get("/admin/config")
def get_config(user: dict = Depends(_get_current_user)):
    """返回当前配置文件内容。"""
    config = _load_config()
    g = config.get("global", {})
    stages = []
    for s in config.get("stages", []):
        stages.append({
            "name": s["name"],
            "cron": s.get("cron", ""),
            "enabled": s.get("enabled", True),
            "only_on": s.get("only_on", []),
            "tasks": [t["name"] for t in s.get("tasks", [])],
        })
    return {
        "global": {
            "project_root": g.get("project_root", str(_PROJECT_ROOT)),
            "python": g.get("python", "python3"),
            "log_dir": g.get("log_dir", "logs/daily_update"),
            "env_file": g.get("env_file", ""),
        },
        "stages": stages,
    }


# ------------------------------------------------------------------ #
# PUT /api/admin/config
# ------------------------------------------------------------------ #

@router.put("/admin/config")
def save_config(body: SaveConfigRequest, user: dict = Depends(_get_current_user)):
    """更新配置文件（只更新 global 设置 及各阶段 cron/enabled）。"""
    config = _load_config()

    # 更新 global
    g = config.setdefault("global", {})
    g["project_root"] = body.global_cfg.project_root
    g["python"]       = body.global_cfg.python
    g["log_dir"]      = body.global_cfg.log_dir
    if body.global_cfg.env_file:
        g["env_file"] = body.global_cfg.env_file
    elif "env_file" in g:
        g["env_file"] = ""

    # 更新各阶段 cron / enabled
    stage_map = {s.name: s for s in body.stages}
    for stage in config.get("stages", []):
        name = stage["name"]
        if name in stage_map:
            stage["cron"] = stage_map[name].cron
            stage["enabled"] = stage_map[name].enabled

    # 备份后写回
    backup = _CONFIG_FILE.with_suffix(".yaml.bak")
    import shutil
    shutil.copy2(_CONFIG_FILE, backup)

    with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    return {"ok": True, "message": "配置已保存（注释已移除，原文件备份至 update_config.yaml.bak）"}


# ------------------------------------------------------------------ #
# POST /api/admin/run
# ------------------------------------------------------------------ #

@router.post("/admin/run")
def trigger_stage(body: TriggerRequest, user: dict = Depends(_get_current_user)):
    """在后台触发指定阶段的更新任务。"""
    config = _load_config()
    g = config.get("global", {})
    python_exe = g.get("python", "python3")
    project_root = Path(g.get("project_root", _PROJECT_ROOT)).expanduser()
    log_dir = _get_log_dir(config)
    log_dir.mkdir(parents=True, exist_ok=True)

    # 验证 stage 名称合法
    valid_stages = [s["name"] for s in config.get("stages", [])]
    if body.stage not in valid_stages:
        raise HTTPException(status_code=400, detail=f"未知阶段: {body.stage}")

    # 防止重复执行
    existing = _running_procs.get(body.stage)
    if existing and existing.poll() is None:
        raise HTTPException(
            status_code=409,
            detail=f"阶段 [{body.stage}] 正在运行中（PID={existing.pid}），请等待完成或先停止",
        )

    # 验证日期格式
    _date_re = re.compile(r"^\d{8}$")
    if body.start_date and not _date_re.match(body.start_date):
        raise HTTPException(status_code=400, detail="start_date 格式应为 YYYYMMDD")
    if body.end_date and not _date_re.match(body.end_date):
        raise HTTPException(status_code=400, detail="end_date 格式应为 YYYYMMDD")
    if body.start_date and body.end_date and body.start_date > body.end_date:
        raise HTTPException(status_code=400, detail="start_date 不能晚于 end_date")

    # 若 python_exe 是相对路径，相对于 project_root
    p = Path(python_exe)
    if not p.is_absolute() and str(p) != "python3":
        python_exe = str(project_root / p)

    scheduler = project_root / "scripts" / "daily_update.py"
    today = datetime.date.today()
    trigger_log = log_dir / f"trigger_{body.stage.replace(' ', '_')}_{today:%Y%m%d_%H%M%S}.log"

    run_cmd = [python_exe, str(scheduler), "--stage", body.stage]
    if body.start_date:
        run_cmd += ["--start", body.start_date]
    if body.end_date:
        run_cmd += ["--end", body.end_date]

    try:
        proc = subprocess.Popen(
            run_cmd,
            cwd=str(project_root),
            stdout=open(trigger_log, "w", encoding="utf-8"),
            stderr=subprocess.STDOUT,
            start_new_session=True,   # 新进程组，方便 killpg 整体终止
        )
        _running_procs[body.stage] = proc
        _killed_stages.discard(body.stage)   # 重新触发，清除停止记录
        return {
            "ok": True,
            "pid": proc.pid,
            "stage": body.stage,
            "message": f"阶段 [{body.stage}] 已在后台启动（PID={proc.pid}）",
            "log": str(trigger_log),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"启动失败: {e}")


# ------------------------------------------------------------------ #
# POST /api/admin/stop
# ------------------------------------------------------------------ #

@router.post("/admin/stop")
def stop_stage(body: StopRequest, user: dict = Depends(_get_current_user)):
    """终止指定阶段的手动触发进程（发送 SIGTERM 给整个进程组）。"""
    proc = _running_procs.get(body.stage)
    if not proc or proc.poll() is not None:
        _running_procs.pop(body.stage, None)
        raise HTTPException(status_code=404, detail=f"阶段 [{body.stage}] 没有正在运行的手动任务")
    try:
        pid = proc.pid
        os.killpg(os.getpgid(pid), signal.SIGTERM)
        _running_procs.pop(body.stage, None)
        _killed_stages.add(body.stage)
        return {"ok": True, "message": f"已终止阶段 [{body.stage}]（PID={pid}）"}
    except ProcessLookupError:
        _running_procs.pop(body.stage, None)
        _killed_stages.add(body.stage)
        return {"ok": True, "message": "进程已结束"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"停止失败: {e}")


# ------------------------------------------------------------------ #
# GET /api/admin/trigger-log/{stage_name}
# ------------------------------------------------------------------ #

@router.get("/admin/trigger-log/{stage_name}")
def get_trigger_log(stage_name: str, user: dict = Depends(_get_current_user)):
    """返回今日最新手动触发日志（trigger_*.log）的最后 80 行。"""
    if not re.match(r"^[\w\s\u4e00-\u9fff\-]+$", stage_name):
        raise HTTPException(status_code=400, detail="非法阶段名")

    config = _load_config()
    log_dir = _get_log_dir(config)
    today = datetime.date.today()

    safe = re.sub(r"\s+", "_", stage_name.strip())
    logs = sorted(log_dir.glob(f"trigger_{safe}_{today:%Y%m%d}_*.log"))
    if not logs:
        return {"lines": [], "found": False, "file": ""}

    latest = logs[-1]
    lines = _read_log_tail(latest, 80)
    return {"lines": lines, "found": True, "file": latest.name}


# ------------------------------------------------------------------ #
# GET /api/admin/log/{task_name}
# ------------------------------------------------------------------ #

@router.get("/admin/log/{task_name}")
def get_task_log(task_name: str, user: dict = Depends(_get_current_user)):
    """返回指定任务今日日志的最后 50 行。"""
    config = _load_config()
    log_dir = _get_log_dir(config)
    today = datetime.date.today()

    # 安全检查：task_name 只允许字母/数字/下划线
    if not re.match(r"^[\w\-]+$", task_name):
        raise HTTPException(status_code=400, detail="非法任务名")

    log_file = log_dir / f"{task_name}_{today:%Y%m%d}.log"
    lines = _read_log_tail(log_file, 50)
    return {"task": task_name, "date": today.isoformat(), "lines": lines}
