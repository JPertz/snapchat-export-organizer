from __future__ import annotations

import subprocess
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

    assert summary.metadata_records == 4
    assert summary.total_media == 4
    assert summary.image_count == 2
    assert summary.video_count == 2
    assert len(summary.errors) == 1


def test_analyze_sources_from_zip(summary_export_zip: Path) -> None:
    summary = analyze_sources([summary_export_zip])

    assert summary.metadata_records == 4
    assert summary.total_media == 4
    assert summary.image_count == 2
    assert summary.video_count == 2
    assert len(summary.errors) == 1
