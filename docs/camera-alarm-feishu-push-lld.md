# 摄像头人脸识别事件推送到飞书 LLD

## 1. 文档状态

- 文档类型：LLD。
- 依据文档：`docs/camera-alarm-feishu-push-plan.html`。
- 日期：2026-07-02。
- 目标环境：`qypower-prod`，公网 IP `82.156.198.180`。
- 实现约束：关键方案已确认，后续代码实现、部署脚本调整和远程服务器初始化必须按本文档执行。

## 2. 设计目标

### 2.1 一期目标

- 摄像头通过 P6SEvent HTTP V2 主动推送 `FaceReco` 事件到远程服务器。
- 匹配成功时，每个独立识别事件都向飞书机器人发送匹配到的人员姓名、人员 ID、摄像头、识别时间和事件 ID。
- 未匹配成功时，服务器保存陌生人抓拍图到按日期创建的目录，并向飞书机器人发送保存路径和可点击查看链接。
- 图片查看链接必须由服务器受控提供，不能直接暴露服务器真实文件路径。
- 服务部署在 `qypower-prod`，通过 Nginx 反代到 FastAPI。
- 首版不依赖数据库，使用文件系统保存原始事件、图片、处理记录和链接记录。

### 2.2 非目标

- 不在本阶段重写摄像头管理后台 UI。
- 不在本阶段实现完整人脸库管理新流程。
- 不在本阶段强制接入飞书应用图片上传能力；首版使用富文本链接闭环。
- 不在文档、git 或 `.env.example` 写入真实飞书 webhook、秘钥、摄像头密码或其他密钥。
- 不直接把服务器磁盘路径作为可点击 URL 暴露给公网。

## 3. 现状对齐与关键决策

### 3.1 当前仓库现状

当前仓库已经是一个 FastAPI 摄像头管理服务：

- `app/main.py`：FastAPI 入口，挂载 `/api` 和静态页面。
- `app/routers/camera.py`：摄像头管理 API、P6S 事件回调、抓拍保存。
- `app/services/p6s_camera.py`：P6S 摄像头 HTTP API 封装。
- `app/services/feishu.py`：飞书通知与图片上传封装。
- `scripts/qypower-camera.service`：systemd 模板。
- `scripts/qypower-nginx.conf`：Nginx 模板。
- `DEPLOY.md`：当前部署说明。

### 3.2 路径与服务名决策

技术方案中曾使用 `camera-event-bridge`、`/api/camera-events/p6s`、`/camera-events/images/{token}` 作为概念路径。LLD 阶段为了减少迁移风险，首版实现优先沿用当前项目已有路径：

- 应用目录：`/opt/camera-face-guard`。
- 环境变量文件：`/etc/camera-face-guard/app.env`。
- 图片与事件根目录：`/var/lib/camera-face-guard/p6s_events`。
- systemd 服务：`camera-face-guard.service`。
- 摄像头事件入口：`POST /api/p6s/events/{P6S_EVENT_SECRET}`。
- 图片查看入口：新增 `GET /api/p6s/event-images/view/{token}`。

对外兼容路径可在 Nginx 层后续增加：

- `/api/camera-events/p6s` 可反代或重写到 `/api/p6s/events/{secret}`。
- `/camera-events/images/{token}` 可反代或重写到 `/api/p6s/event-images/view/{token}`。

首版不强制增加兼容路径，避免摄像头和服务端鉴权设计同时变复杂。

### 3.3 当前实现差距

当前代码已经能接收 `FaceReco`、保存陌生人图片、发送飞书陌生人通知，但与目标仍有差距：

- 当前只在 `personInfo` 为空时处理陌生人，没有发送匹配成功通知。
- 当前只读取 `info.personInfo`，而文档中的 `personInfo` 可能在顶层或 `info` 下，需要兼容。
- 当前图片目录是扁平结构，需要改为按日期目录保存。
- 当前 `GET /api/p6s/event-images/{filename}` 按文件名公开图片，需要改为 token 化查看链接。
- 当前飞书 webhook 没有实现签名秘钥 `FEISHU_WEBHOOK_SECRET`。
- 当前飞书通知主要是文本和可选内嵌图片，缺少富文本链接模板。
- 当前事件处理逻辑集中在 `app/routers/camera.py`，需要拆分到服务模块，降低路由复杂度。

### 3.4 已确认决策

以下结论已由用户确认，后续实现不得擅自变更：

- 首版沿用当前 `camera-face-guard` FastAPI 服务，不新增独立的 `camera-event-bridge` 服务。
- 事件入口使用 `POST /api/p6s/events/{P6S_EVENT_SECRET}`。
- 图片查看入口使用 `GET /api/p6s/event-images/view/{token}`，飞书消息不再使用按文件名直接访问图片的旧接口。
- 首版公网链路先使用 `http://82.156.198.180`，后续再升级域名和 HTTPS。
- 匹配成功必须每次通知：只要是不同的独立 `FaceReco` 匹配成功事件，即使识别到同一个人，也都发送飞书通知。
- 去重只用于同一个事件的缓存重放、网络重试或重复投递，不能按人员 ID、人员姓名或短时间窗口压制不同事件。
- 陌生人图片查看 token 默认有效期为 `86400` 秒。
- 陌生人原图和事件记录默认保留 `30` 天。
- 首版不引入数据库，全部使用文件系统保存原始事件、处理记录、图片和 token 映射。
- 首版不依赖飞书内嵌图片能力，以富文本消息中的可点击图片链接完成闭环。

## 4. 总体架构

```mermaid
flowchart LR
  camera["P6S 摄像头"] -->|FaceReco HTTP POST| nginx["qypower-prod Nginx :80/:443"]
  nginx --> api["FastAPI camera-face-guard"]
  api --> auth["事件鉴权"]
  auth --> persist["原始事件落盘"]
  persist --> router["识别结果分流"]
  router -->|matchNumber > 0 + personInfo| known["匹配成功通知"]
  router -->|matchNumber == 0 或 personInfo 为空| stranger["陌生人图片保存"]
  stranger --> link["生成图片查看 token"]
  known --> feishu["飞书自定义机器人"]
  link --> feishu
  browser["飞书用户点击链接"] --> nginx
  nginx --> image_api["GET /api/p6s/event-images/view/{token}"]
  image_api --> image_file["本地图片文件"]
```

## 5. 模块边界

### 5.1 `app/routers/camera.py`

职责：

- 保留摄像头管理后台相关 API。
- 提供 P6S 事件回调入口。
- 提供图片 token 查看入口。
- 只做 HTTP 层参数读取、错误转换和响应返回。

需要调整：

- `_handle_p6s_event` 只负责调用服务层，不直接解析和处理业务。
- 新增 `GET /p6s/event-images/view/{token}`。
- 生产环境下废弃或保护现有 `GET /p6s/event-images/{filename}`。

### 5.2 新增 `app/services/p6s_events.py`

职责：

- 标准化 P6S 事件 payload。
- 生成 dedupe key。
- 判断事件类型。
- 解析 `FaceReco` 的匹配结果。
- 调用图片保存、链接生成和飞书通知。
- 生成 P6S Ack。

建议暴露函数：

```python
async def handle_event(
    payload: dict[str, Any],
    request_meta: EventRequestMeta,
) -> EventHandleResult:
    ...
```

### 5.3 新增 `app/services/event_store.py`

职责：

- 保存原始事件 JSON。
- 保存结构化处理记录。
- 原子写入文件，避免并发写坏。
- 根据 dedupe key 查询是否已处理。
- 记录飞书发送状态。

首版使用文件系统，不引入数据库。

### 5.4 新增 `app/services/image_links.py`

职责：

- 为陌生人图片生成短期有效 token。
- 保存 token 到图片记录的映射。
- 校验 token、过期时间和文件存在性。
- 返回可被 `FileResponse` 使用的图片路径和 MIME 类型。

首版使用不透明随机 token，不把真实文件路径编码进 URL。

### 5.5 调整 `app/services/feishu.py`

职责：

- 读取飞书 webhook、签名秘钥和可选应用凭证。
- 支持自定义机器人签名校验。
- 支持发送富文本 `post` 消息。
- 保留可选图片上传和图片消息能力。

需要调整：

- `FeishuConfig` 增加 `webhook_secret`。
- 新增 `send_post(title, lines)`。
- 新增 `notify_known_face(...)`。
- 调整 `notify_unknown_face(...)`，支持保存路径和查看链接。
- webhook 请求体大小必须控制在 20 KB 内。

### 5.6 `app/services/p6s_camera.py`

职责不变：

- 摄像头管理、Owner、人脸库、人员图片上传。

本链路可能新增能力：

- 如果真机事件不携带图片，而只携带摄像头图片记录 ID，再扩展摄像头图片拉取方法。
- 该能力必须基于真机样本或 P6S 文档确认后再实现。

## 6. 外部接口设计

### 6.1 摄像头事件入口

首版沿用当前入口：

```http
POST /api/p6s/events/{path_secret}
Content-Type: application/json
```

鉴权规则：

- 如果 `P6S_EVENT_SECRET` 为空：仅允许本地开发，不建议远程使用。
- 如果 `P6S_EVENT_SECRET` 不为空：必须满足以下任一方式。
- 路径：`/api/p6s/events/{P6S_EVENT_SECRET}`。
- 查询参数：`/api/p6s/events?secret={P6S_EVENT_SECRET}`。
- 请求头：`X-P6S-Event-Secret: {P6S_EVENT_SECRET}`。

摄像头联调建议：

```text
Host=82.156.198.180
Port=80
URLPath=/api/p6s/events/<P6S_EVENT_SECRET>
Protocol=http
AuthMode=none
CacheEventEnable=true
```

成功响应：

- `heartbeat` 返回 `heartbeat-Ack`。
- `FaceReco` 返回 `FaceReco-Ack`。
- 其他事件返回 `{operator}-Ack`。

错误响应：

- 鉴权失败：`403`，不处理事件。
- JSON 格式错误：`400`，不处理事件。
- 事件持久化失败：`500`，让摄像头重试。
- 飞书发送失败：不影响摄像头 Ack，错误写入处理记录。

### 6.2 图片查看入口

新增：

```http
GET /api/p6s/event-images/view/{token}
```

规则：

- `token` 必须存在于 link store。
- `token` 未过期。
- 映射的图片路径必须在 `P6S_EVENT_IMAGE_DIR` 下，禁止路径穿越。
- 文件必须存在，且 MIME 类型必须是 `image/jpeg` 或 `image/png`。
- 成功时返回图片二进制。

响应：

- 成功：`200`，`Content-Type: image/jpeg` 或 `image/png`。
- token 不存在：`404`。
- token 过期：`410`。
- 文件丢失：`404`。
- 路径非法：`403`。

当前旧入口：

```http
GET /api/p6s/event-images/{filename}
```

生产要求：

- 不再作为飞书消息链接使用。
- 后续实现时应删除、改为管理员登录后可访问，或仅保留本地排障用途。

### 6.3 管理后台状态接口

现有：

```http
GET /api/camera/status
```

需要补充返回：

```json
{
  "events": {
    "dir": "/var/lib/camera-face-guard/p6s_events",
    "has_secret": true,
    "public_base_url": "http://82.156.198.180",
    "image_link_ttl_seconds": 86400,
    "notify_known_person": true,
    "signed_image_links": true
  },
  "feishu": {
    "has_webhook": true,
    "has_webhook_secret": true,
    "has_app_id": false,
    "has_app_secret": false,
    "can_upload_image": false
  }
}
```

### 6.4 飞书测试接口

现有：

```http
POST /api/camera/feishu/test
```

需要增强：

- 测试签名 webhook。
- 测试富文本链接消息。
- 不发送真实陌生人图片。

## 7. P6S 事件解析

### 7.1 通用字段提取

兼容大小写和位置差异：

```python
operator = payload.get("operator", "")
info = payload.get("info") or {}
device_info = payload.get("deviceInfo") or payload.get("deviceinfo") or {}
serial_number = device_info.get("serialNumber") or device_info.get("SN") or ""
event_id = info.get("eventId") or info.get("eventID") or ""
event_time = info.get("time") or ""
```

时间处理：

- 原始 `event_time` 保留。
- `received_at` 使用服务器时间，时区 `Asia/Shanghai`。
- 保存目录日期优先使用事件时间解析结果，解析失败使用 `received_at` 日期。

### 7.2 `FaceReco` 字段提取

兼容字段：

```python
match_number = info.get("matchNumber")
person_info = (
    payload.get("personInfo")
    or info.get("personInfo")
    or {}
)
capture_image = info.get("CaptureImage") or {}
background_image = info.get("BackgroundImage") or {}
recognize_image = info.get("recognizeImage") or {}
```

`personInfo` 可能形态：

- 对象：`{"uniqueId": "...", "name": "..."}`
- 数组：`[{"uniqueId": "...", "name": "..."}]`
- 空对象：`{}`
- 空数组：`[]`
- 空字符串：`""`
- 字段缺失。

解析规则：

- 如果是数组，取第一条作为首个匹配人员。
- 如果是对象，直接解析。
- 如果是空值，视为未匹配。
- 如果字段结构无法解析但 `matchNumber > 0`，标记为 `parse_error`，发送异常通知而不是静默吞掉。

### 7.3 人员字段映射

人员 ID 候选字段优先级：

1. `uniqueId`
2. `UniqueID`
3. `personId`
4. `PersonID`
5. `FaceUUID`
6. `faceUUID`

人员姓名候选字段优先级：

1. `name`
2. `Name`
3. `personName`
4. `PersonName`
5. `nickName`

如果姓名缺失：

- 飞书显示 `未知姓名`。
- 处理记录写入 `person_name_missing=true`。

如果 ID 缺失：

- 飞书显示 `未知ID`。
- 处理记录写入 `person_id_missing=true`。

### 7.4 分流规则

```python
is_face_reco = operator == "FaceReco"
person_info_empty = person_info in (None, "", {}, [])
match_number_int = parse_int(match_number)

if not is_face_reco:
    result = "ignored"
elif match_number_int is not None and match_number_int == 0:
    result = "stranger"
elif not person_info_empty:
    result = "known"
elif match_number_int is not None and match_number_int > 0:
    result = "parse_error"
else:
    result = "stranger"
```

说明：

- `matchNumber == 0` 优先判定为陌生人。
- `personInfo` 非空优先判定为匹配成功。
- `matchNumber > 0` 但 `personInfo` 为空属于矛盾状态，需要记录并通知异常。
- 没有 `matchNumber` 且没有 `personInfo` 时，按陌生人处理，但记录 `match_number_missing=true`。

## 8. 文件系统数据设计

### 8.1 目录结构

根目录：

```text
P6S_EVENT_IMAGE_DIR=/var/lib/camera-face-guard/p6s_events
```

目标结构：

```text
/var/lib/camera-face-guard/p6s_events/
  raw/
    2026-07-02/
      {dedupe_key}.json
  records/
    2026-07-02/
      {dedupe_key}.json
  strangers/
    2026-07-02/
      {event_time}_{serial}_{event_id}_{md5_8}.jpg
  links/
    2026-07-02/
      {token_hash}.json
```

### 8.2 文件命名

`dedupe_key`：

```text
sha256(serial_number + "|" + operator + "|" + event_id + "|" + picture_md5)
```

如果 `event_id` 或 `picture_md5` 缺失：

- 使用空字符串参与哈希。
- 额外加入 `received_at`，避免不同事件误合并。

图片文件名：

```text
{event_time_compact}_{safe_serial}_{safe_event_id}_{md5_8_or_sha8}.{ext}
```

示例：

```text
20260702183501_SN123456_43_1bbd8864.jpg
```

安全规则：

- 文件名只允许 `0-9A-Za-z_.-`。
- 序列号和事件 ID 必须清洗。
- 所有写入使用临时文件 + `replace` 原子落盘。

### 8.3 原始事件文件

路径：

```text
raw/YYYY-MM-DD/{dedupe_key}.json
```

内容：

```json
{
  "version": 1,
  "received_at": "2026-07-02T18:35:01+08:00",
  "request": {
    "client_host": "1.2.3.4",
    "content_type": "application/json",
    "user_agent": "P6S"
  },
  "payload": {}
}
```

### 8.4 处理记录文件

路径：

```text
records/YYYY-MM-DD/{dedupe_key}.json
```

内容：

```json
{
  "version": 1,
  "dedupe_key": "sha256...",
  "operator": "FaceReco",
  "camera_serial_number": "SN123456",
  "event_id": "43",
  "event_time": "2026-07-02T18:35:01+08:00",
  "received_at": "2026-07-02T18:35:02+08:00",
  "result": "stranger",
  "matched_person": {
    "name": "",
    "id": ""
  },
  "image": {
    "status": "saved",
    "source": "CaptureImage",
    "storage_path": "/var/lib/camera-face-guard/p6s_events/strangers/2026-07-02/20260702183501_SN123456_43_1bbd8864.jpg",
    "relative_path": "strangers/2026-07-02/20260702183501_SN123456_43_1bbd8864.jpg",
    "content_type": "image/jpeg",
    "bytes": 12345,
    "md5": "1bbd886460827015e5d605ed44252251"
  },
  "link": {
    "token_hash": "sha256...",
    "expires_at": "2026-07-03T18:35:02+08:00"
  },
  "feishu": {
    "status": "sent",
    "status_code": 200,
    "response_code": 0,
    "response_text": "success",
    "sent_at": "2026-07-02T18:35:03+08:00"
  },
  "ack": {
    "operator": "FaceReco-Ack",
    "errorNo": 0
  }
}
```

## 9. 图片保存设计

### 9.1 图片来源优先级

1. `info.CaptureImage.picture`：首选，人脸裁剪图。
2. `info.BackgroundImage.picture`：备用，背景图。
3. `info.recognizeImage.picture`：如真机样本证明可用，再纳入备用。
4. 摄像头存储拉取：仅在真机事件提供可用图片记录 ID/路径，并确认接口后实现。

### 9.2 Base64 处理

规则：

- 支持 `data:image/jpeg;base64,...`。
- 支持纯 base64。
- base64 解码必须启用校验。
- 解码失败时记录 `image.status=decode_failed`，仍发送飞书异常通知，但不生成查看链接。

### 9.3 图片格式校验

支持：

- JPEG：魔数 `FF D8 FF`。
- PNG：魔数 `89 50 4E 47 0D 0A 1A 0A`。

不支持：

- 空文件。
- 非图片。
- 超过 `P6S_EVENT_MAX_IMAGE_BYTES` 的图片。

默认限制：

```env
P6S_EVENT_MAX_IMAGE_BYTES=5242880
```

### 9.4 MD5 校验

如果事件提供 `pictureMd5`：

- 保存后计算 MD5。
- 相同则记录 `md5_ok=true`。
- 不同则记录 `md5_ok=false`，飞书通知中不暴露该内部状态，但日志中必须记录。

## 10. 图片链接设计

### 10.1 Token 策略

首版使用不透明随机 token：

```python
token = secrets.token_urlsafe(32)
token_hash = sha256(token)
```

服务器只保存 `token_hash`，不保存明文 token。包含明文 token 的 `view_url` 只能在运行时生成并发送给飞书，不能写入 raw、records 或 links 目录。

链接记录：

```json
{
  "version": 1,
  "token_hash": "sha256...",
  "record_dedupe_key": "sha256...",
  "relative_path": "strangers/2026-07-02/20260702183501_SN123456_43_1bbd8864.jpg",
  "content_type": "image/jpeg",
  "created_at": "2026-07-02T18:35:02+08:00",
  "expires_at": "2026-07-03T18:35:02+08:00",
  "access_count": 0,
  "last_accessed_at": null
}
```

### 10.2 链接生成

优先使用：

```env
P6S_EVENT_IMAGE_PUBLIC_BASE_URL=http://82.156.198.180/api/p6s/event-images/view
```

如果未配置，则使用：

```text
PUBLIC_BASE_URL + "/api/p6s/event-images/view"
```

生成 URL：

```text
{base_url}/{token}
```

### 10.3 链接访问

访问流程：

1. 清洗 token，拒绝异常字符。
2. 计算 `sha256(token)`。
3. 在 `links/**/{token_hash}.json` 中查找 link record。
4. 校验 `expires_at`。
5. 解析 `relative_path`。
6. 确认目标路径在 `P6S_EVENT_IMAGE_DIR` 之内。
7. 确认文件存在且是普通文件。
8. 返回 `FileResponse`。
9. 更新 `access_count` 和 `last_accessed_at`。

过期策略：

- 默认 TTL：`86400` 秒。
- 过期返回 `410 Gone`。
- 不自动删除原图，原图由保留策略清理。

## 11. 飞书通知设计

### 11.1 配置

```env
FEISHU_WEBHOOK_URL=真实 webhook，远程只放 /etc/camera-face-guard/app.env
FEISHU_WEBHOOK_SECRET=飞书签名秘钥
FEISHU_APP_ID=可选，仅内嵌图片时需要
FEISHU_APP_SECRET=可选，仅内嵌图片时需要
```

`FeishuConfig.safe_summary()` 必须只返回布尔值，不能返回真实值。

### 11.2 签名

如果 `FEISHU_WEBHOOK_SECRET` 非空，所有 webhook 请求必须包含：

```json
{
  "timestamp": "1599360473",
  "sign": "base64-signature"
}
```

签名算法：

```python
string_to_sign = f"{timestamp}\n{secret}"
signature = base64.b64encode(
    hmac.new(string_to_sign.encode("utf-8"), b"", hashlib.sha256).digest()
).decode("utf-8")
```

### 11.3 消息类型

首版使用自定义机器人 `post` 富文本消息。

原因：

- 支持文字和超链接。
- 不需要飞书应用 `tenant_access_token`。
- 请求体小于 20 KB，满足自定义机器人限制。

暂不作为首版阻塞项：

- `image` 消息。
- `interactive` 卡片。
- `image_key` 内嵌图片。

### 11.4 匹配成功消息

触发条件：

- `operator == "FaceReco"`。
- `matchNumber > 0` 或 `personInfo` 非空。
- 能解析出至少一个匹配人员。

通知频率：

- 每个独立匹配成功事件都必须发送飞书通知。
- 不按人员 ID、人员姓名、摄像头或短时间窗口静默、采样或合并不同事件。
- 如果摄像头因缓存、断网重放或 HTTP 重试投递同一个事件，服务端按 dedupe key 幂等处理，避免同一事件重复通知。

消息标题：

```text
会员入场提醒 / 教练入场提醒 / 员工入场提醒 / 人员入场提醒
```

内容：

- 姓名。
- 人员 ID。
- 摄像头序列号。
- 识别时间。
- 事件 ID。
- 身份类型；仅当服务端可映射到会员、教练或员工时展示。

富文本示例：

```json
{
  "msg_type": "post",
  "content": {
    "post": {
      "zh_cn": {
        "title": "会员入场提醒",
        "content": [
          [{"tag": "text", "text": "姓名：小明"}],
          [{"tag": "text", "text": "人员 ID：3427976339944670"}],
          [{"tag": "text", "text": "摄像头：SN123456"}],
          [{"tag": "text", "text": "识别时间：2026-07-02 18:30:12"}],
          [{"tag": "text", "text": "事件 ID：42"}],
          [{"tag": "text", "text": "身份类型：会员"}]
        ]
      }
    }
  }
}
```

### 11.5 未匹配成功消息

触发条件：

- `operator == "FaceReco"`。
- `matchNumber == 0`，或 `personInfo` 为空/缺失。

消息标题：

```text
发现陌生人入场
```

内容：

- 摄像头序列号。
- 识别时间。
- 事件 ID。
- 服务器保存路径。
- 图片查看链接。

富文本示例：

```json
{
  "msg_type": "post",
  "content": {
    "post": {
      "zh_cn": {
        "title": "发现陌生人入场",
        "content": [
          [{"tag": "text", "text": "摄像头：SN123456"}],
          [{"tag": "text", "text": "识别时间：2026-07-02 18:35:01"}],
          [{"tag": "text", "text": "事件 ID：43"}],
          [{"tag": "text", "text": "保存位置：/var/lib/camera-face-guard/p6s_events/strangers/2026-07-02/xxx.jpg"}],
          [{"tag": "a", "text": "查看图片", "href": "http://82.156.198.180/api/p6s/event-images/view/<token>"}]
        ]
      }
    }
  }
}
```

### 11.6 异常消息

以下情况发送异常通知：

- `matchNumber > 0` 但 `personInfo` 为空。
- 未匹配成功但图片无法解码。
- 未匹配成功但图片缺失。
- 飞书内嵌图片上传失败但文本链接消息成功。

异常通知不能包含内部堆栈，需包含事件 ID 和原始事件保存路径。

## 12. P6S Ack 设计

### 12.1 Heartbeat Ack

