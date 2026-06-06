# 目录结构说明

本文件是 `myTest/` 新项目的完整目录树与职责说明。

```
myTest/
│
├── README.md                          # 项目说明、快速开始
├── STRUCTURE.md                       # 本文件
├── pyproject.toml                     # 依赖与打包
├── .env.example                       # 环境变量模板
├── .gitignore
│
├── config/                            # 配置（复制 example 后本地使用）
│   ├── settings.example.yaml          # 店铺、路径、浏览器、多规格默认值
│   └── agents.example.yaml            # 各 Agent 开关与描述
│
├── skills/                            # Markdown Skill（供 Agent / 人阅读）
│   ├── listing/multi_spec.md
│   ├── delist/rules.md
│   └── browser/pdd_login.md
│
├── data/                              # 运行时数据（不进 git 的内容可放这里）
│   ├── assets/                        # 商品素材（可 symlink 到 ../多规格测试）
│   ├── profiles/                      # Playwright storage_state 按店铺隔离
│   └── runs/                          # 任务 JSON 记录
│
├── scripts/
│   └── run_graph.py                   # CLI 快捷入口
│
├── tests/
│   ├── conftest.py
│   └── unit/
│       └── test_catalog.py
│
└── src/pdd_agent/                     # Python 主包
    │
    ├── main.py                        # CLI: plan | run | api
    ├── paths.py                       # 路径常量
    │
    ├── core/                          # 基础设施
    │   ├── config.py                  # YAML + .env 配置
    │   ├── logging.py
    │   └── exceptions.py
    │
    ├── domain/                        # 纯领域模型（无框架依赖）
    │   ├── enums.py                   # AgentKind, RunStatus, TaskPhase
    │   └── models.py                  # ListingUnit, PlannedTask, RunRecord
    │
    ├── llm/                           # LangChain LLM 工厂
    │   └── factory.py
    │
    ├── browser/                       # Playwright 层
    │   ├── manager.py                 # Browser 进程 + Context 池
    │   ├── session.py                 # 登录会话
    │   └── pages/                     # Page Object（按页面拆分）
    │       └── base.py
    │
    ├── skills/                        # 可调用 Skill（LangChain Tool）
    │   ├── base.py                    # Skill 抽象 + Registry
    │   ├── registry.py
    │   ├── listing/
    │   │   ├── catalog.py             # 目录 + Excel 解析（确定性）
    │   │   └── preflight.py           # 上架前校验
    │   ├── delist/                    # 下架（待实现）
    │   └── campaign/                  # 活动（待实现）
    │
    ├── agents/                        # LangGraph 图
    │   ├── state.py                   # TypedDict 状态
    │   ├── orchestrator/              # 总编排：自然语言 → PlannedTask[]
    │   │   └── graph.py
    │   ├── listing/                   # 上架子图
    │   │   ├── graph.py               # preflight → browser → report
    │   │   └── nodes.py               # Playwright 填表节点（待迁移）
    │   └── delist/
    │       └── graph.py               # 占位
    │
    ├── prompts/                       # Agent 系统提示词
    │   └── orchestrator.md
    │
    ├── storage/
    │   └── task_store.py              # 运行记录 JSON
    │
    └── api/                           # FastAPI（后续接 Vue3）
        ├── app.py
        └── routes/
            ├── health.py
            └── tasks.py
```

## 后续扩展位

| 新模块 | 新增目录 |
|--------|----------|
| 活动上传 | `skills/campaign/` + `agents/campaign/graph.py` |
| 推广投流 | `skills/traffic/` + `agents/traffic/graph.py` |
| Vue3 前端 | 仓库外或 `myTest/frontend/` |
| 页面操作 | `browser/pages/listing_*.py` + `agents/listing/nodes.py` |

## 数据流

```
用户指令 / Vue3 API
       ↓
agents/orchestrator/graph.py     ← LLM 规划
       ↓ PlannedTask
agents/listing/graph.py          ← LangGraph 状态机
       ↓ 调用
skills/listing/*                 ← 确定性 Tool
       ↓
browser/* (Playwright)           ← 页面执行
```
