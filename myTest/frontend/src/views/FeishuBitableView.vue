<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
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
  property?: Record<string, unknown>
}

const READONLY_FIELD_TYPES = new Set([17, 18, 20, 21, 1001, 1002, 1003, 1004])

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
const recordFields = ref<FieldItem[]>([])
const recordFieldsTableId = ref('')
const recordFormLoading = ref(false)
const createTableName = ref('')
const renameTableName = ref('')
const createFieldName = ref('')
const createFieldType = ref(1)
const createFieldPropertyJson = ref('')
const createRecordJson = ref('')
const recordFormValues = ref<Record<string, unknown>>({})
const deletableRecords = ref<RecordItem[]>([])
const selectedDeleteIds = ref<string[]>([])
const deletePreviewFields = ref<FieldItem[]>([])

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
const writableFields = computed(() => recordFields.value.filter((f) => !READONLY_FIELD_TYPES.has(f.type)))
const recordFormReady = computed(
  () => recordFieldsTableId.value === tableId.value.trim() && writableFields.value.length > 0,
)
const deletePreviewColumns = computed(() =>
  deletePreviewFields.value.slice(0, 4).map((f) => ({
    prop: f.field_name,
    label: f.field_name,
    minWidth: 120,
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

function parseFieldItem(x: {
  field_id?: string
  field_name?: string
  type?: number
  property?: Record<string, unknown>
}): FieldItem {
  return {
    field_id: String(x.field_id || ''),
    field_name: String(x.field_name || ''),
    type: Number(x.type || 0),
    property: x.property || undefined,
  }
}

function getSelectOptions(field: FieldItem): string[] {
  const options = field.property?.options
  if (!Array.isArray(options)) return []
  return options
    .map((item) => String((item as { name?: string }).name || ''))
    .filter(Boolean)
}

function isDateTimeField(field: FieldItem): boolean {
  const formatter = String(field.property?.date_formatter || '')
  if (!formatter) return true
  return /H|h|m|s/.test(formatter)
}

function urlFormValue(fieldName: string) {
  const raw = recordFormValues.value[fieldName]
  if (raw && typeof raw === 'object') return raw as { link: string; text: string }
  return { link: '', text: '' }
}

function setUrlFormValue(fieldName: string, key: 'link' | 'text', value: string) {
  const current = urlFormValue(fieldName)
  recordFormValues.value[fieldName] = { ...current, [key]: value }
}

function initRecordFormValues() {
  const next: Record<string, unknown> = {}
  for (const field of writableFields.value) {
    if (field.type === 4) next[field.field_name] = []
    else if (field.type === 7) next[field.field_name] = false
    else if (field.type === 2) next[field.field_name] = undefined
    else if (field.type === 15) next[field.field_name] = { link: '', text: '' }
    else next[field.field_name] = ''
  }
  recordFormValues.value = next
}

function resetRecordForm() {
  initRecordFormValues()
  ElMessage.success('表单已清空')
}

function serializeFieldValue(field: FieldItem, raw: unknown): unknown {
  switch (field.type) {
    case 2:
      if (raw === '' || raw === null || raw === undefined) return undefined
      return Number(raw)
    case 5:
      if (!raw) return undefined
      if (typeof raw === 'number') return raw
      if (typeof raw === 'string') {
        const ms = Number(raw)
        return Number.isFinite(ms) ? ms : new Date(raw).getTime()
      }
      if (raw instanceof Date) return raw.getTime()
      return undefined
    case 4:
      return Array.isArray(raw) ? raw.filter(Boolean) : []
    case 7:
      return Boolean(raw)
    case 15: {
      if (!raw || typeof raw !== 'object') return undefined
      const obj = raw as { link?: string; text?: string }
      const link = String(obj.link || '').trim()
      if (!link) return undefined
      const text = String(obj.text || link).trim() || link
      return { link, text }
    }
    case 3:
      return raw ? String(raw) : undefined
    default: {
      const text = String(raw ?? '').trim()
      return text || undefined
    }
  }
}

function buildRecordPayload(): Record<string, unknown> {
  const payload: Record<string, unknown> = {}
  for (const field of writableFields.value) {
    const value = serializeFieldValue(field, recordFormValues.value[field.field_name])
    if (value === undefined || value === null || value === '') continue
    if (Array.isArray(value) && !value.length) continue
    payload[field.field_name] = value
  }
  return payload
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
  recordFields.value = []
  recordFieldsTableId.value = ''
  recordFormValues.value = {}
  deletableRecords.value = []
  selectedDeleteIds.value = []
  if (activeTab.value === 'fields') {
    void run(loadFields)
  } else if (activeTab.value === 'records') {
    void run(loadRecordFormFields)
  }
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

async function fetchTableFields(id: string): Promise<FieldItem[] | null> {
  const resp = await api.feishuBitableListFields(id, tokenParam())
  if (tableId.value.trim() !== id) return null
  return extractList<{
    field_id?: string
    field_name?: string
    type?: number
    property?: Record<string, unknown>
  }>(resp, 'items').map(parseFieldItem)
}

async function loadFields() {
  const id = tableId.value.trim()
  if (!id) return ElMessage.warning('请先在左侧选择一个数据表')
  const items = await fetchTableFields(id)
  if (!items) return
  fields.value = items
}

async function loadRecordFormFields() {
  const id = tableId.value.trim()
  if (!id) return ElMessage.warning('请先在左侧选择一个数据表')
  recordFormLoading.value = true
  recordFields.value = []
  recordFieldsTableId.value = ''
  recordFormValues.value = {}
  try {
    const items = await fetchTableFields(id)
    if (!items) return
    recordFields.value = items
    recordFieldsTableId.value = id
    if (!writableFields.value.length) {
      ElMessage.warning('当前表没有可填写的字段，请先在「字段管理」中新增字段')
      return
    }
    initRecordFormValues()
  } finally {
    recordFormLoading.value = false
  }
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
    dataDialogFields.value = extractList<{
      field_id?: string
      field_name?: string
      type?: number
      property?: Record<string, unknown>
    }>(fieldResp, 'items').map(parseFieldItem)
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
  if (!id) return ElMessage.warning('请先在左侧选择一个数据表')
  const name = renameTableName.value.trim()
  if (!name) return ElMessage.warning('请填写新的表名')
  await api.feishuBitableUpdateTable(id, { app_token: tokenParam() || undefined, name })
  ElMessage.success('表名已更新')
  renameTableName.value = ''
  await loadTables()
}

async function createField() {
  const id = tableId.value.trim()
  if (!id) return ElMessage.warning('请先在左侧选择一个数据表')
  const fieldName = createFieldName.value.trim()
  if (!fieldName) return ElMessage.warning('请先填写字段名（上方输入框）')
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
  if (activeTab.value === 'records') {
    await loadRecordFormFields()
  }
}

async function submitRecordForm() {
  const id = tableId.value.trim()
  if (!id) return ElMessage.warning('请先在左侧选择一个数据表')
  if (!recordFormReady.value) {
    return ElMessage.warning('表单字段与当前表不一致，请稍候或点击「重新加载表单」')
  }
  const payload = buildRecordPayload()
  if (!Object.keys(payload).length) {
    return ElMessage.warning('请至少填写一个字段')
  }
  await api.feishuBitableBatchCreateRecords({
    app_token: tokenParam() || undefined,
    table_id: id,
    records: [payload],
  })
  ElMessage.success('记录已提交')
  initRecordFormValues()
  if (dataDialogVisible.value && dataDialogTable.value?.table_id === id) {
    await refreshDataDialog()
  }
  if (deletableRecords.value.length) {
    await loadRecordsForDelete()
  }
}

async function createRecordFromJson() {
  const id = tableId.value.trim()
  if (!id) return ElMessage.warning('请先在左侧选择一个数据表')
  if (!createRecordJson.value.trim()) {
    return ElMessage.warning('请输入 JSON')
  }
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
  createRecordJson.value = ''
  if (dataDialogVisible.value && dataDialogTable.value?.table_id === id) {
    await refreshDataDialog()
  }
}

async function loadRecordsForDelete() {
  const id = tableId.value.trim()
  if (!id) return ElMessage.warning('请先在左侧选择一个数据表')
  const fieldResp = await api.feishuBitableListFields(id, tokenParam())
  deletePreviewFields.value = extractList<{
    field_id?: string
    field_name?: string
    type?: number
    property?: Record<string, unknown>
  }>(fieldResp, 'items')
    .map(parseFieldItem)
    .filter((f) => !READONLY_FIELD_TYPES.has(f.type))
    .slice(0, 4)
  const { items } = await fetchRecordsForTable(id, { reset: true })
  deletableRecords.value = items
  selectedDeleteIds.value = []
}

function onDeleteSelectionChange(rows: RecordItem[]) {
  selectedDeleteIds.value = rows.map((r) => r.record_id)
}

async function removeField(fieldId: string) {
  await api.feishuBitableDeleteField(fieldId, tableId.value.trim(), tokenParam())
  ElMessage.success('字段已删除')
  await loadFields()
}

async function removeSelectedRecords() {
  const id = tableId.value.trim()
  if (!id) return ElMessage.warning('请先在左侧选择一个数据表')
  if (!selectedDeleteIds.value.length) {
    return ElMessage.warning('请先勾选要删除的记录')
  }
  await api.feishuBitableBatchDeleteRecords({
    app_token: tokenParam() || undefined,
    table_id: id,
    record_ids: selectedDeleteIds.value,
  })
  ElMessage.success(`已删除 ${selectedDeleteIds.value.length} 条记录`)
  selectedDeleteIds.value = []
  await loadRecordsForDelete()
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
    } else if (msg.includes('网络') || msg.includes('502') || msg.includes('500') || msg.includes('SSL')) {
      error.value = `飞书接口暂时不可用：${msg}。请稍后点击「重新加载表单」重试。`
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
    if (!tableId.value.trim()) return
    if (activeTab.value === 'fields') {
      await loadFields()
    } else if (activeTab.value === 'records') {
      await loadRecordFormFields()
    }
  })
}

watch(activeTab, (tab) => {
  if (!tableId.value.trim()) return
  if (tab === 'fields' && !fields.value.length) void run(loadFields)
  if (tab === 'records') void run(loadRecordFormFields)
})

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
                <el-input v-model="createFieldName" placeholder="新字段名，如：商品编码" style="width: 200px" />
                <el-select v-model="createFieldType" style="width: 120px">
                  <el-option v-for="(label, type) in FIELD_TYPE_LABEL" :key="type" :label="label" :value="Number(type)" />
                </el-select>
                <el-button type="primary" :disabled="!createFieldName.trim()" @click="run(createField)">
                  新增字段
                </el-button>
              </div>
              <el-input
                v-model="createFieldPropertyJson"
                type="textarea"
                :rows="2"
                class="property-input"
                placeholder='可选 property JSON，如 {"formatter":"0.00"}'
              />
              <el-table :data="fields" size="small" stripe empty-text="暂无字段，可在上方新增">
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
              <div v-loading="recordFormLoading" class="record-write-panel">
                <div class="record-section-head">
                  <div>
                    <div class="block-title">新增记录 · {{ selectedTableName }}</div>
                    <p class="block-desc">
                      切换左侧数据表后会自动加载该表的字段。当前
                      <template v-if="recordFormReady">{{ writableFields.length }} 个可填字段</template>
                      <template v-else>正在加载或加载失败</template>
                    </p>
                  </div>
                  <el-button @click="run(loadRecordFormFields)">重新加载表单</el-button>
                </div>

                <el-empty
                  v-if="!recordFormLoading && !recordFormReady"
                  description="未能加载字段，请点击「重新加载表单」；若表为空请先在「字段管理」里新增列"
                  :image-size="72"
                />

                <el-form v-else-if="recordFormReady" label-position="top" class="record-form" @submit.prevent>
                  <el-row :gutter="16">
                    <el-col
                      v-for="field in writableFields"
                      :key="field.field_id"
                      :xs="24"
                      :sm="12"
                      :lg="field.type === 15 ? 24 : 12"
                    >
                      <el-form-item>
                        <template #label>
                          <span class="field-label">{{ field.field_name }}</span>
                          <span class="field-type-tag">{{ fieldTypeLabel(field.type) }}</span>
                        </template>

                        <el-input
                          v-if="field.type === 1 || field.type === 13"
                          v-model="recordFormValues[field.field_name]"
                          :placeholder="`请输入${field.field_name}`"
                          clearable
                        />

                        <el-input-number
                          v-else-if="field.type === 2"
                          v-model="recordFormValues[field.field_name]"
                          :controls="true"
                          class="full-width-input"
                        />

                        <el-select
                          v-else-if="field.type === 3"
                          v-model="recordFormValues[field.field_name]"
                          :placeholder="`请选择${field.field_name}`"
                          clearable
                          filterable
                          class="full-width-input"
                        >
                          <el-option
                            v-for="opt in getSelectOptions(field)"
                            :key="opt"
                            :label="opt"
                            :value="opt"
                          />
                        </el-select>

                        <el-select
                          v-else-if="field.type === 4"
                          v-model="recordFormValues[field.field_name]"
                          multiple
                          collapse-tags
                          collapse-tags-tooltip
                          :placeholder="`请选择${field.field_name}`"
                          class="full-width-input"
                        >
                          <el-option
                            v-for="opt in getSelectOptions(field)"
                            :key="opt"
                            :label="opt"
                            :value="opt"
                          />
                        </el-select>

                        <el-date-picker
                          v-else-if="field.type === 5"
                          v-model="recordFormValues[field.field_name]"
                          :type="isDateTimeField(field) ? 'datetime' : 'date'"
                          value-format="x"
                          :placeholder="`选择${field.field_name}`"
                          class="full-width-input"
                        />

                        <div v-else-if="field.type === 7" class="checkbox-row">
                          <el-switch v-model="recordFormValues[field.field_name]" />
                          <span class="checkbox-hint">{{ recordFormValues[field.field_name] ? '是' : '否' }}</span>
                        </div>

                        <div v-else-if="field.type === 15" class="url-field-row">
                          <el-input
                            :model-value="urlFormValue(field.field_name).link"
                            placeholder="链接地址"
                            clearable
                            @update:model-value="(v: string) => setUrlFormValue(field.field_name, 'link', v)"
                          />
                          <el-input
                            :model-value="urlFormValue(field.field_name).text"
                            placeholder="显示文字（可选）"
                            clearable
                            @update:model-value="(v: string) => setUrlFormValue(field.field_name, 'text', v)"
                          />
                        </div>

                        <el-input
                          v-else
                          v-model="recordFormValues[field.field_name]"
                          :placeholder="`请输入${field.field_name}`"
                          clearable
                        />
                      </el-form-item>
                    </el-col>
                  </el-row>

                  <div class="form-actions">
                    <el-button @click="resetRecordForm">清空表单</el-button>
                    <el-button type="primary" @click="run(submitRecordForm)">提交记录</el-button>
                  </div>
                </el-form>

                <el-collapse class="advanced-collapse">
                  <el-collapse-item title="JSON 批量写入" name="json">
                    <el-input
                      v-model="createRecordJson"
                      type="textarea"
                      :rows="6"
                      placeholder='单条 {"商品编码":"BD001A"} 或批量 [{"商品编码":"A"},{"商品编码":"B"}]'
                    />
                    <el-button type="primary" class="block-action" @click="run(createRecordFromJson)">JSON 提交</el-button>
                  </el-collapse-item>
                </el-collapse>
              </div>

              <el-divider />

              <div class="record-delete-panel">
                <div class="record-section-head">
                  <div>
                    <div class="block-title">删除记录</div>
                    <p class="block-desc">加载记录后勾选要删的行，无需手动复制 record_id。</p>
                  </div>
                  <el-button @click="run(loadRecordsForDelete)">加载记录</el-button>
                </div>

                <el-table
                  v-if="deletableRecords.length"
                  :data="deletableRecords"
                  size="small"
                  stripe
                  max-height="320"
                  @selection-change="onDeleteSelectionChange"
                >
                  <el-table-column type="selection" width="48" />
                  <el-table-column
                    v-for="col in deletePreviewColumns"
                    :key="col.prop"
                    :label="col.label"
                    :min-width="col.minWidth"
                    show-overflow-tooltip
                  >
                    <template #default="{ row }">
                      {{ formatCellValue(row.fields?.[col.prop]) }}
                    </template>
                  </el-table-column>
                  <el-table-column prop="record_id" label="record_id" min-width="160" show-overflow-tooltip />
                </el-table>
                <el-empty v-else description="点击「加载记录」后可勾选删除" :image-size="64" />

                <div v-if="deletableRecords.length" class="form-actions">
                  <el-button
                    type="danger"
                    :disabled="!selectedDeleteIds.length"
                    @click="run(removeSelectedRecords)"
                  >
                    删除选中（{{ selectedDeleteIds.length }}）
                  </el-button>
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

.record-write-panel,
.record-delete-panel {
  padding-top: 4px;
}

.record-section-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.block-desc {
  margin: 6px 0 0;
  font-size: 12px;
  color: #94a3b8;
  line-height: 1.5;
}

.record-form {
  padding: 4px 2px 0;
}

.field-label {
  font-weight: 600;
  color: #334155;
}

.field-type-tag {
  margin-left: 8px;
  font-size: 11px;
  color: #94a3b8;
  font-weight: 400;
}

.full-width-input {
  width: 100%;
}

.checkbox-row {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 32px;
}

.checkbox-hint {
  font-size: 13px;
  color: #64748b;
}

.url-field-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.form-actions {
  display: flex;
  gap: 10px;
  margin-top: 8px;
  padding-top: 12px;
  border-top: 1px solid #f1f5f9;
}

.advanced-collapse {
  margin-top: 16px;
  border-top: 1px dashed #e2e8f0;
}

.advanced-collapse :deep(.el-collapse-item__header) {
  font-size: 13px;
  color: #64748b;
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

  .url-field-row {
    grid-template-columns: 1fr;
  }
}
</style>
