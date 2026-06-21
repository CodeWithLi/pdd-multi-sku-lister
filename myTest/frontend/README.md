# PDD Agent 前端（Vue3）

独立 Vue3 控制台，对接 `myTest` 内 FastAPI，**不依赖**上级 Streamlit。

## 技术栈

- Vue 3 + TypeScript + Vite
- Vue Router
- Element Plus
- Axios

## 启动

**1. 后端（另一个终端）**

```powershell
cd D:\job\自动上架多sku\myTest
.\.venv\Scripts\Activate.ps1
python -m pdd_agent.main api --port 8010
```

**2. 前端**

```powershell
cd D:\job\自动上架多sku\myTest\frontend
npm install
npm run dev
```

浏览器打开：http://localhost:5173（或 http://127.0.0.1:5173，需 Vite 开启 `host: true`）

Vite 已将 `/api` 代理到 `http://127.0.0.1:8010`。

飞书 OAuth 回调走 **后端** `http://127.0.0.1:8010/api/feishu/oauth/callback`（需在飞书开放平台「安全设置 → 重定向 URL」里添加同地址）。授权完成后返回前端即可，无需 5173 在回调瞬间必须在线。

## 页面

| 路由 | 功能 |
|------|------|
| `/` | 总览：服务状态、店铺、路径配置 |
| `/catalog` | 素材校验 preflight |
| `/tasks` | AI 规划 + 上架任务 |
| `/runs` | 运行记录与 JSON 详情 |

## 构建

```powershell
npm run build
npm run preview
```