沿用当前实现：

- `operator=heartbeat-Ack`。
- 返回 `eventSendMode` 和 `strategy`。
- `strategy.isSnapshotEnable=true`。
- `strategy.isPersonInfoEnable=true`。

### 12.2 FaceReco Ack

返回：

```json
{
  "operator": "FaceReco-Ack",
  "info": {
    "personId": 0,
    "uniqueId": "",
    "pictureMd5": "1bbd886460827015e5d605ed44252251",
    "storedImage": ""
  },
  "result": {
    "errorNo": 0,
    "description": "ok"
  }
}
```

字段规则：

- `personId`：匹配成功时优先使用解析到的 `personId`，否则 `0`。
- `uniqueId`：匹配成功时优先使用解析到的人员 ID，否则空字符串。
- `pictureMd5`：优先使用 `CaptureImage.pictureMd5`，否则空字符串。
- `storedImage`：仅内部排障字段，若发现摄像头不接受该字段，应从 Ack 中移除。

### 12.3 Ack 与后台任务关系

- 原始事件持久化成功后，尽量快速返回 Ack。
- 飞书通知可通过 `BackgroundTasks` 异步执行。
- 如果飞书失败，不改变摄像头 Ack，避免摄像头反复重推。
- 因为 `BackgroundTasks` 不是可靠队列，事件记录必须先落盘，后续可通过维护脚本补发失败通知。

## 13. 配置设计

### 13.1 本地配置

本地真实配置只写入 `.env.local`。

禁止新增：

- `.env.local2`
- `.env.dev`
- 其他临时真实配置文件

### 13.2 远程配置

远程真实配置写入：

```text
/etc/camera-face-guard/app.env
```

权限：

```bash
sudo chown root:root /etc/camera-face-guard/app.env
sudo chmod 640 /etc/camera-face-guard/app.env
```

### 13.3 环境变量清单

```env
CAMERA_SESSION_SECRET=随机长字符串
CAMERA_ADMIN_USERNAME=admin
CAMERA_ADMIN_PASSWORD=后台登录密码

P6S_CAMERA_HOST=http://摄像头IP或域名
P6S_CAMERA_USERNAME=admin
P6S_CAMERA_PASSWORD=摄像头密码
P6S_FACE_OWNER=固定 Owner
P6S_FACE_GROUP_ID=默认脸库ID，兼容旧的单脸库工具，当前指向会员
P6S_FACE_GROUP_NAME=默认脸库名称，兼容旧的单脸库工具，当前为会员
P6S_FACE_GROUP_MEMBERS_ID=会员脸库GroupID2
P6S_FACE_GROUP_MEMBERS_NAME=会员
P6S_FACE_GROUP_COACHES_ID=教练脸库GroupID2
P6S_FACE_GROUP_COACHES_NAME=教练
P6S_FACE_GROUP_STAFF_ID=员工脸库GroupID2
P6S_FACE_GROUP_STAFF_NAME=员工
P6S_FACE_GROUP_THRESHOLD=

P6S_EVENT_SECRET=摄像头事件回调鉴权 token
P6S_EVENT_IMAGE_DIR=/var/lib/camera-face-guard/p6s_events
P6S_EVENT_IMAGE_LINK_SECRET=图片查看链接 token 秘钥
P6S_EVENT_IMAGE_LINK_TTL_SECONDS=86400
P6S_EVENT_NOTIFY_KNOWN_PERSON=true
P6S_EVENT_MAX_BODY_BYTES=5242880
P6S_EVENT_MAX_IMAGE_BYTES=5242880
P6S_EVENT_RETENTION_DAYS=30
PUBLIC_BASE_URL=http://82.156.198.180
P6S_EVENT_IMAGE_PUBLIC_BASE_URL=http://82.156.198.180/api/p6s/event-images/view

FEISHU_WEBHOOK_URL=飞书 webhook
FEISHU_WEBHOOK_SECRET=飞书签名秘钥
FEISHU_APP_ID=可选，仅内嵌图片时需要
FEISHU_APP_SECRET=可选，仅内嵌图片时需要
```

### 13.4 `.env.example`

`.env.example` 只保留占位说明，不写真实值。

需要新增占位项：

```env
P6S_EVENT_IMAGE_LINK_SECRET=replace-with-random-secret
P6S_EVENT_IMAGE_LINK_TTL_SECONDS=86400
P6S_EVENT_NOTIFY_KNOWN_PERSON=true
P6S_EVENT_MAX_BODY_BYTES=5242880
P6S_EVENT_MAX_IMAGE_BYTES=5242880
P6S_EVENT_RETENTION_DAYS=30
FEISHU_WEBHOOK_SECRET=replace-with-feishu-signing-secret
```

## 14. 部署设计

### 14.1 远程服务器

- SSH：`ssh qypower-prod`。
- 公网 IP：`82.156.198.180`。
- 系统：Ubuntu。
- 应用目录：`/opt/camera-face-guard`。
- 环境变量：`/etc/camera-face-guard/app.env`。
- 事件目录：`/var/lib/camera-face-guard/p6s_events`。
- 日志：`journalctl -u camera-face-guard` 和 `/var/log/nginx/`。

### 14.2 初始化命令

```bash
sudo apt update
sudo apt install -y python3-venv nginx
sudo mkdir -p /opt/camera-face-guard /etc/camera-face-guard /var/log/camera-face-guard /var/lib/camera-face-guard/p6s_events
sudo chown -R ubuntu:ubuntu /opt/camera-face-guard /var/log/camera-face-guard /var/lib/camera-face-guard
sudo chmod 750 /etc/camera-face-guard
```

### 14.3 发布命令

本地：

```bash
rsync -a --delete \
  --exclude .git \
  --exclude .venv \
  --exclude .env.local \
  ./ qypower-prod:/opt/camera-face-guard/
```

远程：

```bash
cd /opt/camera-face-guard
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
sudo cp scripts/qypower-camera.service /etc/systemd/system/camera-face-guard.service
sudo cp scripts/qypower-nginx.conf /etc/nginx/sites-available/camera-face-guard
sudo ln -sf /etc/nginx/sites-available/camera-face-guard /etc/nginx/sites-enabled/camera-face-guard
sudo systemctl daemon-reload
sudo systemctl enable --now camera-face-guard
sudo nginx -t
sudo systemctl reload nginx
```

### 14.4 Nginx

首版沿用当前模板：

```nginx
server {
    listen 80;
    server_name _;

    client_max_body_size 20m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

后续增强：

- HTTPS 证书。
- `/api/p6s/events/` 限流。
- `/api/p6s/event-images/view/` 限流。
- 仅允许摄像头公网出口 IP 访问事件入口，如果摄像头出口固定。

### 14.5 systemd

首版沿用当前模板：

```ini
WorkingDirectory=/opt/camera-face-guard
EnvironmentFile=/etc/camera-face-guard/app.env
ExecStart=/opt/camera-face-guard/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=on-failure
```

## 15. 摄像头配置设计

### 15.1 HTTP 事件服务器配置

使用 P6S：

```text
/System/HTTPEventServerConfigV2
```

联调建议：

```xml
<HttpEventServerCfgV2>
  <Enable>true</Enable>
  <Protocol>http</Protocol>
  <Host>82.156.198.180</Host>
  <URLPath>/api/p6s/events/{P6S_EVENT_SECRET}</URLPath>
  <Port>80</Port>
  <DataTransfer2ServerTimeout>5</DataTransfer2ServerTimeout>
  <AuthMode>none</AuthMode>
  <CacheEventEnable>true</CacheEventEnable>
</HttpEventServerCfgV2>
```

### 15.2 AI 事件启用

需要确认以下配置：

- `/System/AIEventCfg`：`Enable=true`，`HttpType=http`。
- `/System/EventPushMode`：记录当前 `MQTTPushMode`，观察是否影响 HTTP 推送。
- `/AI/FaceSnapshotCfg`：`Enable=true`，`Trigger.Push.Enable=true`。
- `/FaceReco/1/RecoRuleList`：人脸识别规则启用，识别区域有效。

### 15.3 测试

使用：

```text
/System/HTTPEventServerTest
```

目标：

- 摄像头返回 `StatusCode` 正常。
- 远程服务 raw 目录收到测试事件。
- FastAPI 日志有访问记录。

## 16. 错误处理

### 16.1 事件入口

- 鉴权失败：`403`，不落盘。
- JSON 解析失败：`400`，记录访问日志，不落业务事件。
- 原始事件落盘失败：`500`，让摄像头缓存/重试。
- 非目标事件：落盘，返回 Ack，不发飞书。

### 16.2 分流

- `FaceReco` 缺少 `info`：记录 `parse_error`，发送异常通知。
- `matchNumber > 0` 但人员解析失败：记录 `parse_error`，发送异常通知。
- `matchNumber` 缺失且 `personInfo` 为空：按陌生人处理，记录 `match_number_missing=true`。

### 16.3 图片

- 图片缺失：记录 `image.status=missing`，飞书通知中不生成查看链接。
- 图片 base64 失败：记录 `decode_failed`。
- 图片格式不支持：记录 `unsupported_format`。
- 图片超过大小限制：记录 `too_large`。
- MD5 不一致：记录 `md5_mismatch`，图片仍可保存，但通知中标记为图片校验异常。

### 16.4 飞书

- webhook 未配置：记录 `feishu.status=skipped`。
- 签名失败返回：记录状态码和响应体。
- 触发频控：记录失败，后续可人工重放。
- 飞书失败不影响摄像头 Ack。

### 16.5 链接

- token 不存在：`404`。
- token 过期：`410`。
- 文件不存在：`404`。
- 路径越界：`403` 并记录安全日志。

## 17. 去重与重放

### 17.1 去重

去重发生在原始事件落盘后、业务处理前。

规则：

- 如果 `records/YYYY-MM-DD/{dedupe_key}.json` 已存在且 `feishu.status=sent`，直接返回 Ack，不重复发飞书。
- 如果记录存在但 `feishu.status=failed`，首版不自动重试，避免重复骚扰；后续提供手动重放脚本。

### 17.2 重放

后续可新增脚本：

```bash
python3 scripts/replay_p6s_event_notifications.py --date 2026-07-02 --failed-only
```

本阶段只在 LLD 中预留，不强制实现。

## 18. 日志与可观测性

必须记录：

- event received：operator、serial、event_id、dedupe_key。
- event persisted：raw path、record path。
- route result：known、stranger、parse_error、ignored。
- image save：status、path、bytes、md5_ok。
- image link：token_hash、expires_at。
- feishu send：message type、status_code、response code。
- image view：token_hash、result、client IP。

禁止记录：

- 飞书 webhook 完整 URL。
- 飞书签名秘钥。
- 摄像头密码。
- 图片 token 明文。

## 19. 验证计划

### 19.1 本地静态验证

```bash
python3 -m py_compile app/main.py app/routers/auth.py app/routers/camera.py app/services/p6s_camera.py app/services/feishu.py run.py
```

如果新增模块，也纳入 `py_compile`。

### 19.2 本地事件样本验证

准备样本：

- `tests/fixtures/p6s_face_reco_known.json`
- `tests/fixtures/p6s_face_reco_stranger.json`
- `tests/fixtures/p6s_face_reco_missing_image.json`
- `tests/fixtures/p6s_heartbeat.json`

验证内容：

- known 样本生成匹配成功飞书消息。
- stranger 样本保存图片，生成 link record。
- missing image 样本不生成图片链接。
- heartbeat 返回策略。

### 19.3 远程服务验证

```bash
ssh qypower-prod
sudo systemctl status camera-face-guard
curl -I http://127.0.0.1:8000/camera
curl -I http://127.0.0.1/camera
curl -I http://82.156.198.180/camera
```

### 19.4 摄像头 HTTP 测试

摄像头调用 `/System/HTTPEventServerTest`。

验证：

- 摄像头侧测试通过。
- 服务端 raw 目录有事件文件。
- 日志中有事件访问。

### 19.5 真机识别验证

匹配成功：

- 摄像头识别到已入库人员。
- 每个独立识别事件都能在飞书收到姓名和 ID。
- 同一个事件的重复投递不会产生重复飞书消息。
- 不保存陌生人图片。

未匹配成功：

- 摄像头识别到未入库人员。
- 服务端保存图片到日期目录。
- 飞书收到保存路径和查看链接。
- 点击链接可打开图片。
- 过期 token 返回 `410`。

### 19.6 安全验证

- 无 secret 访问事件入口返回 `403`。
- 错误 secret 返回 `403`。
- 伪造图片 token 返回 `404`。
- 过期 token 返回 `410`。
- 路径穿越 token 无法读取目录外文件。

## 20. 回滚方案

### 20.1 摄像头侧

- 将 `/System/HTTPEventServerConfigV2.Enable` 改为 `false`。
- 将 `/System/HTTPEventServerStatusV2.Status` 改为 `offline`。
- 关闭人脸抓拍/识别配置中的 `Trigger.Push.Enable`。

### 20.2 服务器侧

```bash
sudo systemctl stop camera-face-guard
sudo systemctl disable camera-face-guard
```

或回滚代码：

```bash
rsync -a --delete <previous-release>/ qypower-prod:/opt/camera-face-guard/
ssh qypower-prod "sudo systemctl restart camera-face-guard"
```

### 20.3 飞书侧

- 删除或注释远程 `/etc/camera-face-guard/app.env` 中的 `FEISHU_WEBHOOK_URL`。
- 重启服务。

## 21. 详细开发步骤计划

本节是后续开发和配置的执行顺序。每一步都必须保持小步提交思路：先完成本步产出，再进入下一步；如果发现实现需要偏离本表，先更新 LLD 再继续。

| 步骤 | 类型 | 目标 | 开发或配置任务 | 完成标准 |
| --- | --- | --- | --- | --- |
| 0 | 文档/流程 | 冻结范围，避免计划外开发。 | 阅读 `AGENTS.md`、技术方案和本 LLD；确认只实现事件接收、识别分流、陌生人图片保存、token 查看链接、飞书通知、配置文档和部署文档。 | 不新增未确认功能；不把真实 webhook、秘钥、摄像头密码写入文档或 git。 |
| 1 | 开发/配置 | 整理配置项和说明。 | 更新 `.env.example`、`README.md`、`DEPLOY.md`；补充 `P6S_EVENT_SECRET`、`P6S_EVENT_IMAGE_DIR`、`P6S_EVENT_IMAGE_LINK_SECRET`、`P6S_EVENT_IMAGE_LINK_TTL_SECONDS`、`P6S_EVENT_NOTIFY_KNOWN_PERSON`、`P6S_EVENT_RETENTION_DAYS`、`FEISHU_WEBHOOK_SECRET` 等配置说明。 | `.env.example` 只有占位值；本地真实配置只在 `.env.local`；远程真实配置只在 `/etc/camera-face-guard/app.env`。 |
| 2 | 开发 | 建立事件存储层。 | 新增 `app/services/event_store.py`；实现 `raw/YYYY-MM-DD`、`records/YYYY-MM-DD`、`strangers/YYYY-MM-DD`、`links/YYYY-MM-DD` 目录；实现原始事件落盘、处理记录落盘、陌生人图片落盘和 dedupe key。 | 事件和图片按日期保存；同一个事件重复投递不会生成重复处理记录或重复通知任务。 |
| 3 | 开发 | 建立图片 token 链接层。 | 新增 `app/services/image_links.py`；实现随机 token 生成、token 哈希保存、过期时间校验、路径归属校验、MIME 类型判断和图片响应元数据。 | 合法 token 可读图片；伪造 token 返回 `404`；过期 token 返回 `410`；路径穿越被拒绝。 |
| 4 | 开发 | 改造飞书通知能力。 | 改造 `app/services/feishu.py`；支持飞书 webhook 签名；新增 `post` 富文本发送；实现匹配成功、陌生人、异常三类消息模板。 | 匹配成功每个独立事件都通知姓名和 ID；陌生人通知包含保存路径和查看链接；日志不输出 webhook 完整 URL 或签名秘钥。 |
| 5 | 开发 | 建立 P6S 事件解析与分流层。 | 新增 `app/services/p6s_events.py`；解析 `operator`、`info`、`deviceInfo`、`matchNumber`、`personInfo`、`CaptureImage`、`BackgroundImage`；实现 known、stranger、parse_error、ignored 分支；生成 Ack。 | known、stranger、缺图、字段异常、非目标事件都有确定输出；`FaceReco-Ack` 字段遵守本 LLD。 |
| 6 | 开发 | 简化摄像头路由。 | 改造 `app/routers/camera.py`；事件入口只负责鉴权、请求体大小限制、调用服务层和返回 Ack；新增 `GET /api/p6s/event-images/view/{token}`；旧文件名图片接口不再用于飞书链接。 | 路由层不再堆识别业务逻辑；新 token 图片入口通过安全校验；旧公开文件名入口不出现在通知消息中。 |
| 7 | 验证 | 本地样本验证。 | 新增或准备 `tests/fixtures/p6s_face_reco_known.json`、`tests/fixtures/p6s_face_reco_stranger.json`、`tests/fixtures/p6s_face_reco_missing_image.json`、`tests/fixtures/p6s_heartbeat.json`；运行 `py_compile` 和最小事件处理脚本。 | known 样本生成匹配成功消息；stranger 样本保存图片并生成链接记录；missing image 样本不生成图片链接；heartbeat 返回正确 Ack。 |
| 8 | 配置 | 远程服务器前置初始化。 | 通过 `ssh qypower-prod` 准备 Ubuntu 依赖、应用目录、事件目录、日志目录、systemd、Nginx 和远程 env 文件。 | `/opt/camera-face-guard`、`/etc/camera-face-guard/app.env`、`/var/lib/camera-face-guard/p6s_events` 权限正确；服务可在远程本机访问。 |
| 9 | 配置 | 配置摄像头 HTTP 事件推送。 | 配置 `/System/HTTPEventServerConfigV2`：`Host=82.156.198.180`、`Port=80`、`URLPath=/api/p6s/events/{P6S_EVENT_SECRET}`；检查 `/System/AIEventCfg`、`/System/EventPushMode`、`/AI/FaceSnapshotCfg`、`/FaceReco/1/RecoRuleList`。 | `/System/HTTPEventServerTest` 能到达服务器；服务端 raw 目录出现测试事件；由于已关闭 access log，摄像头请求以测试返回和 raw 事件文件作为证据。 |
| 10 | 验证 | 真机端到端验证。 | 分别触发已入库人员和陌生人识别；检查飞书消息、服务器保存目录、图片查看链接、token 过期和重复事件幂等。 | 匹配成功每次通知；陌生人保存图片并可点击查看；同一事件重复投递不会重复通知。 |
| 11 | 配置/验证 | 回滚和运维确认。 | 验证关闭摄像头 HTTP 推送、停止远程服务、移除飞书 webhook、回滚代码、查看日志和清理事件目录的步骤。 | 出现异常时可以快速停止推送和通知；不影响本地摄像头管理后台继续使用。 |

### 21.1 暂不开发

- 飞书内嵌图片卡片。
- 飞书应用机器人主动发送 API。
- 数据库存储。
- 摄像头存储图片拉取，除非真机样本证明事件不含图片且给出了可拉取标识。

## 22. 待真机确认项

- `FaceReco.personInfo` 在当前固件中的实际位置和字段名。
- 匹配成功时 `matchNumber` 与 `personInfo` 是否总是一致。
- 未匹配成功时事件是否总是携带 `CaptureImage.picture`。
- 当前固件是否发送 `BackgroundImage.picture`。
- 当前固件对 `FaceReco-Ack` 中额外字段 `storedImage` 是否容忍。
- `/System/EventPushMode.MQTTPushMode` 是否影响 HTTP 事件结构。
- 摄像头是否只能 HTTP 推送，是否支持 HTTPS。
- 摄像头公网出口 IP 是否固定，是否能做 Nginx IP 白名单。

## 23. 开发执行记录

### 23.1 Round 01：LLD 步骤 0-1

本轮对应 LLD 步骤：

- 步骤 0：文档/流程，冻结范围，避免计划外开发。
- 步骤 1：开发/配置，整理配置项和说明。

本轮目标：

- 确认当前已有技术方案和 LLD，可进入实现阶段。
- 将 `.env.example`、`README.md`、`DEPLOY.md` 与 LLD 的最终配置项保持一致。
- 明确本地真实配置只写 `.env.local`，远程真实配置只写 `/etc/camera-face-guard/app.env`。
- 为后续事件存储、图片 token、飞书通知和路由改造提供一致的配置基础。

本轮范围：

- 更新 `.env.example` 中的占位配置，不写真实密钥。
- 更新 `README.md` 的功能说明、配置说明、API 路径和模块目录。
- 更新 `DEPLOY.md` 的远程环境变量、摄像头事件配置、验证步骤和常见问题。
- 不改业务代码。
- 不连接远程服务器。
- 不改摄像头配置。
- 不处理会员图片、会员 CSV 或历史 STYD 抓取文件。

具体开发计划：

1. 阅读并确认 `AGENTS.md`、技术方案和本 LLD，确认本轮不超出步骤 0-1。
2. 对齐 `.env.example`：
   - 增加 `P6S_EVENT_IMAGE_LINK_SECRET`。
   - 增加 `P6S_EVENT_IMAGE_LINK_TTL_SECONDS=86400`。
   - 增加 `P6S_EVENT_NOTIFY_KNOWN_PERSON=true`。
   - 增加 `P6S_EVENT_MAX_BODY_BYTES=5242880`。
   - 增加 `P6S_EVENT_MAX_IMAGE_BYTES=5242880`。
   - 增加 `P6S_EVENT_RETENTION_DAYS=30`。
   - 增加 `P6S_EVENT_IMAGE_PUBLIC_BASE_URL=http://82.156.198.180/api/p6s/event-images/view`。
   - 增加 `FEISHU_WEBHOOK_SECRET` 占位值。
3. 对齐 `README.md`：
   - 强调本地 `.env.local` 规则。
   - 说明匹配成功每次通知。
   - 说明陌生人图片保存到日期目录并生成 token 链接。
   - 补充新增服务模块和 token 图片接口。
4. 对齐 `DEPLOY.md`：
   - 远程配置使用 `/etc/camera-face-guard/app.env`。
   - 事件入口使用 `/api/p6s/events/<P6S_EVENT_SECRET>`。
   - 图片查看入口使用 `/api/p6s/event-images/view/<token>`。
   - 补充飞书签名秘钥、图片链接秘钥、TTL、保留期和请求体大小配置。
   - 补充摄像头 HTTPEventServerConfigV2 的配置要点。
5. 验证：
   - 使用 `rg` 确认文档和样例中没有真实飞书 webhook、飞书 secret、摄像头密码。
   - 使用 `rg` 确认没有旧的 `CAMERA_EVENT_*` 配置项残留在本轮相关文件中。
   - 运行 `git diff --check`。

本轮风险：

- 如果文档与 LLD 配置名不一致，后续开发会读取错误变量。
- 如果样例文件写入真实密钥，会造成安全风险。

本轮回滚方式：

- 回滚 `.env.example`、`README.md`、`DEPLOY.md` 和本节 LLD 执行记录即可。

本轮提交策略：

- 本轮完成并验证后单独提交一次，提交信息需说明这是 LLD 步骤 0-1 的配置文档基础整理。

### 23.2 Round 02：LLD 步骤 2

本轮对应 LLD 步骤：

- 步骤 2：开发，建立事件存储层。

本轮目标：

- 新增 `app/services/event_store.py`，把事件与图片落盘能力从路由层拆出。
- 提供后续 `p6s_events.py`、`image_links.py` 和飞书通知模块可复用的文件系统 API。
- 建立 `raw`、`records`、`strangers`、`links` 日期目录结构。
- 实现 dedupe key 生成，作为重复事件幂等处理的基础。

本轮范围：

- 新增 `app/services/event_store.py`。
- 实现原始事件 JSON 原子落盘。
- 实现处理记录 JSON 原子落盘。
- 实现陌生人图片 bytes 原子落盘。
- 实现事件根目录、日期目录、文件名清洗、图片类型识别、相对路径计算等基础工具。
- 不改 `app/routers/camera.py` 的现有事件处理逻辑。
- 不新增 token 图片查看接口。
- 不改飞书通知逻辑。
- 不连接摄像头，不连接远程服务器。

具体开发计划：

1. 定义存储配置和数据结构：
   - `EventStorePaths`：描述当前日期下的 `raw`、`records`、`strangers`、`links` 目录。
   - `EventIdentity`：保存 `dedupe_key`、`operator`、`serial_number`、`event_id`、`picture_md5`、`received_at`、`event_day` 等基础标识。
   - `RequestMeta`：保存请求来源、Content-Type、User-Agent、路径等原始请求信息。
   - `StoredFile` / `StoredImage`：描述已落盘文件和图片元数据。
