# 项目上下文

## 项目概况

这是一个 P6S AI 人脸识别摄像头管理后台，后端为 FastAPI，前端为静态页面。项目不依赖数据库，后台管理员账号通过环境变量配置。

核心链路：

1. 后台登录。
2. 配置并测试 P6S 摄像头连接。
3. 写入并固定脸库 Owner。
4. 创建会员人脸库。
5. 将 `styd_member_faces/` 中的会员头像上传到摄像头。
6. 接收摄像头陌生人识别事件。
7. 保存抓拍图并通过飞书通知。

## 关键文件

| 文件 | 说明 |
|------|------|
| `run.py` | 加载环境变量文件并启动 Uvicorn |
| `app/main.py` | FastAPI 入口，挂载认证、摄像头 API 与静态页面 |
| `app/routers/auth.py` | 环境变量管理员登录和 HMAC token 校验 |
| `app/routers/camera.py` | P6S 管理 API、事件回调、抓拍保存 |
| `app/services/p6s_camera.py` | P6S HTTP 接口封装 |
| `app/services/feishu.py` | 飞书文字通知和图片上传 |
| `app/static/camera.html` | 摄像头管理页面 |
| `app/static/camera.js` | 摄像头管理页面交互逻辑 |
| `styd_member_faces/` | 已抓取的会员头像 |
| `scripts/qypower-camera.service` | qypower-prod systemd 模板 |
| `scripts/qypower-nginx.conf` | qypower-prod Nginx 反代模板 |

## 环境变量

本地默认通过 `CAMERA_ENV_FILE=.env.local python run.py` 指定环境文件。服务器默认读取 `/etc/camera-face-guard/app.env`。

必须配置：

```env
CAMERA_SESSION_SECRET=...
CAMERA_ADMIN_USERNAME=admin
CAMERA_ADMIN_PASSWORD=...
P6S_CAMERA_HOST=http://...
P6S_CAMERA_USERNAME=admin
P6S_CAMERA_PASSWORD=...
P6S_FACE_OWNER=...
P6S_FACE_GROUP_ID=members
P6S_FACE_GROUP_NAME=会员人脸库
P6S_EVENT_SECRET=...
P6S_EVENT_IMAGE_DIR=/var/lib/camera-face-guard/p6s_events
P6S_FACE_DIR=/opt/camera-face-guard/styd_member_faces
PUBLIC_BASE_URL=http://...
```

飞书图片通知需要额外配置：

```env
FEISHU_WEBHOOK_URL=...
FEISHU_APP_ID=...
FEISHU_APP_SECRET=...
```

## 常用命令

本地启动：

```bash
CAMERA_ENV_FILE=.env.local CAMERA_RELOAD=true python run.py
```

编译检查：

```bash
python3 -m py_compile app/main.py app/routers/auth.py app/routers/camera.py app/services/p6s_camera.py app/services/feishu.py run.py
```

服务检查：

```bash
sudo systemctl status camera-face-guard
curl -I http://127.0.0.1:8000/camera
```

## 注意事项

- `P6S_FACE_OWNER` 是脸库写入安全码的基础，首次写入后必须长期固定。
- `P6S_EVENT_SECRET` 用于摄像头事件回调鉴权，摄像头配置的 URL 路径必须与环境变量一致。
- 先上传 1 张头像测试真机 XML 字段，再进行批量上传。
- 飞书文字通知只需要 webhook；发送抓拍图还需要飞书应用凭证。
