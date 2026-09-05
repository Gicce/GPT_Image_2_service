---
type: release
module: server
lifecycle: current
authority: current
company_standard: 1.x
migrated_from: workspace docs/current/release.md
migrated_at: 2026-09-05
---

# 当前版本与发布事实

> 迁移自工作区 docs/current/release.md（2026-09-05 知识库拆分，出处保真）
>
> 本文件收录服务端版本线相关段落；客户端版本线在客户端仓库 `GPT_Image_2_Application/docs/current/release.md`；工作区级双线对照（客户端 + 服务端）在根工作区 `docs/current/release.md`。

截至 2026-09-06，**CyImagePro 当前客户端正式发布版本是 V4.3.1（2026-09-04 发布），客户端工作区也是 4.3.1；
当前生产服务端版本是 4.2.3（2026-09-05 实测），服务端 develop 工作线为 1.0.0（pending_release，未部署）。** 客户端和服务端是两条独立版本线，必须分开陈述。

## 服务端版本线（工作线 1.0.0 pending_release；生产仍 4.2.3）

| 事实 | 当前值 | 权威来源 |
|---|---|---|
| 服务端工作区代码（develop 分支） | 1.0.0（`version_status=pending_release`） | `backend/app/main.py::APP_VERSION` + `/api/admin/version` |
| 生产服务端环境 | **4.2.3**（1.0.0 尚未部署，生产记录不得提前改写） | `https://www.zjcypc.com/api/health`，2026-09-05 实测 |

## v1.0.0 版本线约定

- **语义**：1.0.0 是服务端独立的账户治理 + 版本管理 + 安全加固版本线，与客户端 V4.x 版本线无关；版本号唯一事实源 = `backend/app/main.py`（`APP_VERSION` 常量与 `VERSION_LOG` 条目同文件维护，`/api/health`、`/api/admin/version` 均从它读取，不存在第二份版本声明）。
- **状态机**：版本条目 `status = released | pending_release`。**pending_release = 代码已合入 develop 但未部署生产**；用户人工部署并在生产 `/api/health` 确认 1.0.0 后，才把 status 改为 released 并更新生产实测行（部署动作与状态翻转均为人工步骤，不由开发流程自动完成）。
- **构建信息不伪造**：`build_commit` / `build_time` 由构建时 env 注入；未注入时接口返回 null，前端显示「未记录」——绝不以本地时间或占位值冒充构建信息。
- 发布流程：develop → 人工验收 → 合入 main（Gitea）→ 用户手动执行 CD（PROD_DEPLOY_ENABLED 打开）→ 生产健康检查 → 翻转 released。

正式发布版本只能以官方更新端点和发布产物为准；工作区版本不得自动写入 public。客户端四个版本源必须一致，服务端 `/health` 与源码常量必须一致。
