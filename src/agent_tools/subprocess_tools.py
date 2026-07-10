"""Agent command tools backed by the isolated tool-sandbox sidecar."""

from __future__ import annotations

import shlex
from typing import Any

from src.constants import MAX_OUTPUT_CHARS
from src.sandbox_executor import (
    MAX_TIMEOUT_SECONDS,
    SandboxExecutorUnavailable,
    execute_sandbox_command,
)
from src.tool_execution import sandbox_workdir


# Long-running model-controlled processes are intentionally not permitted in
# the sandbox.  The container's request, CPU, and process limits use the same
# upper bound.
DEFAULT_BASH_TIMEOUT = MAX_TIMEOUT_SECONDS
DEFAULT_PYTHON_TIMEOUT = MAX_TIMEOUT_SECONDS


def _combined_output(result: dict[str, Any]) -> str:
    output = str(result["stdout"]).rstrip()
    stderr = str(result["stderr"]).rstrip()
    if stderr:
        output = f"{output}\nSTDERR: {stderr}".strip() if output else f"STDERR: {stderr}"
    return output[:MAX_OUTPUT_CHARS] or "(no output)"


async def _execute_in_sandbox(command: str, *, timeout: int, tool_name: str) -> dict[str, Any]:
    try:
        result = await execute_sandbox_command(
            command,
            timeout=timeout,
            workdir=sandbox_workdir(),
        )
    except (SandboxExecutorUnavailable, ValueError) as exc:
        return {
            "error": f"{tool_name}: isolated execution unavailable: {exc}",
            "exit_code": 125,
        }
    if result["timed_out"]:
        return {
            "error": f"{tool_name}: timed out after {timeout}s in isolated executor",
            "exit_code": 124,
            "stdout": str(result["stdout"])[:MAX_OUTPUT_CHARS],
            "stderr": str(result["stderr"])[:MAX_OUTPUT_CHARS],
        }
    return {"output": _combined_output(result), "exit_code": result["exit_code"]}


class BashTool:
    async def execute(self, content: str, ctx: dict) -> dict[str, Any]:
        progress_cb = ctx.get("progress_cb")
        if progress_cb:
            await progress_cb({"elapsed_s": 0, "tail": "Command started in isolated executor."})
        result = await _execute_in_sandbox(
            content, timeout=DEFAULT_BASH_TIMEOUT, tool_name="bash"
        )
        if progress_cb:
            await progress_cb({"elapsed_s": 0, "tail": "Command finished in isolated executor."})
        return result


class PythonTool:
    async def execute(self, content: str, ctx: dict) -> dict[str, Any]:
        # The sidecar image provides python3; quote source so it remains one
        # argument to Python rather than becoming a second shell program.
        command = f"python3 -I -c {shlex.quote(content)}"
        progress_cb = ctx.get("progress_cb")
        if progress_cb:
            await progress_cb({"elapsed_s": 0, "tail": "Python started in isolated executor."})
        result = await _execute_in_sandbox(
            command, timeout=DEFAULT_PYTHON_TIMEOUT, tool_name="python"
        )
        if progress_cb:
            await progress_cb({"elapsed_s": 0, "tail": "Python finished in isolated executor."})
        return result
