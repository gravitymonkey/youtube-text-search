from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(slots=True)
class InputTarget:
    raw_url: str
    normalized_url: str
    kind: str


@dataclass(slots=True)
class VideoMetadata:
    video_id: str
    video_url: str
    title: str
    channel: str
    duration_seconds: int | None = None
    source_run_at: str | None = None
    playlist_ids: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TranscriptSegment:
    video_id: str
    video_url: str
    title: str
    channel: str
    segment_id: str
    start_seconds: int
    start_timestamp: str
    text: str
    source_run_at: str
    playlist_ids: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ExtractionResult:
    metadata: VideoMetadata
    segments: list[TranscriptSegment]


@dataclass(slots=True)
class ManifestEntry:
    url: str
    video_id: str
    kind: str
    content_hash: str
    status: str
    error: str | None
    last_attempt_at: str
    last_success_at: str | None
    playlist_ids: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SearchHit:
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
    score: float
    source: str
    window_segments: list[TranscriptSegment] | None = None


@dataclass(slots=True)
class AnswerResult:
    answer: str
    citations: list[dict[str, Any]]
    warning: str | None = None
