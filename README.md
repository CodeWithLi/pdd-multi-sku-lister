# 拼多多多店铺 SKU 自动上架 / 下架

## 商品素材规则

```
products/
└── 挂件/                    # 品类
    └── BCP001/              # 商品编码
        ├── default/         # 单款式（固定名）
        │   ├── 1.jpg … 5.jpg   # 轮播主图
        │   ├── 6.jpg … 8.jpg   # 详情图
        │   └── sku_1.png …     # SKU 预览图（手动配置）
        └── blue/              # 多款式示例
            └── 1.jpg … 8.jpg
```

config 中每个店铺配置 `product.category / product.code / product.variant`。

## 多规格测试模式（款式 + 型号 + 多套图）

每个商品编码（如 `BD046A/`）下可有 **第一套图、第二套图 …**，**每套图 = 一个独立上架商品**：

```
BD046A/
├── 第一套图/
│   ├── 主图/、详情页/
│   ├── BD046A/              # 款式
│   │   └── BD046A+YKL2005A/预览图.png
│   └── BD046B/ …
├── 第二套图/                # 另一套 = 另一个商品
└── …
```

无「第x套图」时兼容旧结构（商品根目录直接含 主图/详情页/款式）。

SKU 中文名仅从 `sku+名称.xlsx` 检索；查不到则打日志并跳过。

```bash
python multi_spec_main.py --dry-run BD046A   # 解析所有套图
python multi_spec_main.py BD046A             # 按顺序上架每一套图
```
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
