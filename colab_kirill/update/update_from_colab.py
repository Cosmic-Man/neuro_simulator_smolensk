"""Download the latest notebook version from the project's Colab file."""

# Чтобы скачать свежую версию ноутбука из Colab:
# python .\colab_kirill\update\update_from_colab.py
#
# Чтобы скачать, закоммитить и отправить обновление одной командой PowerShell:
# .\colab_kirill\update\update_from_colab.ps1
# Скрипт отправляет только текущую ветку: main — в main, личную — в личную.
#
# То же самое вручную — сначала создать коммит:
# git add "colab_kirill/Copy of FuzzyConvolution.ipynb"
# git commit -m "Update notebook from Colab"
#
# Вариант 1. Отправить коммит прямо в основную ветку main:
# git push --set-upstream origin main
#
# Вариант 2. Отправить коммит только в личную ветку test_maxim:
# git branch --show-current
# git push --set-upstream origin test_maxim
#
# Вариант 3. Отправить в test_maxim, затем перенести изменения в main:
# git push --set-upstream origin test_maxim
# git switch main
# git pull --ff-only origin main
# git merge test_maxim
# git push origin main
# git switch test_maxim

from __future__ import annotations

import json
import os
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.notebook_safety import sanitize_notebook


ENV_PATH = REPO_ROOT / ".env"
TARGET = Path(__file__).resolve().parent.parent / "Copy of FuzzyConvolution.ipynb"


def read_env(name: str) -> str:
    if not ENV_PATH.exists():
        raise RuntimeError(f"Environment file not found: {ENV_PATH}")

    for raw_line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            return value.strip().strip('"\'')

    raise RuntimeError(f"Variable {name} is missing in {ENV_PATH.name}")


def get_drive_file_id(colab_url: str) -> str:
    parts = urllib.parse.urlparse(colab_url).path.strip("/").split("/")
    if len(parts) < 2 or parts[-2] != "drive" or not parts[-1]:
        raise RuntimeError("COLAB_KIRILL_URL is not a valid Colab Drive URL")
    return parts[-1]


FILE_ID = get_drive_file_id(read_env("COLAB_KIRILL_URL"))
DRIVE_HOST = ".".join(("drive", "google", "com"))
DOWNLOAD_URL = urllib.parse.urlunparse(
    ("https", DRIVE_HOST, "/uc", "", urllib.parse.urlencode({"export": "download", "id": FILE_ID}), "")
)


def update_notebook() -> None:
    request = urllib.request.Request(
        DOWNLOAD_URL,
        headers={"User-Agent": "Mozilla/5.0"},
    )

    temporary_path: Path | None = None
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            if "text/html" in response.headers.get_content_type():
                raise RuntimeError(
                    "Google вернул HTML вместо ноутбука. Проверьте доступ по ссылке."
                )

            with tempfile.NamedTemporaryFile(
                mode="wb", delete=False, dir=TARGET.parent, suffix=".ipynb.tmp"
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                while chunk := response.read(1024 * 1024):
                    temporary_file.write(chunk)

        with temporary_path.open("r", encoding="utf-8") as notebook_file:
            notebook = json.load(notebook_file)

        if notebook.get("nbformat") is None or not isinstance(notebook.get("cells"), list):
            raise RuntimeError("Скачанный JSON не является Jupyter Notebook.")

        sanitize_notebook(notebook)
        temporary_path.write_text(
            json.dumps(notebook, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary_path, TARGET)
        temporary_path = None
        print(f"Ноутбук обновлён: {TARGET.name}")
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


if __name__ == "__main__":
    update_notebook()
