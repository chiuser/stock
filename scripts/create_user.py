#!/usr/bin/env python3
"""
创建用户脚本（内部管理工具，无注册功能）

用法：
  python scripts/create_user.py --username alice --password secret123
  python scripts/create_user.py --username bob   --password secret456
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import bcrypt
from db import get_conn


def create_user(username: str, password: str, is_admin: bool = False) -> None:
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    with get_conn() as conn:
        with conn.cursor() as cur:
            try:
                # 管理员权限在数据库中持久化，避免只靠前端或初始 token 区分角色。
                cur.execute(
                    """
                    INSERT INTO users (username, password_hash, is_admin)
                    VALUES (%s, %s, %s)
                    RETURNING id
                    """,
                    (username, password_hash, is_admin),
                )
                user_id = cur.fetchone()[0]
                conn.commit()
                role = "管理员" if is_admin else "普通用户"
                print(f"[OK] 用户 '{username}' 已创建，id={user_id}，角色={role}")
            except Exception as e:
                conn.rollback()
                print(f"[ERROR] 创建失败：{e}")
                sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="添加行情系统用户")
    parser.add_argument("--username", required=True, help="用户名（最长32字符）")
    parser.add_argument("--password", required=True, help="明文密码（将自动哈希存储）")
    parser.add_argument("--admin", action="store_true", help="创建为管理员账号")
    args = parser.parse_args()

    if len(args.username) > 32:
        print("[ERROR] 用户名不能超过32个字符")
        sys.exit(1)
    if len(args.password) < 4:
        print("[ERROR] 密码至少4个字符")
        sys.exit(1)

    create_user(args.username, args.password, is_admin=args.admin)


if __name__ == "__main__":
    main()
