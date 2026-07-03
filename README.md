# Camera Face Guard

P6S AI 人脸识别摄像头管理后台，用于维护摄像头人脸库、接收陌生人识别事件，并通过飞书发送告警。

## 功能

- 管理 P6S 摄像头连接配置。
- 写入并固定摄像头脸库 Owner。
- 创建会员人脸库。
- 将本地会员头像批量上传到摄像头。
- 接收 P6S heartbeat 与 FaceReco 事件。
- 匹配成功时，每个独立识别事件都向飞书通知人员姓名和 ID。
- 未匹配成功时，保存陌生人抓拍图到服务器日期目录，并通过飞书发送保存路径和 token 查看链接。

## 当前开发约束

本仓库的摄像头事件推送链路按以下文档推进：

- `docs/camera-alarm-feishu-push-plan.html`
- `docs/camera-alarm-feishu-push-lld.md`

开发必须先更新技术方案和 LLD，再按 LLD 小步实现。真实配置只能写入本地 `.env.local` 或远程 `/etc/camera-face-guard/app.env`，不能写入 git。

## 本地运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env.local
CAMERA_ENV_FILE=.env.local CAMERA_RELOAD=true python run.py
```

启动后访问：

```text
http://127.0.0.1:8000/camera
```

## 配置

本地真实配置必须使用 `.env.local`，服务器真实配置使用 `/etc/camera-face-guard/app.env`。`.env.example` 只保留占位值。

```env
CAMERA_SESSION_SECRET=请使用随机长字符串
CAMERA_ADMIN_USERNAME=admin
CAMERA_ADMIN_PASSWORD=请设置后台登录密码

P6S_CAMERA_HOST=http://摄像头IP或域名
P6S_CAMERA_USERNAME=admin
P6S_CAMERA_PASSWORD=摄像头密码，空密码时保留这一行且值为空
P6S_FACE_OWNER=固定保存的脸库Owner
P6S_FACE_GROUP_ID=members
P6S_FACE_GROUP_NAME=会员
P6S_FACE_GROUP_MEMBERS_ID=会员脸库GroupID2
P6S_FACE_GROUP_MEMBERS_NAME=会员
P6S_FACE_GROUP_COACHES_ID=教练脸库GroupID2
P6S_FACE_GROUP_COACHES_NAME=教练
P6S_FACE_GROUP_STAFF_ID=员工脸库GroupID2
P6S_FACE_GROUP_STAFF_NAME=员工
P6S_FACE_GROUP_THRESHOLD=

P6S_EVENT_SECRET=摄像头事件回调鉴权token
P6S_EVENT_IMAGE_DIR=/var/lib/camera-face-guard/p6s_events
P6S_EVENT_IMAGE_LINK_SECRET=图片查看链接token密钥
P6S_EVENT_IMAGE_LINK_TTL_SECONDS=86400
P6S_EVENT_NOTIFY_KNOWN_PERSON=true
P6S_EVENT_MAX_BODY_BYTES=5242880
P6S_EVENT_MAX_IMAGE_BYTES=5242880
P6S_EVENT_RETENTION_DAYS=30
P6S_FACE_DIR=/opt/camera-face-guard/styd_member_faces
PUBLIC_BASE_URL=http://82.156.198.180
P6S_EVENT_IMAGE_PUBLIC_BASE_URL=http://82.156.198.180/api/p6s/event-images/view