2. 实现目录与路径函数：
   - `event_store_root()` 从 `P6S_EVENT_IMAGE_DIR` 读取根目录。
   - `ensure_event_store_dirs()` 创建日期目录。
   - `relative_to_root()` 返回可记录到 JSON 的相对路径。
3. 实现 dedupe key：
   - 基础哈希输入为 `serial_number|operator|event_id|picture_md5`。
   - 如果 `event_id` 或 `picture_md5` 缺失，额外加入 `received_at`，避免不同事件误合并。
4. 实现原子写入：
   - JSON 写入使用临时文件 + `replace`。
   - bytes 写入使用临时文件 + `replace`。
   - 写入失败时清理临时文件。
5. 实现事件落盘 API：
   - `persist_raw_event(payload, request_meta, identity)`。
   - `write_processing_record(identity, record)`。
   - `processing_record_exists(identity)`。
6. 实现陌生人图片落盘 API：
   - `detect_image_type(image_bytes)` 支持 JPEG/PNG 魔数。
   - `save_stranger_image(identity, image_bytes, source, expected_md5)`。
   - 文件名格式为 `{event_time_compact}_{safe_serial}_{safe_event_id}_{md5_8_or_sha8}.{ext}`。
7. 验证：
   - `python3 -m py_compile app/services/event_store.py`。
   - 使用临时目录构造样本 payload，验证 raw、record、stranger 图片按日期目录生成。
   - 验证缺少 `pictureMd5` 时 dedupe key 会包含 `received_at`。
   - `git diff --check`。

本轮风险：

- 如果 dedupe key 设计过宽，可能合并不同事件；如果过窄，重复事件无法幂等。
- 如果路径清洗不严格，后续 token 图片查看会有路径穿越风险。

本轮回滚方式：

- 删除 `app/services/event_store.py`。
- 删除本节 Round 02 开发执行记录。

本轮提交策略：

- 本轮完成并验证后单独提交一次，提交信息需说明新增文件系统事件存储层，并明确尚未接入路由。

### 23.3 Round 03：LLD 步骤 3

本轮对应 LLD 步骤：

- 步骤 3：开发，建立图片 token 链接层。

本轮目标：

- 新增 `app/services/image_links.py`，负责陌生人图片查看链接的生成、保存和校验。
- 使用不透明随机 token，服务器只保存 `sha256(token)`，不保存 token 明文。
- 为后续 `GET /api/p6s/event-images/view/{token}` 路由提供可复用解析能力。

本轮范围：

- 新增 `app/services/image_links.py`。
- 复用 `event_store.py` 的事件根目录、日期目录和路径归属校验。
- 实现 token 生成、token 哈希、链接记录落盘、链接 URL 生成。
- 实现 token 访问解析、过期校验、目标图片路径校验、文件存在性校验。
- 实现访问计数 `access_count` 和 `last_accessed_at` 更新。
- 不新增 FastAPI 路由。
- 不改现有 `camera.py` 图片接口。
- 不改飞书通知逻辑。

具体开发计划：

1. 定义异常和数据结构：
   - `ImageLinkError`：图片链接基础异常。
   - `InvalidImageTokenError`：token 字符非法。
   - `ImageLinkNotFoundError`：找不到 token 哈希记录。
   - `ImageLinkExpiredError`：链接过期。
   - `ImageLinkTargetError`：图片路径非法、不存在或不是文件。
   - `CreatedImageLink`：返回 token、token_hash、view_url、record_path、expires_at。
   - `ResolvedImageLink`：返回 image_path、content_type、link_record。
2. 实现配置读取：
   - `P6S_EVENT_IMAGE_LINK_TTL_SECONDS` 默认 `86400`。
   - `P6S_EVENT_IMAGE_PUBLIC_BASE_URL` 优先。
   - 如果未配置图片专用前缀，则使用 `PUBLIC_BASE_URL + /api/p6s/event-images/view`。
3. 实现链接生成：
   - `token = secrets.token_urlsafe(32)`。
   - `token_hash = sha256(token)`。
   - 记录写入 `links/YYYY-MM-DD/{token_hash}.json`。
   - 记录中包含 `record_dedupe_key`、`relative_path`、`content_type`、`created_at`、`expires_at`、`access_count`、`last_accessed_at`。
4. 实现链接解析：
   - 清洗 token，只允许 `0-9A-Za-z_-`。
   - 在 `links/**/{token_hash}.json` 查找记录。
   - 校验 `expires_at`。
   - 使用 `relative_path` 定位图片，并确认目标在 `P6S_EVENT_IMAGE_DIR` 内。
   - 确认文件存在且是普通文件。
   - 成功时更新访问计数和最后访问时间。
5. 验证：
   - `python3 -m py_compile app/services/event_store.py app/services/image_links.py`。
   - 使用临时目录创建图片、生成 link、解析 link。
   - 验证伪造 token 抛出 not found。
   - 验证过期 token 抛出 expired。
   - 验证路径穿越记录无法解析。
   - `git diff --check`。

本轮风险：

- 如果 token 明文被写入文件，会造成链接泄露后无法控制。
- 如果 `relative_path` 没有严格限制在事件根目录内，后续公网图片接口可能产生路径穿越风险。

本轮回滚方式：

- 删除 `app/services/image_links.py`。
- 删除本节 Round 03 开发执行记录。

本轮提交策略：

- 本轮完成并验证后单独提交一次，提交信息需说明新增 token 图片链接层，并明确尚未接入 FastAPI 路由。

### 23.4 Round 04：LLD 步骤 4

本轮对应 LLD 步骤：

- 步骤 4：开发，改造飞书通知能力。

本轮目标：

- 改造 `app/services/feishu.py`，支持飞书自定义机器人签名。
- 支持富文本 `post` 消息，作为匹配成功和陌生人通知的首版消息格式。
- 新增匹配成功、陌生人和异常三类通知模板。
- 保持现有 `send_text`、`upload_image`、`send_image` 和 `notify_unknown_face(image_path=...)` 基本兼容，避免当前路由在后续接入前断裂。

本轮范围：

- 修改 `app/services/feishu.py`。
- `FeishuConfig` 增加 `webhook_secret`。
- `safe_summary()` 只返回布尔状态，不返回真实 webhook 或 secret。
- 新增 `send_post(title, lines)`。
- 新增 `notify_known_face(...)`。
- 扩展 `notify_unknown_face(...)`，支持 `storage_path` 和 `view_url`。
- 新增 `notify_event_error(...)`。
- 不接入 `p6s_events.py`。
- 不改路由。
- 不发送真实飞书消息。

具体开发计划：

1. 配置读取：
   - 从 `FEISHU_WEBHOOK_SECRET` 读取签名秘钥。
   - `safe_summary()` 增加 `has_webhook_secret` 和 `can_sign_webhook`。
2. Webhook 发送封装：
   - 新增 `_send_webhook_payload(payload, cfg)`。
   - 统一 `send_text`、`send_image`、`send_post` 的 webhook 请求路径。
   - 如果配置了 `webhook_secret`，按 LLD 签名算法增加 `timestamp` 和 `sign`。
3. 富文本消息：
   - `send_post(title, lines)` 发送 `msg_type=post`。
   - 支持 text 块和 link 块。
   - 控制消息内容简洁，不暴露内部堆栈。
4. 通知模板：
   - `notify_known_face(name, person_id, device_sn, event_time, event_id)`。
   - `notify_unknown_face(device_sn, event_time, event_id, storage_path, view_url, image_path)`。
   - `notify_event_error(message, device_sn, event_time, event_id, raw_event_path)`。
5. 兼容策略：
   - 保留 `send_text` 原接口。
   - 保留 `notify_unknown_face` 原有 `image_path` 参数。
   - 如果没有 `view_url`，仍可在配置了飞书应用凭证时走可选图片上传。
6. 验证：
   - `python3 -m py_compile app/services/feishu.py`。
   - 用 fake `requests.post` 验证 `FEISHU_WEBHOOK_SECRET` 会生成 `timestamp` 和 `sign`。
   - 验证 `send_post` 的 payload 是飞书 `post` 结构。
   - 验证 `notify_known_face` 和 `notify_unknown_face` 返回成功结果。
   - `git diff --check`。

本轮风险：

- 签名算法如果实现错误，飞书机器人会拒绝消息。
- 如果返回或日志中带出 webhook URL 或 secret，会造成密钥泄露。
- 如果直接破坏旧 `notify_unknown_face` 签名，当前路由在完整重构前会报错。

本轮回滚方式：

- 回滚 `app/services/feishu.py`。
- 删除本节 Round 04 开发执行记录。

本轮提交策略：

- 本轮完成并验证后单独提交一次，提交信息需说明飞书签名、富文本模板和兼容边界。

### 23.5 Round 05：LLD 步骤 5

本轮对应 LLD 步骤：

- 步骤 5：开发，建立 P6S 事件解析与分流层。

本轮目标：

- 新增 `app/services/p6s_events.py`，集中处理 P6S 事件标准化、分流、Ack、存储、图片保存、链接生成和飞书通知调用。
- 将 `FaceReco` 的 known、stranger、parse_error、ignored 分支固化为服务层结果。
- 为 Round 06 路由改造提供单一入口 `handle_event(...)`。

本轮范围：

- 新增 `app/services/p6s_events.py`。
- 小幅调整 `event_store.build_event_identity()`，让 `event_day` 优先使用可解析的事件时间，解析失败才使用 `received_at`。
- 不改 `app/routers/camera.py`。
- 不新增图片查看路由。
- 不连接摄像头，不发送真实飞书消息；验证时使用 `notify=False` 或 fake 方式。

具体开发计划：

1. 定义结果数据结构：
   - `MatchedPerson`：人员姓名、人员 ID、ack 用 `person_id`、缺字段标记。
   - `EventHandleResult`：Ack、分流结果、identity、raw file、record file、image、link、feishu、duplicate。
   - `DecodedEventImage`：图片来源、bytes、expected_md5。
2. 修正事件日期：
   - 在 `event_store.py` 中新增事件时间日期解析。
   - `EventIdentity.event_day` 优先使用 `info.time` 可解析出的日期。
   - 无法解析时继续使用 `received_at` 日期。
3. 实现入口：
   - `async def handle_event(payload, request_meta=None, root=None, notify=True)`。
   - 生成 identity。
   - 原始事件落盘。
   - 如果处理记录已存在，返回 Ack 但跳过通知，保证同一事件重复投递不重复通知。
4. 实现分流：
   - `heartbeat` 返回 heartbeat Ack。
   - 非 `FaceReco` 写入 ignored 记录并返回通用 Ack。
   - `FaceReco` 按 `matchNumber` 和 `personInfo` 判断 known、stranger、parse_error。
5. 实现 known：
   - 解析人员姓名和人员 ID。
   - 姓名缺失显示 `未知姓名`，ID 缺失显示 `未知ID`。
   - `P6S_EVENT_NOTIFY_KNOWN_PERSON=true` 时调用 `feishu.notify_known_face`。
   - 写入处理记录。
6. 实现 stranger：
   - 按 `CaptureImage`、`BackgroundImage`、`recognizeImage` 优先级提取图片。
   - 支持 data URL 和纯 base64。
   - 解码失败、缺图、格式不支持都写记录并发异常通知。
   - 图片保存成功后调用 `image_links.create_image_link`。
   - 调用 `feishu.notify_unknown_face`，传入保存路径和查看链接。
7. 实现 parse_error：
   - 写入处理记录。
   - 调用 `feishu.notify_event_error`，不暴露堆栈。
8. 实现 Ack：
   - heartbeat Ack 沿用现有策略。
   - FaceReco Ack 返回 `personId`、`uniqueId`、`pictureMd5`、`storedImage`。
   - 所有通知失败不影响 Ack。
9. 验证：
   - `python3 -m py_compile app/services/event_store.py app/services/image_links.py app/services/feishu.py app/services/p6s_events.py`。
   - 使用临时目录验证 known 样本、stranger 样本、missing image 样本、heartbeat 样本。
   - 验证重复调用同一 known 样本不会重复通知。
   - `git diff --check`。

本轮风险：

- 如果 known/stranger 分流条件实现错误，会导致陌生人不保存图片或已入库人员被误报。
- 如果重复事件判断过早，可能在首次处理失败后跳过补偿。
- 如果通知异常冒泡，会影响摄像头 Ack，引发摄像头重推。

本轮回滚方式：

- 删除 `app/services/p6s_events.py`。
- 回滚 `event_store.py` 中 event_day 解析调整。
- 删除本节 Round 05 开发执行记录。

本轮提交策略：

- 本轮完成并验证后单独提交一次，提交信息需说明新增 P6S 事件解析分流层，且尚未接入 FastAPI 路由。

### 23.6 Round 06：LLD 步骤 6

本轮对应 LLD 步骤：

- 步骤 6：开发，简化摄像头路由。

本轮目标：

- 改造 `app/routers/camera.py`，让 P6S 事件入口调用 `p6s_events.handle_event(...)`。
- 新增 `GET /api/p6s/event-images/view/{token}`，通过 `image_links.resolve_image_link(...)` 返回图片。
- 让路由层只负责鉴权、请求体限制、JSON 解析、异常到 HTTP 状态码转换和响应返回。

本轮范围：

- 修改 `app/routers/camera.py`。
- 小幅调整 `app/services/image_links.py`，细分路径非法和文件不存在异常，便于路由返回 `403` 或 `404`。
- 不改飞书模板。
- 不改摄像头管理、人脸库上传等后台 API。
- 不部署远程服务器。
- 不调用真实摄像头。

具体开发计划：

1. 事件入口改造：
   - 保留 `POST /api/p6s/events`。
   - 保留 `POST /api/p6s/events/{path_secret}`。
   - `_validate_event_secret` 继续支持路径、query 和 header 三种 secret。
   - 新增请求体大小检查，默认使用 `P6S_EVENT_MAX_BODY_BYTES=5242880`。
   - JSON 非对象或解析失败返回 `400`。
   - 调用 `await p6s_events.handle_event(payload, request_meta=...)`。
   - 返回 `EventHandleResult.ack`。
2. 请求元数据：
   - 从 `request.client.host`、`Content-Type`、`User-Agent`、method、path 构造 `event_store.RequestMeta`。
3. 图片 token 路由：
   - 新增 `GET /api/p6s/event-images/view/{token}`。
   - token 无效或记录不存在返回 `404`。
   - token 过期返回 `410`。
   - 路径非法返回 `403`。
   - 文件不存在返回 `404`。
   - 成功时返回 `FileResponse`，`media_type` 使用 link record 中的 `content_type`。
4. 旧图片接口：
   - 保留 `GET /api/p6s/event-images/{filename}` 作为历史排障接口。
   - 飞书消息和 README/DEPLOY 不使用该接口。
5. 清理旧逻辑：
   - 删除 `camera.py` 中旧的 FaceReco 图片保存、raw 扁平落盘、Ack 和 heartbeat strategy 业务逻辑。
   - 保留 `_event_dir()`、`_event_secret()`、`_public_base_url()` 等状态展示辅助函数。
6. 验证：
   - `python3 -m py_compile app/main.py app/routers/camera.py app/services/event_store.py app/services/image_links.py app/services/feishu.py app/services/p6s_events.py run.py`。
   - 使用 FastAPI `TestClient` 离线验证无 secret、错误 secret、合法 secret、known 事件、stranger 事件、token 图片查看。
   - 验证伪造 token `404`，过期 token `410`。
   - `git diff --check`。

本轮风险：

- 如果动态文件名路由优先于 `/view/{token}`，图片 token 路由会被吞掉。
- 如果事件入口同步发送飞书耗时过长，摄像头 Ack 可能变慢；首版先按服务层同步执行，后续可用 BackgroundTasks 优化。
- 如果错误映射不准确，飞书点击图片时可能难以区分过期和文件丢失。

本轮回滚方式：

- 回滚 `app/routers/camera.py` 和 `app/services/image_links.py`。
- 删除本节 Round 06 开发执行记录。

本轮提交策略：

- 本轮完成并验证后单独提交一次，提交信息需说明事件入口接入服务层和 token 图片查看路由。

### 23.7 Round 07：LLD 步骤 7

本轮对应 LLD 步骤：

- 步骤 7：验证，本地样本与静态验证。

本轮目标：

- 新增 P6S 事件 fixture，覆盖 known、stranger、missing image、heartbeat。
- 新增一个无需 pytest 的最小验证脚本，方便本地和远程服务器快速回归事件链路服务层。
- 将 Round 05/06 中手工执行过的样本验证固化成仓库文件。

本轮范围：

- 新增 `tests/fixtures/p6s_face_reco_known.json`。
- 新增 `tests/fixtures/p6s_face_reco_stranger.json`。
- 新增 `tests/fixtures/p6s_face_reco_missing_image.json`。
- 新增 `tests/fixtures/p6s_heartbeat.json`。
- 新增 `scripts/validate_p6s_event_flow.py`。
- 不引入 pytest 或新的第三方依赖。
- 不发送真实飞书消息。
- 不连接摄像头，不连接远程服务器。

具体开发计划：

1. Fixture 设计：
   - known 样本包含 `matchNumber=1` 和 `personInfo`。
   - stranger 样本包含 `matchNumber=0` 和可解码 JPEG base64。
   - missing image 样本包含 `matchNumber=0` 但不含图片。
   - heartbeat 样本包含 `operator=heartbeat`。
2. 验证脚本：
   - 使用临时目录作为 `P6S_EVENT_IMAGE_DIR` 根目录。
   - 调用 `p6s_events.handle_event(..., notify=False)`，避免真实飞书请求。
   - 验证 known 样本结果为 `known`。
   - 重复处理同一个 known 样本，验证第二次为 `duplicate`。
   - 验证 stranger 样本保存图片并生成 token link。
   - 验证处理记录不包含 token 明文。
   - 验证 missing image 样本不会生成图片。
   - 验证 heartbeat 返回 `heartbeat-Ack`。
3. 验证命令：
   - `python3 -m py_compile app/main.py app/routers/camera.py app/services/event_store.py app/services/image_links.py app/services/feishu.py app/services/p6s_events.py run.py scripts/validate_p6s_event_flow.py`。
   - `python3 scripts/validate_p6s_event_flow.py`。
   - `git diff --check`。

本轮风险：

- 如果 fixture 字段与真实 P6S 样本偏差太大，验证只能覆盖服务层通用逻辑，不能替代真机验证。
- 如果脚本依赖真实环境变量，可能误用本地/远程真实配置。

本轮回滚方式：

- 删除新增 fixture 和验证脚本。
- 删除本节 Round 07 开发执行记录。

本轮提交策略：

- 本轮完成并验证后单独提交一次，提交信息需说明新增 P6S 事件 fixture 和本地验证脚本。

### 23.8 Round 08：LLD 步骤 8

本轮对应 LLD 步骤：

- 步骤 8：配置，远程服务器前置初始化。

本轮目标：

- 在 `qypower-prod` 上准备应用目录、配置目录、日志目录和事件目录。
- 确认远程服务器具备 Python venv 和 Nginx 基础运行环境。
- 为后续发布代码、配置 systemd/Nginx 和摄像头 HTTP 推送做准备。

本轮范围：

- 通过 `ssh qypower-prod` 进行只读预检。
- 如预检通过，执行 Ubuntu 包和目录初始化。
- 设置 `/opt/camera-face-guard`、`/etc/camera-face-guard`、`/var/log/camera-face-guard`、`/var/lib/camera-face-guard/p6s_events` 的基础权限。
- 不上传代码。
- 不启动或重启服务。
- 不写入真实 `/etc/camera-face-guard/app.env` 内容，避免误把本地开发配置写到远程。
- 不配置摄像头。

具体配置计划：

1. 只读预检：
   - `ssh qypower-prod whoami`。
   - `ssh qypower-prod uname -a`。
   - `ssh qypower-prod python3 --version`。
   - `ssh qypower-prod nginx -v`，允许未安装。
   - `ssh qypower-prod sudo -n true`，确认 sudo 是否可非交互执行。
2. 初始化依赖：
   - `sudo apt update`。
   - `sudo apt install -y python3-venv nginx`。
3. 初始化目录：
   - `sudo mkdir -p /opt/camera-face-guard /etc/camera-face-guard /var/log/camera-face-guard /var/lib/camera-face-guard/p6s_events`。
   - `sudo chown -R ubuntu:ubuntu /opt/camera-face-guard /var/log/camera-face-guard /var/lib/camera-face-guard`。
   - `sudo chmod 750 /etc/camera-face-guard`。
4. 验证：
   - `ls -ld` 确认四个目录存在。
   - `python3 -m venv --help` 可用。
   - `nginx -v` 可用。
5. 提交：
   - 本轮如果只产生 LLD 执行记录，则提交 LLD 记录。

实际执行结果：

- 远程 SSH 预检通过，登录用户为 `ubuntu`。
- 远程系统为 Ubuntu，内核 `6.8.0-117-generic`。
- 远程 Python 为 `Python 3.12.3`。
- 远程 Nginx 为 `nginx/1.24.0 (Ubuntu)`。
- `sudo -n true` 通过，可非交互执行 sudo。
- `sudo apt update` 成功，当前有 `117` 个系统包可升级；本轮未做系统升级，避免扩大变更范围。
- `python3-venv` 和 `nginx` 已是最新可用版本，本轮未新增安装包。
- 已创建并验证目录：
  - `/opt/camera-face-guard`，owner 为 `ubuntu:ubuntu`。
  - `/etc/camera-face-guard`，owner 为 `root:root`，权限为 `750`。
  - `/var/log/camera-face-guard`，owner 为 `ubuntu:ubuntu`。
  - `/var/lib/camera-face-guard`，owner 为 `ubuntu:ubuntu`。
  - `/var/lib/camera-face-guard/p6s_events`，owner 为 `ubuntu:ubuntu`。
- 已验证 `python3 -m venv --help` 可用。
- 已验证 `nginx -v` 可用。
- `/etc/camera-face-guard/app.env` 当前不存在；本轮按计划不写真实 env，避免误用本地开发配置。
- 本轮未上传代码、未安装 systemd 服务、未修改 Nginx site、未启动服务、未配置摄像头。

本轮风险：

- 远程 sudo 如果需要交互密码，自动初始化会失败。
- 远程系统用户如果不是 `ubuntu`，目录 owner 需要调整。
- 写入真实 env 文件前必须再次确认配置来源，避免本地开发配置污染远程。

本轮回滚方式：

- 删除远程初始化目录需谨慎，只能在确认未存放用户数据后执行。
- 本轮不会上传代码或启动服务，因此失败时主要回滚 LLD Round 08 记录。

本轮提交策略：

- 本轮完成后单独提交一次，提交信息需说明远程前置初始化计划和实际状态。

### 23.9 Round 09：补充远程发布服务步骤

本轮对应 LLD 修正：

- 原步骤 8 已完成远程前置初始化。
- 原步骤 9 是配置摄像头 HTTP 推送，但在这之前必须先发布服务器代码并启动远程 Web 服务。
- 因此本轮补充“远程发布服务”步骤，位于远程前置初始化和摄像头配置之间。

本轮目标：

- 将当前已提交代码发布到 `qypower-prod:/opt/camera-face-guard/`。
- 将本地真实配置安全写入远程 `/etc/camera-face-guard/app.env`。
- 在远程创建 `.venv` 并安装 `requirements.txt`。
- 安装 systemd 服务和 Nginx site。
- 启动并验证 `camera-face-guard` 服务。
- 关闭 Uvicorn 与 Nginx access log，避免 `P6S_EVENT_SECRET` 和图片查看 token 出现在 HTTP 访问日志里。
- 发布后如果曾用旧 `P6S_EVENT_SECRET` 发起过验证请求，需要旋转该 token 并重启服务。

本轮范围：

- 只发布 Git 已提交内容，避免把当前工作区未提交的会员图片、CSV 或临时文件带到远程。
- 通过临时发布目录和 `rsync --delete` 同步到 `/opt/camera-face-guard/`。
- 通过 SSH 安全复制 `.env.local` 到远程临时文件，再移动为 `/etc/camera-face-guard/app.env`。
- 不在终端输出真实 env 值。
- 不输出、提交或记录任何真实 token；健康检查优先使用不含业务通知的 heartbeat fixture。
- 不配置摄像头。
- 不修改本地未跟踪会员数据。

具体执行计划：

1. 本地配置预检：
   - 只检查 `.env.local` 是否存在。
   - 只输出缺失的关键配置键，不输出任何真实值。
   - 关键键包括 `CAMERA_SESSION_SECRET`、`CAMERA_ADMIN_USERNAME`、`CAMERA_ADMIN_PASSWORD`、`P6S_EVENT_SECRET`、`P6S_EVENT_IMAGE_DIR`、`PUBLIC_BASE_URL`、`FEISHU_WEBHOOK_URL`、`FEISHU_WEBHOOK_SECRET`。
