import asyncio
import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.redis import get_redis, NOTICE_CHANNEL
from app.models.content import Notice

router = APIRouter()

HEARTBEAT_SECONDS = 25


@router.get("")
async def get_notice(db: AsyncSession = Depends(get_db)):
    redis = get_redis()
    cached = await redis.get("notice_content")
    if cached is not None:
        return json.loads(cached)

    result = await db.execute(select(Notice).limit(1))
    notice = result.scalar_one_or_none()
    data = {
        "content": notice.content if notice else "",
        "is_active": notice.is_active if notice else False,
    }
    await redis.setex("notice_content", 180, json.dumps(data))
    return data


@router.get("/stream")
async def notice_stream():
    """运营通知 SSE 实时通道（公开，与 GET /api/notice 同可见性）。

    - 管理端保存通知 → Redis pubsub 广播 → 本通道推送 `notice.updated` 事件
    - 客户端收到事件后重新 GET /api/notice（数据真相仍走 GET）
    - 25s 心跳注释行保活（Nginx/Cloudflare 不断连）
    """
    async def event_gen():
        redis = get_redis()
        pubsub = redis.pubsub()
        await pubsub.subscribe(NOTICE_CHANNEL)
        try:
            # retry 指令：断线后 EventSource 原生自动重连
            yield "retry: 5000\n\n"
            # 连接建立即发一次事件，客户端顺带刷新一遍（补齐连接前的变更）
            yield "event: notice.updated\ndata: connected\n\n"
            while True:
                try:
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=HEARTBEAT_SECONDS
                    )
                except (asyncio.CancelledError, GeneratorExit):
                    raise
                except Exception:
                    await asyncio.sleep(1)
                    continue
                if message and message.get("type") == "message":
                    yield f"event: notice.updated\ndata: {message.get('data', 'updated')}\n\n"
                else:
                    yield ": ping\n\n"
        finally:
            try:
                await pubsub.close()
            except Exception:
                pass

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
