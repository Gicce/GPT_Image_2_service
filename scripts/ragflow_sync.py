#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ragflow-sync（子仓库版）—— 将本仓库 docs/*.md 单向增量同步到本项目专属 RAGFlow Dataset。

与根工作区 scripts/ragflow_sync.py 同源（ADR-004 原则不变）：
- docs/（Git 管理）是唯一事实源；RAGFlow 只做索引/解析/检索，永不反向覆盖
- 双指纹增量：正文变化（content_sha256，不含 frontmatter）→ 重传；仅元数据变化 → 只 PUT meta_fields；
  均未变 → SKIP；本地删除仅删本同步器管理的远端文档
- archive/** 为历史归档，默认不同步（与根工作区口径一致）
- API Key 只从本仓库根目录 .env 读取（已 gitignore），任何输出不回显

按脚本所在仓库目录名自动识别项目（GPT_Image_2_Application / GPT_Image_2_service）。
零第三方依赖（Python 3.9+ 标准库）。

用法（在本仓库根目录）：
  python scripts/ragflow_sync.py init
  python scripts/ragflow_sync.py status
  python scripts/ragflow_sync.py sync [--dry-run]
  python scripts/ragflow_sync.py retrieve "问题"
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "docs"
RF_DIR = ROOT / ".ragflow"
CONFIG_PATH = RF_DIR / "config.json"
STATE_PATH = RF_DIR / "state.json"
ENV_PATH = ROOT / ".env"

HTTP_TIMEOUT = 30
PARSE_POLL_INTERVAL = 3
PARSE_TIMEOUT = 300

# ---------- 项目识别 ----------

PROJECTS = {
    "GPT_Image_2_Application": {
        "project": "CyImagePro 客户端（GPT_Image_2_Application）",
        "project_slug": "gpt-image-client",
        "side": "client",
        "dataset_name": "GPT_Image_2_Application",
        "dataset_description": (
            "CyImagePro 客户端知识库：Tauri + React + Rust 客户端逻辑、画布、图像工作流、漫画、"
            "客户端构建、签名、发布与自动更新。事实源：本仓库 docs/，单向同步，不含密钥与客户数据。"
            "服务端/管理后台/支付计费/部署运维在 GPT_Image_2_service 知识库；共享 API 契约权威定义在服务端。"
        ),
    },
    "GPT_Image_2_service": {
        "project": "CyImagePro 服务端（GPT_Image_2_service）",
        "project_slug": "gpt-image-service",
        "side": "server",
        "dataset_name": "GPT_Image_2_service",
        "dataset_description": (
            "CyImagePro 服务端知识库：FastAPI、管理后台（Vue3/naive-ui）、支付、计费、数据库、"
            "服务配置、部署运维；客户端-服务端共享 API 契约的权威定义在本库 docs/current/api.md。"
            "事实源：本仓库 docs/，单向同步，不含密钥与客户数据。客户端实现在 GPT_Image_2_Application 知识库。"
        ),
    },
}

PROJ = PROJECTS.get(ROOT.name)
if PROJ is None:
    sys.stderr.write(f"未识别的仓库目录：{ROOT.name}（期望 GPT_Image_2_Application 或 GPT_Image_2_service）\n")
    sys.exit(2)

TYPE_MAP = [
    ("README", "doc"),
    ("MIGRATION", "doc"),
    ("admin-frontend", "frontend"),
    ("frontend", "frontend"),
    ("ui", "ui"),
    ("api-consumption", "api"),
    ("models-server", "models"),
    ("models", "models"),
    ("backend", "backend"),
    ("database", "database"),
    ("deployment", "deployment"),
    ("release", "release"),
    ("testing", "testing"),
    ("skill-workshop", "skill"),
    ("skill-catalog", "skill"),
    ("known-issues", "known_issue"),
    ("todo", "todo"),
    ("ai-comic", "doc"),
]


class RagflowError(Exception):
    pass


def out(msg=""):
    print(msg, flush=True)


def load_env():
    vals = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                vals[k.strip()] = v.strip()
    return vals


ENV = load_env()
BASE_URL = ENV.get("RAGFLOW_BASE_URL", "http://192.168.110.91")
API_KEY = ENV.get("RAGFLOW_API_KEY", "")


class Client:
    def __init__(self, base_url, api_key):
        self.api = base_url.rstrip("/") + "/api/v1"
        self.key = api_key

    def _mask(self, text):
        return text.replace(self.key, "***") if self.key else text

    def request(self, method, path, *, json_body=None, raw=None, content_type=None):
        url = self.api + path
        headers = {"Authorization": "Bearer " + self.key}
        data = None
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif raw is not None:
            data = raw
            headers["Content-Type"] = content_type
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                body = resp.read().decode("utf-8", "replace")
                status = resp.status
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            status = e.code
        except urllib.error.URLError as e:
            raise RagflowError(f"无法连接 RAGFlow（{self.api}）：{self.reason(e)}")
        except TimeoutError:
            raise RagflowError(f"连接 RAGFlow 超时（{HTTP_TIMEOUT}s）：{self.api}{path}")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            raise RagflowError(self._mask(f"RAGFlow 返回非 JSON（HTTP {status}）：{body[:300]}"))
        # RAGFlow v0.26 常以 HTTP 200 + body code!=0 表达业务错误，必须检查 body code
        if payload.get("code") not in (0, None):
            msg = payload.get("message") or payload.get("error") or ""
            raise RagflowError(self._mask(f"RAGFlow 错误 code={payload.get('code')}（HTTP {status}）：{msg}"))
        return payload.get("data")

    @staticmethod
    def reason(e):
        return getattr(e, "reason", None) or str(e)


def require_client():
    if not API_KEY:
        raise RagflowError(
            f"RAGFLOW_API_KEY 未配置：请在 {ROOT.name}/.env 写入 RAGFLOW_BASE_URL 与 RAGFLOW_API_KEY（.env 已被 gitignore）")
    return Client(BASE_URL, API_KEY)


def load_config():
    if not CONFIG_PATH.exists():
        raise RagflowError(f"缺少 {CONFIG_PATH.relative_to(ROOT)}：请先运行 python scripts/ragflow_sync.py init")
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def load_state():
    if STATE_PATH.exists():
        try:
            st = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            if "files" in st:
                return {"files": st.get("files", {}), "last_sync": st.get("last_sync")}
            raise ValueError
        except (json.JSONDecodeError, ValueError):
            out("警告：state.json 损坏，按空状态处理（远端同名文档会被识别为碰撞并清理重传）")
    return {"files": {}}


def save_state(state):
    RF_DIR.mkdir(exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    # Windows 下 state.json 可能被杀毒/索引进程短暂锁定，replace 需重试
    for attempt in range(3):
        try:
            tmp.replace(STATE_PATH)
            return
        except OSError:
            if attempt == 2:
                raise
            time.sleep(0.5)


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# ---------- 本仓库事实采集 ----------

_GIT_INFO_CACHE = None


def git_info():
    global _GIT_INFO_CACHE
    if _GIT_INFO_CACHE is None:
        try:
            r = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--abbrev-ref", "HEAD"],
                               capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace")
            br = r.stdout.strip() or "unknown"
            r2 = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
                                capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace")
            cm = r2.stdout.strip() or "unknown"
            _GIT_INFO_CACHE = f"{ROOT.name}:{br}@{cm}"
        except Exception:
            _GIT_INFO_CACHE = f"{ROOT.name}:unknown"
    return _GIT_INFO_CACHE


def project_version():
    v = "unknown"
    try:
        pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        v = "client-" + str(pkg.get("version", "?"))
    except Exception:
        pass
    if PROJ["side"] == "server":
        try:
            main_py = (ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")
            m = re.search(r'APP_VERSION\s*=\s*["\']([^"\']+)', main_py)
            if m:
                v = "service-" + m.group(1)
        except Exception:
            pass
    return v


def parse_front_matter(text):
    fm = {}
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            kv = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.+?)\s*$", line)
            if kv:
                fm[kv.group(1).lower()] = kv.group(2).strip().strip("'\"")
    return fm


def classify(rel):
    """rel: docs 内相对路径（posix）。返回 (type, module)。"""
    parts = rel.split("/")
    name = parts[-1].rsplit(".", 1)[0]
    if "decisions" in parts:
        return "adr", "decisions"
    if "changelog" in parts:
        return "changelog", "changelog"
    if "contracts" in parts:
        return "api", "contracts"
    for prefix, t in TYPE_MAP:
        if name.startswith(prefix):
            return t, ("current" if parts[0] == "current" else "docs")
    return "doc", "docs"


def flatten_name(rel):
    return "docs__" + rel.replace("/", "__")


def build_meta(rel, fm):
    t, module = classify(rel)
    return {
        "project": PROJ["project"],
        "project_slug": PROJ["project_slug"],
        "side": PROJ["side"],
        "version": project_version(),
        "type": fm.get("type") or t,
        "module": fm.get("module") or module,
        "path": "docs/" + rel,
        "git_branch": git_info(),
        "git_commit": git_info(),
        "visibility": "internal",
        "lifecycle": fm.get("lifecycle") or ("current" if rel.startswith("current/") else "reference"),
        "authority": fm.get("authority") or ("current" if rel.startswith("current/") else "supporting"),
        "company_standard": fm.get("company_standard") or "1.x",
        "migrated_from": fm.get("migrated_from") or "",
        "source": "project-docs",
    }


# ---------- 文档发现与远端列表 ----------

def discover_docs():
    if not DOCS_DIR.exists():
        raise RagflowError(f"未找到 docs 目录：{DOCS_DIR}")
    rels = sorted(p.relative_to(DOCS_DIR).as_posix() for p in DOCS_DIR.rglob("*.md"))
    # archive/ 为历史归档，默认不进入活跃 Dataset（与根工作区口径一致）
    return [r for r in rels if not r.startswith("archive/")]


def sha256_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def body_without_front_matter(text):
    m = re.match(r"^---\s*\n.*?\n---\s*\n?", text, re.S)
    return text[m.end():] if m else text


def fingerprints(rel):
    text = (DOCS_DIR / rel).read_text(encoding="utf-8", errors="replace")
    content_sha = hashlib.sha256(body_without_front_matter(text).encode("utf-8")).hexdigest()
    meta = build_meta(rel, parse_front_matter(text))
    meta_sha = hashlib.sha256(
        json.dumps(meta, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return content_sha, meta, meta_sha, sha256_file(DOCS_DIR / rel)


def fetch_all_documents(client, ds_id):
    docs, page = [], 1
    while page <= 50:
        data = client.request("GET", f"/datasets/{ds_id}/documents?page={page}&page_size=100")
        batch = (data or {}).get("docs", [])
        docs.extend(batch)
        total = (data or {}).get("total", len(docs))
        if not batch or len(docs) >= total:
            break
        page += 1
    return docs


# ---------- 子命令 ----------

def cmd_init(args):
    client = require_client()
    datasets = client.request("GET", "/datasets?page_size=100") or []
    found = [d for d in datasets if d.get("name") == PROJ["dataset_name"]]
    if found:
        out(f"复用已有 Dataset：{PROJ['dataset_name']}（{found[0]['id']}）")
        ds = found[0]
    else:
        out(f"Dataset {PROJ['dataset_name']} 不存在，创建……")
        ds = client.request("POST", "/datasets", json_body={
            "name": PROJ["dataset_name"],
            "description": PROJ["dataset_description"],
            "chunk_method": "naive",
            "permission": "me",
        })
        out(f"已创建：{PROJ['dataset_name']}（{ds['id']}）")
    RF_DIR.mkdir(exist_ok=True)
    cfg = {
        "project": PROJ["project"],
        "project_slug": PROJ["project_slug"],
        "side": PROJ["side"],
        "dataset_name": PROJ["dataset_name"],
        "dataset_id": ds["id"],
        "base_url": BASE_URL,
        "api_base": BASE_URL.rstrip("/") + "/api/v1",
        "docs_dir": "docs",
        "include_pattern": "docs/**/*.md（不含 archive/）",
        "created_at": now_iso(),
        "note": "此文件不含任何密钥。API Key 保存在本仓库根目录 .env（已 gitignore）。",
    }
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    out(f"已写入 {CONFIG_PATH.relative_to(ROOT)}")