2. 生成干净发布包：
   - 使用 `git archive HEAD` 生成只包含已提交文件的 tar。
   - 解压到 `/tmp` 临时目录。
   - 使用 `rsync -a --delete` 发布到 `qypower-prod:/opt/camera-face-guard/`。
3. 远程 env：
   - 使用 `rsync -a .env.local qypower-prod:/tmp/camera-face-guard-app.env`。
   - 远程执行 `sudo mv`、`sudo chown root:root`、`sudo chmod 640`。
4. 远程依赖：
   - `cd /opt/camera-face-guard`。
   - `python3 -m venv .venv`。
   - `.venv/bin/pip install -r requirements.txt`。
5. systemd/Nginx：
   - 复制 `scripts/qypower-camera.service` 到 `/etc/systemd/system/camera-face-guard.service`。
   - 复制 `scripts/qypower-nginx.conf` 到 `/etc/nginx/sites-available/camera-face-guard`。
   - 创建 sites-enabled 软链。
   - systemd 模板使用 `uvicorn --no-access-log`。
   - Nginx site 使用 `access_log off`。
   - 禁用 Nginx 默认站点软链，确保公网 IP 访问进入 camera-face-guard。
   - `systemctl daemon-reload`。
   - `systemctl enable --now camera-face-guard`。
   - `nginx -t`。
   - `systemctl reload nginx`。
6. 验证：
   - `systemctl status camera-face-guard --no-pager`。
   - `curl GET http://127.0.0.1:8000/camera`，预期 200；不要用 `HEAD` 判断页面健康，因为当前 FastAPI 静态页路由对 `HEAD` 返回 405。
   - `curl GET http://127.0.0.1/camera`，预期 200。
   - `curl GET http://82.156.198.180/camera`，预期 200。
   - 远程执行 `python3 scripts/validate_p6s_event_flow.py`。
   - 使用远程真实 `/etc/camera-face-guard/app.env` 中的 `P6S_EVENT_SECRET` POST heartbeat fixture 到本机事件入口，预期返回 `heartbeat-Ack`，且不触发飞书通知。

本轮风险：

- `.env.local` 可能缺少远程运行所需键。
- pip 可能因远程网络问题安装失败。
- Nginx reload 可能受现有站点配置影响。
- `rsync --delete` 会删除 `/opt/camera-face-guard/` 中不在 Git 提交里的文件，因此该目录只能作为应用发布目录使用。
- 如果 access log 未关闭，事件回调 URL 中的 `P6S_EVENT_SECRET` 或图片查看 token 可能进入 systemd/Nginx 日志；本轮必须通过关闭 access log 与旋转 token 规避。

本轮回滚方式：

- 停止远程服务：`sudo systemctl stop camera-face-guard`。
- 禁用远程服务：`sudo systemctl disable camera-face-guard`。
- 回滚代码需重新 rsync 上一个 Git 提交的发布包。
- 如果怀疑 `P6S_EVENT_SECRET` 泄露，重新生成 `.env.local` 与 `/etc/camera-face-guard/app.env` 中的 `P6S_EVENT_SECRET`，重启服务，并同步更新摄像头事件回调路径。

本轮实际执行结果：

- 本地 `.env.local` 已补齐远程服务必需键，预检结果为 15 个关键键全部非空；真实值未输出、未提交。
- 已使用 `git archive HEAD` 从 `31e0e7e` 生成干净发布包，并通过 `rsync -a --delete` 同步到 `qypower-prod:/opt/camera-face-guard/`。
- 已将 `.env.local` 同步到远程临时文件，再移动为 `/etc/camera-face-guard/app.env`；远程预检结果为 15 个关键键全部非空。
- 已在远程 `/opt/camera-face-guard/.venv` 创建虚拟环境，并成功安装 `fastapi`、`uvicorn[standard]`、`requests` 等依赖。
- 已安装 `/etc/systemd/system/camera-face-guard.service`，服务状态为 `active`，开机状态为 `enabled`。
- 已安装 `/etc/nginx/sites-available/camera-face-guard` 并启用软链，已删除 `/etc/nginx/sites-enabled/default` 默认站点软链，`nginx -t` 通过并已 reload。
- 初次用真实事件入口做 heartbeat 验证时发现 Uvicorn access log 会记录完整事件 URL；本轮已按安全修正关闭 Uvicorn 与 Nginx access log，并旋转 `P6S_EVENT_SECRET`。
- 旋转 token 后，`GET http://127.0.0.1:8000/camera`、`GET http://127.0.0.1/camera`、`GET http://82.156.198.180/camera` 均返回 200。
- 远程执行 `scripts/validate_p6s_event_flow.py` 通过，输出 `P6S event flow fixtures validated`。
- 使用远程真实 `P6S_EVENT_SECRET` 经 Nginx POST heartbeat fixture 到 `/api/p6s/events/<secret>`，返回 200 和 `heartbeat-Ack`，且不会触发飞书通知。
- 重启后的 `journalctl -u camera-face-guard --since=-1min` 只显示服务停止/启动日志，没有新的请求 URL access log。
- `HEAD /camera` 返回 405 属于当前 FastAPI 静态页路由行为，不作为健康失败；健康检查必须使用 `GET`。

本轮偏差记录：

- 曾有一次远程命令引号传递错误，把虚拟环境误创建到远程 `/home/ubuntu/.venv`；该目录未安装业务依赖，暂不删除，避免未经确认清理用户家目录内容。正式运行使用的是 `/opt/camera-face-guard/.venv`。

本轮提交策略：

- 本轮完成后单独提交一次，提交信息需说明补充了远程发布步骤和实际部署验证结果。

### 23.10 Round 10：LLD 步骤 9，配置摄像头 HTTP 事件推送

本轮对应 LLD 步骤：

- 步骤 9：配置摄像头 HTTP 事件推送。
- 配置 `/System/HTTPEventServerConfigV2` 指向 `qypower-prod`。
- 审计 `/System/EventPushMode`、`/System/AIEventCfg`、`/AI/FaceSnapshotCfg`、`/FaceReco/1/RecoRuleList`。
- 使用 `/System/HTTPEventServerTest` 做摄像头侧连通性测试。

本轮文档依据：

- `docs/p6scgi-showdoc/01 API/网络配置管理/平台接入/P6SEvent/HTTP/获取HTTP服务器配置信息V2__149226750.md`。
- `docs/p6scgi-showdoc/01 API/网络配置管理/平台接入/P6SEvent/HTTP/设置HTTP服务器配置信息V2__149226751.md`。
- `docs/p6scgi-showdoc/01 API/网络配置管理/平台接入/P6SEvent/HTTP/HTTP服务器状态测试__149226754.md`。
- `docs/p6scgi-showdoc/01 API/未分类/获取人脸识别事件推送模式__149230105.md`。
- `docs/p6scgi-showdoc/01 API/智能事件配置管理/人脸相关配置管理接口/人脸抓拍配置管理/获取智能人脸抓拍界面配置__149227113.md`。
- `docs/p6scgi-showdoc/01 API/智能事件配置管理/人脸相关配置管理接口/人脸识别配置管理/获取通道人脸识别规则列表__149227024.md`。

本轮目标：

- 支持摄像头账号为空密码的真实情况，避免把空密码误判为“未配置”。
- 在 `app/services/p6s_camera.py` 中补齐 P6S HTTP 事件相关 API 封装。
- 新增一个可重复执行的配置/审计脚本，避免用一次性手工 curl 配置摄像头。
- 将本地真实摄像头连接配置写入 `.env.local`，不写入 git。
- 对摄像头写入 HTTP 事件服务器配置：`Enable=true`、`Protocol=http`、`Host=82.156.198.180`、`Port=80`、`URLPath=/api/p6s/events/{P6S_EVENT_SECRET}`、`AuthMode=none`、`CacheEventEnable=true`。
- 运行 `/System/HTTPEventServerTest`，确认摄像头能访问远程服务。
- 从远程服务器侧验证测试请求是否产生事件文件或可解释的返回结果。

本轮范围：

- 允许修改 `app/services/p6s_camera.py`，新增摄像头 HTTP 事件配置相关封装。
- 允许新增 `scripts/configure_p6s_http_events.py`，用于读取 env、生成 XML、写入配置、运行测试和输出脱敏摘要。
- 允许更新 `README.md`、`DEPLOY.md` 的步骤 9 说明。
- 允许更新 `.env.local` 的 `P6S_CAMERA_HOST`、`P6S_CAMERA_USERNAME`、`P6S_CAMERA_PASSWORD`，其中真实值不提交。
- 本轮只审计 `/System/AIEventCfg`、`/AI/FaceSnapshotCfg`、`/FaceReco/1/RecoRuleList`；除非文档和当前返回都明确支持且风险可控，否则不批量改动这些识别规则，避免覆盖之前调好的摄像头识别配置。
- 不配置摄像头人脸库，不触发真实人员识别验证；这些属于步骤 10。

具体开发计划：

1. 修正摄像头配置识别：
   - `P6SConfig` 增加 `password_configured` 概念。
   - `P6S_CAMERA_PASSWORD=` 空值在 key 存在时视为已配置。
   - `configured()` 判断改为 base url、username、password key 均存在。
   - `safe_summary()` 不输出密码明文，只区分 `configured`、`blank`、`set`、`missing`。
2. 增加 HTTP 事件 API 封装：
   - 摄像头位于局域网地址，`P6SCameraClient` 发起设备请求时必须禁用 `HTTP_PROXY`、`HTTPS_PROXY` 等环境代理，避免本机代理拦截 `192.168.x.x` 请求。
   - `get_http_event_server_config()`：GET `/System/HTTPEventServerConfigV2`。
   - `set_http_event_server_config(host, port, url_path, protocol, timeout, cache_event_enable)`：PUT `/System/HTTPEventServerConfigV2`。
   - `test_http_event_server(test_text)`：POST `/System/HTTPEventServerTest`。
   - `get_event_push_mode()`：GET `/System/EventPushMode`。
   - `get_ai_event_cfg()`：GET `/System/AIEventCfg`，若固件不支持则记录为 unsupported。
   - `get_face_snapshot_cfg()`：GET `/AI/FaceSnapshotCfg`。
   - `get_face_reco_rule_list(channel_id=1)`：GET `/FaceReco/1/RecoRuleList`。
3. 新增配置脚本：
   - 默认读取 `.env.local`，也允许通过 `CAMERA_ENV_FILE` 覆盖。
   - 默认先做 dry-run/audit，只有传入 `--apply` 才写入 `/System/HTTPEventServerConfigV2`。
   - 输出必须脱敏：不打印完整 `P6S_EVENT_SECRET`，不打印完整 `URLPath`，不打印摄像头密码。
   - 写入后重新 GET 配置，确认 Host/Port/Protocol/Enable/AuthMode/CacheEventEnable 匹配；URLPath 只做内部比较，不输出明文。
   - 运行测试时使用不含密钥的 `Test` 文本。
4. 本地配置：
   - `.env.local` 写入当前局域网摄像头地址 `P6S_CAMERA_HOST`。
   - `.env.local` 写入摄像头账号 `P6S_CAMERA_USERNAME`。
   - `.env.local` 写入 `P6S_CAMERA_PASSWORD=`，表示空密码。
5. 验证：
   - `python3 -m py_compile app/services/p6s_camera.py scripts/configure_p6s_http_events.py`。
   - 运行脚本 audit，确认摄像头可连接且当前配置可读取。
   - 运行脚本 `--apply --test`，写入 HTTP 事件配置并执行摄像头测试。
   - 远程检查 `/var/lib/camera-face-guard/p6s_events/raw/YYYY-MM-DD/` 是否新增测试事件；如果测试事件不是 JSON 导致服务端拒绝，需要记录摄像头返回和远程可观测证据，不盲目重试。
6. 提交：
   - 只提交代码、脚本和文档。
   - 不提交 `.env.local`。
   - 不提交 STYD 会员图片和报表临时文件。

本轮风险：

- 摄像头当前 IP 可能再次变化，导致连接失败。
- 本机开发环境可能设置了 HTTP/HTTPS 代理；如果不禁用代理，局域网摄像头请求会被错误发送到代理端口。
- 空密码如果仍被设备拒绝，需要停下来确认账号状态。
- `/System/HTTPEventServerTest` 的真实请求体可能不是 JSON；如果远程事件入口返回 400，需记录这个协议差异，不能盲目重试。
- 关闭 access log 后，不能依赖 Nginx/Uvicorn URL 日志判断请求；需要依赖测试返回、业务事件目录或安全脱敏的应用记录。
- 写 `/System/HTTPEventServerConfigV2` 会改变摄像头全局 HTTP 事件推送目标；回滚需要关闭 Enable 或恢复旧配置。

本轮回滚方式：

- 将 `/System/HTTPEventServerConfigV2.Enable` 改为 `false`，其他字段保留。
- 或将脚本审计到的旧配置重新 PUT 回 `/System/HTTPEventServerConfigV2`。
- 如果测试期间产生错误事件文件，可按日期目录人工删除对应测试文件。
- 本地回滚代码使用 `git revert` 本轮提交。

本轮停止条件：

- 摄像头连续无法连接，且确认不是本地网络权限问题。
- 摄像头返回认证失败或空密码不被接受。
- 写入 `/System/HTTPEventServerConfigV2` 后 GET 返回与写入不一致。
- `/System/HTTPEventServerTest` 返回无法解释的错误码，且远程侧没有任何可观测证据。

本轮提交策略：

- 本轮完成后单独提交一次，提交信息需说明支持空密码摄像头连接、增加 HTTP 事件配置脚本、完成或阻塞的真机配置验证结论。

本轮实际执行结果：

- 已确认 `.env.local` 原本缺少 `P6S_CAMERA_HOST`、`P6S_CAMERA_USERNAME`、`P6S_CAMERA_PASSWORD`；本轮已按本地真实配置规则写入当前摄像头地址、账号和空密码标记，真实配置未提交。
- 已修正 `P6SConfig.configured()`，支持 `P6S_CAMERA_PASSWORD=` 空密码场景；后台状态页可显示“空密码”。
- 已新增 `scripts/configure_p6s_http_events.py`，支持只读审计、`--apply` 写入 HTTP 事件服务器配置、`--test` 调用摄像头测试接口，且输出会脱敏 `P6S_EVENT_SECRET` 和回调路径。
- 首次审计时发现本机代理环境会劫持局域网请求到 `127.0.0.1:7890`；已在 `P6SCameraClient` 中使用 `requests.Session(trust_env=False)` 禁用环境代理。
- 只读审计成功连接摄像头，确认空密码认证可用。
- 写入前 `/System/HTTPEventServerConfigV2` 状态：`Enable=false`、`AuthMode=OAuth`、`CacheEventEnable=false`、`Host` 为空、`URLPath` 为空。
- 已写入 `/System/HTTPEventServerConfigV2`：`Enable=true`、`Protocol=http`、`Host=82.156.198.180`、`Port=80`、`AuthMode=none`、`CacheEventEnable=true`、`URLPath=/api/p6s/events/<P6S_EVENT_SECRET>`。
- 写入后重新 GET 校验通过，`URLPath` 与远程 `P6S_EVENT_SECRET` 匹配，输出中只显示脱敏路径。
- `/System/HTTPEventServerTest` 返回 `StatusCode=0`、`EventID=240`、`Time=20260702T201928+08`。
- 远程 raw 事件文件数量从 2 增加到 3；新增文件位于 `/var/lib/camera-face-guard/p6s_events/raw/2026-07-02/`，解析后的 payload 为 `operator=heartbeat`，不会触发飞书通知。
- `/System/AIEventCfg` 在当前固件返回 404，提示 `/System/AIEventCfg` 不支持；后续不再把该接口作为强制配置项。
- `/AI/FaceSnapshotCfg` 审计结果：`Enable=true`、`Trigger.Push.Enable=true`、`Trigger.Snapshot.Enable=true`、`IsCaptureBackground=true`、`ShowFaceFrame=true`。
- `/FaceReco/1/RecoRuleList` 审计结果：当前仅 1 条规则，`RecognitionRule=Comparison pass`、`ControlPersonnelType=OrganizationMember`、`Trigger.Push.Enable=true`、`Trigger.Snapshot.Enable=true`，但 `RecoRule.Enable=false`，这会影响后续真实人脸识别事件触发。

本轮遗留问题：

- HTTP 事件推送链路已经打通，但人脸识别规则当前为 `Enable=false`。本轮按照计划只审计不修改识别规则，避免覆盖摄像头既有规则；步骤 10 开始前需要单独设计一轮，读取完整 `/FaceReco/1/RecoRuleList` XML，最小化修改 `RecoRule.Enable=true` 后再做真机识别验证。

### 23.11 Round 11：步骤 10 前置，最小化启用人脸识别规则

本轮对应 LLD 修正：

- Round 10 已打通 HTTP 事件推送，但审计发现 `/FaceReco/1/RecoRuleList` 中 `RecoRule.Enable=false`。
- 如果不启用识别规则，步骤 10 的已入库人员和陌生人真机识别事件很可能不会触发。
- `/FaceReco/1/RecoRuleList` 的 PUT 接口要求提交完整规则 XML，不能只提交局部字段。

本轮文档依据：

- `docs/p6scgi-showdoc/01 API/智能事件配置管理/人脸相关配置管理接口/人脸识别配置管理/获取通道人脸识别规则列表__149227024.md`。
- `docs/p6scgi-showdoc/01 API/智能事件配置管理/人脸相关配置管理接口/人脸识别配置管理/设置通道人脸识别规则列表__149227025.md`。

本轮目标：

- 新增可重复执行的人脸识别规则审计/最小修改脚本。
- 脚本执行前保存当前完整 XML 备份，用于回滚。
- 只把每个 `<RecoRule>` 的第一层 `<Enable>` 改成 `true`。
- 不修改 `RecognitionRule`、`CompareLimit`、`FaceGroupList`、`ControlPersonnelType`、`Schedule`、`EventTimeSlotList`、`Trigger` 等字段。
- 写入后重新 GET `/FaceReco/1/RecoRuleList`，确认 `RecoRule.Enable=true`，同时关键字段未被脚本主动改动。

本轮范围：

- 允许修改 `app/services/p6s_camera.py`，新增 `set_face_reco_rule_list(xml_text, channel_id=1)`。
- 允许新增 `scripts/configure_p6s_face_reco_rule.py`。
- 允许更新 `README.md`、`DEPLOY.md` 中的识别规则启用说明。
- 允许对摄像头执行 PUT `/FaceReco/1/RecoRuleList`，但只能使用脚本最小化修改后的完整 XML。
- 不修改人脸抓拍配置 `/AI/FaceSnapshotCfg`。
- 不修改 HTTP 事件服务器配置。
- 不修改人脸库或人员资料。

具体开发计划：

1. 服务封装：
   - 在 `P6SCameraClient` 中新增 `set_face_reco_rule_list(xml_text, channel_id=1)`。
   - 继续复用禁用环境代理的 session。
2. 脚本设计：
   - 默认读取 `.env.local`，允许 `CAMERA_ENV_FILE` 覆盖。
   - 默认只读审计，输出 `rule_count`、每条规则的 `Enable`、`RecognitionRule`、`CompareLimit`、`ControlPersonnelType`、`Trigger.Push.Enable`、`Trigger.Snapshot.Enable`。
   - 只有传入 `--apply` 才写入。
   - 写入前把完整 XML 保存到 `/private/tmp` 或系统临时目录，不放入 git 工作区。
   - 修改逻辑只定位 `RecoRule/Enable`；如果缺少该节点则停止，不猜测新建。
   - 写入后回读并确认所有 `RecoRule/Enable=true`。
3. 真机配置：
   - 先运行只读审计确认当前仍为 `Enable=false`。
   - 运行 `--apply` 写入最小修改。
   - 再运行只读审计确认 `Enable=true`。
4. 验证：
   - `python3 -m py_compile app/services/p6s_camera.py scripts/configure_p6s_face_reco_rule.py`。
   - 脚本审计和 apply 均成功。
   - 回读摘要确认 `Trigger.Push.Enable=true` 和 `Trigger.Snapshot.Enable=true` 未被改坏。
5. 提交：
   - 只提交代码、脚本和文档。
   - 不提交 `.env.local`。
   - 不提交脚本生成的 XML 备份。

本轮风险：

- PUT 完整 XML 时设备可能重写部分字段格式。
- 当前 `CompareLimit=0` 含义未在真机上完全确认；本轮不修改，避免扩大影响面。
- 如果当前 XML 缺少第一层 `RecoRule/Enable`，脚本必须停止，不自动创建节点。
- 如果写入后回读发现非目标字段变化，需要停止并记录差异，不能继续真机识别验证。

本轮回滚方式：

- 使用脚本执行前保存的完整 XML 备份，重新 PUT 到 `/FaceReco/1/RecoRuleList`。
- 或在脚本中增加后续 `--restore <xml>` 模式后回滚。
- 本地代码回滚使用 `git revert` 本轮提交。

本轮停止条件：

- 读取 `/FaceReco/1/RecoRuleList` 失败。
- 解析 XML 失败。
- XML 中没有可定位的 `RecoRule/Enable`。
- PUT 后返回非 2xx 或响应 `statusCode` 非 0。
- PUT 后回读仍有 `RecoRule.Enable=false`。

本轮提交策略：

- 本轮完成后单独提交一次，提交信息需说明最小化启用人脸识别规则、保存备份、回读验证结果。

本轮实际执行结果：

- 已新增 `set_face_reco_rule_list(xml_text, channel_id=1)`，用于 PUT 完整 `/FaceReco/1/RecoRuleList` XML。
- 已新增 `scripts/configure_p6s_face_reco_rule.py`，支持只读审计、`--apply` 最小化启用、执行前 XML 备份和 `--restore <xml>` 回滚。
- 静态编译通过：`python3 -m py_compile app/services/p6s_camera.py scripts/configure_p6s_face_reco_rule.py scripts/configure_p6s_http_events.py`。
- 只读审计成功，当前规则摘要仍为：`rule_count=1`、`RecoRule.Enable=false`、`RecognitionRule=Comparison pass`、`CompareLimit=0`、`ControlPersonnelType=OrganizationMember`、`Trigger.Push.Enable=true`、`Trigger.Snapshot.Enable=true`。
- 执行过一次 `python3 scripts/configure_p6s_face_reco_rule.py --apply`。脚本已在系统临时目录保存执行前完整 XML 备份。
- 写入后立即回读，`RecoRule.Enable` 仍为 `false`，触发本轮停止条件：`PUT 后回读仍有 RecoRule.Enable=false`。
- 已停止继续写入，没有盲目重试，也没有进入步骤 10 真机识别验证。

本轮阻塞结论：

- 当前设备对 PUT `/FaceReco/1/RecoRuleList` 返回链路没有表现为网络失败或认证失败，但最小化 XML 写入没有持久化 `RecoRule.Enable=true`。
- 可能原因包括：设备要求特定 XML 格式/字段组合、需要通过后台 UI 或其他关联接口启用规则、`CompareLimit=0` 或 `ControlPersonnelType=OrganizationMember` 组合导致规则被设备回写为禁用、或该固件对该接口有隐藏约束。
- 下一步需要先定位为什么 PUT 后不持久化，再决定是否通过后台 UI、完整原始 XML 格式、或更小范围接口解决；在此之前不能继续步骤 10 的真实识别通知验证。

### 23.12 Round 12：诊断 RecoRule.Enable 写入不持久化

本轮对应 LLD 修正：

- Round 11 的最小化 XML 写入没有持久化 `RecoRule.Enable=true`。
- 按停止条件，不能继续盲目重复 PUT。
- 本轮先增强诊断能力，确认是脚本 XML 序列化问题、设备响应问题，还是规则字段组合问题。

本轮目标：

- 只读采集当前 `/FaceReco/1/RecoRuleList` 完整 XML 的结构摘要。
- 比对 Round 11 备份 XML、当前 XML、脚本拟写入 XML 的差异。
- 改造脚本，使其支持两种补丁模式：
  - `elementtree`：当前模式，解析 XML 后改 `RecoRule/Enable`。
  - `raw-text`：保留设备原始 XML 字符串，只替换第一个 `<RecoRule ...>` 内的第一层 `<Enable>false</Enable>` 为 `<Enable>true</Enable>`，避免 ElementTree 改写 namespace、Version 属性顺序、空标签和缩进。
- 脚本在写入后必须打印设备响应摘要：HTTP 状态、`ResponseStatus.statusCode`、`message`、回读摘要、备份路径。
- 只有在只读差异分析支持“上轮可能是 XML 序列化导致设备忽略”的前提下，才允许执行一次 `raw-text --apply` 受控写入。

