"""管理员认证体系测试：登录（含限流）、账户管理、授权边界。"""

import uuid

import httpx
import pytest
from sqlalchemy import select, text

from app.main import app
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password, create_access_token
from app.models.admin_user import AdminUser
from tests.conftest import (
    TEST_ADMIN_ID, TEST_ADMIN_USERNAME, TEST_ADMIN_LOGIN_PASSWORD,
    make_user, make_admin_headers,
)


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _get_admin_row(username: str) -> AdminUser | None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(AdminUser).where(AdminUser.username == username))
        return result.scalar_one_or_none()


async def _create_admin_row(username: str, password: str, role: str = "admin",
                            is_active: bool = True) -> AdminUser:
    admin = AdminUser(
        id=str(uuid.uuid4()), username=username, display_name=username,
        password_hash=hash_password(password), role=role, is_active=is_active,
    )
    async with AsyncSessionLocal() as session:
        session.add(admin)
        await session.commit()
    return admin


# ── 登录 ──────────────────────────────────────────────────────────

async def test_admin_login_valid_password(client):
    r = await client.post("/api/auth/admin/login", json={
        "username": TEST_ADMIN_USERNAME, "password": TEST_ADMIN_LOGIN_PASSWORD,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"]
    assert body["admin"]["role"] == "super_admin"
    # 登录成功后 token 可访问管理员接口
    r2 = await client.get("/api/admin/admins/me",
                          headers={"Authorization": f"Bearer {body['access_token']}"})
    assert r2.status_code == 200
    assert r2.json()["username"] == TEST_ADMIN_USERNAME
    # last_login_at 已更新
    row = await _get_admin_row(TEST_ADMIN_USERNAME)
    assert row.last_login_at is not None


async def test_admin_login_wrong_password_returns_401(client):
    r = await client.post("/api/auth/admin/login", json={
        "username": TEST_ADMIN_USERNAME, "password": "wrong-password",
    })
    assert r.status_code == 401
    assert r.json()["detail"] == "用户名或密码错误"


async def test_admin_login_unknown_user_has_same_public_error(client):
    r1 = await client.post("/api/auth/admin/login", json={
        "username": "no-such-admin", "password": "whatever",
    })
    r2 = await client.post("/api/auth/admin/login", json={
        "username": TEST_ADMIN_USERNAME, "password": "wrong-password",
    })
    assert r1.status_code == r2.status_code == 401
    assert r1.json()["detail"] == r2.json()["detail"] == "用户名或密码错误"


async def test_disabled_admin_cannot_login(client):
    await _create_admin_row("disabled-admin", "password-123", is_active=False)
    r = await client.post("/api/auth/admin/login", json={
        "username": "disabled-admin", "password": "password-123",
    })
    # 对外同样返回"用户名或密码错误"，避免暴露账户存在性
    assert r.status_code == 401
    assert r.json()["detail"] == "用户名或密码错误"


async def test_admin_login_rate_limit(client):
    """连续失败达到阈值后触发限流（429）。"""
    username = "rl-target-admin"
    await _create_admin_row(username, "password-123")
    statuses = []
    for _ in range(6):
        r = await client.post("/api/auth/admin/login", json={
            "username": username, "password": "bad-password",
        })
        statuses.append(r.status_code)
    # 前 5 次 401（第 5 次已设置锁定 key），第 6 次 429
    assert statuses[:5] == [401] * 5
    assert statuses[5] == 429
    assert "尝试次数过多" in r.json()["detail"]
    # 锁定期间正确密码也无法登录
    r = await client.post("/api/auth/admin/login", json={
        "username": username, "password": "password-123",
    })
    assert r.status_code == 429


async def test_admin_login_writes_audit_logs(client):
    await client.post("/api/auth/admin/login", json={
        "username": TEST_ADMIN_USERNAME, "password": "bad-password",
    })
    await client.post("/api/auth/admin/login", json={
        "username": TEST_ADMIN_USERNAME, "password": TEST_ADMIN_LOGIN_PASSWORD,
    })
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(text(
            "SELECT action FROM admin_audit_logs WHERE action LIKE 'admin_login%'"
        ))).scalars().all()
    assert "admin_login_failed" in rows
    assert "admin_login_success" in rows


# ── 管理员管理 ────────────────────────────────────────────────────

async def test_super_admin_can_create_admin(client):
    r = await client.post("/api/admin/admins", headers=make_admin_headers(), json={
        "username": "NewAdmin", "display_name": "运营管理员",
        "password": "long-password-123", "role": "admin",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "newadmin"  # 统一小写存储
    assert body["role"] == "admin"
    # 新管理员可登录
    r = await client.post("/api/auth/admin/login", json={
        "username": "NEWADMIN", "password": "long-password-123",
    })
    assert r.status_code == 200


async def test_normal_user_cannot_access_admin_management(client):
    user = await make_user("plain-user")
    user_headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    for method, path in [
        ("GET", "/api/admin/admins"),
        ("POST", "/api/admin/admins"),
        ("GET", "/api/admin/admins/me"),
    ]:
        r = await client.request(method, path, headers=user_headers,
                                 json={} if method == "POST" else None)
        assert r.status_code == 403, f"{method} {path} => {r.status_code}"


async def test_admin_role_cannot_access_admin_management(client):
    """普通 admin 角色也不能进入管理员管理（仅 super_admin；角色以数据库为准）。"""
    plain = await _create_admin_row("plain-role-admin", "password-123", role="admin")
    r = await client.get("/api/admin/admins",
                         headers=make_admin_headers(role="admin", admin_id=plain.id, username="plain-role-admin"))
    assert r.status_code == 403


async def test_admin_username_unique(client):
    await client.post("/api/admin/admins", headers=make_admin_headers(), json={
        "username": "dup-admin", "password": "long-password-123", "role": "admin",
    })
    r = await client.post("/api/admin/admins", headers=make_admin_headers(), json={
        "username": "DUP-ADMIN", "password": "long-password-456", "role": "admin",
    })
    assert r.status_code == 400
    assert "已存在" in r.json()["detail"]


async def test_password_is_never_stored_plaintext(client):
    await client.post("/api/admin/admins", headers=make_admin_headers(), json={
        "username": "hash-check", "password": "plaintext-secret-123", "role": "admin",
    })
    row = await _get_admin_row("hash-check")
    assert row.password_hash != "plaintext-secret-123"
    assert row.password_hash.startswith("$2")  # bcrypt


async def test_cannot_disable_last_super_admin(client):
    """唯一 super_admin 禁用自己：先命中自我保护，同样拒绝。"""
    r = await client.put(f"/api/admin/admins/{TEST_ADMIN_ID}", headers=make_admin_headers(), json={
        "is_active": False,
    })
    assert r.status_code == 400


async def test_cannot_demote_last_super_admin(client):
    """唯一 super_admin 降权自己：命中最后 super_admin 保护。"""
    r = await client.put(f"/api/admin/admins/{TEST_ADMIN_ID}", headers=make_admin_headers(), json={
        "role": "admin",
    })
    assert r.status_code == 400
    assert "超级管理员" in r.json()["detail"]


async def test_cannot_disable_self(client):
    new_admin = await _create_admin_row("self-disable", "password-123", role="super_admin")
    headers = make_admin_headers(role="super_admin", admin_id=new_admin.id, username="self-disable")
    r = await client.put(f"/api/admin/admins/{new_admin.id}", headers=headers, json={
        "is_active": False,
    })
    assert r.status_code == 400


async def test_can_disable_super_admin_when_another_exists(client):
    second = await _create_admin_row("second-super", "password-123", role="super_admin")
    r = await client.put(f"/api/admin/admins/{second.id}", headers=make_admin_headers(), json={
        "is_active": False,
    })
    assert r.status_code == 200
    assert r.json()["is_active"] is False
    # 被禁用的管理员 token 立即失效
    r = await client.get("/api/admin/admins/me",
                         headers=make_admin_headers(role="super_admin", admin_id=second.id))
    assert r.status_code == 401


async def test_change_own_password_flow(client):
    new_admin = await _create_admin_row("pw-change", "old-password-123")
    token = make_admin_headers(role="admin", admin_id=new_admin.id, username="pw-change")

    # 当前密码错误
    r = await client.put("/api/admin/admins/me/password", headers=token, json={
        "current_password": "wrong", "new_password": "new-password-456",
    })
    assert r.status_code == 400

    # 新密码过短
    r = await client.put("/api/admin/admins/me/password", headers=token, json={
        "current_password": "old-password-123", "new_password": "short",
    })
    assert r.status_code == 400

    # 正确修改
    r = await client.put("/api/admin/admins/me/password", headers=token, json={
        "current_password": "old-password-123", "new_password": "new-password-456",
    })
    assert r.status_code == 200

    # 旧密码失效，新密码可登录
    r = await client.post("/api/auth/admin/login", json={
        "username": "pw-change", "password": "old-password-123",
    })
    assert r.status_code == 401
    r = await client.post("/api/auth/admin/login", json={
        "username": "pw-change", "password": "new-password-456",
    })
    assert r.status_code == 200


async def test_super_admin_can_reset_other_password(client):
    target = await _create_admin_row("reset-target", "old-password-123")
    r = await client.put(f"/api/admin/admins/{target.id}/password",
                         headers=make_admin_headers(), json={"new_password": "reset-password-789"})
    assert r.status_code == 200
    r = await client.post("/api/auth/admin/login", json={
        "username": "reset-target", "password": "reset-password-789",
    })
    assert r.status_code == 200
    # 重置后标记强制改密；本人修改密码后标记清除
    assert r.json()["admin"]["must_change_password"] is True

    token = r.json()["access_token"]
    r = await client.put("/api/admin/admins/me/password",
                         headers={"Authorization": f"Bearer {token}"},
                         json={"current_password": "reset-password-789",
                               "new_password": "own-new-password-1"})
    assert r.status_code == 200
    r = await client.post("/api/auth/admin/login", json={
        "username": "reset-target", "password": "own-new-password-1",
    })
    assert r.json()["admin"]["must_change_password"] is False


async def test_update_admin_role_and_username(client):
    target = await _create_admin_row("rename-me", "password-123")
    r = await client.put(f"/api/admin/admins/{target.id}", headers=make_admin_headers(), json={
        "username": "renamed-admin", "display_name": "新名字", "role": "super_admin",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "renamed-admin"
    assert body["role"] == "super_admin"


# ── 授权边界：重要 admin API 的 401/403 矩阵 ─────────────────────

async def test_admin_api_authorization_matrix(client):
    user = await make_user("matrix-user")
    user_headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}

    protected = [
        ("GET", "/api/admin/tokens"),
        ("GET", "/api/admin/tokens/stats"),
        ("GET", "/api/admin/users"),
        ("GET", "/api/admin/orders"),
        ("GET", "/api/admin/stats"),
        ("GET", "/api/admin/config"),
        ("GET", "/api/admin/audit-logs"),
        ("GET", "/api/admin/online-devices"),
        ("GET", "/api/admin/image2-config"),
        ("GET", "/api/admin/notice"),
        ("GET", "/api/admin/billing/transactions"),
        ("GET", "/api/admin/admins"),
    ]

    # 未认证 → 401
    for method, path in protected:
        r = await client.request(method, path)
        assert r.status_code == 401, f"unauth {method} {path} => {r.status_code}"

    # 普通用户 token → 403
    for method, path in protected:
        r = await client.request(method, path, headers=user_headers)
        assert r.status_code == 403, f"user {method} {path} => {r.status_code}"

    # 管理员 token → 200
    for method, path in protected:
        r = await client.request(method, path, headers=make_admin_headers())
        assert r.status_code == 200, f"admin {method} {path} => {r.status_code}"


async def test_deleted_or_forged_admin_token_rejected(client):
    """伪造/失效 admin_id 的 token 必须被拒（查库校验）。"""
    forged = make_admin_headers(admin_id=str(uuid.uuid4()), username="ghost")
    r = await client.get("/api/admin/admins/me", headers=forged)
    assert r.status_code == 401


# ── 客户端用户登录限流与禁用 token ────────────────────────────────

async def test_user_login_rate_limit(client):
    """普通用户连续失败达到阈值后触发限流（10 次/用户名，15 分钟窗口）。"""
    await make_user("rl-user")
    statuses = []
    for _ in range(11):
        r = await client.post("/api/auth/login", json={
            "username": "rl-user", "password": "bad-password",
        })
        statuses.append(r.status_code)
    assert statuses[:10] == [401] * 10
    assert statuses[10] == 429


async def test_disabled_user_token_immediately_invalid(client):
    """被禁用的客户端用户其存量 token 立即失效（get_current_user 校验 is_active）。"""
    user = await make_user("disabled-token-user")
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    r = await client.get("/api/auth/me", headers=headers)
    assert r.status_code == 200

    async with AsyncSessionLocal() as session:
        await session.execute(text(
            "UPDATE users SET is_active = false WHERE id = :id"), {"id": user.id})
        await session.commit()

    r = await client.get("/api/auth/me", headers=headers)
    assert r.status_code == 403
    assert "禁用" in r.json()["detail"]
