<template>
  <div>
    <div class="page-header">
      <h2 class="page-header-title">订单列表</h2>
      <div class="page-header-actions">
        <n-button type="primary" @click="openCreateOrder">创建订单</n-button>
      </div>
    </div>
    <div class="filter-bar">
      <n-select v-model:value="filterStatus" :options="statusOptions" clearable placeholder="筛选状态" style="width:160px" />
      <n-input v-model:value="search" placeholder="搜索用户名 / 订单号" style="width:260px" clearable />
    </div>
    <n-data-table :columns="columns" :data="filtered" :pagination="{ pageSize: 20 }" :bordered="false" />

    <!-- 查看订单详情 -->
    <n-modal v-model:show="showDetail" preset="card" title="订单详情" style="width:560px">
      <template v-if="detailOrder">
        <n-descriptions :column="2" bordered label-placement="left" size="small">
          <n-descriptions-item label="订单号">{{ detailOrder.out_trade_no }}</n-descriptions-item>
          <n-descriptions-item label="用户">{{ detailOrder.username }}</n-descriptions-item>
          <n-descriptions-item label="分组">{{ detailOrder.group }}</n-descriptions-item>
          <n-descriptions-item label="状态">
            <n-tag :type="statusTag[detailOrder.status]" size="small" bordered="false">{{ statusLabel[detailOrder.status] }}</n-tag>
          </n-descriptions-item>
          <n-descriptions-item label="金额(USD)">${{ Number(detailOrder.amount_usd).toFixed(2) }}</n-descriptions-item>
          <n-descriptions-item label="金额(CNY)">¥{{ Number(detailOrder.amount_cny).toFixed(2) }}</n-descriptions-item>
          <n-descriptions-item label="汇率">{{ detailOrder.exchange_rate }}</n-descriptions-item>
          <n-descriptions-item label="支付方式">{{ detailOrder.pay_type }}</n-descriptions-item>
          <n-descriptions-item label="创建时间">{{ formatTime(detailOrder.created_at) }}</n-descriptions-item>
          <n-descriptions-item label="支付时间">{{ formatTime(detailOrder.paid_at) }}</n-descriptions-item>
          <n-descriptions-item v-if="detailOrder.token_value" label="Token" :span="2">
            <code>{{ detailOrder.token_value }}...</code>
          </n-descriptions-item>
        </n-descriptions>
      </template>
    </n-modal>

    <!-- 编辑订单 -->
    <n-modal v-model:show="showEdit" preset="card" title="编辑订单" style="width:420px">
      <n-form v-if="editForm" label-placement="left" label-width="80">
        <n-form-item label="状态">
          <n-select v-model:value="editForm.status" :options="statusOptions" />
        </n-form-item>
        <n-form-item label="分组">
          <n-input v-model:value="editForm.group" />
        </n-form-item>
        <n-form-item label="金额(USD)">
          <n-input-number v-model:value="editForm.amount_usd" :precision="2" :min="0" style="width:100%" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showEdit=false">取消</n-button>
          <n-button type="primary" @click="submitEdit">保存</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 分配 Token -->
    <n-modal v-model:show="showAssign" preset="card" title="分配 Token" style="width:480px">
      <n-form label-placement="left" label-width="80">
        <n-form-item v-for="g in assignGroups" :key="g" :label="'Token（' + g + '）'">
          <n-input v-model:value="assignTokens[g]" :placeholder="'粘贴 ' + g + ' 分组的 API Token，留空则保留原 Token'" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showAssign = false">取消</n-button>
          <n-button type="primary" :loading="assigning" @click="submitAssign">确认分配</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 创建订单 -->
    <n-modal v-model:show="showCreate" preset="card" title="创建订单" style="width:520px">
      <n-form label-placement="left" label-width="80">
        <div v-for="(item, idx) in createForm.items" :key="idx" style="display:flex;gap:12px;align-items:center;margin-bottom:12px">
          <n-select v-model:value="item.group" :options="groupOptions" placeholder="选择分组" style="width:160px" />
          <n-input-number v-model:value="item.amount_usd" :precision="2" :min="0.01" :max="1000" placeholder="金额(USD)" style="width:140px" />
          <n-button v-if="createForm.items.length > 1" quaternary type="error" size="small" @click="createForm.items.splice(idx, 1)">移除</n-button>
        </div>
        <n-button quaternary type="primary" size="small" @click="createForm.items.push({ group: '', amount_usd: 0 })">+ 添加分组</n-button>
        <div style="margin-top:16px;padding-top:12px;border-top:1px solid var(--cy-border);display:flex;justify-content:space-between">
          <span style="color:var(--cy-text-muted)">合计: ${{ totalUsd.toFixed(2) }}</span>
          <span style="color:var(--cy-accent)">≈ ¥{{ totalCny.toFixed(2) }}</span>
        </div>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showCreate=false">取消</n-button>
          <n-button type="primary" :loading="creating" @click="submitCreateOrder">立即支付</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 退款 -->
    <n-modal v-model:show="showRefund" preset="card" title="退款" style="width:420px">
      <n-form label-placement="left" label-width="100">
        <n-form-item label="订单号">{{ refundTarget.out_trade_no }}</n-form-item>
        <n-form-item label="订单金额">¥{{ Number(refundTarget.amount_cny).toFixed(2) }}</n-form-item>
        <n-form-item label="退款金额(¥)">
          <n-input-number v-model:value="refundAmount" :precision="2" :min="0.01" :max="Number(refundTarget.amount_cny)" placeholder="留空则全额退款" clearable style="width:100%" />
        </n-form-item>
        <n-form-item label="退款原因">
          <n-input v-model:value="refundReason" placeholder="可选" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showRefund = false">取消</n-button>
          <n-button type="error" :loading="refunding" @click="submitRefund">确认退款</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 退款查询 -->
    <n-modal v-model:show="showRefundQuery" preset="card" title="退款查询结果" style="width:520px">
      <n-descriptions v-if="refundQueryResult" :column="1" bordered label-placement="left" size="small">
        <n-descriptions-item label="退款单号">{{ refundQueryResult.out_refund_no }}</n-descriptions-item>
        <n-descriptions-item label="订单号">{{ refundQueryResult.out_trade_no }}</n-descriptions-item>
        <n-descriptions-item label="退款状态">
          <n-tag :type="refundStatusTag[refundQueryResult.status] || 'default'" size="small" bordered="false">
            {{ refundStatusLabel[refundQueryResult.status] || refundQueryResult.status }}
          </n-tag>
        </n-descriptions-item>
        <n-descriptions-item label="退款金额">¥{{ ((refundQueryResult.amount?.refund || 0) / 100).toFixed(2) }}</n-descriptions-item>
        <n-descriptions-item label="订单金额">¥{{ ((refundQueryResult.amount?.total || 0) / 100).toFixed(2) }}</n-descriptions-item>
        <n-descriptions-item v-if="refundQueryResult.success_time" label="退款成功时间">{{ refundQueryResult.success_time }}</n-descriptions-item>
        <n-descriptions-item v-if="refundQueryResult.reason" label="退款原因">{{ refundQueryResult.reason }}</n-descriptions-item>
      </n-descriptions>
    </n-modal>

    <!-- 二维码支付 -->
    <n-modal v-model:show="showQrcode" preset="card" title="微信扫码支付" style="width:400px">
      <div style="text-align:center">
        <p style="margin-bottom:12px;color:var(--cy-text-muted)">请使用微信扫描下方二维码完成支付</p>
        <canvas ref="qrcodeCanvas" style="margin:0 auto"></canvas>
        <p style="margin-top:12px;font-size:12px;color:var(--cy-text-dim)">订单号：{{ qrcodeOrder.out_trade_no }}</p>
        <p style="font-size:14px;font-weight:bold;color:var(--cy-text)">¥{{ qrcodeOrder.amount_cny }} (≈${{ qrcodeOrder.amount_usd }})</p>
        <n-button v-if="qrcodeOrder.status==='pending'" :loading="polling" style="margin-top:12px" @click="checkPayStatus">查询支付状态</n-button>
        <n-tag v-if="qrcodeOrder.status==='paid'||qrcodeOrder.status==='assigned'" type="success" style="margin-top:12px" bordered="false">支付成功</n-tag>
      </div>
    </n-modal>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, h, nextTick, watch } from 'vue'
