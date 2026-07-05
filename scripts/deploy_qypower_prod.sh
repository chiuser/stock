#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="${REMOTE_HOST:-qypower-prod}"
REMOTE_DIR="${REMOTE_DIR:-/opt/camera-face-guard}"
SERVICE_NAME="${SERVICE_NAME:-camera-face-guard}"
LOCAL_PYTHON="${LOCAL_PYTHON:-python3}"

DRY_RUN=0
SKIP_LOCAL_CHECK=0
SKIP_REMOTE_CHECK=0
SKIP_DEPS=0
SKIP_RESTART=0

usage() {
  cat <<'EOF'
Usage: scripts/deploy_qypower_prod.sh [options]

Deploy local Camera Face Guard code to qypower-prod.

Options:
  --dry-run           Show rsync changes without writing remote files.
  --skip-local-check  Skip local py_compile and fixture validation.
  --skip-remote-check Skip remote py_compile, fixture validation, and HTTP checks.
  --skip-deps         Skip remote pip install -r requirements.txt.
  --skip-restart      Skip systemd restart.
  -h, --help          Show this help.

Environment overrides:
  REMOTE_HOST=qypower-prod
  REMOTE_DIR=/opt/camera-face-guard
  SERVICE_NAME=camera-face-guard
  LOCAL_PYTHON=python3
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      ;;
    --skip-local-check)
      SKIP_LOCAL_CHECK=1
      ;;
    --skip-remote-check)
      SKIP_REMOTE_CHECK=1
      ;;
    --skip-deps)
      SKIP_DEPS=1
      ;;
    --skip-restart)
      SKIP_RESTART=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PY_FILES=(
  app/db/__init__.py
  app/db/attendance_repo.py
  app/db/config.py
  app/db/recognition_repo.py
  app/db/session.py
  app/routers/attendance.py
  app/services/p6s_events.py
  app/services/attendance.py
  app/services/face_gallery.py
  app/services/face_recheck.py
  app/services/feishu.py
  app/services/recognition_monitor.py
  app/services/reports.py
  app/services/report_scheduler.py
  app/main.py
  app/routers/camera.py
  app/routers/recognition_monitor.py
  alembic/versions/20260705_0003_create_recognition_events.py
  alembic/versions/20260705_0004_create_recognition_event_faces.py
  alembic/versions/20260705_0005_add_final_recognition_decision.py
  scripts/cleanup_p6s_event_store.py
  scripts/backfill_recognition_events.py
  scripts/generate_attendance_report.py
  scripts/import_attendance_people.py
  scripts/validate_attendance_flow.py
  scripts/validate_p6s_event_flow.py
)

RSYNC_EXCLUDES=(
  --exclude .git/
  --exclude .idea/
  --exclude .venv/
  --exclude .DS_Store
  --exclude '*/.DS_Store'
  --exclude __pycache__/
  --exclude '*.pyc'
  --exclude '.env'
  --exclude '.env.*'
  --exclude docs/p6scgi-showdoc/
  --exclude docs/styd-member-assets.md
  --exclude logs/
  --exclude '*.zip'
  --exclude styd_member_faces/
  --exclude styd_member_faces_full/
  --exclude 'styd_member_faces_new_*/'
  --exclude 'styd_member_faces*_p6s_named/'
  --exclude styd_member_sync_runs/
  --exclude styd_member_ids.txt
  --exclude teacher/
  --exclude teacher_p6s_named/
  --exclude staff/
  --exclude staff_p6s_named/
  --exclude '*.csv'
  --exclude '*.jpg'
  --exclude '*.jpeg'
  --exclude '*.png'
  --exclude '*.backup_before_merge_*'
)

log() {
  printf '[deploy] %s\n' "$*"
}

if [[ "$SKIP_LOCAL_CHECK" -eq 0 ]]; then
  log "running local syntax check"
  "$LOCAL_PYTHON" -m py_compile "${PY_FILES[@]}"
  log "running local fixture validation"
  "$LOCAL_PYTHON" scripts/validate_p6s_event_flow.py
else
  log "skipping local checks"
fi

RSYNC_FLAGS=(-az --delete --itemize-changes)
if [[ "$DRY_RUN" -eq 1 ]]; then
  RSYNC_FLAGS+=(--dry-run)
fi

log "syncing code to ${REMOTE_HOST}:${REMOTE_DIR}"
if [[ "$DRY_RUN" -eq 0 ]]; then
  log "creating remote pre-deploy backup"
  ssh "$REMOTE_HOST" "REMOTE_DIR='$REMOTE_DIR' bash -s" <<'REMOTE_BACKUP'
