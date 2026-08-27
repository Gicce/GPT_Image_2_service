"""Official Skill Catalog validation, serialization and seed content."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.skill import SkillPackage


VALID_DOMAINS = {"desk_setup", "ecommerce", "product", "brand_ad", "interior", "sports", "ui"}
VALID_PROFILE_KINDS = {"base", "style", "theme", "platform", "camera", "lighting"}
REQUIRED_PACKAGE_KEYS = {"availability", "wizard_steps", "profiles", "core_rules", "asset_roles", "review_rubric"}


def validate_package_payload(payload: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["payload 必须是对象"]
    missing = sorted(REQUIRED_PACKAGE_KEYS - set(payload))
    if missing:
        errors.append(f"缺少字段：{', '.join(missing)}")
    if payload.get("availability") not in {"ready", "planned", "testing"}:
        errors.append("availability 必须为 ready、testing 或 planned")
    steps = payload.get("wizard_steps")
    if not isinstance(steps, list) or not steps:
        errors.append("wizard_steps 至少包含一个步骤")
    else:
        ids = [step.get("id") for step in steps if isinstance(step, dict)]
        if len(ids) != len(steps) or any(not item for item in ids) or len(ids) != len(set(ids)):
            errors.append("wizard_steps 的 id 必须存在且唯一")
    profiles = payload.get("profiles")
    if not isinstance(profiles, list):
        errors.append("profiles 必须是数组")
    else:
        for index, profile in enumerate(profiles):
            if not isinstance(profile, dict) or not profile.get("id") or profile.get("kind") not in VALID_PROFILE_KINDS:
                errors.append(f"profiles[{index}] 缺少 id 或 kind 不合法")
    for key in ("core_rules", "asset_roles", "review_rubric"):
        if not isinstance(payload.get(key), list):
            errors.append(f"{key} 必须是数组")
    return errors


def ensure_valid_package(domain: str, payload: dict) -> None:
    if domain not in VALID_DOMAINS:
        raise HTTPException(status_code=400, detail="不支持的 Skill 领域")
    errors = validate_package_payload(payload)
    if errors:
        raise HTTPException(status_code=400, detail={"code": "SKILL_PACKAGE_INVALID", "errors": errors})


def serialize_package(row: SkillPackage, *, include_payload: bool = True) -> dict:
    data = {
        "id": row.id,
        "skill_id": row.skill_id,
        "version": row.version,
        "name": row.name,
        "domain": row.domain,
        "status": row.status,
        "summary": row.summary,
        "availability": (row.payload or {}).get("availability", "planned"),
        "created_by": row.created_by,
        "published_by": row.published_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "source": getattr(row, "source", "official") or "official",
        "author_display_name": getattr(row, "author_display_name", None),
        "preview_sample_id": getattr(row, "preview_sample_id", None),
        "preview_url": f"/api/skills/community-samples/{row.preview_sample_id}" if getattr(row, "preview_sample_id", None) else None,
    }
    if include_payload:
        data["payload"] = row.payload or {}
    return data


def catalog_etag(packages: list[dict]) -> str:
    raw = json.dumps(packages, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return '"' + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24] + '"'


DESK_PROFILES = [
    {"id": "business_walnut", "kind": "base", "name": "Business Walnut", "prompt": "浅胡桃木专业升降桌，黑灰商务设备，暖白灯光，克制摆件"},
    {"id": "business", "kind": "style", "name": "商务", "prompt": "成熟克制的高端商务工作空间"},
    {"id": "minimal", "kind": "style", "name": "极简", "prompt": "极简留白，低装饰密度，清晰秩序"},
    {"id": "creator", "kind": "style", "name": "创作者", "prompt": "专业 Creator Workspace，兼顾创作设备与效率"},
    {"id": "gaming", "kind": "style", "name": "电竞", "prompt": "克制的专业电竞语言，不使用彩虹 RGB"},
    {"id": "industrial", "kind": "style", "name": "工业", "prompt": "金属、深灰与真实结构细节"},
    {"id": "cozy", "kind": "style", "name": "温馨", "prompt": "柔和暖光与少量布艺，保持专业操作区"},
    {"id": "cute", "kind": "style", "name": "可爱", "prompt": "成年人使用的精致可爱设计，甜而不幼稚"},
    {"id": "theme_none", "kind": "theme", "name": "无主题", "prompt": "不加入 IP 主题"},
    {"id": "original_cute", "kind": "theme", "name": "原创可爱", "prompt": "少量原创角色与圆润装饰，不使用第三方 IP"},
    {"id": "custom", "kind": "theme", "name": "自定义主题", "prompt": "仅使用用户明确提供并有权使用的主题素材"},
]

DESK_PAYLOAD = {
    "availability": "ready",
    "default_profile_ids": ["business_walnut", "business", "theme_none"],
    "wizard_steps": [
        {"id": "template", "name": "选择模板"},
        {"id": "purpose", "name": "填写用途"},
        {"id": "assets", "name": "准备素材"},
        {"id": "analysis", "name": "确认素材卡"},
        {"id": "profiles", "name": "选择风格"},
        {"id": "review", "name": "确认生成"},
    ],
    "profiles": DESK_PROFILES,
    "asset_roles": [
        {"id": "brand_logo", "name": "品牌 Logo", "analysis_required_for_brand": True},
        {"id": "device", "name": "电脑主机"},
        {"id": "space", "name": "房间参考"},
        {"id": "style_reference", "name": "风格参考"},
    ],
    "core_rules": [
        "主显示器必须正中，键盘与主屏中轴对齐，鼠标位于右侧自然操作区",
        "27 英寸竖屏位于左侧，32 英寸横屏为绝对视觉中心",
        "两块显示器共用一个桌夹底座、一个主立柱和左右两支独立机械臂",
        "使用真实产品比例、VESA 安装、桌夹承重和隐藏走线逻辑",
        "桌面操作区不得被摆件侵占，主机保留合理散热空间",
        "使用 35–50mm 等效镜头的专业桌搭商业摄影，避免超广角畸变",
    ],
    "review_rubric": ["专业结构", "人体工学", "产品真实性", "素材保持", "风格一致性", "技术质量"],
    "defaults": {"size": "1536x1024", "quality": "high", "count": 1},
}


def _planned_payload(domain: str) -> dict:
    return {
        "availability": "planned",
        "wizard_steps": [{"id": "brief", "name": "创作需求"}],
        "profiles": [],
        "asset_roles": [],
        "core_rules": [f"{domain} 领域规则正在测试中"],
        "review_rubric": ["任务完成度", "技术质量"],
    }


SEED_PACKAGES = [
    ("professional_desk_setup", "1.0.0", "专业桌搭", "desk_setup", "真实产品、人体工学与风格主题可组合的专业桌搭", DESK_PAYLOAD),
    ("ecommerce_visual", "0.1.0", "电商视觉", "ecommerce", "商品主图、详情页与平台素材", _planned_payload("电商视觉")),
    ("product_visual", "0.1.0", "产品视觉", "product", "产品棚拍、场景图与结构表达", _planned_payload("产品视觉")),
    ("brand_campaign", "0.1.0", "品牌广告", "brand_ad", "品牌主视觉与系列广告素材", _planned_payload("品牌广告")),
    ("interior_visual", "0.1.0", "建筑与室内", "interior", "住宅、办公和商业空间视觉", _planned_payload("建筑与室内")),
    ("sports_visual", "0.1.0", "运动视觉", "sports", "真实动作与商业运动摄影", _planned_payload("运动视觉")),
    ("ui_concept", "0.1.0", "UI 概念设计", "ui", "Web、移动端与桌面端界面概念", _planned_payload("UI 概念设计")),
]


async def seed_skill_catalog(db: AsyncSession) -> None:
    for skill_id, version, name, domain, summary, payload in SEED_PACKAGES:
        existing = await db.execute(select(SkillPackage).where(
            SkillPackage.skill_id == skill_id, SkillPackage.version == version,
        ))
        if existing.scalar_one_or_none():
            continue
        db.add(SkillPackage(
            skill_id=skill_id,
            version=version,
            name=name,
            domain=domain,
            status="published",
            summary=summary,
            payload=payload,
            created_by="system-seed",
            published_by="system-seed",
            published_at=datetime.now(timezone.utc),
        ))
