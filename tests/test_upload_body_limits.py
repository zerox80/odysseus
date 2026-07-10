"""Regression coverage for pre-parser multipart upload limits."""

import json

import pytest

import src.upload_body_limits as limits


async def _run_asgi(app, *, path, headers, chunks):
    sent = []
    pending = list(chunks)

    async def receive():
        if pending:
            body = pending.pop(0)
            return {
                "type": "http.request",
                "body": body,
                "more_body": bool(pending),
            }
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": headers,
            "client": ("127.0.0.1", 1234),
            "server": ("testserver", 80),
        },
        receive,
        send,
    )
    return sent


@pytest.mark.anyio
async def test_content_length_is_rejected_before_downstream_parser(monkeypatch):
    called = False

    async def downstream(scope, receive, send):
        nonlocal called
        called = True
        await receive()

    monkeypatch.setattr(limits, "multipart_body_limit", lambda *_: 5)
    app = limits.UploadBodyLimitMiddleware(downstream)
    sent = await _run_asgi(
        app,
        path="/api/upload",
        headers=[
            (b"content-type", b"multipart/form-data; boundary=test"),
            (b"content-length", b"6"),
        ],
        chunks=[b"unused"],
    )

    assert not called
    assert sent[0]["status"] == 413
    assert json.loads(sent[1]["body"])["detail"].startswith("Multipart request")


@pytest.mark.anyio
async def test_chunked_body_is_cut_off_before_parser_can_spool_more(monkeypatch):
    reads = 0

    async def downstream(scope, receive, send):
        nonlocal reads
        while True:
            message = await receive()
            reads += 1
            if not message.get("more_body"):
                break

    monkeypatch.setattr(limits, "multipart_body_limit", lambda *_: 5)
    app = limits.UploadBodyLimitMiddleware(downstream)
    sent = await _run_asgi(
        app,
        path="/api/upload",
        headers=[(b"content-type", b"multipart/form-data; boundary=test")],
        chunks=[b"abc", b"def"],
    )

    assert reads == 1
    assert sent[0]["status"] == 413


@pytest.mark.anyio
async def test_route_parser_limits_are_explicit_per_upload_endpoint():
    class RequestStub:
        headers = {"content-type": "multipart/form-data; boundary=test"}

        def __init__(self):
            self.kwargs = None

        async def form(self, **kwargs):
            self.kwargs = kwargs
            return "parsed"

    request = RequestStub()
    assert await limits.parse_limited_multipart_form(request, max_files=3) == "parsed"
    assert request.kwargs == {
        "max_files": 3,
        "max_fields": limits.MAX_MULTIPART_FIELDS,
        "max_part_size": limits.MAX_MULTIPART_FIELD_BYTES,
    }
    assert limits.multipart_body_limit("/api/gallery/item/replace", "POST")
    assert limits.multipart_body_limit("/api/upload", "GET") is None
