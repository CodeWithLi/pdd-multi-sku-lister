# 抖音（抖店）运营智能体平台

独立于上级仓库 `自动上架多sku` 的新项目，对标同级目录 `myTest`（拼多多）。

基于 **LangGraph** 编排 + **Playwright** 浏览器自动化，首期聚焦 **多规格上架**。

## 技术栈

| 层级 | 技术 |
|------|------|
| 编排 | LangGraph |
| LLM | LangChain ChatOpenAI（兼容 OpenAI API） |
| 浏览器 | Playwright (async 包装 + sync 线程执行) |
| API | FastAPI |
| 前端 | Vue 3 + Element Plus + Vite |
| 数据库 | MySQL（可选，店铺账号持久化） |
| 配置 | YAML + 环境变量 |

## 目录结构

```
dyTest/
├── README.md
├── STRUCTURE.md
├── requirements.txt
├── pyproject.toml
├── frontend/            # Vue 管理界面（端口 5175 → API 8020）
├── config/              # 店铺、浏览器、多规格默认值
├── skills/              # Markdown 业务知识（给 Agent / 人读）
├── data/                # 素材、浏览器 Profile、任务记录
├── scripts/             # 便捷脚本
├── tests/
└── src/dy_agent/        # 主代码包
```

## 架构分层

```
FastAPI (api/)
    ↓
Orchestrator Graph（自然语言 → 子任务，可选）
    ↓
Listing Graph（preflight → browser → report）
    ↓
Skills（确定性 Tool）
    ↓
Browser（Playwright）
    ↓
抖店商家后台 (fxg.jinritemai.com)
```

**原则**：LLM 负责理解意图与规划；目录解析、填表、上传由 Skill + Playwright 确定性执行。

## 快速开始

```bash
cd dyTest

# 1. 虚拟环境与依赖
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -e ".[dev]"

# 2. Playwright 浏览器
playwright install chromium

# 3. 配置
copy .env.example .env
copy config\settings.example.yaml config\settings.yaml
# 可选：在 .env 中设置 DATABASE_URL=mysql+pymysql://user:pass@127.0.0.1:3306/dy_agent

# 4. Dry-run（只跑 preflight，不打开浏览器）
python -m dy_agent.main plan --message "店铺A上架商品BD046A"
python -m dy_agent.main run listing --account store_A --product-code BD046A --dry-run

# 5. 启动 API
python -m dy_agent.main api --port 8020

# 6. 启动前端（另开终端）
cd frontend
npm install
npm run dev
# 浏览器打开 http://localhost:5175

# 7. 首次登录（手机验证码，验证码需手动输入）
python scripts/manual_login.py store_A
```

## 与 myTest（拼多多）的关系

| 维度 | myTest (PDD) | dyTest (抖音) |
|------|--------------|---------------|
| 商家后台 | mms.pinduoduo.com | fxg.jinritemai.com |
| 包名 | `pdd_agent` | `dy_agent` |
| 首期能力 | 全链路（上架/活动/推广等） | 先搭框架 + 上架骨架 |
| 素材结构 | 多规格目录 + Excel | 复用相似结构，页面逻辑后续分化 |

两项目**互不引用**，可共享运营素材目录（symlink 到上级 `多规格测试`）。

## 后续扩展

1. 完善 `skills/listing/upload.py` 抖店发布页填表
2. 按需增加 `delist`、`campaign` 子 Agent
3. 完善 Step2+ 规格填表、配件定价等能力
