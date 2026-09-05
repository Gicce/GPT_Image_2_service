---
type: adr
module: server
visibility: internal
---

# ADR-002 billing_transactions 作为账务单一真相源

- 日期：2026-08（V4 后端重构）
- 状态：已实施（Accepted）

## 背景

V3 存在多套余额口径（Token 分组余额、客户端本地计算等），导致"后台 $100 客户端 $0"等对不上账问题。

## 问题

充值、扣费、退款、管理员调整、迁移等多种资金变动如何保证可审计、可对账、幂等？

## 候选方案

1. 各业务表各自记余额变动（orders 记充值、usage_logs 记扣费……）——对账需扫多表，口径易漂移
2. **统一账务流水表 billing_transactions，所有资金变动唯一入口**（选定）

## 最终选择与原因

方案 2。`billing_transactions`：type（IMAGE2_CHARGE/IMAGE2_REFUND/RECHARGE/RECHARGE_REFUND/ADMIN_ADJUSTMENT/MIGRATION）+ status + **request_id 唯一约束**（幂等基石）+ 前后余额快照（每条流水可独立对账）+ trial_amount/balance_amount/billing_source 来源拆分。

扣费用两阶段（RESERVED→SUCCESS/FAILED，billing.py，settle 按实际成功数重算、CAS 幂等；超时未结算由 reservation GC 释放为 RELEASED 全额退回，见 [ADR-005](ADR-005-no-scheduler-framework.md)），试用额度优先现金兜底（`_split_charge`，Decimal 全链路）。退款以 RECHARGE_REFUND 冲正入同一流水。

## 影响

- 任何新资金类型必须新增 type 并写流水，禁止绕过
- 幂等三支柱：billing_transactions.request_id、usage_logs.request_id、refund_requests.out_refund_no
- 口径区分（2026-08-19 校准）：**流水是资金变动的唯一审计/对账事实源**（每条含 balance_before/after、trial_before/after 快照，可逐条独立对账）；**当前余额状态**存于 users.balance_usd / trial_credit_usd（Numeric(18,6)，行锁 FOR UPDATE 下随流水同事务更新，非 SUM 派生）。两者不一致时以流水为准排查（users 列视为缓存式状态）
- "不引入第二套余额"是后续所有账户/充值/Token 改动的硬约束
