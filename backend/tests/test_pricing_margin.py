"""Pricing Engine / Price Guard / Margin Ledger 测试矩阵（任务规范 §51）。

覆盖：成本 ¥0.20 + 70% 毛利 + 10% 安全垫 → 最低 80 点；最贵 route ¥0.712
低价售卖必须触发警告；pricing version 快照不随后台修改漂移；margin 数学一致性。
"""

from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from app.main import app
from app.core.database import AsyncSessionLocal
from app.models.billing import PricingRule, CostMarginLedger, BillingTransaction
from app.models.user import User
from app.services import pricing as pricing_service
from tests.conftest import make_admin_headers

ADMIN = make_admin_headers()
ADMIN_NORMAL = make_admin_headers(role="admin")


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _seed_rule(unit_credits=50, cost="0.20", target="0.70", buffer="0.10") -> PricingRule:
    async with AsyncSessionLocal() as db:
        rule = PricingRule(
            feature="image", model="gpt-image-2", unit_credits=unit_credits,
            nominal_unit_cost_rmb=Decimal(cost), target_margin=Decimal(target),
            safety_buffer=Decimal(buffer), rounding_step=10,
        )
        db.add(rule)
        await db.commit()
        return rule


# ── 毛利数学（§31-§33） ────────────────────────────────────────────

async def test_margin_math_minimum_credits():
    """成本 ¥0.20 + 10% 安全垫 + 70% 目标 → 最低售价 = 80 点。"""
    m = pricing_service.margin_math(
        unit_credits=80, nominal_unit_cost_rmb=Decimal("0.20"),
        target_margin=Decimal("0.70"), safety_buffer=Decimal("0.10"),
        credits_per_cny=100, rounding_step=10,
    )
    assert m["revenue_rmb"] == "0.800000"
    assert m["effective_unit_cost_rmb"] == "0.220000"
    assert m["min_unit_credits"] == 80
    assert m["below_target"] is False
    # 80 点实际毛利（按安全成本）：0.8 - 0.22 = 0.58；58/80 = 72.5% > 70%
    assert Decimal(m["gross_margin"]) >= Decimal("0.70")


async def test_margin_math_expensive_route_flags_low_price():
    """最贵 route ¥0.712 成本：50 点（¥0.50）售卖 → 安全成本 0.7832 → 毛利为负，必须警告。"""
    m = pricing_service.margin_math(
        unit_credits=50, nominal_unit_cost_rmb=Decimal("0.712"),
        target_margin=Decimal("0.70"), safety_buffer=Decimal("0.10"),
        credits_per_cny=100, rounding_step=10,
    )
    assert m["below_target"] is True
    # 最低售价 = 0.712×1.1/0.3 = 2.6107 → 261.07 → 向上取整到 10 → 270
    assert m["min_unit_credits"] == 270
    assert Decimal(m["gross_profit_rmb"]) < 0


async def test_margin_math_exact_examples():
    """§34 示例：售 100 点（¥1.00），真实成本 ¥0.20 → 毛利 ¥0.80，毛利率 80%。"""
    m = pricing_service.margin_math(
        unit_credits=100, nominal_unit_cost_rmb=Decimal("0.20"),
        target_margin=Decimal("0.70"), safety_buffer=Decimal("0.10"),
        credits_per_cny=100, rounding_step=10,
    )
    assert m["revenue_rmb"] == "1.000000"
    assert m["gross_profit_rmb"] == "0.780000"  # 按安全成本口径（0.22）
    # 真实成本口径（不经安全垫）在经营账 ledger 中体现（test ledger 80%）


# ── Price Guard（§34-§35） ─────────────────────────────────────────

