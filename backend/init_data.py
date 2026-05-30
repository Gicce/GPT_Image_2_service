"""
Safe seed script: creates missing tables and inserts default groups/models.
Does NOT drop or destroy any existing data.
Usage: cd backend && python init_data.py
"""
import asyncio

from app.core.database import engine, Base
from app.models.content import AIModel, Notice, Prompt, Group
from app.models.user import User, UserToken
from app.models.token import TokenInventory, Order, UsageLog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text


DEFAULT_GROUPS = [
    {"name": "image", "description": "图片生成组", "sort_order": 1},
    {"name": "agent", "description": "Agent 对话组", "sort_order": 2},
    {"name": "postprocess", "description": "后处理工具组", "sort_order": 3},
]

DEFAULT_MODELS = [
    {"name": "gpt-image-2", "display_name": "GPT Image 2", "provider": "OpenAI",
     "billing_type": "per_call", "model_type": "image", "group": "image",
     "is_enabled": True, "trial_allowed": True, "price_per_call": "0.046",
     "context_window": 0, "supports_tools": False, "supports_vision": False, "sort_order": 1},
    {"name": "qwen3.5-flash", "display_name": "Qwen 3.5 Flash", "provider": "Alibaba",
     "billing_type": "per_token", "model_type": "agent", "group": "agent",
     "is_enabled": True, "trial_allowed": False,
     "price_input": "0.000115", "price_output": "0.001150", "price_cached": "0.0000115",
     "context_window": 131072, "supports_tools": True, "supports_vision": True, "sort_order": 10},
    {"name": "qwen3.5-plus", "display_name": "Qwen 3.5 Plus", "provider": "Alibaba",
     "billing_type": "per_token", "model_type": "agent", "group": "agent",
     "is_enabled": True, "trial_allowed": False,
     "price_input": "0.00046", "price_output": "0.00276", "price_cached": "0.000046",
     "context_window": 131072, "supports_tools": True, "supports_vision": True, "sort_order": 11},
    {"name": "qwen3.6-plus", "display_name": "Qwen 3.6 Plus", "provider": "Alibaba",
     "billing_type": "per_token", "model_type": "agent", "group": "agent",
     "is_enabled": True, "trial_allowed": False,
     "price_input": "0.00115", "price_output": "0.0069", "price_cached": "0.000115",
     "context_window": 131072, "supports_tools": True, "supports_vision": True, "sort_order": 12},
    {"name": "qwen-max", "display_name": "Qwen Max", "provider": "Alibaba",
     "billing_type": "per_token", "model_type": "agent", "group": "agent",
     "is_enabled": True, "trial_allowed": False,
     "price_input": "0.001438", "price_output": "0.00575", "price_cached": "0.000288",
     "context_window": 32768, "supports_tools": True, "supports_vision": False, "sort_order": 13},
    {"name": "deepseek-v4-flash", "display_name": "DeepSeek V4 Flash", "provider": "DeepSeek",
     "billing_type": "per_token", "model_type": "agent", "group": "agent",
     "is_enabled": True, "trial_allowed": False,
     "price_input": "0.000575", "price_output": "0.00115", "price_cached": "0.0000115",
     "context_window": 131072, "supports_tools": True, "supports_vision": False, "sort_order": 20},
    {"name": "deepseek-v4-pro", "display_name": "DeepSeek V4 Pro", "provider": "DeepSeek",
     "billing_type": "per_token", "model_type": "agent", "group": "agent",
     "is_enabled": True, "trial_allowed": False,
     "price_input": "0.0069", "price_output": "0.0138", "price_cached": "0.0000575",
     "context_window": 131072, "supports_tools": True, "supports_vision": False, "sort_order": 21},
    {"name": "glm-5", "display_name": "GLM-5", "provider": "Zhipu",
     "billing_type": "per_token", "model_type": "agent", "group": "agent",
     "is_enabled": True, "trial_allowed": False,
     "price_input": "0.0023", "price_output": "0.01035", "price_cached": "0.00046",
     "context_window": 131072, "supports_tools": True, "supports_vision": True, "sort_order": 30},
    {"name": "kimi-k2.5", "display_name": "Kimi K2.5", "provider": "Moonshot",
     "billing_type": "per_token", "model_type": "agent", "group": "agent",
     "is_enabled": True, "trial_allowed": False,
     "price_input": "0.0023", "price_output": "0.012075", "price_cached": "0.0004025",
     "context_window": 131072, "supports_tools": True, "supports_vision": False, "sort_order": 31},
    {"name": "gpt-5.4-mini", "display_name": "GPT-5.4 Mini", "provider": "OpenAI",
     "billing_type": "per_token", "model_type": "agent", "group": "agent",
     "is_enabled": True, "trial_allowed": False,
     "price_input": "0.000431", "price_output": "0.002588", "price_cached": "0.0000431",
     "context_window": 131072, "supports_tools": True, "supports_vision": False, "sort_order": 40},
    {"name": "gpt-5.4", "display_name": "GPT-5.4", "provider": "OpenAI",
     "billing_type": "per_token", "model_type": "agent", "group": "agent",
     "is_enabled": True, "trial_allowed": False,
     "price_input": "0.001438", "price_output": "0.008625", "price_cached": "0.0001438",
     "context_window": 131072, "supports_tools": True, "supports_vision": False, "sort_order": 41},
    {"name": "claude-sonnet-4-6", "display_name": "Claude Sonnet 4.6", "provider": "Anthropic",
     "billing_type": "per_token", "model_type": "agent", "group": "agent",
     "is_enabled": True, "trial_allowed": False,
     "price_input": "0.001725", "price_output": "0.008625", "price_cached": "0.0001725",
     "context_window": 200000, "supports_tools": True, "supports_vision": True, "sort_order": 50},
    {"name": "remove_bg", "display_name": "Remove Background", "provider": "Internal",
     "billing_type": "per_call", "model_type": "postprocess", "group": "postprocess",
     "is_enabled": True, "trial_allowed": False, "price_per_call": "0.010",
     "context_window": 0, "supports_tools": False, "supports_vision": False, "sort_order": 100},
]


async def _ensure_columns(conn):
    """Add new columns to existing tables if they don't exist (PostgreSQL)."""
    new_columns = [
        ("ai_models", "context_window", "INTEGER DEFAULT 32768"),
        ("ai_models", "supports_tools", "BOOLEAN DEFAULT FALSE"),
        ("ai_models", "supports_vision", "BOOLEAN DEFAULT FALSE"),
    ]
    for table, column, col_type in new_columns:
        result = await conn.execute(text(
            f"SELECT 1 FROM information_schema.columns "
            f"WHERE table_name='{table}' AND column_name='{column}'"
        ))
        if not result.scalar():
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
            print(f"  + column: {table}.{column}")


async def seed():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_columns(conn)
    print("Tables ensured.")

    async with AsyncSession(engine) as session:
        for g in DEFAULT_GROUPS:
            result = await session.execute(select(Group).where(Group.name == g["name"]))
            if not result.scalar_one_or_none():
                session.add(Group(**g))
                print(f"  + group: {g['name']}")
            else:
                print(f"  = group: {g['name']} (exists)")

        for m in DEFAULT_MODELS:
            result = await session.execute(
                select(AIModel).where(AIModel.name == m["name"], AIModel.group == m["group"])
            )
            if not result.scalar_one_or_none():
                session.add(AIModel(**m))
                print(f"  + model: {m['name']} ({m['group']})")
            else:
                print(f"  = model: {m['name']} ({m['group']}) (exists)")

        await session.commit()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(seed())