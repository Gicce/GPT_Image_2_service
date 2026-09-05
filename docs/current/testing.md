---
type: testing
module: server
lifecycle: current
authority: current
company_standard: 1.x
migrated_from: workspace docs/current/testing.md
migrated_at: 2026-09-05
---

# 测试规则

> 迁移自工作区 docs/current/testing.md（2026-09-05 知识库拆分，出处保真）
>
> 本文件保留服务端行（服务端 API/计费/权限、数据库）与 Release 验证清单中服务端 `/health` 段；客户端行（React/TypeScript/UI、AI 漫画、Rust/Tauri、Release 四版本源 / 更新 manifest / 安装产物验证）见客户端仓库 `GPT_Image_2_Application/docs/current/testing.md` 与根工作区 `docs/current/testing.md`。

默认执行与变更直接相关的最小充分测试；正式发布或用户明确要求时执行全量回归。

| 变更 | 最低验证 |
|---|---|
| 服务端 API/计费/权限 | 对应 pytest；计费必须验证幂等、预占、结算与失败回滚 |
| 数据库 | migration/model/repository 契约验证，不改已执行 migration |

## Release 发布前验证清单

- 服务端 `/api/health` 返回版本与 `backend/app/main.py::APP_VERSION` 一致（生产部署后实测）。

GUI、真实付费、真实设备和生产验证必须与自动测试分开报告。AI 不自动启动 GUI，交付状态先到 `READY_FOR_HUMAN`。
