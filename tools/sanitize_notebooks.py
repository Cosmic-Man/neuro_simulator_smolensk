"""Sanitize every tracked Jupyter notebook in the repository."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from notebook_safety import sanitize_notebook


ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    result = subprocess.run(
        [
            "git",
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
            "*.ipynb",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )

    for raw_path in result.stdout.split(b"\0"):
        if not raw_path:
            continue
        path = ROOT / raw_path.decode("utf-8")
        if not path.is_file():
            continue
        notebook = json.loads(path.read_text(encoding="utf-8"))
        sanitize_notebook(notebook)
        path.write_text(
            json.dumps(notebook, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8",
        )
        print(f"Sanitized: {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
