from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import os
import traceback

from app.core.database import engine, Base, AsyncSession
from app.core.redis import init_redis
from app.api.routes import auth, users, tokens, payment, notice, prompts, models, admin, usage
from app.models.content import Group, AIModel
from sqlalchemy import select

DEFAULT_GROUPS = [
    {"name": "sora", "description": "Sora 项目组", "sort_order": 1},
    {"name": "codex", "description": "Codex 项目组", "sort_order": 2},
    {"name": "codex-sale", "description": "Codex 优惠组", "sort_order": 3},
]

DEFAULT_MODELS = [
    {"name": "gpt-image-2", "display_name": "GPT Image 2", "provider": "OpenAI", "billing_type": "per_call", "model_type": "image", "group": "sora", "is_enabled": True, "trial_allowed": True, "price_per_call": "0.040", "sort_order": 1},
    {"name": "gpt-5.5", "display_name": "GPT-5.5", "provider": "OpenAI", "billing_type": "per_token", "model_type": "chat", "group": "codex", "is_enabled": True, "trial_allowed": False, "price_input": "0.0025", "price_output": "0.0150", "price_cached": "0.0003", "sort_order": 2},
    {"name": "gpt-5.5", "display_name": "GPT-5.5 (优惠)", "provider": "OpenAI", "billing_type": "per_token", "model_type": "chat", "group": "codex-sale", "is_enabled": True, "trial_allowed": False, "price_input": "0.0020", "price_output": "0.0120", "price_cached": "0.0002", "sort_order": 3},
]


async def seed_defaults():
    async with AsyncSession(engine) as session:
        for g in DEFAULT_GROUPS:
            result = await session.execute(select(Group).where(Group.name == g["name"]))
            if not result.scalar_one_or_none():
                session.add(Group(**g))
        for m in DEFAULT_MODELS:
            result = await session.execute(select(AIModel).where(AIModel.name == m["name"], AIModel.group == m["group"]))
            if not result.scalar_one_or_none():
                session.add(AIModel(**m))
        await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_redis()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await seed_defaults()
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
