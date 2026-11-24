#!/usr/bin/env python3
"""车库管家 · 启动入口。

端口与数据目录的解析顺序：
  命令行参数 > 环境变量 GARAGE_PORT / GARAGE_DATA > 配置文件 garage.conf > 默认值
"""
import argparse
import os
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import api  # noqa: E402
import store  # noqa: E402


def read_conf():
    """读取 etc/garage.conf（由安装向导写入），键值对格式。"""
    candidates = []
    etc_dir = os.environ.get("TRIM_PKGETC")
    if etc_dir:
        candidates.append(os.path.join(etc_dir, "garage.conf"))
    candidates.append(os.path.join(os.path.dirname(HERE), "..", "etc", "garage.conf"))
    conf = {}
    for path in candidates:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    conf[key.strip()] = value.strip()
            break
        except OSError:
            continue
    return conf


def main(argv=None):
    conf = read_conf()

    default_port = (
        os.environ.get("GARAGE_PORT")
        or os.environ.get("TRIM_SERVICE_PORT")
        or conf.get("port")
        or "8787"
    )
    parser = argparse.ArgumentParser(description="车库管家 · 车辆保养与能耗管理")
    parser.add_argument("--host", default=os.environ.get("GARAGE_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(default_port))
    parser.add_argument("--data", default=None, help="数据目录（默认取 TRIM_PKGVAR）")
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--check", action="store_true", help="仅初始化数据库并校验环境")
    parser.add_argument("--bootstrap-admin", action="store_true", help="仅初始化管理员账号（安装脚本使用）")
    parser.add_argument("--reset-password", action="store_true", help="重置账号密码（管理员找回密码用）")
    parser.add_argument("--user", default="", help="配合 --reset-password 指定账号，默认 admin")
    args = parser.parse_args(argv)

    if args.version:
        print(api.APP_VERSION)
        return 0

    if args.data:
        store.DATA_DIR = Path(args.data)
        store.DB_PATH = store.DATA_DIR / "garage.db"

    bootstrap = (conf.get("admin_user") or "", conf.get("admin_pass") or "")

    if args.bootstrap_admin:
        store.init_db(bootstrap)
        with store.get_conn() as conn:
            total = store.count_users(conn)
            row = conn.execute(
                "SELECT username, role, must_change FROM users ORDER BY id LIMIT 1"
            ).fetchone()
        print(f"ok users={total} admin={row['username'] if row else '-'}"
              f" must_change={row['must_change'] if row else '-'}")
        return 0

    if args.reset_password:
        import secrets as _secrets
        store.init_db(bootstrap)
        username = (args.user or bootstrap[0] or "admin").strip()
        password = (os.environ.get("GARAGE_ADMIN_PASS") or bootstrap[1] or _secrets.token_urlsafe(9))
        with store.get_conn() as conn:
            row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
            if not row:
                print(f"error: 账号不存在 {username}")
                return 1
            store.set_password(conn, row["id"], password, 0)
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (row["id"],))
        print(f"ok reset user={username} password={password}")
        return 0

    if args.check:
        store.init_db(bootstrap)
        print(f"ok version={api.APP_VERSION} data={store.DATA_DIR} db={store.DB_PATH}")
        return 0

    api.serve(args.host, args.port, bootstrap)
    return 0


if __name__ == "__main__":
    sys.exit(main())
