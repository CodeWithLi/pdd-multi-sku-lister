#!/usr/bin/env bash
# Ubuntu 22.04+ 一键安装 Docker 与 Compose 插件
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "请使用 sudo 运行: sudo bash deploy/setup-ubuntu.sh"
  exit 1
fi

apt-get update
apt-get install -y ca-certificates curl gnupg

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  > /etc/apt/sources.list.d/docker.list

apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

systemctl enable --now docker

echo ""
echo "Docker 安装完成："
docker --version
docker compose version
echo ""
echo "建议将当前用户加入 docker 组："
echo "  sudo usermod -aG docker \$USER"
echo "  newgrp docker"
