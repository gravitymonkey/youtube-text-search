from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

from app.cache import CacheRepository
from app.indexing.embeddings import OpenAIClient, SQLiteEmbeddingStore
from app.indexing.keyword import MeilisearchClient
from app.models import SearchHit, TranscriptSegment


class SearchEngine:
    def __init__(
        self,
        cache: CacheRepository,
        keyword_client: MeilisearchClient,
        embedding_store: SQLiteEmbeddingStore,
        openai_client: OpenAIClient,
        retrieval_window: int = 1,
    ):
        self.cache = cache
        self.keyword_client = keyword_client
        self.embedding_store = embedding_store
        self.openai_client = openai_client
        self.retrieval_window = retrieval_window

    def search(
        self,
        query: str,
        *,
        mode: str = "hybrid",
        limit: int = 10,
        video_id: str | None = None,
        video_url: str | None = None,
    ) -> list[SearchHit]:
        if mode == "keyword":
            hits = self.keyword_search(query, limit=limit, video_id=video_id, video_url=video_url)
        elif mode == "semantic":
            hits = self.semantic_search(query, limit=limit, video_id=video_id, video_url=video_url)
        else:
            hits = self.hybrid_search(query, limit=limit, video_id=video_id, video_url=video_url)
        return [self._expand_hit(hit) for hit in hits]

    def keyword_search(
        self, query: str, *, limit: int, video_id: str | None, video_url: str | None
    ) -> list[SearchHit]:
        filters = []
        if video_id:
            filters.append(f'video_id = "{video_id}"')
        if video_url:
            filters.append(f'video_url = "{video_url}"')
        raw_hits = self.keyword_client.search(query, limit=limit, filters=" AND ".join(filters) or None)
        results: list[SearchHit] = []
        for rank, hit in enumerate(raw_hits):
            results.append(
                SearchHit(
                    chunk_id=hit["id"],
                    anchor_segment_id=hit["anchor_segment_id"],
                    video_id=hit["video_id"],
                    video_url=hit["video_url"],
                    title=hit["title"],
                    channel=hit["channel"],
                    anchor_start_seconds=hit["anchor_start_seconds"],
                    anchor_start_timestamp=hit["anchor_start_timestamp"],
                    window_start_seconds=hit["window_start_seconds"],
                    window_end_seconds=hit["window_end_seconds"],
                    window_start_timestamp=hit["window_start_timestamp"],
                    window_end_timestamp=hit["window_end_timestamp"],
                    text=hit["text"],
                    snippet=hit.get("snippet", hit["text"][:240]),
                    segment_ids=hit.get("segment_ids", []),
                    playlist_ids=hit.get("playlist_ids", []),
                    score=1.0 / (rank + 1),
                    source="keyword",
                )
            )
        return results

    def semantic_search(
        self, query: str, *, limit: int, video_id: str | None, video_url: str | None
    ) -> list[SearchHit]:
        query_vector = self.openai_client.embed_texts([query])[0]
        return self.embedding_store.search(
            query_vector, limit=limit, video_id=video_id, video_url=video_url
        )

    def hybrid_search(
        self, query: str, *, limit: int, video_id: str | None, video_url: str | None
    ) -> list[SearchHit]:
        with ThreadPoolExecutor(max_workers=2) as executor:
            keyword_future = executor.submit(
                self.keyword_search,
                query,
                limit=limit,
                video_id=video_id,
                video_url=video_url,
            )
            semantic_future = executor.submit(
                self.semantic_search,
                query,
                limit=limit,
                video_id=video_id,
                video_url=video_url,
            )
        merged: dict[str, SearchHit] = {}
        for source_hits in (keyword_future.result(), semantic_future.result()):
            for rank, hit in enumerate(source_hits):
                fused_score = 1.0 / (rank + 1)
                existing = merged.get(hit.chunk_id)
                if existing is None:
                    merged[hit.chunk_id] = replace(
                        hit,
                        score=fused_score,
                        source=hit.source,
                    )
                    continue
                existing.score += fused_score
                if hit.source not in existing.source.split("+"):
                    existing.source = f"{existing.source}+{hit.source}"
        results = sorted(merged.values(), key=lambda item: item.score, reverse=True)
        return results[:limit]

    def _expand_hit(self, hit: SearchHit) -> SearchHit:
        segments = self.cache.read_video_segments(hit.video_id)
        if not hit.segment_ids:
            return hit
        wanted = set(hit.segment_ids)
        hit.window_segments = [segment for segment in segments if segment.segment_id in wanted]
        return hit
