# 飞书多维表格接口文档（主系统）

鉴权模式：固定使用 `user_access_token`（来源于 `config/feishu.yaml`）。

接口前缀：`/api/feishu-bitable`

---

## 一、开放平台权限清单

建议直接开通：`bitable:app`（覆盖多数多维表格管理操作）。

若走细粒度最小权限，至少需要：

- `base:app:create`（创建多维表格）
- `base:app:copy`（复制多维表格）
- `base:table:create`
- `base:table:read`
- `base:table:update`
- `base:table:delete`
- `base:field:create`
- `base:field:read`
- `base:field:update`
- `base:field:delete`
- `base:record:create`
- `base:record:read`
- `base:record:update`
- `base:record:delete`

注意：权限开通后需要发布应用新版本才能生效。

---

## 二、配置要求

`config/feishu.yaml` 至少配置：

- `app_id`
- `app_secret`
- `bitable_app_token`（可选默认 Base，调用时也可传 `app_token` 覆盖）

---

## 三、接口列表

### 1) 健康检查

- `GET /api/feishu-bitable/health`

返回示例：

```json
{
  "ok": true,
  "auth_mode": "user_access_token",
  "configured": true,
  "default_app_token": "appxxxx"
}
```

### 2) Base（多维表格）

- `POST /api/feishu-bitable/apps`：创建 Base
- `POST /api/feishu-bitable/apps/copy`：复制 Base

请求示例（创建）：

```json
{
  "name": "运营日报",
  "folder_token": "",
  "time_zone": "Asia/Shanghai"
}
```

请求示例（复制）：

```json
{
  "source_app_token": "app_source_xxx",
  "name": "运营日报-副本",
  "folder_token": "",
  "without_content": false,
  "time_zone": "Asia/Shanghai"
}
```

### 3) 数据表（Table）

- `GET /api/feishu-bitable/tables?app_token=`
- `POST /api/feishu-bitable/tables`
- `PATCH /api/feishu-bitable/tables/{table_id}`
- `DELETE /api/feishu-bitable/tables/{table_id}?app_token=`

请求示例（创建表）：

```json
{
  "app_token": "app_xxx",
  "name": "商品上架记录"
}
```

请求示例（改表名）：

```json
{
  "app_token": "app_xxx",
  "name": "商品上架日志"
}
```

### 4) 字段（Field）

- `GET /api/feishu-bitable/tables/{table_id}/fields?app_token=`
- `POST /api/feishu-bitable/fields`
- `PUT /api/feishu-bitable/fields/{field_id}`
- `DELETE /api/feishu-bitable/fields/{field_id}?table_id=...&app_token=...`

请求示例（创建字段）：

```json
{
  "app_token": "app_xxx",
  "table_id": "tbl_xxx",
  "field_name": "商品编码",
  "type": 1,
  "property": null
}
```

请求示例（更新字段）：

```json
{
  "app_token": "app_xxx",
  "table_id": "tbl_xxx",
  "field_name": "商品编码（新）",
  "type": 1,
  "property": null
}
```

### 5) 记录（Record）

- `GET /api/feishu-bitable/tables/{table_id}/records?app_token=&page_size=&page_token=`
- `POST /api/feishu-bitable/records/batch-create`
- `PUT /api/feishu-bitable/records/{record_id}`
- `POST /api/feishu-bitable/records/batch-delete`

请求示例（批量新增记录）：

```json
{
  "app_token": "app_xxx",
  "table_id": "tbl_xxx",
  "records": [
    {
      "商品编码": "BD001A",
      "状态": "在售"
    },
    {
      "商品编码": "BD001B",
      "状态": "在售"
    }
  ]
}
```

请求示例（更新单条记录）：

```json
{
  "app_token": "app_xxx",
  "table_id": "tbl_xxx",
  "fields": {
    "状态": "已下架"
  }
}
```

请求示例（批量删除记录）：

```json
{
  "app_token": "app_xxx",
  "table_id": "tbl_xxx",
  "record_ids": ["recu1xxx", "recu2xxx"]
}
```

---

## 四、调用建议

- 同一张表的写请求（增删改字段/记录）尽量串行，避免飞书 `Write conflict`。
- 单次批量写入不要过大，建议分批。
- 若接口返回 `99991672` / 权限不足，优先核对应用权限和发布状态。
- 同事调试优先走 `http://127.0.0.1:<port>/docs` 中 `feishu-bitable` 分组。
