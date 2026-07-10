"""Real-ASGI-path regression tests for the multipart upload endpoints.

An earlier revision declared ``files: List[Any] | None = None`` on the route
signatures. FastAPI treats such a parameter as a JSON body field, so every
genuine multipart POST failed request validation with 422 before the
size-limited ``request.form()`` parser ever ran — while direct-call tests kept
passing. These tests drive the endpoints through the full ASGI stack with real
multipart bodies.
"""

from types import SimpleNamespace

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

import routes.upload_routes as up
from routes import personal_routes
from src.upload_handler import UploadHandler


def _app_with(router, auth_manager=None, user="alice"):
    app = FastAPI()

    @app.middleware("http")
    async def _stamp_user(request, call_next):
        # Stand-in for the auth middleware: routes read request.state.
        request.state.current_user = user
        return await call_next(request)

    if auth_manager is not None:
        app.state.auth_manager = auth_manager
    app.include_router(router)
    return app


# ── /api/upload (chat uploads) ───────────────────────────────────────────────


@pytest.fixture()
def chat_upload_client(tmp_path, monkeypatch):
    # Module-level router accumulates routes across setup calls; reset it.
    monkeypatch.setattr(up, "router", APIRouter(prefix="/api/upload", tags=["upload"]))
    handler = UploadHandler(base_dir=str(tmp_path), upload_dir=str(tmp_path / "uploads"))
    router, _cleanup = up.setup_upload_routes(handler)
    return TestClient(_app_with(router))


def test_chat_upload_accepts_real_multipart_post(chat_upload_client):
    response = chat_upload_client.post(
        "/api/upload",
        files=[
            ("files", ("a.txt", b"first upload body", "text/plain")),
            ("files", ("b.txt", b"second upload body", "text/plain")),
        ],
        data={"session_id": "sess-1"},
    )

    assert response.status_code == 200, response.text
    names = [f["name"] for f in response.json()["files"]]
    assert names == ["a.txt", "b.txt"]


def test_chat_upload_multipart_without_files_field_is_400_not_422(chat_upload_client):
    # A multipart body with a plain field but no "files" part.
    response = chat_upload_client.post(
        "/api/upload",
        files=[("session_id", (None, "sess-1"))],
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "No files uploaded"


# ── /api/personal/upload (RAG uploads) ───────────────────────────────────────


class _AuthManager:
    def __init__(self, privileges):
        self._privileges = privileges

    def get_privileges(self, user):
        return self._privileges


class _FakePersonalDocs:
    def add_directory(self, directory, index=False):
        pass


class _FakeRAG:
    def __init__(self):
        self.docs = []

    def _split_into_chunks(self, text, chunk_size=500):
        return [text]

    def add_document(self, chunk, metadata):
        self.docs.append((chunk, metadata))
        return True


def _personal_client(tmp_path, monkeypatch, privileges, rag):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setattr(personal_routes, "UPLOADS_DIR", str(tmp_path))
    monkeypatch.setattr(personal_routes, "get_rag_manager", lambda: rag)
    router = personal_routes.setup_personal_routes(_FakePersonalDocs(), None, True)
    return TestClient(_app_with(router, auth_manager=_AuthManager(privileges)))


def test_personal_upload_accepts_real_multipart_post(tmp_path, monkeypatch):
    rag = _FakeRAG()
    client = _personal_client(tmp_path, monkeypatch, {"can_use_documents": True}, rag)

    response = client.post(
        "/api/personal/upload",
        files=[("files", ("notes.txt", b"hello from multipart", "text/plain"))],
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["indexed_count"] == 1
    assert rag.docs[0][0] == "hello from multipart"


def test_personal_upload_rejects_unprivileged_multipart_with_403(tmp_path, monkeypatch):
    # 403 must win over any parsing outcome: authorization runs first.
    rag = SimpleNamespace()  # untouched; privilege gate fires before RAG lookup
    client = _personal_client(tmp_path, monkeypatch, {"can_use_documents": False}, rag)

    response = client.post(
        "/api/personal/upload",
        files=[("files", ("notes.txt", b"should never be parsed", "text/plain"))],
    )

    assert response.status_code == 403
