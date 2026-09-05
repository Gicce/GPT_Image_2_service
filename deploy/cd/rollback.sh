#!/usr/bin/env bash
# CD 回滚脚本 —— 在生产主机上执行（由 rollback-production workflow 经 SSH 调用，或人工执行）。
#
# 铁律（区别于普通发布）：
# - 先过 DB 兼容检查，再动任何容器
# - 绝不 pg_restore / 绝不恢复旧整库 / 绝不动 pgdata、redisdata、skill_samples 卷
#   （本项目迁移为 main.py lifespan 内幂等加法迁移，无降级脚本；若前向部署含破坏性
#    DDL（DROP/RENAME），回滚代码与现有 schema 不兼容 —— 一律阻断，转人工处理）
#
# 用法: rollback.sh <40位COMMIT_SHA | last-good>
# 环境变量与 deploy.sh 相同（CD_APP_DIR / CD_SOURCE_* / CD_SUDO / CD_HEALTH_URL / CD_DRY_RUN）。
set -euo pipefail

TARGET="${1:?用法: rollback.sh <40位COMMIT_SHA|last-good>}"
APP_DIR="${CD_APP_DIR:-/opt/GPT_Image_2_service}"
SUDO="${CD_SUDO-sudo}"
HEALTH_URL="${CD_HEALTH_URL:-http://127.0.0.1/api/health}"
HISTORY="$APP_DIR/backups/deploy-history.jsonl"

cd "$APP_DIR"
echo "== CD rollback：target=$TARGET =="

# ---- 1. 解析目标提交 ----
if [ "$TARGET" = "last-good" ]; then
    [ -f "$HISTORY" ] || { echo "::error::无部署历史（$HISTORY），无法解析 last-good" >&2; exit 2; }
    TARGET=$(grep '"result":"ok"' "$HISTORY" | tail -1 | sed -n 's/.*"sha":"\([0-9a-f]\{40\}\)".*/\1/p')
    [ -n "$TARGET" ] || { echo "::error::部署历史中无成功记录" >&2; exit 2; }
    echo "last-good = $TARGET"
fi
[[ "$TARGET" =~ ^[0-9a-f]{40}$ ]] || { echo "错误：非法提交 SHA" >&2; exit 2; }

# ---- 2. 必需配置（与 deploy 同门禁） ----
[ -f docker-compose.yml ] && [ -r .env ] && [ -d certs ] \
    || { echo "::error::必需配置缺失（compose/.env/certs），阻断" >&2; exit 3; }
if git status --porcelain | grep -q .; then
    echo "::error::生产工作区存在未提交改动，拒绝自动回滚" >&2; exit 4
fi

CUR_SHA=$(git rev-parse HEAD)
[ "$TARGET" != "$CUR_SHA" ] || { echo "目标与当前 HEAD 相同，无需回滚"; exit 0; }

# ---- 3. DB 兼容检查（回滚核心门禁） ----
# 3a. 数据库可达
if [ "${CD_DRY_RUN:-0}" != "1" ]; then
    $SUDO docker compose exec -T postgres pg_isready -U postgres >/dev/null 2>&1 \
        || $SUDO docker compose exec -T postgres pg_isready >/dev/null 2>&1 \
        || { echo "::error::postgres 不可达，阻断回滚（先人工核实数据库状态）" >&2; exit 5; }
fi
# 3b. 前向迁移范围（target..current）不得含破坏性 DDL
DESTRUCTIVE=$(git diff "$TARGET..$CUR_SHA" -- backend/app/main.py backend/app/ \
              | grep -iE '^\+.*(DROP[ _]TABLE|DROP[ _]COLUMN|ALTER[ _]TABLE.*DROP|RENAME[ _]TO|TRUNCATE)' || true)
if [ -n "$DESTRUCTIVE" ]; then
    echo "::error::前向部署（$TARGET → $CUR_SHA）包含破坏性 DDL，代码回滚与现有 DB schema 不兼容。" >&2
    echo "命中行：$DESTRUCTIVE" >&2
    echo "请人工评估（必要时用部署前备份定向修复，禁止自动恢复旧整库）。" >&2
    exit 6
fi
echo "DB 兼容检查通过（前向迁移无破坏性 DDL；schema 为加法超集，旧代码容忍多列）"

# ---- 4. 回滚 = 重新部署目标提交（只动应用容器与代码） ----
if [ "${CD_DRY_RUN:-0}" = "1" ]; then
    echo "[dry-run] git checkout --detach $TARGET && compose build backend && up -d && restart nginx"
    echo "[dry-run] 健康检查期望版本：$(git show "$TARGET:backend/app/main.py" | sed -n "s/^APP_VERSION *= *[\"']\{0,1\}\([0-9][0-9A-Za-z._-]*\).*/\1/p" | head -1)"
    echo "== dry-run 完成（未做任何变更；未触碰任何数据卷）=="
    exit 0
fi

git checkout --detach "$TARGET"
$SUDO docker compose build backend
$SUDO docker compose up -d
$SUDO docker compose restart nginx

EXPECT_VER=$(sed -n "s/^APP_VERSION *= *[\"']\{0,1\}\([0-9][0-9A-Za-z._-]*\).*/\1/p" backend/app/main.py | head -1)
HEALTH_OK=0
for i in $(seq 1 30); do
    sleep 2
    BODY=$(curl -fsS --max-time 5 "$HEALTH_URL" 2>/dev/null || true)
    if echo "$BODY" | grep -q "$EXPECT_VER"; then HEALTH_OK=1; break; fi
done
RESULT="rollback-failed"
[ "$HEALTH_OK" = "1" ] && RESULT="rollback-ok"

printf '{"ts":"%s","sha":"%s","prev":"%s","version":"%s","result":"%s"}\n' \
    "$(date -Is)" "$TARGET" "$CUR_SHA" "$EXPECT_VER" "$RESULT" >> "$HISTORY"
if [ "$HEALTH_OK" = "1" ]; then
    echo "== 回滚完成：$TARGET @ $EXPECT_VER（数据库与卷未被触碰）=="
else
    echo "::error::回滚后健康检查失败——保持现场，人工介入" >&2
    exit 7
fi
