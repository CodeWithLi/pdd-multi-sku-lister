<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import type { FeishuBitableHealth } from '@/types'

interface TableItem {
  table_id: string
  name: string
}

interface FieldItem {
  field_id: string
  field_name: string
  type: number
}

interface RecordItem {
  record_id: string
  fields: Record<string, unknown>
}

const FIELD_TYPE_LABEL: Record<number, string> = {
  1: '文本',
  2: '数字',
  3: '单选',
  4: '多选',
  5: '日期',
  7: '复选框',
  11: '人员',
  13: '电话',
  15: '超链接',
  17: '附件',
  18: '关联',
  20: '公式',
  21: '双向关联',
  22: '地理位置',
  1001: '创建时间',
  1002: '修改时间',
  1003: '创建人',
  1004: '修改人',
}

const loading = ref(false)
const appToken = ref('')
const tableId = ref('')
const health = ref<FeishuBitableHealth | null>(null)
const activeTab = ref('fields')
const error = ref('')

const tables = ref<TableItem[]>([])
const fields = ref<FieldItem[]>([])
const createTableName = ref('')
const renameTableName = ref('')
const createFieldName = ref('')
const createFieldType = ref(1)
const createFieldPropertyJson = ref('')
const createRecordJson = ref('{\n  "商品编码": "BD001A",\n  "状态": "在售"\n}')
const deleteRecordIds = ref('')

const dataDialogVisible = ref(false)
const dataDialogLoading = ref(false)
const dataDialogTable = ref<TableItem | null>(null)
const dataDialogFields = ref<FieldItem[]>([])
const dataDialogRecords = ref<RecordItem[]>([])
const dataDialogNextToken = ref('')
const dataDialogTotal = ref(0)

const baseName = '技术系统'

const selectedTable = computed(() => tables.value.find((t) => t.table_id === tableId.value.trim()) || null)
const selectedTableName = computed(() => selectedTable.value?.name || '未选择数据表')
const dataDialogColumns = computed(() =>
  dataDialogFields.value.map((f) => ({
    prop: f.field_name,
    label: f.field_name,
    minWidth: f.field_name.length > 6 ? 140 : 110,
  })),
)

function tokenParam() {
  return appToken.value.trim() || health.value?.default_app_token?.trim() || ''
}

function extractList<T = unknown>(resp: unknown, key: string): T[] {
  const data = (resp as { data?: Record<string, unknown> })?.data
  return Array.isArray(data?.[key]) ? (data[key] as T[]) : []
}

function fieldTypeLabel(type: number) {
  return FIELD_TYPE_LABEL[type] || String(type)
}

function formatCellValue(val: unknown): string {
  if (val === null || val === undefined || val === '') return '—'
  if (typeof val === 'boolean') return val ? '是' : '否'
  if (typeof val === 'number') {
    if (val > 1e11) return new Date(val).toLocaleString('zh-CN')
    return String(val)
  }
  if (typeof val === 'string') return val
  if (Array.isArray(val)) {
    return val
      .map((item) => {
        if (item && typeof item === 'object' && 'name' in item) return String((item as { name?: string }).name || '')
        return formatCellValue(item)
      })
      .filter(Boolean)
      .join('、') || '—'
  }
  if (typeof val === 'object') {
    const obj = val as Record<string, unknown>
    if (obj.text !== undefined) return String(obj.text)
    if (obj.name !== undefined) return String(obj.name)
    if (Array.isArray(obj.text_arr)) return obj.text_arr.join('、')
    return JSON.stringify(val)
  }
  return String(val)
}

function truncateToken(token: string, len = 12) {
  if (!token) return '—'
  if (token.length <= len * 2) return token
  return `${token.slice(0, len)}…${token.slice(-6)}`
}

function selectTable(row: TableItem) {
  tableId.value = row.table_id
  fields.value = []
}

