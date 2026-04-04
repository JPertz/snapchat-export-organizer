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
    main_path: Path
    overlay_path: Path | None = None


@dataclass(slots=True)
class ProcessStats:
    discovered_metadata: int = 0
    discovered_media: int = 0
    merged_files: int = 0
    tagged_files: int = 0
    skipped_files: int = 0
    errors: list[str] = field(default_factory=list)

