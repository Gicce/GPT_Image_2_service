import asyncio
import logging
from decimal import Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.content import AIModel

logger = logging.getLogger(__name__)

# Models we want to sync from PackyAPI
SYNCED_MODELS = {
    "qwen3.5-flash", "qwen3.5-plus", "qwen3.6-plus", "qwen-max",
    "deepseek-v4-flash", "deepseek-v4-pro", "glm-5", "kimi-k2.5",
    "gpt-5.4-mini", "gpt-5.4", "claude-sonnet-4-6", "gpt-image-2",
}


async def sync_packyapi_prices(session: AsyncSession):
    """Fetch prices from PackyAPI and update AIModel records."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(settings.PACKYAPI_PRICING_URL)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.error(f"PackyAPI price sync failed: {e}")
        return

    models_data = data.get("data", [])
    if not models_data:
        logger.warning("PackyAPI returned empty data")
        return

    markup = Decimal(str(1 + settings.PACKYAPI_MARKUP_PERCENT / 100))

    for item in models_data:
        model_name = item.get("model_name", "")
        if model_name not in SYNCED_MODELS:
            continue

        # Filter: must support openai endpoint
        endpoints = item.get("supported_endpoint_types", [])
        if "openai" not in endpoints:
            continue

        quota_type = item.get("quota_type", 0)
        billing_type = "per_call" if quota_type == 1 else "per_token"

        # Determine which group this model belongs to
        if model_name == "gpt-image-2":
            group = "image"
        elif billing_type == "per_call":
            group = "postprocess"
        else:
            group = "agent"

        # Find existing model in our DB
        result = await session.execute(
            select(AIModel).where(AIModel.name == model_name, AIModel.group == group)
        )
        model = result.scalar_one_or_none()
        if not model:
            continue

        if billing_type == "per_token":
            model_ratio = Decimal(str(item.get("model_ratio", 0)))
            completion_ratio = Decimal(str(item.get("completion_ratio", 1)))
            cache_ratio = Decimal(str(item.get("cache_ratio", 0)))

            # PackyAPI prices are per 1M tokens; convert to per 1K and apply markup
            price_input = (model_ratio / 1000 * markup).quantize(Decimal("0.000001"))
            price_output = (model_ratio * completion_ratio / 1000 * markup).quantize(Decimal("0.000001"))
            price_cached = (model_ratio * cache_ratio / 1000 * markup).quantize(Decimal("0.000001")) if cache_ratio else None

            model.price_input = str(price_input)
            model.price_output = str(price_output)
            model.price_cached = str(price_cached) if price_cached else None
        elif billing_type == "per_call":
            model_price = Decimal(str(item.get("model_price", 0)))
            price_per_call = (model_price * markup).quantize(Decimal("0.000001"))
            model.price_per_call = str(price_per_call)

        logger.info(f"Synced price for {model_name}: input={model.price_input}, output={model.price_output}")

    await session.commit()
    logger.info("PackyAPI price sync completed")


async def start_price_sync_loop():
    """Background task that periodically syncs prices from PackyAPI."""
    from app.core.database import AsyncSessionLocal

    while True:
        try:
            async with AsyncSessionLocal() as session:
                await sync_packyapi_prices(session)
        except Exception:
            logger.exception("Error in PackyAPI price sync loop")

        await asyncio.sleep(settings.PACKYAPI_SYNC_INTERVAL_MINUTES * 60)