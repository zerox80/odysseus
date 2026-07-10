"""Tiny authenticated command executor for the isolated tool-sandbox image.

This service intentionally uses only the standard library.  Container runtime
policy is the primary isolation boundary; the in-process limits below provide a
second line of defense against accidental resource exhaustion inside it.
"""

from __future__ import annotations

import hmac
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import signal
import socketserver
import stat
import subprocess
import threading
from typing import BinaryIO

try:  # The image is Linux, but keeping this guarded makes the module importable.
    import resource
except ImportError:  # pragma: no cover - Windows-only fallback
    resource = None


LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = int(os.environ.get("ODYSSEUS_TOOL_SANDBOX_PORT", "8081"))
TOKEN = os.environ.get("ODYSSEUS_TOOL_SANDBOX_TOKEN", "")
SOCKET_PATH_SETTING = os.environ.get("ODYSSEUS_TOOL_SANDBOX_SOCKET", "").strip()
WORKSPACE = Path("/workspace")
MAX_REQUEST_BYTES = 64 * 1024
MAX_COMMAND_BYTES = 48 * 1024
MAX_TIMEOUT_SECONDS = 120
MAX_OUTPUT_BYTES = 200_000
_MAX_UNIX_SOCKET_PATH_BYTES = 100
_EXECUTOR_UID = 65532


def _positive_id_from_env(name: str, default: int) -> int:
    raw_value = os.environ.get(name, str(default)).strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise SystemExit(f"{name} must be a positive numeric ID") from exc
    if value < 1:
        raise SystemExit(f"{name} must be a positive numeric ID")
    return value


_EXECUTOR_GID = _positive_id_from_env("ODYSSEUS_TOOL_SANDBOX_GID", 65532)


def _limit_child() -> None:
    """Apply Linux process limits before executing the untrusted shell."""

    # /workspace is intentionally shared with the app through a dedicated
    # group. Keep new files private to that pair of containers, not world
    # readable, while letting app file tools consume command output.
    os.umask(0o007)
    if resource is None:
        return
    resource.setrlimit(resource.RLIMIT_CPU, (MAX_TIMEOUT_SECONDS, MAX_TIMEOUT_SECONDS))
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 * 1024, 16 * 1024 * 1024))


def _drain_limited(
    stream: BinaryIO,
    output: bytearray,
    total_output: list[int],
    lock: threading.Lock,
) -> None:
    """Drain a child pipe without keeping more than the response cap in RAM."""

    while True:
        chunk = stream.read(8192)
        if not chunk:
            return
        with lock:
            remaining = MAX_OUTPUT_BYTES - total_output[0]
            if remaining > 0:
                kept = chunk[:remaining]
                output.extend(kept)
                total_output[0] += len(kept)


def _kill_process_group(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _workspace_cwd(workdir: object) -> Path:
    """Resolve a protocol workdir below the sole mounted workspace tree."""
    if not isinstance(workdir, str) or not workdir.strip():
        raise ValueError("invalid workdir")
    value = workdir.strip()
    if value != ".":
        if value.startswith("/") or "\\" in value:
            raise ValueError("invalid workdir")
        parts = value.split("/")
        if any(part in ("", ".", "..") for part in parts):
            raise ValueError("invalid workdir")
    root = WORKSPACE.resolve()
    candidate = (root / value).resolve()
    try:
        inside = candidate == root or os.path.commonpath([str(candidate), str(root)]) == str(root)
    except ValueError:
        inside = False
    if not inside or not candidate.is_dir():
        raise ValueError("invalid workdir")
    return candidate


def _run(command: str, timeout: int, workdir: object) -> dict[str, object]:
    cwd = _workspace_cwd(workdir)
    env = {
        "HOME": str(cwd),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/local/bin:/usr/bin:/bin",
    }
    proc = subprocess.Popen(
        ["/bin/sh", "-lc", command],
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        preexec_fn=_limit_child,
    )
    stdout = bytearray()
    stderr = bytearray()
    total_output = [0]
    output_lock = threading.Lock()
    assert proc.stdout is not None and proc.stderr is not None
    readers = [
        threading.Thread(target=_drain_limited, args=(proc.stdout, stdout, total_output, output_lock)),
        threading.Thread(target=_drain_limited, args=(proc.stderr, stderr, total_output, output_lock)),
    ]
    for reader in readers:
        reader.start()
    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_process_group(proc)
        proc.wait(timeout=5)
    finally:
        for reader in readers:
            reader.join(timeout=5)

    return {
        "stdout": bytes(stdout).decode("utf-8", errors="replace"),
        "stderr": bytes(stderr).decode("utf-8", errors="replace"),
        "exit_code": 124 if timed_out else int(proc.returncode or 0),
        "timed_out": timed_out,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "OdysseusToolSandbox/1"

    def log_message(self, _format: str, *_args: object) -> None:
        # Commands and their output must not leak into HTTP server logs.
        return

    def _json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - required BaseHTTPRequestHandler API
        if self.path == "/healthz":
            self._json(HTTPStatus.OK, {"ok": True})
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - required BaseHTTPRequestHandler API
        if self.path != "/execute":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        supplied_token = self.headers.get("X-Odysseus-Sandbox-Token", "")
        if not TOKEN or not hmac.compare_digest(supplied_token, TOKEN):
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        try:
            content_length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            content_length = -1
        if content_length < 0 or content_length > MAX_REQUEST_BYTES:
            self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "request too large"})
            return
        try:
            data = json.loads(self.rfile.read(content_length))
            command = data["command"]
            timeout = int(data["timeout"])
            workdir = data["workdir"]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid request"})
            return
        if not isinstance(command, str) or not command.strip() or len(command.encode("utf-8")) > MAX_COMMAND_BYTES:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid command"})
            return
        if not 1 <= timeout <= MAX_TIMEOUT_SECONDS:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid timeout"})
            return
        try:
            self._json(HTTPStatus.OK, _run(command, timeout, workdir))
        except Exception:
            # Do not expose host/container paths or exception details to callers.
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "execution failed"})


class ThreadingUnixHTTPServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    """Threaded HTTP server bound to a filesystem Unix-domain socket."""

    daemon_threads = True
    block_on_close = False


def _socket_path(raw_path: str) -> Path:
    if not raw_path:
        raise SystemExit("ODYSSEUS_TOOL_SANDBOX_SOCKET must not be empty")
    try:
        encoded_path = raw_path.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise SystemExit("ODYSSEUS_TOOL_SANDBOX_SOCKET is invalid") from exc
    if (
        not raw_path.startswith("/")
        or "\\" in raw_path
        or "\x00" in raw_path
        or len(encoded_path) > _MAX_UNIX_SOCKET_PATH_BYTES
    ):
        raise SystemExit("ODYSSEUS_TOOL_SANDBOX_SOCKET is invalid")
    return Path(raw_path)


def _prepare_socket_directory(socket_path: Path) -> None:
    """Create a root-owned directory traversable, but not writable, by the app."""

    socket_dir = socket_path.parent
    if socket_dir.is_symlink():
        raise SystemExit("ODYSSEUS_TOOL_SANDBOX_SOCKET parent must not be a symlink")
    socket_dir.mkdir(parents=True, exist_ok=True)
    os.chown(socket_dir, 0, _EXECUTOR_GID)
    # The app user only needs group execute permission to connect.  It must not
    # be able to replace the socket or add another endpoint in this directory.
    os.chmod(socket_dir, 0o750)


def _remove_stale_socket(socket_path: Path) -> None:
    try:
        existing = socket_path.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISSOCK(existing.st_mode):
        raise SystemExit("Refusing to replace a non-socket executor endpoint")
    socket_path.unlink()


def _drop_to_executor_identity() -> None:
    """Drop the temporary startup privileges before accepting any request."""

    if os.geteuid() == 0:
        os.setgroups([_EXECUTOR_GID])
        os.setgid(_EXECUTOR_GID)
        os.setuid(_EXECUTOR_UID)
        return
    if os.geteuid() != _EXECUTOR_UID or os.getegid() != _EXECUTOR_GID:
        raise SystemExit("tool-sandbox must run as the dedicated executor identity")


def main() -> None:
    if not TOKEN:
        raise SystemExit("ODYSSEUS_TOOL_SANDBOX_TOKEN must be set")
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    socket_path: Path | None = None
    if SOCKET_PATH_SETTING:
        if os.geteuid() != 0:
            raise SystemExit("Unix-socket tool-sandbox must start as root and drop privileges")
        socket_path = _socket_path(SOCKET_PATH_SETTING)
        _prepare_socket_directory(socket_path)
        _remove_stale_socket(socket_path)
        httpd = ThreadingUnixHTTPServer(str(socket_path), Handler)
        # Only root can create the endpoint.  Hand it to the dedicated group
        # before the server drops privileges; the application has that group as
        # a supplementary group but only a read-only mount of its directory.
        os.chown(socket_path, 0, _EXECUTOR_GID)
        os.chmod(socket_path, 0o660)
    else:
        # Native deployments may supply an independently isolated TCP executor.
        # Docker Compose intentionally sets SOCKET_PATH_SETTING, so this path is
        # never network-reachable in the supported container deployment.
        httpd = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler)

    _drop_to_executor_identity()
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
        if socket_path is not None:
            try:
                socket_path.unlink()
            except FileNotFoundError:
                pass


if __name__ == "__main__":
    main()