import { NTag, NButton, NSpace, useMessage, useDialog } from 'naive-ui'
import QRCode from 'qrcode'
import http from '../api/http'

const message = useMessage()
const dialog = useDialog()
const orders = ref([])
const filterStatus = ref(null)
const search = ref('')
const showDetail = ref(false)
const detailOrder = ref(null)
const showEdit = ref(false)
const editForm = ref(null)
const editOrderId = ref(null)
const showAssign = ref(false)
const assignOrderId = ref(null)
const assignGroups = ref([])
const assignTokens = reactive({})
const assigning = ref(false)

const showCreate = ref(false)
const createForm = ref({ items: [{ group: '', amount_usd: 0 }] })
const creating = ref(false)
const groupOptions = ref([])
const exchangeRate = ref(7.25)

const totalUsd = computed(() => createForm.value.items.reduce((sum, i) => sum + (i.amount_usd || 0), 0))
const totalCny = computed(() => Math.round(totalUsd.value * exchangeRate.value * 100) / 100)

const showQrcode = ref(false)

// 退款
const showRefund = ref(false)
const refundTarget = ref({})
const refundAmount = ref(null)
const refundReason = ref('')
const refunding = ref(false)

// 退款查询
const showRefundQuery = ref(false)
const refundQueryResult = ref(null)
const refundStatusTag = { SUCCESS: 'success', PROCESSING: 'warning', CHANGE: 'error', CLOSED: 'default' }
const refundStatusLabel = { SUCCESS: '退款成功', PROCESSING: '退款处理中', CHANGE: '退款异常', CLOSED: '退款关闭' }

