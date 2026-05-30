from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import os
import asyncio
import traceback

from app.core.database import engine, Base, AsyncSession
from app.core.redis import init_redis, start_keyspace_listener, recover_pending_refunds
from app.api.routes import auth, users, tokens, payment, notice, prompts, models, admin, usage
from app.models.content import Group, AIModel
from sqlalchemy import select, text

DEFAULT_GROUPS = [
    {"name": "image", "description": "图片生成组", "sort_order": 1},
    {"name": "agent", "description": "Agent 对话组", "sort_order": 2},
    {"name": "postprocess", "description": "后处理工具组", "sort_order": 3},
]

DEFAULT_MODELS = [
    # Image
    {"name": "gpt-image-2", "display_name": "GPT Image 2", "provider": "OpenAI",
     "billing_type": "per_call", "model_type": "image", "group": "image",
     "is_enabled": True, "trial_allowed": True, "price_per_call": "0.046",
     "context_window": 0, "supports_tools": False, "supports_vision": False, "sort_order": 1},
    # Agent models (15% markup on PackyAPI prices)
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
    # Postprocess
    {"name": "remove_bg", "display_name": "Remove Background", "provider": "Internal",
     "billing_type": "per_call", "model_type": "postprocess", "group": "postprocess",
     "is_enabled": True, "trial_allowed": False, "price_per_call": "0.010",
     "context_window": 0, "supports_tools": False, "supports_vision": False, "sort_order": 100},
]


async def _migrate_groups(session):
    """Migrate old group names to new ones in all related tables."""
    import json
    from sqlalchemy import update as sa_update, delete as sa_delete
    from app.models.user import UserToken
    from app.models.token import TokenInventory, Order

    group_map = {"sora": "image", "codex": "agent", "codex-sale": "agent"}

    for old_name, new_name in group_map.items():
        result = await session.execute(select(Group).where(Group.name == old_name))
        if not result.scalar_one_or_none():
            continue

        # Update AIModel.group
        await session.execute(sa_update(AIModel).where(AIModel.group == old_name).values(group=new_name))
        # Update UserToken.group
        await session.execute(sa_update(UserToken).where(UserToken.group == old_name).values(group=new_name))
        # Update TokenInventory.group
        await session.execute(sa_update(TokenInventory).where(TokenInventory.group == old_name).values(group=new_name))

        # Update Order.group (comma-separated) and Order.items_json
        order_result = await session.execute(select(Order).where(Order.group.contains(old_name)))
        orders = order_result.scalars().all()
        for order in orders:
            groups_list = [group_map.get(g.strip(), g.strip()) for g in order.group.split(",")]
            order.group = ",".join(groups_list)
            if order.items_json:
                try:
                    items = json.loads(order.items_json)
                    for item in items:
                        if item.get("group") in group_map:
                            item["group"] = group_map[item["group"]]
                    order.items_json = json.dumps(items)
                except (json.JSONDecodeError, TypeError):
                    pass

        # Delete old Group row
        await session.execute(sa_delete(Group).where(Group.name == old_name))

    # Migrate model_type chat -> agent in existing AIModel records
    await session.execute(sa_update(AIModel).where(AIModel.model_type == "chat").values(model_type="agent"))

    await session.commit()


async def seed_defaults():
    async with AsyncSession(engine) as session:
        await _migrate_groups(session)
        for g in DEFAULT_GROUPS:
            result = await session.execute(select(Group).where(Group.name == g["name"]))
            if not result.scalar_one_or_none():
                session.add(Group(**g))
        for m in DEFAULT_MODELS:
            result = await session.execute(select(AIModel).where(AIModel.name == m["name"], AIModel.group == m["group"]))
            if not result.scalar_one_or_none():
                session.add(AIModel(**m))
        await session.commit()


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_redis()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_columns(conn)
    await seed_defaults()
    from app.core.packy_sync import start_price_sync_loop
    asyncio.create_task(start_price_sync_loop())

    # 恢复未处理的退款（超时自动退款，未超时重设过期键）
    await recover_pending_refunds()

    # 启动 Redis keyspace 监听器（15分钟自动退款）
    asyncio.create_task(start_keyspace_listener())

    yield


app = FastAPI(title="CyImagePro Service", version="1.0.0", lifespan=lifespan)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": f"服务器内部错误：{str(exc)}"},
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(tokens.router, prefix="/api/tokens", tags=["tokens"])
app.include_router(payment.router, prefix="/api/pay", tags=["payment"])
app.include_router(notice.router, prefix="/api/notice", tags=["notice"])
app.include_router(prompts.router, prefix="/api/prompts", tags=["prompts"])
app.include_router(models.router, prefix="/api/models", tags=["models"])
app.include_router(usage.router, prefix="/api/usage", tags=["usage"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])

@app.get("/api")
@app.get("/api/")
async def api_index():
    return {
        "status": "ok",
        "base_url": "/api",
        "routes": [
            "/api/auth",
            "/api/users",
            "/api/tokens",
            "/api/pay",
            "/api/notice",
            "/api/prompts",
            "/api/models",
            "/api/usage",
        ],
    }

# Serve frontend admin panel
if os.path.exists("/app/static"):
    app.mount("/admin", StaticFiles(directory="/app/static", html=True), name="admin")


@app.get("/health")
async def health():
    return {"status": "ok"}
