# PDD Ops Agent Platform

独立于上级仓库 `自动上架多sku` 的新项目：基于 **LangGraph** 编排 + **Playwright** 浏览器自动化。

上级项目的 `pdd_auto/`、`multi_spec_main.py` 等**不会被引用或修改**；后续可从旧项目迁移业务逻辑到本项目的 `skills/` 层。

## 技术栈

| 层级 | 技术 |
|------|------|
| 编排 | LangGraph |
| LLM 接入 | LangChain ChatOpenAI（兼容 OpenAI API 的厂商） |
| 浏览器 | Playwright (async) |
| API（预留 Vue3） | FastAPI |
| 配置 | YAML + 环境变量 |

## 目录结构

```
myTest/
├── README.md
├── pyproject.toml
├── .env.example
├── .gitignore
│
├── config/                      # 静态配置模板（不含密钥）
│   ├── settings.example.yaml
│   └── agents.example.yaml
│
├── skills/                      # Markdown Skill（给 Agent 读的业务知识）
│   ├── listing/
│   ├── delist/
│   └── browser/
│
├── data/                        # 运行时数据（任务记录、素材路径等）
│   ├── assets/                  # 商品素材根目录（可 symlink 到上级 多规格测试）
│   ├── profiles/                # Playwright 浏览器 Profile（按店铺隔离）
│   └── runs/                    # 任务执行记录 JSON
│
├── scripts/                     # 便捷脚本
│   └── run_graph.py
│
├── tests/
│   ├── conftest.py
│   └── unit/
│
└── src/pdd_agent/               # 主代码包
    ├── main.py                  # CLI 入口
    ├── core/                    # 配置、日志、异常
    ├── domain/                  # 领域模型（纯数据结构）
    ├── llm/                     # LLM 工厂
    ├── browser/                 # Playwright 会话与 Page Object
    ├── skills/                  # 可调用 Skill（Tool 实现）
    ├── agents/                  # LangGraph 图与子 Agent
    │   ├── state.py
    │   ├── orchestrator/        # 总编排（自然语言 → 子任务）
    │   ├── listing/             # 上架子图
    │   └── delist/              # 下架子图（占位）
    ├── storage/                 # 任务持久化
    ├── prompts/                 # Agent 系统提示词
    └── api/                     # FastAPI（后续接 Vue3）
```

## 架构分层

```
Vue3 (后续)
    ↓ HTTP / WebSocket
FastAPI (api/)
    ↓
Orchestrator Graph (agents/orchestrator/)
    ↓ 路由到子图
Listing Graph / Delist Graph / Campaign Graph ...
    ↓ 调用
Skills (skills/) ──→ Playwright (browser/)
    ↓
拼多多商家后台
```

**原则**：LLM 负责「理解意图 + 规划 + 异常决策」；目录解析、填表、上传等由 Skill + Playwright 确定性执行。

## 快速开始

```bash
cd myTest

# 1. 创建虚拟环境并安装
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -e ".[dev]"

# 2. 安装 Playwright 浏览器
playwright install chromium

# 3. 复制配置
copy .env.example .env
copy config\settings.example.yaml config\settings.yaml

# 4. Dry-run（不打开浏览器，只跑 LangGraph 规划 + 素材校验）
python -m pdd_agent.main plan --message "店铺A上架商品BD046A"

# 5. 执行上架子图（需要登录配置）
python -m pdd_agent.main run listing --account store_A --product-code BD046A --dry-run
```

## 扩展新模块（活动 / 推流）

1. 在 `skills/campaign/` 写 Playwright 操作与 `@tool`
2. 在 `agents/campaign/graph.py` 新建 LangGraph 子图
3. 在 `agents/orchestrator/nodes.py` 注册路由
4. 在 `skills/campaign/*.md` 补充页面规则

## 与旧项目关系

| 旧项目 | 新项目对应 |
|--------|------------|
| `catalog.py` | `skills/listing/catalog.py` |
| `multi_spec_runner.py` | `agents/listing/graph.py` + `skills/listing/` |
| `DrissionPage` | `browser/` Playwright |
| `Streamlit app.py` | `api/` + 未来 Vue3 |
| `agent_gateway.py` | `agents/orchestrator/` |