def cmd_status(args):
    cfg = load_config()
    state = load_state()
    client = require_client()
    out("RAGFlow Status（%s）" % PROJ["project"])
    out("")
    out(f"服务器：        {BASE_URL}（API {BASE_URL.rstrip('/')}/api/v1）")
    out(f"API Key：       {'已配置（.env）' if API_KEY else '未配置'}")
    ver = client.request("GET", "/system/version")
    out(f"RAGFlow 版本：  {ver}")
    datasets = client.request("GET", "/datasets?page_size=100") or []
    rels = discover_docs()
    fps = {rel: fingerprints(rel) for rel in rels}
    tracked = state["files"]
    synced, changed, meta_pending = [], [], []
    for rel in rels:
        entry = tracked.get(rel)
        if entry is None:
            continue
        if entry.get("content_sha256"):
            content_same = entry["content_sha256"] == fps[rel][0]
        else:
            content_same = entry.get("sha256") == fps[rel][3]
        if content_same and entry.get("meta_sha256") == fps[rel][2]:
            synced.append(rel)
        elif content_same:
            meta_pending.append(rel)
        else:
            changed.append(rel)
    pending = [r for r in rels if r not in tracked]
    removed = [r for r in tracked if r not in rels]
    ds = next((d for d in datasets if d["id"] == cfg.get("dataset_id")), None)
    out("")
    out(f"Dataset：{cfg.get('dataset_name', '?')}" + ("" if ds else " —— ⚠ 服务器上不存在，请运行 init"))
    if ds:
        remote_docs = fetch_all_documents(client, cfg["dataset_id"])
        ok = [d for d in remote_docs if d.get("run") == "DONE"]
        fail = [d for d in remote_docs if d.get("run") == "FAIL"]
        out(f"  远端文档：{len(remote_docs)}（解析完成 {len(ok)}，失败 {len(fail)}）")
        for d in fail:
            out(f"    - 解析失败 {d['name']}：{str(d.get('progress_msg') or '')[-160:]}")
    out(f"  本地：{len(rels)}  已同步：{len(synced)}  新增待传：{len(pending)}"
        f"  正文变化：{len(changed)}  仅元数据：{len(meta_pending)}  本地已删：{len(removed)}")
    out("")
    out(f"最后同步时间：  {state.get('last_sync', '从未同步')}")
    if pending or changed or meta_pending or removed:
        out("提示：执行 python scripts/ragflow_sync.py sync --dry-run 查看计划")