本轮范围：

- 允许修改 `scripts/configure_p6s_face_reco_rule.py`。
- 允许新增脚本内部的差异摘要函数，不新增依赖。
- 允许对摄像头执行最多一次 PUT `/FaceReco/1/RecoRuleList`，前提是先完成只读差异分析并保存备份。
- 不修改 HTTP 事件配置。
- 不修改人脸库、人员资料、人脸抓拍配置。
- 不进入步骤 10 端到端人脸识别验证，除非本轮能证明 `RecoRule.Enable=true` 已持久化。

具体开发计划：

1. 脚本增强：
   - 增加 `--patch-mode elementtree|raw-text`，默认仍为 `elementtree`。
   - 增加 `--print-diff-summary`，输出拟修改字段数量、目标规则索引、非目标字段摘要。
   - 增加 `raw_text_enable_rules(xml_text)`，只在 `RecoRule` 节点内部替换第一层 `<Enable>false</Enable>`。
   - 增加 `WRITE_RESULT` 输出，包含 HTTP 状态、设备 `statusCode` 和 `message`。
2. 只读诊断：
   - 运行脚本只读审计，确认当前仍为 `Enable=false`。
   - 运行 `--print-diff-summary --patch-mode raw-text`，确认拟改动只有 `RecoRule.Enable`。
   - 检查 Round 11 备份 XML 路径存在，可用于回滚。
3. 受控写入：
   - 如果只读诊断证明 raw-text 只改一个目标字段，则执行一次 `--apply --patch-mode raw-text`。
   - 写入后立即 GET 回读。
   - 如果仍为 false，立即停止，记录设备响应和结论。
4. 验证：
   - `python3 -m py_compile scripts/configure_p6s_face_reco_rule.py app/services/p6s_camera.py`。
   - 暂存区不包含 `.env.local`、XML 备份或 STYD 数据。

本轮风险：

- `raw-text` 替换如果误匹配嵌套 `Enable` 会误改 Trigger 字段，因此必须限定在第一个 `<RecoRule>` 的开始/结束范围内。
- 设备可能返回 `statusCode=0` 但仍忽略字段；此时不能再继续写，需要考虑 UI 或其他接口。
- 如果设备回读 XML 自动格式化，不能仅靠文本 diff 判断失败，必须以字段摘要为准。

本轮回滚方式：

- 如写入成功但后续表现异常，使用脚本 `--restore <backup.xml>` 恢复执行前完整 XML。
- 如写入失败且回读未变化，无需回滚摄像头配置。
- 本地代码回滚使用 `git revert` 本轮提交。

本轮停止条件：

- raw-text 差异分析显示会改动非目标字段。
- 设备响应 `ResponseStatus.statusCode` 非 0。
- raw-text 写入后回读仍为 `RecoRule.Enable=false`。
- 回读发现 `Trigger.Push.Enable` 或 `Trigger.Snapshot.Enable` 被改坏。

本轮提交策略：

- 本轮完成后单独提交一次，提交信息需说明诊断脚本增强、是否执行 raw-text 受控写入、以及设备回读结论。

本轮实际执行结果：

- 已增强 `scripts/configure_p6s_face_reco_rule.py`：
  - 新增 `--patch-mode elementtree|raw-text`。
  - 新增 `--print-diff-summary`。
  - `raw-text` 模式只在 `<RecoRule>` 范围内替换第一层 `<Enable>false</Enable>`。
  - 写入时输出 `WRITE_RESULT`，包含 HTTP 状态、设备 `ResponseStatus.statusCode`、设备 message、patch mode 和变更数量。
- 静态编译通过：`python3 -m py_compile scripts/configure_p6s_face_reco_rule.py app/services/p6s_camera.py`。
- 只读 raw-text diff-summary 结果：
  - 目标规则索引为 `0`。
  - 拟修改数量为 `1`。
  - `enable` 从 `false` 变为 `true`。
  - `RecognitionRule`、`CompareLimit`、`ControlPersonnelType`、`Trigger.Push.Enable`、`Trigger.Snapshot.Enable` 等非目标字段无差异。
- 按本轮计划执行过一次受控写入：`python3 scripts/configure_p6s_face_reco_rule.py --apply --patch-mode raw-text`。
- 写入前已在系统临时目录保存完整 XML 备份。
- 设备写入响应：HTTP `200`，设备 `ResponseStatus.statusCode=0`，message 为空。
- 写入后立即回读，`RecoRule.Enable` 仍为 `false`，触发本轮停止条件：`raw-text 写入后回读仍为 RecoRule.Enable=false`。
- 本轮未继续重复 PUT，也未进入步骤 10 真机端到端识别验证。

本轮诊断结论：

- `elementtree` 和 `raw-text` 两种补丁模式都无法让 `RecoRule.Enable=true` 持久化。
- 设备返回 `statusCode=0` 但字段不持久化，说明当前问题不再像是 XML 序列化问题或 HTTP/认证问题。
- 更可能的方向是：该固件把 `RecoRule.Enable` 作为只读/派生字段、需要通过其他关联字段或 UI 启用、当前规则组合不允许启用，或需要完整后台页面保存流程触发额外接口。
- 下一步不能继续盲目重试 PUT `/FaceReco/1/RecoRuleList`；需要先通过摄像头 Web 后台操作或浏览器/接口抓包确认 UI 启用规则时实际调用了哪些接口和提交了哪些字段。

### 23.13 Round 13：方式3，确认 Web 后台真实启用路径

本轮目标：

- 按“方式3”推进：把摄像头 Web 后台作为真实来源，确认后台启用人脸识别规则时实际访问的接口、请求方法、请求体和字段变化。
- 优先通过离线 ShowDoc 和浏览器/接口轨迹找出 `RecoRule.Enable` 不持久化的根因，避免继续对同一个 PUT 接口做无依据重试。
- 形成可执行结论：如果能确认正确启用接口，则再设计下一轮最小配置写入；如果不能确认，则明确需要人工在 Web 后台操作并提供抓包证据。

本轮范围：

- 只读检索 `docs/p6scgi-showdoc` 中 `FaceReco`、人脸识别规则、识别区域、布防计划、联动策略、Web 后台配置保存相关接口。
- 只读采集当前设备的人脸抓拍、人脸识别规则、事件推送模式和可能的人脸识别关联配置摘要。
- 如需要浏览器验证，只允许打开摄像头 Web 后台并观察网络请求；不在 UI 上保存配置，除非先追加 LLD 并说明会改变哪些设备配置。
- 允许补充只读诊断脚本或文档记录；不允许真实修改摄像头配置。

本轮不做：

- 不再重复 PUT `/FaceReco/1/RecoRuleList`。
- 不进入端到端人脸识别触发测试。
- 不修改远程服务器、飞书 webhook 或已部署服务。
- 不把摄像头密码、事件 token、飞书秘钥写入文档或 git。

影响面：

- 文档影响：更新本 LLD 中关于 `RecoRule.Enable` 不持久化的根因判断和后续动作。
- 代码影响：如果新增诊断能力，仅限只读查询和摘要输出，不改变运行时服务行为。
- 设备影响：本轮预期无设备配置变更。

风险点：

- 摄像头 Web 后台可能通过前端状态组合多个接口，单看一个保存按钮不一定能直接定位根因。
- 浏览器抓包可能包含登录态或认证信息，记录到文档时必须脱敏。
- 如果设备固件与 ShowDoc 不一致，需要以真机返回和 Web 后台请求为准。

回滚方式：

- 本轮不写设备配置，正常不需要设备回滚。
- 如果只读诊断脚本引入问题，删除或回退该脚本即可。
- 如果文档判断不准确，下一轮先修订 LLD 后再继续。

验证方式：

- 使用 `rg` 对离线 ShowDoc 做限定关键词检索，输出命中的接口文件和关键字段。
- 运行只读诊断命令，确认当前设备相关配置摘要可读，且未触发写接口。
- 如发生代码变更，运行 `python3 -m py_compile` 验证脚本和服务模块语法。
- 最终把“是否找到替代启用路径、是否需要 Web 后台人工操作、下一轮是否可以安全写入”的结论写回本节。

本轮只读验证记录：

- 离线 ShowDoc 确认 `/FaceReco/ChannelID/RecoRuleList` 是人脸识别规则列表接口，字段受 `Device-FunctionListAboutChannel-ChannelList-Channel-FaceReco` 能力限制。
- 离线 ShowDoc 确认 `/Pictures/ChannelID/FaceDetect` 是“普通事件-人脸侦测”配置接口，字段受 `DeviceCap-FaceDetect-Support` 能力限制。
- 离线 ShowDoc 确认 `/System/AIWorkMode` 存在 `PeopleMode` 和 `FaceMode`，但当前设备只读返回空 `<AIWorkMode />`，不能作为本机启用依据。
- 通过 Web 后台页面实现定位到 `ipc/js/route.json` 中 `fcrecognition` 菜单实际打开 `ipc/pages/events/Facerecognition.html`。
- `Facerecognition.html` 实际加载 `ipc/js/events/Facerecognition.js`。
- `Facerecognition.js` 中人脸识别总开关绑定到 `/FaceReco/1/BaseConfig`，字段为 `FaceBaseConfig/EnableRecognition`。
- `Facerecognition.js` 中 `/FaceReco/1/RecoRuleList` 主要用于布控人员、布防时间和联动方式配置；Web 后台保存联动方式时修改的是 `Trigger/BeepAlert`、`Trigger/Push`、`Trigger/Snapshot`、`Trigger/Record`、`Trigger/LightAlarm` 等字段，没有读取或写入第一层 `RecoRule/Enable` 作为开关。
- 只读读取当前 `/FaceReco/1/BaseConfig`，`EnableRecognition=true`，说明 Web 后台意义上的人脸识别总开关已经打开。
- 只读读取当前 `/AI/FaceSnapshotCfg`，`Enable=true`、`Trigger.Push.Enable=true`、`Trigger.Snapshot.Enable=true`、`IsCaptureBackground=true`、`ShowFaceFrame=true`。
- 只读读取当前 `/FaceReco/1/RecoRuleList`，仍为 `RecoRule.Enable=false`，但 `RecognitionRule=Comparison pass`、`ControlPersonnelType=OrganizationMember`、`Trigger.Push.Enable=true`、`Trigger.Snapshot.Enable=true`。
- 只读读取当前 `/Pictures/1/FaceDetect`，顶层 `FaceDetect.Enable=false`。该配置属于普通事件的人脸侦测页面，不等同于 Web 后台人脸识别页签的总开关，但如果画面完全没有人脸框或普通人脸侦测事件，也可能影响肉眼观察判断。
- 只读读取当前 `/System/DeviceCap`，`FunctionListAboutChannel/Channel/FaceReco=true`，Web 前端也正是用该字段显示人脸识别菜单；同一能力文档里 `SmartEvent/FaceReco=false`，但 Web 菜单逻辑没有用它控制人脸识别页签。
- `/System/FaceRecognitionIntervalCfg` 和旧 `/FaceRecognition/Ability` 在当前设备返回 `16001`，不适合作为本机配置依据。

本轮结论：

- 找到了替代启用路径：Web 后台实际使用 `/FaceReco/1/BaseConfig/EnableRecognition` 作为人脸识别总开关，而不是第一层 `RecoRule/Enable`。
- `RecoRule.Enable=false` 当前不能再单独视为阻塞条件，因为 Web 后台自身不把它作为可操作开关，而且前一轮两种 PUT 模式都无法让它持久化。
- 当前设备在人脸识别主链路上已经具备三项关键条件：`EnableRecognition=true`、`AIFaceSnapshotCfg.Enable=true`、`RecoRule.Trigger.Push.Enable=true`。
- 下一轮不应继续尝试修改第一层 `RecoRule/Enable`；应进入端到端事件验证，观察真实 `FaceReco` 或 `FaceSnapshot` 推送是否到达远程服务器。
- 如果下一轮仍没有识别事件，再按新 LLD 单独设计“人脸侦测/抓拍观察增强”配置，重点评估是否需要启用 `/Pictures/1/FaceDetect`，而不是把它混入本轮。

### 23.14 Round 14：步骤 10 真机端到端事件验证

本轮目标：

- 推进步骤 10“真机端到端验证”，用远程服务器上的真实落盘文件证明摄像头是否已经推送识别事件。
- 验证范围优先覆盖事件入口与分流证据：`raw` 是否新增、`records` 是否新增、是否出现 `known`、`stranger`、`ignored`、`parse_error` 等处理结果。
- 如果出现陌生人事件，继续验证 `strangers/YYYY-MM-DD` 是否保存图片、`links/YYYY-MM-DD` 是否生成 token 链接记录、飞书消息是否至少具备保存路径和查看链接。
- 如果出现匹配成功事件，验证 `records` 中是否记录 `result=known`、人员姓名/ID 是否解析成功、飞书发送状态是否为成功或可诊断失败。

本轮范围：

- 只读检查远程服务器 `/var/lib/camera-face-guard/p6s_events` 目录下 `raw`、`records`、`strangers`、`links` 的日期目录和文件数量。
- 只读抽样查看最新 raw/record 文件，记录 `operator`、`result`、`event_id`、`camera_serial_number`、图片状态、链接状态和飞书状态。
- 允许运行摄像头 HTTP 配置只读审计脚本，确认事件入口配置仍指向远程服务器。
- 允许运行远程本机 fixture 验证，确认部署版本仍能处理 known/stranger/heartbeat 样本。

本轮不做：

- 不修改摄像头配置。
- 不重复 PUT `/FaceReco/1/RecoRuleList`。
- 不修改飞书 webhook、远程 env 或 systemd/nginx 配置。
- 不清理远程事件目录。
- 不把真实事件 token、飞书秘钥、摄像头密码或 raw 中可能出现的人脸图片内容写入文档。

影响面：

- 文档影响：记录步骤 10 当前验证证据和是否可以进入下一步。
- 代码影响：本轮默认不需要代码改动；如果发现缺少可重复的只读观测能力，可先补充只读脚本并单独说明。
- 设备影响：本轮预期无设备配置变更。
- 远程服务影响：只读查询，不重启服务。

风险点：

- 如果当前没有人在摄像头前触发识别，远程目录不会新增 `FaceReco` 事件，这不代表链路一定失败。
- 真实事件字段可能与 fixture 不一致，需要以 raw 文件为准修订解析逻辑；如遇到字段差异，先记录并更新 LLD，再改代码。
- 飞书发送结果受机器人配置和网络影响；即使事件处理成功，飞书也可能失败，需要区分事件链路失败和通知链路失败。
- raw 文件可能包含图片 base64，文档和输出只能记录摘要，不展示图片内容。

回滚方式：

- 本轮只读验证无设备回滚。
- 如果补充了只读脚本且后续不需要，可删除脚本并回滚对应提交。
- 如果验证结论不成立，下一轮先修订本节结论再继续。

验证方式：

- 使用 `ssh qypower-prod` 读取远程事件目录摘要，统计最近日期目录的 raw/records/strangers/links 文件数。
- 抽样最新 raw/record 文件，只输出脱敏摘要：`operator`、`result`、`event_id`、`image.status`、`link.expires_at`、`feishu.status`。
- 运行 `python3 scripts/configure_p6s_http_events.py` 做本地只读审计，确认摄像头 HTTP 推送配置仍启用且指向远程服务器。
- 若没有真实事件新增，停止并记录“需要人工触发摄像头前人员/陌生人验证”的困难，不盲目改摄像头配置。

本轮验证记录：

- 远程服务状态：`camera-face-guard` 为 `active` 且 `enabled`。
- 本地只读审计 `/System/HTTPEventServerConfigV2`：`Enable=true`、`Protocol=http`、`Host=82.156.198.180`、`Port=80`、`AuthMode=none`、`CacheEventEnable=true`，`URLPath` 与远程事件入口匹配。
- 本地只读审计 `/AI/FaceSnapshotCfg`：`Enable=true`、`Trigger.Push.Enable=true`、`Trigger.Snapshot.Enable=true`、`IsCaptureBackground=true`、`ShowFaceFrame=true`。
- 本地只读审计 `/FaceReco/1/RecoRuleList`：`rule_count=1`、`RecognitionRule=Comparison pass`、`ControlPersonnelType=OrganizationMember`、`Trigger.Push.Enable=true`、`Trigger.Snapshot.Enable=true`，`RecoRule.Enable=false` 按 Round 13 结论不再作为单独阻塞条件。
- 远程事件目录 `/var/lib/camera-face-guard/p6s_events` 中已有 `raw/2026-07-02` 和 `records/2026-07-02` 文件，证明摄像头能访问公网入口并且服务端能落盘处理。
- 远程 raw operator 分布：当前抽样统计 `total_raw=60`，`operator_counts={"heartbeat": 60}`；没有出现 `FaceReco`、`FaceSnapshot` 或其他人脸事件。
- 最新处理记录抽样均为 `operator=heartbeat`、`result=heartbeat`，最近事件时间样本为 `2026-07-02T20:47:48+08:00`。
- 远程 `strangers` 和 `links` 未出现可用于本轮陌生人链路验证的新增证据。
- 摄像头端 `/FaceRecognition/QueryRecordCount` 和 `/FaceRecognition/QueryRecordList` 按文档使用 PUT filter 查询，但当前设备均返回 `ResponseStatus.statusCode=16001`，因此不能作为本机识别记录证据来源。
- 本地运行 `python3 scripts/validate_p6s_event_flow.py` 成功，fixture 覆盖 known、duplicate、stranger、missing image、heartbeat。
- 远程运行 `cd /opt/camera-face-guard && .venv/bin/python scripts/validate_p6s_event_flow.py` 成功，证明已部署版本对 known/stranger/heartbeat 样本的处理逻辑仍可用。

本轮结论：

- HTTP 推送入口已打通：摄像头正在周期性向远程服务器发送 heartbeat，服务器能够接收、Ack、落盘 raw 和 records。
- 服务端业务处理不是当前阻塞点：本地和远程 fixture 均能正确处理 known、stranger 和 heartbeat。
- 步骤 10 尚未完成：当前没有真实 `FaceReco`/`FaceSnapshot` 事件，因此无法验证匹配成功飞书通知、陌生人图片保存、token 图片链接和真实重复事件幂等。
- 当前困难是“摄像头没有向服务器发送真实人脸事件”，而不是“服务器收不到摄像头请求”。
- 下一轮需要先设计人脸事件触发诊断，不应盲目重试已有 HTTP 推送配置；优先评估是否需要启用或调整与人脸检测/抓拍观察相关的配置，例如 `/Pictures/1/FaceDetect` 或 Web 后台对应的人脸侦测开关。

### 23.15 Round 15：人脸事件触发链路只读诊断

本轮目标：

- 针对 Round 14 的阻塞点，定位为什么摄像头只向远程服务器发送 heartbeat，而没有发送真实 `FaceReco` 或 `FaceSnapshot` 事件。
- 用只读证据区分三类可能性：事件能力未启用、检测/识别开关未启用、识别发生但没有进入 HTTP 推送。
- 为下一轮是否需要受控启用 `/Pictures/1/FaceDetect`、调整 `/AI/FaceSnapshotCfg` 或补充其他识别事件开关提供明确依据。

本轮范围：

- 只读查阅离线 ShowDoc 和摄像头 Web 前端脚本，定位人脸侦测、人脸抓拍、人脸识别、事件联动推送各自对应的接口和字段。
- 只读读取当前摄像头配置摘要，覆盖 `/FaceReco/1/BaseConfig`、`/AI/FaceSnapshotCfg`、`/FaceReco/1/RecoRuleList`、`/Pictures/1/FaceDetect`、`/System/HTTPEventServerConfigV2`、`/System/DeviceCap` 等已知相关接口。
- 只读复核远程事件目录最新 raw/records 的 operator 分布，确认是否仍只有 heartbeat。
- 允许新增一个只读诊断脚本，但脚本必须默认不写设备、不输出密钥、不输出图片 base64，仅输出脱敏摘要。

本轮不做：

- 不修改摄像头配置。
- 不启用 `/Pictures/1/FaceDetect`。
- 不修改人脸库、识别规则、抓拍规则、HTTP 推送 URL 或远程服务配置。
- 不删除远程事件目录和本地备份文件。
- 不把摄像头密码、事件 token、飞书秘钥、图片 base64 或完整 raw payload 写入文档。

影响面：

- 文档影响：追加本轮诊断计划、证据和结论。
- 代码影响：如果现有脚本不足以稳定输出摘要，可新增或增强只读诊断脚本；运行时服务逻辑不变。
- 设备影响：本轮只读，预期无设备配置变化。
- 远程服务影响：只读查询远程落盘文件，预期不重启服务。

风险点：

- 摄像头 Web 后台脚本可能经过压缩或动态拼接，单靠关键词不一定能完整还原 UI 行为。
- `/Pictures/1/FaceDetect` 可能是普通人脸侦测事件，与人脸识别不是同一条链路；不能因为它为 false 就直接断定必须开启。
- 设备部分接口可能返回 `16001` 或空 XML，需要把“接口不支持”和“配置关闭”分开记录。
- 如果读取 raw 文件时误输出图片字段，可能泄露隐私；所有 raw 检查只能做字段级摘要。

回滚方式：

- 本轮只读诊断无设备回滚。
- 新增的只读脚本如判断不需要，可通过后续提交删除或 `git revert` 本轮提交回滚。
- 文档结论如后续被真机验证推翻，下一轮先修订本节再继续。

验证方式：

- 使用 `rg` 在 `docs/p6scgi-showdoc` 中检索 `FaceDetect`、`FaceSnapshot`、`FaceReco`、`HTTPEventServer`、`Trigger.Push` 等关键词，并记录命中的接口路径和关键字段。
- 读取摄像头 Web 后台脚本中人脸识别、人脸抓拍、人脸侦测页面对应的接口调用，确认 UI 实际依赖哪些开关。
- 运行只读配置审计命令，输出当前相关接口的脱敏摘要。
- 使用 `ssh qypower-prod` 统计远程 raw operator 分布，确认是否仍没有真实人脸事件。
- 如果所有证据仍指向“缺少触发开关但不确定写哪一个”，停止并在结论中说明困难；下一轮再单独设计受控配置变更。

本轮执行步骤：

1. 文档与前端接口检索：
   - 检索离线 ShowDoc 中普通人脸侦测、人脸抓拍、人脸识别和 HTTP 事件推送接口。
   - 检索摄像头 Web 前端脚本中 `FaceDetect`、`FaceSnapshot`、`Facerecognition` 相关调用。
2. 当前配置只读审计：
   - 读取 `/FaceReco/1/BaseConfig`，确认 `EnableRecognition`。
   - 读取 `/AI/FaceSnapshotCfg`，确认抓拍启用、抓拍联动和推送联动。
   - 读取 `/FaceReco/1/RecoRuleList`，确认识别规则、布控人员类型、推送联动和抓拍联动。
   - 读取 `/Pictures/1/FaceDetect`，确认普通人脸侦测是否开启及联动方式。
   - 读取 `/System/HTTPEventServerConfigV2`，确认 HTTP 入口仍启用。
   - 读取 `/System/DeviceCap`，确认本机声明的人脸识别/人脸侦测能力。
3. 远程事件只读复核：
   - 统计最近日期 raw operator 分布。
   - 抽样最新 records 的 `operator`、`result`、`event_id`、`feishu.status`。
4. 结论归档：
   - 如果能明确某个开关关闭且文档/Web UI 都证明它是事件推送必要条件，只记录下一轮受控写入计划，不在本轮写入。
   - 如果证据显示配置已开启但仍无事件，记录需要人工在画面前触发和抓包/日志的困难。
   - 如果发现服务端解析遗漏了真实事件字段，先更新 LLD，再进入代码修复。

本轮停止条件：

- 需要修改任何摄像头配置。
- 需要读取或展示完整图片/base64。
- 远程 raw 中出现未见过的真实人脸事件但字段与 fixture 不一致；此时先记录 raw 字段摘要并停止，避免误解析。
- 发现已有 LLD 与实际代码或配置严重不一致，需要先修订 LLD。

本轮提交策略：

- 如果只产生文档诊断结论，提交类型使用 `docs:`。
- 如果新增只读诊断脚本，提交类型使用 `chore:`，并在提交信息中强调默认只读和脱敏输出。
- 暂存前必须确认不包含 `.env.local`、远程事件 raw 文件、图片文件和 STYD 会员数据。

本轮实际执行结果：

