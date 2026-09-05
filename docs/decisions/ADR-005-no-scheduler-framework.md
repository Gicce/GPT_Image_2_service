---
type: adr
module: server
visibility: internal
---

# ADR-005 服务端不引入定时任务框架，周期逻辑以内建机制实现

- 日期：2026-08-19（补记既有设计）
- 状态：已实施（Accepted）

## 背景

服务端有时效性需求：预占扣费的回收（客户端崩溃后 RESERVED 悬挂）、微信退款 processing 态恢复、在线设备状态、登录限流窗口。是否引入 apscheduler / celery / cron？

## 问题

如何满足全部时效性需求，同时不增加调度框架的依赖、配置与运维面？

## 候选方案

1. apscheduler / celery 等调度框架——为一个 10 分钟级任务引入框架与 broker，成本错配
2. 系统 crontab 脚本——落在容器外，与 docker compose 单元部署冲突
3. **内建轻量机制：单个 asyncio 周期循环 + lifespan 一次性恢复 + Redis TTL**（选定）

## 最终选择与原因

方案 3（2026-08-19 依源码核验：backend 无 apscheduler/celery/crontab 任何引用）：

- **唯一周期任务**：`start_reservation_gc_loop`（`main.py`，`while True` + `sleep(600)`）：每 10 分钟调 `billing.release_stale_reservations`，把超过 `RESERVATION_TTL_HOURS` 仍 RESERVED 的流水释放为 RELEASED 并全额退回（trial/balance 分别退回，行锁 + 状态复查）；启动时先清理一次
- **一次性恢复**：lifespan 内 `recover_processing_refunds()` 恢复卡在 processing 的微信退款
- **时效状态**：Redis TTL（`online_device:*` 180s、登录限流窗口）

## 影响

- 新增周期性需求先评估：Redis TTL / 请求时惰性处理 / lifespan 启动恢复能否解决
- 确需周期任务，沿用"单个 asyncio 循环"模式并在本 ADR 追加登记，不引入调度框架
