# 拼多多多店铺 SKU 自动上架 / 下架

## 项目结构

```
自动上架多sku/
├── app.py                 # Streamlit 控制台（启动入口）
├── main.py                # 批量上架 CLI
├── delist_main.py         # 批量下架 CLI
├── agent_gateway.py       # AI 自然语言指令入口
├── config.json            # 店铺与商品配置
├── pdd_auto/              # 核心业务包
│   ├── paths.py           # 路径常量
│   ├── config.py          # 配置读写
│   ├── browser/           # 浏览器登录
│   ├── listing/           # 上架自动化
│   ├── delist/            # 下架自动化
│   ├── ai/                # GLM 标题生成
│   └── ui/                # Streamlit 页面组件
├── products/              # 各店素材（cover / detail / sku）
├── ChromeProfiles/        # 浏览器登录缓存
├── logs/                  # 运行日志
└── scripts/               # 辅助脚本
```

## 启动

在项目根目录执行：

```bash
# 安装依赖（首次）
pip install streamlit DrissionPage openai

# 控制台
streamlit run app.py

# 命令行上架 / 下架
python main.py
python delist_main.py
```

## 功能模块

| 模块 | 说明 |
|------|------|
| `pdd_auto/listing` | 多 SKU 上架、页面 AI 标题 |
| `pdd_auto/delist` | 按创建时间门槛批量下架 |
| `pdd_auto/ai` | 智谱 GLM 视觉标题生成 |
| `pdd_auto/ui` | 控制台 Tab 组件 |
