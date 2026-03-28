#!/usr/bin/env python3
"""Simple single-URL entrypoint for transcript extraction.

Usage:
    python extract_transcript.py "https://www.youtube.com/watch?v=..."
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.cache import CacheRepository
from app.config import load_settings
from app.extractors.playwright_extractor import PlaywrightYouTubeExtractor


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="extract_transcript.py",
        description="Extract one YouTube video transcript with timestamps.",
    )
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument(
        "--format",
        choices=["json", "jsonl", "txt"],
        default="json",
        help="Output format for the extracted transcript",
    )
    parser.add_argument(
        "--output",
        help="Optional output file path. Defaults to stdout.",
    )
    parser.add_argument(
        "--cache-write",
        action="store_true",
        help="Also persist the extracted transcript into the standard cache layout.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = load_settings()
    cache = CacheRepository(settings.cache_dir)
    extractor = PlaywrightYouTubeExtractor(
        headless=settings.playwright_headless,
        timeout_ms=settings.playwright_timeout_ms,
        debug_dir=settings.cache_dir / "debug",
    )
    result = extractor.extract_video(args.url)
    artifact_dir = None
    if args.cache_write:
        artifact_dir = cache.persist_transcript_artifact(result)

    if args.format == "json":
        payload = {
            "metadata": result.metadata.to_dict(),
            "segments": [segment.to_dict() for segment in result.segments],
        }
        if artifact_dir is not None:
            payload["artifact_dir"] = str(artifact_dir)
        rendered = json.dumps(payload, indent=2, sort_keys=True)
    elif args.format == "jsonl":
        rendered = "\n".join(
            json.dumps(segment.to_dict(), sort_keys=True) for segment in result.segments
        )
    else:
        rendered = "\n".join(
            f"{segment.start_timestamp}\t{segment.text}" for segment in result.segments
        )

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            rendered + ("" if rendered.endswith("\n") else "\n"),
            encoding="utf-8",
        )
    else:
        print(rendered)


if __name__ == "__main__":
    main()
