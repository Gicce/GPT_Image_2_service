#!/usr/bin/env bash
# CD 预检（无副作用，可在 CI / 本地运行）：静态校验部署前置条件。
# 生产主机绝不被本脚本触碰。
set -euo pipefail

REPO_DIR="${1:?用法: preflight.sh <REPO_DIR>}"
cd "$REPO_DIR"

fail() { echo "::error::预检失败：$*" >&2; exit 1; }

# 1. compose 结构四件套
python - <<'EOF' || fail "docker-compose.yml 结构不符合预期"
import yaml
with open('docker-compose.yml', encoding='utf-8') as f:
    doc = yaml.safe_load(f)
assert 'services' in doc and {'backend', 'postgres', 'redis', 'nginx'} <= set(doc['services']), \
    'compose 服务不全（期望 backend/postgres/redis/nginx）'
print('OK compose 服务:', ', '.join(sorted(doc['services'])))
EOF

# 2. 脚本语法
for s in deploy.sh deploy/cd/preflight.sh deploy/cd/deploy.sh deploy/cd/rollback.sh; do
    [ -f "$s" ] || fail "缺少 $s"
    bash -n "$s" || fail "$s 语法错误"
done
echo "OK 脚本语法（deploy.sh + deploy/cd/*）"

# 3. 目标树无被跟踪的敏感文件
if git rev-parse --git-dir >/dev/null 2>&1; then
    bad=$(git ls-files | grep -iE '(^|/)\.env$|(^|/)\.env\.(local|prod)(\.|$)|\.pem$|\.p12$|(^|/)certs/|\.bak$|(^|/)backups/' || true)
    [ -z "$bad" ] || fail "敏感文件被跟踪：$bad"
    echo "OK 无敏感文件被跟踪"
else
    echo "（非 git 检出，跳过敏感文件检查）"
fi

# 4. APP_VERSION 可提取（健康检查的期望值来源）
extract_version() {
    sed -n "s/^APP_VERSION *= *[\"']\{0,1\}\([0-9][0-9A-Za-z._-]*\).*/\1/p" backend/app/main.py | head -1
}
VER=$(extract_version)
[ -n "$VER" ] || fail "无法从 backend/app/main.py 提取 APP_VERSION"
echo "OK APP_VERSION=$VER"

echo "预检通过。"
