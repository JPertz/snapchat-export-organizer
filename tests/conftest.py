from __future__ import annotations

import json
import subprocess
import zipfile
from pathlib import Path

import imageio_ffmpeg
import pytest
from PIL import Image


SAMPLE_MID = "11111111-1111-1111-1111-111111111111"
IMAGE_TWO_MID = "22222222-2222-2222-2222-222222222222"
VIDEO_ONE_MID = "33333333-3333-3333-3333-333333333333"
VIDEO_TWO_MID = "44444444-4444-4444-4444-444444444444"


def _write_export_fixture(root: Path) -> Path:
    export_dir = root / "sample_export"
    export_dir.mkdir(parents=True, exist_ok=True)

    Image.new("RGB", (20, 20), color=(220, 30, 30)).save(export_dir / f"{SAMPLE_MID}-main.jpg", "JPEG")
    Image.new("RGBA", (20, 20), color=(0, 0, 255, 96)).save(export_dir / f"{SAMPLE_MID}-overlay.png", "PNG")

    payload = [
        {
            "Date": "2024-01-02 03:04:05 UTC",
            "Media Id": SAMPLE_MID,
            "Media Download Url": f"https://example.com/{SAMPLE_MID}-main.jpg",
            "Media Type": "Image",
            "Latitude": 52.52,
            "Longitude": 13.405,
        }
    ]
    (export_dir / "metadata.json").write_text(json.dumps(payload), encoding="utf-8")
    return export_dir


def _write_summary_fixture(root: Path) -> Path:
    export_dir = root / "summary_export"
    export_dir.mkdir(parents=True, exist_ok=True)

    payload = [
        {
            "Date": "2024-01-02 03:04:05 UTC",
            "Media Id": SAMPLE_MID,
            "Media Download Url": f"https://example.com/{SAMPLE_MID}-main.jpg",
            "Media Type": "Image",
        },
        {
            "Date": "2024-01-02 03:04:05 UTC",
            "Media Id": SAMPLE_MID,
            "Media Download Url": f"https://example.com/{SAMPLE_MID}-main.jpg",
            "Media Type": "Image",
        },
        {
            "Date": "2024-02-03 04:05:06 UTC",
            "Media Id": IMAGE_TWO_MID,
            "Download URL": f"https://example.com/{IMAGE_TWO_MID}.webp",
            "Type": "Photo",
        },
        {
            "Date": "2024-03-04 05:06:07 UTC",
            "Media Id": VIDEO_ONE_MID,
            "Download Link": f"https://example.com/{VIDEO_ONE_MID}.mp4",
            "Type": "Video",
        },
        {
            "Date": "2024-04-05 06:07:08 UTC",
            "Media Id": VIDEO_TWO_MID,
            "Media Download Url": f"https://example.com/{VIDEO_TWO_MID}.mov",
        },
    ]

    (export_dir / "summary.json").write_text(json.dumps(payload), encoding="utf-8")
    (export_dir / "broken.json").write_text("{not-valid-json", encoding="utf-8")
    return export_dir


def _run_ffmpeg(args: list[str]) -> None:
    result = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout or "ffmpeg failed")


def _write_video_export_fixture(root: Path) -> Path:
    export_dir = root / "sample_video_export"
    export_dir.mkdir(parents=True, exist_ok=True)

    _run_ffmpeg(
        [
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=20x20:d=1:r=1",
            "-pix_fmt",
            "yuv420p",
            str(export_dir / f"{VIDEO_ONE_MID}-main.mp4"),
        ]
    )
    Image.new("RGBA", (20, 20), color=(0, 0, 255, 96)).save(export_dir / f"{VIDEO_ONE_MID}-overlay.png", "PNG")

    payload = [
        {
            "Date": "2024-03-04 05:06:07 UTC",
            "Media Id": VIDEO_ONE_MID,
            "Media Download Url": f"https://example.com/{VIDEO_ONE_MID}.mp4",
            "Media Type": "Video",
            "Latitude": 52.52,
            "Longitude": 13.405,
        }
    ]
    (export_dir / "metadata.json").write_text(json.dumps(payload), encoding="utf-8")
    return export_dir


def _write_reconciliation_issue_fixture(root: Path) -> Path:
    export_dir = root / "reconciliation_issue_export"
    export_dir.mkdir(parents=True, exist_ok=True)

    Image.new("RGB", (20, 20), color=(220, 30, 30)).save(export_dir / f"{SAMPLE_MID}-main.jpg", "JPEG")
    _run_ffmpeg(
        [
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=green:s=20x20:d=1:r=1",
            "-pix_fmt",
            "yuv420p",
            str(export_dir / f"{VIDEO_ONE_MID}-main.mp4"),
        ]
    )

    payload = [
        {
            "Date": "2024-01-02 03:04:05 UTC",
            "Media Id": SAMPLE_MID,
            "Media Download Url": f"https://example.com/{SAMPLE_MID}-main.jpg",
            "Media Type": "Image",
        },
        {
            "Date": "2024-02-03 04:05:06 UTC",
            "Media Id": IMAGE_TWO_MID,
            "Media Download Url": f"https://example.com/{IMAGE_TWO_MID}.jpg",
            "Media Type": "Image",
        },
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


@pytest.fixture()
def summary_export_dir(tmp_path: Path) -> Path:
    return _write_summary_fixture(tmp_path)


@pytest.fixture()
def summary_export_zip(tmp_path: Path) -> Path:
    export_dir = _write_summary_fixture(tmp_path)
    zip_path = tmp_path / "summary_export.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for file_path in export_dir.rglob("*"):
            archive.write(file_path, arcname=file_path.relative_to(export_dir))
    return zip_path


@pytest.fixture()
def sample_video_export_dir(tmp_path: Path) -> Path:
    return _write_video_export_fixture(tmp_path)


@pytest.fixture()
def sample_video_export_zip(tmp_path: Path) -> Path:
    export_dir = _write_video_export_fixture(tmp_path)
    zip_path = tmp_path / "sample_video_export.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for file_path in export_dir.rglob("*"):
            archive.write(file_path, arcname=file_path.relative_to(export_dir))
    return zip_path


@pytest.fixture()
def reconciliation_issue_export_dir(tmp_path: Path) -> Path:
    return _write_reconciliation_issue_fixture(tmp_path)
