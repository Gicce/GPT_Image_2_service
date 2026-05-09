from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.models.content import Prompt

router = APIRouter()

CATEGORIES = [
    "抖音商品图", "电商详情图", "商品白底图", "去除背景",
    "图片修图", "提取图片", "分镜", "商品标注",
    "跨境电商图", "跨境电商A+图",
]


@router.get("")
async def get_prompts(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Prompt)
        .where(Prompt.is_active == True)
        .order_by(Prompt.category, Prompt.sort_order)
    )
    prompts = result.scalars().all()

    grouped: dict = {cat: [] for cat in CATEGORIES}
    for p in prompts:
        if p.category in grouped:
            grouped[p.category].append({"id": p.id, "title": p.title, "content": p.content})
        else:
            grouped[p.category] = [{"id": p.id, "title": p.title, "content": p.content}]

    return {"categories": CATEGORIES, "prompts": grouped}