async function loadHealth() {
  health.value = await api.feishuBitableHealth()
  if (!appToken.value.trim() && health.value.default_app_token) {
    appToken.value = health.value.default_app_token
  }
  if (!tableId.value.trim() && health.value.default_table_id) {
    tableId.value = health.value.default_table_id
  }
}

async function loadTables() {
  const resp = await api.feishuBitableListTables(tokenParam())
  tables.value = extractList<{ table_id?: string; name?: string }>(resp, 'items').map((x) => ({
    table_id: String(x.table_id || ''),
    name: String(x.name || ''),
  }))
  if (!tableId.value.trim() && tables.value.length) {
    tableId.value = tables.value[0].table_id
  }
}

async function loadFields() {
  const id = tableId.value.trim()
  if (!id) return ElMessage.warning('请先在左侧选择一个数据表')
  const resp = await api.feishuBitableListFields(id, tokenParam())
  fields.value = extractList<{ field_id?: string; field_name?: string; type?: number }>(resp, 'items').map((x) => ({
    field_id: String(x.field_id || ''),
    field_name: String(x.field_name || ''),
    type: Number(x.type || 0),
  }))
}

async function fetchRecordsForTable(
  id: string,
  opts: { reset?: boolean; pageToken?: string } = {},
): Promise<{ items: RecordItem[]; nextToken: string; hasMore: boolean }> {
  const resp = await api.feishuBitableListRecords(id, {
    app_token: tokenParam() || undefined,
    page_size: 100,
    page_token: opts.reset ? '' : opts.pageToken || '',
  })
  const items = extractList<{ record_id?: string; fields?: Record<string, unknown> }>(resp, 'items').map((x) => ({
    record_id: String(x.record_id || ''),
    fields: (x.fields || {}) as Record<string, unknown>,
  }))
  const data = (resp as { data?: { page_token?: string; total?: number; has_more?: boolean } })?.data
  return {
    items,
    nextToken: String(data?.page_token || ''),
    hasMore: Boolean(data?.has_more),
  }
}

async function openDataDialog(row?: TableItem) {
  const target = row || selectedTable.value
  if (!target) return ElMessage.warning('请先选择一个数据表')
  dataDialogTable.value = target
  dataDialogVisible.value = true
  dataDialogLoading.value = true
  dataDialogRecords.value = []
  dataDialogFields.value = []
  dataDialogNextToken.value = ''
  dataDialogTotal.value = 0
  try {
    const fieldResp = await api.feishuBitableListFields(target.table_id, tokenParam())
    dataDialogFields.value = extractList<{ field_id?: string; field_name?: string; type?: number }>(
      fieldResp,
      'items',
    ).map((x) => ({
      field_id: String(x.field_id || ''),
      field_name: String(x.field_name || ''),
      type: Number(x.type || 0),
    }))
    const { items, nextToken } = await fetchRecordsForTable(target.table_id, { reset: true })
    dataDialogRecords.value = items
    dataDialogNextToken.value = nextToken
    dataDialogTotal.value = items.length
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载数据失败')
    dataDialogVisible.value = false
  } finally {
    dataDialogLoading.value = false
  }
}

async function loadMoreDialogRecords() {
  const target = dataDialogTable.value
  if (!target || !dataDialogNextToken.value) return
  dataDialogLoading.value = true
  try {
    const { items, nextToken } = await fetchRecordsForTable(target.table_id, {
      pageToken: dataDialogNextToken.value,
    })
    dataDialogRecords.value = [...dataDialogRecords.value, ...items]
    dataDialogNextToken.value = nextToken
    dataDialogTotal.value = dataDialogRecords.value.length
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载更多失败')
  } finally {
    dataDialogLoading.value = false
  }
}

