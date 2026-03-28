from __future__ import annotations

from dataclasses import dataclass

from app.models import TranscriptSegment


@dataclass(slots=True)
class TranscriptChunk:
    chunk_id: str
    anchor_segment_id: str
    video_id: str
    video_url: str
    title: str
    channel: str
    anchor_start_seconds: int
    anchor_start_timestamp: str
    window_start_seconds: int
    window_end_seconds: int
    window_start_timestamp: str
    window_end_timestamp: str
    text: str
    snippet: str
    segment_ids: list[str]
    playlist_ids: list[str]


def build_rolling_chunks(
    segments: list[TranscriptSegment], *, before: int, after: int
) -> list[TranscriptChunk]:
    chunks: list[TranscriptChunk] = []
    for index, anchor in enumerate(segments):
        start = max(0, index - before)
        end = min(len(segments), index + after + 1)
        window_segments = segments[start:end]
        text = " ".join(segment.text for segment in window_segments)
        chunks.append(
            TranscriptChunk(
                chunk_id=f"{anchor.segment_id}|w{before}-{after}",
                anchor_segment_id=anchor.segment_id,
                video_id=anchor.video_id,
                video_url=anchor.video_url,
                title=anchor.title,
                channel=anchor.channel,
                anchor_start_seconds=anchor.start_seconds,
                anchor_start_timestamp=anchor.start_timestamp,
                window_start_seconds=window_segments[0].start_seconds,
                window_end_seconds=window_segments[-1].start_seconds,
                window_start_timestamp=window_segments[0].start_timestamp,
                window_end_timestamp=window_segments[-1].start_timestamp,
                text=text,
                snippet=text[:240],
                segment_ids=[segment.segment_id for segment in window_segments],
                playlist_ids=anchor.playlist_ids or [],
            )
        )
    return chunks
