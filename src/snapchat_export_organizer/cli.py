from __future__ import annotations

import argparse
from pathlib import Path

from .pipeline import process_sources


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Process Snapchat export ZIP files and folders into merged, EXIF-tagged JPG files."
    )
    parser.add_argument(
        "sources",
        nargs="+",
        help="ZIP files and/or extracted export folders",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output folder for merged and tagged images",
    )
    args = parser.parse_args()

    stats = process_sources(
        sources=args.sources,
        output_dir=Path(args.output),
        status=lambda message: print(message, flush=True),
    )

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

