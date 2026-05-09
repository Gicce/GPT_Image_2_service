from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import os

from app.core.database import engine, Base
from app.core.redis import init_redis
from app.api.routes import auth, users, tokens, payment, notice, prompts, models, admin, usage


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_redis()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(title="CyImagePro Service", version="1.0.0", lifespan=lifespan)

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

# Serve frontend admin panel
if os.path.exists("/app/static"):
    app.mount("/admin", StaticFiles(directory="/app/static", html=True), name="admin")


@app.get("/health")
async def health():
    return {"status": "ok"}