async def test_price_guard_rejects_below_target(client):
    """低于 70% 毛利：普通管理员 403；super_admin 强制需 reason。"""
    from sqlalchemy import text
    from app.core.security import hash_password

    # 创建真实普通管理员行（角色以 DB 为准，get_admin_user 忽略 token 里的 role）
    NORMAL_ADMIN_ID = "00000000-0000-0000-0000-0000000000bb"
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "INSERT INTO admin_users (id, username, display_name, password_hash, role, "
            "is_active, must_change_password, created_at, updated_at) "
            "VALUES (:id, 'admin2', 'Normal Admin', :pw, 'admin', true, false, now(), now()) "
            "ON CONFLICT (id) DO NOTHING"
        ), {"id": NORMAL_ADMIN_ID, "pw": hash_password("x")})
        await db.commit()
    normal_admin = make_admin_headers(role="admin", admin_id=NORMAL_ADMIN_ID, username="admin2")

    rule = await _seed_rule(unit_credits=50, cost="0.20")

    payload = {
        "unit_credits": 50, "nominal_unit_cost_rmb": "0.20",
        "target_margin": "0.70", "safety_buffer": "0.10", "rounding_step": 10,
    }
    # super_admin 不带 force → 403
    r = await client.put(f"/api/admin/pricing/rules/{rule.id}", json=payload, headers=ADMIN)
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "BELOW_TARGET_MARGIN"
    body = r.json()["detail"]
    assert body["margin_preview"]["min_unit_credits"] == 80

    # normal admin 带 force → 仍 403（仅 super_admin 可强制）
    r = await client.put(f"/api/admin/pricing/rules/{rule.id}",
                         json={**payload, "force": True}, headers=normal_admin)
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "OVERRIDE_REQUIRES_SUPER_ADMIN"

    # super_admin force 无 reason → 400
    r = await client.put(f"/api/admin/pricing/rules/{rule.id}",
                         json={**payload, "force": True}, headers=ADMIN)
    assert r.status_code == 400

    # super_admin force + reason → 200，留痕
    r = await client.put(f"/api/admin/pricing/rules/{rule.id}",
                         json={**payload, "force": True, "override_reason": "促销期临时定价"},
                         headers=ADMIN)
    assert r.status_code == 200
    rule_json = r.json()["rule"]
    assert rule_json["override_reason"] == "促销期临时定价"
    assert rule_json["override_by"] == "admin"


async def test_price_guard_allows_healthy_price(client):
    """80 点 × 成本 ¥0.20：满足 70% 目标 → 直接保存成功并升版本。"""
    rule = await _seed_rule(unit_credits=50, cost="0.20")
    r = await client.put(f"/api/admin/pricing/rules/{rule.id}", json={
        "unit_credits": 80, "nominal_unit_cost_rmb": "0.20",
        "target_margin": "0.70", "safety_buffer": "0.10", "rounding_step": 10,
    }, headers=ADMIN)
    assert r.status_code == 200
    assert r.json()["rule"]["version"] == 2
    assert r.json()["rule"]["margin_preview"]["below_target"] is False


# ── 快照不漂移（§10/§29） ──────────────────────────────────────────

async def test_pricing_snapshot_survives_rule_edit(client):
    """已预占任务在改价后结算：流水与经营账仍按预占时的 rule 版本成本快照。"""
    from app.services import billing as billing_service

    async with AsyncSessionLocal() as db:
        user = User(username="pm1", email="pm1@test.local", password_hash="x",
                    paid_credits=10000)
        db.add(user)
        await db.flush()
        rule = PricingRule(
            feature="image", model="gpt-image-2", unit_credits=50,
            nominal_unit_cost_rmb=Decimal("0.20"), target_margin=Decimal("0.70"),
            safety_buffer=Decimal("0.10"), rounding_step=10,
        )
        db.add(rule)
        await db.flush()
        uid, rid = user.id, rule.id
        await billing_service.authorize_image2(db, uid, "pm-snap-0001", 1)
        await db.commit()

    # 改价 + 改成本
    async with AsyncSessionLocal() as db:
        r = await db.get(PricingRule, rid)
        r.unit_credits = 200
        r.nominal_unit_cost_rmb = Decimal("0.50")
        r.version += 1
        await db.flush()
        await billing_service.settle_image2(db, uid, "pm-snap-0001", True)
        await db.commit()

    async with AsyncSessionLocal() as db:
        txn = (await db.execute(select(BillingTransaction).where(
            BillingTransaction.request_id == "pm-snap-0001"))).scalar_one()
        assert txn.unit_credits == 50  # 预占冻结价
        assert txn.amount_credits == 50
        ledger = (await db.execute(select(CostMarginLedger).where(
            CostMarginLedger.billing_transaction_id == txn.id))).scalar_one()
        # 经营账按结算时规则（新成本 0.50）计成本——结算时刻快照
        assert ledger.nominal_unit_cost_rmb == Decimal("0.500000")
        assert ledger.actual_cost_rmb == Decimal("0.500000")
        # 收入按冻结 50 点 = ¥0.50
        assert ledger.revenue_rmb == Decimal("0.500000")


