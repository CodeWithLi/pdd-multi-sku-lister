# VMware Ubuntu Docker 部署教程

将 **PDD Agent Platform** 在 Ubuntu 虚拟机上以 Docker 分体式部署：

| 容器 | 职责 |
|------|------|
| `pdd-frontend` | Vue3 静态页 + Nginx，`/api` 反代到后端 |
| `pdd-backend` | FastAPI + LangGraph + Playwright |
| `pdd-mysql` | MySQL 8 持久化任务/账号数据 |

域名示例：`velunqwe.online`（你的 DNS 已托管在 **Cloudflare**）。

---

## 一、架构示意

```
浏览器
  │
  ├─ 方案 A：公网 IP ──► VM:80 ──► frontend(Nginx) ──► /api ──► backend:8000
  │                                              └──► MySQL
  │
  └─ 方案 B：Cloudflare Tunnel ──► cloudflared ──► frontend:80 ──► ...
```

- 前端与后端**各自独立 Dockerfile**，由 `docker-compose.yml` 编排。
- 对外只暴露前端 **80 端口**（或 Cloudflare Tunnel，无需开端口）。

---

## 二、VMware / Ubuntu 准备

### 2.1 虚拟机建议配置

| 项目 | 建议 |
|------|------|
| 系统 | Ubuntu 22.04 LTS 64 位 |
| 内存 | ≥ 4 GB（Playwright 建议 4 GB+） |
| 磁盘 | ≥ 40 GB |
| CPU | ≥ 2 核 |
| 网络 | NAT 或桥接均可（用 Tunnel 时 NAT 即可） |

### 2.2 安装 Docker

在 Ubuntu 虚拟机内：

```bash
cd /opt   # 或你打算放项目的目录
# 将项目拷入 VM 后：
sudo bash deploy/setup-ubuntu.sh

# 当前用户免 sudo 跑 docker（可选）
sudo usermod -aG docker $USER
newgrp docker
```

### 2.3 将项目传入 VM

任选一种：

```bash
# 方式 1：git clone（若仓库在远端）
git clone <你的仓库地址> pdd-agent
cd pdd-agent/myTest

# 方式 2：从 Windows 主机 scp
# scp -r D:\job\自动上架多sku\myTest user@<VM_IP>:/opt/pdd-agent
```

---

## 三、配置

### 3.1 环境变量

```bash
cd /opt/pdd-agent/myTest   # 进入项目根目录

cp .env.docker.example .env
nano .env
```

**务必修改**：

```env
MYSQL_ROOT_PASSWORD=你的强密码
MYSQL_PASSWORD=你的强密码
LLM_API_KEY=你的大模型Key
PLAYWRIGHT_HEADLESS=true
HTTP_PORT=80
```

### 3.2 业务配置 settings.yaml

```bash
cp config/settings.docker.example.yaml config/settings.yaml
nano config/settings.yaml
```

填写店铺账号、`delist.min_created_after` 等。路径均相对容器内 `/app`，已通过 volume 映射到宿主机 `./data`、`./config`。

### 3.3 商品素材

把素材放到宿主机（会挂载进容器）：

```text
myTest/data/assets/商品上架规格文件/...
myTest/data/assets/拼多多所有商品.xls
```

可从 Windows 开发机直接复制整个 `data/assets` 目录到 VM。

### 3.4 初始化目录与权限

```bash
bash deploy/init-dirs.sh
```

Playwright 容器以 `uid=1000` 运行，需保证 `data/`、`config/` 可写，脚本会自动 `chown`。

---

## 四、构建与启动

### 4.1 一键启动（推荐）

```bash
docker compose up -d --build
```

查看状态：

```bash
docker compose ps
docker compose logs -f backend
```

### 4.2 分开构建（前后端独立镜像）

```bash
# 仅构建后端
docker build -f docker/backend/Dockerfile -t pdd-backend:local .

# 仅构建前端
docker build -f docker/frontend/Dockerfile -t pdd-frontend:local .
```

仍建议用 `docker compose up` 统一拉起 MySQL 与网络。

### 4.3 验证

在 VM 内：

```bash
curl http://127.0.0.1/api/health
# {"status":"ok","service":"pdd-agent-platform",...}

curl -I http://127.0.0.1/
# HTTP/1.1 200
```

浏览器访问：`http://<VM局域网IP>/`

---

## 五、域名 velunqwe.online 接入

