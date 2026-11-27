<template>
  <section class="page" :data-module="meta.key">
    <header class="page-head">
      <div>
        <h2>{{ meta.name }}</h2>
        <p class="page-desc">{{ meta.desc }}</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" data-testid="open-create" type="button" @click="openCreate">
          登记{{ meta.entity }}
        </button>
        <button class="btn" data-testid="export" type="button" @click="exportRows">
          导出{{ meta.name }}清单
        </button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <p class="status-legend">
      <span v-for="item in statusSummary" :key="item.status" class="legend-item">
        {{ item.status }}：{{ item.count }}
      </span>
    </p>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :data-testid="`filter-${field}`" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" data-testid="query" type="submit">查询</button>
      <button class="btn ghost" data-testid="reset" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in meta.fields" :key="column">{{ column }}</th>
          <th>当前状态</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :data-testid="`row-${row.id}`" :data-status="String(row.status)">
          <td v-for="column in meta.fields" :key="column">{{ row[column] ?? '—' }}</td>
          <td>{{ row.status }}</td>
          <td class="row-actions">
            <button
              v-for="action in meta.actions"
              :key="action"
              class="link"
              type="button"
              :data-testid="`action-${row.id}-${action}`"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <button
              v-if="meta.packageFlow"
              class="link"
              type="button"
              :data-testid="`export-package-${row.id}`"
              @click="exportPackage(row)"
            >
              导出证据包
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="meta.fields.length + 2" class="empty-state">
            暂无{{ meta.name }}数据，可先登记{{ meta.entity }}
          </td>
        </tr>
      </tbody>
    </table>

    <div v-if="showCreate" class="modal-backdrop" data-testid="create-modal">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记{{ meta.entity }}</h3>
        <label v-for="field in meta.fields" :key="field" class="create-field">
          <span>{{ field }}</span>
          <input v-model="createValues[field]" :data-testid="`create-${field}`" required />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showCreate = false">取消</button>
          <button class="btn primary" data-testid="submit-create" type="submit" :disabled="creating">
            {{ creating ? '提交中…' : '确认登记' }}
          </button>
        </div>
      </form>
    </div>

    <div v-if="submitRow" class="modal-backdrop" data-testid="submit-modal">
      <div class="modal">
        <h3>上报评审受理 — {{ submitRow['成果名称'] }}</h3>
        <p class="package-hint">请输入评审员交回的材料包编号，先核验包状态再确认上报。</p>
        <label class="create-field">
          <span>材料包编号</span>
          <input v-model="packageNo" data-testid="package-no" placeholder="如 K-1" />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" data-testid="verify-package" :disabled="verifying" @click="verifyPackage">
            {{ verifying ? '核验中…' : '核验材料包' }}
          </button>
        </div>
        <div v-if="packageView" class="package-view" data-testid="package-view" :data-status="packageView.状态">
          <p>
            <strong>{{ packageView.包编号 }}</strong>
            <span class="package-status">{{ packageView.状态 }}</span>
          </p>
          <ul class="package-materials">
            <li v-for="mat in packageView.材料" :key="mat.材料ID">
              {{ mat.档案类型 }}《{{ mat.名称 }}》（档案 #{{ mat.材料ID }}，导出时{{ mat.导出时状态 }}）
            </li>
          </ul>
          <p v-if="packageView.失效原因" class="error-text">失效原因：{{ packageView.失效原因 }}</p>
          <p class="package-tip">{{ packageView.提示 }}</p>
        </div>
        <div class="page-actions">
          <button class="btn" type="button" @click="closeSubmit">取消</button>
          <button
            class="btn primary"
            data-testid="confirm-submit"
            type="button"
            :disabled="submitting || !packageView || !packageView.可受理"
            @click="confirmSubmit"
          >
            {{ submitting ? '提交中…' : '确认上报' }}
          </button>
        </div>
      </div>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条{{ meta.name }}记录</span>
      <span v-if="noticeMessage" class="notice-text" data-testid="notice">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import {
  createEntry,
  downloadEntries,
  exportAwardPackage,
  listEntries,
  moduleMeta,
  runAction as applyAction,
  submitAwardWithPackage,
  verifyAwardPackage,
} from '@/api/backend-service'
import type { AwardPackageView, EntryRow } from '@/data/types'

