<template>
  <div>
    <div class="page-header">
      <div class="page-header-left">
        <h2 class="page-header-title">交易订单</h2>
        <p class="page-header-subtitle">余额充值订单；付款金额（¥）与到账金额（$）成对展示，退款需审核后原路退回</p>
      </div>
      <div class="page-header-actions">
        <n-button type="primary" @click="openCreateOrder">创建订单</n-button>
      </div>
    </div>

    <div class="filter-bar">
      <n-select v-model:value="filterStatus" :options="statusOptions" clearable placeholder="筛选状态" style="width:160px" />
      <n-input v-model:value="search" placeholder="搜索用户名 / 订单号" style="width:260px" clearable />
    </div>

    <n-data-table
      :columns="columns"
      :data="filtered"
      :pagination="{ pageSize: 20 }"
      :row-key="row => row.id"
      :bordered="false"
    />

    <!-- 查看订单详情 -->
    <n-modal v-model:show="showDetail" preset="card" title="订单详情" style="width:560px">
      <n-descriptions v-if="detailOrder" :column="2" bordered label-placement="left" size="small">
        <n-descriptions-item label="订单号" :span="2">{{ detailOrder.out_trade_no }}</n-descriptions-item>
        <n-descriptions-item label="用户">{{ detailOrder.username || '-' }}</n-descriptions-item>
        <n-descriptions-item label="状态">
          <n-tag :type="statusTag[detailOrder.status] || 'default'" size="small" :bordered="false">
            {{ statusLabel[detailOrder.status] || detailOrder.status }}
          </n-tag>
        </n-descriptions-item>
        <n-descriptions-item label="到账金额(USD)">${{ Number(detailOrder.amount_usd).toFixed(2) }}</n-descriptions-item>
        <n-descriptions-item label="付款金额(CNY)">¥{{ Number(detailOrder.amount_cny).toFixed(2) }}</n-descriptions-item>
        <n-descriptions-item label="汇率">{{ detailOrder.exchange_rate ?? '-' }}</n-descriptions-item>
        <n-descriptions-item label="已退款">¥{{ Number(detailOrder.refunded_cny || 0).toFixed(2) }}</n-descriptions-item>
        <n-descriptions-item label="剩余可退款">¥{{ Number(detailOrder.remaining_refundable_cny ?? (detailOrder.amount_cny - (detailOrder.refunded_cny || 0))).toFixed(2) }}</n-descriptions-item>
        <n-descriptions-item label="支付方式">{{ detailOrder.pay_type || '-' }}</n-descriptions-item>
        <n-descriptions-item label="分组（历史）">{{ detailOrder.group || '-' }}</n-descriptions-item>
        <n-descriptions-item label="微信支付单号">{{ detailOrder.trade_no || '-' }}</n-descriptions-item>
        <n-descriptions-item label="创建时间">{{ formatTime(detailOrder.created_at) }}</n-descriptions-item>
        <n-descriptions-item label="支付时间">{{ formatTime(detailOrder.paid_at) }}</n-descriptions-item>
        <n-descriptions-item v-if="detailOrder.refund_request" label="退款申请" :span="2">
          <refund-request-inline :req="detailOrder.refund_request" />
        </n-descriptions-item>
      </n-descriptions>
    </n-modal>

    <!-- 编辑订单 -->
    <n-modal v-model:show="showEdit" preset="card" title="编辑订单" style="width:420px">
      <n-form v-if="editForm" label-placement="left" label-width="80">
        <n-form-item label="状态">
          <n-select v-model:value="editForm.status" :options="statusOptions" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showEdit=false">取消</n-button>
          <n-button type="primary" @click="submitEdit">保存</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 创建订单 -->
    <n-modal v-model:show="showCreate" preset="card" title="创建充值订单" style="width:520px">
      <n-form label-placement="left" label-width="100">
        <n-form-item label="金额 (USD)">
          <n-input-number
            v-model:value="createForm.amount_usd"
            :precision="2" :min="0.01" :max="100000"
            placeholder="充值金额"
            style="width:100%"
          />
        </n-form-item>
        <n-form-item label="目标用户">
          <n-select
            v-model:value="createForm.user_id"
            :options="userOptions"
            :loading="loadingUsers"
            filterable
            clearable
            placeholder="不选则为第一个用户"
          />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showCreate=false">取消</n-button>
          <n-button type="primary" :loading="creating" @click="submitCreateOrder">立即支付</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 退款申请审核（用户提交的申请） -->
    <n-modal v-model:show="showReview" preset="card" title="退款申请审核" style="width:560px">
      <n-descriptions v-if="reviewSummary" :column="2" bordered label-placement="left" size="small">
        <n-descriptions-item label="订单号" :span="2">{{ reviewSummary.out_trade_no }}</n-descriptions-item>
        <n-descriptions-item label="用户">{{ reviewSummary.username || '-' }}</n-descriptions-item>
        <n-descriptions-item label="申请时间">{{ formatTime(reviewSummary.refund_request?.requested_at) }}</n-descriptions-item>
        <n-descriptions-item label="充值额度">${{ Number(reviewSummary.amount_usd).toFixed(2) }}</n-descriptions-item>
        <n-descriptions-item label="微信实付">¥{{ Number(reviewSummary.amount_cny).toFixed(2) }}</n-descriptions-item>
        <n-descriptions-item label="申请退款金额">¥{{ Number(reviewSummary.refund_request?.requested_amount_cny || reviewSummary.remaining_refundable_cny).toFixed(2) }}</n-descriptions-item>
        <n-descriptions-item label="对应 USD 冲正">${{ Number(reviewSummary.refund_request?.requested_amount_usd || reviewSummary.max_usd_reversal).toFixed(2) }}</n-descriptions-item>
        <n-descriptions-item label="用户现金余额">${{ Number(reviewSummary.user_balance_usd || 0).toFixed(2) }}</n-descriptions-item>
        <n-descriptions-item label="试用额度">${{ Number(reviewSummary.user_trial_credit_usd || 0).toFixed(2) }}</n-descriptions-item>
        <n-descriptions-item label="订单已退款">¥{{ Number(reviewSummary.refunded_cny).toFixed(2) }}</n-descriptions-item>
        <n-descriptions-item label="剩余可退款">¥{{ Number(reviewSummary.remaining_refundable_cny).toFixed(2) }}</n-descriptions-item>
        <n-descriptions-item label="退款理由" :span="2">{{ reviewSummary.refund_request?.reason || '（未填写）' }}</n-descriptions-item>
      </n-descriptions>
      <n-alert v-if="reviewBalanceWarning" type="warning" style="margin-top:12px" :bordered="false">
        用户当前可冲正余额不足（$不足部分将在流水中如实记录为少扣），请人工确认后处理。
      </n-alert>
      <n-form label-placement="left" label-width="90" style="margin-top:12px">
        <n-form-item label="审核备注">
          <n-input v-model:value="reviewNote" placeholder="拒绝时必填，批准时可选" type="textarea" :rows="2" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button type="warning" :loading="reviewing" @click="submitReject">拒绝退款</n-button>
          <n-button type="error" :loading="reviewing" @click="submitApprove">批准退款</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 管理员主动退款 -->
    <n-modal v-model:show="showRefund" preset="card" title="退款" style="width:460px">
      <n-descriptions v-if="refundSummary" :column="2" bordered label-placement="left" size="small">
        <n-descriptions-item label="订单号" :span="2">{{ refundSummary.out_trade_no }}</n-descriptions-item>
        <n-descriptions-item label="充值额度">${{ Number(refundSummary.amount_usd).toFixed(2) }}</n-descriptions-item>
        <n-descriptions-item label="微信实付">¥{{ Number(refundSummary.amount_cny).toFixed(2) }}</n-descriptions-item>
        <n-descriptions-item label="已退款">¥{{ Number(refundSummary.refunded_cny).toFixed(2) }}</n-descriptions-item>
        <n-descriptions-item label="剩余可退款">¥{{ Number(refundSummary.remaining_refundable_cny).toFixed(2) }}</n-descriptions-item>
        <n-descriptions-item label="对应最大 USD 冲正" :span="2">${{ Number(refundSummary.max_usd_reversal).toFixed(2) }}</n-descriptions-item>
      </n-descriptions>
      <n-form label-placement="left" label-width="100" style="margin-top:12px">
        <n-form-item label="退款金额(¥)">
          <n-input-group>
            <n-input-number
              v-model:value="refundAmount"
              :precision="2" :min="0.01" :max="Number(refundSummary?.remaining_refundable_cny || 0)"
              placeholder="留空则全额退款" clearable style="width:100%"
            />
            <n-button type="primary" secondary @click="fillFullRefund">全额退款</n-button>
          </n-input-group>
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
          <n-tag :type="refundStatusTag[refundQueryResult.status] || 'default'" size="small" :bordered="false">
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
        <p style="margin-bottom:12px;color:var(--cy-text-muted)">请使用微信扫描下方二维码完成支付，支付成功后余额自动入账</p>
        <canvas ref="qrcodeCanvas" style="margin:0 auto"></canvas>
        <p style="margin-top:12px;font-size:12px;color:var(--cy-text-dim)">订单号：{{ qrcodeOrder.out_trade_no }}</p>
        <p style="font-size:14px;font-weight:bold;color:var(--cy-text)">付款 ¥{{ qrcodeOrder.amount_cny }} → 到账 ${{ qrcodeOrder.amount_usd }}</p>
        <n-button v-if="qrcodeOrder.status==='pending'" :loading="polling" style="margin-top:12px" @click="checkPayStatus">查询支付状态</n-button>
        <n-tag v-if="qrcodeOrder.status==='paid'||qrcodeOrder.status==='assigned'" type="success" style="margin-top:12px" :bordered="false">支付成功</n-tag>
      </div>
    </n-modal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, h, nextTick, defineComponent } from 'vue'
