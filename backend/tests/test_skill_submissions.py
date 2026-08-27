import copy

import httpx
import pytest

from app.core.config import settings
from app.core.security import create_access_token
from app.main import app
from app.services.skill_catalog import DESK_PAYLOAD
from tests.conftest import make_admin_headers, make_user


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as value:
        yield value


def _facts():
    """与客户端 SkillSourceFact[] 一致的结构化事实数组。"""
    return [
        {"key": "composition", "label": "构图", "value": "主体居中，留白均匀", "immutable": True},
        {"key": "contract:style", "label": "风格", "value": "现代极简", "immutable": True},
    ]


def _body(**overrides):
    payload = copy.deepcopy(DESK_PAYLOAD)
    payload["availability"] = "testing"
    body = {
        "local_skill_id": "visual-project-skill",
        "revision": 3,
        "version": "1.0.0",
        "name": "通用人物海报",
        "domain": "desk_setup",
        "summary": "从视觉项目通用化的测试 Skill",
        "payload": payload,
        "source_facts": _facts(),
        "authoring_meta": {"model": "test-model", "source_revision": 3, "confirmed_at": "2026-08-28T00:00:00Z"},
    }
    body.update(overrides)
    return body


async def _upload_sample(client, submission_id, headers, *, content=b"\x89PNG\r\n\x1a\n" + b"x" * 32):
    return await client.post(
        f"/api/skills/submissions/{submission_id}/samples", headers=headers,
        files={"image": ("sample.png", content, "image/png")},
        data={"metadata_json": "{}", "public_cover": "true"},
    )


async def test_submission_review_and_community_publish(client, tmp_path):
    settings.SKILL_SAMPLE_DIR = str(tmp_path)
    user = await make_user("skill_author")
    user_headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    created = await client.post("/api/skills/submissions", headers=user_headers, json=_body())
    assert created.status_code == 200, created.text
    submission_id = created.json()["id"]
    # source_facts 以数组合同入库并回显
    assert created.json()["source_facts"] == _facts()

    # 内容冲突的重复投稿 → 结构化 409
    conflict = await client.post("/api/skills/submissions", headers=user_headers, json=_body(name="重复", summary="重复"))
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "SKILL_SUBMISSION_DUPLICATE"
    assert conflict.json()["detail"]["message"]

    sample = await _upload_sample(client, submission_id, user_headers)
    assert sample.status_code == 200, sample.text

    started = await client.post(
        f"/api/admin/skill-submissions/{submission_id}/start-review", headers=make_admin_headers(),
    )
    assert started.status_code == 200
    approved = await client.post(
        f"/api/admin/skill-submissions/{submission_id}/approve", headers=make_admin_headers(),
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["package"]["source"] == "community"
    assert approved.json()["package"]["availability"] == "ready"

    catalog = await client.get("/api/skills/catalog")
    public_id = approved.json()["package"]["skill_id"]
    assert any(item["skill_id"] == public_id and item["author_display_name"] == "skill_author" for item in catalog.json()["packages"])


async def test_zero_sample_submission_resume(client, tmp_path):
    """投稿创建后样例上传失败（零样例）：相同内容重试返回已有投稿，不产生重复。"""
    settings.SKILL_SAMPLE_DIR = str(tmp_path / "broken")
    user = await make_user("resume_author")
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}

    first = await client.post("/api/skills/submissions", headers=headers, json=_body())
    assert first.status_code == 200, first.text

    # 第二步样例上传失败（目录不可写：父路径是一个文件）
    blocker = tmp_path / "blocker"
    blocker.write_bytes(b"not-a-dir")
    settings.SKILL_SAMPLE_DIR = str(blocker)
    failed = await _upload_sample(client, first.json()["id"], headers)
    assert failed.status_code == 500
    assert failed.json()["detail"]["code"] == "SKILL_SAMPLE_WRITE_FAILED"

    # 恢复：相同内容再次创建 → 返回已有投稿（200 同一 id）
    settings.SKILL_SAMPLE_DIR = str(tmp_path / "fixed")
    resumed = await client.post("/api/skills/submissions", headers=headers, json=_body())
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["id"] == first.json()["id"]
    assert resumed.json()["sample_count"] == 0

    # 补传样例后进入正常审核链路（开始审核强制至少一张样例）
    before_sample = await client.post(
        f"/api/admin/skill-submissions/{first.json()['id']}/start-review", headers=make_admin_headers(),
    )
    assert before_sample.status_code == 409
    assert "样例" in before_sample.json()["detail"]["message"]
    sample = await _upload_sample(client, first.json()["id"], headers)
    assert sample.status_code == 200
    started = await client.post(
        f"/api/admin/skill-submissions/{first.json()['id']}/start-review", headers=make_admin_headers(),
    )
    assert started.status_code == 200


