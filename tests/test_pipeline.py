from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

import imageio_ffmpeg
import piexif
import pytest
from PIL import Image

import snapchat_export_organizer.pipeline as pipeline
from snapchat_export_organizer.pipeline import (
    ALREADY_RUNNING_MESSAGE,
    acquire_app_instance_lock,
    analyze_sources,
    cleanup_stale_app_temp_data,
    process_sources,
)


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
    assert list(output_dir.glob("*.seo.part")) == []


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
    assert list(output_dir.glob("*.seo.part")) == []


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
    assert list(output_dir.glob("*.seo.part")) == []


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
    assert list(output_dir.glob("*.seo.part")) == []


def test_process_sources_reports_live_progress(progress_export_dir: Path, tmp_path: Path) -> None:
    output_dir = tmp_path / "output-progress"
    progress_updates = []

    stats = process_sources(
        [progress_export_dir],
        output_dir,
        progress=lambda state: progress_updates.append(state),
    )

    assert stats.errors == []
    assert progress_updates
    assert progress_updates[0].phase == "preparing"
    assert any(item.phase == "loading_metadata" for item in progress_updates)
    assert any(item.phase == "scanning_media" for item in progress_updates)
    assert any(item.phase == "processing" and item.total_files == 4 for item in progress_updates)
    assert any(
        item.phase == "processing"
        and item.completed_files == 3
        and item.files_left == 1
        and item.estimated_remaining_seconds is not None
        for item in progress_updates
    )
    final_progress = progress_updates[-1]
    assert final_progress.phase == "completed"
    assert final_progress.total_files == 4
    assert final_progress.completed_files == 4
    assert final_progress.files_left == 0
    assert final_progress.progress_percent == 100.0
    assert final_progress.estimated_remaining_seconds is None


def test_process_sources_uses_system_temp_and_cleans_workspace(
    sample_export_zip: Path,
    tmp_path: Path,
    monkeypatch,
) -> None:
    fake_temp_root = tmp_path / "system-temp"
    output_dir = tmp_path / "output-system-temp"

    monkeypatch.setattr(pipeline.tempfile, "gettempdir", lambda: str(fake_temp_root))

    stats = process_sources([sample_export_zip], output_dir)

    assert stats.errors == []
    jobs_root = fake_temp_root / "snapchat_export_organizer" / "jobs"
    assert jobs_root == fake_temp_root / "snapchat_export_organizer" / "jobs"
    assert not jobs_root.exists() or list(jobs_root.iterdir()) == []
    assert list(output_dir.glob("*.seo.part")) == []


def test_process_sources_removes_stale_output_stage_files(sample_export_dir: Path, tmp_path: Path) -> None:
    output_dir = tmp_path / "output-stale-stage"
    output_dir.mkdir(parents=True, exist_ok=True)
    stale_stage = output_dir / "old-file.jpg.seo.part"
    stale_stage.write_bytes(b"stale")

    stats = process_sources([sample_export_dir], output_dir)

    assert stats.errors == []
    assert stale_stage.exists() is False
    assert list(output_dir.glob("*.seo.part")) == []


def test_process_sources_cleans_failed_output_stage_files(sample_export_dir: Path, tmp_path: Path, monkeypatch) -> None:
    output_dir = tmp_path / "output-cleanup-on-error"

    def failing_write(media_kind: str, source_path: Path, destination: Path, metadata) -> None:
        destination.write_bytes(b"partial-output")
        raise RuntimeError("metadata write exploded")

    monkeypatch.setattr(pipeline, "_write_tagged_media", failing_write)

    stats = process_sources([sample_export_dir], output_dir)

    assert len(stats.errors) == 1
    assert "metadata write exploded" in stats.errors[0]
    assert list(output_dir.glob("*.seo.part")) == []


def test_cleanup_stale_app_temp_data_removes_old_workspaces(tmp_path: Path, monkeypatch) -> None:
    fake_temp_root = tmp_path / "system-temp"
    stale_workspace = fake_temp_root / "snapchat_export_organizer" / "jobs" / "old-job"
    stale_workspace.mkdir(parents=True, exist_ok=True)
    (stale_workspace / "artifact.tmp").write_text("stale", encoding="utf-8")

    monkeypatch.setattr(pipeline.tempfile, "gettempdir", lambda: str(fake_temp_root))

    cleanup_stale_app_temp_data()

    assert stale_workspace.exists() is False
    jobs_root = fake_temp_root / "snapchat_export_organizer" / "jobs"
    assert jobs_root.exists() is False or list(jobs_root.iterdir()) == []


