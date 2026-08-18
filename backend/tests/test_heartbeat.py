"""客户端心跳（/api/client/heartbeat）与在线设备判定测试。"""

import asyncio
import json

import httpx
import pytest
from sqlalchemy import select, text

from app.main import app
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, hash_password
from app.core.redis import get_redis
from app.models.user import User
from tests.conftest import make_user, make_admin_headers


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _user_headers(user_id: str) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


async def test_heartbeat_requires_authenticated_user(client):
    r = await client.post("/api/client/heartbeat", json={"device_id": "d1"})
    assert r.status_code == 401

    # 普通用户 token 不能访问管理员在线设备接口
    user = await make_user("hb-admin-check")
    r = await client.get("/api/admin/online-devices", headers=await _user_headers(user.id))
    assert r.status_code == 403


async def test_heartbeat_updates_last_seen(client):
    user = await make_user("hb-user1")
    r = await client.post(
        "/api/client/heartbeat",
        headers=await _user_headers(user.id),
        json={"device_id": "device-abc", "device_name": "Windows PC",
              "app_version": "4.0.2", "platform": "windows"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

    devices = (await client.get("/api/admin/online-devices", headers=make_admin_headers())).json()["devices"]
    mine = [d for d in devices if d["device_id"] == "device-abc"]
    assert len(mine) == 1
    assert mine[0]["user_email"] == "hb-user1@test.local"
    assert mine[0]["last_seen"]
    assert mine[0]["status"] == "online"
    assert mine[0]["ttl_seconds"] > 0

    # 再次上报后 last_seen 更新
    first_seen = mine[0]["last_seen"]
    await asyncio.sleep(0.05)
    await client.post(
        "/api/client/heartbeat",
        headers=await _user_headers(user.id),
        json={"device_id": "device-abc"},
    )
    devices = (await client.get("/api/admin/online-devices", headers=make_admin_headers())).json()["devices"]
    mine = [d for d in devices if d["device_id"] == "device-abc"][0]
    assert mine["last_seen"] >= first_seen


async def test_online_status_uses_last_heartbeat(client):
    """在线判定基于 Redis TTL：key 过期（180s 无心跳）设备即从列表消失。"""
    user = await make_user("hb-user2")
    r = await client.post(
        "/api/client/heartbeat", headers=await _user_headers(user.id),
        json={"device_id": "device-ttl"},
    )
    assert r.status_code == 200

    redis = get_redis()
    # 模拟心跳停止：将 TTL 缩短到 1 秒并等待过期
    await redis.expire(f"online_device:{user.id}:device-ttl", 1)
    await asyncio.sleep(1.2)

    devices = (await client.get("/api/admin/online-devices", headers=make_admin_headers())).json()["devices"]
    assert all(d["device_id"] != "device-ttl" for d in devices)


async def test_spoofed_user_cannot_report_for_other_user(client):
    """user_id 一律取自 JWT，心跳 body 伪造的 user_id 无效。"""
    attacker = await make_user("hb-attacker")
    victim = await make_user("hb-victim")

    r = await client.post(
        "/api/client/heartbeat",
        headers=await _user_headers(attacker.id),
        json={"device_id": "device-spoof", "user_id": victim.id},
    )
    assert r.status_code == 200

    devices = (await client.get("/api/admin/online-devices", headers=make_admin_headers())).json()["devices"]
    spoof = [d for d in devices if d["device_id"] == "device-spoof"]
    assert len(spoof) == 1
    assert spoof[0]["user_email"] == "hb-attacker@test.local"
    assert spoof[0]["user_id"] == attacker.id


async def test_heartbeat_rejects_missing_device_id(client):
    user = await make_user("hb-user3")
    r = await client.post("/api/client/heartbeat", headers=await _user_headers(user.id), json={})
    assert r.status_code == 400