async function refreshDataDialog() {
  const target = dataDialogTable.value
  if (!target) return
  dataDialogLoading.value = true
  try {
    const { items, nextToken } = await fetchRecordsForTable(target.table_id, { reset: true })
    dataDialogRecords.value = items
    dataDialogNextToken.value = nextToken
    dataDialogTotal.value = items.length
    ElMessage.success('已刷新')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '刷新失败')
  } finally {
    dataDialogLoading.value = false
  }
}

async function createTable() {
  const name = createTableName.value.trim()
  if (!name) return ElMessage.warning('请输入数据表名称')
  await api.feishuBitableCreateTable({ app_token: tokenParam() || undefined, name })
  ElMessage.success('数据表创建成功')
  createTableName.value = ''
  await loadTables()
}

async function renameTable() {
  const id = tableId.value.trim()
  const name = renameTableName.value.trim()
  if (!id || !name) return ElMessage.warning('请选择数据表并填写新名称')
  await api.feishuBitableUpdateTable(id, { app_token: tokenParam() || undefined, name })
  ElMessage.success('表名已更新')
  renameTableName.value = ''
  await loadTables()
}

async function createField() {
  const id = tableId.value.trim()
  const fieldName = createFieldName.value.trim()
  if (!id || !fieldName) return ElMessage.warning('请选择数据表并填写字段名')
  let property: Record<string, unknown> | null = null
  if (createFieldPropertyJson.value.trim()) {
    try {
      property = JSON.parse(createFieldPropertyJson.value)
    } catch {
      return ElMessage.error('字段 property JSON 格式不正确')
    }
  }
  await api.feishuBitableCreateField({
    app_token: tokenParam() || undefined,
    table_id: id,
    field_name: fieldName,
    type: createFieldType.value,
    property,
  })
  ElMessage.success('字段创建成功')
  createFieldName.value = ''
  createFieldPropertyJson.value = ''
  await loadFields()
}

async function createRecord() {
  const id = tableId.value.trim()
  if (!id) return ElMessage.warning('请先在左侧选择一个数据表')
  let parsed: Record<string, unknown> | Record<string, unknown>[]
  try {
    parsed = JSON.parse(createRecordJson.value)
  } catch {
    return ElMessage.error('记录 JSON 格式不正确')
  }
  const rows = Array.isArray(parsed) ? parsed : [parsed]
  if (!rows.length) return ElMessage.warning('记录不能为空')
  await api.feishuBitableBatchCreateRecords({
    app_token: tokenParam() || undefined,
    table_id: id,
    records: rows,
  })
  ElMessage.success(`已新增 ${rows.length} 条记录`)
  if (dataDialogVisible.value && dataDialogTable.value?.table_id === id) {
    await refreshDataDialog()
  }
}

async function removeField(fieldId: string) {
  await api.feishuBitableDeleteField(fieldId, tableId.value.trim(), tokenParam())
  ElMessage.success('字段已删除')
  await loadFields()
}

async function removeRecords() {
  const id = tableId.value.trim()
  if (!id) return ElMessage.warning('请先在左侧选择一个数据表')
  const ids = deleteRecordIds.value
    .split(',')
    .map((x) => x.trim())
    .filter(Boolean)
  if (!ids.length) return ElMessage.warning('请输入要删除的 record_id')
  await api.feishuBitableBatchDeleteRecords({
    app_token: tokenParam() || undefined,
    table_id: id,
    record_ids: ids,
  })
  ElMessage.success(`已删除 ${ids.length} 条记录`)
  deleteRecordIds.value = ''
  if (dataDialogVisible.value && dataDialogTable.value?.table_id === id) {
    await refreshDataDialog()
  }
}

async function run<T>(fn: () => Promise<T>) {
  loading.value = true
  error.value = ''
  try {
    await fn()
  } catch (e) {
    const msg = e instanceof Error ? e.message : '操作失败'
    if (msg.includes('91402') || msg.includes('NOTEXIST')) {
      error.value =
        '无法访问「技术系统」：app_token 不正确或 OAuth 账号无权限。请检查 feishu.yaml 并重新授权。'
    } else {
      error.value = msg
    }
  } finally {
    loading.value = false
  }
}

