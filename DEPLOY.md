# 部署指南

## 环境要求

- Python 3.11+
- PostgreSQL 12+
- Tushare Pro 账号（需有足够积分）

---

## 一、克隆代码

```bash
git clone <仓库地址>
cd stock
```

---

## 二、创建虚拟环境并安装依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## 三、配置 PostgreSQL 数据库

### 3.1 创建数据库和用户

```sql
-- 以 postgres 超级用户登录后执行
CREATE DATABASE stock;
CREATE USER stockuser WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE stock TO stockuser;
```

### 3.2 初始化表结构

```bash
psql -h localhost -U stockuser -d stock -f db/schema.sql
```

---

## 四、配置环境变量

可以直接修改 `config.py`，也可以通过环境变量覆盖（推荐后者，避免密码提交到代码仓库）：

```bash
export TUSHARE_TOKEN=你的tushare_token
export DB_HOST=localhost
export DB_PORT=5432
export DB_NAME=stock
export DB_USER=stockuser
export DB_PASSWORD=your_password
```

或者写入文件（供定时任务使用）：

```bash
# 创建 /etc/stock/stock.env
cat > /etc/stock/stock.env <<EOF
TUSHARE_TOKEN=你的tushare_token
DB_HOST=localhost
DB_PORT=5432
DB_NAME=stock
DB_USER=stockuser
DB_PASSWORD=your_password
EOF
```

---

## 五、创建系统用户

本系统无注册功能，用户由管理员通过脚本添加：

```bash
.venv/bin/python scripts/create_user.py --username admin --password yourpassword
```

---

## 六、启动 Web 服务

```bash
.venv/bin/python run.py
```

服务默认监听 `0.0.0.0:8000`，启动后访问 `http://服务器IP:8000`。

---

## 七、配置定时数据更新

### 7.1 修改更新配置

编辑 `scripts/update_config.yaml`，至少修改以下两项：

```yaml
global:
  project_root: /home/user/stock          # 改为实际绝对路径
  python: .venv/bin/python                # 改为虚拟环境的 Python 路径
  env_file: /etc/stock/stock.env          # 取消注释并填写环境变量文件路径
```

### 7.2 预览将要安装的 cron 任务

```bash
bash scripts/install_cron.sh --show
```

### 7.3 安装定时任务

```bash
bash scripts/install_cron.sh
```

默认调度时间（周一至周五收盘后自动运行）：

| 阶段 | 时间 | 触发条件 | 内容 |
|------|------|----------|------|
| 基础列表 | 19:00 | 每个工作日 | stock_basic、index_basic |
| 日线行情 | 19:10 | 每个工作日 | index_daily、stock_daily、stock_daily_basic、moneyflow |
| 周线行情 | 19:00 | 每周五 | stock_weekly |
| 月线行情 | 20:00 | 每月最后5天 | stock_monthly |
| 券商金股 | 21:00 | 每月1~5日 | broker_recommend |

### 7.4 手动触发更新

```bash
# 查看所有阶段今日触发状态
.venv/bin/python scripts/daily_update.py --list

# 模拟执行（不实际运行）
.venv/bin/python scripts/daily_update.py --dry-run

# 手动执行指定阶段
.venv/bin/python scripts/daily_update.py --stage 基础列表
.venv/bin/python scripts/daily_update.py --stage 日线行情

# 移除定时任务
bash scripts/install_cron.sh --remove
```

---

## 八、常见问题

### 端口 8000 已被占用

**报错：**
```
ERROR:    [Errno 98] Address already in use
```

**排查并杀掉占用进程：**
```bash
ss -tlnp | grep 8000
# 找到 PID 后执行（替换为实际 PID）
kill -9 <pid1> <pid2> <pid3>
```

然后重新运行：
```bash
.venv/bin/python run.py
```

### 数据库连接失败

检查 PostgreSQL 是否启动，以及 `config.py` 或环境变量中的连接参数是否正确：

```bash
psql -h $DB_HOST -U $DB_USER -d $DB_NAME
```

### Tushare 接口报错

- 确认 `TUSHARE_TOKEN` 已正确设置
- 确认账号积分是否充足（部分接口有积分要求）
- 访问 [tushare.pro](https://tushare.pro) 查看账号状态

### 配置了 Nginx 反向代理后页面无法访问

**症状：** 配置好 Nginx 后仍然无法访问页面。

**原因：** 混淆了访问端口——配置 Nginx 反代后，应访问 **80 端口**（`http://服务器IP`），而非直接访问 FastAPI 的 `8000` 端口。

**排查步骤：**
```bash
# 1. 确认 sites-enabled 中有配置文件
ls /etc/nginx/sites-enabled/

# 2. 语法检查
sudo nginx -t

# 3. 确认 nginx 正在运行
sudo systemctl status nginx

# 4. 确认 stock 服务监听在 127.0.0.1:8000
sudo systemctl status stock
```

**正确访问方式：** `http://服务器IP`（不带端口号，走 80 → nginx → 8000）
