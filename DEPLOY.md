# 部署指南

本文档面向 qypower-prod 上的 P6S 摄像头管理后台部署。

## 一、服务器准备

```bash
sudo apt update
sudo apt install -y python3-venv nginx
sudo mkdir -p /opt/camera-face-guard /etc/camera-face-guard /var/log/camera-face-guard /var/lib/camera-face-guard/p6s_events
sudo chown -R ubuntu:ubuntu /opt/camera-face-guard /var/log/camera-face-guard /var/lib/camera-face-guard
sudo chmod 750 /etc/camera-face-guard
```

## 二、上传代码

在本地执行：

```bash
scripts/deploy_qypower_prod.sh --dry-run
scripts/deploy_qypower_prod.sh --skip-deps
```

部署脚本会自动执行本地验证、同步代码、远程验证和服务重启。脚本默认排除 `.env*`、`.venv/`、日志、会员图片、CSV、教练/员工图片目录、离线 ShowDoc 镜像等本地数据，避免把真实配置或大体积数据误同步到服务器。

如果需要同步已抓取的会员头像，不要使用默认部署脚本直接带上数据；应单独确认目标目录、数据来源和回滚方式后再执行专门的数据同步。

## 三、安装依赖

在服务器执行：

```bash
cd /opt/camera-face-guard
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 四、配置环境变量

创建 `/etc/camera-face-guard/app.env`：

```env
CAMERA_SESSION_SECRET=请使用随机长字符串
CAMERA_ADMIN_USERNAME=admin
CAMERA_ADMIN_PASSWORD=请设置后台登录密码

P6S_CAMERA_HOST=http://摄像头IP或域名
P6S_CAMERA_USERNAME=admin
P6S_CAMERA_PASSWORD=摄像头密码，空密码时保留这一行且值为空
P6S_FACE_OWNER=首次写入Owner后回填这里
P6S_FACE_GROUP_ID=members
P6S_FACE_GROUP_NAME=会员人脸库
P6S_FACE_GROUP_THRESHOLD=

P6S_EVENT_SECRET=请使用随机长字符串
P6S_EVENT_IMAGE_DIR=/var/lib/camera-face-guard/p6s_events
P6S_EVENT_IMAGE_LINK_SECRET=请使用随机长字符串
P6S_EVENT_IMAGE_LINK_TTL_SECONDS=86400
P6S_EVENT_NOTIFY_KNOWN_PERSON=true
P6S_EVENT_MAX_BODY_BYTES=5242880
P6S_EVENT_MAX_IMAGE_BYTES=5242880
P6S_EVENT_RETENTION_DAYS=30
P6S_FACE_DIR=/opt/camera-face-guard/styd_member_faces
PUBLIC_BASE_URL=http://82.156.198.180
P6S_EVENT_IMAGE_PUBLIC_BASE_URL=http://82.156.198.180/api/p6s/event-images/view
P6S_FACE_GROUP_MEMBERS_ID=会员脸库GroupID2
P6S_FACE_GROUP_MEMBERS_NAME=会员
P6S_FACE_GROUP_COACHES_ID=教练脸库GroupID2
P6S_FACE_GROUP_COACHES_NAME=教练
P6S_FACE_GROUP_STAFF_ID=员工脸库GroupID2
P6S_FACE_GROUP_STAFF_NAME=员工

FEISHU_WEBHOOK_URL=
FEISHU_WEBHOOK_SECRET=
FEISHU_APP_ID=
FEISHU_APP_SECRET=

