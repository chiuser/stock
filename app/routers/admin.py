"""
数据更新监控 & 配置管理 API

路由前缀: /api/admin
所有接口均需要 JWT 认证。
"""

import os
import re
import sys
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


def _stage_date_type(stage: dict) -> str:
    """检测阶段的日期参数类型：'none' | 'range' | 'month'"""
    for task in stage.get("tasks", []):
        cmd_str = " ".join(task.get("cmd", []))
        if "{current_month}" in cmd_str:
            return "month"
        if any(p in cmd_str for p in ("{today}", "{yesterday}", "{week_monday}", "{month_start}")):
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

    stages_status = []
    for stage in config.get("stages", []):
        name = stage["name"]
        enabled = stage.get("enabled", True)
        only_on = stage.get("only_on")
        should_run_today, condition_reason = _check_today_condition(only_on)
        trigger_info = _stage_trigger_status(name, events)

        tasks_status = []
        for task in stage.get("tasks", []):
            tname = task["name"]
            task_events = events.get(tname, [])
            st = _task_status_from_events(task_events)

            # 读取 per-task 日志末尾
            task_log = log_dir / f"{tname}_{today:%Y%m%d}.log"
            st["log_tail"] = _read_log_tail(task_log, 20)
            st["name"] = tname
            tasks_status.append(st)

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
        )
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
