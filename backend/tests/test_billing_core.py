"""核心计费测试（spec Test 1-9）：Decimal 精确扣款、试用优先、组合额度、
并发原子性、幂等、上游失败退款、价格快照。"""

import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from app.core.database import AsyncSessionLocal
from app.models.billing import BillingTransaction
from app.models.token import UsageLog
from app.services import billing
from tests.conftest import make_user, get_user


def money(v) -> Decimal:
    return Decimal(str(v))


@pytest.mark.parametrize("balance,trial", [("1.00", "0")])
async def test_1_cash_deduct_exact(balance, trial):
    """Test 1：现金余额正常扣款，$1.00 - $0.07 = $0.93，无浮点误差。"""
    user = await make_user("t1", balance, trial)
    async with AsyncSessionLocal() as db:
        txn, u = await billing.authorize_image2(db, user.id, "req-t1-0001", 1)
        txn, u = await billing.settle_image2(db, user.id, "req-t1-0001", True)
        await db.commit()

    row = await get_user(user.id)
    assert row.balance_usd == Decimal("0.930000")
    assert txn.status == "SUCCESS"
    assert str(txn.amount_usd) == "0.070000"


async def test_2_trial_deduct_then_exhausted():
    """Test 2：试用额度 0.14 可用 2 次，第 3 次 QUOTA_EXHAUSTED。"""
    user = await make_user("t2", "0", "0.14")
    for i in (1, 2):
        async with AsyncSessionLocal() as db:
            await billing.authorize_image2(db, user.id, f"req-t2-{i:04d}", 1)
            await billing.settle_image2(db, user.id, f"req-t2-{i:04d}", True)
            await db.commit()

    row = await get_user(user.id)
    assert row.trial_credit_usd == Decimal("0")
    assert row.balance_usd == Decimal("0")

    async with AsyncSessionLocal() as db:
        with pytest.raises(billing.QuotaExhaustedError):
            await billing.authorize_image2(db, user.id, "req-t2-0003", 1)


async def test_3_mixed_quota():
    """Test 3：组合额度 trial 0.03 + cash 0.04 恰好覆盖一次调用。"""
    user = await make_user("t3", "0.04", "0.03")
    async with AsyncSessionLocal() as db:
        txn, u = await billing.authorize_image2(db, user.id, "req-t3-0001", 1)
        assert txn.billing_source == "MIXED"
        assert money(txn.trial_amount) == Decimal("0.03")
        assert money(txn.balance_amount) == Decimal("0.04")
        await billing.settle_image2(db, user.id, "req-t3-0001", True)
        await db.commit()

    row = await get_user(user.id)
    assert row.trial_credit_usd == Decimal("0")
    assert row.balance_usd == Decimal("0")

    async with AsyncSessionLocal() as db:
        with pytest.raises(billing.QuotaExhaustedError):
            await billing.authorize_image2(db, user.id, "req-t3-0002", 1)


async def test_4_zero_quota_blocks_before_any_charge():
    """Test 4：完全没额度 → authorize 直接拒绝（上游调用前的门禁），不产生任何计费记录。"""
    user = await make_user("t4", "0", "0")
    async with AsyncSessionLocal() as db:
        with pytest.raises(billing.QuotaExhaustedError):
            await billing.authorize_image2(db, user.id, "req-t4-0001", 1)

    async with AsyncSessionLocal() as db:
        count = (await db.execute(
            select(BillingTransaction).where(BillingTransaction.user_id == user.id)
        )).scalars().all()
        usage = (await db.execute(
            select(UsageLog).where(UsageLog.user_id == user.id)
        )).scalars().all()
    assert count == [] and usage == []


async def test_5_total_below_price_rejected():
    """Test 5：trial 0.02 + cash 0.04 = 0.06 < 0.07 → 拒绝。"""
    user = await make_user("t5", "0.04", "0.02")
    async with AsyncSessionLocal() as db:
        with pytest.raises(billing.QuotaExhaustedError):
            await billing.authorize_image2(db, user.id, "req-t5-0001", 1)
    row = await get_user(user.id)
    assert row.balance_usd == Decimal("0.040000")
    assert row.trial_credit_usd == Decimal("0.020000")


async def test_6_concurrency_no_overspend():
    """Test 6：balance=0.07，并发两个 $0.07 authorize —— 只能成功一个，最终余额 0，不得为负。"""
    user = await make_user("t6", "0.07", "0")

    async def attempt(req_id: str):
        async with AsyncSessionLocal() as db:
            try:
                await billing.authorize_image2(db, user.id, req_id, 1)
                await db.commit()
                return "ok"
            except billing.QuotaExhaustedError:
                await db.rollback()
                return "exhausted"

    results = await asyncio.gather(attempt("req-t6-aaaa"), attempt("req-t6-bbbb"))
    assert sorted(results) == ["exhausted", "ok"], results

    row = await get_user(user.id)
    assert row.balance_usd == Decimal("0.000000")


async def test_7_upstream_failure_refund():
    """Test 7：上游失败 → settle(false) 全额退回，余额不减少。"""
    user = await make_user("t7", "1.00", "0")
    async with AsyncSessionLocal() as db:
        await billing.authorize_image2(db, user.id, "req-t7-0001", 1)
        txn, _ = await billing.settle_image2(db, user.id, "req-t7-0001", False, "upstream error")
        await db.commit()
    assert txn.status == "FAILED"

    row = await get_user(user.id)
    assert row.balance_usd == Decimal("1.000000")