function openRefund(row) {
  refundTarget.value = row
  refundAmount.value = null
  refundReason.value = ''
  showRefund.value = true
}

async function submitRefund() {
  refunding.value = true
  try {
    const body = { reason: refundReason.value }
    if (refundAmount.value) body.refund_amount_cny = refundAmount.value
    const { data } = await http.post(`/api/pay/refund/${refundTarget.value.out_trade_no}`, body)
    message.success(`退款申请已提交，退款单号：${data.out_refund_no}`)
    showRefund.value = false
    await loadOrders()
  } catch (e) {
    message.error(e.response?.data?.detail || '退款失败')
  } finally {
    refunding.value = false
  }
}

async function queryRefundStatus(outRefundNo) {
  try {
    const { data } = await http.get(`/api/pay/refund/query/${outRefundNo}`)
    refundQueryResult.value = data
    showRefundQuery.value = true
  } catch (e) {
    message.error(e.response?.data?.detail || '查询失败')
  }
}
const qrcodeOrder = ref({})
const qrcodeCanvas = ref(null)
const polling = ref(false)

const statusOptions = [
  { label: '待支付', value: 'pending' },
  { label: '已支付', value: 'paid' },
  { label: '已分配', value: 'assigned' },
  { label: '已关闭', value: 'closed' },
  { label: '已退款', value: 'refunded' },
  { label: '退款异常', value: 'refund_change' },
]
const statusTag = { pending: 'warning', paid: 'success', assigned: 'info', closed: 'default', refunded: 'info', refund_change: 'error' }
const statusLabel = { pending: '待支付', paid: '已支付', assigned: '已分配', closed: '已关闭', refunded: '已退款', refund_change: '退款异常' }

function formatTime(v) { return v ? v.replace('T', ' ').slice(0, 19) : '-' }

const filtered = computed(() => {
  let list = orders.value
  if (filterStatus.value) list = list.filter(o => o.status === filterStatus.value)
  if (search.value) {
    const q = search.value.toLowerCase()
    list = list.filter(o =>
      (o.username || '').toLowerCase().includes(q) ||
      (o.out_trade_no || '').toLowerCase().includes(q)
    )
  }
  return list
})

const columns = [
  { title: '订单号', key: 'out_trade_no', width: 180, ellipsis: true },
  { title: '用户', key: 'username', width: 100 },
  { title: '分组', key: 'group', width: 120,
    render: row => h(NTag, { size: 'small', bordered: false }, { default: () => row.group }) },
  { title: '金额(USD)', key: 'amount_usd', width: 90,
    render: row => `$${Number(row.amount_usd).toFixed(2)}` },
  { title: '状态', key: 'status', width: 80,
    render: row => h(NTag, { type: statusTag[row.status] || 'default', size: 'small', bordered: false },
      { default: () => statusLabel[row.status] || row.status }) },
  { title: '时间', key: 'created_at', width: 150,
    render: row => formatTime(row.created_at) },
  { title: '操作', key: 'actions', width: 260,
    render: row => h(NSpace, { size: 'small' }, { default: () => {
      const btns = [
        h(NButton, { size: 'small', quaternary: true, type: 'info', onClick: () => viewOrder(row) }, { default: () => '查看' }),
        h(NButton, { size: 'small', quaternary: true, type: 'warning', onClick: () => openEdit(row) }, { default: () => '编辑' }),
      ]
      if (row.status === 'paid') {
        btns.push(h(NButton, { size: 'small', quaternary: true, type: 'success', onClick: () => openAssign(row) }, { default: () => '分配' }))
      }
      if (row.status === 'pending') {
        btns.push(h(NButton, { size: 'small', quaternary: true, type: 'error', onClick: () => closeOrder(row) }, { default: () => '关闭' }))
      }
      if (row.status === 'paid' || row.status === 'assigned') {
        btns.push(h(NButton, { size: 'small', quaternary: true, type: 'error', onClick: () => openRefund(row) }, { default: () => '退款' }))
      }
      if (row.status === 'refunded' || row.status === 'refund_change') {
        btns.push(h(NButton, { size: 'small', quaternary: true, type: 'info', onClick: () => queryRefundStatus(row.out_refund_no) }, { default: () => '退款查询' }))
      }
      if (row.status !== 'paid' && row.status !== 'assigned') {
        btns.push(h(NButton, { size: 'small', quaternary: true, type: 'error', onClick: () => deleteOrder(row) }, { default: () => '删除' }))
      }
      return btns
    }})
  },
]

