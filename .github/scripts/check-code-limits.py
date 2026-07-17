"""Enforce a ratcheted line-count limit for Python, TypeScript, and Rust files."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


MAX_LINES = 500
CHECK_NAME_FILE_LIMIT = 4
SOURCE_GLOBS = ("*.py", "*.ts", "*.tsx", "*.rs")
SOURCE_SUFFIXES = frozenset({".py", ".ts", ".tsx", ".rs"})


class SourceLimitError(RuntimeError):
    """Raised when the source comparison cannot be completed safely."""


@dataclass(frozen=True)
class FileChange:
    """A current source path and the path it had in the baseline, if any."""

    current_path: Path
    baseline_path: Path | None


@dataclass(frozen=True)
class Violation:
    """A source-size violation suitable for terminal and GitHub reporting."""

    path: Path
    message: str


def run_git(*args: str) -> subprocess.CompletedProcess[bytes]:
    """Run a read-only Git command and retain output for structured parsing."""

    return subprocess.run(
        ["git", *args],
        check=False,
        capture_output=True,
    )


def git_output(*args: str) -> bytes:
    """Return Git output or raise an error with useful command context."""

    result = run_git(*args)
    if result.returncode == 0:
        return result.stdout

    detail = result.stderr.decode("utf-8", errors="replace").strip()
    command = "git " + " ".join(args)
    raise SourceLimitError(f"{command} failed: {detail or 'unknown Git error'}")


def is_source_path(path: Path) -> bool:
    return path.suffix.lower() in SOURCE_SUFFIXES


def tracked_source_files() -> list[Path]:
    """Return all source files tracked at HEAD for a strict local scan."""

    raw_paths = git_output("ls-files", "-z", "--", *SOURCE_GLOBS)
    paths = os.fsdecode(raw_paths).split("\0")
    return sorted(Path(path) for path in paths if path)


def resolve_baseline_ref(requested_ref: str | None) -> str | None:
    """Resolve the requested baseline; an omitted option selects strict mode."""

    if requested_ref is None:
        return None

    candidate = requested_ref.strip()
    if not candidate or not candidate.strip("0"):
        candidate = "HEAD^"

    result = run_git("rev-parse", "--verify", f"{candidate}^{{commit}}")
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise SourceLimitError(
            f"cannot resolve source-limit baseline {candidate!r}: "
            f"{detail or 'unknown Git error'}"
        )

    return result.stdout.decode("ascii").strip()


def changed_source_files(baseline_ref: str) -> list[FileChange]:
    """Return current source files changed since the selected baseline."""

    raw_changes = git_output(
        "diff",
        "--name-status",
        "-z",
        "--find-renames",
        baseline_ref,
        "HEAD",
        "--",
        *SOURCE_GLOBS,
    )
    fields = os.fsdecode(raw_changes).split("\0")
    if fields and not fields[-1]:
        fields.pop()

    changes: list[FileChange] = []
    index = 0
    while index < len(fields):
        status = fields[index]
        index += 1
        if not status:
            raise SourceLimitError("Git returned an empty file status")

        status_code = status[0]
        if status_code in {"R", "C"}:
            if index + 1 >= len(fields):
                raise SourceLimitError(f"Git returned an incomplete {status} record")
            old_path = Path(fields[index])
            current_path = Path(fields[index + 1])
            index += 2

            if not is_source_path(current_path):
                continue

            baseline_path = old_path if status_code == "R" and is_source_path(old_path) else None
            changes.append(FileChange(current_path, baseline_path))
            continue

        if index >= len(fields):
            raise SourceLimitError(f"Git returned an incomplete {status} record")
        current_path = Path(fields[index])
        index += 1

        if status_code == "D" or not is_source_path(current_path):
            continue

        baseline_path = None if status_code == "A" else current_path
        changes.append(FileChange(current_path, baseline_path))

    return sorted(changes, key=lambda change: change.current_path.as_posix())


def blob_line_count(ref: str, path: Path) -> int:
    """Count lines in a tracked blob without following workspace symlinks."""

    object_name = f"{ref}:{path.as_posix()}"
    content = git_output("cat-file", "blob", object_name)
    return len(content.splitlines())


def strict_violations(paths: list[Path]) -> list[Violation]:
    """Apply the hard limit to every supplied path."""

    violations: list[Violation] = []
    for path in paths:
        line_count = blob_line_count("HEAD", path)
        if line_count > MAX_LINES:
            violations.append(
                Violation(
                    path,
                    f"file has {line_count} lines; maximum is {MAX_LINES}",
                )
            )
    return violations


def incremental_violations(
    changes: list[FileChange],
    baseline_ref: str,
) -> list[Violation]:
    """Reject new oversized files and growth in existing oversized files."""

    violations: list[Violation] = []
    for change in changes:
        current_count = blob_line_count("HEAD", change.current_path)
        if current_count <= MAX_LINES:
            continue

        if change.baseline_path is None:
            violations.append(
                Violation(
                    change.current_path,
                    f"new file has {current_count} lines; maximum is {MAX_LINES}",
                )
            )
            continue

        baseline_count = blob_line_count(baseline_ref, change.baseline_path)
        if current_count > baseline_count:
            violations.append(
                Violation(
                    change.current_path,
                    f"oversized file grew from {baseline_count} to {current_count} lines; "
                    f"maximum is {MAX_LINES}",
                )
            )

    return violations


def failed_files(violations: list[Violation]) -> list[str]:
    return sorted({violation.path.as_posix() for violation in violations})


def github_check_name(violations: list[Violation]) -> str:
    files = failed_files(violations)
    if not files:
        return "Source size PASSED"

    visible_files = ", ".join(files[:CHECK_NAME_FILE_LIMIT])
    remaining = len(files) - CHECK_NAME_FILE_LIMIT
    suffix = f" (+{remaining} more)" if remaining > 0 else ""
    return f"Source size FAILED: {visible_files}{suffix}"


def report_summary(
    violations: list[Violation],
    baseline_ref: str | None,
) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    with open(summary_path, "a", encoding="utf-8") as summary:
        summary.write("## Python/TypeScript/Rust file-size limit\n\n")
        if baseline_ref:
            summary.write(
                f"Changed files were compared with baseline `{baseline_ref[:12]}`. "
                f"New files may have at most {MAX_LINES} lines; existing oversized "
                "files may not grow.\n\n"
            )
        else:
            summary.write(f"All tracked source files may have at most {MAX_LINES} lines.\n\n")

        if violations:
            files = failed_files(violations)
            summary.write(f"FAILED: {len(files)} file(s) exceed the allowed size.\n\n")
            for violation in violations:
                summary.write(f"- `{violation.path.as_posix()}:1` - {violation.message}\n")
        else:
            summary.write("PASSED: no source file exceeded its allowed size.\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--baseline-ref",
        metavar="REF",
        help=(
            "compare changed files with REF; new files must meet the hard limit "
            "and existing oversized files may not grow"
        ),
    )
    parser.add_argument(
        "--github-output",
        action="store_true",
        help="print a dynamic GitHub check name and exit successfully",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        baseline_ref = resolve_baseline_ref(args.baseline_ref)
        if baseline_ref:
            changes = changed_source_files(baseline_ref)
            violations = incremental_violations(changes, baseline_ref)
        else:
            violations = strict_violations(tracked_source_files())
    except SourceLimitError as error:
        print(f"::error::{error}", file=sys.stderr)
        if args.github_output:
            print("check_name=Source size ERROR")
        return 2

    if args.github_output:
        print(f"check_name={github_check_name(violations)}")
        return 0

    if violations:
        for violation in violations:
            path = violation.path.as_posix()
            print(f"::error file={path},line=1::{path}:1: {violation.message}")
        print(f"FAILED: {len(violations)} source file-size violation(s).")
    else:
        print("PASSED: no source file exceeded its allowed size.")

    report_summary(violations, baseline_ref)
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
