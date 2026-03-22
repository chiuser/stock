#!/usr/bin/env python3
"""
每日股票数据自动更新调度器

用法：
    # 运行所有符合今日条件的阶段（正常使用）
    python scripts/daily_update.py

    # 只运行指定阶段（支持多个）
    python scripts/daily_update.py --stage 基础列表 日线行情

    # 查看将要执行的内容（不实际运行）
    python scripts/daily_update.py --dry-run

    # 列出所有阶段及其状态
    python scripts/daily_update.py --list

    # 指定配置文件路径
    python scripts/daily_update.py --config /path/to/update_config.yaml
"""

import argparse
import datetime
import logging
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import yaml


# ------------------------------------------------------------------ #
# 日期占位符
# ------------------------------------------------------------------ #

def _build_placeholders() -> dict[str, str]:
    today = datetime.date.today()
    week_monday = today - datetime.timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    return {
        "{today}":         today.strftime("%Y%m%d"),
        "{yesterday}":     (today - datetime.timedelta(days=1)).strftime("%Y%m%d"),
        "{week_monday}":   week_monday.strftime("%Y%m%d"),
        "{month_start}":   month_start.strftime("%Y%m%d"),
        "{current_month}": today.strftime("%Y%m"),
    }


def _apply_placeholders(cmd: list[str], ph: dict[str, str]) -> list[str]:
    return [part.replace(k, v) for part in cmd for k, v in [(k, v) for k, v in ph.items()] if True]


# 更简洁的实现
def _sub(cmd: list[str], ph: dict[str, str]) -> list[str]:
    result = []
    for part in cmd:
        for k, v in ph.items():
            part = part.replace(k, v)
        result.append(part)
    return result


# ------------------------------------------------------------------ #
# 触发条件
# ------------------------------------------------------------------ #

def _check_condition(only_on: Optional[list[str]]) -> tuple[bool, str]:
    """返回 (是否触发, 原因说明)"""
    if not only_on:
        return True, "无条件限制"

    today = datetime.date.today()
    weekday = today.weekday()   # 0=Monday … 6=Sunday
    day = today.day

    # 计算本月天数
    if today.month == 12:
        next_month_first = today.replace(year=today.year + 1, month=1, day=1)
    else:
        next_month_first = today.replace(month=today.month + 1, day=1)
    days_in_month = (next_month_first - datetime.timedelta(days=1)).day

    reasons = []
    for cond in only_on:
        if cond == "weekday" and weekday <= 4:
            reasons.append("工作日")
        elif cond == "friday" and weekday == 4:
            reasons.append("周五")
        elif cond == "month_early" and 1 <= day <= 5:
            reasons.append(f"月初（第{day}天）")
        elif cond == "month_last" and day >= days_in_month - 4:
            reasons.append(f"月末（本月共{days_in_month}天）")

    if reasons:
        return True, " / ".join(reasons)

    cond_str = ", ".join(only_on)
    return False, f"今日不满足条件 [{cond_str}]，跳过"


# ------------------------------------------------------------------ #
# 单任务执行
# ------------------------------------------------------------------ #

def _run_task(
    task_name: str,
    cmd_args: list[str],
    project_root: Path,
    python_exe: str,
    log_dir: Path,
    dry_run: bool,
    logger: logging.Logger,
) -> tuple[str, bool, str]:
    """
    执行单个任务（在线程中调用）。

    返回 (task_name, success, output_summary)
    """
    full_cmd = [python_exe, str(project_root / "pipeline.py")] + cmd_args

    cmd_str = " ".join(full_cmd)
    logger.info("[%s] 开始执行: %s", task_name, cmd_str)

    if dry_run:
        logger.info("[%s] [dry-run] 跳过实际执行", task_name)
        return task_name, True, "[dry-run]"

    log_file = log_dir / f"{task_name}_{datetime.date.today():%Y%m%d}.log"

    try:
        result = subprocess.run(
            full_cmd,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=7200,   # 单任务最多等 2 小时
        )
        output = result.stdout + result.stderr
        log_file.write_text(output, encoding="utf-8")

        success = result.returncode == 0
        # 截取最后几行作为摘要
        lines = [l for l in output.splitlines() if l.strip()]
        summary = "\n".join(lines[-5:]) if lines else "(无输出)"

        if success:
            logger.info("[%s] 完成 ✓\n%s", task_name, summary)
        else:
            logger.error("[%s] 失败 ✗（退出码 %d）\n%s", task_name, result.returncode, summary)

        return task_name, success, summary

    except subprocess.TimeoutExpired:
        msg = "任务超时（>2h），已强制终止"
        logger.error("[%s] %s", task_name, msg)
        return task_name, False, msg
    except Exception as e:
        msg = f"执行出错: {e}"
        logger.error("[%s] %s", task_name, msg)
        return task_name, False, msg


# ------------------------------------------------------------------ #
# 阶段执行（并行）
# ------------------------------------------------------------------ #

def _run_stage(
    stage: dict,
    project_root: Path,
    python_exe: str,
    log_dir: Path,
    placeholders: dict[str, str],
    dry_run: bool,
    logger: logging.Logger,
) -> tuple[int, int]:
    """
    并行执行一个 stage 内的所有 tasks。

    返回 (成功数, 失败数)
    """
    tasks = stage.get("tasks", [])
    if not tasks:
        return 0, 0

    max_workers = min(len(tasks), 8)   # 最多同时跑 8 个进程

    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _run_task,
                task["name"],
                _sub(task["cmd"], placeholders),
                project_root,
                python_exe,
                log_dir,
                dry_run,
                logger,
            ): task["name"]
            for task in tasks
        }
        for future in as_completed(futures):
            name, success, summary = future.result()
            results[name] = success

    ok = sum(1 for v in results.values() if v)
    fail = sum(1 for v in results.values() if not v)
    return ok, fail


