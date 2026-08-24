"""HTTP 层计费端点测试：authorize/settle 语义、402 QUOTA_EXHAUSTED 错误形态、
管理端 Image2 配置校验与审计、Prompt/ServiceGroup API 已删除。"""

import pytest
import httpx
from decimal import Decimal

from app.main import app
from app.core.security import create_access_token
from tests.conftest import make_admin_headers, make_user, get_user


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def auth_headers(user_id: str) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


ADMIN_HEADERS = make_admin_headers()


async def test_authorize_settle_http_flow(client):
    user = await make_user("h1", "1.00", "0")
    r = await client.post("/api/usage/authorize", json={
        "request_id": "http-req-0001", "image_count": 2,
    }, headers=await auth_headers(user.id))
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "RESERVED"
    assert data["amount_usd"] == "0.140000"
    assert data["unit_price_usd"] == "0.070000"

    r = await client.post("/api/usage/settle", json={
        "request_id": "http-req-0001", "success": True,
    }, headers=await auth_headers(user.id))
    assert r.status_code == 200
    assert r.json()["status"] == "SUCCESS"

    row = await get_user(user.id)
    assert row.balance_usd == Decimal("0.860000")


async def test_quota_exhausted_error_shape(client):
    """402 + QUOTA_EXHAUSTED + 固定文案「点数不足，请充值后继续使用」。"""
    user = await make_user("h2", "0", "0")
    r = await client.post("/api/usage/authorize", json={
        "request_id": "http-req-0002", "image_count": 1,
    }, headers=await auth_headers(user.id))
    assert r.status_code == 402
    body = r.json()
    assert body["detail"]["code"] == "QUOTA_EXHAUSTED"
    assert body["detail"]["message"] == "点数不足，请充值后继续使用"


async def test_settle_unknown_request_404(client):
    user = await make_user("h3", "1.00", "0")
    r = await client.post("/api/usage/settle", json={
        "request_id": "no-such-req-xx", "success": True,
    }, headers=await auth_headers(user.id))
    assert r.status_code == 404


async def test_image2_config_get_put_and_audit(client):
    r = await client.get("/api/admin/image2-config", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    cfg = r.json()
    assert cfg["model_id"] == "gpt-image-2"
    assert cfg["billing_mode"] == "per_call"
    assert cfg["currency"] == "USD"
    assert cfg["price_per_call_usd"] == "0.070000"

    # 合法改价
    r = await client.put("/api/admin/image2-config", json={
        "price_per_call_usd": "0.075000",
    }, headers=ADMIN_HEADERS)
    assert r.status_code == 200
    assert "price_per_call_usd" in r.json()["changed"]

    r = await client.get("/api/admin/image2-config", headers=ADMIN_HEADERS)
    assert r.json()["price_per_call_usd"] == "0.075000"

    # 价格修改审计日志
    r = await client.get("/api/admin/audit-logs", headers=ADMIN_HEADERS)
    logs = r.json()["logs"]
    assert any(l["action"] == "image2_price_update" for l in logs)

    # 非法价格（0 / 负数 / 超过 6 位小数）被拒绝
    for bad in ("0", "-1", "0.1234567", "abc"):
        r = await client.put("/api/admin/image2-config", json={
            "price_per_call_usd": bad,
        }, headers=ADMIN_HEADERS)
        assert r.status_code == 422, bad


async def test_deleted_admin_apis_return_404(client):
    """Test 14/15：Prompt 与 Service Group 管理 API 已不存在。"""
    for path, method in [
        ("/api/admin/prompts", "GET"),
        ("/api/admin/prompts", "POST"),
        ("/api/admin/groups", "GET"),
        ("/api/admin/groups", "POST"),
        ("/api/admin/models", "GET"),
        ("/api/admin/models", "POST"),
    ]:
        r = await client.request(method, path, headers=ADMIN_HEADERS)
        assert r.status_code == 404, f"{method} {path} -> {r.status_code}"

    # 公开 prompts 路由也已删除
    r = await client.get("/api/prompts")
    assert r.status_code == 404


async def test_public_models_single_entry(client):
    r = await client.get("/api/models")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list) and len(data) == 1
    assert data[0]["name"] == "gpt-image-2"
    assert data[0]["model_type"] == "image"
    assert data[0]["billing_type"] == "per_call"


async def test_me_and_entitlements_shape(client):
    user = await make_user("h4", "3.42", "0.14")
    h = await auth_headers(user.id)
    r = await client.get("/api/users/me", headers=h)
    assert r.status_code == 200
    me = r.json()
    assert me["balance_usd"] == "3.420000"
    assert me["trial_credit_usd"] == "0.140000"
    assert "tokens" not in me

    r = await client.get("/api/users/me/entitlements", headers=h)
    ent = r.json()
    assert ent["total_credit_usd"] == "3.560000"
    assert ent["enabled_features"]["image"] is True
    assert ent["enabled_models"] == ["gpt-image-2"]
