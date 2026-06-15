#!/usr/bin/env bash
set -euo pipefail

# 等待 MySQL 就绪（docker-compose 健康检查后仍会再确认一次）
if [[ -n "${DATABASE_URL:-}" ]]; then
  echo "[entrypoint] waiting for database..."
  python - <<'PY'
import os, sys, time
from urllib.parse import urlparse

url = os.environ.get("DATABASE_URL", "")
if not url:
    sys.exit(0)

parsed = urlparse(url.replace("mysql+pymysql://", "mysql://", 1))
host = parsed.hostname or "mysql"
port = parsed.port or 3306

for i in range(60):
    try:
        import socket
        with socket.create_connection((host, port), timeout=2):
            print(f"[entrypoint] database {host}:{port} is reachable")
            break
    except OSError:
        time.sleep(2)
else:
    print("[entrypoint] database not reachable, starting anyway", file=sys.stderr)
PY
fi

exec "$@"