DATABASE_URL=postgresql+psycopg://camera_face_guard:数据库密码@127.0.0.1:5432/camera_face_guard
ATTENDANCE_DB_ENABLED=true
ATTENDANCE_NOTIFY_DEDUP_ENABLED=true
ATTENDANCE_NOTIFY_DEDUP_WINDOW_SECONDS=7200
ATTENDANCE_REPORT_TIMEZONE=Asia/Shanghai
ATTENDANCE_DAILY_REPORT_ENABLED=true
ATTENDANCE_DAILY_REPORT_TIME=22:00
ATTENDANCE_DAILY_REPORT_TITLE=每日入场情况统计
ATTENDANCE_DB_CONNECT_TIMEOUT_SECONDS=3
ATTENDANCE_SQL_ECHO=false
```

配置说明：

- `P6S_EVENT_SECRET` 会出现在摄像头事件回调路径中，必须足够随机。
- `P6S_EVENT_IMAGE_LINK_SECRET` 用于图片查看 token，必须和 `P6S_EVENT_SECRET` 使用不同随机值。
- `P6S_EVENT_NOTIFY_KNOWN_PERSON=true` 表示匹配成功每次都通知。
- `P6S_FACE_GROUP_MEMBERS_ID`、`P6S_FACE_GROUP_COACHES_ID`、`P6S_FACE_GROUP_STAFF_ID` 用于把匹配成功事件映射为会员、教练、员工，并生成对应飞书标题。
- `P6S_EVENT_IMAGE_LINK_TTL_SECONDS=86400` 表示飞书里的图片查看链接有效期为 24 小时。
- `P6S_EVENT_RETENTION_DAYS=30` 表示服务器事件图片和处理记录默认保留 30 天。
- `FEISHU_WEBHOOK_URL` 和 `FEISHU_WEBHOOK_SECRET` 写真实值时只能写在远程 env 文件中，不能提交到仓库。
- `ATTENDANCE_DB_ENABLED` 只控制是否写入 PostgreSQL；`ATTENDANCE_NOTIFY_DEDUP_ENABLED` 只控制非陌生人 2 小时提醒去重。两者不要混用。
- `ATTENDANCE_DAILY_REPORT_TIME=22:00` 表示每天晚上 22:00 生成日报快照并发送标题为“每日入场情况统计”的飞书日报。

保护环境变量文件：

```bash
sudo chown root:root /etc/camera-face-guard/app.env
sudo chmod 640 /etc/camera-face-guard/app.env
```

## 五、安装 systemd 和 Nginx

```bash
sudo cp /opt/camera-face-guard/scripts/qypower-camera.service /etc/systemd/system/camera-face-guard.service
sudo cp /opt/camera-face-guard/scripts/qypower-nginx.conf /etc/nginx/sites-available/camera-face-guard
sudo ln -sf /etc/nginx/sites-available/camera-face-guard /etc/nginx/sites-enabled/camera-face-guard
sudo rm -f /etc/nginx/sites-enabled/default
sudo systemctl daemon-reload
sudo systemctl enable --now camera-face-guard
sudo nginx -t
sudo systemctl reload nginx
```

`qypower-camera.service` 和 `qypower-nginx.conf` 默认关闭 HTTP access log，因为事件回调 URL 与图片查看 URL 都包含 token。排查业务事件时优先查看 `P6S_EVENT_IMAGE_DIR` 下的事件记录，服务启动异常再看 `journalctl -u camera-face-guard`。

如果摄像头使用空密码，必须保留 `P6S_CAMERA_PASSWORD=` 这个 key。程序会把 key 存在但值为空识别为“空密码已配置”。

访问：

```text
http://服务器公网IP/camera
```

## 六、PostgreSQL 与入场表迁移

服务器需要先准备 PostgreSQL 数据库，再开启 `ATTENDANCE_DB_ENABLED=true`：

```bash
sudo apt install -y postgresql
sudo -u postgres psql
```

在 `psql` 中创建用户和库，密码请使用随机长字符串，随后写入 `/etc/camera-face-guard/app.env` 的 `DATABASE_URL`：

```sql
create user camera_face_guard with password '请替换为随机密码';
create database camera_face_guard owner camera_face_guard;
\q
```

部署脚本会在远程 `/etc/camera-face-guard/app.env` 中发现 `DATABASE_URL` 后执行：

```bash
cd /opt/camera-face-guard
.venv/bin/alembic upgrade head
```

也可以手工执行同一命令。迁移完成后，可运行数据库验证：

```bash
cd /opt/camera-face-guard
.venv/bin/python scripts/validate_attendance_flow.py --env-file /etc/camera-face-guard/app.env
```

验证脚本会写入 `p6s-validation-*` 临时数据，验证 2 小时去重、关闭去重、陌生人记录和日报聚合，然后自动清理。

## 七、摄像头事件配置

在 P6S 摄像头事件上报配置 `/System/HTTPEventServerConfigV2` 中填写：

```text
Enable=true
Protocol=http
Host=82.156.198.180
Port=80
URLPath=/api/p6s/events/<P6S_EVENT_SECRET>
AuthMode=none
CacheEventEnable=true
```

同时检查这些配置已经启用：

- `/System/AIEventCfg`：AI 事件上传启用。
- `/System/EventPushMode`：人脸识别事件推送模式正常。
- `/AI/FaceSnapshotCfg`：人脸抓拍和推送启用。
- `/FaceReco/1/RecoRuleList`：人脸识别规则、识别区域和联动推送启用。

如果后续配置域名和 HTTPS，把 `PUBLIC_BASE_URL`、`P6S_EVENT_IMAGE_PUBLIC_BASE_URL` 与摄像头事件地址一起改为 HTTPS 地址。

也可以在本地使用脚本配置和审计摄像头，脚本默认读取 `.env.local` 并输出脱敏摘要：

```bash
python3 scripts/configure_p6s_http_events.py
python3 scripts/configure_p6s_http_events.py --apply --test
```

如果审计发现 `/FaceReco/1/RecoRuleList` 中 `RecoRule.Enable=false`，使用最小化脚本启用识别规则。脚本会先保存当前完整 XML 备份，然后只修改 `RecoRule/Enable`：

```bash
python3 scripts/configure_p6s_face_reco_rule.py
python3 scripts/configure_p6s_face_reco_rule.py --apply
```

## 八、验证

```bash
sudo systemctl status camera-face-guard
curl -sS -o /dev/null -w 'UPSTREAM_GET:%{http_code}\n' http://127.0.0.1:8000/camera
curl -sS -o /dev/null -w 'NGINX_GET:%{http_code}\n' http://127.0.0.1/camera
curl -sS -o /dev/null -w 'PUBLIC_GET:%{http_code}\n' http://82.156.198.180/camera
```

后台页面内建议按这个顺序验证：

1. 登录后台。
2. 查看摄像头配置状态。
3. 测试摄像头连接。
4. 写入并记录 Owner。
5. 创建会员人脸库。
6. 上传 1 张头像测试。
7. 批量上传头像。
8. 配置飞书机器人后发送测试通知。

事件链路建议按这个顺序验证：

1. 使用摄像头 `/System/HTTPEventServerTest` 测试公网事件入口。
2. 确认服务器 `P6S_EVENT_IMAGE_DIR/raw/YYYY-MM-DD/` 下出现原始事件。
3. 触发已入库人员识别，确认飞书收到姓名和人员 ID。
4. 触发未入库人员识别，确认服务器保存图片到 `strangers/YYYY-MM-DD/`。
5. 点击飞书图片链接，确认能通过 `/api/p6s/event-images/view/<token>` 查看图片。
6. 重复投递同一事件时，不应重复发送飞书通知。

入场数据库和日报链路建议按这个顺序验证：

1. `DATABASE_URL=... .venv/bin/alembic current` 确认迁移版本为 `20260703_0001`。
2. `.venv/bin/python scripts/import_attendance_people.py --env-file /etc/camera-face-guard/app.env` 先 dry-run。
3. 确认会员 244、教练 15、员工 4 后，再执行 `--apply` 写入人员基础表。
4. `.venv/bin/python scripts/validate_attendance_flow.py --env-file /etc/camera-face-guard/app.env` 验证写库、去重和日报聚合。
5. 真实识别后查询 `/api/attendance/reports/daily?date=YYYY-MM-DD` 验证当天统计。

事件目录清理不自动启用。需要手动清理过期事件时，先 dry-run，再 apply：

```bash
python3 scripts/cleanup_p6s_event_store.py
python3 scripts/cleanup_p6s_event_store.py --apply
```

## 九、常见问题

### 登录提示密钥未配置

检查 `/etc/camera-face-guard/app.env` 是否包含 `CAMERA_SESSION_SECRET`。

### 登录提示后台密码未配置

检查 `/etc/camera-face-guard/app.env` 是否包含 `CAMERA_ADMIN_PASSWORD`。

### 摄像头连接失败

确认服务器能访问 `P6S_CAMERA_HOST`，并检查摄像头账号密码是否正确。

### 收不到陌生人事件

确认摄像头事件上报 URL 使用公网可访问地址，并且路径中的 `P6S_EVENT_SECRET` 与环境变量一致。

### 飞书通知签名失败

确认远程 `/etc/camera-face-guard/app.env` 中的 `FEISHU_WEBHOOK_SECRET` 与飞书机器人设置一致。

### 飞书里的图片链接打不开

确认 `P6S_EVENT_IMAGE_PUBLIC_BASE_URL` 是公网可访问地址，并且 Nginx 已代理 `/api/p6s/event-images/view/<token>` 到 FastAPI。

### 飞书没有内嵌图片

首版不依赖飞书内嵌图片能力。陌生人图片通过服务器 token 链接查看；只有后续升级为飞书应用机器人时，才需要 `FEISHU_APP_ID` 和 `FEISHU_APP_SECRET`。