set -euo pipefail
timestamp="$(date +%Y%m%d%H%M%S)"
backup_dir="${HOME}/camera-face-guard-backups/backup-${timestamp}"
mkdir -p "$(dirname "$backup_dir")"
rsync -a --delete \
  --exclude .venv/ \
  --exclude logs/ \
  --exclude '*.zip' \
  --exclude styd_member_faces/ \
  --exclude styd_member_faces_full/ \
  --exclude 'styd_member_faces_new_*/' \
  --exclude 'styd_member_faces*_p6s_named/' \
  --exclude styd_member_sync_runs/ \
  --exclude teacher/ \
  --exclude teacher_p6s_named/ \
  --exclude staff/ \
  --exclude staff_p6s_named/ \
  "$REMOTE_DIR/" "$backup_dir/"
printf '[remote] backup_dir=%s\n' "$backup_dir"
REMOTE_BACKUP
fi

rsync "${RSYNC_FLAGS[@]}" "${RSYNC_EXCLUDES[@]}" ./ "${REMOTE_HOST}:${REMOTE_DIR}/"

if [[ "$DRY_RUN" -eq 1 ]]; then
  log "dry-run complete; no remote files were changed"
  exit 0
fi

REMOTE_SCRIPT=$(cat <<'REMOTE_EOF'
set -euo pipefail
cd "$REMOTE_DIR"

if [[ "$SKIP_DEPS" -eq 0 ]]; then
  if [[ ! -x .venv/bin/python ]]; then
    python3 -m venv .venv
  fi
  .venv/bin/python -m pip install -r requirements.txt
else
  printf '[remote] skipping dependency install\n'
fi

if [[ "$SKIP_REMOTE_CHECK" -eq 0 ]]; then
  .venv/bin/python -m py_compile \
    app/db/__init__.py \
    app/db/attendance_repo.py \
    app/db/config.py \
    app/db/recognition_repo.py \
    app/db/session.py \
    app/routers/attendance.py \
    app/routers/camera.py \
    app/routers/recognition_monitor.py \
    app/services/attendance.py \
    app/services/face_gallery.py \
    app/services/face_recheck.py \
    app/services/p6s_events.py \
    app/services/feishu.py \
    app/services/recognition_monitor.py \
    app/services/reports.py \
    app/services/report_scheduler.py \
    app/main.py \
    alembic/versions/20260705_0003_create_recognition_events.py \
    alembic/versions/20260705_0004_create_recognition_event_faces.py \
    alembic/versions/20260705_0005_add_final_recognition_decision.py \
    scripts/cleanup_p6s_event_store.py \
    scripts/backfill_recognition_events.py \
    scripts/generate_attendance_report.py \
    scripts/import_attendance_people.py \
    scripts/validate_attendance_flow.py \
    scripts/validate_p6s_event_flow.py
  .venv/bin/python scripts/validate_p6s_event_flow.py
else
  printf '[remote] skipping remote checks before restart\n'
fi

DATABASE_URL="$(
  sudo python3 - <<'PY'
from pathlib import Path

env_path = Path("/etc/camera-face-guard/app.env")
if env_path.exists():
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() == "DATABASE_URL":
            print(value.strip().strip('"').strip("'"))
            break
PY
)"
export DATABASE_URL

if [[ -n "$DATABASE_URL" ]]; then
  printf '[remote] running alembic upgrade head\n'
  .venv/bin/alembic upgrade head
else
  printf '[remote] DATABASE_URL is not configured; skipping alembic migration\n'
fi

if [[ "$SKIP_RESTART" -eq 0 ]]; then
  sudo systemctl restart "$SERVICE_NAME"
  sudo systemctl is-active "$SERVICE_NAME"
else
  printf '[remote] skipping service restart\n'
fi

if [[ "$SKIP_REMOTE_CHECK" -eq 0 ]]; then
  wait_for_http() {
    path="$1"
    label="$2"
    for _attempt in $(seq 1 20); do
      code="$(curl -sS -o /dev/null -w '%{http_code}' "http://127.0.0.1:8000${path}" 2>/dev/null || true)"
      if [[ "$code" == "200" ]]; then
        printf '[remote] %s_http=%s\n' "$label" "$code"
        return 0
      fi
      sleep 0.5
    done
    printf '[remote] %s_http=%s\n' "$label" "$code"
    return 1
  }
  wait_for_http /api/docs docs
  wait_for_http /camera camera
  wait_for_http /recognition-monitor recognition_monitor
  grep -RIn '会员入场提醒\|教练入场提醒\|员工入场提醒\|发现陌生人入场' app/services scripts | head -20
fi
REMOTE_EOF
)

log "running remote deploy checks and restart"
ssh "$REMOTE_HOST" \
  "REMOTE_DIR='$REMOTE_DIR' SERVICE_NAME='$SERVICE_NAME' SKIP_DEPS='$SKIP_DEPS' SKIP_REMOTE_CHECK='$SKIP_REMOTE_CHECK' SKIP_RESTART='$SKIP_RESTART' bash -s" \
  <<<"$REMOTE_SCRIPT"

log "deployment complete"
