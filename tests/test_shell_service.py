import importlib.util
from pathlib import Path


_SERVICE_PATH = Path(__file__).resolve().parents[1] / "services" / "shell" / "service.py"
_SPEC = importlib.util.spec_from_file_location("_shell_service_under_test", _SERVICE_PATH)
shell_service = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(shell_service)
ShellService = shell_service.ShellService


async def test_shell_stream_uses_isolated_executor(monkeypatch):
    calls = []

    async def fake_execute(command, *, timeout, workdir):
        calls.append((command, timeout, workdir))
        return {"stdout": "hello\n", "stderr": "warning\n", "exit_code": 0, "timed_out": False}

    monkeypatch.setattr(shell_service, "execute_sandbox_command", fake_execute)
    monkeypatch.setattr(shell_service, "sandbox_workdir", lambda: ".")

    async def collect_events():
        service = ShellService()
        return [event async for event in service.stream("unused", timeout=5)]

    events = await collect_events()

    assert events == [
        {"stream": "stdout", "data": "hello"},
        {"stream": "stderr", "data": "warning"},
        {"exit_code": 0},
    ]
    assert calls == [("unused", 5, ".")]