# ------------------------------------------------------------------ #
# 主流程
# ------------------------------------------------------------------ #

def _setup_logger(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"scheduler_{datetime.date.today():%Y%m%d}.log"

    logger = logging.getLogger("daily_update")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    return logger


def _load_env_file(env_file: str) -> None:
    """加载 .env 文件中的环境变量（KEY=VALUE 格式）"""
    path = Path(env_file)
    if not path.exists():
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="每日股票数据自动更新调度器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--config", default=None,
        help="配置文件路径（默认: <project_root>/scripts/update_config.yaml）",
    )
    parser.add_argument(
        "--stage", nargs="+", metavar="STAGE",
        help="只执行指定阶段名（支持多个），不填则执行所有符合条件的阶段",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="只打印将要执行的命令，不实际运行",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="列出所有阶段及今日触发状态后退出",
    )
    args = parser.parse_args()

    # 定位配置文件
    script_dir = Path(__file__).parent
    config_path = Path(args.config) if args.config else (script_dir / "update_config.yaml")
    if not config_path.exists():
        print(f"[ERROR] 配置文件不存在: {config_path}", file=sys.stderr)
        sys.exit(1)

    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    g = config.get("global", {})
    project_root = Path(g.get("project_root", script_dir.parent)).expanduser()
    python_exe   = g.get("python", "python3")
    log_dir_cfg  = g.get("log_dir", "logs/daily_update")
    log_dir = (
        Path(log_dir_cfg) if Path(log_dir_cfg).is_absolute()
        else project_root / log_dir_cfg
    )
    env_file = g.get("env_file", "")
    if env_file:
        _load_env_file(env_file)

    # 若 python_exe 是相对路径，相对于 project_root 解析
    if not Path(python_exe).is_absolute() and python_exe != "python3":
        python_exe = str(project_root / python_exe)

    stages: list[dict] = config.get("stages", [])
    placeholders = _build_placeholders()

    # --list 模式
    if args.list:
        print(f"\n{'─'*60}")
        print(f"  配置文件: {config_path}")
        print(f"  今日日期: {placeholders['{today}']} ({datetime.date.today().strftime('%A')})")
        print(f"{'─'*60}")
        for stage in stages:
            enabled = stage.get("enabled", True)
            ok, reason = _check_condition(stage.get("only_on"))
            marker = "✓" if (ok and enabled) else "✗"
            tasks = [t["name"] for t in stage.get("tasks", [])]
            print(f"\n  [{marker}] {stage['name']}")
            print(f"      cron   : {stage.get('cron', '—')}")
            print(f"      启用   : {'是' if enabled else '否（已禁用）'}")
            print(f"      触发   : {reason}")
            print(f"      任务   : {', '.join(tasks)}")
        print(f"\n{'─'*60}\n")
        return

    logger = _setup_logger(log_dir)

    # 过滤要执行的阶段
    if args.stage:
        stage_names = set(args.stage)
        run_stages = [s for s in stages if s["name"] in stage_names]
        if not run_stages:
            logger.error("未找到指定阶段：%s", args.stage)
            sys.exit(1)
        # 手动指定阶段时忽略 only_on 条件
        check_conditions = False
    else:
        run_stages = stages
        check_conditions = True

    logger.info("=" * 60)
    logger.info("开始每日更新  日期=%s  dry_run=%s", placeholders["{today}"], args.dry_run)
    logger.info("项目路径: %s", project_root)
    logger.info("Python:   %s", python_exe)
    logger.info("=" * 60)

    total_ok = total_fail = 0
    skipped_stages = []

    for stage in run_stages:
        name = stage["name"]

        # 检查是否启用
        if not stage.get("enabled", True):
            logger.info("[%s] 跳过 — 阶段已在配置中禁用（enabled: false）", name)
            skipped_stages.append(name)
            continue

        # 检查触发条件
        if check_conditions:
            triggered, reason = _check_condition(stage.get("only_on"))
            if not triggered:
                logger.info("[%s] 跳过 — %s", name, reason)
                skipped_stages.append(name)
                continue
            logger.info("[%s] 触发 — %s", name, reason)
        else:
            logger.info("[%s] 手动指定，忽略触发条件", name)

        task_names = [t["name"] for t in stage.get("tasks", [])]
        logger.info("[%s] 并行执行 %d 个任务: %s", name, len(task_names), ", ".join(task_names))

        t0 = datetime.datetime.now()
        ok, fail = _run_stage(stage, project_root, python_exe, log_dir, placeholders, args.dry_run, logger)
        elapsed = (datetime.datetime.now() - t0).seconds

        total_ok += ok
        total_fail += fail
        status = "全部成功" if fail == 0 else f"{fail} 个失败"
        logger.info("[%s] 阶段结束 — %s，耗时 %ds\n", name, status, elapsed)

        # 如果阶段有失败，后续依赖阶段不应继续
        if fail > 0 and not args.stage:
            logger.warning("阶段 [%s] 有失败任务，后续阶段将继续执行（请检查日志）。", name)

    logger.info("=" * 60)
    logger.info(
        "全部完成  成功=%d  失败=%d  跳过阶段=%s",
        total_ok, total_fail,
        skipped_stages if skipped_stages else "无",
    )
    logger.info("日志目录: %s", log_dir)
    logger.info("=" * 60)

    sys.exit(1 if total_fail > 0 else 0)


if __name__ == "__main__":
    main()
