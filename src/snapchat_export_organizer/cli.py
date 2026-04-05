from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .pipeline import acquire_app_instance_lock, cleanup_stale_app_temp_data, process_sources


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Process Snapchat export ZIP files and folders into merged, metadata-tagged JPG and MP4 files."
    )
    parser.add_argument(
        "sources",
        nargs="+",
        help="ZIP files and/or extracted export folders",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output folder for merged and tagged media",
    )
    args = parser.parse_args()

    try:
        with acquire_app_instance_lock(status=lambda message: print(message, flush=True)):
            cleanup_stale_app_temp_data(status=lambda message: print(message, flush=True))
            stats = process_sources(
                sources=args.sources,
                output_dir=Path(args.output),
                status=lambda message: print(message, flush=True),
            )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr, flush=True)
        raise SystemExit(1) from exc

    print("")
    print("Summary")
    print(f"Metadata records: {stats.discovered_metadata}")
    print(f"Media groups: {stats.discovered_media}")
    print(f"Merged files: {stats.merged_files}")
    print(f"Tagged files: {stats.tagged_files}")
    print(f"Copied without metadata: {stats.skipped_files}")
    print(f"Errors: {len(stats.errors)}")


if __name__ == "__main__":
    main()
