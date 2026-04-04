from __future__ import annotations

import json
import subprocess
import zipfile
from pathlib import Path

import imageio_ffmpeg
import piexif
from PIL import Image

from snapchat_export_organizer.pipeline import analyze_sources, process_sources


def _assert_outputs(output_dir: Path) -> None:
    image_files = list(output_dir.glob("*.jpg"))

    assert len(image_files) == 1

    exif_payload = piexif.load(str(image_files[0]))
    assert piexif.ExifIFD.DateTimeOriginal in exif_payload["Exif"]
    assert piexif.GPSIFD.GPSLatitude in exif_payload["GPS"]


def _extract_video_frame(video_path: Path, frame_path: Path) -> None:
    result = subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-y",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            str(frame_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout or "ffmpeg frame extraction failed")


def _dump_video_metadata(video_path: Path) -> str:
    result = subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-i",
            str(video_path),
            "-f",
            "ffmetadata",
            "-",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode not in {0, 1}:
        raise RuntimeError(result.stderr or result.stdout or "ffmpeg metadata dump failed")
    return result.stdout + result.stderr


def test_process_sources_from_folder(sample_export_dir: Path, tmp_path: Path) -> None:
    output_dir = tmp_path / "output-folder"

    stats = process_sources([sample_export_dir], output_dir)

    assert stats.discovered_metadata == 1
    assert stats.discovered_media == 1
    assert stats.merged_files == 1
    assert stats.tagged_files == 1
    assert stats.skipped_files == 0
    assert stats.errors == []
    _assert_outputs(output_dir)


def test_process_sources_from_zip(sample_export_zip: Path, tmp_path: Path) -> None:
    output_dir = tmp_path / "output-zip"

    stats = process_sources([sample_export_zip], output_dir)

    assert stats.discovered_metadata == 1
    assert stats.discovered_media == 1
    assert stats.merged_files == 1
    assert stats.tagged_files == 1
    assert stats.skipped_files == 0
    assert stats.errors == []
    _assert_outputs(output_dir)


def test_process_video_sources_from_folder(sample_video_export_dir: Path, tmp_path: Path) -> None:
    output_dir = tmp_path / "output-video-folder"

    stats = process_sources([sample_video_export_dir], output_dir)

    assert stats.discovered_metadata == 1
    assert stats.discovered_media == 1
    assert stats.merged_files == 1
    assert stats.tagged_files == 1
    assert stats.skipped_files == 0
    assert stats.errors == []

    tagged_files = list(output_dir.glob("*.mp4"))
    assert len(tagged_files) == 1

    frame_path = tmp_path / "frame-folder.png"
    _extract_video_frame(tagged_files[0], frame_path)
    pixel = Image.open(frame_path).convert("RGB").getpixel((10, 10))
    assert pixel[2] > 80

    metadata_dump = _dump_video_metadata(tagged_files[0])
    assert "creation_time" in metadata_dump
    assert "2024-03-04T05:06:07" in metadata_dump
    assert "+52.5200+013.4050/" in metadata_dump


def test_process_video_sources_from_zip(sample_video_export_zip: Path, tmp_path: Path) -> None:
    output_dir = tmp_path / "output-video-zip"

    stats = process_sources([sample_video_export_zip], output_dir)

    assert stats.discovered_metadata == 1
    assert stats.discovered_media == 1
    assert stats.merged_files == 1
    assert stats.tagged_files == 1
    assert stats.skipped_files == 0
    assert stats.errors == []

    tagged_files = list(output_dir.glob("*.mp4"))
    assert len(tagged_files) == 1


def test_analyze_sources_from_folder(summary_export_dir: Path) -> None:
    summary = analyze_sources([summary_export_dir])

    assert summary.zip_count == 0
    assert summary.folder_count == 1
    assert summary.metadata_records == 4
    assert summary.total_media == 4
    assert summary.image_count == 2
    assert summary.video_count == 2
    assert summary.scan_complete is True
    assert summary.scan_ready is False
    assert summary.found_media_files == 0
    assert summary.matched_media_files == 0
    assert summary.missing_media_files == 4
    assert summary.orphan_media_files == 0
    assert len(summary.errors) == 1
    assert summary.warnings == []


def test_analyze_sources_from_zip(summary_export_zip: Path) -> None:
    summary = analyze_sources([summary_export_zip])

    assert summary.zip_count == 1
    assert summary.folder_count == 0
    assert summary.metadata_records == 4
    assert summary.total_media == 4
    assert summary.image_count == 2
    assert summary.video_count == 2
    assert summary.scan_complete is True
    assert summary.scan_ready is False
    assert summary.found_media_files == 0
    assert summary.matched_media_files == 0
    assert summary.missing_media_files == 4
    assert summary.orphan_media_files == 0
    assert len(summary.errors) == 1
    assert summary.warnings == []


def test_analyze_sources_ready_from_folder(sample_export_dir: Path) -> None:
    summary = analyze_sources([sample_export_dir])

    assert summary.zip_count == 0
    assert summary.folder_count == 1
    assert summary.metadata_records == 1
    assert summary.total_media == 1
    assert summary.image_count == 1
    assert summary.video_count == 0
    assert summary.scan_complete is True
    assert summary.scan_ready is True
    assert summary.found_media_files == 1
    assert summary.matched_media_files == 1
    assert summary.missing_media_files == 0
    assert summary.orphan_media_files == 0
    assert summary.errors == []
    assert summary.warnings == []


def test_analyze_sources_detects_missing_and_orphan_files(reconciliation_issue_export_dir: Path) -> None:
    summary = analyze_sources([reconciliation_issue_export_dir])

    assert summary.zip_count == 0
    assert summary.folder_count == 1
    assert summary.metadata_records == 2
    assert summary.total_media == 2
    assert summary.image_count == 2
    assert summary.video_count == 0
    assert summary.scan_complete is True
    assert summary.scan_ready is False
    assert summary.found_media_files == 2
    assert summary.matched_media_files == 1
    assert summary.missing_media_files == 1
    assert summary.orphan_media_files == 1
    assert summary.errors == []
    assert summary.warnings == []


def test_analyze_sources_matches_json_from_one_zip_to_media_in_other_folder(tmp_path: Path) -> None:
    metadata_dir = tmp_path / "metadata_export"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    (metadata_dir / "metadata.json").write_text(
        json.dumps(
            [
                {
                    "Date": "2024-01-02 03:04:05 UTC",
                    "Media Id": "11111111-1111-1111-1111-111111111111",
                    "Media Download Url": "https://example.com/11111111-1111-1111-1111-111111111111-main.jpg",
                    "Media Type": "Image",
                }
            ]
        ),
        encoding="utf-8",
    )
    metadata_zip = tmp_path / "metadata_export.zip"
    with zipfile.ZipFile(metadata_zip, "w") as archive:
        archive.write(metadata_dir / "metadata.json", arcname="metadata.json")

    media_dir = tmp_path / "media_export"
    media_dir.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (20, 20), color=(220, 30, 30)).save(
        media_dir / "11111111-1111-1111-1111-111111111111-main.jpg",
        "JPEG",
    )

    summary = analyze_sources([metadata_zip, media_dir])

    assert summary.zip_count == 1
    assert summary.folder_count == 1
    assert summary.metadata_records == 1
    assert summary.total_media == 1
    assert summary.image_count == 1
    assert summary.video_count == 0
    assert summary.scan_complete is True
    assert summary.scan_ready is True
    assert summary.found_media_files == 1
    assert summary.matched_media_files == 1
    assert summary.missing_media_files == 0
    assert summary.orphan_media_files == 0
    assert summary.errors == []