import { NTag, NButton, NSpace, useMessage, useDialog } from 'naive-ui'
import QRCode from 'qrcode'
import http from '../api/http'
import { formatTime } from '../utils/time'

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

// 创建订单
const showCreate = ref(false)
const createForm = ref({ amount_usd: null, user_id: null })
const creating = ref(false)
const userOptions = ref([])
const loadingUsers = ref(false)

// 二维码支付
const showQrcode = ref(false)
const qrcodeOrder = ref({})
const qrcodeCanvas = ref(null)
const polling = ref(false)

// 退款申请审核
const showReview = ref(false)
const reviewSummary = ref(null)
const reviewNote = ref('')
const reviewing = ref(false)

// 管理员主动退款
const showRefund = ref(false)
const refundSummary = ref(null)
const refundAmount = ref(null)
const refundReason = ref('')
const refunding = ref(false)

// 退款查询
const showRefundQuery = ref(false)
const refundQueryResult = ref(null)
const refundStatusTag = { SUCCESS: 'success', PROCESSING: 'warning', CHANGE: 'error', CLOSED: 'default', ABNORMAL: 'error' }
const refundStatusLabel = { SUCCESS: '退款成功', PROCESSING: '退款处理中', CHANGE: '退款异常', CLOSED: '退款关闭', ABNORMAL: '退款异常' }

