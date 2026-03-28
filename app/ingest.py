from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.cache import CacheRepository
from app.extractors.base import TranscriptExtractionError, TranscriptExtractor
from app.models import ManifestEntry
from app.url_inputs import parse_input_file, playlist_id_from_url, video_id_from_url


class IngestService:
    """Batch URL ingestion service backed by the shared cache artifact layout."""

    def __init__(
        self,
        cache: CacheRepository,
        extractor: TranscriptExtractor,
        *,
        playlist_max_videos: int | None = None,
    ):
        self.cache = cache
        self.extractor = extractor
        self.playlist_max_videos = playlist_max_videos

    def ingest_file(self, url_file: str | Path, *, force: bool = False) -> dict[str, int]:
        targets = parse_input_file(url_file)
        video_to_playlists: dict[str, set[str]] = {}
        videos: list[str] = []
        for target in targets:
            if target.kind == "playlist":
                playlist_id = playlist_id_from_url(target.normalized_url)
                playlist_videos = self.extractor.list_playlist_videos(target.normalized_url)
                if self.playlist_max_videos and self.playlist_max_videos > 0:
                    playlist_videos = playlist_videos[: self.playlist_max_videos]
                self.cache.write_playlist(playlist_id, playlist_videos)
                self.cache.update_url_index(
                    target.normalized_url,
                    {
                        "kind": "playlist",
                        "playlist_id": playlist_id,
                        "video_urls": playlist_videos,
                    },
                )
                for video_url in playlist_videos:
                    videos.append(video_url)
                    video_to_playlists.setdefault(video_url, set()).add(playlist_id)
            else:
                videos.append(target.normalized_url)
                video_to_playlists.setdefault(target.normalized_url, set())
        seen_videos: set[str] = set()
        summary = {"processed": 0, "skipped": 0, "failed": 0}
        for video_url in videos:
            if video_url in seen_videos:
                continue
            seen_videos.add(video_url)
            playlist_ids = sorted(video_to_playlists.get(video_url, set()))
            if self._should_skip(video_url, force=force):
                summary["skipped"] += 1
                continue
            try:
                result = self.extractor.extract_video(video_url, playlist_ids=playlist_ids)
                artifact_dir = self.cache.persist_transcript_artifact(result)
                self.cache.update_url_index(
                    video_url,
                    {
                        "kind": "video",
                        "video_id": result.metadata.video_id,
                        "playlist_ids": playlist_ids,
                        "cache_dir": str(artifact_dir),
                    },
                )
                self.cache.upsert_manifest_entry(
                    ManifestEntry(
                        url=video_url,
                        video_id=result.metadata.video_id,
                        kind="video",
                        content_hash=self.cache.compute_content_hash(video_url),
                        status="success",
                        error=None,
                        last_attempt_at=self._now(),
                        last_success_at=self._now(),
                        playlist_ids=playlist_ids,
                    )
                )
                summary["processed"] += 1
            except TranscriptExtractionError as exc:
                video_id = video_id_from_url(video_url)
                self.cache.upsert_manifest_entry(
                    ManifestEntry(
                        url=video_url,
                        video_id=video_id,
                        kind="video",
                        content_hash=self.cache.compute_content_hash(video_url),
                        status="failed",
                        error=str(exc),
                        last_attempt_at=self._now(),
                        last_success_at=None,
                        playlist_ids=playlist_ids,
                    )
                )
                summary["failed"] += 1
        return summary

    def _should_skip(self, video_url: str, *, force: bool) -> bool:
        if force:
            return False
        video_id = video_id_from_url(video_url)
        entry = self.cache.get_manifest_entry(video_id)
        if not entry:
            return False
        return (
            entry.get("status") == "success"
            and entry.get("content_hash") == self.cache.compute_content_hash(video_url)
        )

    def _now(self) -> str:
        return datetime.now(UTC).isoformat()
