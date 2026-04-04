from __future__ import annotations

import json
import re
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

import piexif
from PIL import Image, ImageOps

from .models import MediaFiles, MediaMetadata, ProcessStats


StatusCallback = Callable[[str], None]

MID_RE = re.compile(
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})-(main|overlay)\.(jpg|jpeg|png)$",
    re.IGNORECASE,
)


def process_sources(
    sources: Iterable[str | Path],
    output_dir: str | Path,
    status: StatusCallback | None = None,
) -> ProcessStats:
    stats = ProcessStats()
    source_paths = [Path(item).expanduser().resolve() for item in sources]
    output_root = Path(output_dir).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    def log(message: str) -> None:
        if status is not None:
            status(message)

    with tempfile.TemporaryDirectory(prefix="snapchat_export_organizer_") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        log("Preparing inputs...")
        expanded_roots = _expand_sources(source_paths, temp_dir, log)

        if not expanded_roots:
            raise ValueError("No readable ZIP files or folders were provided.")

        log("Loading metadata from JSON files...")
        metadata_map = _load_metadata(expanded_roots, stats, log)
        stats.discovered_metadata = len(metadata_map)

        log("Scanning for Snapchat media files...")
        media_map = _find_media(expanded_roots, stats)
        stats.discovered_media = len(media_map)

        if not media_map:
            raise ValueError("No Snapchat memory images were found in the selected inputs.")

        merged_dir = output_root / "merged"
        final_dir = output_root / "tagged"
        merged_dir.mkdir(parents=True, exist_ok=True)
        final_dir.mkdir(parents=True, exist_ok=True)

        for media in media_map.values():
            output_name = _build_output_name(media.mid, metadata_map.get(media.mid))
            merged_path = merged_dir / output_name
            final_path = final_dir / output_name

            try:
                _merge_media(media, merged_path)
                stats.merged_files += 1

                metadata = metadata_map.get(media.mid)
                if metadata and metadata.captured_at is not None:
                    _write_tagged_image(merged_path, final_path, metadata)
                    stats.tagged_files += 1
                else:
                    shutil.copy2(merged_path, final_path)
                    stats.skipped_files += 1
            except Exception as exc:
                stats.errors.append(f"{media.mid}: {exc}")
                log(f"Error while processing {media.mid}: {exc}")

        log(
            "Finished. "
            f"Merged: {stats.merged_files}, tagged: {stats.tagged_files}, "
            f"copied without metadata: {stats.skipped_files}, errors: {len(stats.errors)}"
        )

    return stats


def _expand_sources(source_paths: list[Path], temp_dir: Path, log: StatusCallback) -> list[Path]:
    roots: list[Path] = []

    for source in source_paths:
        if not source.exists():
            log(f"Skipping missing path: {source}")
            continue

        if source.is_file() and source.suffix.lower() == ".zip":
            extract_dir = temp_dir / source.stem
            extract_dir.mkdir(parents=True, exist_ok=True)
            log(f"Extracting ZIP: {source.name}")
            with zipfile.ZipFile(source) as archive:
                archive.extractall(extract_dir)
            roots.append(extract_dir)
            continue

        if source.is_dir():
            roots.append(source)

    return roots


def _load_metadata(roots: list[Path], stats: ProcessStats, log: StatusCallback) -> dict[str, MediaMetadata]:
    metadata_map: dict[str, MediaMetadata] = {}

    for root in roots:
        for json_path in root.rglob("*.json"):
            try:
                with json_path.open("r", encoding="utf-8") as handle:
                    payload = json.load(handle)
            except Exception as exc:
                stats.errors.append(f"JSON read failed for {json_path}: {exc}")
                continue

            before = len(metadata_map)
            _scan_json(payload, json_path, metadata_map)
            discovered = len(metadata_map) - before
            if discovered:
                log(f"Found {discovered} metadata records in {json_path.name}")

    return metadata_map


def _scan_json(obj: object, source_file: Path, metadata_map: dict[str, MediaMetadata]) -> None:
    if isinstance(obj, dict):
        maybe_metadata = _extract_metadata_record(obj, source_file)
        if maybe_metadata is not None:
            metadata_map[maybe_metadata.mid] = maybe_metadata

        for value in obj.values():
            _scan_json(value, source_file, metadata_map)
        return

    if isinstance(obj, list):
        for item in obj:
            _scan_json(item, source_file, metadata_map)


def _extract_metadata_record(record: dict[str, object], source_file: Path) -> MediaMetadata | None:
    raw_date = _coerce_text(record.get("Date")) or _coerce_text(record.get("Created"))
    raw_url = (
        _coerce_text(record.get("Media Download Url"))
        or _coerce_text(record.get("Download Link"))
        or _coerce_text(record.get("Download URL"))
    )
    raw_mid = _extract_mid_from_text(raw_url) or _extract_mid_from_text(_coerce_text(record.get("Media Id")))

    if raw_mid is None:
        return None

    captured_at = _parse_datetime(raw_date)
    latitude, longitude = _extract_lat_lon(record)

    return MediaMetadata(
        mid=raw_mid,
        captured_at=captured_at,
        latitude=latitude,
        longitude=longitude,
        source_file=source_file,
    )