你的域名注册在腾讯云，但 **DNS 解析在 Cloudflare**（`emely.ns.cloudflare.com` / `rayden.ns.cloudflare.com`），因此请在 [Cloudflare Dashboard](https://dash.cloudflare.com) 操作，而不是腾讯云 DNS 面板。

推荐使用子域名，例如：**`pdd.velunqwe.online`**

---

### 方案 A：有公网 IP + 路由器端口映射（简单直接）

**适用**：家庭/公司宽带有公网 IP，能在路由器把 **80/443** 映射到 VM。

1. VMware 网络设为 **桥接**，或 NAT + 端口转发到 VM。
2. 查 VM IP：`ip a`（桥接时用局域网 IP；若公网直达则用公网 IP）。
3. Cloudflare → DNS → 添加记录：

   | 类型 | 名称 | 内容 | 代理 |
   |------|------|------|------|
   | A | `pdd` | `<你的公网IP>` | 已代理（橙色云） |

4. Cloudflare → SSL/TLS → 加密模式选 **灵活**（源站仅 HTTP:80）或 **完全**（源站需 HTTPS，见方案 A+）。

5. 访问：`https://pdd.velunqwe.online`

**方案 A+：源站 HTTPS（可选）**

在 VM 上用 Certbot 为 Nginx 申请证书，需将 Cloudflare SSL 改为 **完全（严格）**。可后续再加 `docker/nginx-ssl` 层，初期用「灵活」即可。

---

### 方案 B：Cloudflare Tunnel（推荐，无需公网 IP）

**适用**：VMware NAT、无公网 IP、不想折腾路由器。

#### B.1 在 Cloudflare 创建 Tunnel

1. 登录 Cloudflare → **Zero Trust** → **Networks** → **Tunnels** → **Create a tunnel**。
2. 名称填 `pdd-agent`，选择 **Docker** 安装方式。
3. 复制页面上的 **Tunnel Token**（一长串）。
4. 添加 **Public Hostname**：
   - Subdomain：`pdd`
   - Domain：`velunqwe.online`
   - Service Type：`HTTP`
   - URL：`frontend:80`（注意：在 compose 网络里用服务名，不是 localhost）

#### B.2 写入 Token 并启动

```bash
# 在 .env 追加
echo "CLOUDFLARE_TUNNEL_TOKEN=粘贴你的Token" >> .env

# 带 Tunnel 启动
docker compose -f docker-compose.yml -f docker/cloudflared/docker-compose.cloudflared.yml up -d --build
```

#### B.3 访问

打开：`https://pdd.velunqwe.online`（Cloudflare 自动 HTTPS，无需在 VM 开端口）。

---

### 方案 C：根域名 velunqwe.online 直接访问

若希望不用子域名，在 Cloudflare DNS 添加：

| 类型 | 名称 | 内容 |
|------|------|------|
| A | `@` | 公网 IP（方案 A） |

或通过 Tunnel 的 Public Hostname 使用 `@` + `velunqwe.online`。

> 若根域名已有其他网站，请用子域名 `pdd.` 避免冲突。

---

## 六、首次使用 checklist

1. **打开控制台** → 系统设置：确认素材路径、默认价格等。
2. **店铺设置** → 填写拼多多账号（或导入已有 `settings.yaml`）。
3. **登录体检** → 在 VM 无图形界面时，Playwright 以 headless 登录；若需扫码，可临时：
   ```bash
   # 在 .env 设 PLAYWRIGHT_HEADLESS=false 并挂载 X11（高级，一般建议本机登录后复制 profile）
   ```
   更稳妥：在 Windows 本机登录一次，将 `data/profiles/store_A` 复制到 VM 的 `myTest/data/profiles/`。
4. **素材检查** → 选商品编码做 preflight。
5. **上架任务** → 先 dry-run，再正式上架。

---

## 七、常用运维命令

```bash
# 查看日志
docker compose logs -f backend
docker compose logs -f frontend

# 重启
docker compose restart backend frontend

# 停止
docker compose down

# 停止并删除数据库卷（慎用！会清空 MySQL）
docker compose down -v

# 进入后端容器
docker compose exec backend bash

# 重新构建仅后端
docker compose up -d --build backend
```

---

## 八、目录与数据持久化

| 宿主机路径 | 容器路径 | 说明 |
|------------|----------|------|
| `./data` | `/app/data` | 素材、浏览器 Profile、运行截图 |
| `./config` | `/app/config` | settings.yaml |
| `mysql_data` 卷 | MySQL 数据 | 账号、任务队列、失败记录 |

**备份建议**：定期备份 `data/`、`config/settings.yaml` 和 MySQL 卷。

---

## 九、故障排查

| 现象 | 处理 |
|------|------|
| `backend` 一直 restarting | `docker compose logs backend`；检查 MySQL 密码是否与 `.env` 一致 |
| `/api/health` 502 | 后端未就绪，`docker compose ps` 看 health 状态 |
| Playwright 崩溃 / 超时 | 确认 `shm_size: 1gb` 已生效；内存是否 ≥ 4GB |
| 登录失败 | 复制本机 `data/profiles/<店铺>` 到 VM；或检查账号密码 |
| 域名无法访问 | Cloudflare DNS 是否「已代理」；Tunnel Token 是否有效；路由器是否映射 80 端口 |
| 素材找不到 | 确认 `data/assets` 已挂载，`settings.yaml` 中 `paths.assets_root` 正确 |

---

## 十、文件清单

```text
myTest/
├── docker-compose.yml              # 主编排（mysql + backend + frontend）
├── .env.docker.example             # 环境变量模板
├── docker/
│   ├── backend/Dockerfile          # 后端镜像
│   ├── backend/entrypoint.sh
│   ├── frontend/Dockerfile         # 前端镜像
│   ├── frontend/nginx.conf         # Nginx 反代 /api
│   └── cloudflared/                # 可选：Cloudflare Tunnel
├── config/settings.docker.example.yaml
└── deploy/
    ├── DEPLOY.md                   # 本教程
    └── setup-ubuntu.sh             # 安装 Docker
```

---

## 十一、安全提示

1. **不要**把 `.env`、`config/settings.yaml`（含店铺密码）提交到 git。
2. 生产环境请修改 MySQL 默认密码。
3. 若用公网暴露，建议在 Cloudflare 开启 **WAF**、限制来源 IP，或加简单认证。
4. `LLM_API_KEY` 仅在后端容器内使用，不会暴露给浏览器。

---

完成以上步骤后，即可通过 **`https://pdd.velunqwe.online`**（或你配置的域名）使用整套拼多多运营控制台。