const props = defineProps<{ moduleKey: string }>()
const meta = moduleMeta(props.moduleKey)
const rows = ref<EntryRow[]>([])
const total = ref(0)
const errorMessage = ref('')
const noticeMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = meta.fields.slice(0, 3)
const showCreate = ref(false)
const creating = ref(false)
const createValues = ref<Record<string, string>>({})
// 送审材料包流程（教学成果申报）：凭包受理上报单
const submitRow = ref<EntryRow | null>(null)
const packageNo = ref('')
const packageView = ref<AwardPackageView | null>(null)
const verifying = ref(false)
const submitting = ref(false)
const stats = computed(() => [
  { label: meta.metrics[0], value: total.value },
  { label: meta.metrics[1], value: rows.value.filter((row) => row.status === meta.statuses[1]).length },
  {
    label: meta.metrics[2],
    value: rows.value.filter((row) => row.status === meta.statuses[meta.statuses.length - 1]).length,
  },
])
const statusSummary = computed(() =>
  meta.statuses.map((status) => ({
    status,
    count: rows.value.filter((row) => String(row.status) === status).length,
  })),
)

function resetFilters() {
  filters.value = {}
  noticeMessage.value = ''
  void reload()
}

async function exportRows() {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    await downloadEntries(meta.key, filters.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '导出失败'
  }
}

function openCreate() {
  createValues.value = Object.fromEntries(meta.fields.map((field) => [field, '']))
  errorMessage.value = ''
  noticeMessage.value = ''
  showCreate.value = true
}

async function submitCreate() {
  creating.value = true
  errorMessage.value = ''
  try {
    const result = await createEntry(meta.key, createValues.value)
    if (!result.ok) throw new Error(result.message)
    showCreate.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记失败'
  } finally {
    creating.value = false
  }
}

async function runAction(action: string, row: EntryRow) {
  errorMessage.value = ''
  noticeMessage.value = ''
  // 教学成果申报的上报评审必须凭送审材料包编号，打开受理上报单
  if (meta.packageFlow && action === '上报评审') {
    openSubmit(row)
    return
  }
  try {
    const result = await applyAction(meta.key, Number(row.id), action)
    if (!result.ok) throw new Error(result.message)
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '操作失败'
  }
}

async function exportPackage(row: EntryRow) {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const result = await exportAwardPackage(Number(row.id))
    if (!result.ok) throw new Error(result.message)
    noticeMessage.value = result.message
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '导出证据包失败'
  }
}

function openSubmit(row: EntryRow) {
  submitRow.value = row
  packageNo.value = ''
  packageView.value = null
  errorMessage.value = ''
  noticeMessage.value = ''
}

function closeSubmit() {
  submitRow.value = null
  packageView.value = null
}

async function verifyPackage() {
  if (!packageNo.value.trim()) {
    errorMessage.value = '请先填写材料包编号'
    return
  }
  verifying.value = true
  errorMessage.value = ''
  try {
    const result = await verifyAwardPackage(packageNo.value.trim())
    if (!result.ok || !result.package) throw new Error(result.message)
    packageView.value = result.package
  } catch (error) {
    packageView.value = null
    errorMessage.value = error instanceof Error ? error.message : '材料包核验失败'
  } finally {
    verifying.value = false
  }
}

async function confirmSubmit() {
  if (!submitRow.value) return
  submitting.value = true
  errorMessage.value = ''
  try {
    const result = await submitAwardWithPackage(Number(submitRow.value.id), packageNo.value.trim())
    if (!result.ok) throw new Error(result.message)
    noticeMessage.value = result.message
    closeSubmit()
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '上报受理失败'
  } finally {
    submitting.value = false
  }
}

async function reload() {
  errorMessage.value = ''
  try {
    const payload = await listEntries(meta.key, filters.value)
    rows.value = payload.items
    total.value = payload.total
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '业务列表读取失败'
  }
}

onMounted(reload)
</script>