- 离线 ShowDoc 复核：
  - `/FaceReco/ChannelID/BaseConfig` 的 `EnableRecognition` 字段是“配置-智能分析-人脸识别-人脸识别-启用人脸识别”。
  - `/AI/FaceSnapshotCfg` 的 `Enable` 字段是“配置-智能分析-人脸识别-人脸抓拍-启用人脸抓拍”，其 `Trigger.Push.Enable` 是“推送告警”，`Trigger.Snapshot.Enable` 是“SD卡抓图”。
  - `/FaceReco/ChannelID/RecoRuleList` 的 `Trigger.Push.Enable` 是人脸识别规则联动推送，`Trigger.Snapshot.Enable` 是人脸识别规则联动 SD 卡抓图。
  - `/Pictures/ChannelID/FaceDetect` 属于“配置-普通事件-人脸侦测”，字段受 `DeviceCap-FaceDetect-Support` 能力限制；它有独立 `Enable`、`Trigger.Push.Enable`、`Trigger.Snapshot.Enable` 和布防计划。
  - HTTP 事件文档中 `FaceReco`、`FaceSnapshot` 只描述 POST 事件格式、断电重传和响应间隔重传，没有说明额外必须打开哪个配置开关。
- Web 前端脚本复核：
  - `FaceCapture.js` 中 `getFaceRecoBaseConfig()` 读取 `/FaceReco/1/BaseConfig`，并把 `EnableRecognition` 绑定到人脸识别页“启用人脸识别”开关。
  - `FaceCapture.js` 中 `setFaceRecoBaseConfig()` PUT `/FaceReco/1/BaseConfig`，只改 `FaceBaseConfig/EnableRecognition`。
  - `FaceCapture.js` 中 `getAlarmLink()` 读取 `/FaceReco/1/RecoRuleList`，绑定布控人员、布控时间和联动方式。
  - `FaceCapture.js` 中 `saveAlarmContronl()` PUT `/FaceReco/1/RecoRuleList`，修改的是 `ControlPersonnelType`、`Schedule` 和 `Trigger` 下的联动字段。
  - `FaceCapture.js` 中 `getfacetime()` 与 `setfacetronic()` 使用 `/AI/FaceSnapshotCfg` 管理人脸抓拍页配置。
  - 在已采集的人脸识别/人脸抓拍 Web 前端脚本中未发现 `/Pictures/1/FaceDetect` 调用，说明它不是该页面的主配置接口。
- 当前摄像头只读配置复核：
  - `/FaceReco/1/BaseConfig`：`EnableRecognition=true`、`OpenDoorMode=0`、`OverlayHumanBox=0`、`Senstive=0`、`SyncPictureOpt=0`。
  - `/AI/FaceSnapshotCfg`：`Enable=true`、`Trigger.Push.Enable=true`、`Trigger.Snapshot.Enable=true`、`IsCaptureBackground=true`、`ShowFaceFrame=true`、`Schedule.AllDay=true`。
  - `/FaceReco/1/RecoRuleList`：`rule_count=1`、`RecoRule.Enable=false`、`RecognitionRule=Comparison pass`、`CompareLimit=0`、`ControlPersonnelType=OrganizationMember`、`Trigger.Push.Enable=true`、`Trigger.Snapshot.Enable=true`。
  - `/Pictures/1/FaceDetect`：`Enable=false`、`EnableOverlay=false`、`Senstive=0`、`Trigger.Push.Enable=true`、`Trigger.Snapshot.Enable=true`、`Trigger.Record.Enable=true`、`Trigger.BeepAlert.Enable=true`、`Trigger.LightAlarm.Enable=true`、`Schedule.AllDay=true`。
  - `/System/HTTPEventServerConfigV2`：`Enable=true`、`Protocol=http`、`Host=82.156.198.180`、`Port=80`、`AuthMode=none`、`CacheEventEnable=true`，`URLPath` 与远程事件入口匹配。
  - `/System/DeviceCap`：`FunctionListAboutChannel/Channel/FaceReco=true`、`FaceSnap=true`，且 `DeviceCap-FaceDetect-Support=true`。
- 远程事件只读复核：
  - `/var/lib/camera-face-guard/p6s_events/raw/2026-07-02` 当前 `total_raw=102`。
  - raw 文件是信封结构，顶层字段为 `dedupe_key`、`payload`、`received_at`、`request`、`version`；事件 operator 位于 `payload.operator`。
  - `raw_payload_operator_counts={"heartbeat": 102}`。
  - `/var/lib/camera-face-guard/p6s_events/records/2026-07-02` 当前 `total_records=102`。
  - `record_operator_counts={"heartbeat": 102}`，`record_result_counts={"heartbeat": 102}`。
  - 最新抽样 records 仍均为 `operator=heartbeat`、`result=heartbeat`，未出现 `FaceReco` 或 `FaceSnapshot`。

本轮结论：

- HTTP 推送链路仍然是通的，摄像头持续向远程服务器发送 heartbeat，服务端持续落盘处理。
- 人脸识别页面对应的主链路配置从文档、Web 前端和真机读数看均已启用：`EnableRecognition=true`、`AIFaceSnapshotCfg.Enable=true`、`AIFaceSnapshotCfg.Trigger.Push=true`、`RecoRule.Trigger.Push=true`。
- `RecoRule.Enable=false` 仍存在，但前两轮已经证明它无法通过 `/FaceReco/1/RecoRuleList` 持久化，且 Web 前端不把它作为启用人脸识别的 UI 开关；本轮不再把它作为唯一阻塞条件。
- 当前唯一明显关闭的相关开关是 `/Pictures/1/FaceDetect.Enable=false`，但文档和 Web 前端均显示它属于“普通事件-人脸侦测”，不是人脸识别页或人脸抓拍页的主配置接口。
- 因此，本轮证据不足以安全断言“必须直接启用 `/Pictures/1/FaceDetect`”；继续写设备配置会变成盲改，触发本轮停止条件。
- 当前困难复述：服务端和 HTTP 入口已经被证明可用，但摄像头没有产生真实 `FaceReco` 或 `FaceSnapshot` 事件；只读证据无法确认原因是普通人脸侦测关闭、算法没有检测到人脸、识别规则未实际生效，还是需要 Web 后台某个隐藏流程触发。
- 下一轮如果继续，应单独写 LLD 计划，二选一推进：
  - 方案 A：受控启用 `/Pictures/1/FaceDetect.Enable=true` 并保持现有 `Trigger.Push/Snapshot=true`，写入前备份完整 XML，写入后观察是否出现 `FaceDetect`、`FaceSnapshot` 或 `FaceReco` 事件。
  - 方案 B：通过 Web 后台人工操作或浏览器抓包确认普通人脸侦测开关与人脸识别/抓拍页面之间是否有关联，再决定是否写入。

### 23.16 Round 16：受控启用普通人脸侦测并观察真实事件

本轮目标：

- 基于 Round 15 的结论，执行一次受控实验：启用 `/Pictures/1/FaceDetect.Enable=true`，观察摄像头是否开始向远程服务器推送真实人脸相关事件。
- 判断普通事件“人脸侦测”是否是当前固件触发 `FaceSnapshot`、`FaceReco` 或其他人脸事件的前置条件。
- 如果启用后仍只有 heartbeat，停止并记录困难，不继续连环改动其他识别/抓拍配置。

本轮技术方案：

- 新增 `P6SCameraClient.get_face_detect(channel_id=1)` 与 `set_face_detect(xml_text, channel_id=1)`，只封装 `/Pictures/{ChannelID}/FaceDetect` 的 GET/PUT。
- 新增脚本 `scripts/configure_p6s_face_detect.py`：
  - 默认只读审计当前 `FaceDetect` 摘要。
  - `--print-diff-summary` 输出拟修改字段，确认只会把顶层 `FaceDetect/Enable` 从 `false` 改为 `true`。
  - `--apply` 才执行真实 PUT。
  - 写入前保存完整 XML 备份到系统临时目录，不进入 git。
  - 写入后立即 GET 回读，确认 `Enable=true` 且 `Trigger.Push/Snapshot/Record/BeepAlert/LightAlarm` 等已有联动字段没有被改坏。
  - 支持 `--restore <backup.xml>` 回滚完整 XML。
- 远程观察使用只读 SSH 统计 `/var/lib/camera-face-guard/p6s_events/raw` 与 `records` 中最新日期的 operator/result 分布。
- 观察窗口首轮设置为 90 秒，避免长时间等待；如果 90 秒后仍只有 heartbeat，本轮停止，不继续扩大配置改动。

本轮范围：

- 允许修改本地代码：
  - `app/services/p6s_camera.py`
  - `scripts/configure_p6s_face_detect.py`
  - `docs/camera-alarm-feishu-push-lld.md`
- 允许对摄像头执行最多一次 PUT `/Pictures/1/FaceDetect`，且只能在 diff-summary 证明仅修改顶层 `Enable=false -> true` 后执行。
- 允许读取远程事件目录摘要，但不读取或展示图片 base64。

本轮不做：

- 不修改 `/AI/FaceSnapshotCfg`。
- 不修改 `/FaceReco/1/BaseConfig`。
- 不修改 `/FaceReco/1/RecoRuleList`。
- 不修改 HTTP 事件服务器配置、飞书配置、远程 systemd/nginx 配置。
- 不清理远程事件目录。
- 不把摄像头密码、事件 token、飞书秘钥、raw payload、图片 base64 写入文档或 git。

影响面：

- 设备影响：普通事件“人脸侦测”会被启用；当前设备已有 `Trigger.Push/Snapshot/Record/BeepAlert/LightAlarm=true`，启用后可能产生普通人脸侦测告警、SD 卡抓图、录像或灯光/蜂鸣联动。
- 远程影响：如果设备开始推送事件，远程 raw/records 会新增非 heartbeat 记录；服务端对非 `FaceReco` 事件会按现有逻辑记录为 ignored 或后续可诊断结果。
- 代码影响：新增一个运维诊断脚本和两个摄像头客户端方法，不改变 FastAPI 运行时事件处理逻辑。
- 文档影响：记录本轮实验计划、执行结果和是否需要继续进入真实端到端验证。

风险点：

- `/Pictures/1/FaceDetect` 是普通事件链路，启用后可能只产生 `FaceDetect` 或其他普通事件，未必会产生 `FaceReco`。
- 如果设备 PUT 返回成功但回读不持久化，不能继续重试；要记录与前几轮 `RecoRule.Enable` 类似的固件行为。
- 如果启用后远程出现新 operator，而服务端当前把它归类为 ignored，本轮只记录摘要；是否支持该 operator 需要下一轮 LLD 单独设计。
- 如果启用后产生大量事件，不能直接清理目录；应先记录数量和 operator 分布，再决定是否回滚。

回滚方式：

- 使用脚本写入前生成的完整 XML 备份执行 `--restore <backup.xml>`。
- 或再次运行脚本支持的受控写入把 `FaceDetect/Enable` 改回 `false`，但优先使用完整 XML 备份。
- 本地代码使用 `git revert` 本轮提交回滚。

验证方式：

- `python3 -m py_compile app/services/p6s_camera.py scripts/configure_p6s_face_detect.py`。
- `python3 scripts/configure_p6s_face_detect.py --print-diff-summary`，确认 `non_target_mismatches=[]` 且 `changed_fields=["Enable"]`。
- `python3 scripts/configure_p6s_face_detect.py --apply`，确认设备 HTTP 成功、设备 `statusCode` 为 `0` 或响应为空且 GET 回读 `Enable=true`。
- 等待 90 秒后通过 `ssh qypower-prod` 统计远程 raw/records operator 分布。
- 如果出现 `FaceReco` 或 `FaceSnapshot`，进入下一轮步骤 10 真机端到端验证；如果只出现普通事件或仍只有 heartbeat，记录结论并停止。

本轮停止条件：

- diff-summary 显示会修改顶层 `Enable` 以外字段。
- 读取或解析 `/Pictures/1/FaceDetect` 失败。
- PUT 返回 HTTP 非 2xx 或设备 `ResponseStatus.statusCode` 非 0。
- 写入后回读 `Enable` 仍不是 `true`。
- 写入后回读发现原本已启用的 Push/Snapshot/Record/BeepAlert/LightAlarm 被改坏。
- 远程出现未知真实事件但字段与服务端 fixture 不一致；先记录摘要，不直接改解析逻辑。

本轮提交策略：

- 先提交 LLD + 脚本 + 客户端方法，提交信息说明这是受控 FaceDetect 实验工具。
- 如果执行真机写入和观察后只更新文档结论，再单独提交 `docs:`；如果脚本和实验结果在同一轮完成且 diff 简洁，也可以一次提交，但提交信息必须写清楚设备配置实际变化。
- 暂存前确认不包含 `.env.local`、临时备份 XML、远程 raw 文件、图片文件或 STYD 会员数据。

本轮工具提交记录：

- 已新增 `P6SCameraClient.get_face_detect(channel_id=1)` 与 `set_face_detect(xml_text, channel_id=1)`。
- 已新增 `scripts/configure_p6s_face_detect.py`：
  - 默认只读。
  - 支持 `--print-diff-summary`。
  - 支持 `--apply` 写入。
  - 支持 `--restore <backup.xml>` 使用完整 XML 备份回滚。
  - 输出只包含配置摘要、差异摘要和设备响应摘要，不输出密码、事件 token、图片 base64 或 raw payload。
- 本地语法验证通过：`python3 -m py_compile app/services/p6s_camera.py scripts/configure_p6s_face_detect.py`。
- 工具与计划已提交：`9160d7c chore: 增加P6S FaceDetect受控配置脚本`。

本轮真机执行结果：

- 写入前远程事件基线：
  - `total_raw=128`，`raw_ops={"heartbeat": 128}`。
  - `total_records=128`，`record_ops={"heartbeat": 128}`，`record_results={"heartbeat": 128}`。
- 只读 dry-run 结果：
  - `FACE_DETECT_BEFORE.enable=false`。
  - `Trigger.Push.Enable=true`、`Trigger.Snapshot.Enable=true`、`Trigger.Record.Enable=true`、`Trigger.BeepAlert.Enable=true`、`Trigger.LightAlarm.Enable=true`。
  - `PATCH_DIFF_SUMMARY.changed_fields=["Enable"]`。
  - `PATCH_DIFF_SUMMARY.changed_count=1`。
  - `PATCH_DIFF_SUMMARY.non_target_mismatches=[]`。
- 按计划执行过一次 `python3 scripts/configure_p6s_face_detect.py --apply`。
- 写入前已保存完整 XML 备份，路径位于系统临时目录：`camera-face-guard-p6s-backups/face_detect_1_20260702212204.xml`。
- 设备写入响应：
  - HTTP 状态：`200`。
  - 设备 `ResponseStatus.statusCode=0`。
  - 设备 message 为空。
- 写入后立即 GET 回读：
  - `FACE_DETECT_AFTER.enable=false`。
  - 原有 `Trigger.Push/Snapshot/Record/BeepAlert/LightAlarm` 仍为 `true`，未被改坏。
- 触发本轮停止条件：`写入后回读 Enable 仍不是 true`。
- 因为配置没有持久化，本轮没有进入 90 秒真实事件观察窗口，也没有继续尝试其他写入。
- 写入后远程事件复核：
  - `total_raw=128`，`raw_ops={"heartbeat": 128}`。
  - `total_records=128`，`record_ops={"heartbeat": 128}`，`record_results={"heartbeat": 128}`。

本轮结论：

- `/Pictures/1/FaceDetect` 与此前 `/FaceReco/1/RecoRuleList` 的第一层 `Enable` 表现一致：设备接受 PUT，并返回成功状态，但目标 `Enable` 字段没有持久化。
- 这说明当前问题很可能不是单个 XML 序列化或 HTTP 认证问题，而是该固件对这些事件启用字段存在只读、派生、能力模式限制，或需要通过 Web 后台更高层流程切换算法/事件模式。
- 当前仍无法触发真实 `FaceReco`、`FaceSnapshot` 或普通人脸侦测事件；远程服务仍只收到 heartbeat。
- 本轮已按停止条件中断，没有盲目重试，也没有继续修改 `/AI/FaceSnapshotCfg`、`/FaceReco/1/BaseConfig`、`/FaceReco/1/RecoRuleList` 或 HTTP 推送配置。
- 下一轮不应继续对单个 `Enable` 字段做 PUT 重试。建议先进入“设备算法/工作模式与 Web 后台真实保存流程”诊断：
  - 只读核对 `/System/AIWorkMode`、算法仓库相关接口、AICap/DeviceCap 中与 `FaceCapture`、`FaceRecognition` 相关能力。
  - 或通过浏览器 DevTools/Web 后台真实点击保存，抓取成功持久化这些开关时是否调用了其他前置接口。
  - 如果需要继续真机写配置，必须先在新 LLD 中明确要切换的算法/工作模式字段和回滚方式。

### 23.17 Round 17：算法仓库与 AI 工作模式只读诊断

本轮目标：

- 解释 Round 14 到 Round 16 中多次出现的“PUT 返回成功，但 `Enable` 字段不持久化”现象。
- 判断摄像头是否处在 `FaceCapture`、`FaceRecognition` 或其他算法仓库模式中。
- 明确下一轮如果要写设备配置，应该写上层算法模式，还是继续停留在人脸抓拍/识别子配置排查。

本轮技术方案：

- 先从离线 ShowDoc 和摄像头 Web 前端脚本确认算法仓库配置接口。
- 只读读取真机当前算法相关配置，覆盖：
  - `/System/AlgorithmStoreCfg`：算法仓库当前类型，重点看 `AlgorithmType`。
  - `/System/AICap`：算法仓库能力，重点看 `AlgorithmWarehouse.support`、`FaceSnap.support`、`FaceReco.support`。
  - `/System/DeviceCap`：通道人脸识别、人脸抓拍、人脸侦测能力。
  - `/System/AIWorkMode`：如设备支持，确认是否还有额外 AI 工作模式。
  - `/FaceReco/1/BaseConfig`、`/AI/FaceSnapshotCfg`、`/FaceReco/1/RecoRuleList`、`/Pictures/1/FaceDetect`：只复核摘要，用于和算法模式做交叉判断。
- 只读统计远程服务器事件目录，确认在诊断期间是否仍只有 heartbeat。
- 本轮不新增运行时代码；如果必须解析 XML，只使用临时只读命令输出字段摘要，不保存 raw XML 到仓库。

本轮范围：

- 允许修改：
  - `docs/camera-alarm-feishu-push-lld.md`
- 允许只读访问摄像头 GET 接口。
- 允许只读访问远程服务器事件目录摘要。

本轮不做：

- 不执行 PUT `/System/AlgorithmStoreCfg`。
- 不执行 PUT `/System/AIWorkMode`。
- 不修改 `/FaceReco/1/BaseConfig`、`/AI/FaceSnapshotCfg`、`/FaceReco/1/RecoRuleList`、`/Pictures/1/FaceDetect`。
- 不重启远程服务，不修改 nginx/systemd/env。
- 不读取或展示完整 raw payload、图片 base64、摄像头密码、事件 token、飞书秘钥。

影响面：

- 设备影响：只读，无配置变化。
- 远程影响：只读统计文件，无服务变化。
- 文档影响：记录算法仓库证据、当前配置摘要、下一轮是否需要受控切换算法模式。

风险点：

- Web 前端脚本可能存在 bug 或错误处理分支，不能仅凭脚本判断真机状态，必须以真机 GET 为准。
- `/System/AlgorithmStoreCfg` 的 XML 示例在文档中闭合标签存在笔误，执行写入前必须重新设计 XML 构造和回读验证。
- 如果 `/System/AIWorkMode` 返回空或不支持，不能把它当成关闭状态；只能记录为“本机未暴露有效字段”。
- `FaceCapture` 与 `FaceRecognition` 可能是互斥算法模式，切换可能影响当前抓拍或识别行为；本轮不能直接写。

回滚方式：

- 本轮只读无设备回滚。
- 文档结论如后续被真机验证推翻，下一轮先修订本节。

验证方式：

- 使用离线文档确认：
  - `GET /System/AlgorithmStoreCfg` 返回 `AlgorithmType`。
  - `PUT /System/AlgorithmStoreCfg` 可设置 `Unknown`、`IntelligentAlert`、`FaceCapture`、`FaceRecognition`，但本轮不调用。
- 使用 Web 前端脚本确认后台“算法仓库”页面保存时调用 `/System/AlgorithmStoreCfg`。
- 使用只读 GET 读取真机当前 `AlgorithmType` 和 AI 能力摘要。
- 使用 `ssh qypower-prod` 只读统计远程 raw/records operator 分布。

本轮停止条件：

- 任何需要写摄像头配置的动作。
- 读取到的算法状态与文档明显不一致，需要先人工复核。
- 远程出现新的真实人脸事件但字段结构未知；先记录字段摘要，不能直接改解析逻辑。
- 发现摄像头返回敏感字段或 raw 图片内容；停止输出并只保留脱敏结论。

本轮提交策略：

- 如果只更新文档，提交类型使用 `docs:`。
- 暂存前确认不包含 `.env.local`、图片文件、STYD 会员数据、临时备份 XML 和摄像头 raw payload。

本轮文档与 Web 前端复核结果：

- 离线 ShowDoc 中“算法商场定制”明确暴露 `GET /System/AlgorithmStoreCfg` 和 `PUT /System/AlgorithmStoreCfg`。
- `AlgorithmStoreCfg/AlgorithmType` 的可选值为 `Unknown`、`IntelligentAlert`、`FaceCapture`、`FaceRecognition`。
- 摄像头 Web 前端 `ipc_js_events_AlgorithmWarehouse.js` 的算法仓库页面保存逻辑也调用 `/System/AlgorithmStoreCfg`：
  - 选择人脸抓拍时写 `FaceCapture`。
  - 选择人脸识别时写 `FaceRecognition`。
- Web 前端脚本中的 GET 成功分支为空、error 分支读取 `xmlDoc` 的写法明显可疑，因此不能只依赖脚本判断 UI 行为；真机 GET 结果优先级更高。

本轮真机只读诊断结果：

- `GET /System/AlgorithmStoreCfg`：
  - `AlgorithmType=Unknown`。
  - 该值既不是 `FaceCapture`，也不是 `FaceRecognition`。
- `GET /System/AICap`：
  - XML 根节点为 `Channel`，不是 ShowDoc/Web 前端假设的 `AICap` 包裹结构。
  - `AlgorithmWarehouse.support=false`。
  - `AlgorithmWarehouse.FaceSnap.support=false`。
  - `AlgorithmWarehouse.FaceReco.support=true`。
  - `ForFaceReco.support=true`，且支持 `AudioVolume`、`AudioType`。
- `GET /System/DeviceCap`：
  - `FunctionList/FaceFunction/FaceSnapshot=true`。
  - `FunctionList/FaceFunction/FaceReco=true`。
  - `FunctionList/Push/FaceCapture/Support=true`。
  - `FunctionList/ConfigReboot/FaceSnapshot=true`、`FaceReco=true`。
  - `FunctionList/AIWorkMode/PeopleMode=true`、`FaceMode=false`。
  - `FunctionListAboutChannel/ChannelList/Channel/FaceSnap=true`。
  - `FunctionListAboutChannel/ChannelList/Channel/FaceReco=true`。
  - `FunctionListAboutChannel/ChannelList/Channel/SmartEvent/FaceSnap=false`、`SmartEvent/FaceReco=false`，该字段与前几项能力字段不一致，不能单独作为禁用依据。
- `GET /System/AIWorkMode`：
  - 返回空 `<AIWorkMode Version="1.0" />`。
  - 本机未通过该接口暴露可直接读取的 `PeopleMode`、`FaceMode` 当前值。
- 复核人脸子配置：
  - `/FaceReco/1/BaseConfig`：`EnableRecognition=true`、`OverlayHumanBox=0`、`Senstive=0`。
  - `/AI/FaceSnapshotCfg`：`Enable=true`、`Trigger.Push.Enable=true`、`Trigger.Snapshot.Enable=true`、`ShowFaceFrame=true`、`Schedule.AllDay=true`。
  - `/FaceReco/1/RecoRuleList`：`rule_count=1`、第一层 `Enable=false`、`RecognitionRule=Comparison pass`、`FaceGroupList.ControlPersonnelType=OrganizationMember`、`Trigger.Push.Enable=true`、`Trigger.Snapshot.Enable=true`。
  - `/Pictures/1/FaceDetect`：`Enable=false`、`Trigger.Push.Enable=true`、`Trigger.Snapshot.Enable=true`、`Schedule.AllDay=true`。

本轮远程只读复核结果：

- `/var/lib/camera-face-guard/p6s_events/raw/2026-07-02`：
  - `total=139`。
  - `operators={"heartbeat": 139}`。
- `/var/lib/camera-face-guard/p6s_events/records/2026-07-02`：
  - `total=139`。
  - `operators={"heartbeat": 139}`。
  - `results={"heartbeat": 139}`。

本轮结论：

