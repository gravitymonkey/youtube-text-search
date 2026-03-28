from __future__ import annotations

import json
from typing import Any
from urllib import error, request

from app.cache import CacheRepository
from app.chunking import build_rolling_chunks


class MeilisearchClient:
    def __init__(self, host: str, api_key: str, index_name: str):
        self.host = host.rstrip("/")
        self.api_key = api_key
        self.index_name = index_name

    def _request(self, method: str, path: str, payload: Any | None = None) -> Any:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = request.Request(
            f"{self.host}{path}", data=body, headers=headers, method=method
        )
        try:
            with request.urlopen(req) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "ignore")
            raise RuntimeError(f"Meilisearch request failed: {exc.code} {detail}") from exc

    def ensure_index(self) -> None:
        self._request(
            "POST",
            "/indexes",
            {"uid": self.index_name, "primaryKey": "id"},
        )

    def configure(self) -> None:
        self._request(
            "PATCH",
            f"/indexes/{self.index_name}/settings",
            {
                "searchableAttributes": ["text", "title", "channel", "video_id"],
                "filterableAttributes": ["video_id", "video_url", "playlist_ids"],
                "sortableAttributes": ["anchor_start_seconds", "window_start_seconds"],
                "displayedAttributes": [
                    "id",
                    "anchor_segment_id",
                    "video_id",
                    "video_url",
                    "title",
                    "channel",
                    "playlist_ids",
                    "anchor_start_seconds",
                    "anchor_start_timestamp",
                    "window_start_seconds",
                    "window_end_seconds",
                    "window_start_timestamp",
                    "window_end_timestamp",
                    "segment_ids",
                    "text",
                    "snippet",
                ],
                "rankingRules": [
                    "words",
                    "typo",
                    "proximity",
                    "attribute",
                    "sort",
                    "exactness",
                ],
            },
        )

    def add_documents(self, documents: list[dict[str, Any]]) -> None:
        self._request("POST", f"/indexes/{self.index_name}/documents", documents)

    def search(
        self, query: str, limit: int = 10, filters: str | None = None
    ) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"q": query, "limit": limit}
        if filters:
            payload["filter"] = filters
        response = self._request("POST", f"/indexes/{self.index_name}/search", payload)
        return response.get("hits", [])


class KeywordIndexer:
    def __init__(
        self,
        cache: CacheRepository,
        client: MeilisearchClient,
        *,
        window_before: int,
        window_after: int,
    ):
        self.cache = cache
        self.client = client
        self.window_before = window_before
        self.window_after = window_after

    def build_documents(self) -> list[dict[str, Any]]:
        documents: list[dict[str, Any]] = []
        for video_id in self.cache.iter_video_ids():
            segments = self.cache.read_video_segments(video_id)
            chunks = build_rolling_chunks(
                segments, before=self.window_before, after=self.window_after
            )
            documents.extend(self._chunk_to_document(chunk) for chunk in chunks)
        return documents

    def index(self) -> int:
        try:
            self.client.ensure_index()
        except RuntimeError as exc:
            if "index_already_exists" not in str(exc):
                raise
        self.client.configure()
        documents = self.build_documents()
        if documents:
            self.client.add_documents(documents)
        return len(documents)

    def _chunk_to_document(self, chunk) -> dict[str, Any]:
        return {
            "id": chunk.chunk_id,
            "anchor_segment_id": chunk.anchor_segment_id,
            "video_id": chunk.video_id,
            "video_url": chunk.video_url,
            "title": chunk.title,
            "channel": chunk.channel,
            "playlist_ids": chunk.playlist_ids,
            "anchor_start_seconds": chunk.anchor_start_seconds,
            "anchor_start_timestamp": chunk.anchor_start_timestamp,
            "window_start_seconds": chunk.window_start_seconds,
            "window_end_seconds": chunk.window_end_seconds,
            "window_start_timestamp": chunk.window_start_timestamp,
            "window_end_timestamp": chunk.window_end_timestamp,
            "segment_ids": chunk.segment_ids,
            "text": chunk.text,
            "snippet": chunk.snippet,
        }
