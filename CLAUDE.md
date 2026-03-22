# 项目上下文（供 Claude Code 快速回忆）

## 项目概况

A 股行情监控 Web 系统，数据来源 Tushare Pro，后端 FastAPI + PostgreSQL，前端静态页面。

- **项目路径**：`/home/stock/stock`
- **系统用户**：`stock`
- **Python**：3.12，虚拟环境 `.venv/`
- **Web 服务端口**：8000
- **数据库**：PostgreSQL，本机 localhost:5432，库名 `stock`

## 关键文件

| 文件 | 说明 |
|------|------|
| `run.py` | 启动 Web 服务（uvicorn，port 8000） |
| `config.py` | DB / Tushare / 指数代码配置，优先读环境变量 |
| `db/connection.py` | psycopg2 连接 + upsert 工具 |
| `db/schema.sql` | 全库表结构（含索引） |
| `pipeline.py` | 数据拉取入口，供定时任务调用 |
| `scripts/daily_update.py` | 定时更新调度器 |
| `scripts/update_config.yaml` | 定时任务配置（阶段/cron/任务） |
| `scripts/install_cron.sh` | 安装/移除 crontab |
| `scripts/create_user.py` | 管理员创建用户（无注册功能） |
| `app/main.py` | FastAPI 入口，路由挂载，静态文件，禁缓存中间件 |
| `app/routers/auth.py` | 登录接口，bcrypt 验密 + JWT 签发 |
| `app/routers/stocks.py` | 行情 API（搜索、基本信息、日线+均线） |
| `app/routers/portfolio.py` | 持仓股 CRUD API |
| `app/routers/admin.py` | 监控页全部 API（状态/配置/执行/日志） |

## 环境变量文件

敏感配置统一放在 `/etc/stock/stock.env`（不提交 git）：

```
TUSHARE_TOKEN=...
DB_HOST=localhost
DB_PORT=5432
DB_NAME=stock
DB_USER=stock
DB_PASSWORD=...
JWT_SECRET=...
```

- `run.py` 启动时自动加载此文件
- `daily_update.py` 通过 `update_config.yaml` 的 `env_file` 字段加载

## 数据库主要表

| 表名 | 内容 |
|------|------|
| `stock_basic` | 股票基本资料 |
| `index_basic` | 指数基本资料 |
| `stock_daily` | 个股日线（含前/后复权） |
| `stock_daily_basic` | 每日市值/PE/PB 等指标 |
| `index_daily` | 指数日线 |
| `stock_weekly/monthly` | 周线/月线 |
| `kline_1/5/15/30/60min` | 分钟线 |
| `moneyflow_dc` | 个股资金流向（东财） |
| `moneyflow_ind_dc` | 板块资金流向 |
| `moneyflow_mkt_dc` | 大盘资金流向 |
| `broker_recommend` | 券商月度金股 |
| `users` | 用户账号（bcrypt 哈希密码） |
| `user_portfolio` | 用户持仓/自选股 |

## 定时任务调度

收盘后自动运行（周一至周五）：

| 阶段 | cron | 内容 |
|------|------|------|
| 基础列表 | 19:00 每工作日 | stock_basic、index_basic |
| 日线行情 | 19:10 每工作日 | index_daily、stock_daily、stock_daily_basic、moneyflow |
| 周线行情 | 19:00 每周五 | stock_weekly |
| 月线行情 | 20:00 月末5天 | stock_monthly |
| 券商金股 | 21:00 月初1~5日 | broker_recommend |

## 常见问题 & 解决记录

**端口 8000 占用**
```bash
ss -tlnp | grep 8000
kill -9 <pid>
```

**DB 连接报 `no password supplied`**
原因：环境变量未加载。`run.py` 已修复为自动读取 `/etc/stock/stock.env`。

**登录报密码错误**
- 不是 JWT 问题（bcrypt 验密与 JWT 无关）
- 检查 `users` 表是否有该用户，或重置密码：
  ```bash
  .venv/bin/python scripts/create_user.py --username xxx --password xxx
  ```

**Nginx 反代配置后页面无法访问**
原因：配置好 Nginx 后应访问 80 端口（`http://服务器IP`），不要直接访问 `:8000`。
排查：`ls /etc/nginx/sites-enabled/` → `sudo nginx -t` → `sudo systemctl status nginx`

**DataGrip 连不上数据库（连接超时）**
1. 云服务器安全组放行 TCP 5432
2. `sudo ufw allow 5432`
3. PostgreSQL `postgresql.conf` 中 `listen_addresses = '*'`
4. `pg_hba.conf` 中添加客户端 IP 授权
5. `sudo systemctl restart postgresql`

## 开发分支