async function initPage() {
  await run(async () => {
    await loadHealth()
    await loadTables()
  })
}

onMounted(initPage)
</script>

<template>
  <div v-loading="loading" class="feishu-page">
    <PageHeader
      :title="`飞书多维表格 · ${baseName}`"
      desc="在技术系统 Base 内管理数据表、字段与记录"
    >
      <template #actions>
        <el-button @click="run(initPage)">刷新</el-button>
        <el-button
          type="primary"
          :disabled="!selectedTable"
          @click="openDataDialog()"
        >
          查看当前表数据
        </el-button>
      </template>
    </PageHeader>

    <el-alert
      v-if="error"
      type="error"
      :title="error"
      show-icon
      closable
      class="page-error"
      @close="error = ''"
    />

    <div class="status-bar">
      <div class="status-pill" :class="{ ok: health?.ok }">
        <span class="dot" />
        {{ health?.ok ? '接口正常' : '未连接' }}
      </div>
      <div class="status-pill muted">user_access_token</div>
      <div class="status-pill muted" :title="appToken">
        Base {{ truncateToken(appToken) }}
      </div>
      <div v-if="selectedTable" class="status-pill active">
        当前表：{{ selectedTableName }}
      </div>
    </div>

    <div class="main-layout">
      <aside class="table-panel">
        <div class="panel-head">
          <div>
            <div class="panel-title">数据表</div>
            <div class="panel-sub">{{ tables.length }} 张表</div>
          </div>
          <el-button link type="primary" @click="run(loadTables)">刷新</el-button>
        </div>

        <div class="table-list">
          <button
            v-for="row in tables"
            :key="row.table_id"
            type="button"
            class="table-item"
            :class="{ active: tableId === row.table_id }"
            @click="selectTable(row)"
          >
            <div class="table-item-name">{{ row.name }}</div>
            <div class="table-item-id">{{ row.table_id }}</div>
            <div class="table-item-actions" @click.stop>
              <el-button link type="primary" size="small" @click="openDataDialog(row)">查看数据</el-button>
            </div>
          </button>
          <el-empty v-if="!tables.length" description="暂无数据表，请先刷新" :image-size="64" />
        </div>

        <el-collapse class="panel-collapse">
          <el-collapse-item title="新建 / 重命名数据表" name="table-ops">
            <div class="mini-form">
              <el-input v-model="createTableName" placeholder="新数据表名称" size="small" />
              <el-button type="primary" size="small" @click="run(createTable)">新建</el-button>
            </div>
            <div class="mini-form">
              <el-input v-model="renameTableName" placeholder="新表名（当前选中表）" size="small" />
              <el-button size="small" :disabled="!tableId" @click="run(renameTable)">重命名</el-button>
            </div>
          </el-collapse-item>
          <el-collapse-item title="连接设置" name="conn">
            <el-input v-model="appToken" size="small" placeholder="app_token" />
            <p class="hint">一般无需修改，默认读取 feishu.yaml</p>
          </el-collapse-item>
        </el-collapse>
      </aside>

      <section class="content-panel">
        <div v-if="!tableId" class="empty-workspace">
          <el-empty description="请从左侧选择一个数据表" />
        </div>

        <template v-else>
          <div class="workspace-head">
            <div>
              <h3>{{ selectedTableName }}</h3>
              <p class="workspace-meta">{{ tableId }}</p>
            </div>
            <div class="workspace-actions">
              <el-button @click="run(loadFields)">刷新字段</el-button>
              <el-button type="primary" @click="openDataDialog()">查看数据</el-button>
            </div>
          </div>

          <el-tabs v-model="activeTab" class="workspace-tabs">
            <el-tab-pane label="字段管理" name="fields">
              <div class="tab-toolbar">
                <el-input v-model="createFieldName" placeholder="字段名" style="width: 160px" />
                <el-select v-model="createFieldType" style="width: 120px">
                  <el-option v-for="(label, type) in FIELD_TYPE_LABEL" :key="type" :label="label" :value="Number(type)" />
                </el-select>
                <el-button type="primary" @click="run(createField)">新增字段</el-button>
              </div>
              <el-input
                v-model="createFieldPropertyJson"
                type="textarea"
                :rows="2"
                class="property-input"
                placeholder='可选 property JSON，如 {"formatter":"0.00"}'
              />
              <el-table :data="fields" size="small" stripe empty-text="点击「刷新字段」加载列定义">
                <el-table-column prop="field_name" label="字段名" min-width="140" />
                <el-table-column label="类型" width="100">
                  <template #default="{ row }">{{ fieldTypeLabel(row.type) }}</template>
                </el-table-column>
                <el-table-column prop="field_id" label="field_id" min-width="180" show-overflow-tooltip />
                <el-table-column label="操作" width="80" fixed="right">
                  <template #default="{ row }">
                    <el-button link type="danger" @click="run(() => removeField(row.field_id))">删除</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </el-tab-pane>

            <el-tab-pane label="写入记录" name="records">
              <div class="record-layout">
                <div class="record-block">
                  <div class="block-title">新增记录（JSON）</div>
                  <el-input
                    v-model="createRecordJson"
                    type="textarea"
                    :rows="10"
                    placeholder='{"商品编码":"BD001A"} 或 [{"商品编码":"A"},{"商品编码":"B"}]'
                  />
                  <el-button type="primary" class="block-action" @click="run(createRecord)">提交</el-button>
                </div>
                <div class="record-block">
                  <div class="block-title">删除记录</div>
                  <el-input
                    v-model="deleteRecordIds"
                    type="textarea"
                    :rows="10"
                    placeholder="record_id，多个用英文逗号分隔"
                  />
                  <el-button type="danger" class="block-action" @click="run(removeRecords)">批量删除</el-button>
                </div>
              </div>
            </el-tab-pane>
          </el-tabs>
        </template>
      </section>
    </div>

    <el-dialog
      v-model="dataDialogVisible"
      :title="`${dataDialogTable?.name || ''} · 数据预览`"
      width="min(1200px, 92vw)"
      top="4vh"
      destroy-on-close
      class="data-dialog"
    >
      <div v-loading="dataDialogLoading" class="dialog-body">
        <div class="dialog-toolbar">
          <span class="dialog-count">已加载 {{ dataDialogTotal }} 条</span>
          <el-button size="small" @click="refreshDataDialog">刷新</el-button>
        </div>

        <el-table
          :data="dataDialogRecords"
          size="small"
          stripe
          border
          max-height="62vh"
          empty-text="该表暂无记录"
          class="data-table"
        >
          <el-table-column type="index" label="#" width="52" fixed="left" />
          <el-table-column
            v-for="col in dataDialogColumns"
            :key="col.prop"
            :prop="col.prop"
            :label="col.label"
            :min-width="col.minWidth"
            show-overflow-tooltip
          >
            <template #default="{ row }">
              {{ formatCellValue(row.fields?.[col.prop]) }}
            </template>
          </el-table-column>
          <el-table-column
            v-if="!dataDialogColumns.length && dataDialogRecords.length"
            label="原始数据"
            min-width="320"
          >
            <template #default="{ row }">
              <span class="raw-cell">{{ JSON.stringify(row.fields) }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="record_id" label="record_id" width="180" fixed="right" show-overflow-tooltip />
        </el-table>

        <div v-if="dataDialogNextToken" class="dialog-footer">
          <el-button :loading="dataDialogLoading" @click="loadMoreDialogRecords">加载更多</el-button>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.feishu-page {
  width: 100%;
}

.page-error {
  margin-bottom: 12px;
}

.status-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 14px;
}

