"""Fetch and preserve the original publisher page before a story can enter production.

This module collects source evidence only. It does not claim that a story is fact-checked;
a readable article is not proof that its claims are true.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html.parser import HTMLParser
import ipaddress
import json
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


MAX_RESPONSE_BYTES = 3 * 1024 * 1024
MAX_ARTICLE_CHARS = 12_000
TRANSIENT_HTTP_CODES = {408, 425, 429, 500, 502, 503, 504}
SKIP_TAGS = {"script", "style", "noscript", "svg", "nav", "header", "footer", "aside", "form"}
TEXT_TAGS = {"p", "h1", "h2", "h3", "blockquote", "li"}


# Some publisher pages expose a list of related headlines plus an unrendered
# template token instead of the article body. Length alone must not promote
# that page to readable source evidence.
TEMPLATE_ARTIFACT_PATTERNS = (
    re.compile(r"\\{\\{\\s*[^{}]{1,160}\\s*\\}\\}"),
    re.compile(r"\\brelated_articles\\s*\\[\\s*\\d+\\s*\\]", re.IGNORECASE),
)


def _has_template_artifacts(value: str) -> bool:
    text = str(value or "")
    return any(pattern.search(text) for pattern in TEMPLATE_ARTIFACT_PATTERNS)


class ArticleTextParser(HTMLParser):
    """Extract human-readable paragraphs/headings while ignoring page chrome."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.capture_tag: str | None = None
        self.capture_parts: list[str] = []
        self.paragraphs: list[str] = []
        self.page_title_parts: list[str] = []
        self.in_title = False
        self.meta_description = ""
        self.meta_og_title = ""
        self.json_ld_parts: list[str] = []
        self.json_ld_documents: list[object] = []
        self.in_json_ld = False

    def handle_starttag(self, tag: str, attrs) -> None:
        attrs_map = {str(k).lower(): str(v or "") for k, v in attrs}
        if tag == "script" and not self.skip_depth:
            if attrs_map.get("type", "").split(";")[0].strip().lower() == "application/ld+json":
                self.in_json_ld = True
                self.json_ld_parts = []
            else:
                self.skip_depth += 1
            return
        if tag in SKIP_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag == "meta":
            key = (attrs_map.get("property") or attrs_map.get("name") or "").lower()
            value = attrs_map.get("content", "").strip()
            if key in {"og:description", "description", "twitter:description"} and value:
                if len(value) > len(self.meta_description):
                    self.meta_description = value
            elif key in {"og:title", "twitter:title"} and value:
                self.meta_og_title = value
        elif tag == "title":
            self.in_title = True
        elif tag in TEXT_TAGS and self.capture_tag is None:
            self.capture_tag = tag
            self.capture_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self.in_json_ld:
            raw = "".join(self.json_ld_parts).strip()
            if raw:
                try:
                    self.json_ld_documents.append(json.loads(raw))
                except (json.JSONDecodeError, TypeError):
                    pass
            self.json_ld_parts = []
            self.in_json_ld = False
            return
        if tag in SKIP_TAGS:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth:
            return
        if tag == "title":
            self.in_title = False
        if self.capture_tag == tag:
            value = re.sub(r"\s+", " ", " ".join(self.capture_parts)).strip()
            if len(value) >= 25:
                self.paragraphs.append(value)
            self.capture_tag = None
            self.capture_parts = []

    def handle_data(self, data: str) -> None:
        if self.in_json_ld:
            self.json_ld_parts.append(data)
            return
        if self.skip_depth:
            return
        text = re.sub(r"\s+", " ", data).strip()
        if not text:
            return
        if self.in_title:
            self.page_title_parts.append(text)
        if self.capture_tag:
            self.capture_parts.append(text)

    def result(self) -> dict:
        # Structured Article/NewsArticle metadata often contains the full article
        # even when the publisher renders its visible body with client-side JavaScript.
        jsonld_bodies: list[str] = []
        jsonld_headlines: list[str] = []
        jsonld_descriptions: list[str] = []

        def visit(node) -> None:
            if isinstance(node, list):
                for item in node:
                    visit(item)
                return
            if not isinstance(node, dict):
                return
            raw_types = node.get("@type", [])
            types = raw_types if isinstance(raw_types, list) else [raw_types]
            article_node = any(
                str(item).rsplit("/", 1)[-1].casefold()
                in {"article", "newsarticle", "reportagenewsarticle", "blogposting"}
                for item in types
            )
            if article_node:
                body = node.get("articleBody")
                headline = node.get("headline")
                description = node.get("description")
                if isinstance(body, str) and len(body.strip()) >= 250:
                    jsonld_bodies.append(re.sub(r"\s+", " ", body).strip())
                if isinstance(headline, str) and headline.strip():
                    jsonld_headlines.append(headline.strip())
                if isinstance(description, str) and description.strip():
                    jsonld_descriptions.append(description.strip())
            for value in node.values():
                if isinstance(value, (dict, list)):
                    visit(value)

        for document in self.json_ld_documents:
            visit(document)

        # Remove repeated boilerplate without changing the publisher's wording.
        seen = set()
        paragraphs = []
        for paragraph in self.paragraphs:
            key = paragraph.casefold()
            if key not in seen:
                seen.add(key)
                paragraphs.append(paragraph)

        visible_text = "\n\n".join(paragraphs)
        structured_text = max(jsonld_bodies, key=len, default="")
        article_text = structured_text if len(structured_text) >= 250 else visible_text
        title = self.meta_og_title or max(jsonld_headlines, key=len, default="") or " ".join(self.page_title_parts)
        description = self.meta_description or max(jsonld_descriptions, key=len, default="")
        return {
            "page_title": re.sub(r"\s+", " ", title).strip()[:500],
            "meta_description": re.sub(r"\s+", " ", description).strip()[:1200],
            "article_text": article_text[:MAX_ARTICLE_CHARS],
        }