async function loadOrders() {
  const { data } = await http.get('/api/admin/orders')
  orders.value = data
}

function viewOrder(row) { detailOrder.value = row; showDetail.value = true }

function openEdit(row) {
  editOrderId.value = row.id
  editForm.value = { status: row.status, group: row.group, amount_usd: Number(row.amount_usd) }
  showEdit.value = true
}

async function submitEdit() {
  try {
    await http.put(`/api/admin/orders/${editOrderId.value}`, editForm.value)
    message.success('保存成功')
    showEdit.value = false
    await loadOrders()
  } catch (e) { message.error(e.response?.data?.detail || '保存失败') }
}

function openAssign(row) {
  assignOrderId.value = row.id
  assignGroups.value = (row.group || '').split(',').map(g => g.trim()).filter(Boolean)
  for (const key of Object.keys(assignTokens)) { delete assignTokens[key] }
  for (const g of assignGroups.value) { assignTokens[g] = '' }
  showAssign.value = true
}

async function submitAssign() {
  assigning.value = true
  try {
    const tokens = {}
    for (const g of assignGroups.value) { tokens[g] = (assignTokens[g] || '').trim() }
    await http.post(`/api/admin/orders/${assignOrderId.value}/assign`, { tokens })
    message.success('操作成功')
    showAssign.value = false
    await loadOrders()
  } catch (e) { message.error(e.response?.data?.detail || '操作失败') }
  finally { assigning.value = false }
}

async function openCreateOrder() {
  try {
    const [groupsRes, packagesRes] = await Promise.all([
      http.get('/api/admin/groups'),
      http.get('/api/pay/packages')
    ])
    groupOptions.value = groupsRes.data.map(g => ({ label: g.name, value: g.name }))
    if (packagesRes.data.exchange_rate) {
      exchangeRate.value = packagesRes.data.exchange_rate
    }
    if (groupOptions.value.length) {
      createForm.value.items = [{ group: groupOptions.value[0].value, amount_usd: 0 }]
    }
  } catch {}
  showCreate.value = true
}

async function submitCreateOrder() {
  const validItems = createForm.value.items.filter(i => i.group && i.amount_usd > 0)
  if (!validItems.length) return message.warning('请至少填写一个分组的金额')
  creating.value = true
  try {
    const { data } = await http.post('/api/admin/orders/create', { items: validItems })
    showCreate.value = false
    qrcodeOrder.value = data
    showQrcode.value = true
    await nextTick()
    if (data.code_url && qrcodeCanvas.value) {
      QRCode.toCanvas(qrcodeCanvas.value, data.code_url, { width: 200, margin: 2 })
    }
    await loadOrders()
  } catch (e) {
    message.error(e.response?.data?.detail || '创建订单失败')
  } finally { creating.value = false }
}

async function checkPayStatus() {
  if (!qrcodeOrder.value.out_trade_no) return
  polling.value = true
  try {
    const { data } = await http.get(`/api/admin/orders/query_pay/${qrcodeOrder.value.out_trade_no}`)
    if (data.status === 'paid' || data.status === 'assigned') {
      qrcodeOrder.value.status = 'paid'
      message.success('支付成功')
      await loadOrders()
    } else {
      message.info('尚未支付，请扫码后再查询')
    }
  } catch (e) { message.error(e.response?.data?.detail || '查询失败') }
  finally { polling.value = false }
}

function closeOrder(row) {
  dialog.warning({ title: '关闭订单', content: `确定关闭订单 ${row.out_trade_no}？`,
    positiveText: '关闭', negativeText: '取消',
    onPositiveClick: async () => {
      try { await http.post(`/api/admin/orders/${row.id}/close`); message.success('已关闭'); await loadOrders() }
      catch (e) { message.error(e.response?.data?.detail || '操作失败') }
    }
  })
}

function deleteOrder(row) {
  dialog.error({ title: '删除订单', content: `确定删除订单 ${row.out_trade_no}？此操作不可恢复。`,
    positiveText: '删除', negativeText: '取消',
    onPositiveClick: async () => {
      try { await http.delete(`/api/admin/orders/${row.id}`); message.success('已删除'); await loadOrders() }
      catch (e) { message.error(e.response?.data?.detail || '删除失败') }
    }
  })
}

onMounted(loadOrders)
</script>