#!/usr/bin/env bash
# CD 发布脚本 —— 在生产主机上执行（由 deploy-production workflow 经 SSH 调用，或人工执行）。
#
# 设计约束（docs/current/deployment.md + CD 方针）：
# - 只部署「确定提交」：参数必须是 40 位 SHA，且是受信分支（默认 origin/main）的祖先
# - 必需配置缺失（.env / certs / compose）立即阻断，绝不复制示例配置、绝不重新生成密钥
# - 普通发布只更新应用（backend/nginx 容器 + 代码），绝不初始化空库、绝不动 pgdata/redisdata 卷
# - 部署前先 pg_dump（延续 2026-08-27/28 既有人工实践），失败即阻断
# - 健康检查：/api/health 必须 200 且返回目标提交的 APP_VERSION
#
# 环境变量：
#   CD_APP_DIR       应用目录（默认 /opt/GPT_Image_2_service；隔离测试可指向临时目录）
#   CD_SOURCE_REMOTE 拉取源 remote（默认 origin —— 生产当前 origin=GitHub master；
#                     Gitea main 与之同步，SHA 双重校验在 workflow 侧完成）
#   CD_SOURCE_REF    受信分支（默认 refs/heads/main；生产 origin 为 GitHub 时由调用方传 refs/heads/master）
#   CD_SUDO          sudo 前缀（默认 "sudo"；无 docker 权限要求的测试环境可传空）
#   CD_HEALTH_URL    健康检查地址（默认 http://127.0.0.1/api/health）
#   CD_DRY_RUN=1     只打印将要执行的变更，不执行（隔离测试用；守卫逻辑照常评估）
set -euo pipefail

SHA="${1:?用法: deploy.sh <40位COMMIT_SHA>}"
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "错误：非法提交 SHA（必须 40 位十六进制）" >&2; exit 2; }

APP_DIR="${CD_APP_DIR:-/opt/GPT_Image_2_service}"
REMOTE="${CD_SOURCE_REMOTE:-origin}"
SRC_REF="${CD_SOURCE_REF:-refs/heads/main}"
SUDO="${CD_SUDO-sudo}"
HEALTH_URL="${CD_HEALTH_URL:-http://127.0.0.1/api/health}"
HISTORY="$APP_DIR/backups/deploy-history.jsonl"

run() {  # run <desc> <cmd...>：CD_DRY_RUN=1 时只打印
    if [ "${CD_DRY_RUN:-0}" = "1" ]; then echo "[dry-run] $*"; else "$@"; fi
}

cd "$APP_DIR"
echo "== CD deploy $SHA -> $APP_DIR (源 $REMOTE/$SRC_REF) =="

# ---- 1. 必需配置存在（缺失立即阻断；绝不自动生成/复制示例） ----
[ -f docker-compose.yml ] || { echo "::error::缺少 docker-compose.yml" >&2; exit 3; }
[ -r .env ]              || { echo "::error::缺少可读的 .env（生产配置）——阻断，禁止用 .env.example 顶替" >&2; exit 3; }
[ -d certs ]             || { echo "::error::缺少 certs/（支付证书目录）——阻断" >&2; exit 3; }

# ---- 2. 本地改动守卫：tracked 文件有未提交改动则拒绝（防覆盖手工热修） ----
if git status --porcelain | grep -q .; then
    echo "::error::生产工作区存在未提交改动，拒绝自动部署（人工处理后再试）：" >&2
    git status --porcelain >&2
    exit 4
fi

# ---- 3. 拉取并校验确定提交 ∈ 受信分支 ----
BARE_REF="${SRC_REF#refs/heads/}"   # main / master
run git fetch "$REMOTE" "$BARE_REF"
# FETCH_HEAD = 受信分支 tip；SHA 若不在本地对象库则单独拉取
git cat-file -e "$SHA^{commit}" 2>/dev/null || run git fetch "$REMOTE" "$SHA"
git cat-file -e "$SHA^{commit}" 2>/dev/null || { echo "::error::$SHA 不存在于 $REMOTE" >&2; exit 5; }
git merge-base --is-ancestor "$SHA" FETCH_HEAD 2>/dev/null \
    || { echo "::error::$SHA 不是 $REMOTE $BARE_REF 的祖先，拒绝部署非受信提交" >&2; exit 5; }

PREV_HEAD=$(git rev-parse HEAD)

# ---- 4. 部署前备份（pg_dump；失败阻断） ----
TS=$(date +%Y%m%d-%H%M%S)
DUMP="backups/pre-${SHA:0:8}-$TS.sql.gz"
if [ "${CD_DRY_RUN:-0}" = "1" ]; then
    echo "[dry-run] $SUDO docker compose exec -T postgres pg_dump -U \${POSTGRES_USER:-postgres} | gzip > $DUMP"
else
    PG_USER=$(grep -E '^POSTGRES_USER=' .env | head -1 | cut -d= -f2 || true)
    $SUDO docker compose exec -T postgres pg_dump -U "${PG_USER:-postgres}" 2>/dev/null | gzip > "$DUMP" \
        || { echo "::error::部署前 pg_dump 失败——阻断发布" >&2; exit 6; }
    gzip -t "$DUMP" || { echo "::error::备份 gzip 校验失败——阻断发布" >&2; exit 6; }
    echo "备份完成：$DUMP（$(du -h "$DUMP" | cut -f1)）"
fi

# ---- 5. 切换到确定提交（detached；master 指针不动，供人工流程回退） ----
run git checkout --detach "$SHA"

# ---- 6. 构建并只更新应用容器 ----
run $SUDO docker compose build backend
run $SUDO docker compose up -d
run $SUDO docker compose restart nginx

# ---- 7. 健康检查：/api/health 必须 200 且版本 = 目标提交 APP_VERSION ----
EXPECT_VER=$(sed -n "s/^APP_VERSION *= *[\"']\{0,1\}\([0-9][0-9A-Za-z._-]*\).*/\1/p" backend/app/main.py | head -1)
if [ "${CD_DRY_RUN:-0}" = "1" ]; then
    echo "[dry-run] 健康检查：轮询 $HEALTH_URL 直至版本包含 $EXPECT_VER"
    echo "== dry-run 完成（未做任何变更）=="
    exit 0
fi
HEALTH_OK=0
for i in $(seq 1 30); do
    sleep 2
    BODY=$(curl -fsS --max-time 5 "$HEALTH_URL" 2>/dev/null || true)
    if echo "$BODY" | grep -q "$EXPECT_VER"; then HEALTH_OK=1; break; fi
    echo "  等待健康检查（$((i*2))s）：$(echo "$BODY" | head -c 80)"
done
RESULT="failed"
if [ "$HEALTH_OK" = "1" ]; then
    RESULT="ok"
    echo "健康检查通过（版本 $EXPECT_VER）"
else
    echo "::error::健康检查超时（期望版本 $EXPECT_VER）——回滚请用 rollback.sh（先过 DB 兼容检查）" >&2
fi

# ---- 8. 记录部署历史（last-good 由 rollback.sh 读取） ----
mkdir -p backups
printf '{"ts":"%s","sha":"%s","prev":"%s","version":"%s","result":"%s"}\n' \
    "$(date -Is)" "$SHA" "$PREV_HEAD" "$EXPECT_VER" "$RESULT" >> "$HISTORY"
[ "$RESULT" = "ok" ] || exit 7
echo "== 部署完成：$SHA @ $EXPECT_VER（前一版本 $PREV_HEAD 已可 rollback）=="
