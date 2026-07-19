"""Fail when tracked repository content contains local data or notebook results."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN_NAMES = {".env"}
FORBIDDEN_SUFFIXES = {".csv", ".xls", ".xlsx"}
GOOGLE_LINK_PATTERN = re.compile(
    rb"(?:colab\.research\.google\.com/drive|drive\.google\.com|docs\.google\.com)"
)
SENSITIVE_METADATA_KEYS = {
    "authorship_tag",
    "displayName",
    "executionInfo",
    "outputId",
    "provenance",
    "userId",
}


def tracked_files() -> list[Path]:
    result = subprocess.run(
        [
            "git",
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [ROOT / item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def find_sensitive_key(value: object) -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in SENSITIVE_METADATA_KEYS:
                return key
            found = find_sensitive_key(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_sensitive_key(child)
            if found:
                return found
    return None


def audit_notebook(path: Path, errors: list[str]) -> None:
    try:
        notebook = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        errors.append(f"{path.relative_to(ROOT)}: invalid notebook ({error})")
        return

    for index, cell in enumerate(notebook.get("cells", [])):
        if cell.get("cell_type") != "code":
            continue
        if cell.get("execution_count") is not None:
            errors.append(f"{path.relative_to(ROOT)}: cell {index} has execution_count")
        if cell.get("outputs"):
            errors.append(f"{path.relative_to(ROOT)}: cell {index} has outputs")

    sensitive_key = find_sensitive_key(notebook.get("metadata", {}))
    if sensitive_key:
        errors.append(f"{path.relative_to(ROOT)}: metadata contains {sensitive_key}")

    for index, cell in enumerate(notebook.get("cells", [])):
        sensitive_key = find_sensitive_key(cell.get("metadata", {}))
        if sensitive_key:
            errors.append(
                f"{path.relative_to(ROOT)}: cell {index} metadata contains {sensitive_key}"
            )


def main() -> int:
    errors: list[str] = []

    for path in tracked_files():
        relative = path.relative_to(ROOT)
        if not path.is_file():
            continue
        if path.name in FORBIDDEN_NAMES or path.suffix.lower() in FORBIDDEN_SUFFIXES:
            errors.append(f"{relative}: forbidden tracked data file")
            continue

        try:
            content = path.read_bytes()
        except OSError as error:
            errors.append(f"{relative}: cannot read file ({error})")
            continue

        if GOOGLE_LINK_PATTERN.search(content):
            errors.append(f"{relative}: contains a direct Google Drive/Colab link")

        if path.suffix.lower() == ".ipynb":
            audit_notebook(path, errors)

    if errors:
        print("Repository safety audit failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print("Repository safety audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
