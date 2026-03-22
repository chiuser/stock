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
| `app/routers/auth.py` | 登录接口，bcrypt 验密 + JWT 签发 |

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
