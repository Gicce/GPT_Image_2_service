"""Trial Entitlement V1 测试矩阵（任务规范 §49）。

覆盖：首次领取成功、同账号重复领取失败、同邮箱新账号领取失败、
邮箱大小写/空格不可绕过、试用默认 Token 禁用后 trial_available=false、
正式默认 Token 不受影响、并发双击仅一次成功。
"""

import asyncio
import uuid
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from app.main import app
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token
from app.models.token import TokenInventory
from app.models.trial import TrialClaim
from app.models.user import User
from tests.conftest import make_admin_headers


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _headers(user_id: str) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


async def _seed_tokens() -> tuple[TokenInventory, TokenInventory]:
    """创建试用默认 + 正式默认 Token，返回 (trial, paid)。"""
    async with AsyncSessionLocal() as db:
        trial = TokenInventory(
            token_value=f"sk-trial-{uuid.uuid4().hex[:12]}", name="Trial Default",
            is_trial=True, is_default=True,
        )
        paid = TokenInventory(
            token_value=f"sk-paid-{uuid.uuid4().hex[:12]}", name="Prod Default",
            is_trial=False, is_default=True,
        )
        db.add_all([trial, paid])
        await db.commit()
        return trial, paid


async def _make_normal_user(username: str, email: str) -> User:
    async with AsyncSessionLocal() as db:
        user = User(
            username=username, email=email, password_hash="x", account_type="normal",
        )
        db.add(user)
        await db.commit()
        return user


async def test_first_claim_success(client):
    """新邮箱首次领取：自动通过 + 500 试用点 + claim 记录 + 绑定试用 Token。"""
    trial_token, _ = await _seed_tokens()
    user = await _make_normal_user("tc1", "newbie@example.com")

    r = await client.post("/api/trial/claim", headers=await _headers(user.id))
    assert r.status_code == 200
    body = r.json()
    assert body["granted"] is True
    assert body["grant_credits"] == 500

    async with AsyncSessionLocal() as db:
        u = (await db.execute(select(User).where(User.id == user.id))).scalar_one()
        assert u.trial_credits == 500
        assert u.account_type == "trial"

        claim = (await db.execute(select(TrialClaim).where(
            TrialClaim.normalized_email == "newbie@example.com"))).scalar_one()
        assert claim.user_id_at_claim == user.id
        assert claim.grant_credits == 500

        from app.services import runtime_token as rt
        assignment = await rt.get_user_active_assignment(db, user.id)
        assert assignment.token_id == trial_token.id


async def test_same_account_second_claim_rejected(client):
    user = await _make_normal_user("tc2", "again@example.com")
    await _seed_tokens()

    r1 = await client.post("/api/trial/claim", headers=await _headers(user.id))
    assert r1.status_code == 200
    r2 = await client.post("/api/trial/claim", headers=await _headers(user.id))
    assert r2.status_code == 409
    assert r2.json()["detail"]["code"] == "TRIAL_ALREADY_CLAIMED"

    async with AsyncSessionLocal() as db:
        u = (await db.execute(select(User).where(User.id == user.id))).scalar_one()
        assert u.trial_credits == 500  # 只发一次


async def test_same_email_new_account_rejected(client):
    """删号重注册同邮箱：claim ledger 命中，不可再领。"""
    await _seed_tokens()
    first = await _make_normal_user("tc3a", "recycle@example.com")
    r = await client.post("/api/trial/claim", headers=await _headers(first.id))
    assert r.status_code == 200

    # 模拟注销（SQL 删除用户行；trial_claims 不级联、不被删除）
    async with AsyncSessionLocal() as db:
        from sqlalchemy import text as sql_text
        await db.execute(sql_text(
            "DELETE FROM runtime_token_assignments WHERE user_id = :uid"), {"uid": first.id})
        await db.execute(sql_text(
            "DELETE FROM billing_transactions WHERE user_id = :uid"), {"uid": first.id})
        await db.execute(sql_text("DELETE FROM users WHERE id = :uid"), {"uid": first.id})
        await db.commit()

    second = await _make_normal_user("tc3b", "recycle@example.com")
    r = await client.post("/api/trial/claim", headers=await _headers(second.id))
    assert r.status_code == 409
    assert r2_detail_code(r) == "TRIAL_ALREADY_CLAIMED"

    async with AsyncSessionLocal() as db:
        u2 = (await db.execute(select(User).where(User.id == second.id))).scalar_one()
        assert u2.trial_credits == 0


def r2_detail_code(r) -> str:
    return r.json()["detail"]["code"]