.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 999px;
  font-size: 12px;
  background: #f8fafc;
  color: #475569;
  border: 1px solid #e2e8f0;
}

.status-pill.ok {
  background: #ecfdf5;
  color: #047857;
  border-color: #a7f3d0;
}

.status-pill.active {
  background: #eff6ff;
  color: #1d4ed8;
  border-color: #bfdbfe;
}

.status-pill.muted {
  color: #64748b;
}

.status-pill .dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #94a3b8;
}

.status-pill.ok .dot {
  background: #10b981;
}

.main-layout {
  display: grid;
  grid-template-columns: 300px 1fr;
  gap: 14px;
  align-items: start;
}

.table-panel,
.content-panel {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  overflow: hidden;
}

.table-panel {
  position: sticky;
  top: 12px;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px 10px;
  border-bottom: 1px solid #f1f5f9;
}

.panel-title {
  font-size: 14px;
  font-weight: 700;
  color: #111827;
}

.panel-sub {
  margin-top: 2px;
  font-size: 12px;
  color: #94a3b8;
}

.table-list {
  max-height: 420px;
  overflow: auto;
  padding: 8px;
}

.table-item {
  width: 100%;
  text-align: left;
  border: 1px solid transparent;
  background: #f8fafc;
  border-radius: 10px;
  padding: 10px 12px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.table-item:hover {
  border-color: #dbeafe;
  background: #f8fbff;
}

.table-item.active {
  border-color: #3b82f6;
  background: #eff6ff;
  box-shadow: 0 0 0 1px rgba(59, 130, 246, 0.15);
}

.table-item-name {
  font-size: 13px;
  font-weight: 600;
  color: #1f2937;
}

.table-item-id {
  margin-top: 4px;
  font-size: 11px;
  color: #94a3b8;
  word-break: break-all;
}

.table-item-actions {
  margin-top: 6px;
}

.panel-collapse {
  border-top: 1px solid #f1f5f9;
}

.panel-collapse :deep(.el-collapse-item__header) {
  padding: 0 14px;
  font-size: 13px;
}

.panel-collapse :deep(.el-collapse-item__content) {
  padding: 0 14px 14px;
}

.mini-form {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
}

.hint {
  margin: 8px 0 0;
  font-size: 12px;
  color: #94a3b8;
}

.content-panel {
  min-height: 520px;
}

.empty-workspace {
  padding: 80px 20px;
}

.workspace-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 18px;
  border-bottom: 1px solid #f1f5f9;
}

