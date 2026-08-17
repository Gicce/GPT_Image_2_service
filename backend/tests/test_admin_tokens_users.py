"""统一 Token 池统计（Test 11）与客户账户统一余额（Test 12 相关）。"""

import uuid
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import text

from app.main import app
from app.core.database import AsyncSessionLocal
from app.core.security import create_admin_token
from tests.conftest import make_user

ADMIN_HEADERS = {"Authorization": f"Bearer {create_admin_token()}"}


async def insert_token(trial=False, assigned=False, disabled=False) -> str:
    tid = str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "INSERT INTO token_inventory (id, token_value, is_trial, is_assigned, is_disabled, assigned_to, created_at) "
            "VALUES (:id, :val, :t, :a, :d, NULL, now())"
        ), {"id": tid, "val": f"sk-{tid[:12]}", "t": trial, "a": assigned, "d": disabled})
        await db.commit()
    return tid


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_token_stats_unified_pool(client):
    """Test 11：Token 统计只有 总量/可用/试用可用/已分配/禁用，无 Image2/ChatGPT 分类。"""
    await insert_token(trial=False, assigned=False)          # 可用
    await insert_token(trial=False, assigned=False)          # 可用
    await insert_token(trial=True, assigned=False)           # 试用可用
    await insert_token(trial=False, assigned=True)           # 已分配
    await insert_token(trial=False, assigned=False, disabled=True)  # 禁用

    r = await client.get("/api/admin/tokens/stats", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    stats = r.json()
    assert stats == {
        "total": 5, "available": 3, "trial_available": 1, "assigned": 1, "disabled": 1,
    }
    # 不存在 image/chatgpt 分类键
    assert "image" not in stats and "chat" not in stats and "chatgpt" not in stats


async def test_token_list_masked(client):
    """管理端 Token 列表脱敏（不返回原文）。"""
    tid = await insert_token()
    r = await client.get("/api/admin/tokens", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    tokens = r.json()["tokens"]
    target = next(t for t in tokens if t["id"] == tid)
    assert "sk-" in target["token_value"]
    assert "****" in target["token_value"]
    assert len(target["token_value"]) < 20


async def test_token_batch_import_stats(client):
    """批量录入返回完整统计：新增 / 重复 / 无效分开计数，绝不静默吞掉输入。"""
    r = await client.post("/api/admin/tokens/batch", json={
        "tokens": ["sk-test-token-1", "备注名 sk-test-token-2 ", "sk-test-token-1", "short"],
    }, headers=ADMIN_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 4
    assert body["added"] == 2        # token-1 首次 + 「备注名 sk-xxx」行提取出的 token-2
    assert body["duplicate"] == 1    # token-1 批内重复
    assert body["invalid"] == 1      # "short" 低于长度下限
    assert len(body["details"]) == 2
    for d in body["details"]:
        assert "****" in d["token"]  # 明细必须脱敏


async def test_token_batch_import_duplicate_reported(client):
    """重复录入库内已有 Token：added=0 且明确返回 duplicate 原因，而不是「成功录入 0 个」。"""
    await client.post("/api/admin/tokens/batch", json={"tokens": ["sk-test-token-1"]},
                      headers=ADMIN_HEADERS)
    r = await client.post("/api/admin/tokens/batch", json={"tokens": ["sk-test-token-1"]},
                          headers=ADMIN_HEADERS)
    body = r.json()
    assert body["added"] == 0
    assert body["duplicate"] == 1
    assert body["invalid"] == 0
    assert body["details"][0]["reason"] == "duplicate"


async def test_token_batch_import_trial_persisted(client):
    """试用开关真实落库：is_trial=True，未分配、未禁用。"""
    r = await client.post("/api/admin/tokens/batch", json={
        "tokens": ["sk-trial-token-9"], "is_trial": True,
    }, headers=ADMIN_HEADERS)
    assert r.json()["added"] == 1
    async with AsyncSessionLocal() as db:
        row = (await db.execute(text(
            "SELECT is_trial, is_assigned, is_disabled FROM token_inventory "
            "WHERE token_value = 'sk-trial-token-9'"
        ))).one()
    assert row.is_trial is True
    assert row.is_assigned is False
    assert row.is_disabled is False


async def test_users_unified_balance(client):
    """客户账户：统一 余额 + 试用额度，无 agent/image 分账。"""
    user = await make_user("a1", "3.00", "0.14")

    r = await client.get("/api/admin/users", headers=ADMIN_HEADERS)
    row = next(u for u in r.json() if u["id"] == user.id)
    assert row["balance_usd"] == "3.000000"
    assert row["trial_credit_usd"] == "0.140000"
    assert "tokens" not in row

    r = await client.get(f"/api/admin/users/{user.id}", headers=ADMIN_HEADERS)
    detail = r.json()
    assert detail["total_recharged_usd"] == "0"
    assert detail["image2_call_count"] == 0
    assert "tokens" not in detail


async def test_admin_balance_adjust(client):
    """管理员调余额：写 ADMIN_ADJUSTMENT 流水。"""
    user = await make_user("a2", "1.00", "0")
    r = await client.put(f"/api/admin/users/{user.id}/balance", json={
        "balance_usd": "5.00", "trial_credit_usd": "0.50", "remark": "test adjust",
    }, headers=ADMIN_HEADERS)
    assert r.status_code == 200

    r = await client.get(f"/api/admin/users/{user.id}", headers=ADMIN_HEADERS)
    assert r.json()["balance_usd"] == "5.000000"
    assert r.json()["trial_credit_usd"] == "0.500000"

    r = await client.get("/api/admin/billing/transactions", headers=ADMIN_HEADERS)
    txns = [t for t in r.json()["transactions"] if t["type"] == "ADMIN_ADJUSTMENT"]
    assert len(txns) == 2
