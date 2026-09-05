---
type: adr
module: server
visibility: internal
---

# ADR-007 金额全链路 Decimal，人民币以"分"为精确基准

- 日期：2026-08-19（补记既有设计）
- 状态：已实施（Accepted）

## 背景

系统同时处理美元余额/定价、人民币支付/退款与汇率快照；浮点金额会产生对不上的账（二进制浮点无法精确表示十进制小数）。

## 问题

金额如何在数据库、Python 计算、微信支付边界三个层面保持精确且可审计？

## 候选方案

1. float + 四舍五入——累计漂移，不可接受
2. 整数分存储全链路——美元侧需六位小数（如 $0.046 单价），整数化不便
3. **Decimal 全链路 + Numeric(18,6) 存储 + 微信边界转分**（选定）

## 最终选择与原因

方案 3（源码核验：billing.py / refund.py）：

- 数据库：金额列 Numeric(18,6)（users.balance_usd / trial_credit_usd、billing_transactions 各金额列）
- Python：Decimal 全链路；外部入参经 `billing.d()` 以 `Decimal(str(value))` 收敛，不直接用 float 计算
- 微信支付边界：元→分 `int((Decimal(cny) * 100).quantize(Decimal("1"), ROUND_HALF_UP))`，分→元反向；退款以人民币"分"为精确基准
- float 仅允许出现在 API 响应序列化展示（如退款详情字段），禁止参与任何金额计算

## 影响

- 新代码禁止 float 金额运算；微信请求金额一律走既有转换函数
- 与幂等三支柱（billing_transactions.request_id / usage_logs.request_id / refund_requests.out_refund_no）共同构成资金安全基线
