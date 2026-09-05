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

## v1.0.0 安全评估缓期项（2026-09-06，评估过、留痕不修）

完整评估见 `security-assessment.md`（已修复项 S-1～S-5 均有回归测试）。

### 15. ecdsa PYSEC-2026-1325（低，不修）

- python-jose 传递依赖；0.19.2 已是最新版本，**无上游修复可升**；本项目 JWT 全部 HS256，ECDSA 验签不在任何请求路径上，攻击面不成立。跟踪上游发布即可。

### 16. vite ≤6.4.2 / esbuild ≤0.24.2（低，对本项目；缓期）

- 两条 advisory 均仅影响 `vite dev` 开发服务器（dev path traversal / server.fs.deny 绕过 / launch-editor NTLM 泄露）；生产管理后台只发布 `dist/` 静态产物，不经 vite 服务器。修复需 vite 4→8 大版本升级（破坏性），另行排期。

### 17. docker.sock 挂载与响应头/CORS 硬化（部署面，缓期）

- docker.sock 挂载进 backend 容器为 restart 功能依赖，入口已收紧 super_admin（ADR-020）；socket proxy 方案与 CSP/X-Frame-Options 安全头、生产 `CORS_ORIGINS` 白名单配置属部署硬化专项，随下次人工部署处理。
