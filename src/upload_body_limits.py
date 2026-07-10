"""ASGI and multipart limits that apply *before* upload files are spooled.

FastAPI resolves ``File(...)`` arguments only after Starlette has parsed the
multipart body.  Route-local ``UploadFile.read(limit + 1)`` checks are still
useful for defence in depth, but are too late to protect temporary storage.
This module puts a byte ceiling around known upload routes at the ASGI receive
boundary and supplies the small per-route parser limits used by those routes.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

from fastapi import HTTPException, Request
from starlette.datastructures import FormData
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.upload_limits import (
    EMAIL_COMPOSE_UPLOAD_MAX_BYTES,
    GALLERY_TRANSFORM_UPLOAD_MAX_BYTES,
    GALLERY_UPLOAD_MAX_BYTES,
    ICS_MAX_BYTES,
    MEMORY_IMPORT_MAX_BYTES,
    PERSONAL_UPLOAD_MAX_BYTES,
    STT_MAX_AUDIO_BYTES,
    get_chat_upload_max_bytes,
)

# Account for multipart boundaries, filenames and the small textual fields on
# each route.  This is deliberately separate from an individual file cap:
# applications must be able to upload the declared number of files without a
# surprise rejection caused by multipart framing.
MULTIPART_OVERHEAD_BYTES = int(
    os.getenv("ODYSSEUS_MULTIPART_OVERHEAD_BYTES", str(1024 * 1024))
)
MAX_MULTIPART_FIELDS = int(os.getenv("ODYSSEUS_MAX_MULTIPART_FIELDS", "32"))
MAX_MULTIPART_FIELD_BYTES = int(
    os.getenv("ODYSSEUS_MAX_MULTIPART_FIELD_BYTES", str(256 * 1024))
)
MAX_CHAT_UPLOAD_FILES = int(os.getenv("ODYSSEUS_MAX_CHAT_UPLOAD_FILES", "10"))
MAX_PERSONAL_UPLOAD_FILES = int(
    os.getenv("ODYSSEUS_MAX_PERSONAL_UPLOAD_FILES", "10")
)

for _name, _value in {
    "ODYSSEUS_MULTIPART_OVERHEAD_BYTES": MULTIPART_OVERHEAD_BYTES,
    "ODYSSEUS_MAX_MULTIPART_FIELDS": MAX_MULTIPART_FIELDS,
    "ODYSSEUS_MAX_MULTIPART_FIELD_BYTES": MAX_MULTIPART_FIELD_BYTES,
    "ODYSSEUS_MAX_CHAT_UPLOAD_FILES": MAX_CHAT_UPLOAD_FILES,
    "ODYSSEUS_MAX_PERSONAL_UPLOAD_FILES": MAX_PERSONAL_UPLOAD_FILES,
}.items():
    if _value < 1:
        raise ValueError(f"{_name} must be greater than 0")


def _with_overhead(file_bytes: int) -> int:
    return file_bytes + MULTIPART_OVERHEAD_BYTES


def multipart_body_limit(path: str, method: str) -> Optional[int]:
    """Return the pre-parser body limit for a known multipart upload route."""
    if method.upper() != "POST":
        return None
    path = (path or "/").rstrip("/") or "/"
    chat_limit = get_chat_upload_max_bytes()
    exact_limits = {
        "/api/upload": _with_overhead(chat_limit * MAX_CHAT_UPLOAD_FILES),
        "/api/documents/import-pdf": _with_overhead(chat_limit),
        "/api/memory/import": _with_overhead(MEMORY_IMPORT_MAX_BYTES),
        "/api/personal/upload": _with_overhead(
            PERSONAL_UPLOAD_MAX_BYTES * MAX_PERSONAL_UPLOAD_FILES
        ),
        "/api/stt/transcribe": _with_overhead(STT_MAX_AUDIO_BYTES),
        "/api/calendar/import": _with_overhead(ICS_MAX_BYTES),
        "/api/email/compose-upload": _with_overhead(EMAIL_COMPOSE_UPLOAD_MAX_BYTES),
        "/api/gallery/upload": _with_overhead(GALLERY_UPLOAD_MAX_BYTES),
        "/api/gallery/ai-upscale": _with_overhead(GALLERY_TRANSFORM_UPLOAD_MAX_BYTES),
        "/api/gallery/style-transfer": _with_overhead(
            GALLERY_TRANSFORM_UPLOAD_MAX_BYTES
        ),
    }
    if path in exact_limits:
        return exact_limits[path]
    if path.startswith("/api/gallery/") and path.endswith("/replace"):
        return _with_overhead(GALLERY_UPLOAD_MAX_BYTES)
    return None


def _is_multipart(scope: Scope) -> bool:
    headers = dict(scope.get("headers") or [])
    content_type = headers.get(b"content-type", b"").decode(
        "latin-1", errors="ignore"
    )
    return content_type.lower().startswith("multipart/form-data")


def _content_length(scope: Scope) -> Optional[int]:
    headers = dict(scope.get("headers") or [])
    raw = headers.get(b"content-length")
    if not raw:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


class _BodyLimitExceeded(Exception):
    pass


async def _send_payload_too_large(send: Send, limit: int) -> None:
    payload = json.dumps(
        {"detail": f"Multipart request exceeds the {limit} byte route limit"}
    ).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(payload)).encode("ascii")),
                # The server has intentionally stopped consuming this body.
                (b"connection", b"close"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": payload, "more_body": False})


class UploadBodyLimitMiddleware:
    """Reject oversized multipart requests while ASGI is still receiving them."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http" or not _is_multipart(scope):
            await self.app(scope, receive, send)
            return

        limit = multipart_body_limit(
            str(scope.get("path") or ""), str(scope.get("method") or "")
        )
        if limit is None:
            await self.app(scope, receive, send)
            return

        content_length = _content_length(scope)
        if content_length is not None and content_length > limit:
            await _send_payload_too_large(send, limit)
            return

        received = 0
        response_started = False

        async def receive_limited() -> Message:
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _BodyLimitExceeded
            return message

        async def send_tracking(message: Message) -> None:
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive_limited, send_tracking)
        except _BodyLimitExceeded:
            # A parser asks for body bytes before it sends a response, so this
            # should be the normal branch.  Never emit a second HTTP response
            # if an application has already started one, however.
            if not response_started:
                await _send_payload_too_large(send, limit)


async def parse_limited_multipart_form(request: Request, *, max_files: int) -> FormData:
    """Parse multipart data with small per-route part and field ceilings.

    The ASGI middleware bounds uploaded *file* bytes before Starlette spools
    them.  These parser settings bound the count and size of metadata fields,
    preventing a small-body multipart request from using excessive parser work.
    """
    if max_files < 1:
        raise ValueError("max_files must be greater than 0")
    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("multipart/form-data"):
        raise HTTPException(status_code=415, detail="Expected multipart/form-data")
    return await request.form(
        max_files=max_files,
        max_fields=MAX_MULTIPART_FIELDS,
        max_part_size=MAX_MULTIPART_FIELD_BYTES,
    )


def uploaded_values(form: FormData, field: str) -> list[Any]:
    """Return only file-like values for one multipart field name."""
    return [value for value in form.getlist(field) if hasattr(value, "read")]