def plan_sync(state, fps, remote_by_name):
    rels = list(fps.keys())
    tracked = state.get("files", {})
    uploads, deletes, skips, meta_updates = [], [], [], []
    pre_delete_ids = set()

    for rel in rels:
        content_sha, _meta, meta_sha, file_sha = fps[rel]
        entry = tracked.get(rel)
        flat = flatten_name(rel)
        if entry is None:
            action = "新增"
        else:
            if entry.get("content_sha256"):
                content_changed = entry["content_sha256"] != content_sha
            else:
                content_changed = entry.get("sha256") != file_sha
            meta_changed = entry.get("meta_sha256") != meta_sha
            if not content_changed and entry.get("document_id"):
                if meta_changed:
                    meta_updates.append((rel, entry["document_id"], content_sha, meta_sha))
                    continue
                skips.append(rel)
                continue
            action = "更新"
        if entry and entry.get("document_id"):
            pre_delete_ids.add(entry["document_id"])
        dup = remote_by_name.get(flat)
        if dup and dup["id"] not in pre_delete_ids:
            pre_delete_ids.add(dup["id"])
        uploads.append((action, rel, flat))

    for rel, entry in tracked.items():
        if rel not in fps and entry.get("document_id"):
            deletes.append((rel, entry["document_id"]))

    return uploads, deletes, skips, meta_updates, sorted(pre_delete_ids)


