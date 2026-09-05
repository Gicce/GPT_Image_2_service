---
type: models
module: server
lifecycle: current
authority: current
company_standard: 1.x
migrated_from: workspace docs/06-MODELS.md
migrated_at: 2026-09-05
---

# 一、上游 Provider（服务端调度）

> 迁移自工作区 docs/06-MODELS.md（2026-09-05 知识库拆分，出处保真）
>
> 本文件仅收录源文档「§一 上游 Provider（服务端调度）」全文；客户端 BYOK / Transport 路由 / Vision（视觉理解）体系见客户端仓库 `GPT_Image_2_Application/docs/current/models.md`，工作区级全量见根工作区 `docs/06-MODELS.md`。

- **packyapi 等 OpenAI 兼容中转**：gpt-image-2（图像生成，$0.046/次，seed 于 ai_models 表）；gpt-5.6 / gpt-5.6-luna（**仅支持 Responses API** `/v1/responses`，不支持 chat completions）
- **智谱 GLM**：GLM-5.3/5.2/5.1 等；coding plan 双计费模式（API/Coding Plan 两种 credential）；错误码 **1113 = Key 余额不足**（insufficient_balance）
- **DeepSeek**：官方 API
- 上游凭证 = 服务端 TokenInventory → runtime-config 下发临时 token → 客户端直连