const reqStatusTag = { requested: 'warning', approved: 'info', processing: 'warning', success: 'success', rejected: 'default', failed: 'error' }
const reqStatusLabel = { requested: '待审核', approved: '已批准', processing: '微信处理中', success: '退款成功', rejected: '已拒绝', failed: '退款失败' }

const RefundRequestInline = defineComponent({
  props: { req: { type: Object, required: true } },
  setup(props) {
    return () => h('span', { style: 'display:inline-flex;align-items:center;gap:8px;flex-wrap:wrap' }, [
      h(NTag, { type: reqStatusTag[props.req.status] || 'default', size: 'small', bordered: false },
        { default: () => reqStatusLabel[props.req.status] || props.req.status }),
      props.req.reason ? h('span', { style: 'font-size:12px;color:var(--cy-text-muted)' }, `理由：${props.req.reason}`) : null,
      props.req.review_note ? h('span', { style: 'font-size:12px;color:var(--cy-text-muted)' }, `审核：${props.req.review_note}`) : null,
      props.req.failure_reason ? h('span', { style: 'font-size:12px;color:var(--cy-danger)' }, `失败：${props.req.failure_reason}`) : null,
    ])
  },
})

const statusOptions = [
  { label: '待支付', value: 'pending' },
  { label: '已支付', value: 'paid' },
  { label: '已入账', value: 'assigned' },
  { label: '退款待审核', value: 'refund_requested' },
  { label: '退款处理中', value: 'refunding' },
  { label: '已部分退款', value: 'partially_refunded' },
  { label: '已退款', value: 'refunded' },
  { label: '已关闭', value: 'closed' },
  { label: '退款异常', value: 'refund_change' },
]
const statusTag = {
  pending: 'warning', paid: 'success', assigned: 'info',
  refund_requested: 'warning', refunding: 'warning', partially_refunded: 'info',
  refunded: 'default', closed: 'default', refund_change: 'error',
}
const statusLabel = {
  pending: '待支付', paid: '已支付', assigned: '已入账',
  refund_requested: '退款待审核', refunding: '退款处理中', partially_refunded: '已部分退款',
  refunded: '已退款', closed: '已关闭', refund_change: '退款异常',
}

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
  { title: '订单号', key: 'out_trade_no', width: 200, ellipsis: true },
  { title: '用户', key: 'username', width: 110, render: row => row.username || '-' },
  { title: '付款 / 到账', key: 'amount', width: 150,
    render: row => h('div', { style: 'line-height:1.4' }, [
      h('div', { style: 'font-weight:600' }, `¥${Number(row.amount_cny).toFixed(2)}`),
      h('div', { style: 'color:var(--cy-text-muted);font-size:12px' }, `$${Number(row.amount_usd).toFixed(2)}`),
    ]) },
  { title: '已退款', key: 'refunded_cny', width: 90,
    render: row => Number(row.refunded_cny) > 0
      ? h('span', { style: 'color:var(--cy-text-muted)' }, `¥${Number(row.refunded_cny).toFixed(2)}`)
      : '-' },
  { title: '状态', key: 'status', width: 120,
    render: row => h('div', { style: 'display:flex;flex-direction:column;gap:4px' }, [
      h(NTag, { type: statusTag[row.status] || 'default', size: 'small', bordered: false },
        { default: () => statusLabel[row.status] || row.status }),
      row.refund_request && row.refund_request.status !== 'success'
        ? h(NTag, { type: reqStatusTag[row.refund_request.status] || 'default', size: 'tiny', bordered: false },
            { default: () => `申请：${reqStatusLabel[row.refund_request.status] || row.refund_request.status}` })
        : null,
    ]) },
  { title: '创建时间', key: 'created_at', width: 150,
    render: row => formatTime(row.created_at) },
  { title: '操作', key: 'actions', width: 260,
    render: row => h(NSpace, { size: 'small' }, { default: () => {
      const btns = [
        h(NButton, { size: 'small', quaternary: true, type: 'info', onClick: () => viewOrder(row) }, { default: () => '查看' }),
      ]
      if (row.status === 'refund_requested') {
        btns.push(h(NButton, { size: 'small', quaternary: true, type: 'warning', onClick: () => openReview(row) }, { default: () => '审核退款' }))
      }
      if (row.status === 'refunding') {
        btns.push(h(NButton, { size: 'small', quaternary: true, type: 'success', onClick: () => queryRefundStatus(row.out_refund_no) }, { default: () => '同步退款状态' }))
      }
      if (['paid', 'assigned', 'partially_refunded'].includes(row.status)) {
        btns.push(h(NButton, { size: 'small', quaternary: true, type: 'error', onClick: () => openRefund(row) }, { default: () => '退款' }))
      }
      if (['refunded', 'refund_change', 'partially_refunded'].includes(row.status)) {
        btns.push(h(NButton, { size: 'small', quaternary: true, type: 'info', onClick: () => queryRefundStatus(row.out_refund_no) }, { default: () => '退款查询' }))
      }
      if (row.status === 'pending') {
        btns.push(h(NButton, { size: 'small', quaternary: true, type: 'error', onClick: () => closeOrder(row) }, { default: () => '关闭' }))
      }
      if (!['paid', 'assigned', 'refund_requested', 'refunding'].includes(row.status)) {
        btns.push(h(NButton, { size: 'small', quaternary: true, type: 'error', onClick: () => deleteOrder(row) }, { default: () => '删除' }))
      }
      return btns
    }})
  },
]