def cmd_sync(args):
    cfg = load_config()
    client = require_client()
    state = load_state()
    ds_id = cfg.get("dataset_id")
    if not ds_id:
        raise RagflowError("配置缺少 dataset_id，请先运行 init")
    out("RAGFlow Sync（%s）" % PROJ["project"])
    if args.dry_run:
        out("（dry-run：只打印计划）")
    rels = discover_docs()
    fps = {rel: fingerprints(rel) for rel in rels}
    remote_docs = fetch_all_documents(client, ds_id)
    remote_by_name = {d["name"]: d for d in remote_docs}
    bucket = state

    uploads, deletes, skips, meta_updates, pre_delete_ids = plan_sync(bucket, fps, remote_by_name)
    tracked_by_id = {e["document_id"]: rel for rel, e in bucket["files"].items() if e.get("document_id")}
    reparse = [(tracked_by_id[d["id"]], d["id"]) for d in remote_docs
               if d.get("run") in ("FAIL", "UNSTART") and d["id"] in tracked_by_id]

    out(f"Dataset: {cfg.get('dataset_name')}（{ds_id}）")
    out(f"计划 —— 新增：{sum(1 for a, *_ in uploads if a == '新增')}"
        f"  更新：{sum(1 for a, *_ in uploads if a == '更新')}"
        f"  元数据更新：{len(meta_updates)}  跳过：{len(skips)}"
        f"  删除：{len(deletes)}  重解析：{len(reparse)}")
    for action, rel, flat in uploads:
        out(f"  [{action}] docs/{rel}")
    for rel, _doc_id, _c, _m in meta_updates:
        out(f"  [元数据更新] docs/{rel}")
    for rel, _ in deletes:
        out(f"  [删除] docs/{rel}（本地已移除）")

    failed = False
    if not args.dry_run:
        if not uploads and not deletes and not pre_delete_ids and not reparse and not meta_updates:
            out("无变更。")
        else:
            # 1) 删除（仅限 state 记录的、或与计划上传名碰撞的旧文档；均在当前 Dataset 内）
            ids_to_delete = sorted(set(pre_delete_ids) | {doc_id for _, doc_id in deletes})
            if ids_to_delete:
                client.request("DELETE", f"/datasets/{ds_id}/documents", json_body={"ids": ids_to_delete})
                out(f"已删除远端旧文档 {len(ids_to_delete)} 个（变更重传/本地删除/碰撞清理）")
            for rel, _ in deletes:
                bucket["files"].pop(rel, None)
            save_state(state)

            # 2) 上传 + 元数据
            uploaded = []
            for action, rel, flat in uploads:
                content = (DOCS_DIR / rel).read_bytes()
                body, ctype = multipart_body(flat, content)
                arr = client.request("POST", f"/datasets/{ds_id}/documents", raw=body, content_type=ctype)
                doc = arr[0] if isinstance(arr, list) else arr
                client.request("PUT", f"/datasets/{ds_id}/documents/{doc['id']}",
                               json_body={"meta_fields": fps[rel][1]})
                bucket["files"][rel] = {
                    "sha256": fps[rel][3],
                    "content_sha256": fps[rel][0],
                    "meta_sha256": fps[rel][2],
                    "document_id": doc["id"],
                    "display_name": flat,
                    "last_sync": now_iso(),
                }
                save_state(state)
                uploaded.append((rel, doc["id"]))
                out(f"已上传：docs/{rel}")

            # 2.5) 仅元数据变化
            for rel, doc_id, content_sha, meta_sha in meta_updates:
                client.request("PUT", f"/datasets/{ds_id}/documents/{doc_id}",
                               json_body={"meta_fields": fps[rel][1]})
                entry = bucket["files"].setdefault(rel, {})
                entry.update({
                    "sha256": fps[rel][3],
                    "content_sha256": content_sha,
                    "meta_sha256": meta_sha,
                    "document_id": doc_id,
                    "display_name": flatten_name(rel),
                    "last_sync": now_iso(),
                })
                save_state(state)
                out(f"已更新元数据：docs/{rel}")

            # 3) 触发解析 + 轮询
            parse_ok, parse_fail, parse_timeout = 0, [], []
            to_parse = uploaded + reparse
            if to_parse:
                client.request("POST", f"/datasets/{ds_id}/chunks",
                               json_body={"document_ids": list({doc_id for _, doc_id in to_parse})})
                out(f"已触发解析（{len(to_parse)} 个），轮询状态……")
                deadline = time.time() + PARSE_TIMEOUT
                pending = {doc_id: rel for rel, doc_id in to_parse}
                while pending and time.time() < deadline:
                    time.sleep(PARSE_POLL_INTERVAL)
                    docs = fetch_all_documents(client, ds_id)
                    by_id = {d["id"]: d for d in docs}
                    for doc_id in list(pending):
                        d = by_id.get(doc_id)
                        if d is None:
                            parse_fail.append((pending.pop(doc_id), "远端文档消失"))
                        elif d.get("run") == "DONE":
                            parse_ok += 1
                            pending.pop(doc_id)
                        elif d.get("run") == "FAIL":
                            parse_fail.append((pending.pop(doc_id), str(d.get("progress_msg") or "")[-300:]))
                    if pending:
                        out(f"  解析中…… 剩余 {len(pending)}")
                for doc_id, rel in pending.items():
                    parse_timeout.append(rel)

            out(f"解析成功：{parse_ok}  失败/超时：{len(parse_fail) + len(parse_timeout)}")
            for rel, msg in parse_fail:
                out(f"  [解析失败] docs/{rel}")
                out(f"    原因：{msg}")
            for rel in parse_timeout:
                out(f"  [解析超时] docs/{rel}（>{PARSE_TIMEOUT}s，可稍后重跑 sync）")
            failed = bool(parse_fail or parse_timeout)

        state["last_sync"] = now_iso()
        save_state(state)
        if not failed:
            out("")
            out("同步完成。")
    else:
        out("")
        out("Dry Run：未修改 RAGFlow 任何数据，state.json 未变更。")
    if failed:
        sys.exit(1)