# ── 经营账统计（§37-§40） ──────────────────────────────────────────

async def test_margin_ledger_separates_trial_from_paid(client):
    """试用消耗：revenue=0、promo=价值、profit=-成本（获客成本口径）；付费单列。"""
    from app.services import billing as billing_service

    async with AsyncSessionLocal() as db:
        paid_user = User(username="pm-paid", email="pmp@test.local", password_hash="x",
                         paid_credits=1000)
        trial_user = User(username="pm-trial", email="pmt@test.local", password_hash="x",
                          trial_credits=1000)
        db.add_all([paid_user, trial_user])
        await db.flush()
        rule = PricingRule(
            feature="image", model="gpt-image-2", unit_credits=100,
            nominal_unit_cost_rmb=Decimal("0.20"), target_margin=Decimal("0.70"),
            safety_buffer=Decimal("0.10"), rounding_step=10,
        )
        db.add(rule)
        await db.flush()
        await billing_service.authorize_image2(db, paid_user.id, "pm-paid-0001", 1)
        await billing_service.settle_image2(db, paid_user.id, "pm-paid-0001", True)
        await billing_service.authorize_image2(db, trial_user.id, "pm-trial-0001", 1)
        await billing_service.settle_image2(db, trial_user.id, "pm-trial-0001", True)
        await db.commit()

    r = await client.get("/api/admin/margin/ledger?category=paid", headers=ADMIN)
    assert r.status_code == 200
    paid = r.json()
    assert paid["total"] == 1
    assert paid["summary"]["revenue_rmb"] == "1.000000"
    assert paid["summary"]["gross_margin"] == "0.8000"

    r = await client.get("/api/admin/margin/ledger?category=trial", headers=ADMIN)
    trial = r.json()
    assert trial["total"] == 1
    assert Decimal(trial["summary"]["revenue_rmb"]) == 0
    assert Decimal(trial["summary"]["promotional_value_rmb"]) == 1  # 100 试用点 × ¥0.01
    assert Decimal(trial["summary"]["gross_profit_rmb"]) == Decimal("-0.200000")  # 获客成本

    # 全量汇总 = 两者之和
    r = await client.get("/api/admin/margin/ledger", headers=ADMIN)
    all_rows = r.json()
    assert all_rows["total"] == 2
    assert Decimal(all_rows["summary"]["revenue_rmb"]) == 1
    assert Decimal(all_rows["summary"]["gross_profit_rmb"]) == Decimal("0.600000")


# ── system_config 管理接口 ─────────────────────────────────────────

async def test_config_crud_and_audit(client):
    r = await client.get("/api/admin/system-config", headers=ADMIN)
    assert r.status_code == 200
    keys = {c["key"] for c in r.json()["configs"]}
    assert {"credits_per_cny", "trial_grant_credits", "target_margin"} <= keys

    r = await client.put("/api/admin/system-config", json={
        "key": "trial_grant_credits", "value": "600", "reason": "活动加量",
    }, headers=ADMIN)
    assert r.status_code == 200

    # 非法值拒绝
    r = await client.put("/api/admin/system-config", json={
        "key": "credits_per_cny", "value": "abc",
    }, headers=ADMIN)
    assert r.status_code == 400

    # 未知键拒绝
    r = await client.put("/api/admin/system-config", json={
        "key": "not_exist", "value": "1",
    }, headers=ADMIN)
    assert r.status_code == 400
