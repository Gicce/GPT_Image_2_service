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
| 账户治理（归档/删除/重置密码/会话） | `tests/test_v100_account_governance.py`（13 项：撤销/恢复/双路径删除/阻断/幂等/迟到回调/权限/审计脱敏/tv 兼容窗口） |
| 依赖升级 | `pip check` + 导入冒烟 + 全量 pytest（v1.0.0 升级后 178 passed 零回归） |

**当前全量口径（v1.0.0，2026-09-06）：pytest 178 passed**（隔离库 cyimage_v4_test + Redis db15；conftest 重建 TEST_ADMIN，`make_admin_headers(role, admin_id, username)` 可造普通管理员 token）。管理后台 `npm run build` 通过。

**测试环境硬边界**：支付链路全 monkeypatch / dev-payment，不触真实微信；不连生产库；不启动用户日常开发实例；测试后临时数据随测试库重建清理。

## Release 发布前验证清单

- 服务端 `/api/health` 返回版本与 `backend/app/main.py::APP_VERSION` 一致（生产部署后实测）。

GUI、真实付费、真实设备和生产验证必须与自动测试分开报告。AI 不自动启动 GUI，交付状态先到 `READY_FOR_HUMAN`。
