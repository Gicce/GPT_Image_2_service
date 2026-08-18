"""Runtime Token 共享池链路（1 Token → N Users、默认 Token、有效期/额度、自动绑定）。"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import text

from app.main import app
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, create_admin_token
from tests.conftest import make_admin_headers, make_user

ADMIN_HEADERS = make_admin_headers()


async def insert_token(
    value: str = None, trial=False, disabled=False, default=False,
    quota=None, expires_in_days=None, name=None,
) -> str:
    tid = str(uuid.uuid4())
    value = value or f"sk-{tid.replace('-', '')[:24]}"
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "INSERT INTO token_inventory "
            "(id, token_value, name, is_trial, is_default, quota_usd, expires_at, is_assigned, is_disabled, assigned_to, created_at) "
            "VALUES (:id, :val, :name, :t, :df, :quota, :exp, false, :d, NULL, now())"
        ), {
            "id": tid, "val": value, "name": name, "t": trial, "df": default,
            "quota": quota,
            "exp": (
                datetime.now(timezone.utc) + timedelta(days=expires_in_days)
                if expires_in_days is not None else None
            ),
            "d": disabled,
        })
        await db.commit()
    return tid


async def bind_directly(token_id: str, user_id: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "INSERT INTO runtime_token_assignments (id, token_id, user_id, status, source, assigned_at) "
            "VALUES (gen_random_uuid()::text, :tid, :uid, 'active', 'test', now()) "
            "ON CONFLICT (token_id, user_id) DO UPDATE SET status = 'active'"
        ), {"tid": token_id, "uid": user_id})
        await db.commit()


async def active_assignment_count(token_id: str) -> int:
    async with AsyncSessionLocal() as db:
        result = await db.execute(text(
            "SELECT COUNT(*) FROM runtime_token_assignments "
            "WHERE token_id = :tid AND status = 'active'"
        ), {"tid": token_id})
        return result.scalar()


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_shared_token_serves_multiple_users(client):
    """CASE 1：同一 Token 可绑定多个用户（1 Token → N Users）。"""
    u1 = await make_user("shared1", "0", "0")
    u2 = await make_user("shared2", "0", "0")
    u3 = await make_user("shared3", "0", "0")
    tid = await insert_token(name="主正式 Token")

    for uid in (u1.id, u2.id, u3.id):
        r = await client.post(
            f"/api/admin/users/{uid}/runtime-token/assign",
            json={"token_id": tid}, headers=ADMIN_HEADERS,
        )
        assert r.status_code == 200

    assert await active_assignment_count(tid) == 3

    r = await client.get("/api/admin/tokens", headers=ADMIN_HEADERS)
    target = next(t for t in r.json()["tokens"] if t["id"] == tid)
    assert target["user_count"] == 3
    assert target["name"] == "主正式 Token"

    detail = (await client.get(f"/api/admin/tokens/{tid}", headers=ADMIN_HEADERS)).json()
    assert detail["user_count"] == 3
    usernames = {u["username"] for u in detail["users"]}
    assert usernames == {"shared1", "shared2", "shared3"}


async def test_user_keeps_one_active_token_on_rebind(client):
    """用户换绑：旧 Token 释放，同一时刻只有一个 active 绑定。"""
    user = await make_user("rebind", "0", "0")
    t1 = await insert_token()
    t2 = await insert_token()
    await bind_directly(t1, user.id)

    r = await client.post(
        f"/api/admin/users/{user.id}/runtime-token/assign",
        json={"token_id": t2}, headers=ADMIN_HEADERS,
    )
    assert r.status_code == 200
    assert r.json()["released_token_id"] == t1

    assert await active_assignment_count(t1) == 0
    assert await active_assignment_count(t2) == 1


async def test_set_default_switches_within_type(client):
    """默认 Token 唯一性：设新默认时同类型旧默认自动清除；正式/试用各自独立。"""
    paid_a = await insert_token(default=True, name="Paid A")
    paid_b = await insert_token(name="Paid B")
    trial_a = await insert_token(trial=True, default=True, name="Trial A")
    trial_b = await insert_token(trial=True, name="Trial B")

    r = await client.post(f"/api/admin/tokens/{paid_b}/set-default", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    r = await client.post(f"/api/admin/tokens/{trial_b}/set-default", headers=ADMIN_HEADERS)
    assert r.status_code == 200

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(text(
            "SELECT id, is_default FROM token_inventory WHERE id IN (:a, :b, :c, :d)"
        ), {"a": paid_a, "b": paid_b, "c": trial_a, "d": trial_b})).all()
    default_map = {row.id: row.is_default for row in rows}
    assert default_map == {paid_a: False, paid_b: True, trial_a: False, trial_b: True}


async def test_default_switch_does_not_migrate_existing_users(client):
    """默认切换只影响新绑定：已绑定用户不迁移。"""
    user = await make_user("stayme", "0", "0")
    paid_a = await insert_token(default=True)
    paid_b = await insert_token()
    await bind_directly(paid_a, user.id)

    await client.post(f"/api/admin/tokens/{paid_b}/set-default", headers=ADMIN_HEADERS)

    from app.services import runtime_token as rt
    async with AsyncSessionLocal() as db:
        token = await rt.get_user_active_token(db, user.id)
        assert token.id == paid_a  # 用户仍在 A


async def test_payment_auto_binds_default_paid_token(client, monkeypatch):
    """支付成功 → 自动绑定默认正式 Token；已有正式绑定的用户保持不变。"""
    from app.api.routes import payment as payment_routes
    from app.services.order_assignment import assign_paid_order
    from sqlalchemy import select
    from app.models.token import Order, OrderStatus

    monkeypatch.setattr(payment_routes, "should_use_dev_payment", lambda: True)
    user = await make_user("autobind", "0", "0")
    paid_default = await insert_token(default=True, name="默认正式")

    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    r = await client.post("/api/pay/create_order", json={"amount_usd": 1}, headers=headers)
    assert r.status_code == 200
    out_trade_no = r.json()["out_trade_no"]

    async with AsyncSessionLocal() as db:
        order = (await db.execute(
            select(Order).where(Order.out_trade_no == out_trade_no)
        )).scalar_one()
        order.status = OrderStatus.PAID
        order.paid_at = datetime.now(timezone.utc)
        await assign_paid_order(db, order)
        await db.commit()

    assert await active_assignment_count(paid_default) == 1

    # 管理员切换默认后，再充值的新用户绑新默认；老用户不动
    paid_b = await insert_token(name="新默认")
    await client.post(f"/api/admin/tokens/{paid_b}/set-default", headers=ADMIN_HEADERS)
    user2 = await make_user("autobind2", "0", "0")
    r = await client.post("/api/pay/create_order", json={"amount_usd": 1},
                          headers={"Authorization": f"Bearer {create_access_token(user2.id)}"})
    async with AsyncSessionLocal() as db:
        order2 = (await db.execute(
            select(Order).where(Order.out_trade_no == r.json()["out_trade_no"])
        )).scalar_one()
        order2.status = OrderStatus.PAID
        order2.paid_at = datetime.now(timezone.utc)
        await assign_paid_order(db, order2)
        await db.commit()

    assert await active_assignment_count(paid_b) == 1
    assert await active_assignment_count(paid_default) == 1  # 老用户未被迁移


async def test_register_trial_binds_default_trial_token(client):
    """注册试用：绑定默认试用 Token（共享，不消耗库存）+ 发放试用额度。"""
    await insert_token(trial=True, default=True, name="试用线路 01")

    r = await client.post("/api/auth/register", json={
        "username": "trialuser", "email": "trialuser@example.org",
        "password": "Passw0rd!123", "account_type": "trial",
    })
    assert r.status_code == 200

    async with AsyncSessionLocal() as db:
        uid = (await db.execute(text(
            "SELECT id FROM users WHERE username = 'trialuser'"
        ))).scalar()
        count = (await db.execute(text(
            "SELECT COUNT(*) FROM runtime_token_assignments a "
            "JOIN token_inventory t ON t.id = a.token_id "
            "WHERE a.user_id = :uid AND a.status = 'active' AND t.is_trial = true"
        ), {"uid": uid})).scalar()
    assert count == 1


async def test_token_effective_status_matrix(client):
    """Token 派生状态：禁用 / 过期 / 额度耗尽 / 正常。"""
    from app.models.token import TokenInventory
    from app.services import runtime_token as rt

    async with AsyncSessionLocal() as db:
        disabled = await db.get(TokenInventory, await insert_token(disabled=True))
        expired = await db.get(TokenInventory, await insert_token(expires_in_days=-1))
        fresh = await db.get(TokenInventory, await insert_token(expires_in_days=1))
        quota_ok = await db.get(TokenInventory, await insert_token(quota="10.0"))

        assert await rt.token_effective_status(db, disabled) == "disabled"
        assert await rt.token_effective_status(db, expired) == "expired"
        assert await rt.token_effective_status(db, fresh) == "active"
        assert await rt.token_effective_status(db, quota_ok) == "active"

    # 额度耗尽：给 quota Token 绑一个有消费的用户
    spender = await make_user("spender", "0", "0")
    await bind_directly(quota_ok.id, spender.id)
    async with AsyncSessionLocal() as s2:
        await s2.execute(text(
            "INSERT INTO usage_logs (id, user_id, model, usage_type, image_count, "
            "input_tokens, output_tokens, cached_tokens, cost_usd, created_at) "
            "VALUES (gen_random_uuid()::text, :uid, 'gpt-image-2', 'image', 1, 0, 0, 0, 10.0, now())"
        ), {"uid": spender.id})
        await s2.commit()
    async with AsyncSessionLocal() as db:
        assert await rt.token_effective_status(db, quota_ok) == "exhausted"


async def test_runtime_config_falls_back_when_token_invalid(client, monkeypatch):
    """绑定 Token 失效（禁用/过期）→ runtime-config 回落 Master Token。"""
    from app.core.config import settings
    user = await make_user("fallback", "1", "0")
    tid = await insert_token(disabled=True, value="sk-DISABLEDISABLEDISA1")
    await bind_directly(tid, user.id)
    monkeypatch.setattr(settings, "PACKYAPI_IMAGE_MASTER_TOKEN", "sk-MASTERMASTERMASTERMA", raising=False)

    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    r = await client.get("/api/users/me/runtime-config", headers=headers)
    assert r.json()["image"]["token"] == "sk-MASTERMASTERMASTERMA"


async def test_token_delete_guard_with_active_users(client):
    """有关联用户的 Token 禁止物理删除，提示关联数量。"""
    user = await make_user("guard", "0", "0")
    tid = await insert_token()
    await bind_directly(tid, user.id)

    r = await client.delete(f"/api/admin/tokens/{tid}", headers=ADMIN_HEADERS)
    assert r.status_code == 400
    assert "1 个用户" in r.json()["detail"]

    # 无关联时可删除
    free = await insert_token()
    r = await client.delete(f"/api/admin/tokens/{free}", headers=ADMIN_HEADERS)
    assert r.status_code == 200


async def test_token_detail_user_search(client):
    """Token 详情支持按用户名搜索关联用户。"""
    tid = await insert_token()
    u1 = await make_user("findable", "0", "0")
    u2 = await make_user("hiddenxx", "0", "0")
    await bind_directly(tid, u1.id)
    await bind_directly(tid, u2.id)

    r = await client.get(f"/api/admin/tokens/{tid}", params={"search": "findable"}, headers=ADMIN_HEADERS)
    data = r.json()
    assert data["user_count"] == 1
    assert data["users"][0]["username"] == "findable"


async def test_user_replace_endpoint_removed(client):
    """普通用户手动领取/更换 Token 入口已移除（自动绑定 + 管理员操作）。"""
    user = await make_user("norpl", "0", "0")
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    r = await client.post("/api/users/me/runtime-token/replace", headers=headers)
    assert r.status_code in (404, 405)


async def test_create_order_accepts_legacy_total_usd(client, monkeypatch):
    """充值兼容：V3 旧客户端 total_usd 字段可直接下单（开发模式跳过微信）。"""
    from app.api.routes import payment as payment_routes
    monkeypatch.setattr(payment_routes, "should_use_dev_payment", lambda: True)
    user = await make_user("buyer", "0", "0")

    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    r = await client.post("/api/pay/create_order", json={"total_usd": 5}, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["amount_usd"] == 5
    assert body["status"] == "pending"

    r = await client.post("/api/pay/create_order", json={"amount_usd": 6}, headers=headers)
    assert r.status_code == 200


async def test_create_order_debounces_rapid_duplicates(client, monkeypatch):
    """服务端防连击：10 秒内同用户已有待支付订单 → 429。"""
    from app.api.routes import payment as payment_routes
    monkeypatch.setattr(payment_routes, "should_use_dev_payment", lambda: True)
    user = await make_user("buyer3", "0", "0")

    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    r = await client.post("/api/pay/create_order", json={"amount_usd": 5}, headers=headers)
    assert r.status_code == 200
    first_no = r.json()["out_trade_no"]

    r = await client.post("/api/pay/create_order", json={"amount_usd": 5}, headers=headers)
    assert r.status_code == 429

    from sqlalchemy import select
    from app.models.token import Order
    async with AsyncSessionLocal() as db:
        orders = (await db.execute(
            select(Order.out_trade_no).where(Order.user_id == user.id)
        )).scalars().all()
    assert orders == [first_no]


async def test_create_order_missing_amount_returns_explicit_422(client, monkeypatch):
    """amount_usd / total_usd 均缺失 → 422 且返回结构化原因。"""
    from app.api.routes import payment as payment_routes
    monkeypatch.setattr(payment_routes, "should_use_dev_payment", lambda: True)
    user = await make_user("buyer2", "0", "0")

    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    r = await client.post("/api/pay/create_order", json={"foo": 1}, headers=headers)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["code"] == "INVALID_RECHARGE_AMOUNT"
    assert "amount_usd" in detail["message"]
