import pytest

from src.api_token_policy import api_token_route_allowed


@pytest.mark.parametrize(
    "path",
    [
        "/api/models",
        "/api/chat",
        "/api/chat_stream",
        "/api/chat/resume/session-1",
        "/api/session/session-1",
        "/api/sessions",
        "/api/history/session-1",
        "/api/inject_context/session-1",
        "/api/upload",
        "/api/presets/expand",
        "/api/search",
        "/api/rewrite",
        "/api/v1/chat",
        "/api/companion/models",
    ],
)
def test_chat_scope_allows_only_documented_chat_surface(path):
    assert api_token_route_allowed(path, ["chat"]) is True


@pytest.mark.parametrize(
    "path",
    [
        "/api/codex/capabilities",
        "/api/codex/todos",
        "/api/codex/documents",
        "/api/claude/plugin.zip",
        "/api/companion/ping",
        "/api/companion/info",
    ],
)
def test_dedicated_integration_routes_reach_their_endpoint_scope_checks(path):
    assert api_token_route_allowed(path, ["todos:read"]) is True


@pytest.mark.parametrize(
    "path",
    [
        "/api/auth/setup",
        "/api/auth/users",
        "/api/tokens",
        "/api/companion/pair",
        "/api/gallery/library",
        "/api/generated-image/image.png",
        "/api/email/messages",
        "/api/export",
        "/api/diagnostics/services",
        "/api/cookbook/state",
        "/api/activity/heartbeat",
        "/api/version",
        "/api/unknown-future-route",
    ],
)
def test_bearer_tokens_fail_closed_for_browser_admin_and_unknown_routes(path):
    assert api_token_route_allowed(path, ["chat", "todos:write"]) is False


def test_non_chat_scope_cannot_reach_owner_backed_chat_routes():
    assert api_token_route_allowed("/api/chat", ["todos:read"]) is False
    assert api_token_route_allowed("/api/session/session-1", []) is False


def test_path_normalization_does_not_turn_similar_prefixes_into_chat_routes():
    assert api_token_route_allowed("/api/chat/", ["chat"]) is True
    assert api_token_route_allowed("/api/chat-admin", ["chat"]) is False
    assert api_token_route_allowed("/api/session-secrets", ["chat"]) is False
