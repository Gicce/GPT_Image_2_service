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

截至 2026-09-05，**CyImagePro 当前客户端正式发布版本是 V4.3.1（2026-09-04 发布），客户端工作区也是 4.3.1；
当前生产服务端版本是 4.2.3，服务端工作区也是 4.2.3。** 客户端和服务端是两条独立版本线，必须分开陈述。

## 服务端版本线（当前 4.2.3）

| 事实 | 当前值 | 权威来源 |
|---|---|---|
| 服务端工作区代码 | 4.2.3 | `backend/app/main.py::APP_VERSION` |
| 生产服务端环境 | 4.2.3 | `https://www.zjcypc.com/api/health`，2026-09-05 实测 |

正式发布版本只能以官方更新端点和发布产物为准；工作区版本不得自动写入 public。客户端四个版本源必须一致，服务端 `/health` 与源码常量必须一致。