- 服务端 HTTP 推送链路仍然正常，摄像头持续推送 heartbeat，远程服务也持续落盘。
- 设备明确具备人脸抓拍和人脸识别能力，但当前上层算法仓库模式为 `Unknown`。
- 这可以解释前几轮现象：人脸抓拍、人脸识别、普通人脸侦测的子配置看似存在，部分字段也可读写，但关键 `Enable` 字段可能受上层算法模式约束，导致 PUT 返回成功却不持久化或不触发真实事件。
- 当前不应继续重试 `/FaceReco/1/RecoRuleList.Enable` 或 `/Pictures/1/FaceDetect.Enable`。
- 下一轮建议单独设计受控写入 `/System/AlgorithmStoreCfg`：
  - 目标值优先为 `FaceRecognition`，因为本项目目标是匹配会员人脸库并区分熟人/陌生人。
  - 写入前必须备份当前 XML。
  - 写入后必须 GET 回读 `AlgorithmType=FaceRecognition`。
  - 写入后再复核 `/FaceReco/1/BaseConfig`、`/AI/FaceSnapshotCfg`、`/FaceReco/1/RecoRuleList`、`/Pictures/1/FaceDetect` 是否发生派生变化。
  - 如果算法模式切换成功，再进入真实人脸事件观察；如果仍不能持久化，停止并复述困难，不继续盲目写其他字段。

### 23.18 Round 18：受控切换算法仓库到 FaceRecognition

本轮目标：

- 将摄像头上层算法仓库从 `Unknown` 受控切换为 `FaceRecognition`。
- 验证算法模式是否能够持久化，并观察它是否带动人脸识别/抓拍子配置出现派生变化。
- 为后续真实人脸事件验证创造明确的算法前置条件。

本轮技术方案：

- 在 `P6SCameraClient` 中新增算法仓库配置方法：
  - `get_algorithm_store_cfg()`：GET `/System/AlgorithmStoreCfg`。
  - `set_algorithm_store_cfg(xml_text)`：PUT `/System/AlgorithmStoreCfg`。
  - `get_face_reco_base_config(channel_id=1)`：GET `/FaceReco/{ChannelID}/BaseConfig`，供写入后复核人脸识别总开关。
- 新增脚本 `scripts/configure_p6s_algorithm_store.py`：
  - 默认只读，输出摄像头连接摘要和当前 `AlgorithmType`。
  - `--print-diff-summary` 输出拟变更摘要，默认目标为 `FaceRecognition`。
  - `--apply` 才执行真实 PUT。
  - 写入前保存完整 `/System/AlgorithmStoreCfg` XML 到系统临时目录，不进入 git。
  - 写入后立即 GET 回读，要求 `AlgorithmType=FaceRecognition`。
  - 写入后复核子配置摘要：`/FaceReco/1/BaseConfig`、`/AI/FaceSnapshotCfg`、`/FaceReco/1/RecoRuleList`、`/Pictures/1/FaceDetect`。
  - 支持 `--restore <backup.xml>` 用完整备份回滚。
- XML 构造不直接照抄 ShowDoc 中缺少闭合标签的示例，而使用真机 GET 返回根节点和脚本生成的完整闭合 XML。
- 本轮先提交工具代码；工具提交后再执行 dry-run 和一次受控 `--apply`。

本轮范围：

- 允许修改：
  - `app/services/p6s_camera.py`
  - `scripts/configure_p6s_algorithm_store.py`
  - `docs/camera-alarm-feishu-push-lld.md`
- 允许对摄像头执行一次 PUT `/System/AlgorithmStoreCfg`，前提是 dry-run 证明只修改 `AlgorithmType=Unknown -> FaceRecognition`。
- 允许只读复核远程事件目录 operator 分布。

本轮不做：

- 不修改 HTTP 事件服务器配置。
- 不修改飞书、nginx、systemd 或远程 env。
- 不直接修改 `/FaceReco/1/BaseConfig`、`/AI/FaceSnapshotCfg`、`/FaceReco/1/RecoRuleList`、`/Pictures/1/FaceDetect`。
- 不删除远程事件目录，不展示 raw payload、图片 base64 或任何密钥。

影响面：

- 设备影响：摄像头 AI 算法模式会从 `Unknown` 切换为 `FaceRecognition`，可能改变 Web 后台当前算法页面选中状态，并可能让人脸识别/抓拍事件开始真实触发。
- 远程影响：如果切换成功并触发真实人脸事件，远程 raw/records 可能新增非 heartbeat 记录。
- 代码影响：新增一个运维配置脚本和两个客户端方法，不改变 FastAPI 运行时业务逻辑。

风险点：

- 当前 `AICap` 中 `AlgorithmWarehouse.support=false`，即使 `FaceReco.support=true`，设备仍可能拒绝或不持久化算法仓库写入。
- 切换到 `FaceRecognition` 可能重置或派生调整部分人脸子配置；必须在写入后复核摘要。
- 如果设备返回成功但回读仍为 `Unknown`，不得继续重试，应记录与前几轮相同的固件限制。
- 如果切换成功但仍没有人脸事件，问题将转移到识别触发条件或摄像头画面/规则层，不能把服务端作为首要嫌疑。

回滚方式：

- 使用脚本写入前保存的完整 XML 备份执行 `--restore <backup.xml>`。
- 或使用脚本目标值 `Unknown` 重新写回，但优先使用备份。
- 本地代码通过 `git revert` 本轮提交回滚。

验证方式：

- `python3 -m py_compile app/services/p6s_camera.py scripts/configure_p6s_algorithm_store.py`。
- `python3 scripts/configure_p6s_algorithm_store.py --print-diff-summary`：
  - `before.algorithm_type=Unknown`。
  - `after.algorithm_type=FaceRecognition`。
  - `changed_fields=["AlgorithmType"]`。
  - `non_target_mismatches=[]`。
- `python3 scripts/configure_p6s_algorithm_store.py --apply`：
  - HTTP 2xx。
  - 设备 `ResponseStatus.statusCode` 为空或 `0`。
  - 回读 `AlgorithmType=FaceRecognition`。
- 写入后复核子配置摘要，确认关键字段未被意外关闭。
- 写入后只读统计远程 raw/records operator 分布，确认是否开始出现真实人脸事件。

本轮停止条件：

- dry-run 显示除 `AlgorithmType` 外还有其他字段变化。
- PUT 返回 HTTP 非 2xx 或设备 `statusCode` 非 `0`。
- 写入后回读不是 `FaceRecognition`。
- 写入后关键子配置被意外关闭，例如 `EnableRecognition=false`、`AIFaceSnapshotCfg.Enable=false` 或 `Trigger.Push=false`。
- 远程出现未知真实事件但字段与现有 fixture 不一致；先记录摘要，不直接改解析逻辑。

本轮提交策略：

- 先提交脚本和客户端方法，提交类型使用 `chore:`。
- 执行真机写入后，如果只更新 LLD 结论，再单独提交 `docs:`。
- 暂存前确认不包含 `.env.local`、图片文件、STYD 会员数据、临时备份 XML 和摄像头 raw payload。

本轮工具提交记录：

- 已新增 `P6SCameraClient.get_algorithm_store_cfg()` 和 `set_algorithm_store_cfg(xml_text)`。
- 已新增 `P6SCameraClient.get_face_reco_base_config(channel_id=1)`，用于写入后复核人脸识别总开关。
- 已新增 `scripts/configure_p6s_algorithm_store.py`：
  - 默认只读。
  - 支持 `--print-diff-summary`。
  - 支持 `--apply` 写入。
  - 支持 `--restore <backup.xml>` 使用完整 XML 备份回滚。
  - 写入后会回读 `AlgorithmType`，并在成功持久化后复核人脸识别、人脸抓拍、识别规则和普通人脸侦测摘要。
  - 输出只包含配置摘要、差异摘要和设备响应摘要，不输出密码、事件 token、图片 base64 或 raw payload。
- 本地语法验证通过：`python3 -m py_compile app/services/p6s_camera.py scripts/configure_p6s_algorithm_store.py`。
- dry-run 验证通过：
  - `ALGORITHM_STORE_BEFORE.algorithm_type=Unknown`。
  - `PATCH_DIFF_SUMMARY.changed_fields=["AlgorithmType"]`。
  - `PATCH_DIFF_SUMMARY.changed_count=1`。
  - `PATCH_DIFF_SUMMARY.non_target_mismatches=[]`。
  - `PATCH_DIFF_SUMMARY.after.algorithm_type=FaceRecognition`。
- 工具与计划已提交：`6129a0a chore: 增加P6S算法仓库受控切换工具`。

本轮真机执行结果：

- 按计划执行过一次 `python3 scripts/configure_p6s_algorithm_store.py --apply`。
- 写入前状态：
  - `AlgorithmType=Unknown`。
  - XML 根节点为 `AlgorithmStoreCfg`，`Version=1.0`。
- 写入前已保存完整 XML 备份，路径位于系统临时目录：`camera-face-guard-p6s-backups/algorithm_store_20260702214211.xml`。
- 设备写入响应：
  - HTTP 状态：`200`。
  - 设备 `ResponseStatus.statusCode=0`。
  - 设备 message 为空。
- 写入后立即 GET 回读：
  - `AlgorithmType=Unknown`。
- 触发本轮停止条件：写入后回读不是 `FaceRecognition`。
- 因为算法模式没有持久化，本轮没有进入子配置派生复核，也没有继续观察真实人脸事件。

本轮结论：

- `/System/AlgorithmStoreCfg` 与此前 `/FaceReco/1/RecoRuleList`、`/Pictures/1/FaceDetect` 的关键启用字段表现一致：设备接受 PUT，并返回成功状态，但目标字段不持久化。
- 当前阻塞已经从“找不到该写哪个子配置”推进为更明确的问题：当前固件或设备状态不允许通过这些 CGI 接口持久化上层算法模式。
- 结合 Round 17 的 `AICap.AlgorithmWarehouse.support=false`，合理推断存在以下可能：
  - 当前固件虽然暴露 `/System/AlgorithmStoreCfg`，但算法仓库写入能力被关闭或只读。
  - 设备的 Web UI 可能通过额外接口、会话态、授权态、重启流程或厂商云端能力激活后才允许切换算法。
  - 当前设备能力模型中 `FaceReco.support=true` 只表示人脸识别功能存在，不等于算法仓库页面可通过 CGI 直接切换。
- 本轮已经按停止条件中断，没有继续尝试其他 XML 写法、没有重试 PUT、没有改 `/System/AIWorkMode`、没有改人脸子配置。
- 下一步不应继续盲目写 API。建议先做人机结合验证：
  - 通过摄像头 Web 后台手动找到“算法仓库/算法商场/人脸识别”页面，尝试切换到人脸识别并保存。
  - 保存后立即由脚本只读查询 `/System/AlgorithmStoreCfg` 是否变化。
  - 如果 Web 后台可以持久化，则再用浏览器 DevTools 或抓取后台 JS/请求确认 Web 实际调用的额外接口。
  - 如果 Web 后台也不能持久化，则问题可能是固件能力、设备型号授权或当前模式限制，需要厂商文档/后台能力页面进一步确认。

### 23.19 Round 19：真实人脸识别可用性验证

本轮目标：

- 修正验收口径：不再把配置回读值作为唯一阻塞条件，而是以真实识别事件是否产生、服务端是否处理、飞书是否通知作为最终可用性证据。
- 验证当前摄像头是否已经可以实际识别人脸并向远程服务器推送事件。
- 如果真实链路已经可用，则停止纠结 `AlgorithmStoreCfg=Unknown`、`RecoRule.Enable=false`、`FaceDetect.Enable=false` 等回读异常，把它们记录为固件表现差异。

本轮技术方案：

- 只读检查远程服务器事件目录：
  - 统计 `raw` 和 `records` 最新日期的 operator/result 分布。
  - 如果出现 `FaceReco`、`FaceSnapshot` 或其他人脸相关 operator，抽取字段摘要，确认是否已经被服务端正确解析。
  - 如果 `records` 出现 known/stranger/parse_error 分支，进一步检查飞书发送状态摘要。
- 如远程仍只有 heartbeat，则进行一次人工触发验证：
  - 请用户站到摄像头前 5 到 10 秒。
  - 在用户触发期间，远程观察 60 到 120 秒 raw/records 是否新增非 heartbeat 事件。
  - 观察只看 operator、result、feishu.status、图片落盘相对路径等摘要，不展示原始图片/base64。
- 本轮不改摄像头配置，不改服务端代码，不重试任何 PUT。

本轮范围：

- 允许修改：
  - `docs/camera-alarm-feishu-push-lld.md`
- 允许只读访问远程服务器事件目录。
- 允许只读调用摄像头查询接口，但不以配置回读作为可用性否决条件。

本轮不做：

- 不写 `/System/AlgorithmStoreCfg`。
- 不写 `/FaceReco/1/RecoRuleList`、`/Pictures/1/FaceDetect`、`/AI/FaceSnapshotCfg`。
- 不重启远程服务。
- 不展示 raw payload、图片 base64、摄像头密码、事件 token、飞书秘钥。

通过标准：

- 远程 raw 中出现真实人脸相关事件，并且 records 中产生对应处理结果。
- 匹配成功事件能进入 known 分支并触发飞书通知。
- 陌生人事件能进入 stranger 分支，图片能落盘并生成可访问链接或相对存储位置。

失败或继续条件：

- 如果观察窗口内仍只有 heartbeat，说明当前现实链路还没有证明可用，需要继续排查触发条件、摄像头画面/算法、人脸库或 Web 后台模式。
- 如果出现人脸事件但服务端解析失败，下一轮应按真实 raw 字段修复解析 fixture，而不是继续改摄像头配置。
- 如果出现人脸事件且飞书通知成功，则本阶段可认为“识别推送链路可用”，后续转入稳定性和字段完善。

风险点：

- 没有人站在摄像头前时，远程只有 heartbeat 不能证明识别不可用。
- 摄像头可能只在画面质量、距离、光照和角度满足条件时触发人脸事件。
- 如果真实事件 operator 与文档不同，不能直接丢弃，需要以 raw 摘要为准调整服务端解析。

回滚方式：

- 本轮只读无设备或代码回滚。
- 文档结论如被后续真实事件推翻，下一轮先修订本节。

验证方式：

- `ssh qypower-prod` 统计 `/var/lib/camera-face-guard/p6s_events/raw/<date>` 与 `records/<date>`。
- 如需要人工触发，则在触发前后分别记录 raw/records 总数和 operator 分布差异。
- 如出现真实事件，抽样 records 的 `operator`、`result`、`feishu.status`、`stored_image` 或等价字段摘要。

本轮提交策略：

- 只更新文档时提交类型使用 `docs:`。
- 暂存前确认不包含 `.env.local`、图片文件、STYD 会员数据、临时备份 XML 和摄像头 raw payload。

本轮第一阶段只读检查结果：

- 远程事件目录最新日期为 `2026-07-02`。
- `/var/lib/camera-face-guard/p6s_events/raw/2026-07-02`：
  - `total=175`。
  - `operators={"heartbeat": 175}`。
  - `non_heartbeat_samples=[]`。
- `/var/lib/camera-face-guard/p6s_events/records/2026-07-02`：
  - `total=175`。
  - `operators={"heartbeat": 175}`。
  - `results={"heartbeat": 175}`。
  - `feishu_status={}`。
  - `image_fields={}`。
  - `non_heartbeat_samples=[]`。

第一阶段结论：

- 目前远程历史数据仍没有证明人脸识别事件已经可用。
- 但“只有 heartbeat”不能直接证明人脸识别不可用，因为无人站在摄像头前、光照/角度不满足、或触发窗口不够，都可能导致没有真实事件。
- 下一步必须进行人工站位测试：
  - 用户站到摄像头前 5 到 10 秒。
  - 站位前后分别统计远程 raw/records 总数和 operator 分布。
  - 如果新增非 heartbeat 人脸事件，就按真实事件继续验证服务端解析和飞书通知。
  - 如果仍只有 heartbeat，再回到摄像头触发条件、画面识别框、Web 后台算法页面等方向排查。

### 23.20 Round 20：恢复 RecoRule 到已知可抓拍状态

本轮目标：

- 按用户明确指令恢复第 3 条可疑配置：`/FaceReco/1/RecoRuleList`。
- 将当前识别规则恢复到历史证据中“抓拍变好”后的状态：`ControlPersonnelType=Stranger`、`Trigger.Snapshot.Enable=true`。
- 恢复后停止，交给用户重新做现实抓拍测试。

本轮技术方案：

- 使用已存在的历史可用状态 XML：
  - `/private/tmp/p6sai-fix-recorule-20260702_171528/after_recorule.xml`
- 写入前只读读取当前 `/FaceReco/1/RecoRuleList`，只比较摘要字段：
  - `RecoRule.Enable`
  - `RecognitionRule`
  - `CompareLimit`
  - `FaceGroupList.ControlPersonnelType`
  - `Trigger.Push.Enable`
  - `Trigger.Snapshot.Enable`
  - `Trigger.Snapshot.SnapshotMask`
  - `Trigger.Record.Enable`
  - `Schedule.AllDay`
- 执行一次完整 XML PUT `/FaceReco/1/RecoRuleList`。
- 写入后立即 GET 回读，确认至少满足：
  - `FaceGroupList.ControlPersonnelType=Stranger`
  - `Trigger.Snapshot.Enable=true`
  - `Trigger.Snapshot.SnapshotMask=1`
  - `Trigger.Push.Enable=true`
  - `Trigger.Record.Enable=true`

本轮范围：

- 允许修改：
  - `docs/camera-alarm-feishu-push-lld.md`
- 允许对摄像头执行一次 PUT `/FaceReco/1/RecoRuleList`。

本轮不做：

- 不写 `/AI/FaceSnapshotCfg`。
- 不写 `/Pictures/1/FaceDetect`。
- 不写 `/System/AlgorithmStoreCfg`。
- 不写 `/System/HTTPEventServerConfigV2`。
- 不写人脸库、人员、Owner、组织结构。
- 不重启摄像头或远程服务。
- 不展示摄像头密码、事件 token、图片 base64 或完整 raw payload。

影响面：

- 设备影响：人脸识别规则的布控对象会恢复为陌生人，抓拍联动保持开启。
- 远程影响：如果摄像头重新产生人脸事件，服务器可能收到新的非 heartbeat 事件。
- 文档影响：记录恢复前后摘要，作为后续测试基线。

风险点：

- 完整 XML PUT 可能让设备按自身固件规则回写部分字段，例如 `RecoRule.Enable` 仍可能保持 `false`。
- 如果当前用户其实希望识别组织成员而不是陌生人，恢复为 `Stranger` 会改变识别规则语义；但本轮是按用户要求恢复“第 3 条”。
- 如果恢复后仍不抓拍，说明问题不止在 `ControlPersonnelType` 或抓拍联动字段。

回滚方式：

- 本轮写入前保存当前 `/FaceReco/1/RecoRuleList` 到系统临时目录。
- 如恢复后表现更差，可用该备份完整 PUT 回写。

验证方式：

- 写入前后摘要对比。
- 写入后只读回查关键字段。
- 用户随后站到摄像头前做现实抓拍测试。

本轮停止条件：

- 历史 XML 文件不存在或无法解析。
- 当前规则读取失败。
- PUT 返回 HTTP 非 2xx 或设备 `statusCode` 非 `0`。
- 写入后 `ControlPersonnelType` 未恢复为 `Stranger`。
- 写入后 `Trigger.Snapshot.Enable` 未保持 `true`。

本轮执行结果：

- 写入前只读保存当前规则到系统临时文件：
  - `/private/tmp/reco_rule_before_restore_round20.xml`
- 使用历史可用状态 XML 作为恢复目标：
  - `/private/tmp/p6sai-fix-recorule-20260702_171528/after_recorule.xml`
- 写入前摘要对比：
  - 当前：`ControlPersonnelType=OrganizationMember`
  - 目标：`ControlPersonnelType=Stranger`
  - 其他关键字段无差异：`RecognitionRule=Comparison pass`、`CompareLimit=0`、`Trigger.Push.Enable=true`、`Trigger.Snapshot.Enable=true`、`Trigger.Snapshot.SnapshotMask=1`、`Trigger.Record.Enable=true`、`Schedule.AllDay=true`
- 已执行一次完整 XML PUT `/FaceReco/1/RecoRuleList`。
- 写入响应：
  - HTTP 状态：`200`
  - 设备 `ResponseStatus.statusCode=0`
  - 设备 message 为空
- 写入后只读回读摘要：
  - `ControlPersonnelType=Stranger`
  - `Trigger.Snapshot.Enable=true`
  - `Trigger.Snapshot.SnapshotMask=1`
  - `Trigger.Push.Enable=true`
  - `Trigger.Record.Enable=true`
  - `Schedule.AllDay=true`
  - `RecoRule.Enable=false`

本轮结论：

- 第 3 条已按用户要求恢复成功。
- 当前设备规则已经回到历史证据中的可抓拍基线：`Stranger + Snapshot=true + Push=true + Record=true`。
- `RecoRule.Enable=false` 仍存在，但该值与历史可抓拍基线一致，本轮不再把它作为恢复失败条件。
- 本轮没有写入 `/AI/FaceSnapshotCfg`、`/Pictures/1/FaceDetect`、`/System/AlgorithmStoreCfg`、`/System/HTTPEventServerConfigV2`、人脸库、人员、Owner 或组织结构。
- 下一步应由用户重新站到摄像头前测试现实抓拍效果；如仍不抓拍，再基于该恢复基线只读排查。

### 23.21 Round 21：会员脸库批量导入运行步骤

本轮目标：

- 将本地会员 CSV 中已有人脸图片的 244 个会员写入摄像头“会员”脸库。
- 使用 `member_name` 作为摄像头人员姓名。
- 使用 CSV `id` 作为 `FaceUUID`，并绑定同名图片 `styd_member_faces/{id}.jpg`。
- 性别统一写入 `male`。

本轮技术方案：

- 目标脸库：
  - `GroupName=会员`
  - `GroupID2=c1e42a1f2531467bae464da8a79dad53`
- 写入前预检：
  - CSV 必须存在且恰好 244 行。
  - `id` 必须非空、唯一、全部为 16 位数字。
  - `member_name` 必须非空，UTF-8 字节长度不得超过 32。
  - 每个 `id` 必须有对应 `styd_member_faces/{id}.jpg`。
  - JPG 必须可打开，大小不得超过接口文档建议上限。
- 脸库确认：
  - 先调用 `/FaceGroups/QueryAll`。
  - 如果目标 `GroupID2` 已存在且名称为“会员”，直接复用。
  - 如果目标 `GroupID2` 不存在，调用 `/FaceGroups/Create` 创建。
  - 如果目标 `GroupID2` 已存在但名称不是“会员”，立即停止。
- 人员写入：
  - 使用官方 multipart `POST /FaceGroup/UpdatePersonInfoAndFaceImage`。
  - 字段固定为 `Name`、`Sex`、`Ownner`、`FaceGroupID`、`FaceUUID`、`SystemTime`、`file`。
  - 先写入样本 `3785841386866689 / 苏苏`，成功后再按 CSV 顺序写入剩余人员。
  - 单线程执行，每条间隔约 200ms。

本轮范围：

- 允许修改：
  - `docs/camera-alarm-feishu-push-lld.md`
- 允许写入摄像头：
  - `/FaceGroups/Create`，仅当“会员”目标脸库不存在时。
  - `/FaceGroup/UpdatePersonInfoAndFaceImage`，仅写入会员 CSV 中的 244 个会员。

本轮不做：

- 不写入“教练”或“员工”脸库。
- 不写入组织结构。
- 不修改人脸识别抓拍、推送、录像、算法、HTTP 事件配置。
- 不修改远程服务器或飞书配置。
- 不提交会员 CSV、图片或 `.env.local`。

停止条件：

- 写入前预检失败。
- 目标脸库 ID 与现有名称冲突。
- 样本写入失败。
- 样本写入后无法通过人员查询或等价证据确认。
- 批量写入任一人员返回 HTTP 非 2xx 或设备 `statusCode` 非 `0`。

回滚方式：

- 本轮不在执行中自动删除人员，避免误删既有人脸库数据。
- 如需回滚，使用运行报告中的成功 `FaceUUID` 列表，按 `/FaceGroup/DeletePersonList` 从“会员”脸库删除本轮成功写入的人员。
- 如果本轮创建了“会员”脸库且确认其中只有本轮数据，可使用 `/FaceGroups/Delete` 删除该脸库。

验证方式：

