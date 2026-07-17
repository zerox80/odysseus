"""Check line-count and line-length limits for tracked TypeScript and Rust files."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


MAX_LINES = 500
MAX_LINE_LENGTH = 120


def tracked_source_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.ts", "*.tsx", "*.rs"],
        check=True,
        capture_output=True,
    )
    return [Path(name) for name in result.stdout.decode().split("\0") if name]


def report_summary(violations: list[tuple[Path, int, str]]) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    with open(summary_path, "a", encoding="utf-8") as summary:
        summary.write("## TypeScript/Rust source limits\n\n")
        if violations:
            summary.write("❌ The following limits failed:\n\n")
            for path, line_number, message in violations:
                summary.write(f"- `{path}:{line_number}` — {message}\n")
        else:
            summary.write(
                f"✅ All tracked TypeScript and Rust files are at most "
                f"{MAX_LINES} lines, with no line longer than "
                f"{MAX_LINE_LENGTH} characters.\n"
            )


def main() -> int:
    violations: list[tuple[Path, int, str]] = []

    for path in tracked_source_files():
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError as error:
            violations.append((path, 1, f"cannot be read as UTF-8: {error}"))
            continue

        if len(lines) > MAX_LINES:
            violations.append(
                (
                    path,
                    1,
                    f"file has {len(lines)} lines; maximum is {MAX_LINES}",
                )
            )

        for line_number, line in enumerate(lines, start=1):
            length = len(line)
            if length > MAX_LINE_LENGTH:
                violations.append(
                    (
                        path,
                        line_number,
                        f"line has {length} characters; maximum is {MAX_LINE_LENGTH}",
                    )
                )

    if violations:
        for path, line_number, message in violations:
            print(f"::error file={path.as_posix()},line={line_number}::{message}")
        print(f"FAILED: {len(violations)} TypeScript/Rust source-limit violation(s).")
    else:
        print(
            f"PASSED: all tracked TypeScript/Rust files satisfy the "
            f"{MAX_LINES}-line and {MAX_LINE_LENGTH}-character limits."
        )

    report_summary(violations)
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
