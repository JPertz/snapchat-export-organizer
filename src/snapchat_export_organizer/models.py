from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(slots=True)
class MediaMetadata:
    mid: str
    captured_at: datetime | None
    latitude: float | None = None
    longitude: float | None = None
    source_file: Path | None = None


@dataclass(slots=True)
class MediaFiles:
    mid: str
    media_kind: str
    main_path: Path | None = None
    overlay_path: Path | None = None


@dataclass(slots=True)
class ProcessStats:
    discovered_metadata: int = 0
    discovered_media: int = 0
    merged_files: int = 0
    tagged_files: int = 0
    skipped_files: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class MediaSummary:
    zip_count: int = 0
    folder_count: int = 0
    metadata_records: int = 0
    total_media: int = 0
    image_count: int = 0
    video_count: int = 0
    scan_complete: bool = False
    scan_ready: bool = False
    found_media_files: int = 0
    matched_media_files: int = 0
    missing_media_files: int = 0
    orphan_media_files: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
