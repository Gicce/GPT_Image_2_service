---
type: known_issue
module: server
lifecycle: current
authority: current
company_standard: 1.x
migrated_from: workspace docs/09-KNOWN-ISSUES.md
migrated_at: 2026-09-05
---

# 已知问题与文档口径偏差（服务端侧）

> 迁移自工作区 docs/09-KNOWN-ISSUES.md（2026-09-05 知识库拆分，出处保真）
>
> 加注：本文件仅收录服务端相关问题（#1 / #5 / #6 / #14），**保留源文档原编号**；完整清单（含客户端与文档体系问题）见根工作区 `docs/09-KNOWN-ISSUES.md`。记录格式沿用源文档：问题 / 影响版本 / 表现 / 原因 / 当前状态 / 解决方案 / 关联模块。

## 1. 生产环境 admin 密码未人工修改

- 影响版本：V4.0.2 部署（ed74cda）
- 表现：生产 admin 仍为初始密码
- 原因：部署脚本不自动改密（must_change_password 机制要求人工首次登录修改）
- 当前状态：**未解决，需人工处理**
- 解决方案：管理员首次登录按提示改密
- 关联：backend admin_accounts / admin_users

## 5. postprocess（后处理充值）功能未完成

- `src/config/serviceFeatures.ts`：postprocess `enabled=false`（"功能开发中"）
- 约束：**功能完善前勿删相关 Card UI**
- 关联：客户端 serviceFeatures / Account

## 6. PackyAPI 价格口径

- 服务端历史上有 PackyAPI 定期同步加价 15% 逻辑（V4 已移除）；价格以数据库 `ai_models` 为准（gpt-image-2 $0.046/call）
- 关联：ai_models / billing

## 14. 管理后台客户删除与窄桌面布局（2026-08-26 已解决）

- 原表现：客户物理删除触发外键异常并统一显示“服务器内部错误”；1366×768 客户表操作列被裁切，详情弹窗底部不可达；概览 Token 卡口径错误且数值断行。
- 根因：删除接口未先判断业务关联；表格和弹窗使用固定宽高；Dashboard 把 Token 记录数误作客户可用额度展示。
- 当前状态：**已解决**——删除预检 + purge/archive 分流和结构化错误；核心列降级/固定操作列；弹窗视口约束；概览完全移除 Token 指标。
- 关联：服务端 admin users/stats/admin-login-logs；管理前端 Dashboard/Users/Layout/Admins/Settings。
