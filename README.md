# stock

股票数据抓取、调度与 Web 查看工具。

## 运行模式

项目支持两种常见使用方式：

- 本地开发机：运行 Web 服务做调试，连接远程数据库。
- 远程服务器：运行正式 Web 服务和定时任务。

## 1. 安装依赖

```bash
cd /path/to/stock
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. 环境变量

至少需要这些变量：

```env
TUSHARE_TOKEN=your_tushare_token
JWT_SECRET=your_random_secret
DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=stock
DB_USER=postgres
DB_PASSWORD=your_password
```

### 本地开发

建议在仓库根目录创建 `.env.local`：

```env
TUSHARE_TOKEN=your_tushare_token
JWT_SECRET=dev_local_secret
DB_HOST=your.remote.db.host
DB_PORT=5432
DB_NAME=stock
DB_USER=postgres
DB_PASSWORD=your_password
```

启动 Web：

```bash
cd /path/to/stock
source .venv/bin/activate
export STOCK_ENV_FILE=/path/to/stock/.env.local
export STOCK_RELOAD=true
python run.py
```

说明：

- `STOCK_ENV_FILE` 用来指定本地开发环境文件。
- `STOCK_RELOAD=true` 只建议在本地开发时开启。

本地如需手工跑调度器，可使用本地配置模板：

```bash
python scripts/daily_update.py --config scripts/update_config.local.yaml --list
python scripts/daily_update.py --config scripts/update_config.local.yaml --dry-run
```

### 远程服务器

建议把环境文件放在：

```text
/etc/stock/stock.env
```

然后直接启动：

```bash
cd /home/user/stock
source .venv/bin/activate
python run.py
```

如果不设置 `STOCK_ENV_FILE`，`run.py` 会自动尝试读取 `/etc/stock/stock.env`。

定时任务配置请使用：

```text
scripts/update_config.yaml
```

其中至少要确认这些字段是实际部署值：

- `global.project_root`
- `global.python`
- `global.log_dir`
- `global.env_file`

## 3. 数据库初始化

新库或升级库时执行：

```bash
psql -U postgres -d stock -f db/schema.sql
```

## 4. 创建管理员账号

后台页面 `/admin` 仅管理员可访问。

```bash
python scripts/create_user.py --username admin --password your_password --admin
```

## 5. 常用命令

初始化基础数据：

```bash
python pipeline.py --table stock_basic
python pipeline.py --table index_basic
```

查看调度计划：

```bash
python scripts/daily_update.py --list
```

本地开发配置查看：

```bash
python scripts/daily_update.py --config scripts/update_config.local.yaml --list
```
