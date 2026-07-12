# 目录结构说明

```
dyTest/
│
├── README.md
├── STRUCTURE.md
├── pyproject.toml
├── .env.example
├── .gitignore
│
├── config/
│   ├── settings.example.yaml
│   └── agents.example.yaml
│
├── skills/                            # Markdown Skill（业务知识文档）
│   ├── listing/multi_spec.md
│   └── browser/douyin_login.md
│
├── data/
│   ├── assets/                        # 商品素材
│   ├── profiles/                      # Playwright Profile（按店铺隔离）
│   └── runs/                          # 任务 JSON 记录
│
├── scripts/
│   └── run_graph.py
│
├── tests/
│   ├── conftest.py
│   └── unit/
│
└── src/dy_agent/
    ├── main.py                        # CLI: plan | run | api
    ├── paths.py
    ├── core/                          # 配置、日志、异常
    ├── domain/                        # 领域模型
    ├── llm/                           # LLM 工厂
    ├── browser/                       # Playwright 会话
    ├── skills/                        # 可调用 Skill（Python）
    ├── agents/                        # LangGraph 子图
    ├── storage/                       # 任务持久化（JSON）
    ├── prompts/                       # Agent 提示词
    └── api/                           # FastAPI
```

## 数据流（上架）

```
CLI / API
    ↓
agents/listing/graph.py
    preflight → browser → report
    ↓
skills/listing/catalog.py      # 解析素材目录
skills/listing/preflight.py    # 校验
skills/listing/upload.py       # 浏览器填表（待实现）
    ↓
browser/sync_job.py            # Playwright 执行
```
