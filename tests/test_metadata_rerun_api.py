"""UX-004: Metadata rerun API endpoints tests.

覆盖 3 个新端点:
- POST /{ext_id}/rerun-preview (预览，不写DB)
- POST /{ext_id}/rerun-apply (确认，写入DB)
- GET /{ext_id}/rerun-prompt (降级方案)
"""

from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient


# ============================================================
# Fixtures (复用 conftest.py 的 sample_db)
# ============================================================

@pytest.fixture
def client(sample_db, monkeypatch):
    """创建使用临时 sample DB 的 FastAPI TestClient。"""
    import api.db as db

    monkeypatch.setattr(db, "DB_PATH", sample_db)
    from api.main import app
    return TestClient(app)


@pytest.fixture
def sample_extraction(client):
    """创建一个有完整 extracted_json 的 extraction 记录用于 rerun 测试。"""
    import tempfile
    from pathlib import Path

    # 使用函数级唯一 ID（避免跨测试冲突）
    import uuid
    uid = uuid.uuid4().hex[:8]
    ext_id = f"ME-rerun-{uid}"
    work_id = f"W-rerun-{uid}"

    # 创建临时的 content.md 文件
    tmp_dir = Path(tempfile.mkdtemp())
    content_file = tmp_dir / "content.md"
    content_file.write_text(
        "This is a test paper about AI safety.\n"
        "Title: Original Title\nAuthors: John Doe\nAbstract: This is the original abstract.",
        encoding="utf-8",
    )

    # 直接操作数据库：先插入 work（extraction_by_id 需要 JOIN works）
    import sqlite3
    from api.db import DB_PATH
    conn = sqlite3.connect(str(DB_PATH))
    try:
        # 插入 work（INSERT OR IGNORE 避免重复）
        conn.execute("""
            INSERT OR IGNORE INTO works (id, title, authors, year, doc_type)
            VALUES (?, ?, ?, ?, ?)
        """, (work_id, "Rerun Test Paper", json.dumps(["Test Author"]), 2024, "paper"))

        # 插入 extraction
        ext_data = {
            "id": ext_id,
            "work_id": work_id,
            "model_name": "test-model",
            "content_md_path": str(content_file),
            "input_chars": 1000,
            "input_tokens_est": 250,
            "raw_response": '{"title": "Original Title"}',
            "extracted_json": {
                "title": "Original Title",
                "title_zh": "原始标题",
                "date": {"year": 2024, "month": 1, "day": 1},
                "authors": [{"name": "John Doe"}],
                "author_count": 1,
                "institutions": [{"name": "Test University"}],
                "doi": "10.1234/test",
                "arxiv_id": "2401.12345",
                "venue": "Test Conference",
                "url": "https://example.com/paper",
                "abstract": "This is the original abstract.",
                "evidence": {"title": "from title section", "abstract": "from abstract section"},
                "confidence": {"title": "high", "abstract": "medium"},
                "missing": [],
            },
            "confidence_json": {"title": "high", "abstract": "medium"},
            "review_status": "pending",
            "risk_level": "low",
            "risk_score": 5,
            "risk_reasons": [],
            "review_note": "",
            "created_at": "2026-07-03T10:00:00+00:00",
        }

        conn.execute("""
            INSERT INTO metadata_extractions
            (id, work_id, model_name, content_md_path, input_chars, input_tokens_est,
             raw_response, extracted_json, confidence_json, applied,
             applied_at, created_at, review_status, review_note, reviewed_at,
             risk_level, risk_score, risk_reasons, review_source,
             fix_action, superseded_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, ?, ?, ?, NULL, ?, ?, ?, 'human', '', '')
        """, (
            ext_data["id"], ext_data["work_id"], ext_data["model_name"],
            ext_data["content_md_path"], ext_data["input_chars"], ext_data["input_tokens_est"],
            ext_data["raw_response"],
            json.dumps(ext_data["extracted_json"], ensure_ascii=False),
            json.dumps(ext_data["confidence_json"], ensure_ascii=False),
            ext_data["created_at"],
            ext_data["review_status"], ext_data["review_note"],
            ext_data["risk_level"], ext_data["risk_score"],
            json.dumps(ext_data["risk_reasons"]),
        ))
        conn.commit()
    finally:
        conn.close()

    return ext_data


# ============================================================
# POST /{ext_id}/rerun-preview 测试
# ============================================================

