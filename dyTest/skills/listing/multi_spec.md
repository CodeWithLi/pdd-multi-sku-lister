# 抖店多规格上架 Skill

## 发布页第一步（已实现）

1. 商品管理 → 点击「商品创建」（新标签页，关闭旧页）
2. 上传主图 1~5
3. 等待 AI 标题（先等 15s）→ 「立即使用」或点 AI 生成
4. 等待商品类目 → 选择第一个推荐
5. 点击「下一步」（支持 category_next_burst_demo 连点）

## 页面变体

- `publish_page_flow.py` 识别变体并路由
- 当前：`standard_v1` → `publish_page_standard_v1.py`
- 新变体：新增 `publish_page_*.py` 并在 flow 中注册

## 预留开关（settings.yaml listing 段）

| 开关 | 用途 |
|------|------|
| slot_alignment_test | 规格槽位对齐（step2） |
| spec_fill_verify_test | 规格校验填表（step2） |
| primary_style_first_test | 主款款式优先（step2） |
| category_next_burst_demo | 类目/下一步连点 workaround |
| accessory_cost_pricing | 配件成本定价（step2+） |
| accessory_tiered_float | 子商品档位浮动（step2+） |

## 素材目录

与拼多多共用结构，见上级 `多规格测试` 或 `data/assets/商品上架规格文件/`。

