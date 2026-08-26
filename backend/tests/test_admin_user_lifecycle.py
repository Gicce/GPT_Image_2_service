"""客户删除/归档、登录审计与 Dashboard 点数口径回归。"""

import json
import uuid

import httpx
import pytest
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.main import app
from tests.conftest import make_admin_headers, make_user


ADMIN = make_admin_headers()


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as value:
        yield value


async def _attach_runtime_state(user_id: str) -> str:
    token_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "INSERT INTO token_inventory "
            "(id, token_value, is_trial, is_default, is_assigned, is_disabled, created_at) "
            "VALUES (:id, :value, false, false, false, false, now())"
        ), {"id": token_id, "value": f"sk-lifecycle-{token_id}"})
        await db.execute(text(
            "INSERT INTO runtime_token_assignments "
            "(id, token_id, user_id, status, source, assigned_at) "
            "VALUES (:id, :token_id, :user_id, 'active', 'admin_assign', now())"
        ), {"id": str(uuid.uuid4()), "token_id": token_id, "user_id": user_id})
        await db.execute(text(
            "INSERT INTO token_assignment_logs "
            "(id, token_id, user_id, action, source, created_at) "
            "VALUES (:id, :token_id, :user_id, 'assign', 'admin_assign', now())"
        ), {"id": str(uuid.uuid4()), "token_id": token_id, "user_id": user_id})
        await db.execute(text(
            "INSERT INTO client_devices "
            "(id, user_id, device_id, heartbeat_count, first_seen_at, last_seen_at) "
            "VALUES (:id, :user_id, 'dev-1', 1, now(), now())"
        ), {"id": str(uuid.uuid4()), "user_id": user_id})
        await db.commit()
    return token_id


async def test_clean_account_is_purged_but_claim_and_audit_are_retained(client):
    user = await make_user("clean-purge")
    token_id = await _attach_runtime_state(user.id)
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "INSERT INTO trial_claims "
            "(id, normalized_email, user_id_at_claim, claimed_at, grant_credits, status, campaign_version) "
            "VALUES (:id, :email, :user_id, now(), 500, 'granted', 1)"
        ), {"id": str(uuid.uuid4()), "email": user.email, "user_id": user.id})
        await db.commit()

    preview = await client.get(f"/api/admin/users/{user.id}/deletion-preview", headers=ADMIN)
    assert preview.status_code == 200
    assert preview.json()["mode"] == "purge"

    response = await client.delete(f"/api/admin/users/{user.id}", headers=ADMIN)
    assert response.status_code == 200
    assert response.json()["mode"] == "purge"

    async with AsyncSessionLocal() as db:
        assert (await db.execute(text("SELECT count(*) FROM users WHERE id=:id"), {"id": user.id})).scalar() == 0
        assert (await db.execute(text("SELECT count(*) FROM client_devices WHERE user_id=:id"), {"id": user.id})).scalar() == 0
        assert (await db.execute(text("SELECT count(*) FROM runtime_token_assignments WHERE user_id=:id"), {"id": user.id})).scalar() == 0
        assert (await db.execute(text("SELECT count(*) FROM trial_claims WHERE user_id_at_claim=:id"), {"id": user.id})).scalar() == 1
        assert (await db.execute(text("SELECT count(*) FROM token_assignment_logs WHERE user_id=:id"), {"id": user.id})).scalar() == 1
        assert (await db.execute(text("SELECT count(*) FROM token_inventory WHERE id=:id"), {"id": token_id})).scalar() == 1
        assert (await db.execute(text("SELECT count(*) FROM admin_audit_logs WHERE action='user_purged'"))).scalar() == 1