class TestRerunPreviewEndpoint:
    """POST /api/metadata/{ext_id}/rerun-preview (不写DB)"""

    def test_preview_missing_ext_id(self, client):
        """404: extraction 不存在"""
        res = client.post("/api/metadata/NONEXIST/rerun-preview", json={"fields": ["title"]})
        assert res.status_code == 404
        assert "not found" in res.json()["detail"].lower()

    def test_preview_invalid_field(self, client):
        """400: 字段不在白名单"""
        res = client.post("/api/metadata/ME-test/rerun-preview", json={"fields": ["invalid_field"]})
        assert res.status_code == 400
        assert "Invalid fields" in res.json()["detail"]

    def test_preview_empty_fields(self, client):
        """400: fields 为空列表"""
        res = client.post("/api/metadata/ME-test/rerun-preview", json={"fields": []})
        assert res.status_code == 400
        assert "non-empty" in res.json()["detail"].lower()

    @patch("scripts.llm_judge.chat")
    def test_preview_success_single_field(self, mock_chat, client, sample_extraction):
        """200: 成功预览单个字段，返回 diff 数据结构正确"""
        mock_llm_response = {
            "message": {
                "content": json.dumps({
                    "title": "New Rerun Title",
                    "authors": [],
                    "abstract": "Updated abstract text.",
                    "evidence": {"title": "evidence for new title"},
                    "confidence": {"title": "high"},
                    "missing": [],
                })
            }
        }
        mock_chat.return_value = mock_llm_response

        res = client.post(f"/api/metadata/{sample_extraction['id']}/rerun-preview", json={
            "fields": ["title"],
            "review_note": "测试重抽预览"
        })

        assert res.status_code == 200
        data = res.json()

        # 验证返回结构完整性
        assert "preview_id" in data
        assert data["preview_id"].startswith("ME-")
        assert data["fields"] == ["title"]
        assert "diff" in data
        assert "new_extraction" in data
        assert "risk" in data

        # 验证 diff 结构
        assert "title" in data["diff"]
        diff_title = data["diff"]["title"]
        assert "old" in diff_title
        assert "new" in diff_title
        assert "changed" in diff_title
        assert diff_title["old"] == "Original Title"  # 原值
        assert diff_title["new"] == "New Rerun Title"  # 新值（来自 mock LLM）
        assert diff_title["changed"] is True  # 应该标记为已变更

    @patch("scripts.llm_judge.chat")
    def test_preview_multiple_fields(self, mock_chat, client, sample_extraction):
        """200: 同时预览多个字段"""
        mock_chat.return_value = {
            "message": {
                "content": json.dumps({
                    "title": "Multi New Title",
                    "abstract": "Multi new abstract",
                    "authors": [],
                    "evidence": {},
                    "confidence": {},
                    "missing": [],
                })
            }
        }

        res = client.post(f"/api/metadata/{sample_extraction['id']}/rerun-preview", json={
            "fields": ["title", "abstract"]
        })

        assert res.status_code == 200
        data = res.json()
        assert len(data["diff"]) == 2
        assert "title" in data["diff"]
        assert "abstract" in data["diff"]

    @patch("scripts.llm_judge.chat")
    def test_preview_includes_risk_info(self, mock_chat, client, sample_extraction):
        """200: 返回数据包含风险等级信息"""
        mock_chat.return_value = {
            "message": {
                "content": json.dumps({
                    "title": "Risk Test Title",
                    "authors": [],
                    "evidence": {},
                    "confidence": {},
                    "missing": [],
                })
            }
        }

        res = client.post(f"/api/metadata/{sample_extraction['id']}/rerun-preview", json={
            "fields": ["title"]
        })

        assert res.status_code == 200
        risk = res.json()["risk"]
        assert "risk_level" in risk
        assert "risk_score" in risk
        assert "risk_reasons" in risk
        assert risk["risk_level"] in ("low", "medium", "high")


# ============================================================
# POST /{ext_id}/rerun-apply 测试
# ============================================================