`claude/tushare-index-data-06Kfi`

---

## 三个前端页面速查（2026-03-22）

### 页面路由

| URL | HTML | JS | 后端 Router |
|-----|------|----|-------------|
| `/login` | `login.html` | `login.js` | `auth.py` |
| `/portfolio` | `portfolio.html` | `portfolio.js` | `portfolio.py` |
| `/chart?code=…` | `chart.html` | `app.js` | `stocks.py` |
| `/admin` | `admin.html` | `admin.js` | `admin.py` |

所有页面共用 `style.css`（深色主题，红涨绿跌）。

---

### 持仓股页（portfolio）

**功能**：展示用户自选/持仓股列表，支持添加/删除，点击行跳行情页。

**前端关键点**
- `loadPortfolio()` → `GET /api/portfolio` → `renderPortfolio(items)` 渲染表格
- 添加：搜索弹层（`GET /api/stocks/search?q=…`）→ 选中 → `POST /api/portfolio`
- 删除：`DELETE /api/portfolio/{ts_code}`
- 表格列：代码 / 名称 / 现价 / 涨跌幅 / 成交量 / 换手率 / PE / 股息率 / 市值

**后端关键点**
- `GET /api/portfolio`：JOIN `stock_basic` + LATERAL 取 `stock_daily` / `stock_daily_basic` 最新一行
- 用户隔离：所有操作过滤 `user_id`（JWT payload）

---

### 行情页（chart）

**功能**：K 线图 + 成交量图，支持复权切换、8 条均线开关、6 档时间范围。

**前端关键点**
- 图表库：`lightweight-charts`（CandlestickSeries + HistogramSeries）
- 初始化：`initChart()` → `loadData(tsCode)`（一次性拉全量历史）
- 时间范围：前端 `applyVisibleRange()` 滑窗，不重新请求
- 复权切换：改 `currentAdj` → 重新 `loadData()`
- 均线开关：维护 `activeMA` Set → 切换 series 可见性
- 两图同步：`subscribeVisibleLogicalRangeChange` + `syncPriceScaleWidth()`
- 详情浮窗：crosshair move 事件，自适应左/右显示 OHLC、涨幅、成交量
- 阳线：红色 `#E04040`（空心）；阴线：绿色 `#45AA55`（实心）

**后端关键点（`stocks.py`）**
- `GET /api/stock/{ts_code}/daily?adj=qfq|hfq|`
  - 多取 ~400 日保证 MA250 计算完整
  - pandas 计算 MA5/10/15/20/30/60/120/250
  - 回退：无 stock_daily 数据时查 index_daily
  - 返回：`{candles, volume, ma, is_index}`
- `GET /api/stocks/search?q=…`
  - 指数：内存缓存 `_index_cache`，支持拼音缩写
  - 个股：DB ILIKE 查询 ts_code / name / cnspell
  - 返回前 20 项，指数优先

---

### 数据监控页（admin）

**功能**：查看定时任务执行状态、手动触发阶段、实时日志、编辑 cron 配置。

**前端关键点（`admin.js`）**
- 两个 Tab：「任务状态」/ 「系统配置」
- `renderStages(data)`：首次构建完整 DOM，后续轮询脏检查局部更新
  - 稳定 ID：`sc-{ssid}`（卡片）、`tr/td/tb/tt/tlb-{tid}`（任务行各元素）
  - 脏检查：`textContent`/`innerHTML`/`className` 值无变化则跳过写入
- `setupStageListeners()`：事件委托，单次注册，不随轮询重绑
- 自动刷新：30s 轮询；有任务运行中改 5s；`loadStatus(showSpinner)` 只有首次/手动刷新才显示 spinner
- 手动执行流程：
  1. 点「手动执行」→ `openTriggerModal`（按 date_type 显示日期/月份/无日期）
  2. 确认 → `POST /api/admin/run` → 启动后台进程
  3. `_triggerPollTimer` 每 2s 拉 `/api/admin/trigger-log/{stage}` 显示实时日志
  4. 完成后自动停止轮询
- 日志弹窗：`_logModalTimer` 运行中每 3s 刷新，atBottom 检查后自动滚底

**后端关键点（`admin.py`）**
- `GET /api/admin/status`：解析 `scheduler_YYYYMMDD.log` 提取事件 → 推断任务状态；`_get_latest_dates()` 查各表 MAX(trade_date)（60s 缓存）；`_resolve_task_date_range()` 解析 cmd 占位符展示日期范围
- `POST /api/admin/run`：`_running_procs` 防重复；后台 Popen 写 `trigger_*.log`
- `GET /api/admin/trigger-log/{stage}`：读最新 trigger log 末 80 行
- `GET /api/admin/log/{task}`：读任务日志末 50 行
- `PUT /api/admin/config`：更新 yaml，备份为 `.yaml.bak`

