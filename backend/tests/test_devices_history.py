"""Device History V1 测试矩阵（任务规范 §52）+ 汇率来源语义（§53）。"""

import asyncio
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from app.main import app
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token
from app.models.device import ClientDevice
from app.models.user import User
from tests.conftest import make_admin_headers

ADMIN = make_admin_headers()


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _make_user(username: str) -> User:
    async with AsyncSessionLocal() as db:
        user = User(username=username, email=f"{username}@test.local", password_hash="x")
        db.add(user)
        await db.commit()
        return user


async def _headers(user_id: str) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


async def _heartbeat(client, user_id, device_id, name="PC", version="4.2.0", platform="windows"):
    return await client.post("/api/client/heartbeat", headers=await _headers(user_id), json={
        "device_id": device_id, "device_name": name,
        "app_version": version, "platform": platform,
    })


async def test_first_heartbeat_creates_device(client):
    user = await _make_user("dv1")
    r = await _heartbeat(client, user.id, "dev-001")
    assert r.status_code == 200

    async with AsyncSessionLocal() as db:
        device = (await db.execute(select(ClientDevice).where(
            ClientDevice.device_id == "dev-001"))).scalar_one()
        assert device.user_id == user.id
        assert device.client_version == "4.2.0"
        assert device.first_seen_at is not None
        assert device.heartbeat_count == 1


async def test_second_heartbeat_updates_last_seen_not_duplicate(client):
    user = await _make_user("dv2")
    await _heartbeat(client, user.id, "dev-002")
    await asyncio.sleep(0.05)
    await _heartbeat(client, user.id, "dev-002", version="4.2.1")

    async with AsyncSessionLocal() as db:
        devices = (await db.execute(select(ClientDevice).where(
            ClientDevice.device_id == "dev-002"))).scalars().all()
        assert len(devices) == 1
        assert devices[0].heartbeat_count == 2
        assert devices[0].client_version == "4.2.1"  # 信息更新
        assert devices[0].last_seen_at > devices[0].first_seen_at


async def test_offline_device_persists_and_reonline(client):
    """离线（Redis 过期）后设备记录仍在；重新上线恢复 online。"""
    from app.core.redis import get_redis

    user = await _make_user("dv3")
    await _heartbeat(client, user.id, "dev-003")

    # 手动清掉 Redis 心跳 key 模拟离线
    redis = get_redis()
    await redis.delete(f"online_device:{user.id}:dev-003")

    r = await client.get("/api/admin/devices?status=offline", headers=ADMIN)
    rows = [d for d in r.json()["devices"] if d["device_id"] == "dev-003"]
    assert len(rows) == 1  # 历史仍在
    assert rows[0]["status"] == "offline"
    assert rows[0]["seconds_since_seen"] >= 0

    # 重新上线
    await _heartbeat(client, user.id, "dev-003")
    r = await client.get("/api/admin/devices?status=online", headers=ADMIN)
    rows = [d for d in r.json()["devices"] if d["device_id"] == "dev-003"]
    assert len(rows) == 1
    assert rows[0]["status"] == "online"


async def test_seconds_since_seen_never_negative(client):
    """服务器时钟计算 seconds_since_seen，恒 >= 0（负时间 Bug 回归）。"""
    from datetime import datetime, timedelta, timezone

    user = await _make_user("dv4")
    await _heartbeat(client, user.id, "dev-004")

    # 恶意构造：直接把 last_seen_at 写到未来（模拟时钟漂移/未来时间戳）
    future = datetime.now(timezone.utc) + timedelta(seconds=28)
    async with AsyncSessionLocal() as db:
        device = (await db.execute(select(ClientDevice).where(
            ClientDevice.device_id == "dev-004"))).scalar_one()
        device.last_seen_at = future
        await db.commit()

    r = await client.get("/api/admin/devices", headers=ADMIN)
    row = [d for d in r.json()["devices"] if d["device_id"] == "dev-004"][0]
    assert row["seconds_since_seen"] == 0  # max(0, negative) = 0，绝不出现 -28


async def test_device_counts_and_filters(client):
    user = await _make_user("dv5")
    await _heartbeat(client, user.id, "dev-a")
    await _heartbeat(client, user.id, "dev-b")

    r = await client.get("/api/admin/devices", headers=ADMIN)
    body = r.json()
    assert body["online_count"] == 2
    assert body["history_count"] == 2

    r = await client.get("/api/admin/devices?status=online", headers=ADMIN)
    assert all(d["online"] for d in r.json()["devices"])

    # 兼容旧入口
    r = await client.get("/api/admin/online-devices", headers=ADMIN)
    assert r.status_code == 200
    assert r.json()["total"] >= 2
    assert all(d.get("last_seen") for d in r.json()["devices"])


# ── 汇率来源语义（§53） ────────────────────────────────────────────

async def test_packages_exchange_rate_semantics(client):
    """packages 返回汇率来源语义：来源类型与文案规则一致，缓存来源带更新时间。"""
    from app.core.redis import get_redis

    redis = get_redis()
    # 构造缓存命中（cached 来源）
    await redis.setex("exchange_rate_usd_cny", 3600, "6.73")
    await redis.setex("exchange_rate_usd_cny_at", 3600, "2026-08-24T00:00:00+00:00")

    r = await client.get("/api/pay/packages")
    assert r.status_code == 200
    body = r.json()
    assert body["exchange_rate"] == 6.73
    # realtime_cached → UI 必须显示「参考汇率」而非「实时汇率」
    assert body["exchange_rate_source"] == "realtime_cached"
    assert body["exchange_rate_updated_at"] is not None
    # credits 字段齐备
    assert body["credits_per_cny"] == 100
    assert body["presets_cny"] == [10, 20, 50, 100]
    assert body["limits"]["min_cny"] == 1
    assert "max_cny" in body["limits"]

    # 清缓存 → 实时拉取（realtime_fresh 或网络失败 fallback_fixed，两者都合法但类型必须准确）
    await redis.delete("exchange_rate_usd_cny", "exchange_rate_usd_cny_at")
    r = await client.get("/api/pay/packages")
    src = r.json()["exchange_rate_source"]
    assert src in ("realtime_fresh", "fallback_fixed")
