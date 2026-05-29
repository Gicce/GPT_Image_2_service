"""
Run once after first deploy to seed default groups and AI models.
Usage: python backend/init_data.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import Base, engine
from backend.app.models.content import AIModel, Group


DEFAULT_GROUPS = [
    {"name": "image", "description": "Image generation credits", "sort_order": 1},
    {"name": "agent", "description": "Agent chat credits", "sort_order": 2},
    {"name": "postprocess", "description": "Image postprocess credits", "sort_order": 3},
]

DEFAULT_MODELS = [
    {
        "name": "gpt-image-2",
        "display_name": "GPT Image 2",
        "provider": "OpenAI",
        "billing_type": "per_call",
        "model_type": "image",
        "group": "image",
        "is_enabled": True,
        "trial_allowed": True,
        "price_per_call": "0.04",
        "price_per_image": "0.04",
        "sort_order": 1,
        "supports_vision": True,
    },
    {
        "name": "gpt-4.5",
        "display_name": "GPT-4.5",
        "provider": "OpenAI",
        "billing_type": "per_token",
        "model_type": "chat",
        "group": "agent",
        "is_enabled": True,
        "trial_allowed": False,
        "price_input": "1.0",
        "price_output": "6.0",
        "price_cached": "0.1",
        "price_input_per_m": "1.0",
        "price_output_per_m": "6.0",
        "price_cached_per_m": "0.1",
        "sort_order": 2,
        "context_window": 32768,
        "supports_tools": True,
        "supports_vision": True,
    },
    {
        "name": "gpt-4o",
        "display_name": "GPT-4o",
        "provider": "OpenAI",
        "billing_type": "per_token",
        "model_type": "chat",
        "group": "agent",
        "is_enabled": True,
        "trial_allowed": False,
        "price_input": "2.5",
        "price_output": "10.0",
        "price_cached": "0.25",
        "price_input_per_m": "2.5",
        "price_output_per_m": "10.0",
        "price_cached_per_m": "0.25",
        "sort_order": 3,
        "context_window": 128000,
        "supports_tools": True,
        "supports_vision": True,
    },
    {
        "name": "remove.bg",
        "display_name": "remove.bg",
        "provider": "remove.bg",
        "billing_type": "per_call",
        "model_type": "postprocess",
        "group": "postprocess",
        "is_enabled": True,
        "trial_allowed": False,
        "price_per_call": "0.03",
        "sort_order": 4,
    },
]


async def seed():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSession(engine) as session:
        for group_data in DEFAULT_GROUPS:
            existing = await session.execute(select(Group).where(Group.name == group_data["name"]))
            if existing.scalar_one_or_none() is None:
                session.add(Group(**group_data))
                print(f"  + group {group_data['name']}")

        for model_data in DEFAULT_MODELS:
            existing = await session.execute(select(AIModel).where(AIModel.name == model_data["name"]))
            row = existing.scalar_one_or_none()
            if row is None:
                session.add(AIModel(**model_data))
                print(f"  + model {model_data['name']}")
            else:
                for key, value in model_data.items():
                    if getattr(row, key, None) in (None, ""):
                        setattr(row, key, value)
                print(f"  ~ model {model_data['name']} already exists")
        await session.commit()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(seed())