- 写入报告记录每条人员的 `id`、`name`、图片文件、HTTP 状态、设备状态码和响应摘要。
- 写入后使用 `/FaceGroup/QueryPersonInfoList` 分页查询，按 `FaceUUID` 统计目标人员是否存在。
- 真实验收由用户站到摄像头前触发识别，远程事件中应出现 `FaceReco`，并包含 CSV 姓名和会员 ID。

本轮执行结果：

- 运行目录：
  - `/private/tmp/p6s_member_import_20260703_084508`
- 写入前预检通过：
  - CSV 行数：244。
  - manifest 行数：244。
  - `id` 无重复、无空值，图片全部存在且可打开。
  - `member_name` 无空值，存在 1 组重名，但本轮按用户要求不追加手机号或 ID。
- 目标脸库检查：
  - 初始 `/FaceGroups/QueryAll` 中不存在目标 `GroupID2`，且无同名冲突。
  - 已创建 `GroupName=会员`、`GroupID2=c1e42a1f2531467bae464da8a79dad53`。
  - 原始 UTF-8 回读确认脸库名为“会员”。
- 样本写入：
  - 已写入 `3785841386866689 / 苏苏`。
  - HTTP 状态：`200`。
  - 设备 `statusCode=0`。
  - `/FaceGroup/QueryPersonInfoList` 回查到对应 `FaceUUID`。
- 批量写入：
  - 剩余 243 条全部返回成功。
  - 加上样本，总计 244 条目标会员写入成功。
  - 未出现中途失败。
- 写入后回查：
  - `/FaceGroups/QueryAll` 回读“会员”脸库：
    - `PersonInfoCount=244`
    - `ValidPersonCount=244`
    - `InvalidPersonCount=0`
  - `/FaceGroup/QueryPersonInfoList` 分页回查：
    - 244 个目标会员 `FaceUUID` 全部存在，缺失数为 0。
    - 查询结果额外包含历史测试 ID `3427976339944670`；由于 `/FaceGroups/QueryAll` 对“会员”脸库计数为 244，本轮不删除该历史测试人员，避免误删非本轮数据。
    - 查询到的人员 `ModelState` 均为 `success`。
- 本轮未修改：
  - 远程服务器。
  - 飞书配置。
  - 人脸识别抓拍、推送、录像、算法或 HTTP 事件配置。
  - 教练/员工脸库。

### 23.22 Round 22：教练/员工脸库批量导入运行步骤

本轮目标：

- 将本地 `teacher.csv` 中的 15 名教练写入摄像头“教练”脸库。
- 将本地 `staff.csv` 中的 4 名员工写入摄像头“员工”脸库。
- 使用 CSV `姓名` 作为摄像头人员姓名。
- 使用 CSV `ID` 作为 `FaceUUID`，并绑定 CSV `人脸图片名称` 指向的本地图片。
- 性别统一写入 `male`。

本轮技术方案：

- 目标脸库：
  - 教练：`GroupName=教练`，`GroupID2=9c89bc7bc2234801b5ae0f8d60da8c30`
  - 员工：`GroupName=员工`，`GroupID2=4dcafc2c9fbd4d1fa267ccbf145c8861`
- 写入前预检：
  - `teacher.csv` 必须存在且恰好 15 行。
  - `staff.csv` 必须存在且恰好 4 行。
  - `ID` 必须非空且唯一。
  - `姓名` 必须非空，UTF-8 字节长度不得超过 32。
  - `人脸图片名称` 必须符合 `ID_姓名.(jpg|jpeg|png)`。
  - 每条记录必须有对应本地图片，且图片必须可打开。
  - 如果图片尺寸超过设备导入建议上限，或图片不是适合设备导入的 RGB JPEG，则在运行目录生成临时归一化 JPEG 副本；原始图片不修改。
  - 教练、员工之间不得有重复 ID；不得与已导入会员 CSV 的 ID 冲突。
- 脸库确认：
  - 先调用 `/FaceGroups/QueryAll`。
  - 如果目标 `GroupID2` 已存在且名称匹配，直接复用。
  - 如果目标 `GroupID2` 不存在，调用 `/FaceGroups/Create` 创建。
  - 如果目标 `GroupID2` 已存在但名称不匹配，或目标名称被其他 `GroupID2` 占用，立即停止。
- 人员写入：
  - 使用官方 multipart `POST /FaceGroup/UpdatePersonInfoAndFaceImage`。
  - 字段固定为 `Name`、`Sex`、`Ownner`、`FaceGroupID`、`FaceUUID`、`SystemTime`、`file`。
  - 先写入教练样本 `2190181831084742 / 祝教练`。
  - 再写入员工样本 `1715263741293 / 刘彩玲`。
  - 样本成功后，先按 CSV 顺序写入剩余 14 名教练，再写入剩余 3 名员工。
  - 实际上传文件优先使用运行目录中的归一化 JPEG 副本；报告同时记录原图路径和实际上传路径。
  - 单线程执行，每条间隔约 200ms。

本轮范围：

- 允许修改：
  - `docs/camera-alarm-feishu-push-lld.md`
- 允许写入摄像头：
  - `/FaceGroups/Create`，仅当“教练”或“员工”目标脸库不存在时。
  - `/FaceGroup/UpdatePersonInfoAndFaceImage`，仅写入教练和员工 CSV 中的 19 个人员。

本轮不做：

- 不修改“会员”脸库。
- 不写入组织结构。
- 不修改人脸识别抓拍、推送、录像、算法、HTTP 事件配置。
- 不修改远程服务器或飞书配置。
- 不修改 `.env.local`。
- 不提交 CSV 或图片。

停止条件：

- 写入前预检失败。
- 目标脸库 ID 或名称冲突。
- 任一样本写入失败。
- 任一样本写入后无法通过人员查询确认在目标组。
- 批量写入任一人员返回 HTTP 非 2xx 或设备 `statusCode` 非 `0`。

回滚方式：

- 本轮不在执行中自动删除人员，避免误删既有人脸库数据。
- 如需回滚，使用运行报告中的成功 `FaceUUID` 列表，按 `/FaceGroup/DeletePersonList` 从对应脸库删除本轮成功写入的人员。
- 如果本轮创建了“教练”或“员工”脸库且确认其中只有本轮数据，可使用 `/FaceGroups/Delete` 删除该脸库。

验证方式：

- 写入报告记录每条人员的角色、`id`、`name`、图片文件、HTTP 状态、设备状态码和响应摘要。
- 写入报告同时记录原始图片路径、实际上传图片路径、原始尺寸和归一化后尺寸，便于定位 `4112` 等图片规格问题。
- 写入后使用 `/FaceGroup/QueryPersonInfoList` 分页查询，按 `FaceUUID` 和返回 `<Group>` 字段等于目标 `GroupID2` 统计目标人员是否存在。
- `/FaceGroup/QueryPersonInfoList` 的数字 `GroupID` 在当前设备上不能可靠区分脸库，不能作为分组校验依据。
- `/FaceGroups/QueryAll` 回读“教练”和“员工”脸库的 `PersonInfoCount`、`ValidPersonCount`、`InvalidPersonCount`。
- 真实验收由用户站到摄像头前触发识别，事件中应包含对应姓名和人员 ID，并可通过 `GroupID2` 映射识别为教练或员工。

本轮执行结果：

- 首次运行目录：
  - `/private/tmp/p6s_role_import_20260703_092058`
- 首次运行结果：
  - 写入前预检通过，manifest 行数为 19。
  - 摄像头初始只存在“会员”脸库。
  - 已创建“教练”和“员工”两个目标脸库。
  - 教练样本 `2190181831084742 / 祝教练` 使用原始图片写入时，HTTP 状态为 `200`，设备 `statusCode=4112`，按停止条件终止。
  - 失败样本原图为 `1276x1276`、约 `239955` 字节；对比此前成功会员图约 `210x210`，判断需要按设备图片规格生成临时归一化上传图。
- 二次运行目录：
  - `/private/tmp/p6s_role_import_20260703_092235`
- 二次运行调整：
  - 对超尺寸或非 RGB JPEG 图片，在运行目录 `normalized_faces/` 下生成临时 JPEG 副本。
  - 原始图片不修改。
  - 报告同时记录原图路径和实际上传路径。
- 二次运行预检通过：
  - 教练 CSV 行数：15。
  - 员工 CSV 行数：4。
  - 教练图片数：15。
  - 员工图片数：4。
  - 无重复 ID、无重复图片名、无缺失图片、无跨角色重复 ID、无会员 ID 冲突。
- 样本写入：
  - 已写入教练样本 `2190181831084742 / 祝教练`。
  - 已写入员工样本 `1715263741293 / 刘彩玲`。
  - 两个样本均为 HTTP `200`、设备 `statusCode=0`。
  - 两个样本均通过人员列表按 `FaceUUID + GroupID2` 回查确认。
- 批量写入：
  - 剩余 14 名教练全部写入成功。
  - 剩余 3 名员工全部写入成功。
  - 加上样本，总计 19 名目标人员写入成功。
- 写入后回查：
  - `/FaceGroups/QueryAll` 回读“教练”脸库：
    - `PersonInfoCount=15`
    - `ValidPersonCount=15`
    - `InvalidPersonCount=0`
  - `/FaceGroups/QueryAll` 回读“员工”脸库：
    - `PersonInfoCount=4`
    - `ValidPersonCount=4`
    - `InvalidPersonCount=0`
  - `/FaceGroup/QueryPersonInfoList` 分页回查：
    - 查询总人数为 263。
    - 会员组：244 人。
    - 教练组：15 人。
    - 员工组：4 人。
    - 19 个目标 `FaceUUID` 全部存在，缺失数为 0。
    - 查询到的人员 `ModelState` 均为 `success`。
- 本轮未修改：
  - 会员脸库。
  - 组织结构。
  - 人脸识别抓拍、推送、录像、算法或 HTTP 事件配置。
  - 远程服务器。
  - 飞书配置。
  - `.env.local`。

## 24. 未开发项审计与推进计划

本节只记录仍需开发、文档修订或配置模板调整的任务；不把真机未验收、人工未触发、飞书未观察到等验证事项混入“未开发”口径。

### 24.1 本轮跟踪项与实现状态

1. 飞书通知标题按人员类型定制：
   - 本轮已实现：`app/services/feishu.py` 支持按角色传入标题，陌生人标题改为“发现陌生人入场”。
   - 已确认基础标题：`会员入场提醒`、`教练入场提醒`、`员工入场提醒`、`人员入场提醒`、`发现陌生人入场`。
   - 文案优化后，主飞书标题前增加用户可见 emoji：会员 `😊`、教练 `🧑‍🏫`、员工 `🧑‍💼`、陌生人 `‼️`。
   - 验证方式：本地 fixture 校验飞书 post payload 的标题和正文，不发送真实飞书消息。

2. `FaceReco.personInfo` 到本地角色的映射层：
   - 本轮已实现：服务端解析 `personType`、`groupId`、`groupName`、`Group`、`FaceGroupID` 等字段，映射为“会员/教练/员工”。
   - 已知真机现象：真实 `FaceReco` 样本中 `groupId` 与 `groupName` 可能为空，`personType` 可携带脸库 `GroupID2`。
   - 降级策略：无法识别角色时不丢弃事件，使用 `role=unknown` 和“人员入场提醒”。

3. 教练/员工入场通知语义：
   - 本轮已实现：通知层区分会员、教练、员工和未知已匹配身份。
   - 字段展示：已识别人员保留姓名、身份类型、时间、事件 ID 和图片查看入口；陌生人保留时间、事件 ID 和图片查看入口。
   - 不再展示人员 ID、设备和保存位置；这些字段保留在处理记录、数据库或监控后台中用于排障，不进入主飞书正文。

4. 旧文件名图片公开接口收口：
   - 本轮已实现：`GET /api/p6s/event-images/{filename}` 保留为排障入口，但增加管理员鉴权。
   - 对外路径：飞书消息只使用 token 图片入口 `GET /api/p6s/event-images/view/{token}`。

5. 事件与图片保留期清理机制：
   - 本轮已实现：新增 `scripts/cleanup_p6s_event_store.py`。
   - 行为：只清理过期 `raw`、`records`、`strangers`、`links` 日期目录；默认 dry-run，显式 `--apply` 才删除。
   - 约束：脚本不接触摄像头，不删除 LLD、CSV、人脸库导入报告或非事件根目录文件。

6. LLD 当前状态同步：
   - 本轮已同步：本节记录截至当前的开发状态、硬约束、批准步骤和验证结果。
   - 仍需注意：真人识别、远程服务器接收事件和飞书真实送达属于后续验证任务，不属于本轮代码未完成项。

### 24.2 推进硬约束

- 未经用户明确允许，后续任何开发、验证和排障都禁止向摄像头写入配置。
- 禁止未经允许调用以下摄像头写接口：
  - `/System/HTTPEventServerConfigV2`
  - `/FaceReco/1/RecoRuleList`
  - `/Pictures/1/FaceDetect`
  - `/AI/FaceSnapshotCfg`
  - `/System/AlgorithmStoreCfg`
  - `/FaceGroups/Create`
  - `/FaceGroups/Modify`
  - `/FaceGroups/Delete`
  - `/FaceGroup/UpdatePersonInfoAndFaceImage`
  - `/FaceGroup/ModifyPersonInfo`
  - `/FaceGroup/DeletePersonList`
- 允许的默认动作仅限：
  - 阅读和修改本地代码/文档。
  - 运行本地单元或 fixture 验证。
  - 只读查看远程服务器事件目录、日志摘要和 systemd 状态。
  - 只读调用摄像头 GET/查询类接口；如果接口语义不明确，先停下来确认，不用“试试看”的方式写入。
- 如后续确实需要写摄像头，必须先新增或更新 LLD 小节，写清楚目标接口、写入字段、影响面、回滚方式、停止条件，并等用户明确批准。

### 24.3 建议开发顺序

1. 同步文档当前状态：
   - 更新 LLD 中过时的“当前实现差距”和真机验证结论。
   - 明确三组脸库已完成录入，但三组入场通知标题尚未开发。

2. 设计并实现角色映射层：
   - 从环境变量读取会员、教练、员工的 `GroupID2` 与名称。
   - 从真实 `personInfo` 中优先读取 `personType`、`groupId`、`groupName`，映射到本地角色。
   - 在处理记录中保存 `person_role`、`person_role_name`、`person_group_id`，便于排障。

3. 改造飞书通知模板：
   - `notify_known_face` 增加角色/标题入参。
   - 匹配成功按角色生成标题。
   - 陌生人标题改为“发现陌生人入场”。
   - 保持原有姓名、人员 ID、设备、时间、事件 ID 字段不丢失。

4. 补充 fixture 与本地验证：
   - 增加会员、教练、员工、未知角色、陌生人 fixture。
   - 验证各角色标题、记录字段、飞书 payload 结构。
   - 验证无角色字段时降级为通用标题。

5. 收口旧图片接口：
   - 先确认是否仍需保留本地排障入口。
   - 按确认结果实现删除或管理员鉴权。
   - 验证 token 图片入口不受影响。

6. 增加事件保留期清理脚本：
   - 支持 `--dry-run`、`--apply`、`--days`。
   - 只允许清理 `P6S_EVENT_IMAGE_DIR` 下的事件子目录。
   - 默认不接入定时任务；是否加 cron/systemd timer 另行确认。

### 24.5 本轮批准开发步骤

本轮只实现服务端代码、文档、配置模板和本地验证脚本；不部署远程服务器、不修改 `.env.local`、不调用任何摄像头写接口、不变更脸库数据。

1. 文档落地：
   - 将本轮批准范围、默认标题、验证方式和摄像头写入禁令同步到本节。
   - 后续实现必须以本节为边界，发现范围外需求先暂停反馈。

2. 角色映射：
   - 服务端从环境变量读取三组脸库：
     - `P6S_FACE_GROUP_MEMBERS_ID` / `P6S_FACE_GROUP_MEMBERS_NAME`
     - `P6S_FACE_GROUP_COACHES_ID` / `P6S_FACE_GROUP_COACHES_NAME`
     - `P6S_FACE_GROUP_STAFF_ID` / `P6S_FACE_GROUP_STAFF_NAME`
   - 兼容旧配置 `P6S_FACE_GROUP_ID` / `P6S_FACE_GROUP_NAME`，作为会员组 fallback。
   - 从 `personInfo` 中按 `personType`、`groupId`、`groupName`、`Group`、`FaceGroupID` 等字段匹配本地角色。
   - 匹配不到角色时不丢弃事件，降级为 `role=unknown`、标题“人员入场提醒”。

3. 飞书通知：
   - 已匹配人员标题：
     - 会员：`😊 会员入场提醒`
     - 教练：`🧑‍🏫 教练入场提醒`
     - 员工：`🧑‍💼 员工入场提醒`
     - 未知已匹配身份：`人员入场提醒`
   - 陌生人标题：`‼️ 发现陌生人入场`。
   - 飞书正文保留姓名、身份类型、时间、事件 ID 和图片查看入口。
   - 飞书正文不展示人员 ID、设备和保存位置，降低用户侧噪音；排障仍从处理记录、DB 或监控后台查看这些内部字段。
   - 抽出纯 payload 构建函数，便于本地验证，不依赖真实飞书 webhook。

4. 事件处理记录：
   - `known` 记录中保存 `person_role`、`person_role_name`、`person_group_id`、`person_group_name`、`notification_title`。
   - `stranger` 记录保持图片落盘、token 链接和 Ack 行为不变。

5. 图片访问接口：
   - 飞书链接只使用 `GET /api/p6s/event-images/view/{token}`。
   - 旧 `GET /api/p6s/event-images/{filename}` 保留为排障入口，但必须加管理员鉴权；未登录用户不能通过裸文件名访问图片。

6. 事件保留期清理：
   - 新增手动运维脚本，默认 dry-run。
   - 仅扫描并清理事件根目录下的 `raw`、`records`、`strangers`、`links` 日期目录。
   - 只有显式传入 `--apply` 才删除；本轮不接入 cron 或 systemd timer。

7. 本地验证：
   - 扩展 fixture 验证会员、教练、员工、未知已匹配身份、陌生人、重复事件、心跳。
   - 验证飞书 payload 标题和正文，不发送真实飞书消息。
   - 验证 token 图片入口不受旧路由鉴权影响。
   - 用 `/private/tmp` 模拟事件目录验证清理脚本 dry-run 和 apply。

### 24.6 本轮实现结果

- 已更新：
  - `app/services/p6s_events.py`
  - `app/services/feishu.py`
  - `app/routers/camera.py`
  - `scripts/cleanup_p6s_event_store.py`
  - `scripts/validate_p6s_event_flow.py`
  - `.env.example`
  - `README.md`
  - `DEPLOY.md`
  - `tests/fixtures/p6s_face_reco_member.json`
  - `tests/fixtures/p6s_face_reco_coach.json`
  - `tests/fixtures/p6s_face_reco_staff.json`
  - `tests/fixtures/p6s_face_reco_unknown_role.json`
- 已验证：
  - `python3 -m py_compile app/services/p6s_events.py app/services/feishu.py app/routers/camera.py scripts/cleanup_p6s_event_store.py scripts/validate_p6s_event_flow.py`
  - `python3 scripts/validate_p6s_event_flow.py`
- 本轮未执行：
  - 未部署远程服务器。
  - 未修改 `.env.local`。
  - 未调用摄像头写接口。
  - 未修改摄像头配置、脸库、组织结构或人员数据。

### 24.7 不属于开发未完成的事项

- 会员、教练、员工三组脸库录入后的真人识别测试：属于验证任务。
- 陌生人站位触发、图片落盘、token 链接点击：属于验证任务，除非验证发现代码缺陷。
- 真实重复事件幂等：属于验证任务；当前本地 fixture 已覆盖 duplicate 分支。
- 摄像头抓拍/识别配置继续调参：不属于当前开发任务，且必须遵守 24.2 的写入禁令。

### 24.8 远程部署脚本与本轮部署步骤

本节用于把本轮服务端模板改动发布到 `qypower-prod`，并沉淀一个可重复使用的本地部署脚本。

部署目标：

- 远程主机：`qypower-prod`。
- 应用目录：`/opt/camera-face-guard`。
- systemd 服务：`camera-face-guard`。
- 环境变量文件：`/etc/camera-face-guard/app.env`，本轮不修改。
- 事件和图片目录：`/var/lib/camera-face-guard/p6s_events`，本轮不修改。

脚本设计：

- 新增 `scripts/deploy_qypower_prod.sh`，从本地执行。
- 默认同步当前工作区代码到远程 `/opt/camera-face-guard/`。
- 默认执行本地语法检查和 fixture 验证。
- 默认远程执行语法检查、fixture 验证、服务重启和本机 HTTP 验证。
- 支持 `--dry-run` 只查看同步计划。
- 支持 `--skip-local-check`、`--skip-remote-check`、`--skip-deps`、`--skip-restart` 作为排障开关。

同步范围：

- 同步应用代码、静态页面、脚本、测试 fixture、文档和配置模板。
- 不同步真实本地配置：`.env.local`、`.env.*`。
- 不同步本地虚拟环境、Git 目录、缓存目录。
- 不同步会员图片、教练图片、员工图片、CSV、抓取报告、事件日志等数据文件。
- 不使用 `--delete-excluded`，避免删除远程已经存在但被排除的数据目录，如 `styd_member_faces/` 和 `.venv/`。

部署验证：

1. 本地：
   - `python3 -m py_compile app/services/p6s_events.py app/services/feishu.py app/routers/camera.py scripts/cleanup_p6s_event_store.py scripts/validate_p6s_event_flow.py`
   - `python3 scripts/validate_p6s_event_flow.py`
2. 远程：
   - `.venv/bin/python -m py_compile ...`
   - `.venv/bin/python scripts/validate_p6s_event_flow.py`
   - `systemctl restart camera-face-guard`
   - `systemctl is-active camera-face-guard`
   - `curl http://127.0.0.1:8000/api/docs`
   - `curl http://127.0.0.1:8000/camera`
   - 只读 grep 确认远程代码已包含 `会员入场提醒`、`教练入场提醒`、`员工入场提醒`、`发现陌生人入场`。

回滚方式：

- 本轮部署脚本会在远程生成 `~/camera-face-guard-backups/backup-<timestamp>` 备份目录。
- 如部署后服务异常，可在远程执行：
  - `sudo systemctl stop camera-face-guard`
  - `rsync -a --delete ~/camera-face-guard-backups/backup-<timestamp>/ /opt/camera-face-guard/`
  - `sudo systemctl restart camera-face-guard`
- 回滚不涉及 `/etc/camera-face-guard/app.env` 和 `/var/lib/camera-face-guard/p6s_events`。

本轮限制：

- 不修改 `.env.local`。
- 不修改远程 `/etc/camera-face-guard/app.env`。
- 不写摄像头配置、不写脸库、不调用摄像头写接口。
- 不触发飞书测试消息；只验证模板代码和本地 fixture。

本轮执行结果：

- 已新增并使用 `scripts/deploy_qypower_prod.sh`。
- 首次部署前备份：
  - `/home/ubuntu/camera-face-guard-backups/backup-20260703101943`
- 首次部署已完成文件同步，但远程验证脚本因 `fastapi.testclient` 额外依赖缺失而在重启前停止；服务当时未切换到新代码。
- 已将验证脚本改为不依赖 `TestClient`，通过直接 token 解析和路由依赖检查完成图片入口验证。
- 二次部署完成代码同步、远程 fixture 验证和服务重启；服务状态为 `active`。
- 重启后即时 HTTP 检查曾遇到启动竞态，后续只读检查确认：
  - `http://127.0.0.1:8000/api/docs` 返回 `200`。
  - `http://127.0.0.1:8000/camera` 返回 `200`。
  - 远程代码已包含 `会员入场提醒`、`教练入场提醒`、`员工入场提醒`、`发现陌生人入场`。
- 已为部署脚本增加 HTTP 等待循环，并用 `--skip-restart` 同步到远程后验证通过。
- 最新脚本同步备份：
  - `/home/ubuntu/camera-face-guard-backups/backup-20260703102118`
- 本轮未修改：
  - `.env.local`
  - `/etc/camera-face-guard/app.env`
  - 摄像头配置
  - 摄像头脸库和人员数据
  - 飞书机器人配置

## 25. 参考文档

- `docs/camera-alarm-feishu-push-plan.html`
- `README.md`
- `DEPLOY.md`
- `app/routers/camera.py`
- `app/services/feishu.py`
- `app/services/p6s_camera.py`
- `scripts/qypower-camera.service`
- `scripts/qypower-nginx.conf`
- P6S HTTP 事件文档：`http://docs.p6sai.com/docs/cn/device/Event/http/index.html`
- P6S FaceReco 文档：`http://docs.p6sai.com/docs/cn/device/Event/http/FaceRecognitionEvents.html`
- 飞书自定义机器人文档：`https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot`
