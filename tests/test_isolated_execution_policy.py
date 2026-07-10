"""Regression coverage for fail-closed command-execution boundaries."""

from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_background_marker_is_rejected_before_any_host_launcher(monkeypatch):
    import src.tool_execution as tool_execution

    monkeypatch.setattr(tool_execution, "_owner_is_admin", lambda _owner: True)
    monkeypatch.setattr(tool_execution, "is_public_blocked_tool", lambda _tool: False)

    desc, result = await tool_execution.execute_tool_block(
        SimpleNamespace(tool_type="bash", content="#!bg\necho should-not-run-detached"),
        owner="admin",
        session_id="chat-1",
    )

    assert desc == "bash (background): BLOCKED"
    assert result["exit_code"] == 125
    assert "Detached background commands" in result["error"]


def test_legacy_background_launcher_fails_closed():
    from src import bg_jobs

    with pytest.raises(RuntimeError, match="Detached background jobs are disabled"):
        bg_jobs.launch("echo should-not-run", session_id="chat-1")


@pytest.mark.asyncio
async def test_scheduled_local_action_uses_isolated_executor(monkeypatch):
    from src import builtin_actions
    import src.sandbox_executor as sandbox_executor
    import src.tool_execution as tool_execution

    calls = []

    async def fake_execute(command, *, timeout, workdir):
        calls.append((command, timeout, workdir))
        return {"stdout": "ok", "stderr": "", "exit_code": 0, "timed_out": False}

    monkeypatch.setattr(sandbox_executor, "execute_sandbox_command", fake_execute)
    monkeypatch.setattr(tool_execution, "sandbox_workdir", lambda: ".")

    output, succeeded = await builtin_actions.action_run_local("admin", script="echo ok")

    assert succeeded is True
    assert output == "ok"
    assert calls == [("echo ok", 120, ".")]


@pytest.mark.asyncio
async def test_scheduled_remote_action_is_rejected_without_ssh(monkeypatch):
    from src import builtin_actions

    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("remote command execution must not be attempted")

    monkeypatch.setattr(builtin_actions, "_run_isolated_command", fail_if_called)
    output, succeeded = await builtin_actions.action_ssh_command(
        "admin", command="id", host="ops.example.test"
    )

    assert succeeded is False
    assert "Remote SSH task actions are disabled" in output


@pytest.mark.asyncio
async def test_model_host_operations_are_disabled_without_explicit_opt_in(monkeypatch):
    import src.tool_execution as tool_execution

    monkeypatch.delenv("ODYSSEUS_ENABLE_HIGH_TRUST_COOKBOOK", raising=False)
    monkeypatch.setattr(tool_execution, "_owner_is_admin", lambda _owner: True)
    monkeypatch.setattr(tool_execution, "is_public_blocked_tool", lambda _tool: False)

    desc, result = await tool_execution.execute_tool_block(
        SimpleNamespace(tool_type="serve_model", content='{"model": "example/model"}'),
        owner="admin",
        session_id="chat-1",
    )

    assert desc == "serve_model: BLOCKED"
    assert result["exit_code"] == 1
    assert "ODYSSEUS_ENABLE_HIGH_TRUST_COOKBOOK=true" in result["error"]


def test_high_trust_cookbook_flag_requires_exact_true_value():
    from src.high_trust_operations import high_trust_cookbook_enabled

    assert high_trust_cookbook_enabled(environ={}) is False
    assert high_trust_cookbook_enabled(environ={"ODYSSEUS_ENABLE_HIGH_TRUST_COOKBOOK": "yes"}) is False
    assert high_trust_cookbook_enabled(environ={"ODYSSEUS_ENABLE_HIGH_TRUST_COOKBOOK": "true"}) is True


