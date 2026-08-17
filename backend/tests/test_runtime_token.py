"""Runtime Token 分配链路（Token↔User 映射、脱敏、更换事务、兼容充值金额字段）。"""

import uuid
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import text

from app.main import app
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, create_admin_token
from tests.conftest import make_user

ADMIN_HEADERS = {"Authorization": f"Bearer {create_admin_token()}"}


async def insert_token(value: str = None, trial=False, disabled=False) -> str:
    tid = str(uuid.uuid4())
    value = value or f"sk-{tid.replace('-', '')[:24]}"
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "INSERT INTO token_inventory (id, token_value, is_trial, is_assigned, is_disabled, assigned_to, created_at) "
            "VALUES (:id, :val, :t, false, :d, NULL, now())"
        ), {"id": tid, "val": value, "t": trial, "d": disabled})
        await db.commit()
    return tid


async def assign_token_directly(token_id: str, user_id: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "UPDATE token_inventory SET is_assigned = true, assigned_to = :uid, assigned_at = now() "
            "WHERE id = :tid"
        ), {"uid": user_id, "tid": token_id})
        await db.commit()


async def token_row(token_id: str):
    async with AsyncSessionLocal() as db:
        result = await db.execute(text(
            "SELECT is_assigned, assigned_to FROM token_inventory WHERE id = :tid"
        ), {"tid": token_id})
        return result.one()


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_admin_token_list_shows_assigned_user(client):
    """CASE 1：Token 列表返回 assigned_username / assigned_email，而不是只有 UUID。"""
    user = await make_user("bbs", "0", "0")
    tid = await insert_token()
    await assign_token_directly(tid, user.id)

    r = await client.get("/api/admin/tokens", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    target = next(t for t in r.json()["tokens"] if t["id"] == tid)
    assert target["is_assigned"] is True
    assert target["assigned_username"] == "bbs"
    assert target["assigned_email"] == "bbs@test.local"

    # 未分配 Token 不携带用户信息
    free_tid = await insert_token()
    free = next(t for t in (await client.get("/api/admin/tokens", headers=ADMIN_HEADERS)).json()["tokens"]
                if t["id"] == free_tid)
    assert free["assigned_username"] is None


async def test_admin_token_search_by_user_and_suffix(client):
    """Token 库存筛选：按用户名 / 邮箱 / Token 后四位搜索。"""
    user = await make_user("searchme", "0", "0")
    tid = await insert_token(value="sk-AAAABBBBCCCCDDDD1234")
    await assign_token_directly(tid, user.id)
    await insert_token(value="sk-ZZZZ000011112222")  # 干扰项

    for q in ("searchme", "searchme@test.local", "D1234", "d1234"):
        r = await client.get("/api/admin/tokens", params={"search": q}, headers=ADMIN_HEADERS)
        ids = [t["id"] for t in r.json()["tokens"]]
        assert tid in ids, f"search={q} 应命中目标 Token"
        assert len(ids) == 1, f"search={q} 只应命中一个 Token"


async def test_admin_user_detail_contains_masked_runtime_token(client):
    """CASE 2：用户详情返回 runtime_token（脱敏，含类型/状态/分配时间）。"""
    user = await make_user("detailu", "0", "0")
    tid = await insert_token(value="sk-iQU8XXXXXXXXXXXXTQZp")
    await assign_token_directly(tid, user.id)

    r = await client.get(f"/api/admin/users/{user.id}", headers=ADMIN_HEADERS)
    rt = r.json()["runtime_token"]
    assert rt["token_id"] == tid
    assert rt["masked_token"] == "sk-iQU****TQZp"
    assert "iQU8XXXXXXXXXXXXTQZp" not in r.text  # 明文绝不出现
    assert rt["assigned_at"] is not None


async def test_me_runtime_token_same_masked_value(client):
    """CASE 3：客户端 /me/runtime-token 与后台看到同一个 masked token。"""
    user = await make_user("cli", "0", "0")
    tid = await insert_token(value="sk-iQU8XXXXXXXXXXXXTQZp")
    await assign_token_directly(tid, user.id)

    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    r = await client.get("/api/users/me/runtime-token", headers=headers)
    data = r.json()
    assert data["assigned"] is True
    assert data["source"] == "assigned"
    assert data["masked_token"] == "sk-iQU****TQZp"
    assert "token_id" in data and data["token_id"] == tid


async def test_replace_with_available_token(client):
    """CASE 4：有可用 Token 时更换 → 旧解绑、新绑定、写分配历史。"""
    user = await make_user("rep", "0", "0")
    old_tid = await insert_token(value="sk-OLDOLDOLDOLDOLDOLD1")
    await assign_token_directly(old_tid, user.id)
    new_tid = await insert_token(value="sk-NEWNEWNEWNEWNEWNEW2")

    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    r = await client.post("/api/users/me/runtime-token/replace", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["replaced"] is True
    assert data["masked_token"].startswith("sk-NEW****")

    old = await token_row(old_tid)
    new = await token_row(new_tid)
    assert old.is_assigned is False and old.assigned_to is None
    assert new.is_assigned is True and new.assigned_to == user.id

    async with AsyncSessionLocal() as db:
        logs = (await db.execute(text(
            "SELECT action, source FROM token_assignment_logs WHERE user_id = :uid ORDER BY created_at"
        ), {"uid": user.id})).all()
    actions = [(l.action, l.source) for l in logs]
    assert ("release", "user_replace") in actions
    assert ("assign", "user_replace") in actions


async def test_replace_without_available_token_keeps_old(client):
    """CASE 5：无可用 Token 时更换 → 409 + NO_AVAILABLE_RUNTIME_TOKEN，旧绑定不变。"""
    user = await make_user("norep", "0", "0")
    old_tid = await insert_token()
    await assign_token_directly(old_tid, user.id)

    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    r = await client.post("/api/users/me/runtime-token/replace", headers=headers)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "NO_AVAILABLE_RUNTIME_TOKEN"

    old = await token_row(old_tid)
    assert old.is_assigned is True and old.assigned_to == user.id


async def test_replace_skips_trial_and_disabled_tokens(client):
    """用户更换只挑正式可用 Token；试用卡与禁用卡不算可用库存。"""
    user = await make_user("skip", "0", "0")
    await insert_token(trial=True)
    await insert_token(disabled=True)

    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    r = await client.post("/api/users/me/runtime-token/replace", headers=headers)
    assert r.status_code == 409


async def test_admin_assign_and_runtime_config_prefers_assigned(client, monkeypatch):
    """管理员分配 → 客户端 runtime-config 下发的是用户绑定 Token 的明文。"""
    from app.core.config import settings
    user = await make_user("adm", "1", "0")  # runtime-config 要求账户有可用额度
    tid = await insert_token(value="sk-USERUSERUSERUSERUSER9")
    monkeypatch.setattr(settings, "PACKYAPI_IMAGE_MASTER_TOKEN", "sk-MASTERMASTERMASTERMA", raising=False)

    r = await client.post(
        f"/api/admin/users/{user.id}/runtime-token/assign",
        json={"token_id": tid}, headers=ADMIN_HEADERS,
    )
    assert r.status_code == 200
    assert r.json()["runtime_token"]["masked_token"].startswith("sk-USE****")

    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    r = await client.get("/api/users/me/runtime-config", headers=headers)
    token = r.json()["image"]["token"]
    assert token == "sk-USERUSERUSERUSERUSER9"  # 优先用户绑定 Token 而非 Master


async def test_admin_assign_conflict_on_assigned_token(client):
    """指定已分配给他人的 Token → 400，双方绑定不变。"""
    u1 = await make_user("own1", "0", "0")
    u2 = await make_user("own2", "0", "0")
    tid = await insert_token()
    await assign_token_directly(tid, u1.id)

    r = await client.post(
        f"/api/admin/users/{u2.id}/runtime-token/assign",
        json={"token_id": tid}, headers=ADMIN_HEADERS,
    )
    assert r.status_code == 400
    row = await token_row(tid)
    assert row.assigned_to == u1.id


async def test_create_order_accepts_legacy_total_usd(client, monkeypatch):
    """充值兼容：V3 旧客户端 total_usd 字段可直接下单（开发模式跳过微信）。"""
    from app.api.routes import payment as payment_routes
    from app.core.config import settings
    monkeypatch.setattr(settings, "APP_ENV", "development", raising=False)
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
    """服务端防连击：10 秒内同用户已有待支付订单 → 429，不再重复创建微信订单。"""
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
    """amount_usd / total_usd 均缺失 → 422 且返回结构化原因（不再 [object Object]）。"""
    from app.api.routes import payment as payment_routes
    monkeypatch.setattr(payment_routes, "should_use_dev_payment", lambda: True)
    user = await make_user("buyer2", "0", "0")

    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    r = await client.post("/api/pay/create_order", json={"foo": 1}, headers=headers)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["code"] == "INVALID_RECHARGE_AMOUNT"
    assert "amount_usd" in detail["message"]