def _coerce_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _extract_mid_from_text(value: str | None) -> str | None:
    if not value:
        return None

    match = re.search(
        r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
        value,
        re.IGNORECASE,
    )
    return match.group(1).lower() if match else None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None

    known_formats = [
        "%Y-%m-%d %H:%M:%S UTC",
        "%Y-%m-%d %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
    ]

    for fmt in known_formats:
        try:
            parsed = datetime.strptime(value, fmt)
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    return None


def _extract_lat_lon(record: dict[str, object]) -> tuple[float | None, float | None]:
    for lat_key, lon_key in (("Latitude", "Longitude"), ("Lat", "Lng")):
        raw_lat = record.get(lat_key)
        raw_lon = record.get(lon_key)
        if isinstance(raw_lat, (float, int)) and isinstance(raw_lon, (float, int)):
            return float(raw_lat), float(raw_lon)

    location = _coerce_text(record.get("Location"))
    if location:
        match = re.search(r"(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)", location)
        if match:
            return float(match.group(1)), float(match.group(2))

    return None, None


def _find_media(roots: list[Path], stats: ProcessStats) -> dict[str, MediaFiles]:
    media_map: dict[str, MediaFiles] = {}

    for root in roots:
        for file_path in root.rglob("*"):
            if not file_path.is_file():
                continue

            match = MID_RE.search(file_path.name)
            if not match:
                continue

            mid = match.group(1).lower()
            kind = match.group(2).lower()
            current = media_map.get(mid)

            if kind == "main":
                media_map[mid] = MediaFiles(mid=mid, main_path=file_path, overlay_path=current.overlay_path if current else None)
            elif current is not None:
                current.overlay_path = file_path
            else:
                media_map[mid] = MediaFiles(mid=mid, main_path=file_path, overlay_path=file_path)

    cleaned_map: dict[str, MediaFiles] = {}
    for mid, media in media_map.items():
        if media.main_path == media.overlay_path and media.overlay_path is not None:
            stats.errors.append(f"{mid}: overlay found before main image")
            continue
        cleaned_map[mid] = media

    return cleaned_map


def _merge_media(media: MediaFiles, destination: Path) -> None:
    base_image = Image.open(media.main_path)
    base_image = ImageOps.exif_transpose(base_image).convert("RGBA")

    if media.overlay_path is not None:
        overlay = Image.open(media.overlay_path).convert("RGBA")
        if overlay.size != base_image.size:
            overlay = overlay.resize(base_image.size)
        base_image = Image.alpha_composite(base_image, overlay)

    destination.parent.mkdir(parents=True, exist_ok=True)
    base_image.convert("RGB").save(destination, "JPEG", quality=95)


def _write_tagged_image(source_path: Path, destination: Path, metadata: MediaMetadata) -> None:
    image = Image.open(source_path)
    exif_bytes = _build_exif(metadata)
    image.save(destination, "JPEG", quality=95, exif=exif_bytes)


def _build_exif(metadata: MediaMetadata) -> bytes:
    timestamp = metadata.captured_at.astimezone(timezone.utc).strftime("%Y:%m:%d %H:%M:%S")
    zeroth: dict[int, object] = {
        piexif.ImageIFD.DateTime: timestamp,
    }
    exif: dict[int, object] = {
        piexif.ExifIFD.DateTimeOriginal: timestamp,
        piexif.ExifIFD.DateTimeDigitized: timestamp,
    }
    gps: dict[int, object] = {}

    if metadata.latitude is not None and metadata.longitude is not None:
        gps[piexif.GPSIFD.GPSLatitudeRef] = "N" if metadata.latitude >= 0 else "S"
        gps[piexif.GPSIFD.GPSLatitude] = _to_dms(metadata.latitude)
        gps[piexif.GPSIFD.GPSLongitudeRef] = "E" if metadata.longitude >= 0 else "W"
        gps[piexif.GPSIFD.GPSLongitude] = _to_dms(metadata.longitude)

    return piexif.dump({
        "0th": zeroth,
        "Exif": exif,
        "GPS": gps,
        "1st": {},
        "thumbnail": None,
    })


def _to_dms(value: float) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int]]:
    absolute = abs(value)
    degrees = int(absolute)
    minutes_float = (absolute - degrees) * 60
    minutes = int(minutes_float)
    seconds = int(round((minutes_float - minutes) * 60 * 100))
    return ((degrees, 1), (minutes, 1), (seconds, 100))


def _build_output_name(mid: str, metadata: MediaMetadata | None) -> str:
    if metadata and metadata.captured_at is not None:
        prefix = metadata.captured_at.astimezone(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
        return f"{prefix}_{mid}.jpg"
    return f"{mid}.jpg"