@pytest.mark.asyncio
async def test_unix_socket_executor_transport_never_uses_configured_network_url(monkeypatch):
    import src.sandbox_executor as sandbox_executor

    captured = {}
    sentinel_transport = object()

    def fake_transport(*, uds):
        captured["uds"] = uds
        return sentinel_transport

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"stdout": "ok", "stderr": "", "exit_code": 0, "timed_out": False}

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url, **kwargs):
            captured["post_url"] = url
            captured["post_kwargs"] = kwargs
            return FakeResponse()

    monkeypatch.setenv("ODYSSEUS_TOOL_SANDBOX_TOKEN", "test-token")
    monkeypatch.setenv("ODYSSEUS_TOOL_SANDBOX_SOCKET", "/run/odysseus-sandbox/executor.sock")
    # A hostile/misconfigured TCP URL must be ignored whenever the private
    # socket transport is present.
    monkeypatch.setenv("ODYSSEUS_TOOL_SANDBOX_URL", "http://untrusted.example:8081")
    monkeypatch.setenv("ODYSSEUS_TOOL_SANDBOX_HOSTS", "untrusted.example")
    monkeypatch.setattr(sandbox_executor.httpx, "AsyncHTTPTransport", fake_transport)
    monkeypatch.setattr(sandbox_executor.httpx, "AsyncClient", FakeClient)

    result = await sandbox_executor.execute_sandbox_command("echo ok", timeout=10)

    assert result["exit_code"] == 0
    assert captured["uds"] == "/run/odysseus-sandbox/executor.sock"
    assert captured["client_kwargs"]["transport"] is sentinel_transport
    assert captured["client_kwargs"]["trust_env"] is False
    assert captured["post_url"] == "http://tool-sandbox/execute"


@pytest.mark.parametrize("socket_path", ["relative.sock", r"C:\\executor.sock", "/" + "x" * 101])
def test_unix_socket_executor_rejects_unsafe_socket_paths(monkeypatch, socket_path):
    import src.sandbox_executor as sandbox_executor

    monkeypatch.setenv("ODYSSEUS_TOOL_SANDBOX_TOKEN", "test-token")
    monkeypatch.setenv("ODYSSEUS_TOOL_SANDBOX_SOCKET", socket_path)

    with pytest.raises(sandbox_executor.SandboxExecutorUnavailable, match="socket path"):
        sandbox_executor._sandbox_settings()


def test_default_compose_executor_uses_private_socket_without_an_ip_network():
    from pathlib import Path

    import yaml

    compose_path = Path(__file__).resolve().parents[1] / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    app = compose["services"]["odysseus"]
    sandbox = compose["services"]["tool-sandbox"]

    assert sandbox["network_mode"] == "none"
    assert "networks" not in sandbox
    assert "ports" not in sandbox
    assert "tool-sandbox-socket:/run/odysseus-sandbox:rw" in sandbox["volumes"]
    assert "tool-sandbox-socket:/run/odysseus-sandbox:ro" in app["volumes"]
    assert "ODYSSEUS_TOOL_SANDBOX_SOCKET=/run/odysseus-sandbox/executor.sock" in app["environment"]
    assert "ODYSSEUS_TOOL_SANDBOX_URL=http://tool-sandbox:8081" not in app["environment"]


@pytest.mark.asyncio
async def test_cookbook_host_inspection_routes_require_explicit_opt_in(monkeypatch):
    import routes.cookbook_routes as cookbook_routes
    from fastapi import HTTPException

    monkeypatch.delenv("ODYSSEUS_ENABLE_HIGH_TRUST_COOKBOOK", raising=False)
    monkeypatch.setattr(cookbook_routes, "require_admin", lambda _request: None)
    router = cookbook_routes.setup_cookbook_routes()

    for path in ("/api/model/cached", "/api/cookbook/gpus", "/api/cookbook/tasks/status"):
        endpoint = next(route.endpoint for route in router.routes if route.path == path)
        with pytest.raises(HTTPException) as exc:
            await endpoint(object())
        assert exc.value.status_code == 403
        assert "ODYSSEUS_ENABLE_HIGH_TRUST_COOKBOOK=true" in str(exc.value.detail)