async def test_8_duplicate_requests_idempotent():
    """Test 8：相同 request_id 重复 authorize / 重复 settle 均不重复扣款。"""
    user = await make_user("t8", "1.00", "0")
    async with AsyncSessionLocal() as db:
        t1, _ = await billing.authorize_image2(db, user.id, "req-t8-0001", 1)
        t2, _ = await billing.authorize_image2(db, user.id, "req-t8-0001", 1)
        assert t1.id == t2.id
        await db.commit()

    row = await get_user(user.id)
    assert row.balance_usd == Decimal("0.930000")

    async with AsyncSessionLocal() as db:
        s1, _ = await billing.settle_image2(db, user.id, "req-t8-0001", True)
        await db.commit()
        s2, _ = await billing.settle_image2(db, user.id, "req-t8-0001", True)
        await db.commit()
        assert s1.status == s2.status == "SUCCESS"

    row = await get_user(user.id)
    assert row.balance_usd == Decimal("0.930000")  # 只扣一次


async def test_8b_usage_log_single_row():
    user = await make_user("t8b", "1.00", "0")
    async with AsyncSessionLocal() as db:
        await billing.authorize_image2(db, user.id, "req-t8b-0001", 1)
        await billing.settle_image2(db, user.id, "req-t8b-0001", True)
        await db.commit()
    async with AsyncSessionLocal() as db:
        logs = (await db.execute(
            select(UsageLog).where(UsageLog.user_id == user.id)
        )).scalars().all()
    assert len(logs) == 1
    assert str(logs[0].cost_usd) == "0.070000"
    assert str(logs[0].unit_price) == "0.070000"


async def test_9_price_snapshot():
    """Test 9：改价不影响历史订单；新订单按新价。"""
    user = await make_user("t9", "10.00", "0")
    async with AsyncSessionLocal() as db:
        txn1, _ = await billing.authorize_image2(db, user.id, "req-t9-0001", 1)
        await billing.settle_image2(db, user.id, "req-t9-0001", True)
        await db.commit()
    assert str(txn1.amount_usd) == "0.070000"

    # 管理员改价 0.07 -> 0.09
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "UPDATE ai_models SET price_per_call = 0.090000 WHERE name = 'gpt-image-2'"
        ))
        await db.commit()

    async with AsyncSessionLocal() as db:
        txn2, _ = await billing.authorize_image2(db, user.id, "req-t9-0002", 1)
        await billing.settle_image2(db, user.id, "req-t9-0002", True)
        await db.commit()
    assert str(txn2.amount_usd) == "0.090000"
    assert str(txn1.amount_usd) == "0.070000"  # 旧订单不变


async def test_9b_partial_settle_refund_difference():
    """授权 2 张、实际成功 1 张 → 只收 1 张钱，差额退回（按试用优先顺序核算）。"""
    user = await make_user("t9b", "0.04", "0.10")
    async with AsyncSessionLocal() as db:
        txn, _ = await billing.authorize_image2(db, user.id, "req-t9b-0001", 2)
        assert str(txn.amount_usd) == "0.140000"
        txn, _ = await billing.settle_image2(db, user.id, "req-t9b-0001", True, final_image_count=1)
        await db.commit()
    assert str(txn.amount_usd) == "0.070000"

    row = await get_user(user.id)
    # 消耗：试用 0.07（授权扣了 0.10 试用 + 0.04 现金；结算 1 张按试用优先 → 实耗 trial 0.07）
    assert row.trial_credit_usd == Decimal("0.030000")
    assert row.balance_usd == Decimal("0.040000")


async def test_10_trial_frozen_when_disabled():
    """trial_allowed 关闭时试用额度冻结，仅可用现金。"""
    user = await make_user("t10", "0.10", "0.50")
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "UPDATE ai_models SET trial_allowed = false WHERE name = 'gpt-image-2'"
        ))
        await db.commit()
        txn, _ = await billing.authorize_image2(db, user.id, "req-t10-0001", 1)
        assert txn.billing_source == "PAID"
        await billing.settle_image2(db, user.id, "req-t10-0001", True)
        await db.commit()

    row = await get_user(user.id)
    assert row.balance_usd == Decimal("0.030000")
    assert row.trial_credit_usd == Decimal("0.500000")


async def test_11_stale_reservation_auto_release():
    """预占超时 → GC 全额释放（客户端崩溃兜底）。"""
    user = await make_user("t11", "0.07", "0")
    async with AsyncSessionLocal() as db:
        await billing.authorize_image2(db, user.id, "req-t11-0001", 1)
        await db.commit()
        # 伪造为 3 小时前的预占
        await db.execute(text(
            "UPDATE billing_transactions SET created_at = now() - interval '3 hours' "
            "WHERE request_id = 'req-t11-0001'"
        ))
        await db.commit()

    from app.main import billing as _  # noqa: F401  (确保模块加载)
    async with AsyncSessionLocal() as db:
        released = await billing.release_stale_reservations(db, ttl_hours=2)
    assert released == 1
    row = await get_user(user.id)
    assert row.balance_usd == Decimal("0.070000")
