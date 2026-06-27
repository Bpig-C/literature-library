"""
API 集成测试：使用 FastAPI TestClient，不启动真实服务器。
Mock 掉 MinerU 和 LibreOffice，让任务立即完成。

运行：pytest tests/test_api.py -v

说明：
- TestClient 在同一进程内运行，所有 import 都真实执行
- mock_convert：让 Convert2PDF.convert 直接返回原路径（无需 LibreOffice）
- mock_mineru：让 push_task 立即触发回调，标记任务 succeeded
"""
import io
import json
import shutil
import sys
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent))

# 必须在 import app 之前 patch，否则 config.load() 会在模块级执行
from fastapi.testclient import TestClient

FIXTURE_JSON = Path(__file__).parent / "fixtures" / "sample_content_list.json"

# 测试用认证头（匹配 kAllowedApiClients）
AUTH = {"Client-ID": "test_client", "X-API-Key": "test_key"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def tmp_base(tmp_path_factory):
    """会话级临时目录，模拟 HX_2/ 根目录。"""
    return tmp_path_factory.mktemp("hx2_root")


@pytest.fixture(scope="session")
def client(tmp_base):
    """创建 TestClient，mock 掉所有外部依赖。"""

    # 1. mock BASE_DIR 指向临时目录
    import api.task_manage as tm_mod
    original_base = tm_mod.BASE_DIR

    tm_mod.BASE_DIR = tmp_base
    # routes_submit 也用 BASE_DIR，需要打补丁

    # 2. mock Convert2PDF.convert（直接返回原路径，不调用 LibreOffice）
    def fake_convert(file_path: Path) -> Path:
        file_path.touch()   # 确保文件存在
        return file_path

    with patch("api.services.parse_service.Convert2PDF.convert", side_effect=fake_convert):
        # 3. mock MinerU_OP：push_task 立即回调 succeeded
        from core.mineru.mineru_op import MinerU_OP

        original_push = MinerU_OP.push_task

        def instant_push(self, priority, path, callback, **kwargs):
            # 立即触发回调（成功）
            callback(True, str(path))

        MinerU_OP.push_task = instant_push

        from server.app import create_app
        app = create_app()

        with TestClient(app, raise_server_exceptions=True) as c:
            yield c

        MinerU_OP.push_task = original_push

    tm_mod.BASE_DIR = original_base


@pytest.fixture(scope="session")
def submitted_task(client, tmp_base):
    """提交一个测试文件，返回 task_id 和 file_path。
    同时在上传目录放好 content_list.json，让 result 接口可用。
    """
    # 假 PDF 内容（最小合法字节）
    fake_pdf_bytes = b"%PDF-1.4 fake content for testing"
    filename = "test_doc.pdf"

    resp = client.post(
        "/tools/api/v1/doc-content-extraction/submit",
        files={"files": (filename, io.BytesIO(fake_pdf_bytes), "application/pdf")},
        headers=AUTH,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    task_id = data["task_id"]

    # 把 content_list.json 放到上传目录，供 result 接口读取
    upload_dir = tmp_base / "Datas" / "uploads" / task_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    dst = upload_dir / "test_doc_content_list.json"
    shutil.copy(FIXTURE_JSON, dst)

    return task_id, data["file_path"]


# ---------------------------------------------------------------------------
# 测试：/health
# ---------------------------------------------------------------------------

def test_health_no_auth(client):
    """/health 不需要认证。"""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["code"] == 0


def test_health_with_auth(client):
    resp = client.get("/health", headers=AUTH)
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 测试：认证中间件
# ---------------------------------------------------------------------------

def test_auth_missing_headers(client):
    resp = client.get("/tools/api/v1/doc-content-extraction/status/fake123")
    assert resp.status_code == 401


def test_auth_wrong_key(client):
    resp = client.get(
        "/tools/api/v1/doc-content-extraction/status/fake123",
        headers={"Client-ID": "test_client", "X-API-Key": "wrong_key"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 测试：POST /submit
# ---------------------------------------------------------------------------

def test_submit_returns_task_id(client):
    resp = client.post(
        "/tools/api/v1/doc-content-extraction/submit",
        files={"files": ("doc.pdf", io.BytesIO(b"%PDF-test"), "application/pdf")},
        headers=AUTH,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert "task_id" in body["data"]
    assert "file_path" in body["data"]


def test_submit_idempotent(client):
    """相同文件两次提交，task_id 应相同。"""
    content = b"%PDF-idempotent-test"
    filename = "idempotent.pdf"

    def do_submit():
        return client.post(
            "/tools/api/v1/doc-content-extraction/submit",
            files={"files": (filename, io.BytesIO(content), "application/pdf")},
            headers=AUTH,
        )

    r1 = do_submit()
    r2 = do_submit()
    assert r1.json()["data"]["task_id"] == r2.json()["data"]["task_id"]


def test_submit_different_files_different_ids(client):
    r1 = client.post(
        "/tools/api/v1/doc-content-extraction/submit",
        files={"files": ("a.pdf", io.BytesIO(b"%PDF-aaaa"), "application/pdf")},
        headers=AUTH,
    )
    r2 = client.post(
        "/tools/api/v1/doc-content-extraction/submit",
        files={"files": ("b.pdf", io.BytesIO(b"%PDF-bbbb"), "application/pdf")},
        headers=AUTH,
    )
    assert r1.json()["data"]["task_id"] != r2.json()["data"]["task_id"]


def test_submit_html_marks_task_succeeded(client):
    from core.xml.xml_op import XML_OP

    original_push = XML_OP.push_task

    def instant_html_push(self, file_path, file_type, task_id, callback):
        assert file_type == "html"
        json_path = Path(file_path).with_suffix(".json")
        json_path.write_text(
            json.dumps([{"content_type": "text", "text": "hello html"}], ensure_ascii=False),
            encoding="utf-8",
        )
        callback(True, str(json_path), task_id)

    XML_OP.push_task = instant_html_push
    try:
        resp = client.post(
            "/tools/api/v1/doc-content-extraction/submit",
            files={"files": ("page.html", io.BytesIO(b"<html><body><p>hello</p></body></html>"), "text/html")},
            headers=AUTH,
        )
    finally:
        XML_OP.push_task = original_push

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]

    status_resp = client.get(
        f"/tools/api/v1/doc-content-extraction/status/{data['task_id']}",
        headers=AUTH,
    )
    assert status_resp.status_code == 200
    assert status_resp.json()["data"]["status"] == "succeeded"


def test_result_content_extraction_for_html(client):
    from core.xml.xml_op import XML_OP

    original_push = XML_OP.push_task

    def instant_html_push(self, file_path, file_type, task_id, callback):
        json_path = Path(file_path).with_suffix(".json")
        payload = [{"content_type": "text", "text": "hello html"}]
        json_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        callback(True, str(json_path), task_id)

    XML_OP.push_task = instant_html_push
    try:
        submit_resp = client.post(
            "/tools/api/v1/doc-content-extraction/submit",
            files={"files": ("page.html", io.BytesIO(b"<html><body><p>hello</p></body></html>"), "text/html")},
            headers=AUTH,
        )
    finally:
        XML_OP.push_task = original_push

    task_id = submit_resp.json()["data"]["task_id"]
    result_resp = client.get(
        f"/tools/api/v1/doc-content-extraction/result/{task_id}",
        headers=AUTH,
    )
    assert result_resp.status_code == 200
    assert result_resp.json()["data"]["data"] == [{"content_type": "text", "text": "hello html"}]


# ---------------------------------------------------------------------------
# 测试：GET /status
# ---------------------------------------------------------------------------

def test_status_succeeded(client, submitted_task):
    """push_task 被 mock 为立即成功，状态应为 succeeded。"""
    task_id, _ = submitted_task
    resp = client.get(
        f"/tools/api/v1/doc-content-extraction/status/{task_id}",
        headers=AUTH,
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["task_id"] == task_id
    assert data["status"] == "succeeded"
    assert data["time_create"] is not None


def test_status_not_found(client):
    resp = client.get(
        "/tools/api/v1/doc-content-extraction/status/nonexistent_task_id",
        headers=AUTH,
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 测试：GET /result
# ---------------------------------------------------------------------------

def test_result_content_extraction(client, submitted_task):
    task_id, _ = submitted_task
    resp = client.get(
        f"/tools/api/v1/doc-content-extraction/result/{task_id}",
        headers=AUTH,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    content_list = body["data"]["data"]
    assert isinstance(content_list, list)
    assert len(content_list) > 0
    # 每个条目有 content_type
    assert all("content_type" in e for e in content_list)


def test_result_layout_recognition(client, submitted_task):
    task_id, _ = submitted_task
    resp = client.get(
        f"/tools/api/v1/doc-layout-recognition/result/{task_id}",
        headers=AUTH,
    )
    assert resp.status_code == 200
    layout = resp.json()["data"]["data"]
    assert isinstance(layout, list)


def test_result_annotated_pdf_no_layout_file(client, submitted_task):
    """没有 _layout.pdf 时，success=False 但接口返回 200。"""
    task_id, _ = submitted_task
    resp = client.get(
        f"/tools/api/v1/doc-annotated-pdf/result/{task_id}",
        headers=AUTH,
    )
    assert resp.status_code == 200
    result = resp.json()["data"]["data"]
    assert result["success"] is False


def test_result_unknown_tool_id(client, submitted_task):
    task_id, _ = submitted_task
    resp = client.get(
        f"/tools/api/v1/unknown-tool/result/{task_id}",
        headers=AUTH,
    )
    assert resp.status_code == 400


def test_result_task_not_found(client):
    resp = client.get(
        "/tools/api/v1/doc-content-extraction/result/nonexistent",
        headers=AUTH,
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 测试：POST /run
# ---------------------------------------------------------------------------

def test_run_basic(client):
    resp = client.post(
        "/tools/api/v1/doc-content-extraction/run",
        json={"key": "value"},
        headers=AUTH,
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["tool_id"] == "doc-content-extraction"
    assert data["status"] == "running"
    assert data["accepts_arbitrary_tool_id"] is True


# ---------------------------------------------------------------------------
# Agent API
# ---------------------------------------------------------------------------

def test_agent_parse_returns_resource_urls(client):
    resp = client.post(
        "/api/v1/parse",
        files={"file": ("agent.pdf", io.BytesIO(b"%PDF-agent"), "application/pdf")},
        data={"metadata": json.dumps({"source": "test"})},
        headers=AUTH,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["status"] in ("pending", "succeeded")
    assert data["status_url"] == f"/api/v1/tasks/{data['task_id']}"
    assert data["result_url"].endswith("/result")
    assert data["package_url"].endswith("/artifacts/package")


def test_agent_status_includes_error_and_urls(client, submitted_task):
    task_id, _ = submitted_task
    resp = client.get(f"/api/v1/tasks/{task_id}", headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["task_id"] == task_id
    assert data["status"] == "succeeded"
    assert data["error"] == ""
    assert data["artifacts_url"].endswith("/artifacts")


def test_agent_result_content(client, submitted_task):
    task_id, _ = submitted_task
    resp = client.get(f"/api/v1/tasks/{task_id}/result?type=content", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["task_id"] == task_id
    assert body["type"] == "content"
    assert isinstance(body["result"], list)
    assert body["result"]


def test_agent_result_unknown_type(client, submitted_task):
    task_id, _ = submitted_task
    resp = client.get(f"/api/v1/tasks/{task_id}/result?type=unknown", headers=AUTH)
    assert resp.status_code == 400


def test_agent_artifacts_list_and_download(client, submitted_task):
    task_id, _ = submitted_task
    list_resp = client.get(f"/api/v1/tasks/{task_id}/artifacts", headers=AUTH)
    assert list_resp.status_code == 200
    files = list_resp.json()["data"]["files"]
    content_file = next(item for item in files if item["name"] == "test_doc_content_list.json")
    assert content_file["relative_path"] == "test_doc_content_list.json"

    file_resp = client.get(
        f"/api/v1/tasks/{task_id}/artifacts/file",
        params={"path": content_file["relative_path"]},
        headers=AUTH,
    )
    assert file_resp.status_code == 200
    assert isinstance(file_resp.json(), list)


def test_agent_artifact_path_traversal_blocked(client, submitted_task, tmp_base):
    task_id, _ = submitted_task
    secret = tmp_base / "Datas" / "uploads" / "secret.txt"
    secret.parent.mkdir(parents=True, exist_ok=True)
    secret.write_text("do not read", encoding="utf-8")

    resp = client.get(
        f"/api/v1/tasks/{task_id}/artifacts/file",
        params={"path": "../secret.txt"},
        headers=AUTH,
    )
    assert resp.status_code == 400


def test_agent_artifacts_package_dynamic_zip(client, submitted_task):
    task_id, _ = submitted_task
    resp = client.get(f"/api/v1/tasks/{task_id}/artifacts/package", headers=AUTH)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/zip")

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        assert "test_doc_content_list.json" in zf.namelist()


def test_failed_task_error_is_exposed(client):
    from core.mineru.mineru_op import MinerU_OP

    original_push = MinerU_OP.push_task

    def failing_push(self, priority, path, callback, **kwargs):
        callback(False, str(path), "mineru boom")

    MinerU_OP.push_task = failing_push
    try:
        resp = client.post(
            "/api/v1/parse",
            files={"file": ("failing.pdf", io.BytesIO(b"%PDF-failing"), "application/pdf")},
            headers=AUTH,
        )
    finally:
        MinerU_OP.push_task = original_push

    assert resp.status_code == 200, resp.text
    task_id = resp.json()["data"]["task_id"]

    status_resp = client.get(f"/api/v1/tasks/{task_id}", headers=AUTH)
    assert status_resp.status_code == 200
    data = status_resp.json()["data"]
    assert data["status"] == "failed"
    assert data["error"] == "mineru boom"


def test_openapi_available_without_auth_and_declares_headers(client):
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()
    schemes = schema["components"]["securitySchemes"]
    assert schemes["ClientID"]["name"] == "Client-ID"
    assert schemes["APIKey"]["name"] == "X-API-Key"
    assert schema["paths"]["/api/v1/parse"]["post"]["security"] == [{"ClientID": [], "APIKey": []}]
