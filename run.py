"""启动 Stock Charts Web 服务。"""
import os
from pathlib import Path
import uvicorn


def _load_env_file(path: str) -> None:
    p = Path(path)
    if not p.exists():
        return
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())


if __name__ == "__main__":
    _load_env_file("/etc/stock/stock.env")
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
