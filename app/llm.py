from __future__ import annotations

from app.indexing.embeddings import OpenAIClient
from app.models import AnswerResult, SearchHit


class AnswerSynthesizer:
    def __init__(self, openai_client: OpenAIClient):
        self.openai_client = openai_client

    def answer(self, question: str, hits: list[SearchHit]) -> AnswerResult:
        if not hits:
            return AnswerResult(
                answer="I could not find enough transcript evidence to answer that question.",
                citations=[],
                warning="No supporting transcript hits were found.",
            )
        prompt = self._build_prompt(question, hits)
        answer_text = self.openai_client.answer(prompt)
        citations = [
            {
                "title": hit.title,
                "video_url": f"{hit.video_url}&t={hit.anchor_start_seconds}s",
                "timestamp": hit.anchor_start_timestamp,
                "chunk_id": hit.chunk_id,
            }
            for hit in hits[:5]
        ]
        return AnswerResult(answer=answer_text, citations=citations)

    def _build_prompt(self, question: str, hits: list[SearchHit]) -> str:
        context_blocks = []
        for hit in hits[:8]:
            window = hit.window_segments or []
            joined_window = " ".join(segment.text for segment in window) if window else hit.text
            context_blocks.append(
                (
                    f"Video: {hit.title}\n"
                    f"Channel: {hit.channel}\n"
                    f"Timestamp Range: {hit.window_start_timestamp}-{hit.window_end_timestamp}\n"
                    f"Anchor Timestamp: {hit.anchor_start_timestamp}\n"
                    f"URL: {hit.video_url}&t={hit.anchor_start_seconds}s\n"
                    f"Transcript: {joined_window}"
                )
            )
        joined_context = "\n\n".join(context_blocks)
        return (
            f"Question: {question}\n\n"
            "Use the transcript evidence below to answer the question.\n"
            "Cite timestamps inline.\n\n"
            f"{joined_context}"
        )
