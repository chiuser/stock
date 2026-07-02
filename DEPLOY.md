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
rsync -a --delete \
  --exclude .git \
  --exclude .venv \
  --exclude .env.local \
  ./ qypower-prod:/opt/camera-face-guard/
```

如果需要同步已抓取的会员头像，确认 `styd_member_faces/` 已包含在 rsync 范围内。

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
P6S_CAMERA_PASSWORD=摄像头密码
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

FEISHU_WEBHOOK_URL=
FEISHU_WEBHOOK_SECRET=
FEISHU_APP_ID=
FEISHU_APP_SECRET=
```

配置说明：

- `P6S_EVENT_SECRET` 会出现在摄像头事件回调路径中，必须足够随机。
- `P6S_EVENT_IMAGE_LINK_SECRET` 用于图片查看 token，必须和 `P6S_EVENT_SECRET` 使用不同随机值。
- `P6S_EVENT_NOTIFY_KNOWN_PERSON=true` 表示匹配成功每次都通知。
- `P6S_EVENT_IMAGE_LINK_TTL_SECONDS=86400` 表示飞书里的图片查看链接有效期为 24 小时。
- `P6S_EVENT_RETENTION_DAYS=30` 表示服务器事件图片和处理记录默认保留 30 天。
- `FEISHU_WEBHOOK_URL` 和 `FEISHU_WEBHOOK_SECRET` 写真实值时只能写在远程 env 文件中，不能提交到仓库。

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

访问：

```text
http://服务器公网IP/camera
```

## 六、摄像头事件配置

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

## 七、验证

```bash
sudo systemctl status camera-face-guard
curl -I http://127.0.0.1:8000/camera
curl -I http://127.0.0.1/camera
curl -I http://82.156.198.180/camera
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

## 八、常见问题

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
