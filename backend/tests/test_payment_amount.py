"""充值金额校验与人民币换算测试：金额边界、USD→CNY、CNY→分。"""

import pytest
from fastapi import HTTPException

from app.api.routes import payment
from app.core.redis import get_redis


async def test_validate_amount_rejects_below_min():
    with pytest.raises(HTTPException) as ei:
        await payment._validate_amount(0.5)
    assert ei.value.status_code == 400


async def test_validate_amount_rejects_above_max():
    with pytest.raises(HTTPException) as ei:
        await payment._validate_amount(2000.0)
    assert ei.value.status_code == 400


async def test_validate_amount_usd_to_cny_uses_cached_rate():
    redis = get_redis()
    await redis.setex("exchange_rate_usd_cny", 60, "6.7480")
    try:
        amount_cny, rate = await payment._validate_amount(5.0)
        assert amount_cny == 33.74
        assert rate == 6.748
    finally:
        await redis.delete("exchange_rate_usd_cny")


async def test_cny_to_fen_conversion():
    """微信金额单位为分：int(round(cny * 100)) 必须精确。"""
    assert int(round(33.74 * 100)) == 3374
    assert int(round(0.01 * 100)) == 1
    assert int(round(0.3 * 100)) == 30


async def test_create_order_rejects_missing_amount():
    import httpx
    from app.main import app
    from tests.conftest import make_user
    from app.core.security import create_access_token

    user = await make_user("amt1")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/pay/create_order", json={}, headers={
            "Authorization": f"Bearer {create_access_token(user.id)}"
        })
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "INVALID_RECHARGE_AMOUNT"
