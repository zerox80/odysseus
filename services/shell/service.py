# services/shell/service.py
"""Shell service — safe command execution."""

from dataclasses import dataclass
from typing import Optional, AsyncIterator

from src.sandbox_executor import SandboxExecutorUnavailable, execute_sandbox_command
from src.tool_execution import sandbox_workdir


@dataclass
class ShellResult:
    """Result of a shell command."""
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False


class ShellService:
    """
    Shell execution service.

    Usage:
        service = ShellService()
        result = await service.execute("ls -la")
        print(result.stdout)
    """

    def __init__(self, timeout: int = 30, max_output: int = 200_000):
        self.timeout = timeout
        self.max_output = max_output

    async def _run(self, command: str, timeout: int) -> ShellResult:
        """Run a bounded command in the dedicated workspace sidecar."""
        safe_timeout = max(1, min(int(timeout), 120))
        try:
            result = await execute_sandbox_command(
                command,
                timeout=safe_timeout,
                workdir=sandbox_workdir(),
            )
        except (SandboxExecutorUnavailable, ValueError, RuntimeError) as exc:
            return ShellResult(stdout="", stderr=str(exc), exit_code=125)
        return ShellResult(
            stdout=str(result["stdout"])[:self.max_output],
            stderr=str(result["stderr"])[:self.max_output],
            exit_code=int(result["exit_code"]),
            timed_out=bool(result["timed_out"]),
        )

    async def execute(
        self,
        command: str,
        timeout: Optional[int] = None,
        cwd: Optional[str] = None,
    ) -> ShellResult:
        """
        Execute a shell command.

        Args:
            command: Shell command to run
            timeout: Timeout in seconds (default: self.timeout)
            cwd: Working directory (default: home)

        Returns:
            ShellResult with stdout, stderr, exit_code
        """
        if cwd is not None:
            return ShellResult(
                stdout="",
                stderr="Custom working directories are disabled; commands use the dedicated workspace.",
                exit_code=125,
            )
        return await self._run(command, timeout or self.timeout)

    async def stream(
        self,
        command: str,
        timeout: int = 120,
    ) -> AsyncIterator[dict]:
        """
        Execute a command and stream output.

        Yields:
            {"stream": "stdout"|"stderr", "data": line}
            {"exit_code": int}
        """

        result = await self._run(command, timeout)
        for line in result.stdout.splitlines():
            yield {"stream": "stdout", "data": line}
        for line in result.stderr.splitlines():
            yield {"stream": "stderr", "data": line}
        yield {"exit_code": result.exit_code}
