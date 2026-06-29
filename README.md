# Camera Face Guard

P6S AI 人脸识别摄像头管理后台，用于维护摄像头人脸库、接收陌生人识别事件，并通过飞书发送告警。

## 功能

- 管理 P6S 摄像头连接配置。
- 写入并固定摄像头脸库 Owner。
- 创建会员人脸库。
- 将本地会员头像批量上传到摄像头。
- 接收 P6S heartbeat 与 FaceReco 事件。
- 保存陌生人抓拍图并触发飞书通知。

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

本地建议使用 `.env.local`，服务器建议使用 `/etc/camera-face-guard/app.env`。

```env
CAMERA_SESSION_SECRET=请使用随机长字符串
CAMERA_ADMIN_USERNAME=admin
CAMERA_ADMIN_PASSWORD=请设置后台登录密码

P6S_CAMERA_HOST=http://摄像头IP或域名
P6S_CAMERA_USERNAME=admin
P6S_CAMERA_PASSWORD=摄像头密码
P6S_FACE_OWNER=固定保存的脸库Owner
P6S_FACE_GROUP_ID=members
P6S_FACE_GROUP_NAME=会员人脸库
P6S_FACE_GROUP_THRESHOLD=

P6S_EVENT_SECRET=摄像头事件回调鉴权token
P6S_EVENT_IMAGE_DIR=/var/lib/camera-face-guard/p6s_events
P6S_FACE_DIR=/opt/camera-face-guard/styd_member_faces
PUBLIC_BASE_URL=https://你的域名

FEISHU_WEBHOOK_URL=飞书机器人webhook
FEISHU_APP_ID=如需图片通知再配置
FEISHU_APP_SECRET=如需图片通知再配置
```

`P6S_FACE_OWNER` 必须长期固定保存。后台首次写入 Owner 后，请把页面返回的 Owner 写回环境变量文件。

## API 路径

- `POST /api/auth/login`：后台登录。
- `GET /api/camera/status`：查看摄像头、人脸目录、事件目录、飞书配置状态。
- `POST /api/camera/owner`：写入或生成摄像头 Owner。
- `POST /api/camera/face-group`：创建摄像头人脸库。
- `POST /api/camera/faces/upload`：上传单张会员头像。
- `POST /api/camera/faces/upload-batch`：批量上传本地会员头像。
- `POST /api/camera/feishu/test`：发送飞书测试通知。
- `POST /api/p6s/events/<P6S_EVENT_SECRET>`：摄像头事件回调地址。

## 目录

- `app/routers/auth.py`：环境变量管理员登录和 token 校验。
- `app/routers/camera.py`：摄像头管理和 P6S 事件回调 API。
- `app/services/p6s_camera.py`：P6S HTTP 接口封装。
- `app/services/feishu.py`：飞书通知与图片上传封装。
- `app/static/`：后台页面。
- `styd_member_faces/`：已抓取的会员头像目录。
- `scripts/`：qypower-prod 部署模板。