def test_create_temp_work_dir_never_uses_repo_or_home(tmp_path: Path, monkeypatch) -> None:
    fake_temp_root = tmp_path / "system-temp"
    monkeypatch.setattr(pipeline.tempfile, "gettempdir", lambda: str(fake_temp_root))

    work_dir = pipeline._create_temp_work_dir()
    try:
        expected_root = fake_temp_root / "snapchat_export_organizer" / "jobs"
        assert expected_root in work_dir.parents
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def test_build_output_stage_path_keeps_valid_video_extension(tmp_path: Path) -> None:
    final_path = tmp_path / "movie.mp4"

    stage_path = pipeline._build_output_stage_path(final_path, "video")

    assert stage_path.name == "movie.seo-stage.mp4"
    assert stage_path.suffix == ".mp4"


def test_build_output_stage_path_marks_image_stage_files(tmp_path: Path) -> None:
    final_path = tmp_path / "photo.jpg"

    stage_path = pipeline._build_output_stage_path(final_path, "image")

    assert stage_path.name == "photo.jpg.seo.part"


def test_acquire_app_instance_lock_blocks_second_start(tmp_path: Path, monkeypatch) -> None:
    fake_temp_root = Path(tempfile.mkdtemp(prefix="seo-lock-test-"))
    lock_path = fake_temp_root / "snapchat_export_organizer" / "instance.lock"

    monkeypatch.setattr(pipeline, "_instance_lock_path", lambda: lock_path)
    monkeypatch.setattr(pipeline.os, "open", lambda path, flags: (_ for _ in ()).throw(FileExistsError()))
    monkeypatch.setattr(pipeline, "_read_instance_lock_metadata", lambda path: {"pid": os.getpid()})
    monkeypatch.setattr(pipeline, "_is_process_active", lambda pid: True)

    with pytest.raises(RuntimeError, match=ALREADY_RUNNING_MESSAGE):
        acquire_app_instance_lock()


def test_acquire_app_instance_lock_removes_stale_lock(tmp_path: Path, monkeypatch) -> None:
    fake_temp_root = Path(tempfile.mkdtemp(prefix="seo-lock-test-"))
    lock_path = fake_temp_root / "snapchat_export_organizer" / "instance.lock"
    open_calls = {"count": 0}
    real_os_open = os.open
    acquired_lock_path = fake_temp_root / "acquired-instance.lock"

    def fake_open(path, flags):
        open_calls["count"] += 1
        if open_calls["count"] == 1:
            raise FileExistsError()
        return real_os_open(acquired_lock_path, flags)

    monkeypatch.setattr(pipeline, "_instance_lock_path", lambda: lock_path)
    monkeypatch.setattr(pipeline.os, "open", fake_open)
    monkeypatch.setattr(pipeline, "_read_instance_lock_metadata", lambda path: {"pid": 999999})
    monkeypatch.setattr(pipeline, "_is_process_active", lambda pid: False)
    deleted = {"called": False}

    def fake_delete(path, attempts=6, delay_seconds=0.1):
        deleted["called"] = True
        return True

    monkeypatch.setattr(pipeline, "_delete_with_retries", fake_delete)

    lock = acquire_app_instance_lock()
    assert lock.path == lock_path
    assert deleted["called"] is True
    lock.release()
    acquired_lock_path.unlink(missing_ok=True)


def test_analyze_sources_from_folder(summary_export_dir: Path) -> None:
    summary = analyze_sources([summary_export_dir])

    assert summary.zip_count == 0
    assert summary.folder_count == 1
    assert summary.source_item_count == 2
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
    assert summary.source_item_count == 2
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
    assert summary.source_item_count == 3
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
    assert summary.source_item_count == 3
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
    assert summary.source_item_count == 2
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


