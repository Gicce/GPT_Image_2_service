---
type: decision
module: server
visibility: internal
---

# ADR-018：CY Credits Billing V1（点数计费 + 报价冻结 + 试用领取 + 经营账）

日期：2026-08-24
状态：已实施（V4.2.0，服务端 + 管理后台 + 客户端同步落地）
关联：ADR-003（余额统一）、ADR-015（人物替换，同版发布）、cyimagepro-ui Skill 14.0.0 规则 22 / patterns §21-§24

## 背景

V4.1 及之前的计费体系以美元为用户侧单位（`users.balance_usd`，充值按实时汇率换算 USD，
生成按 `ai_models.price_per_call`（$0.07）扣费）。存在七个结构性问题：

1. 用户要理解 美元余额 / 人民币付款 / 实时汇率 三层换算，认知成本高；
2. 无生成前报价——authorize 才知道价格，且取价是"任务开始时点"而非独立报价冻结；
3. 上游采购成本完全无记录，无成本/毛利账，无法按任务查账；
4. 试用按账号发放，删除账号重注册可重复领取；
5. 设备只存 Redis TTL（180s），无历史，且后台相对时间用管理员浏览器时钟计算，
   服务器时钟偏移时出现「-28 秒前」负数；
6. 汇率来源（实时 API + 1h 缓存）与 UI 文案（无来源标注）不一致；
7. Token「默认」徽章不区分正式/试用角色。

## 决策

### 1. CY 点数为唯一用户侧计费单位

- `¥1 = credits_per_cny 点`（默认 100），存 `system_config` K-V 表，管理后台可改；
- 钱包三类点数：`users.paid_credits / trial_credits / gift_credits`（INT）；
- 消费顺序 **trial → gift → paid**，唯一入口 `billing.consume_credits()`；
- **USD 列降级为兼容镜像**：每次点数变动后按 `legacy_usd_to_credits`（默认 700）回写
  `balance_usd / trial_credit_usd`，供 V4.0.x 旧客户端继续展示，不再作为业务真相。

### 2. 旧余额迁移（三步走）

`v4.2_credits_billing` 一次性迁移：`round(balance_usd × 700)` → paid_credits。
生产必须 preview（只读报告：用户数/旧总余额/总点数/异常数）→ 人工核对 → super_admin
apply（`POST /api/admin/billing/credits-migration`）；非生产环境 lifespan 自动执行。
幂等（schema_migrations 标记）；写 MIGRATION 流水可追溯。

### 3. 报价冻结（Generation Quote）

- `POST /api/billing/quote` → quote_id + unit_credits + estimated_credits（Redis TTL 600s）；
- authorize 携 quote_id 时按报价冻结价计费（校验归属/数量/有效期，不符回退当前价）；
- 流水快照 `unit_credits / pricing_rule_id / pricing_rule_version / quote_id`——
  管理员事后改价不影响已报价任务。

### 4. 定价规则与 Price Guard

- `pricing_rules` 表：feature/model 唯一生效规则（部分唯一索引），字段含
  unit_credits + 成本侧（nominal_unit_cost_rmb / target_margin / safety_buffer / rounding_step）；
- 毛利公式：`revenue = unit/credits_per_cny`；`effective_cost = nominal×(1+buffer)`；
  `min_unit_credits = ceil_step(effective_cost/(1-target)×credits_per_cny)`；
  示例：成本 ¥0.20 + 10% 垫 + 70% 目标 → 最低 80 点；
- 低于目标毛利：普通管理员 403；super_admin force + reason 强制保存（override 留痕 + 审计）；
- **采购成本以人民币记账**：上游 $1 额度 ≈ ¥1 实充的业务事实，禁止按实时汇率换算 nominal USD。

### 5. 经营账（Cost & Margin Ledger）

- `cost_margin_ledger`：settle 成功时冻结快照（reserved/charged/released、收入按 paid 部分、
  promotional_value 按 trial+gift 部分、成本/毛利/毛利率、Token 归因、成功/失败张数）；
- 收入口径：**revenue_rmb 只计 paid_credits 部分**；trial/gift 消耗记 promotional_value，
  利润为负 = 获客成本，不污染付费毛利报表；
- 三本账对账键：orders → billing_transactions(related_order_id) →
  cost_margin_ledger(billing_transaction_id)。

### 6. 试用一次性领取（Trial Entitlement）

- `trial_claims` 表：`normalized_email`（trim+lowercase）唯一约束——同邮箱一生一次，
  删号重注册不可再领；并发双击由 DB 唯一约束兜底（SAVEPOINT 捕获）；
- `trial_available` = 总开关 AND 试用默认 Token 有效 AND 未领取（服务端判定下发）；
- `POST /api/trial/claim` 自动通过：+trial_grant_credits（默认 500）+ 绑试用默认 Token。

### 7. 设备历史与心跳修复

- `client_devices` 表：user_id+device_id 唯一 upsert，永久保留，离线不删；
- `GET /api/admin/devices`：`seconds_since_seen` 由**服务器时钟**计算且恒 ≥0
  （`max(0, now - last_seen)`），前端禁止本地时钟求差——根除「-28 秒前」；
- online 判定仍为 Redis TTL key（180s）。

### 8. 汇率来源语义

`/api/pay/packages` 新增 `exchange_rate_source`（realtime_cached / realtime_fresh /
fallback_fixed）+ `exchange_rate_updated_at`；缓存来源 UI 必须标「参考汇率 · 每小时更新」。
Credits 体系下汇率退出用户侧主展示，仅存旧订单展示与后台成本核算。

## 兼容性

- 旧客户端 `/api/pay/create_order`(USD) 继续可用（$N → N×700 点入账）；
- `/api/users/me`、authorize/settle 响应保留全部 USD 镜像字段；
- `usage_logs.cost_usd` 镜像继续写入（Token 配额聚合依赖）。

## 后果

- 服务端 APP_VERSION 4.0.2 → 4.2.0；客户端 4.0.9 → 4.2.0（内含 V4.1 视觉工作流一并发布）；
- 生产部署必须执行 credits-migration preview→apply（deploy runbook 步骤）；
- V1 已知局限：客户端直连上游（Token 经 runtime-config 下发），服务端无法确知具体
  哪个 Token 服务了哪次请求——经营账 Token 归因按"结算时用户绑定"快照，属近似值。
