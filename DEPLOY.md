# 部署指南

## 启动服务

```bash
.venv/bin/python run.py
```

## 常见问题

### 端口 8000 已被占用

**报错信息：**
```
ERROR:    [Errno 98] Address already in use
```

**排查占用端口的进程：**
```bash
ss -tlnp | grep 8000
```

**杀掉占用进程（替换为实际 PID）：**
```bash
kill -9 <pid1> <pid2> <pid3>
```

**示例：**
```bash
# 查看占用情况
ss -tlnp | grep 8000
# LISTEN ...  users:(("python",pid=1327747,...),("python",pid=1327746,...),("python",pid=1327744,...))

# 杀掉进程
kill -9 1327747 1327746 1327744
```

然后重新运行：
```bash
.venv/bin/python run.py
```