async def test_email_case_and_spaces_cannot_bypass(client):
    """ABC@x.com / abc@x.com / 前后空格 均视为同一邮箱。"""
    await _seed_tokens()
    user1 = await _make_normal_user("tc4a", "case.user@example.com")
    assert (await client.post("/api/trial/claim", headers=await _headers(user1.id))).status_code == 200

    # 同邮箱不同大小写 + 空格的新账号
    user2 = await _make_normal_user("tc4b", "Case.User@Example.com")
    r = await client.post("/api/trial/claim", headers=await _headers(user2.id))
    assert r.status_code == 409

    # 服务端 normalize（trim+lower）——直接构造带空格存储的账号
    async with AsyncSessionLocal() as db:
        user3 = User(username="tc4c", email="  case.user@example.com  ", password_hash="x")
        db.add(user3)
        await db.commit()
        uid3 = user3.id
    r = await client.post("/api/trial/claim", headers=await _headers(uid3))
    assert r.status_code == 409


async def test_trial_token_disabled_closes_entry(client):
    """禁用试用默认 Token → trial_available=false；正式默认不受影响。"""
    trial_token, paid_token = await _seed_tokens()
    user = await _make_normal_user("tc5", "gate@example.com")

    r = await client.get("/api/trial/status", headers=await _headers(user.id))
    assert r.status_code == 200
    assert r.json()["trial_available"] is True

    async with AsyncSessionLocal() as db:
        t = await db.get(TokenInventory, trial_token.id)
        t.is_disabled = True
        await db.commit()

    r = await client.get("/api/trial/status", headers=await _headers(user.id))
    assert r.json()["trial_available"] is False
    assert r.json()["reason"] == "trial_token_unavailable"

    # 领取也被拒绝
    r = await client.post("/api/trial/claim", headers=await _headers(user.id))
    assert r.status_code == 403

    # 正式默认 Token 解析不受影响（ensure_paid_assignment 仍可用）
    from app.services import runtime_token as rt
    async with AsyncSessionLocal() as db:
        paid_default = await rt.resolve_default_token(db, is_trial=False)
        assert paid_default is not None and paid_default.id == paid_token.id
        trial_default = await rt.resolve_default_token(db, is_trial=True)
        assert trial_default is None


async def test_trial_feature_switch_closes_entry(client):
    """总开关关闭 → 不可领取；开启恢复。"""
    await _seed_tokens()
    user = await _make_normal_user("tc6", "switch@example.com")

    async with AsyncSessionLocal() as db:
        from app.services import config_service
        await config_service.set_config(db, "trial_feature_enabled", "false")
        await db.commit()

    r = await client.post("/api/trial/claim", headers=await _headers(user.id))
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "TRIAL_TRIAL_DISABLED"

    async with AsyncSessionLocal() as db:
        from app.services import config_service
        await config_service.set_config(db, "trial_feature_enabled", "true")
        await db.commit()

    r = await client.post("/api/trial/claim", headers=await _headers(user.id))
    assert r.status_code == 200


async def test_concurrent_double_click_single_success(client):
    """并发双击：唯一约束保证只有一次成功入账 500 点。"""
    await _seed_tokens()
    user = await _make_normal_user("tc7", "race@example.com")

    responses = await asyncio.gather(
        client.post("/api/trial/claim", headers=await _headers(user.id)),
        client.post("/api/trial/claim", headers=await _headers(user.id)),
        client.post("/api/trial/claim", headers=await _headers(user.id)),
    )
    codes = sorted(r.status_code for r in responses)
    assert codes.count(200) == 1
    assert codes.count(409) == 2

    async with AsyncSessionLocal() as db:
        u = (await db.execute(select(User).where(User.id == user.id))).scalar_one()
        assert u.trial_credits == 500
        claims = (await db.execute(select(TrialClaim).where(
            TrialClaim.normalized_email == "race@example.com"))).scalars().all()
        assert len(claims) == 1


async def test_register_trial_writes_claim_and_legacy_upgrade(client):
    """注册试用流写 claim；旧 /upgrade-trial 入口对齐（已领 → 400 明确文案）。"""
    await _seed_tokens()

    r = await client.post("/api/auth/register", json={
        "username": "tc8", "email": "reg@example.com", "password": "Passw0rd!123",
        "account_type": "trial",
    })
    assert r.status_code == 200
    token = r.json()["access_token"]
    user_info = r.json()["user"]
    assert user_info["trial_credits"] == 500

    async with AsyncSessionLocal() as db:
        claims = (await db.execute(select(TrialClaim).where(
            TrialClaim.normalized_email == "reg@example.com"))).scalars().all()
        assert len(claims) == 1

    # 同邮箱再注册试用 → 静默降级为 normal（不发放）
    r2 = await client.post("/api/auth/register", json={
        "username": "tc8b", "email": "reg@example.com", "password": "Passw0rd!123",
        "account_type": "trial",
    })
    # 邮箱唯一约束：注册本身失败（与领取规则无冲突）
    assert r2.status_code == 400

    # 旧客户端入口：该账号已领 → 明确拒绝
    r3 = await client.post("/api/auth/upgrade-trial", headers={"Authorization": f"Bearer {token}"})
    assert r3.status_code == 400
