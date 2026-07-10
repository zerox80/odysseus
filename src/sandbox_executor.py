"""Fail-closed client for the isolated command-execution sidecar.

The application process must never execute model- or admin-supplied shell code
itself.  Commands are sent to a separately confined container which has only a
dedicated workspace mount and no Docker socket, SSH material, or application
environment.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any
from urllib.parse import urlsplit

import httpx


MAX_COMMAND_BYTES = 48 * 1024
MAX_TIMEOUT_SECONDS = 120
MAX_OUTPUT_CHARS = 200_000
_LOCAL_SOCKET_EXECUTE_URL = "http://tool-sandbox/execute"
_MAX_UNIX_SOCKET_PATH_BYTES = 100


class SandboxExecutorUnavailable(RuntimeError):
    """Raised when a command cannot be sent to the isolated executor."""


@dataclass(frozen=True)
class SandboxSettings:
    execute_url: str
    token: str
    socket_path: str | None = None


def _sandbox_settings() -> SandboxSettings:
    """Load a fail-closed executor transport configuration.

    Docker deployments use a Unix-domain socket so an untrusted command
    container never shares an IP network with the application.  A validated
    HTTP endpoint remains available only for intentionally configured native
    executors, where the deployer supplies an equivalent isolated transport.
    """

    raw_url = os.environ.get("ODYSSEUS_TOOL_SANDBOX_URL", "").strip()
    raw_socket = os.environ.get("ODYSSEUS_TOOL_SANDBOX_SOCKET", "").strip()
    token = os.environ.get("ODYSSEUS_TOOL_SANDBOX_TOKEN", "").strip()
    if not token:
        raise SandboxExecutorUnavailable(
            "The isolated tool executor is not configured; host command execution is disabled."
        )

    if raw_socket:
        # Linux AF_UNIX paths are deliberately accepted only in their normal
        # filesystem form.  This rejects abstract sockets and avoids a client
        # silently falling back to DNS/TCP because a malformed path was set.
        try:
            socket_path_bytes = raw_socket.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise SandboxExecutorUnavailable("Invalid isolated tool executor socket path.") from exc
        if (
            not raw_socket.startswith("/")
            or "\\" in raw_socket
            or "\x00" in raw_socket
            or len(socket_path_bytes) > _MAX_UNIX_SOCKET_PATH_BYTES
        ):
            raise SandboxExecutorUnavailable("Invalid isolated tool executor socket path.")
        return SandboxSettings(
            execute_url=_LOCAL_SOCKET_EXECUTE_URL,
            token=token,
            socket_path=raw_socket,
        )

    allowed_hosts = {
        host.strip().lower()
        for host in os.environ.get("ODYSSEUS_TOOL_SANDBOX_HOSTS", "").split(",")
        if host.strip()
    }
    if not raw_url or not allowed_hosts:
        raise SandboxExecutorUnavailable(
            "The isolated tool executor is not configured; host command execution is disabled."
        )

    parsed = urlsplit(raw_url)
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "http"
        or not host
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or host not in allowed_hosts
    ):
        raise SandboxExecutorUnavailable("Invalid isolated tool executor configuration.")
    return SandboxSettings(execute_url=raw_url.rstrip("/") + "/execute", token=token)


def _bounded_text(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise SandboxExecutorUnavailable(f"Isolated executor returned invalid {field}.")
    return value[:MAX_OUTPUT_CHARS]


def _safe_workdir(workdir: str) -> str:
    """Validate the sidecar-relative workspace directory wire format."""
    if not isinstance(workdir, str) or not workdir.strip():
        raise ValueError("Sandbox working directory must not be empty.")
    value = workdir.strip()
    if value == ".":
        return value
    if value.startswith("/") or "\\" in value:
        raise ValueError("Sandbox working directory must be a relative POSIX path.")
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("Sandbox working directory must stay below the workspace mount.")
    return value


async def execute_sandbox_command(
    command: str,
    *,
    timeout: int | float,
    workdir: str = ".",
) -> dict[str, Any]:
    """Execute *command* only in the configured isolated sidecar.

    There deliberately is no development or host-process fallback.  A missing
    sidecar is an explicit, safe failure rather than an opportunity to regain
    the application's filesystem, network credentials, or process identity.
    """

    if not isinstance(command, str) or not command.strip():
        raise ValueError("Command must not be empty.")
    if len(command.encode("utf-8")) > MAX_COMMAND_BYTES:
        raise ValueError(f"Command exceeds the {MAX_COMMAND_BYTES}-byte limit.")
    safe_workdir = _safe_workdir(workdir)

    settings = _sandbox_settings()
    try:
        requested_timeout = int(timeout)
    except (TypeError, ValueError) as exc:
        raise ValueError("Command timeout must be an integer.") from exc
    safe_timeout = max(1, min(requested_timeout, MAX_TIMEOUT_SECONDS))

    try:
        transport = (
            httpx.AsyncHTTPTransport(uds=settings.socket_path)
            if settings.socket_path is not None
            else None
        )
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(safe_timeout + 5),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        ) as client:
            response = await client.post(
                settings.execute_url,
                headers={"X-Odysseus-Sandbox-Token": settings.token},
                json={"command": command, "timeout": safe_timeout, "workdir": safe_workdir},
            )
    except httpx.HTTPError as exc:
        raise SandboxExecutorUnavailable("Isolated tool executor is unavailable.") from exc

    if response.status_code != 200:
        raise SandboxExecutorUnavailable(
            f"Isolated tool executor rejected the command ({response.status_code})."
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise SandboxExecutorUnavailable("Isolated tool executor returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise SandboxExecutorUnavailable("Isolated tool executor returned an invalid response.")
    exit_code = payload.get("exit_code")
    if not isinstance(exit_code, int):
        raise SandboxExecutorUnavailable("Isolated tool executor returned an invalid exit code.")
    return {
        "stdout": _bounded_text(payload.get("stdout", ""), "stdout"),
        "stderr": _bounded_text(payload.get("stderr", ""), "stderr"),
        "exit_code": exit_code,
        "timed_out": bool(payload.get("timed_out", False)),
    }