def test_analyze_sources_extracts_mid_from_snapchat_query_parameter(tmp_path: Path) -> None:
    export_dir = tmp_path / "snapchat_export"
    export_dir.mkdir(parents=True, exist_ok=True)

    media_mid = "a0ba75ba-71d8-f337-1f28-ad5acb620872"
    (export_dir / f"{media_mid}-main.mp4").write_bytes(b"fake-video")
    payload = {
        "Saved Media": [
            {
                "Date": "2026-03-04 14:13:55 UTC",
                "Media Type": "Video",
                "Location": "Latitude, Longitude: 50.13433, 8.609106",
                "Download Link": (
                    "https://app.snapchat.com/dmd/memories"
                    "?uid=8315ef08-8c3f-4fd3-a188-36f987eb7d81"
                    "&sid=37b805b8-1ae6-a061-6e5a-10b21b27ee03"
                    f"&mid={media_mid}"
                    "&ts=1772638639856"
                ),
                "Media Download Url": (
                    "https://us-east1-aws.api.snapchat.com/dmd/mm"
                    "?uid=8315ef08-8c3f-4fd3-a188-36f987eb7d81"
                    "&sid=37b805b8-1ae6-a061-6e5a-10b21b27ee03"
                    f"&mid={media_mid}"
                    "&ts=1772638639856"
                ),
            }
        ]
    }
    (export_dir / "memories_history.json").write_text(json.dumps(payload), encoding="utf-8")

    summary = analyze_sources([export_dir])

    assert summary.metadata_records == 1
    assert summary.source_item_count == 2
    assert summary.total_media == 1
    assert summary.image_count == 0
    assert summary.video_count == 1
    assert summary.matched_media_files == 1
    assert summary.missing_media_files == 0
    assert summary.orphan_media_files == 0
    assert summary.scan_ready is True


def test_process_video_sources_without_overlay(sample_video_no_overlay_export_dir: Path, tmp_path: Path) -> None:
    output_dir = tmp_path / "output-video-no-overlay"

    stats = process_sources([sample_video_no_overlay_export_dir], output_dir)

    assert stats.discovered_metadata == 1
    assert stats.discovered_media == 1
    assert stats.merged_files == 1
    assert stats.tagged_files == 1
    assert stats.skipped_files == 0
    assert stats.errors == []

    tagged_files = list(output_dir.glob("*.mp4"))
    assert len(tagged_files) == 1

    metadata_dump = _dump_video_metadata(tagged_files[0])
    assert "creation_time" in metadata_dump
    assert "2024-04-05T06:07:08" in metadata_dump
    assert list(output_dir.glob("*.seo-stage.mp4")) == []


def test_parse_datetime_handles_no_timezone() -> None:
    result = pipeline._parse_datetime("2024-01-02 03:04:05")
    assert result is not None
    assert result.year == 2024
    assert result.month == 1
    assert result.day == 2
    assert result.hour == 3
    assert result.tzinfo is not None


def test_parse_datetime_handles_date_only() -> None:
    result = pipeline._parse_datetime("2024-06-15")
    assert result is not None
    assert result.year == 2024
    assert result.month == 6
    assert result.day == 15
    assert result.tzinfo is not None


def test_parse_datetime_handles_iso_with_utc_offset() -> None:
    result = pipeline._parse_datetime("2024-01-02T05:04:05+02:00")
    assert result is not None
    assert result.hour == 3
    assert result.tzinfo is not None


def test_parse_datetime_handles_iso_with_milliseconds_and_offset() -> None:
    result = pipeline._parse_datetime("2024-01-02T03:04:05.123+00:00")
    assert result is not None
    assert result.hour == 3
    assert result.minute == 4


def test_parse_datetime_returns_none_for_garbage() -> None:
    assert pipeline._parse_datetime("not-a-date") is None
    assert pipeline._parse_datetime("") is None
    assert pipeline._parse_datetime(None) is None


def test_extract_lat_lon_handles_string_values() -> None:
    result = pipeline._extract_lat_lon({"Latitude": "52.52", "Longitude": "13.405"})
    assert result == (52.52, 13.405)


def test_extract_lat_lon_handles_lowercase_keys() -> None:
    result = pipeline._extract_lat_lon({"lat": 48.8566, "lon": 2.3522})
    assert result == (48.8566, 2.3522)


def test_extract_lat_lon_handles_dms_format() -> None:
    result = pipeline._extract_lat_lon({"Location": '52° 31\' 12" N, 13° 24\' 18" E'})
    assert result is not None
    lat, lon = result
    assert abs(lat - 52.52) < 0.01
    assert abs(lon - 13.405) < 0.01


def test_extract_lat_lon_handles_dms_south_west() -> None:
    result = pipeline._extract_lat_lon({"Location": '33° 51\' 54" S, 151° 12\' 36" W'})
    assert result is not None
    lat, lon = result
    assert lat < 0
    assert lon < 0
