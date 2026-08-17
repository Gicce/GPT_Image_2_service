"""
Safe seed script: creates missing tables, runs V4 startup migrations, seeds Image2.
Does NOT drop or destroy any existing data.
Usage: cd backend && python init_data.py
"""
import asyncio

from app.core.database import engine, Base, AsyncSession
from app.models.content import AIModel, Notice
from app.models.user import User
from app.models.token import TokenInventory, Order, UsageLog
from app.models.billing import BillingTransaction
from app.models.audit import AdminAuditLog
from sqlalchemy import select

from main import seed_defaults, _ensure_columns, _ensure_indexes, _migrate_v4_single_model


async def seed():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_columns(conn)
        await _ensure_indexes(conn)
        await _migrate_v4_single_model(conn)
    print("Tables & migrations ensured.")

    await seed_defaults()
    async with AsyncSession(engine) as session:
        result = await session.execute(select(AIModel))
        for m in result.scalars().all():
            print(f"  model: {m.name} (enabled={m.is_enabled}, price={m.price_per_call})")

    print("Done.")


if __name__ == "__main__":
    asyncio.run(seed())
