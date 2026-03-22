#!/usr/bin/env bash
# =============================================================
# 安装/更新定时任务（crontab）
#
# 用法：
#   bash scripts/install_cron.sh          # 安装定时任务
#   bash scripts/install_cron.sh --remove # 移除本项目的定时任务
#   bash scripts/install_cron.sh --show   # 仅显示将要安装的内容
#
# 说明：
#   - 只修改带有 "# stock-update" 标记的行，不影响已有其他 cron 任务
#   - 修改 update_config.yaml 中的 cron 字段后，重新执行本脚本即可
#   - 安装前会备份当前 crontab 到 /tmp/crontab.bak
# =============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
CONFIG_FILE="$SCRIPT_DIR/update_config.yaml"
DAILY_UPDATE="$SCRIPT_DIR/daily_update.py"
MARKER="# stock-update"

# 颜色输出
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# 解析参数
MODE="install"
for arg in "$@"; do
  case $arg in
    --remove) MODE="remove" ;;
    --show)   MODE="show"   ;;
    --help|-h)
      sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
  esac
done

# 检查依赖
command -v python3 &>/dev/null || error "找不到 python3"
python3 -c "import yaml" 2>/dev/null || error "请先安装 PyYAML: pip install pyyaml"

# 用 Python 从 YAML 读取配置并生成 cron 行
CRON_LINES=$(python3 - <<EOF
import yaml, sys
from pathlib import Path

config_path = "$CONFIG_FILE"
daily_update = "$DAILY_UPDATE"
marker = "$MARKER"

with open(config_path, encoding="utf-8") as f:
    config = yaml.safe_load(f)

g = config.get("global", {})
python_exe = g.get("python", "python3")
project_root = g.get("project_root", "$PROJECT_ROOT")

# 若 python_exe 是相对路径，相对项目根目录解析
from pathlib import Path
p = Path(python_exe)
if not p.is_absolute() and str(p) != "python3":
    python_exe = str(Path(project_root) / p)

lines = [f"{marker}-begin"]
lines.append(f"# 自动生成，修改 update_config.yaml 后重新执行 install_cron.sh")
lines.append(f"# 项目: {project_root}")
lines.append("")

for stage in config.get("stages", []):
    cron = stage.get("cron", "")
    if not cron:
        continue
    name  = stage["name"]
    tasks = [t["name"] for t in stage.get("tasks", [])]
    log_dir = g.get("log_dir", "logs/daily_update")
    if not Path(log_dir).is_absolute():
        log_dir = str(Path(project_root) / log_dir)

    log_file = f"{log_dir}/cron_{name.replace(' ', '_')}.log"
    cmd = (
        f"{python_exe} {daily_update} "
        f"--stage '{name}' "
        f">> {log_file} 2>&1"
    )
    lines.append(f"# 阶段: {name}  任务: {', '.join(tasks)}")
    lines.append(f"{cron}  {cmd}  {marker}")
    lines.append("")

lines.append(f"{marker}-end")
print("\n".join(lines))
EOF
)

if [[ "$MODE" == "show" ]]; then
  echo ""
  info "将要安装的 cron 条目："
  echo ""
  echo "$CRON_LINES"
  echo ""
  exit 0
fi

# ---- 备份当前 crontab ----
BACKUP="/tmp/crontab.bak.$(date +%Y%m%d%H%M%S)"
crontab -l > "$BACKUP" 2>/dev/null || true
info "当前 crontab 已备份至 $BACKUP"

# ---- 移除旧的 stock-update 条目 ----
CURRENT=$(crontab -l 2>/dev/null || true)
# 删除 marker-begin 到 marker-end 之间的所有行（含边界）
CLEANED=$(python3 - <<EOF
import re, sys
text = """$CURRENT"""
# 去掉 begin/end 块
pattern = r"$MARKER-begin.*?$MARKER-end\n?"
cleaned = re.sub(pattern, "", text, flags=re.DOTALL)
# 去掉尾部多余空行（保留最多一个）
cleaned = re.sub(r'\n{3,}', '\n\n', cleaned).rstrip('\n')
print(cleaned)
EOF
)

if [[ "$MODE" == "remove" ]]; then
  if [[ -z "$CLEANED" ]]; then
    (echo "") | crontab -
  else
    (echo "$CLEANED") | crontab -
  fi
  info "已移除所有 stock-update 定时任务。"
  exit 0
fi

# ---- 安装 ----
if [[ -z "$CLEANED" ]]; then
  NEW_CRONTAB="$CRON_LINES"
else
  NEW_CRONTAB="$CLEANED"$'\n\n'"$CRON_LINES"
fi

(echo "$NEW_CRONTAB") | crontab -

info "定时任务已安装成功！"
echo ""
warn "请确认以下内容："
echo "  1. update_config.yaml 中 project_root 已设置为正确的绝对路径"
echo "  2. Python 路径 (python/python3) 可访问项目依赖（建议使用虚拟环境绝对路径）"
echo "  3. 环境变量（TUSHARE_TOKEN、DB_PASSWORD 等）已在 env_file 中配置"
echo ""
info "当前 crontab："
echo ""
crontab -l
echo ""
info "可运行以下命令验证配置（--list 查看今日触发状态，--dry-run 模拟执行）："
echo "  python3 $DAILY_UPDATE --list"
echo "  python3 $DAILY_UPDATE --dry-run"
