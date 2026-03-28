from __future__ import annotations

from typing import Protocol

from app.models import ExtractionResult


class TranscriptExtractionError(RuntimeError):
    pass


class TranscriptExtractor(Protocol):
    def list_playlist_videos(self, playlist_url: str) -> list[str]:
        ...

    def extract_video(self, video_url: str, playlist_ids: list[str] | None = None) -> ExtractionResult:
        ...