.workspace-head h3 {
  margin: 0;
  font-size: 18px;
  color: #111827;
}

.workspace-meta {
  margin: 4px 0 0;
  font-size: 12px;
  color: #94a3b8;
}

.workspace-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.workspace-tabs {
  padding: 0 18px 18px;
}

.workspace-tabs :deep(.el-tabs__header) {
  margin-bottom: 14px;
}

.tab-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}

.property-input {
  margin-bottom: 12px;
}

.record-layout {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.record-block {
  border: 1px solid #f1f5f9;
  border-radius: 10px;
  padding: 14px;
  background: #fafbfc;
}

.block-title {
  margin-bottom: 10px;
  font-size: 13px;
  font-weight: 600;
  color: #374151;
}

.block-action {
  margin-top: 10px;
}

.dialog-body {
  min-height: 200px;
}

.dialog-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.dialog-count {
  font-size: 13px;
  color: #64748b;
}

.dialog-footer {
  margin-top: 12px;
  text-align: center;
}

.raw-cell {
  font-size: 12px;
  color: #475569;
  word-break: break-all;
}

.data-table :deep(.el-table__cell) {
  font-size: 12px;
}

@media (max-width: 1100px) {
  .main-layout {
    grid-template-columns: 1fr;
  }

  .table-panel {
    position: static;
  }

  .record-layout {
    grid-template-columns: 1fr;
  }
}
</style>
