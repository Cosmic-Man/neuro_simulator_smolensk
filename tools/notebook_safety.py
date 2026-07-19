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
DATASET_PATH = "../datasets/smolensk_dataset_shared.csv"
LEGACY_DATASET_PATHS = {
    "../smolensk_dataset.csv",
    "smolensk_data.csv",
    "smolensk_dataset (1).csv",
    "smolensk_dataset (2).csv",
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
    """Remove generated data and normalize the shared dataset path in place."""
    metadata = notebook.setdefault("metadata", {})
    metadata.pop("colab", None)
    _remove_sensitive_metadata(metadata)

    for cell in notebook.get("cells", []):
        source = cell.get("source")
        if isinstance(source, list):
            normalized_source = _normalize_source("".join(source))
            cell["source"] = normalized_source.splitlines(keepends=True)
        elif isinstance(source, str):
            cell["source"] = _normalize_source(source)

        if cell.get("cell_type") == "code":
            cell["execution_count"] = None
            cell["outputs"] = []

        cell_metadata = cell.setdefault("metadata", {})
        cell_metadata.pop("colab", None)
        _remove_sensitive_metadata(cell_metadata)

    return notebook


def _normalize_source(source: str) -> str:
    for legacy_path in LEGACY_DATASET_PATHS:
        source = source.replace(legacy_path, DATASET_PATH)

    source = source.replace(
        "/content/smolensk_clean.csv",
        "../datasets/smolensk_clean_guldar.csv",
    )
    source = source.replace(
        "/content/weights_transport.csv",
        "../datasets/weights_transport_guldar.csv",
    )
    source = source.replace(
        "OUTPUT_CSV = 'smolensk_clean.csv'",
        "OUTPUT_CSV = '../datasets/smolensk_clean_guldar.csv'",
    )
    if (
        "df = clean_csv(CSV_PATH, OUTPUT_CSV)" in source
        and "CSV_PATH =" not in source
    ):
        source = source.replace(
            "OUTPUT_CSV = '../datasets/smolensk_clean_guldar.csv'",
            "CSV_PATH = 'smolensk.csv'\n"
            "OUTPUT_CSV = '../datasets/smolensk_clean_guldar.csv'",
            1,
        )

    boxplot_signature = "def get_boxplot(d, title):\n"
    series_conversion = (
        "  if isinstance(d, pd.Series):\n"
        "    d = d.to_frame()\n"
        "\n"
    )
    if boxplot_signature in source and "isinstance(d, pd.Series)" not in source:
        source = source.replace(
            boxplot_signature,
            boxplot_signature + series_conversion,
            1,
        )

    return source