async function loadOrders() {
  try {
    const { data } = await http.get('/api/admin/orders')
    orders.value = data
  } catch (e) {
    message.error(e.response?.data?.detail || '加载订单失败')
  }
}

function viewOrder(row) { detailOrder.value = row; showDetail.value = true }

function openEdit(row) {
  editOrderId.value = row.id
  editForm.value = { status: row.status }
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

async function openCreateOrder() {
  createForm.value = { amount_usd: null, user_id: null }
  loadingUsers.value = true
  try {
    const { data } = await http.get('/api/admin/users')
    userOptions.value = data.map(u => ({
      label: `${u.username}${u.email ? ' (' + u.email + ')' : ''}`,
      value: u.id,
    }))
  } catch {
    userOptions.value = []
  } finally {
    loadingUsers.value = false
  }
  showCreate.value = true
}

async function submitCreateOrder() {
  if (!createForm.value.amount_usd || createForm.value.amount_usd <= 0) {
    return message.warning('请输入充值金额')
  }
  creating.value = true
  try {
    const body = { amount_usd: createForm.value.amount_usd }
    if (createForm.value.user_id) body.user_id = createForm.value.user_id
    const { data } = await http.post('/api/admin/orders/create', body)
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
      message.success('支付成功，余额已自动入账')
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

// ── 退款申请审核 ──────────────────────────────────────────────────

const reviewBalanceWarning = computed(() => {
  if (!reviewSummary.value) return false
  const bal = Number(reviewSummary.value.user_balance_usd || 0)
  const need = Number(reviewSummary.value.refund_request?.requested_amount_usd || reviewSummary.value.max_usd_reversal || 0)
  return bal < need
})

async function openReview(row) {
  reviewNote.value = ''
  try {
    const { data } = await http.get(`/api/admin/orders/${row.id}/refund/summary`)
    reviewSummary.value = data
    showReview.value = true
  } catch (e) {
    message.error(e.response?.data?.detail || '加载退款申请失败')
  }
}

async function submitApprove() {
  if (!reviewSummary.value) return
  const s = reviewSummary.value
  reviewing.value = true
  try {
    const body = {}
    if (reviewNote.value.trim()) body.review_note = reviewNote.value.trim()
    const { data } = await http.post(`/api/admin/orders/${s.order_id}/refund/approve`, body)
    message.success(data.message || '退款已批准')
    showReview.value = false
    await loadOrders()
  } catch (e) {
    message.error(e.response?.data?.detail || '退款审批失败')
  } finally { reviewing.value = false }
}

async function submitReject() {
  if (!reviewSummary.value) return
  if (!reviewNote.value.trim()) {
    return message.warning('拒绝退款必须填写原因')
  }
  const s = reviewSummary.value
  reviewing.value = true
  try {
    const { data } = await http.post(`/api/admin/orders/${s.order_id}/refund/reject`, {
      review_note: reviewNote.value.trim(),
    })
    message.success(data.message || '退款已拒绝')
    showReview.value = false
    await loadOrders()
  } catch (e) {
    message.error(e.response?.data?.detail || '操作失败')
  } finally { reviewing.value = false }
}

// ── 管理员主动退款 ────────────────────────────────────────────────

async function openRefund(row) {
  refundAmount.value = null
  refundReason.value = ''
  try {
    const { data } = await http.get(`/api/admin/orders/${row.id}/refund/summary`)
    refundSummary.value = data
    showRefund.value = true
  } catch (e) {
    message.error(e.response?.data?.detail || '加载退款信息失败')
  }
}

function fillFullRefund() {
  if (!refundSummary.value) return
  refundAmount.value = Number(Number(refundSummary.value.remaining_refundable_cny).toFixed(2))
}

async function submitRefund() {
  if (!refundSummary.value) return
  const s = refundSummary.value
  const amount = refundAmount.value ?? Number(s.remaining_refundable_cny)
  if (!amount || amount <= 0) return message.warning('请输入退款金额')
  if (amount > Number(s.remaining_refundable_cny)) return message.warning('退款金额不能超过剩余可退款金额')

  dialog.warning({
    title: '确认退款',
    content: `确认退款 ¥${amount.toFixed(2)}？退款将原路退回用户微信支付账户，并在微信确认成功后冲正对应 USD 余额。`,
    positiveText: '确认退款', negativeText: '取消',
    onPositiveClick: async () => {
      refunding.value = true
      try {
        const body = { reason: refundReason.value || undefined }
        if (refundAmount.value) body.refund_amount_cny = refundAmount.value
        const { data } = await http.post(`/api/admin/orders/${s.order_id}/refund`, body)
        message.success(data.message || '退款已提交')
        showRefund.value = false
        await loadOrders()
      } catch (e) {
        message.error(e.response?.data?.detail || '退款失败')
      } finally {
        refunding.value = false
      }
    },
  })
}

async function queryRefundStatus(outRefundNo) {
  if (!outRefundNo) return message.warning('该订单无退款单号')
  try {
    const { data } = await http.get(`/api/pay/refund/query/${outRefundNo}`)
    refundQueryResult.value = data
    showRefundQuery.value = true
    await loadOrders()
  } catch (e) {
    message.error(e.response?.data?.detail || '查询失败')
  }
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
