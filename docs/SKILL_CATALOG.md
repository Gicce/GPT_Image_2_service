# Skill Catalog API

## Public API

- `GET /api/skills/catalog`：返回每个 Skill 当前发布版本，支持 `domain` 过滤，响应带 `ETag` 和五分钟缓存策略。
- `GET /api/skills/{skill_id}/versions/{version}`：返回指定已发布且不可变的 SkillPackage 版本，同样支持条件请求。

## Admin API

管理端 `/api/admin/skill-packages` 支持列表、创建草稿、更新草稿、校验、发布、停用和回滚。发布时会归档同 Skill 的上一发布版本；已发布内容禁止原地修改。创建、更新、发布、停用和回滚均写入管理员审计日志。

## Database

表 `skill_packages` 以 `(skill_id, version)` 唯一约束保存版本，`payload` 使用 JSON 字段保存领域合同。状态为 `draft`、`published` 或 `archived`。

生产部署需按现有 Alembic/建表流程创建该表；服务启动会幂等写入首批官方目录，其中只有专业桌搭为 `ready`。
