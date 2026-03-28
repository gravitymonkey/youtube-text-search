from pathlib import Path

from app.cache import CacheRepository
from app.indexing.embeddings import SQLiteEmbeddingStore
from app.models import SearchHit, TranscriptSegment, VideoMetadata
from app.search.hybrid import SearchEngine


class FakeKeywordClient:
    def search(self, query: str, limit: int = 10, filters: str | None = None):
        return [
            {
                "id": "abc123:0:0|w1-1",
                "anchor_segment_id": "abc123:0:0",
                "video_id": "abc123",
                "video_url": "https://www.youtube.com/watch?v=abc123",
                "title": "Demo",
                "channel": "Channel",
                "playlist_ids": [],
                "anchor_start_seconds": 0,
                "anchor_start_timestamp": "0:00",
                "window_start_seconds": 0,
                "window_end_seconds": 5,
                "window_start_timestamp": "0:00",
                "window_end_timestamp": "0:05",
                "segment_ids": ["abc123:0:0", "abc123:5:1"],
                "text": "vector databases improve retrieval neighbor context appears here",
                "snippet": "vector databases improve retrieval neighbor context appears here",
            }
        ]


class FakeOpenAIClient:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if "retrieval" in texts[0]:
            return [[1.0, 0.0]]
        return [[0.0, 1.0]]


def _write_segments(cache: CacheRepository) -> None:
    metadata = VideoMetadata(
        video_id="abc123",
        video_url="https://www.youtube.com/watch?v=abc123",
        title="Demo",
        channel="Channel",
        source_run_at="2026-03-28T00:00:00+00:00",
        playlist_ids=[],
    )
    segments = [
        TranscriptSegment(
            video_id="abc123",
            video_url=metadata.video_url,
            title=metadata.title,
            channel=metadata.channel,
            segment_id="abc123:0:0",
            start_seconds=0,
            start_timestamp="0:00",
            text="vector databases improve retrieval",
            source_run_at=metadata.source_run_at or "",
            playlist_ids=[],
        ),
        TranscriptSegment(
            video_id="abc123",
            video_url=metadata.video_url,
            title=metadata.title,
            channel=metadata.channel,
            segment_id="abc123:5:1",
            start_seconds=5,
            start_timestamp="0:05",
            text="neighbor context appears here",
            source_run_at=metadata.source_run_at or "",
            playlist_ids=[],
        ),
    ]
    cache.write_video(metadata, segments)


def test_hybrid_search_merges_and_expands_context(tmp_path: Path) -> None:
    cache = CacheRepository(tmp_path / "cache")
    _write_segments(cache)
    store = SQLiteEmbeddingStore(cache.embeddings_db_path)
    chunk = type(
        "Chunk",
        (),
        {
            "chunk_id": "abc123:0:0|w1-1",
            "anchor_segment_id": "abc123:0:0",
            "video_id": "abc123",
            "video_url": "https://www.youtube.com/watch?v=abc123",
            "title": "Demo",
            "channel": "Channel",
            "anchor_start_seconds": 0,
            "anchor_start_timestamp": "0:00",
            "window_start_seconds": 0,
            "window_end_seconds": 5,
            "window_start_timestamp": "0:00",
            "window_end_timestamp": "0:05",
            "text": "vector databases improve retrieval neighbor context appears here",
            "snippet": "vector databases improve retrieval neighbor context appears here",
            "segment_ids": ["abc123:0:0", "abc123:5:1"],
            "playlist_ids": [],
        },
    )()
    store.upsert_chunk(chunk, [1.0, 0.0])
    engine = SearchEngine(
        cache=cache,
        keyword_client=FakeKeywordClient(),
        embedding_store=store,
        openai_client=FakeOpenAIClient(),
        retrieval_window=1,
    )

    hits = engine.search("retrieval", mode="hybrid", limit=5)

    assert len(hits) == 1
    assert hits[0].source in {"keyword+semantic", "semantic+keyword"}
    assert hits[0].window_segments is not None
    assert len(hits[0].window_segments) == 2
    assert hits[0].window_start_timestamp == "0:00"
    assert hits[0].window_end_timestamp == "0:05"