FEISHU_WEBHOOK_URL=飞书机器人webhook
FEISHU_WEBHOOK_SECRET=飞书机器人签名密钥
FEISHU_APP_ID=可选，仅内嵌图片时需要
FEISHU_APP_SECRET=可选，仅内嵌图片时需要
```

`P6S_FACE_OWNER` 必须长期固定保存。后台首次写入 Owner 后，请把页面返回的 Owner 写回环境变量文件。

如果摄像头使用空密码，必须在 `.env.local` 中保留 `P6S_CAMERA_PASSWORD=` 这个 key。程序会把 key 存在但值为空识别为“空密码已配置”，而不是“未配置”。

事件推送相关配置说明：

- `P6S_EVENT_SECRET`：摄像头事件回调路径 token，事件入口为 `/api/p6s/events/<P6S_EVENT_SECRET>`。
- `P6S_FACE_GROUP_MEMBERS_ID`、`P6S_FACE_GROUP_COACHES_ID`、`P6S_FACE_GROUP_STAFF_ID`：服务端按这些 `GroupID2` 把识别成功事件映射为会员、教练、员工。
- `P6S_EVENT_IMAGE_DIR`：服务器保存原始事件、处理记录、陌生人图片和 token 映射的根目录。
- `P6S_EVENT_IMAGE_LINK_SECRET`：生成和校验图片查看 token 的随机密钥。
- `P6S_EVENT_IMAGE_LINK_TTL_SECONDS`：图片查看链接有效期，首版为 24 小时。
- `P6S_EVENT_NOTIFY_KNOWN_PERSON`：匹配成功是否通知，当前需求必须为 `true`。
- `P6S_EVENT_RETENTION_DAYS`：事件图片与记录默认保留天数，首版为 30 天。
- `P6S_EVENT_IMAGE_PUBLIC_BASE_URL`：飞书中图片查看链接的公网前缀。
- `FEISHU_WEBHOOK_SECRET`：飞书自定义机器人开启签名校验时必须配置。

摄像头 HTTP 事件推送可用脚本重复配置和审计：

```bash
python3 scripts/configure_p6s_http_events.py
python3 scripts/configure_p6s_http_events.py --apply --test
```

脚本默认读取 `.env.local`，只输出脱敏摘要，不打印完整 `P6S_EVENT_SECRET`、摄像头密码或完整事件回调路径。

人脸识别规则启用使用最小化脚本，脚本会先保存当前完整 XML 备份，然后只修改 `RecoRule/Enable`：

```bash
python3 scripts/configure_p6s_face_reco_rule.py
python3 scripts/configure_p6s_face_reco_rule.py --apply
```

## 事件处理目标

- 摄像头通过 P6SEvent HTTP V2 推送 `FaceReco` 到远程服务器。
- 匹配成功：飞书消息包含姓名、人员 ID、摄像头序列号、识别时间和事件 ID；不同识别事件都通知。会员、教练、员工分别使用“会员入场提醒”“教练入场提醒”“员工入场提醒”。
- 未匹配成功：服务器保存人脸抓拍图到 `strangers/YYYY-MM-DD/`，飞书消息包含保存路径和可点击图片链接。
- 重复投递：只对同一个事件的缓存重放或网络重试做幂等，不按人员维度合并不同事件。
- 图片查看：飞书链接使用 `/api/p6s/event-images/view/<token>`，服务器校验 token 后返回图片；旧的裸文件名图片入口只作为管理员排障入口。

事件存储保留期可用脚本手动清理，默认只 dry-run：

```bash
python3 scripts/cleanup_p6s_event_store.py
python3 scripts/cleanup_p6s_event_store.py --apply
```

## API 路径

- `POST /api/auth/login`：后台登录。
- `GET /api/camera/status`：查看摄像头、人脸目录、事件目录、飞书配置状态。
- `POST /api/camera/owner`：写入或生成摄像头 Owner。
- `POST /api/camera/face-group`：创建摄像头人脸库。
- `POST /api/camera/faces/upload`：上传单张会员头像。
- `POST /api/camera/faces/upload-batch`：批量上传本地会员头像。
- `POST /api/camera/feishu/test`：发送飞书测试通知。
- `POST /api/p6s/events/<P6S_EVENT_SECRET>`：摄像头事件回调地址。
- `GET /api/p6s/event-images/view/<token>`：陌生人图片 token 查看地址。

## 目录

- `app/routers/auth.py`：环境变量管理员登录和 token 校验。
- `app/routers/camera.py`：摄像头管理和 P6S 事件回调 API。
- `app/services/p6s_camera.py`：P6S HTTP 接口封装。
- `app/services/feishu.py`：飞书通知与图片上传封装。
- `app/services/event_store.py`：按 LLD 开发的事件、图片和处理记录落盘模块。
- `app/services/image_links.py`：按 LLD 开发的图片 token 链接模块。
- `app/services/p6s_events.py`：按 LLD 开发的 P6S 事件解析与分流模块。
- `app/static/`：后台页面。
- `styd_member_faces/`：已抓取的会员头像目录。
- `scripts/`：qypower-prod 部署模板。
