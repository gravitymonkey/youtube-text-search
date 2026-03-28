from pathlib import Path

from app.cache import CacheRepository
from app.models import ExtractionResult, TranscriptSegment, VideoMetadata


def test_cache_repository_round_trips_video_data(tmp_path: Path) -> None:
    cache = CacheRepository(tmp_path / "cache")
    metadata = VideoMetadata(
        video_id="abc123",
        video_url="https://www.youtube.com/watch?v=abc123",
        title="Demo",
        channel="Channel",
        playlist_ids=["PL1"],
        source_run_at="2026-03-28T00:00:00+00:00",
    )
    segment = TranscriptSegment(
        video_id="abc123",
        video_url=metadata.video_url,
        title=metadata.title,
        channel=metadata.channel,
        segment_id="abc123:12:0",
        start_seconds=12,
        start_timestamp="0:12",
        text="hello world",
        source_run_at=metadata.source_run_at or "",
        playlist_ids=["PL1"],
    )
    cache.persist_transcript_artifact(
        ExtractionResult(metadata=metadata, segments=[segment])
    )

    assert cache.read_video_meta("abc123")["title"] == "Demo"
    segments = cache.read_video_segments("abc123")
    assert len(segments) == 1
    assert segments[0].text == "hello world"


def test_cache_repository_reads_full_artifact(tmp_path: Path) -> None:
    cache = CacheRepository(tmp_path / "cache")
    metadata = VideoMetadata(
        video_id="abc123",
        video_url="https://www.youtube.com/watch?v=abc123",
        title="Demo",
        channel="Channel",
        playlist_ids=["PL1"],
        source_run_at="2026-03-28T00:00:00+00:00",
    )
    segment = TranscriptSegment(
        video_id="abc123",
        video_url=metadata.video_url,
        title=metadata.title,
        channel=metadata.channel,
        segment_id="abc123:12:0",
        start_seconds=12,
        start_timestamp="0:12",
        text="hello world",
        source_run_at=metadata.source_run_at or "",
        playlist_ids=["PL1"],
    )
    cache.persist_transcript_artifact(
        ExtractionResult(metadata=metadata, segments=[segment])
    )

    artifact = cache.read_transcript_artifact("abc123")
    assert artifact.metadata.title == "Demo"
    assert artifact.segments[0].segment_id == "abc123:12:0"