def _validate_http_url(value: str) -> None:
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("رابط المصدر يجب أن يكون HTTPS صالحاً.")
    host = parsed.hostname.casefold()
    if host in {"localhost"} or host.endswith((".local", ".internal")):
        raise ValueError("رابط المصدر غير مسموح به.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("عناوين الشبكات الخاصة أو المحلية غير مسموح بها.")


def fetch_original_source(story: dict) -> dict:
    """Fetch one original article with bounded retries and a truthful extraction status."""
    source_url = str(story.get("link") or "").strip()
    record = {
        "story_id": str(story.get("id") or ""),
        "source_name": str(story.get("source") or ""),
        "source_url": source_url,
        "final_url": "",
        "publisher_domain": "",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "status": "unavailable",
        "http_status": None,
        "page_title": "",
        "meta_description": "",
        "article_text": "",
        "extracted_chars": 0,
        "evidence_level": "unavailable",
        "warnings": [],
    }
    try:
        _validate_http_url(source_url)
    except ValueError as exc:
        record["warnings"].append(str(exc))
        return record

    request = Request(
        source_url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; NewsFlowSourceReview/1.0)",
            "Accept": "text/html,application/xhtml+xml;q=0.9",
            "Accept-Language": "ar,en;q=0.8",
        },
    )
    last_error = None
    for attempt in range(3):
        try:
            with urlopen(request, timeout=20) as response:
                status = int(getattr(response, "status", 200))
                content_type = response.headers.get_content_type()
                charset = response.headers.get_content_charset() or "utf-8"
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                final_url = response.geturl()
                _validate_http_url(final_url)
            if len(raw) > MAX_RESPONSE_BYTES:
                raw = raw[:MAX_RESPONSE_BYTES]
                record["warnings"].append("تم قص صفحة المصدر بعد حد الحجم الآمن.")
            record["http_status"] = status
            record["final_url"] = final_url
            record["publisher_domain"] = (urlparse(final_url).hostname or "").lower()
            if content_type not in {"text/html", "application/xhtml+xml"}:
                record["warnings"].append("رابط المصدر لم يُرجع صفحة HTML قابلة للمراجعة.")
                return record
            parser = ArticleTextParser()
            parser.feed(raw.decode(charset, errors="replace"))
            extracted = parser.result()
            record.update(extracted)
            record["extracted_chars"] = len(extracted["article_text"])
            if _has_template_artifacts(record["article_text"]):
                record["status"] = "partial"
                record["evidence_level"] = "partial_text"
                record["warnings"].append(
                    "صفحة المصدر تحتوي على عناصر قالب أو عناوين مقالات مرتبطة بدلاً من نص مقال مكتمل."
                )
                return record
            if record["extracted_chars"] >= 700:
                record["status"] = "readable"
                record["evidence_level"] = "article_text"
            elif record["extracted_chars"] >= 250:
                record["status"] = "partial"
                record["evidence_level"] = "partial_text"
                record["warnings"].append("النص المستخرج جزئي؛ لا يكفي وحده للتحقق من الوقائع.")
            else:
                record["status"] = "thin"
                record["evidence_level"] = "metadata_only"
                record["warnings"].append("تعذر استخراج نص المقال الكامل من صفحة المصدر.")
            return record
        except HTTPError as exc:
            last_error = exc
            if exc.code not in TRANSIENT_HTTP_CODES or attempt == 2:
                record["warnings"].append(f"تعذر فتح المصدر (HTTP {exc.code}).")
                return record
        except (URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt == 2:
                record["warnings"].append(
                    f"تعذر الاتصال بالمصدر بعد ثلاث محاولات ({type(exc).__name__})."
                )
                return record
        if attempt < 2:
            time.sleep(0.75 * (attempt + 1))

    record["warnings"].append(
        f"تعذر فتح المصدر بعد ثلاث محاولات ({type(last_error).__name__ if last_error else 'unknown'})."
    )
    return record


def collect_source_evidence(stories: list[dict], max_workers: int = 4) -> list[dict]:
    """Fetch accepted original sources concurrently while preserving story order."""
    if not stories:
        return []
    results: dict[int, dict] = {}
    workers = max(1, min(int(max_workers), 4, len(stories)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(fetch_original_source, story): index
            for index, story in enumerate(stories)
        }
        for future in as_completed(future_map):
            index = future_map[future]
            try:
                results[index] = future.result()
            except Exception as exc:
                story = stories[index]
                results[index] = {
                    "story_id": str(story.get("id") or ""),
                    "source_name": str(story.get("source") or ""),
                    "source_url": str(story.get("link") or ""),
                    "status": "unavailable",
                    "evidence_level": "unavailable",
                    "article_text": "",
                    "extracted_chars": 0,
                    "warnings": [f"فشل جمع دليل المصدر ({type(exc).__name__})."],
                }
    return [results[index] for index in range(len(stories))]
