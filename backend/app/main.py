from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import os
import traceback

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
