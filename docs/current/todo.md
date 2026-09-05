---
type: todo
module: server
lifecycle: current
authority: current
company_standard: 1.x
migrated_from: workspace docs/10-TODO.md
migrated_at: 2026-09-05
---

# TODO（真实未完成事项）

> 迁移自工作区 docs/10-TODO.md（2026-09-05 知识库拆分，出处保真）
>
> 本文件仅收录源文档「§运维」；文档清理 / 客户端 / 知识库等其余小节见根工作区 `docs/10-TODO.md`。

> 只记录已确认的真实未完成项，禁止想象式 TODO。

## 运维

- [ ] **生产 admin 密码人工修改**（首次登录 must_change_password 流程）——V4.0.2 部署遗留
- [ ] 确认客户端 v4.0.4 发布链路：GitHub Release 是否成功、生产镜像 latest.json 何时从 4.0.3 切到 4.0.4（见 09-KNOWN-ISSUES #2）
- [ ] v1.0.0 人工验收 → 合入 main → 用户手动 CD 部署（PROD_DEPLOY_ENABLED 打开）→ 生产 `/api/health` 确认 1.0.0 → release.md 翻转 released（2026-09-06 记录，见 ADR-019/020 与 changelog v1.0.0 条目）
- [ ] vite 4→8 大版本升级（前端构建链，消除 dev-server advisory，known-issues #16）
- [ ] 部署硬化专项：docker.sock socket proxy / 安全响应头 / 生产 CORS_ORIGINS 白名单（known-issues #17）
