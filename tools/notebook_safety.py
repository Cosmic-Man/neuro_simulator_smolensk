"""Utilities for removing generated and personal data from Jupyter notebooks."""

from __future__ import annotations

from typing import Any


SENSITIVE_METADATA_KEYS = {
    "authorship_tag",
    "displayName",
    "executionInfo",
    "outputId",
    "provenance",
    "user",
    "userId",
}


def _remove_sensitive_metadata(value: Any) -> None:
    if isinstance(value, dict):
        for key in list(value):
            if key in SENSITIVE_METADATA_KEYS:
                del value[key]
            else:
                _remove_sensitive_metadata(value[key])
    elif isinstance(value, list):
        for item in value:
            _remove_sensitive_metadata(item)


def sanitize_notebook(notebook: dict[str, Any]) -> dict[str, Any]:
    """Remove outputs, execution state, and Colab identity metadata in place."""
    metadata = notebook.setdefault("metadata", {})
    metadata.pop("colab", None)
    _remove_sensitive_metadata(metadata)

    for cell in notebook.get("cells", []):
        if cell.get("cell_type") == "code":
            cell["execution_count"] = None
            cell["outputs"] = []

        cell_metadata = cell.setdefault("metadata", {})
        cell_metadata.pop("colab", None)
        _remove_sensitive_metadata(cell_metadata)

    return notebook
