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
P6S_FACE_DIR=/opt/camera-face-guard/styd_member_faces
PUBLIC_BASE_URL=http://服务器公网IP或域名

FEISHU_WEBHOOK_URL=
FEISHU_APP_ID=
FEISHU_APP_SECRET=
```

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

访问：

```text
http://服务器公网IP/camera
```

## 六、摄像头事件配置

在 P6S 摄像头事件上报配置中填写：

```text
http://服务器公网IP/api/p6s/events/<P6S_EVENT_SECRET>
```

如果后续配置域名和 HTTPS，把 `PUBLIC_BASE_URL` 与摄像头事件地址一起改为 HTTPS 地址。

## 七、验证

```bash
sudo systemctl status camera-face-guard
curl -I http://127.0.0.1:8000/camera
curl -I http://127.0.0.1/camera
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

## 八、常见问题

### 登录提示密钥未配置

检查 `/etc/camera-face-guard/app.env` 是否包含 `CAMERA_SESSION_SECRET`。

### 登录提示后台密码未配置

检查 `/etc/camera-face-guard/app.env` 是否包含 `CAMERA_ADMIN_PASSWORD`。

### 摄像头连接失败

确认服务器能访问 `P6S_CAMERA_HOST`，并检查摄像头账号密码是否正确。

### 收不到陌生人事件

确认摄像头事件上报 URL 使用公网可访问地址，并且路径中的 `P6S_EVENT_SECRET` 与环境变量一致。

### 飞书只有文字没有图片

文字通知只需要 `FEISHU_WEBHOOK_URL`。图片通知还需要 `FEISHU_APP_ID` 和 `FEISHU_APP_SECRET`，并要求飞书应用有上传图片能力。
