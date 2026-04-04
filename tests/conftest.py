from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image


SAMPLE_MID = "11111111-1111-1111-1111-111111111111"


def _write_export_fixture(root: Path) -> Path:
    export_dir = root / "sample_export"
    export_dir.mkdir(parents=True, exist_ok=True)

    Image.new("RGB", (20, 20), color=(220, 30, 30)).save(export_dir / f"{SAMPLE_MID}-main.jpg", "JPEG")
    Image.new("RGBA", (20, 20), color=(0, 0, 255, 96)).save(export_dir / f"{SAMPLE_MID}-overlay.png", "PNG")

    payload = [
        {
            "Date": "2024-01-02 03:04:05 UTC",
            "Media Id": SAMPLE_MID,
            "Latitude": 52.52,
            "Longitude": 13.405,
        }
    ]
    (export_dir / "metadata.json").write_text(json.dumps(payload), encoding="utf-8")
    return export_dir


@pytest.fixture()
def sample_export_dir(tmp_path: Path) -> Path:
    return _write_export_fixture(tmp_path)


@pytest.fixture()
def sample_export_zip(tmp_path: Path) -> Path:
    export_dir = _write_export_fixture(tmp_path)
    zip_path = tmp_path / "sample_export.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for file_path in export_dir.rglob("*"):
            archive.write(file_path, arcname=file_path.relative_to(export_dir))
    return zip_path