def multipart_body(filename, content):
    boundary = "----ragflowsync" + uuid.uuid4().hex
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: text/markdown\r\n\r\n"
    ).encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
    return head + content + tail, f"multipart/form-data; boundary={boundary}"


def cmd_retrieve(args):
    cfg = load_config()
    client = require_client()
    data = client.request("POST", "/retrieval", json_body={
        "question": args.query,
        "dataset_ids": [cfg["dataset_id"]],
        "page_size": args.top or 5,
    })
    chunks = (data or {}).get("chunks", [])
    out(f"Retrieval：{args.query!r}（Dataset {cfg['dataset_name']}）命中 {len(chunks)} 条")
    for i, c in enumerate(chunks, 1):
        out("")
        out(f"[{i}] {c.get('document_keyword', '?')}  相似度 {c.get('similarity', '?')}")
        text = re.sub(r"\s+", " ", c.get("content", ""))[:260]
        out(f"    {text}")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="RAGFlow 子仓库知识库单向增量同步器")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="找回/创建本项目 Dataset 并写入 .ragflow/config.json（幂等）")
    sub.add_parser("status", help="查看服务器/Dataset/本地与远端同步状态")
    p_sync = sub.add_parser("sync", help="增量同步 docs/ 到 RAGFlow")
    p_sync.add_argument("--dry-run", action="store_true", help="只打印计划，不修改远端")
    p_ret = sub.add_parser("retrieve", help="检索测试（Retrieval API）")
    p_ret.add_argument("query")
    p_ret.add_argument("--top", type=int, default=5)
    args = ap.parse_args()
    try:
        {"init": cmd_init, "status": cmd_status, "sync": cmd_sync, "retrieve": cmd_retrieve}[args.cmd](args)
    except RagflowError as e:
        out(f"错误：{e}")
        sys.exit(1)
    except KeyboardInterrupt:
        out("\n已中断（已完成的步骤已写入 state.json，重跑 sync 会继续）")
        sys.exit(130)


if __name__ == "__main__":
    main()