class TestRerunApplyEndpoint:
    """POST /api/metadata/{ext_id}/rerun-apply (确认写入DB)"""

    def test_apply_missing_ext_id(self, client):
        """404: 原记录不存在"""
        fake_new_ext = {
            "id": "ME-fake-new",
            "work_id": "W-nonexist",
            "model_name": "test",
            "content_md_path": "/fake/content.md",
            "input_chars": 100,
            "input_tokens_est": 25,
            "raw_response": "{}",
            "extracted_json": {},
            "confidence_json": {},
            "risk": {"risk_level": "low", "risk_score": 0, "risk_reasons": []},
            "review_note": "test apply",
            "created_at": "2026-07-03T10:00:00+00:00",
            "fields": ["title"],
        }
        res = client.post("/api/metadata/NONEXIST/rerun-apply", json={
            "preview_id": "ME-fake-new",
            "new_extraction": fake_new_ext,
        })
        assert res.status_code == 404

    def test_apply_success_and_supersede(self, client, sample_extraction):
        """200: 成功写入 DB，旧记录被标记 superseded_by"""
        # 构造合法的 new_extraction（模拟 preview 返回的数据）
        new_id = f"ME-apply-{sample_extraction['id']}"
        new_ext = {
            "id": new_id,
            "old_id": sample_extraction["id"],  # write_superseding_extraction 需要此字段
            "work_id": sample_extraction["work_id"],
            "model_name": "test-model-v2",
            "content_md_path": sample_extraction["content_md_path"],
            "input_chars": 1200,
            "input_tokens_est": 300,
            "raw_response": '{"title": "Applied Title"}',
            "extracted_json": {
                **(sample_extraction.get("extracted_json") or {}),
                "title": "Applied After Review",  # 新值
            },
            "confidence_json": {
                **(sample_extraction.get("confidence_json") or {}),
                "title": "high",  # 更新的置信度
            },
            "risk": {"risk_level": "low", "risk_score": 3, "risk_reasons": []},
            "review_note": f"rerun from {sample_extraction['id']}; fields=title",
            "created_at": "2026-07-03T11:00:00+00:00",
            "fields": ["title"],
        }

        res = client.post(f"/api/metadata/{sample_extraction['id']}/rerun-apply", json={
            "preview_id": new_id,
            "new_extraction": new_ext,
        })

        assert res.status_code == 200
        data = res.json()
        assert data["id"] == new_id
        assert data["extracted_json"]["title"] == "Applied After Review"

        # 验证旧记录被 supersede
        import sqlite3
        from api.db import DB_PATH
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        old_record = conn.execute(
            "SELECT superseded_by FROM metadata_extractions WHERE id = ?",
            (sample_extraction["id"],)
        ).fetchone()
        conn.close()

        assert old_record is not None
        assert old_record["superseded_by"] == new_id


# ============================================================
# GET /{ext_id}/rerun-prompt 测试
# ============================================================

class TestGetRerunPromptEndpoint:
    """GET /api/metadata/{ext_id}/rerun-prompt (降级方案)"""

    def test_prompt_missing_ext_id(self, client):
        """404: extraction 不存在"""
        res = client.get("/api/metadata/NONEXIST/rerun-prompt?fields=title")
        assert res.status_code == 404

    def test_prompt_invalid_fields(self, client):
        """400: 字段不在白名单"""
        res = client.get("/api/metadata/ME-test/rerun-prompt?fields=invalid_field")
        assert res.status_code == 400
        assert "Invalid fields" in res.json()["detail"]

    def test_prompt_empty_fields(self, client):
        """400: fields 参数为空"""
        res = client.get("/api/metadata/ME-test/rerun-prompt?fields=")
        assert res.status_code == 400

    def test_prompt_success(self, client, sample_extraction):
        """200: 成功生成 prompt，返回结构正确"""
        res = client.get(f"/api/metadata/{sample_extraction['id']}/rerun-prompt?fields=title,abstract")

        assert res.status_code == 200
        data = res.json()

        # 验证必要字段存在
        assert "prompt" in data
        assert len(data["prompt"]) > 0
        assert data["fields"] == ["title", "abstract"]
        assert "content_chars" in data
        assert "content_preview" in data

        # 验证 prompt 包含关键字段
        assert "title" in data["prompt"].lower() or "Focus especially" in data["prompt"]
        assert data["content_chars"] > 0

    def test_prompt_content_preview_truncated(self, client, sample_extraction):
        """200: content_preview 截断到 500 字符以内"""
        res = client.get(f"/api/metadata/{sample_extraction['id']}/rerun-prompt?fields=title")

        assert res.status_code == 200
        preview_len = len(res.json()["content_preview"])
        assert preview_len <= 500

    def test_prompt_single_field(self, client, sample_extraction):
        """200: 单字段 prompt 也正常工作"""
        res = client.get(f"/api/metadata/{sample_extraction['id']}/rerun-prompt?fields=title")

        assert res.status_code == 200
        data = res.json()
        assert data["fields"] == ["title"]
        assert "title" in data["prompt"] or "Focus especially on these fields" in data["prompt"]

    def test_prompt_uses_review_note_query(self, client, sample_extraction):
        """200: 降级 prompt 使用当前页面传入的审核备注"""
        note = "prefer the title from the abstract heading"
        res = client.get(
            f"/api/metadata/{sample_extraction['id']}/rerun-prompt",
            params={"fields": "title", "review_note": note},
        )

        assert res.status_code == 200
        assert note in res.json()["prompt"]
