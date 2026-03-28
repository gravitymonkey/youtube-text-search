"""Playwright-based YouTube transcript extraction.

This module is intentionally explicit and slightly defensive because YouTube's
DOM changes regularly. The maintenance strategy is:

1. Keep selectors concentrated in a small number of methods.
2. Prefer modern, specific selectors before broad text-based fallbacks.
3. Persist rich debug artifacts for every failed run so selector drift can be
   fixed from saved HTML and screenshots instead of guesswork.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from tempfile import mkdtemp
from urllib.parse import parse_qs, urlparse

from app.extractors.base import TranscriptExtractionError
from app.models import ExtractionResult, TranscriptSegment, VideoMetadata
from app.url_inputs import (
    canonical_video_url,
    playlist_id_from_url,
    video_id_from_url,
)


class PlaywrightYouTubeExtractor:
    """Browser-first extractor for YouTube videos and playlists."""

    def __init__(
        self,
        *,
        headless: bool = True,
        timeout_ms: int = 30000,
        debug_dir: Path | None = None,
    ):
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.debug_dir = debug_dir
        self._current_artifact_dir: Path | None = None
        self._debug_steps: list[dict[str, object]] = []

    def list_playlist_videos(self, playlist_url: str) -> list[str]:
        """Expand a playlist page into canonical video URLs."""
        page_data = self._run_browser(self._scrape_playlist_page, playlist_url)
        seen: set[str] = set()
        urls: list[str] = []
        for href in page_data:
            video_id = self._video_id_from_href(href)
            if not video_id:
                continue
            url = canonical_video_url(video_id)
            if url in seen:
                continue
            seen.add(url)
            urls.append(url)
        if not urls:
            raise TranscriptExtractionError(
                f"No playlist videos found for {playlist_url}. The YouTube UI may have changed."
            )
        return urls

    def extract_video(
        self, video_url: str, playlist_ids: list[str] | None = None
    ) -> ExtractionResult:
        """Extract normalized metadata and transcript segments for one video."""
        scraped = self._run_browser(self._scrape_video_page, video_url)
        video_id = video_id_from_url(video_url)
        title = scraped["title"] or video_id
        channel = scraped["channel"] or "Unknown"
        source_run_at = datetime.now(UTC).isoformat()
        metadata = VideoMetadata(
            video_id=video_id,
            video_url=video_url,
            title=title,
            channel=channel,
            duration_seconds=scraped["duration_seconds"],
            source_run_at=source_run_at,
            playlist_ids=playlist_ids or [],
        )
        segments: list[TranscriptSegment] = []
        for index, row in enumerate(scraped["rows"]):
            timestamp = row["timestamp"]
            seconds = self._timestamp_to_seconds(timestamp)
            text = " ".join(row["text"].split())
            if not text:
                continue
            segments.append(
                TranscriptSegment(
                    video_id=video_id,
                    video_url=video_url,
                    title=title,
                    channel=channel,
                    segment_id=f"{video_id}:{seconds}:{index}",
                    start_seconds=seconds,
                    start_timestamp=timestamp,
                    text=text,
                    source_run_at=source_run_at,
                    playlist_ids=playlist_ids or [],
                )
            )
        if not segments:
            raise TranscriptExtractionError(
                f"No transcript rows extracted for {video_url}. Transcript may be unavailable."
            )
        return ExtractionResult(metadata=metadata, segments=segments)

    def extract_url_summary(self, url: str) -> dict:
        """Return a CLI-friendly summary payload for one URL."""
        if "list=" in url and "watch?v=" not in url:
            playlist_id = playlist_id_from_url(url)
            video_urls = self.list_playlist_videos(url)
            artifact_dir = self.debug_dir / f"playlist-{playlist_id}" if self.debug_dir else None
            payload = {
                "kind": "playlist",
                "url": url,
                "playlist_id": playlist_id,
                "video_urls": video_urls,
                "artifact_dir": str(artifact_dir) if artifact_dir else None,
            }
            if artifact_dir:
                artifact_dir.mkdir(parents=True, exist_ok=True)
                (artifact_dir / "playlist.json").write_text(
                    json.dumps(payload, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
            return payload
        result = self.extract_video(url)
        artifact_dir = self.debug_dir / f"video-{result.metadata.video_id}" if self.debug_dir else None
        payload = {
            "kind": "video",
            "url": url,
            "video_id": result.metadata.video_id,
            "title": result.metadata.title,
            "channel": result.metadata.channel,
            "duration_seconds": result.metadata.duration_seconds,
            "segment_count": len(result.segments),
            "sample_segments": [segment.to_dict() for segment in result.segments[:5]],
            "artifact_dir": str(artifact_dir) if artifact_dir else None,
        }
        if artifact_dir:
            artifact_dir.mkdir(parents=True, exist_ok=True)
            (artifact_dir / "summary.json").write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        return payload

    def debug_extract(self, url: str) -> dict:
        """Backward-compatible alias kept for the CLI/debug workflow."""
        return self.extract_url_summary(url)

    def _run_browser(self, callback, url: str):
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise TranscriptExtractionError(
                "Playwright is not installed. Install with `pip install -e .[browser]` "
                "and run `playwright install chromium`."
            ) from exc
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=self.headless)
                page = browser.new_page()
                page.set_default_timeout(self.timeout_ms)
                artifact_dir = self._make_artifact_dir(url)
                self._current_artifact_dir = artifact_dir
                self._debug_steps = []
                try:
                    self._record_step(page, "browser_started", {"url": url})
                    result = callback(page, url, PlaywrightTimeoutError)
                    self._write_debug_artifacts(
                        page,
                        artifact_dir,
                        {
                            "url": url,
                            "status": "success",
                            "title": page.title(),
                        },
                    )
                    return result
                except Exception as exc:
                    self._write_debug_artifacts(
                        page,
                        artifact_dir,
                        {
                            "url": url,
                            "status": "failed",
                            "error": str(exc),
                            "title": self._safe_page_title(page),
                        },
                    )
                    raise
                finally:
                    self._current_artifact_dir = None
                    browser.close()
        except PlaywrightTimeoutError as exc:
            raise TranscriptExtractionError(f"Timed out loading YouTube page: {url}") from exc

    def _scrape_playlist_page(self, page, playlist_url: str, timeout_error):
        page.goto(playlist_url, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        for _ in range(4):
            page.mouse.wheel(0, 5000)
            page.wait_for_timeout(750)
        hrefs = []
        for selector in [
            "ytd-playlist-video-renderer a[href*='/watch?v=']",
            "a[href*='/watch?v='][href*='list=']",
            "a[href*='/watch?v=']",
        ]:
            hrefs = page.eval_on_selector_all(
                selector,
                "nodes => nodes.map(node => node.getAttribute('href')).filter(Boolean)",
            )
            if hrefs:
                break
        return hrefs

    def _scrape_video_page(self, page, video_url: str, timeout_error):
        self._record_step(page, "goto_start", {"url": video_url})
        page.goto(video_url, wait_until="domcontentloaded")
        self._record_step(page, "goto_done")
        page.wait_for_load_state("networkidle")
        self._record_step(page, "networkidle_done")
        page.wait_for_timeout(2000)
        self._record_step(page, "pre_open_transcript")
        # Transcript opening is the DOM-fragile step, so keep it isolated and
        # heavily instrumented for future YouTube UI updates.
        self._open_transcript(page)
        self._record_step(page, "open_transcript_done")
        self._wait_for_transcript_content(page)
        self._record_step(page, "transcript_content_ready")
        title = self._text_content(
            page,
            [
                "ytd-watch-metadata h1 yt-formatted-string",
                "h1.ytd-watch-metadata",
                "h1",
            ],
        )
        channel = self._text_content(
            page,
            [
                "ytd-channel-name a",
                "#channel-name a",
            ],
        )
        duration_seconds = page.eval_on_selector(
            "video",
            """node => {
                const duration = node && Number.isFinite(node.duration) ? Math.floor(node.duration) : null;
                return duration;
            }""",
        )
        rows = self._read_transcript_rows(page)
        return {
            "title": title,
            "channel": channel,
            "duration_seconds": duration_seconds,
            "rows": rows,
        }

    def _open_transcript(self, page) -> None:
        # Prefer the current transcript section rendered in the description area.
        # The legacy engagement-panel controls are still checked as fallbacks.
        transcript_button_selectors = [
            "ytd-video-description-transcript-section-renderer button[aria-label='Show transcript']",
            "div#primary-button ytd-button-renderer button[aria-label='Show transcript']",
            "ytd-video-description-transcript-section-renderer ytd-button-renderer",
            "ytd-video-description-transcript-section-renderer yt-button-shape",
            "div#primary-button",
            "button[aria-label*='transcript']",
            "button[aria-label*='Transcript']",
            "button:has-text('Show transcript')",
            "yt-button-view-model button:has-text('Show transcript')",
            "div.yt-spec-button-shape-next__button-text-content:has-text('Show transcript')",
            "span:has-text('Show transcript')",
            "tp-yt-paper-item:has-text('Show transcript')",
            "ytd-menu-service-item-renderer:has-text('Show transcript')",
        ]
        more_button_selectors = [
            "button[aria-label='More actions']",
            "#button[aria-label='More actions']",
            "ytd-menu-renderer button[aria-label='More actions']",
            "tp-yt-paper-button#expand",
            "tp-yt-paper-button:has-text('...more')",
            "#description-inline-expander tp-yt-paper-button#expand",
            "ytd-text-inline-expander tp-yt-paper-button#expand",
        ]
        if self._click_transcript_from_expanded_description(page):
            return
        for selector in transcript_button_selectors:
            locator = page.locator(selector)
            if self._click_if_visible(locator):
                self._record_step(page, "transcript_click_attempt", {"selector": selector})
                if self._transcript_panel_present(page):
                    return
        for selector in more_button_selectors:
            locator = page.locator(selector)
            if self._click_if_visible(locator):
                self._record_step(page, "more_click_attempt", {"selector": selector})
                page.wait_for_timeout(750)
                for transcript_selector in transcript_button_selectors:
                    transcript_locator = page.locator(transcript_selector)
                    if self._click_if_visible(transcript_locator):
                        self._record_step(
                            page,
                            "transcript_click_attempt_after_more",
                            {"selector": transcript_selector},
                        )
                        if self._transcript_panel_present(page):
                            return
        if self._transcript_panel_present(page):
            return
        for expander_selector in [
            "tp-yt-paper-button#expand",
            "button:has-text('...more')",
            "span:has-text('...more')",
            "button[aria-label*='more']",
        ]:
            expander = page.locator(expander_selector)
            if self._click_if_visible(expander):
                self._record_step(page, "expander_click_attempt", {"selector": expander_selector})
                page.wait_for_timeout(500)
                if self._click_transcript_from_expanded_description(page):
                    return
                for transcript_selector in transcript_button_selectors:
                    transcript_locator = page.locator(transcript_selector)
                    if self._click_if_visible(transcript_locator):
                        self._record_step(
                            page,
                            "transcript_click_attempt_after_expander",
                            {"selector": transcript_selector},
                        )
                        if self._transcript_panel_present(page):
                            return
        raise TranscriptExtractionError(
            "Could not open transcript panel. The video may not have a transcript or the UI changed."
        )

    def _read_transcript_rows(self, page) -> list[dict[str, str]]:
        # YouTube currently renders transcripts in a newer inline transcript
        # component, but older watch pages may still expose legacy renderers.
        selectors = [
            "transcript-segment-view-model",
            ".ytwTimelineItemViewModelContentItems transcript-segment-view-model",
            "ytd-transcript-segment-renderer",
            "ytd-transcript-body-renderer ytd-transcript-segment-renderer",
        ]
        for selector in selectors:
            rows = page.eval_on_selector_all(
                selector,
                """nodes => nodes.map((node) => {
                    const timestamp = node.querySelector(
                        '.ytwTranscriptSegmentViewModelTimestamp, .segment-timestamp, [id=segment-timestamp], yt-formatted-string.segment-timestamp'
                    )?.textContent || '';
                    const text = node.querySelector(
                        '.yt-core-attributed-string[role=text], .segment-text, [id=segment-text]'
                    )?.textContent || '';
                    return {timestamp: timestamp.trim(), text: text.trim()};
                })""",
            )
            if rows:
                normalized = self._normalize_transcript_rows(rows)
                if normalized:
                    return normalized
        raise TranscriptExtractionError(
            "Transcript panel opened but no transcript rows were found."
        )

    def _text_content(self, page, selectors: list[str]) -> str:
        for selector in selectors:
            locator = page.locator(selector)
            if locator.count():
                text = locator.first.text_content()
                if text:
                    return " ".join(text.split())
        return ""

    def _video_id_from_href(self, href: str) -> str | None:
        if not href:
            return None
        parsed = urlparse(href)
        query = parse_qs(parsed.query)
        if query.get("v"):
            return query["v"][0]
        if parsed.path.startswith("/watch") and "v=" in href:
            return video_id_from_url(f"https://www.youtube.com{href}")
        return None

    def _timestamp_to_seconds(self, value: str) -> int:
        cleaned = value.strip()
        if not re.fullmatch(r"\d+(?::\d+){1,2}", cleaned):
            raise TranscriptExtractionError(f"Unsupported timestamp format: {value}")
        parts = [int(part) for part in cleaned.split(":")]
        if len(parts) == 2:
            minutes, seconds = parts
            return minutes * 60 + seconds
        if len(parts) == 3:
            hours, minutes, seconds = parts
            return hours * 3600 + minutes * 60 + seconds
        raise TranscriptExtractionError(f"Unsupported timestamp format: {value}")

    def _normalize_transcript_rows(self, rows: list[dict[str, str]]) -> list[dict[str, str]]:
        normalized: list[dict[str, str]] = []
        for row in rows:
            timestamp = " ".join((row.get("timestamp") or "").split())
            text = " ".join((row.get("text") or "").split())
            if not timestamp or not text:
                continue
            try:
                self._timestamp_to_seconds(timestamp)
            except TranscriptExtractionError:
                continue
            normalized.append({"timestamp": timestamp, "text": text})
        return normalized

    def _click_if_visible(self, locator) -> bool:
        count = locator.count()
        if not count:
            return False
        try:
            locator.first.scroll_into_view_if_needed(timeout=2000)
            locator.first.click(timeout=2000)
            locator.first.page.wait_for_timeout(1200)
            return True
        except Exception:
            pass
        try:
            locator.first.evaluate(
                """node => {
                    if (typeof node.click === 'function') {
                        node.click();
                        return true;
                    }
                    return false;
                }"""
            )
            locator.first.page.wait_for_timeout(1200)
            return True
        except Exception:
            return False

    def _click_transcript_from_expanded_description(self, page) -> bool:
        containers = [
            page.locator("#description-inline-expander"),
            page.locator("ytd-text-inline-expander"),
            page.locator("#description"),
        ]
        for container in containers:
            if not container.count():
                continue
            try:
                transcript_button = container.first.locator(
                    "ytd-video-description-transcript-section-renderer button[aria-label='Show transcript'], "
                    "ytd-video-description-transcript-section-renderer ytd-button-renderer, "
                    "ytd-video-description-transcript-section-renderer yt-button-shape, "
                    "ytd-video-description-transcript-section-renderer div#primary-button, "
                    "div#primary-button ytd-button-renderer button[aria-label='Show transcript']"
                )
                if self._click_transcript_candidates(page, transcript_button):
                    return True
            except Exception:
                continue
        return False

    def _click_transcript_candidates(self, page, locator) -> bool:
        count = min(locator.count(), 4)
        for index in range(count):
            candidate = locator.nth(index)
            try:
                description = {
                    "index": index,
                    "text": (candidate.text_content() or "").strip(),
                    "aria_label": candidate.get_attribute("aria-label") or "",
                }
            except Exception:
                description = {"index": index}
            if self._click_if_visible(candidate):
                self._record_step(page, "transcript_candidate_clicked", description)
                if self._transcript_panel_present(page):
                    return True
        return False

    def _transcript_panel_present(self, page) -> bool:
        # The old engagement panel can exist in the DOM in a hidden state before
        # the transcript is actually opened, so visibility matters here.
        panel = page.locator(
            "ytd-engagement-panel-section-list-renderer[target-id='engagement-panel-searchable-transcript']"
        )
        if panel.count():
            try:
                is_hidden = panel.first.evaluate(
                    """node => {
                        const visibility = node.getAttribute('visibility') || '';
                        const hiddenAttr = node.hasAttribute('hidden');
                        const ariaHidden = node.getAttribute('aria-hidden') === 'true';
                        return visibility.includes('HIDDEN') || hiddenAttr || ariaHidden;
                    }"""
                )
                if not is_hidden and panel.first.is_visible():
                    return True
            except Exception:
                pass
        for selector in [
            ".ytwTimelineItemViewModelContentItems",
            "transcript-segment-view-model",
            "ytd-transcript-segment-list-renderer",
            "ytd-transcript-body-renderer",
        ]:
            locator = page.locator(selector)
            if locator.count() and locator.first.is_visible():
                return True
        return False

    def _wait_for_transcript_content(self, page) -> None:
        self._record_step(page, "wait_for_transcript_content_start")
        if not self._transcript_panel_present(page):
            raise TranscriptExtractionError("Transcript panel never became visible.")
        try:
            # Favor a hard upper bound here so failed selector changes do not
            # leave the browser hanging indefinitely during maintenance.
            page.wait_for_function(
                """() => {
                    const selectors = [
                        'transcript-segment-view-model',
                        '.ytwTimelineItemViewModelContentItems transcript-segment-view-model',
                        'ytd-transcript-segment-renderer',
                        'ytd-transcript-body-renderer ytd-transcript-segment-renderer'
                    ];
                    return selectors.some((selector) => document.querySelector(selector));
                }""",
                timeout=min(8000, max(5000, self.timeout_ms // 2)),
            )
            self._record_step(page, "wait_for_transcript_rows_success")
            return
        except Exception:
            self._record_step(page, "wait_for_transcript_rows_timeout")
        try:
            spinner = page.locator(
                "ytd-continuation-item-renderer tp-yt-paper-spinner"
            )
            if spinner.count():
                self._record_step(page, "wait_for_spinner_resolution_start")
                page.wait_for_function(
                    """() => {
                        const spinner = document.querySelector('ytd-continuation-item-renderer tp-yt-paper-spinner');
                        if (!spinner) return true;
                        const hiddenAttr = spinner.hasAttribute('hidden');
                        const active = spinner.getAttribute('active');
                        return hiddenAttr || active === null;
                    }""",
                    timeout=min(8000, max(5000, self.timeout_ms // 2)),
                )
                self._record_step(page, "wait_for_spinner_resolution_done")
        except Exception:
            self._record_step(page, "wait_for_spinner_resolution_timeout")
        try:
            page.wait_for_timeout(1500)
        except Exception:
            pass
        self._record_step(page, "wait_for_transcript_content_end")

    def _make_artifact_dir(self, url: str) -> Path | None:
        if self.debug_dir is None:
            return None
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", url)[:80].strip("-") or "youtube"
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        return Path(mkdtemp(prefix=f"{timestamp}-{slug}-", dir=self.debug_dir))

    def _write_debug_artifacts(self, page, artifact_dir: Path | None, metadata: dict) -> None:
        if artifact_dir is None:
            return
        artifact_dir.mkdir(parents=True, exist_ok=True)
        try:
            page.screenshot(path=str(artifact_dir / "page.png"), full_page=True)
        except Exception:
            pass
        try:
            html = page.content()
            (artifact_dir / "page.html").write_text(html, encoding="utf-8")
        except Exception:
            pass
        try:
            transcript_html = self._capture_transcript_panel_html(page)
            if transcript_html:
                (artifact_dir / "transcript_panel.html").write_text(
                    transcript_html,
                    encoding="utf-8",
                )
        except Exception:
            pass
        self._write_dom_debug_artifacts(page, artifact_dir)
        (artifact_dir / "step_trace.json").write_text(
            json.dumps(self._debug_steps, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        (artifact_dir / "metadata.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _capture_transcript_panel_html(self, page) -> str:
        for selector in [
            "ytd-engagement-panel-section-list-renderer[target-id='engagement-panel-searchable-transcript']",
            ".ytwTimelineItemViewModelContentItems",
            "ytd-transcript-body-renderer",
        ]:
            locator = page.locator(selector)
            if locator.count():
                html = locator.first.evaluate("node => node.outerHTML")
                if html:
                    return html
        return ""

    def _safe_page_title(self, page) -> str:
        try:
            return page.title()
        except Exception:
            return ""

    def _write_dom_debug_artifacts(self, page, artifact_dir: Path) -> None:
        try:
            controls = self._collect_clickable_controls(page)
            (artifact_dir / "clickable_controls.json").write_text(
                json.dumps(controls, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except Exception:
            pass
        for filename, selector in [
            ("description.html", "#description-inline-expander"),
            ("description_fallback.html", "ytd-text-inline-expander"),
            ("metadata_actions.html", "ytd-watch-metadata"),
            ("top_actions.html", "#top-level-buttons-computed"),
        ]:
            try:
                html = self._capture_outer_html(page, selector)
                if html:
                    (artifact_dir / filename).write_text(html, encoding="utf-8")
            except Exception:
                pass

    def _capture_outer_html(self, page, selector: str) -> str:
        locator = page.locator(selector)
        if not locator.count():
            return ""
        return locator.first.evaluate("node => node.outerHTML") or ""

    def _collect_clickable_controls(self, page) -> list[dict[str, str | bool]]:
        return page.evaluate(
            """() => {
                const candidates = Array.from(document.querySelectorAll(`
                    button,
                    tp-yt-paper-button,
                    yt-button-view-model,
                    ytd-button-renderer,
                    ytd-menu-renderer button,
                    [role="button"],
                    .yt-spec-button-shape-next,
                    .yt-spec-button-shape-next__button-text-content
                `.replace(/\\s+/g, ' ')));
                const seen = new Set();
                const rows = [];
                const textOf = (node) => (node.innerText || node.textContent || '').replace(/\\s+/g, ' ').trim();
                const selectorHint = (node) => {
                    const parts = [];
                    let current = node;
                    for (let i = 0; i < 4 && current; i += 1) {
                        let part = current.tagName ? current.tagName.toLowerCase() : 'node';
                        if (current.id) part += `#${current.id}`;
                        if (current.classList && current.classList.length) {
                            part += '.' + Array.from(current.classList).slice(0, 3).join('.');
                        }
                        parts.unshift(part);
                        current = current.parentElement;
                    }
                    return parts.join(' > ');
                };
                for (const node of candidates) {
                    const key = selectorHint(node);
                    if (seen.has(key)) continue;
                    seen.add(key);
                    const rect = node.getBoundingClientRect();
                    const text = textOf(node);
                    const ariaLabel = node.getAttribute('aria-label') || '';
                    const title = node.getAttribute('title') || '';
                    const role = node.getAttribute('role') || '';
                    const hiddenAttr = node.hasAttribute('hidden');
                    const visible = !!(rect.width || rect.height);
                    const inDescription = !!node.closest('#description-inline-expander, ytd-text-inline-expander, #description');
                    const inWatchMeta = !!node.closest('ytd-watch-metadata');
                    if (!text && !ariaLabel && !title) continue;
                    rows.push({
                        selector_hint: key,
                        text,
                        aria_label: ariaLabel,
                        title,
                        role,
                        visible,
                        hidden: hiddenAttr,
                        in_description: inDescription,
                        in_watch_metadata: inWatchMeta
                    });
                }
                return rows;
            }"""
        )

    def _record_step(self, page, name: str, details: dict[str, object] | None = None) -> None:
        entry: dict[str, object] = {
            "step": name,
            "at": datetime.now(UTC).isoformat(),
            "details": details or {},
        }
        self._debug_steps.append(entry)
        if self._current_artifact_dir is None:
            return
        safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "-", name)
        step_dir = self._current_artifact_dir / "step_snapshots"
        step_dir.mkdir(parents=True, exist_ok=True)
        step_index = len(self._debug_steps)
        prefix = f"{step_index:02d}-{safe_name}"
        try:
            (step_dir / f"{prefix}.json").write_text(
                json.dumps(entry, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except Exception:
            pass
        try:
            page.screenshot(path=str(step_dir / f"{prefix}.png"), full_page=False)
        except Exception:
            pass
