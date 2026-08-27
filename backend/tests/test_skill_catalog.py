import copy

import httpx
import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.skill import SkillPackage
from app.services.skill_catalog import DESK_PAYLOAD
from tests.conftest import make_admin_headers


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_public_catalog_returns_ready_and_planned_skills_with_etag(client):
    response = await client.get("/api/skills/catalog")
    assert response.status_code == 200
    assert response.headers["etag"]
    packages = response.json()["packages"]
    desk = next(item for item in packages if item["skill_id"] == "professional_desk_setup")
    assert desk["availability"] == "ready"
    assert any(item["availability"] == "planned" for item in packages)

    cached = await client.get("/api/skills/catalog", headers={"If-None-Match": response.headers["etag"]})
    assert cached.status_code == 304


async def test_public_detail_exposes_versioned_desk_contract(client):
    response = await client.get("/api/skills/professional_desk_setup/versions/1.0.0")
    assert response.status_code == 200
    payload = response.json()["payload"]
    assert payload["availability"] == "ready"
    assert "business_walnut" in payload["default_profile_ids"]
    assert any("机械臂" in rule for rule in payload["core_rules"])


async def test_admin_draft_publish_immutability_and_rollback(client):
    headers = make_admin_headers()
    payload = copy.deepcopy(DESK_PAYLOAD)
    payload["availability"] = "testing"
    created = await client.post("/api/admin/skill-packages", headers=headers, json={
        "skill_id": "professional_desk_setup",
        "version": "1.1.0",
        "name": "专业桌搭",
        "domain": "desk_setup",
        "summary": "测试新版本",
        "payload": payload,
    })
    assert created.status_code == 200, created.text
    package_id = created.json()["id"]

    validated = await client.post(f"/api/admin/skill-packages/{package_id}/validate", headers=headers)
    assert validated.json() == {"ok": True, "errors": []}

    published = await client.post(f"/api/admin/skill-packages/{package_id}/publish", headers=headers)
    assert published.status_code == 200
    assert published.json()["status"] == "published"

    immutable = await client.put(f"/api/admin/skill-packages/{package_id}", headers=headers, json={
        "summary": "不允许原地修改",
    })
    assert immutable.status_code == 409

    async with AsyncSessionLocal() as session:
        previous = (await session.execute(select(SkillPackage).where(
            SkillPackage.skill_id == "professional_desk_setup",
            SkillPackage.version == "1.0.0",
        ))).scalar_one()
        previous_id = previous.id
        assert previous.status == "archived"

    rolled_back = await client.post(
        f"/api/admin/skill-packages/{previous_id}/rollback", headers=headers,
    )
    assert rolled_back.status_code == 200
    assert rolled_back.json()["version"] == "1.0.0"
    assert rolled_back.json()["status"] == "published"


async def test_invalid_package_cannot_be_created(client):
    response = await client.post("/api/admin/skill-packages", headers=make_admin_headers(), json={
        "skill_id": "broken_skill",
        "version": "1.0.0",
        "name": "错误模板",
        "domain": "desk_setup",
        "summary": "",
        "payload": {"availability": "ready"},
    })
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "SKILL_PACKAGE_INVALID"
