from __future__ import annotations

from pathlib import Path

import piexif

from snapchat_export_organizer.pipeline import process_sources


def _assert_outputs(output_dir: Path) -> None:
    merged_files = list((output_dir / "merged").glob("*.jpg"))
    tagged_files = list((output_dir / "tagged").glob("*.jpg"))

    assert len(merged_files) == 1
    assert len(tagged_files) == 1

    exif_payload = piexif.load(str(tagged_files[0]))
    assert piexif.ExifIFD.DateTimeOriginal in exif_payload["Exif"]
    assert piexif.GPSIFD.GPSLatitude in exif_payload["GPS"]


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
