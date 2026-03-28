from pathlib import Path

from app.cache import CacheRepository
from app.ingest import IngestService
from app.models import ExtractionResult, TranscriptSegment, VideoMetadata


class FakeExtractor:
    def list_playlist_videos(self, playlist_url: str) -> list[str]:
        return [
            "https://www.youtube.com/watch?v=abc123",
            "https://www.youtube.com/watch?v=xyz789",
        ]

    def extract_video(
        self, video_url: str, playlist_ids: list[str] | None = None
    ) -> ExtractionResult:
        video_id = video_url.split("v=", 1)[1]
        metadata = VideoMetadata(
            video_id=video_id,
            video_url=video_url,
            title=f"title-{video_id}",
            channel="channel",
            playlist_ids=playlist_ids or [],
            source_run_at="2026-03-28T00:00:00+00:00",
        )
        segment = TranscriptSegment(
            video_id=video_id,
            video_url=video_url,
            title=metadata.title,
            channel=metadata.channel,
            segment_id=f"{video_id}:0:0",
            start_seconds=0,
            start_timestamp="0:00",
            text=f"text-{video_id}",
            source_run_at=metadata.source_run_at or "",
            playlist_ids=playlist_ids or [],
        )
        return ExtractionResult(metadata=metadata, segments=[segment])


def test_ingest_expands_playlist_and_deduplicates(tmp_path: Path) -> None:
    cache = CacheRepository(tmp_path / "cache")
    service = IngestService(cache, FakeExtractor())
    url_file = tmp_path / "urls.txt"
    url_file.write_text(
        "\n".join(
            [
                "https://www.youtube.com/playlist?list=PL1",
                "https://www.youtube.com/watch?v=abc123",
            ]
        ),
        encoding="utf-8",
    )

    summary = service.ingest_file(url_file)

    assert summary == {"processed": 2, "skipped": 0, "failed": 0}
    manifest = cache.load_manifest()
    assert set(manifest) == {"abc123", "xyz789"}
    assert cache.load_url_index()["https://www.youtube.com/playlist?list=PL1"]["kind"] == "playlist"
    assert cache.read_transcript_artifact("abc123").metadata.title == "title-abc123"