async def test_account_with_business_history_is_blocked_then_archived(client):
    user = await make_user("history-archive")
    token_id = await _attach_runtime_state(user.id)
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "INSERT INTO usage_logs "
            "(id, user_id, model, usage_type, image_count, input_tokens, output_tokens, cached_tokens, cost_usd, cost_credits, created_at) "
            "VALUES (:id, :user_id, 'gpt-image-2', 'image', 1, 0, 0, 0, 0.1, 70, now())"
        ), {"id": str(uuid.uuid4()), "user_id": user.id})
        await db.commit()

    preview = await client.get(f"/api/admin/users/{user.id}/deletion-preview", headers=ADMIN)
    assert preview.json()["mode"] == "archive"
    assert preview.json()["blockers"]["usage_logs"] == 1

    blocked = await client.delete(f"/api/admin/users/{user.id}", headers=ADMIN)
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "USER_PURGE_BLOCKED"

    archived = await client.post(
        f"/api/admin/users/{user.id}/archive",
        json={"reason": "有历史记录的测试账户"}, headers=ADMIN,
    )
    assert archived.status_code == 200
    async with AsyncSessionLocal() as db:
        row = (await db.execute(text(
            "SELECT is_active, archived_at, archived_by FROM users WHERE id=:id"
        ), {"id": user.id})).one()
        assert row.is_active is False
        assert row.archived_at is not None
        assert row.archived_by == "admin"
        assignment = (await db.execute(text(
            "SELECT status, released_at FROM runtime_token_assignments WHERE token_id=:id"
        ), {"id": token_id})).one()
        assert assignment.status == "released"
        assert assignment.released_at is not None
        assert (await db.execute(text("SELECT count(*) FROM admin_audit_logs WHERE action='user_purge_blocked'"))).scalar() == 1
        assert (await db.execute(text("SELECT count(*) FROM admin_audit_logs WHERE action='user_archived'"))).scalar() == 1

    login = await client.post("/api/auth/login", json={"username": user.username, "password": "x"})
    assert login.status_code == 403

    reactivate = await client.put(
        f"/api/admin/users/{user.id}", json={"is_active": True}, headers=ADMIN,
    )
    assert reactivate.status_code == 409
    assert reactivate.json()["detail"]["code"] == "USER_ARCHIVED"

    reassign = await client.post(
        f"/api/admin/users/{user.id}/runtime-token/assign", json={}, headers=ADMIN,
    )
    assert reassign.status_code == 409
    assert reassign.json()["detail"]["code"] == "USER_ARCHIVED"


async def test_dashboard_uses_successful_recharge_credits(client):
    user = await make_user("dashboard-credits")
    async with AsyncSessionLocal() as db:
        for status, credits in (("SUCCESS", 1250), ("FAILED", 9900)):
            await db.execute(text(
                "INSERT INTO billing_transactions "
                "(id, user_id, type, status, amount_usd, trial_amount, balance_amount, billing_source, "
                "image_count, amount_credits, trial_credits_part, gift_credits_part, paid_credits_part, created_at, updated_at) "
                "VALUES (:id, :user_id, 'RECHARGE', :status, 0, 0, 0, 'PAID', 0, :credits, 0, 0, :credits, now(), now())"
            ), {"id": str(uuid.uuid4()), "user_id": user.id, "status": status, "credits": credits})
        await db.commit()

    response = await client.get("/api/admin/stats", headers=ADMIN)
    assert response.status_code == 200
    assert response.json()["total_recharged_credits"] == 1250
    assert "token_stats" in response.json()  # 旧调用方兼容字段仍保留


async def test_login_logs_are_filterable_and_super_admin_only(client):
    normal_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "INSERT INTO admin_users "
            "(id, username, display_name, password_hash, role, is_active, must_change_password, created_at, updated_at) "
            "VALUES (:id, 'operator', 'Operator', :pw, 'admin', true, false, now(), now())"
        ), {"id": normal_id, "pw": hash_password("operator-password")})
        await db.execute(text(
            "INSERT INTO admin_audit_logs (id, admin, action, detail, created_at) "
            "VALUES (:id, 'admin', 'admin_login_success', :detail, now())"
        ), {"id": str(uuid.uuid4()), "detail": json.dumps({"ip": "10.0.0.1", "ua": "pytest"})})
        await db.execute(text(
            "INSERT INTO admin_audit_logs (id, admin, action, detail, created_at) "
            "VALUES (:id, 'operator', 'admin_login_failed', :detail, now())"
        ), {"id": str(uuid.uuid4()), "detail": json.dumps({"ip": "10.0.0.2", "ua": "pytest-bad", "reason": "bad_password"})})
        await db.commit()

    failed = await client.get(
        "/api/admin/admin-login-logs?result=failed&username=operator&page=1&page_size=10",
        headers=ADMIN,
    )
    assert failed.status_code == 200
    assert failed.json()["total"] == 1
    assert failed.json()["logs"][0]["reason"] == "bad_password"
    assert failed.json()["logs"][0]["ip"] == "10.0.0.2"

    forbidden = await client.get(
        "/api/admin/admin-login-logs",
        headers=make_admin_headers(role="admin", admin_id=normal_id, username="operator"),
    )
    assert forbidden.status_code == 403
