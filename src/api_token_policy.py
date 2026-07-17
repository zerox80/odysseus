"""Deny-by-default route policy for bearer API tokens.

Bearer tokens are integration credentials, not browser sessions. Keep the
small set of integration namespaces here so adding a normal ``/api`` route can
never make it token-accessible by accident.
"""

from __future__ import annotations

from collections.abc import Iterable


def _normalized_scopes(scopes: Iterable[str] | str | None) -> set[str]:
    if isinstance(scopes, str):
        scopes = scopes.split(",")
    return {str(scope).strip() for scope in (scopes or ()) if str(scope).strip()}


def api_token_route_allowed(path: str, scopes: Iterable[str] | str | None) -> bool:
    """Return whether a bearer token may reach ``path``.

    The Codex namespace performs its finer read/write scope checks in each
    handler. All owner-backed browser/chat routes require the ``chat`` scope.
    Unknown routes fail closed.
    """
    normalized_path = (path or "/").rstrip("/") or "/"
    token_scopes = _normalized_scopes(scopes)

    # Dedicated integration routes with their own per-operation scope checks.
    if normalized_path == "/api/codex" or normalized_path.startswith("/api/codex/"):
        return True
    if normalized_path == "/api/claude/plugin.zip":
        return True

    # Authenticated discovery endpoints intentionally reveal only coarse
    # server identity/capabilities. Pairing is deliberately excluded.
    if normalized_path in {"/api/companion/ping", "/api/companion/info"}:
        return True

    if "chat" not in token_scopes:
        return False

    if normalized_path in {"/api/models", "/api/v1/chat", "/api/companion/models"}:
        return True

    # Owner-scoped chat surface used by paired clients.
    chat_prefixes = (
        "/api/session",
        "/api/sessions",
        "/api/history",
        "/api/chat",
        "/api/inject_context",
        "/api/upload",
        "/api/presets",
    )
    if any(
        normalized_path == prefix or normalized_path.startswith(prefix + "/")
        for prefix in chat_prefixes
    ):
        return True
    return normalized_path in {"/api/chat_stream", "/api/search", "/api/rewrite"}
