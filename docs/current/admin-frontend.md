---
type: frontend
module: server
lifecycle: current
authority: current
company_standard: 1.x
migrated_from: workspace docs/02-FRONTEND.md
migrated_at: 2026-09-05
---

# 二、管理后台（GPT_Image_2_service/frontend，Vue3 + naive-ui）

> 迁移自工作区 docs/02-FRONTEND.md（2026-09-05 知识库拆分，出处保真）
>
> 本文件仅收录源文档「§二 管理后台」全文；CyImagePro 客户端前端（React 18 + TS + Tauri 2）事实在客户端仓库 `GPT_Image_2_Application/docs/`，工作区级全量（含 §一 客户端 / §三 关键交互约定）见根工作区 `docs/02-FRONTEND.md`。

views（13 个，截至 svc@c27f2dc）：Login、Layout、Dashboard、Users、Admins（V4.0.2 数据库化管理员）、Orders（订单/退款审核）、Transactions（账务流水）、Tokens（Token 池，录入统计 Toast 分级）、Models（模型价格）、Notice（公告）、OnlineDevices（在线设备/心跳）、Settings（**可写服务端 .env 并触发容器重启**）、Profile。

## 2026-08-26 管理后台信息架构与响应式约定

- 导航按业务域折叠：运营管理、交易与财务、资源与计费、系统管理；概览保持一级入口，个人设置只在右上角账户菜单。
- 概览只展示客户数、今日 Image2 调用/出图、累计充值点数、在线设备、待审退款；不展示 Token 指标，完整健康信息仍在 Token 库存页。
- 1024–1199px 默认 72px 侧栏，≥1200px 默认 240px；内容容器 `min-width:0`，禁止页面级横向溢出。客户表 <1600px 使用核心列，宽屏恢复完整列，操作列固定右侧。
- 所有 `n-modal` 受 `100vw/100vh - 48px` 约束，内容区内部滚动；客户详情在 1024×768 下使用单列描述并保留底部操作可达性。
- `Admins` 合并管理员账户和登录记录（成功/失败、管理员、时间、IP、客户端、失败原因），登录记录只对超级管理员开放。
- `Settings` 分为业务参数、基础设施、运维操作；管理员账号不再从旧环境变量配置，统一由数据库管理员体系维护。
