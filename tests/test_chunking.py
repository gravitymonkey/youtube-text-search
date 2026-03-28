from app.chunking import build_rolling_chunks
from app.models import TranscriptSegment


def test_build_rolling_chunks_uses_anchor_and_neighbor_rows() -> None:
    segments = [
        TranscriptSegment(
            video_id="vid",
            video_url="https://youtube.com/watch?v=vid",
            title="Demo",
            channel="Channel",
            segment_id=f"vid:{i}:0",
            start_seconds=i,
            start_timestamp=f"0:0{i}",
            text=f"text-{i}",
            source_run_at="2026-03-28T00:00:00+00:00",
            playlist_ids=[],
        )
        for i in range(6)
    ]
    chunks = build_rolling_chunks(segments, before=2, after=2)
    assert len(chunks) == 6
    middle = chunks[3]
    assert middle.anchor_segment_id == "vid:3:0"
    assert middle.window_start_seconds == 1
    assert middle.window_end_seconds == 5
    assert middle.segment_ids == ["vid:1:0", "vid:2:0", "vid:3:0", "vid:4:0", "vid:5:0"]
    assert "text-3" in middle.text