---

### 共用 API 端点速查

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/login` | 登录，返回 JWT token |
| GET | `/api/stocks/search?q=` | 搜索股票/指数（最多20条） |
| GET | `/api/stock/{code}/info` | 基本信息（stock_basic / index_basic） |
| GET | `/api/stock/{code}/daily?adj=` | 日线+均线（全量历史） |
| GET | `/api/portfolio` | 用户持仓列表（含最新行情） |
| POST | `/api/portfolio` | 添加持仓 |
| DELETE | `/api/portfolio/{code}` | 删除持仓 |
| GET | `/api/admin/status` | 今日任务状态树 |
| GET | `/api/admin/config` | 配置文件内容 |
| PUT | `/api/admin/config` | 更新配置 |
| POST | `/api/admin/run` | 手动触发阶段 |
| POST | `/api/admin/stop` | 停止执行中阶段 |
| GET | `/api/admin/trigger-log/{stage}` | 手动触发实时日志（末80行） |
| GET | `/api/admin/log/{task}` | 任务日志（末50行） |

---

## 已完成功能记录（2026-03-22）

### 数据更新监控页面（admin 页）

#### 关键文件
| 文件 | 说明 |
|------|------|
| `app/routers/admin.py` | 监控页所有 API（`/api/admin/*`） |
| `app/static/admin.js` | 监控页前端逻辑 |
| `app/static/style.css` | 监控页样式 |
| `scripts/daily_update.py` | 定时调度器，执行 pipeline.py 子进程 |

#### 功能列表

**1. 日志实时写入（`daily_update.py`）**
- 改 `subprocess.run(capture_output=True)` → `stdout=log_file, stderr=STDOUT`
- 设 `PYTHONUNBUFFERED=1`，子进程输出实时落盘
- 任务执行中点「查看日志」即可看到 pipeline.py 实时输出

**2. 消除页面刷新跳动（`admin.js` `renderStages`）**
- 不再 `innerHTML = ""`，改为局部 DOM 更新
- 每个阶段卡片稳定 ID 方案：`sc-{ssid}`
- 任务行稳定 ID：`tr-`, `td-`, `tb-`, `tt-`, `tlb-`（行/点/徽章/时间/日志按钮）
- 阶段徽章稳定 ID：`strig-`, `sstat-`, `slatd-`
- 首次渲染建完整 DOM，后续轮询只 `innerHTML` 更新动态字段

**3. 事件委托（`admin.js` `setupStageListeners`）**
- 不再在 `renderStages` 里每次重新绑定按钮事件
- 单次在容器上注册 click 委托，匹配 `.admin-btn-trigger` 和 `.task-log-btn`

**4. 日志弹窗自动刷新（`admin.js` `openLogModal`）**
- 任务运行中：每 3s 自动 fetch 日志、更新内容、保持滚动到底部
- 关闭弹窗时 `clearInterval` 停止刷新
- `_logModalTimer` 全局变量管理 timer

**5. 阶段最新数据日期（`admin.py` + `admin.js`）**
- `_get_latest_dates()`：一次性查 7 张表的 `MAX(date_col)`，60s 缓存
  - 涵盖 `index_daily`, `stock_daily`, `stock_daily_basic`, `moneyflow_dc`, `stock_weekly`, `stock_monthly`, `broker_recommend`
- `_stage_latest_date(stage, latest_dates)`：从阶段的代表性任务取最新日期
- status API 响应新增 `latest_date` 字段（阶段级）
- 前端：阶段标题栏绿色 badge 显示「最新 YYYY-MM-DD」，空时自动隐藏（`:empty`）

**6. 任务更新时间范围（`admin.py` + `admin.js`）**
- `_build_placeholders_adm()`：解析 `{today}`, `{week_monday}`, `{month_start}`, `{current_month}` 为实际日期
- `_resolve_task_date_range(cmd, placeholders)`：从 cmd 提取 `--start/--end/--date/--month`，返回可读字符串
  - 单日 → `2026-03-22`
  - 区间 → `2026-03-16 ~ 2026-03-22`
  - 月份 → `2026-03`
- status API 响应新增 `date_range` 字段（任务级）
- 前端：任务行名字旁灰色小 badge 展示本次更新范围

#### 注意事项
- `_get_latest_dates` 有 60s 缓存（`_date_cache`），DB 不可用时静默返回空 dict
- `renderStages` 的 `_sid(name)` 将中文/特殊字符替换为 `_`，确保合法 DOM ID
- 日志弹窗"滚动到底部"仅在用户未上翻时触发（检查 `atBottom`）
