#!/usr/bin/env bash
# 初始化宿主机目录并修正 Playwright 容器用户 (uid=1000) 的写权限
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

mkdir -p data/assets data/profiles data/runs config

if [[ ! -f config/settings.yaml ]]; then
  cp config/settings.docker.example.yaml config/settings.yaml
  echo "[init] 已生成 config/settings.yaml"
fi

if [[ ! -f .env ]]; then
  cp .env.docker.example .env
  echo "[init] 已生成 .env，请编辑其中的密码与 LLM_API_KEY"
fi

# pwuser in Playwright image is uid 1000
if command -v sudo >/dev/null 2>&1; then
  sudo chown -R 1000:1000 data config 2>/dev/null || chown -R 1000:1000 data config 2>/dev/null || true
fi

echo "[init] 完成。下一步: nano .env && docker compose up -d --build"
