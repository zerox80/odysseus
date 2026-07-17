"""Check line-count and line-length limits for tracked Python, TypeScript, and Rust files."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


MAX_LINES = 500
MAX_LINE_LENGTH = 120
CHECK_NAME_FILE_LIMIT = 4


def tracked_source_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.py", "*.ts", "*.tsx", "*.rs"],
        check=True,
        capture_output=True,
    )
    return [Path(name) for name in result.stdout.decode().split("\0") if name]


def find_violations(paths: list[Path]) -> list[tuple[Path, int, str]]:
    violations: list[tuple[Path, int, str]] = []

    for path in paths:
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

    return violations


def failed_files(violations: list[tuple[Path, int, str]]) -> list[str]:
    return sorted({path.as_posix() for path, _, _ in violations})


def github_check_name(violations: list[tuple[Path, int, str]]) -> str:
    files = failed_files(violations)
    if not files:
        return "Source limits PASSED"

    visible_files = ", ".join(files[:CHECK_NAME_FILE_LIMIT])
    remaining = len(files) - CHECK_NAME_FILE_LIMIT
    suffix = f" (+{remaining} more)" if remaining > 0 else ""
    return f"Source limits FAILED: {visible_files}{suffix}"


def report_summary(violations: list[tuple[Path, int, str]]) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    with open(summary_path, "a", encoding="utf-8") as summary:
        summary.write("## Python/TypeScript/Rust source limits\n\n")
        if violations:
            files = failed_files(violations)
            summary.write(f"FAILED: {len(files)} file(s) violate the source limits.\n\n")
            summary.write("### Failed files\n\n")
            for path in files:
                summary.write(f"- `{path}`\n")
            summary.write("\n### Violations\n\n")
            for path, line_number, message in violations:
                summary.write(f"- `{path}:{line_number}` - {message}\n")
        else:
            summary.write(
                f"PASSED: all tracked Python, TypeScript, and Rust files are at most "
                f"{MAX_LINES} lines, with no line longer than "
                f"{MAX_LINE_LENGTH} characters.\n"
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--github-output",
        action="store_true",
        help="print a dynamic GitHub check name and exit successfully",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    violations = find_violations(tracked_source_files())

    if args.github_output:
        print(f"check_name={github_check_name(violations)}")
        return 0

    if violations:
        for path, line_number, message in violations:
            print(f"::error file={path.as_posix()},line={line_number}::{message}")
        print(f"FAILED: {len(violations)} Python/TypeScript/Rust source-limit violation(s).")
    else:
        print(
            f"PASSED: all tracked Python/TypeScript/Rust files satisfy the "
            f"{MAX_LINES}-line and {MAX_LINE_LENGTH}-character limits."
        )

    report_summary(violations)
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