async def test_resume_rejected_when_content_differs(client, tmp_path):
    """零样例但内容被修改 → 409（不能借恢复通道覆盖内容）。"""
    settings.SKILL_SAMPLE_DIR = str(tmp_path)
    user = await make_user("conflict_author")
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    first = await client.post("/api/skills/submissions", headers=headers, json=_body())
    assert first.status_code == 200
    changed = await client.post(
        "/api/skills/submissions", headers=headers,
        json=_body(payload={**copy.deepcopy(DESK_PAYLOAD), "availability": "testing", "core_rules": ["另一套规则"]}),
    )
    assert changed.status_code == 409
    assert changed.json()["detail"]["code"] == "SKILL_SUBMISSION_DUPLICATE"


async def test_sample_upload_atomic_no_partial_file(client, tmp_path):
    """样例写入失败时不残留半成品文件（临时文件 + 最终文件都清理）。"""
    sample_root = tmp_path / "samples"
    settings.SKILL_SAMPLE_DIR = str(sample_root)
    user = await make_user("atomic_author")
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    created = await client.post("/api/skills/submissions", headers=headers, json=_body())
    assert created.status_code == 200

    # 类型不支持：不落盘
    bad_type = await client.post(
        f"/api/skills/submissions/{created.json()['id']}/samples", headers=headers,
        files={"image": ("sample.gif", b"GIF89a" + b"x" * 16, "image/gif")},
        data={"metadata_json": "{}"},
    )
    assert bad_type.status_code == 400
    assert bad_type.json()["detail"]["code"] == "SKILL_SAMPLE_TYPE_UNSUPPORTED"

    # 超限：413 结构化
    settings.SKILL_SAMPLE_MAX_BYTES = 16
    too_large = await _upload_sample(client, created.json()["id"], headers, content=b"x" * 64)
    assert too_large.status_code == 413
    assert too_large.json()["detail"]["code"] == "SKILL_SAMPLE_TOO_LARGE"
    settings.SKILL_SAMPLE_MAX_BYTES = 10 * 1024 * 1024

    # 正常上传后目录内只有 1 个最终文件、无 .uploading 临时文件
    ok = await _upload_sample(client, created.json()["id"], headers)
    assert ok.status_code == 200
    files = list((sample_root / created.json()["id"]).iterdir())
    assert len(files) == 1
    assert not files[0].name.endswith(".uploading")


async def test_submission_rejects_local_paths(client):
    user = await make_user("unsafe_author")
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    payload = copy.deepcopy(DESK_PAYLOAD)
    payload["core_rules"] = ["读取 C:\\Users\\name\\private.png"]
    response = await client.post("/api/skills/submissions", headers=headers, json=_body(payload=payload))
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "SKILL_SUBMISSION_UNSAFE"


async def test_source_facts_value_scanned(client):
    """source_facts 数组的 value 同样过净化扫描（含本地路径 → 拒绝）。"""
    user = await make_user("fact_scan_author")
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    unsafe_facts = [{"key": "asset", "label": "素材", "value": "/home/user/secret.png", "immutable": True}]
    response = await client.post(
        "/api/skills/submissions", headers=headers, json=_body(source_facts=unsafe_facts),
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "SKILL_SUBMISSION_UNSAFE"
    assert any("source_facts" in item for item in response.json()["detail"]["errors"])


async def test_source_facts_must_be_structured_array(client):
    """source_facts 不再接受旧 dict 合同（与客户端一致的结构化数组）。"""
    user = await make_user("legacy_fact_author")
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    response = await client.post(
        "/api/skills/submissions", headers=headers,
        json=_body(source_facts={"composition": "主体居中"}),
    )
    assert response.status_code == 422


async def test_mine_and_not_found_structured(client, tmp_path):
    """GET /api/skills/mine 已登录返回 200；不存在的投稿 → 结构化 404。"""
    settings.SKILL_SAMPLE_DIR = str(tmp_path)
    user = await make_user("mine_author")
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    mine = await client.get("/api/skills/mine", headers=headers)
    assert mine.status_code == 200
    assert mine.json()["total"] == 0

    missing = await client.get("/api/skills/submissions/00000000-0000-0000-0000-0000000000ff", headers=headers)
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "SKILL_SUBMISSION_NOT_FOUND"
    assert missing.json()["detail"]["message"]
