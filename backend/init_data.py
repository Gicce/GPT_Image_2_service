"""
Run once after first deploy to seed default AI models.
Usage: python backend/init_data.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from backend.app.core.database import engine, Base
from backend.app.models.content import AIModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select


DEFAULT_MODELS = [
    {
        "name": "gpt-image-2",
        "display_name": "GPT Image 2",
        "model_type": "image",
        "is_enabled": True,
        "trial_allowed": True,
        "price_per_image": 0.04,
        "price_input_per_m": 0.0,
        "price_output_per_m": 0.0,
        "price_cached_per_m": 0.0,
        "sort_order": 1,
    },
    {
        "name": "gpt-4.5",
        "display_name": "GPT-4.5",
        "model_type": "chat",
        "is_enabled": True,
        "trial_allowed": False,
        "price_per_image": 0.0,
        "price_input_per_m": 1.0,
        "price_output_per_m": 6.0,
        "price_cached_per_m": 0.1,
        "sort_order": 2,
    },
]


async def seed():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSession(engine) as session:
        for m in DEFAULT_MODELS:
            existing = await session.execute(
                select(AIModel).where(AIModel.name == m["name"])
            )
            if existing.scalar_one_or_none() is None:
                session.add(AIModel(**m))
                print(f"  + {m['name']}")
            else:
                print(f"  ~ {m['name']} already exists, skipping")
        await session.commit()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(seed())
