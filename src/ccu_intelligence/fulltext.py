"""Legal full-text access for analysis: robots-respecting page extraction and open-access papers.

Text obtained here is model input only. It is cached privately outside the run artifact and is never
written to drafts, reports or bundles; those record only its basis, size, origin and hash.
"""

import hashlib
import io
import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit

import httpx

from .collect import Fetcher
from .normalize import plain

LOG = logging.getLogger(__name__)
CACHE = Path("data/runtime/fulltext-cache")  # private: never inside an uploaded run directory
HTML_BYTES = 5_000_000
PDF_BYTES = 15_000_000
PDF_PAGES = 40
FULL_TEXT_MIN = {"paper": 2500, "page": 1200}
ABSTRACT_MIN = 300
MARKERS = ("[Opening excerpt]\n", "\n\n[Middle excerpt]\n", "\n\n[Closing excerpt]\n")


def select_content(text: str, max_chars: int, sampling: str = "head-middle-tail") -> str:
    """Bounded excerpt that keeps a long document's opening, middle and conclusion (40/30/30)."""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    if sampling == "prefix":
        return text[:max_chars].rstrip()
    available = max_chars - sum(len(m) for m in MARKERS)
    opening = int(available * 0.4)
    middle = int(available * 0.3)
    closing = available - opening - middle
    start = max(0, len(text) // 2 - middle // 2)
    return (MARKERS[0] + text[:opening].rstrip() + MARKERS[1] + text[start:start + middle].strip()
            + MARKERS[2] + text[-closing:].lstrip())


@dataclass
class SourceText:
    basis: str  # full_text | abstract | headline
    text: str = field(repr=False)
    origin: str | None = None
    method: str = "feed metadata"
    attempts: list[dict] = field(default_factory=list)

    def record(self) -> dict:
        """Artifact-safe description: no source text."""
        data = asdict(self)
        data.pop("text")
        data["chars"] = len(self.text)
        data["sha256"] = hashlib.sha256(self.text.encode()).hexdigest()
        return data


def reconstruct_abstract(index: dict | None) -> str:
    if not index:
        return ""
    words = sorted((position, word) for word, positions in index.items() for position in positions)
    return " ".join(word for _, word in words)


def extract_html(body: bytes, url: str) -> str:
    import trafilatura

    tree = trafilatura.load_html(body)
    if tree is None:
        return ""
    return trafilatura.extract(tree, url=url, favor_precision=True, include_comments=False,
                               include_tables=True) or ""


def extract_pdf(body: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(body))
    pages = []
    for page in reader.pages[:PDF_PAGES]:
        try:
            pages.append(page.extract_text() or "")
        except Exception:  # malformed page objects: keep what is readable
            continue
    return re.sub(r"[ \t]+", " ", "\n".join(pages)).strip()


class PageReader:
    """Fetch a public page with our honest User-Agent, checking robots.txt on every hop."""

    def __init__(self, fetcher: Fetcher, minimum_interval: float = 2.0):
        self.fetcher = fetcher
        self.minimum_interval = minimum_interval

    def read(self, url: str, attempts: list[dict]) -> tuple[str, str]:
        """Return (main text, final URL); empty text when not permitted or not extractable."""
        for _ in range(6):
            note = {"url": url}
            attempts.append(note)
            try:
                permitted, interval = self.fetcher.allowed(url, self.minimum_interval)
                if not permitted:
                    note["result"] = "robots.txt disallows"
                    return "", url
                pdf_like = url.lower().split("?")[0].endswith(".pdf")
                result = self.fetcher.fetch(
                    url, interval=interval, max_bytes=PDF_BYTES if pdf_like else HTML_BYTES,
                    headers={"Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.5"},
                )
            except (httpx.HTTPError, ValueError, RuntimeError, OSError) as exc:
                note["result"] = type(exc).__name__
                return "", url
            note["status"] = result.status
            if result.status in (301, 302, 303, 307, 308) and result.headers.get("location"):
                url = urljoin(url, result.headers["location"])
                continue
            if not 200 <= result.status < 300:
                note["result"] = "not available (no paywall bypass)"
                return "", url
            kind = result.headers.get("content-type", "").lower()
            try:
                if "pdf" in kind or result.body[:5] == b"%PDF-":
                    text, note["method"] = extract_pdf(result.body), "pypdf"
                elif "html" in kind or "xml" in kind or not kind:
                    text, note["method"] = extract_html(result.body, url), "trafilatura"
                else:
                    note["result"] = "unsupported content type"
                    return "", url
            except Exception as exc:  # extractor failures on hostile documents fall back to metadata
                note["result"] = "extraction failed: " + type(exc).__name__
                return "", url
            note["chars"] = len(text)
            return text, url
        attempts.append({"url": url, "result": "too many redirects"})
        return "", url


def _doi(value: str | None) -> str | None:
    if not value:
        return None
    return re.sub(r"^(https?://(dx\.)?doi.org/|doi:\s*)", "", value.strip(), flags=re.I).lower()


def openalex_records(fetcher: Fetcher, dois: list[str]) -> dict[str, dict]:
    """Abstract and open-access locations for up to 50 DOIs per request."""
    headers = {"Authorization": "Bearer " + os.environ["OPENALEX_API_KEY"]} if os.getenv("OPENALEX_API_KEY") else {}
    found = {}
    for start in range(0, len(dois), 50):
        chunk = dois[start:start + 50]
        params = {
            "filter": "doi:" + "|".join(chunk),
            "per_page": 50,
            "select": "doi,type,abstract_inverted_index,open_access,best_oa_location,locations",
        }
        if os.getenv("CCU_CONTACT_EMAIL"):
            params["mailto"] = os.environ["CCU_CONTACT_EMAIL"]
        try:
            raw = fetcher.get("https://api.openalex.org/works", params=params, headers=headers)
        except (httpx.HTTPError, ValueError, RuntimeError, OSError) as exc:
            LOG.warning("OpenAlex lookup failed (%s)", type(exc).__name__)
            continue
        for work in json.loads(raw).get("results", []):
            doi = _doi(work.get("doi"))
            if not doi:
                continue
            locations = [work.get("best_oa_location") or {}] + list(work.get("locations") or [])
            urls = []
            for location in locations:
                if not location or not location.get("is_oa"):
                    continue
                for key in ("landing_page_url", "pdf_url"):
                    if location.get(key) and location[key] not in urls:
                        urls.append(location[key])
            found[doi] = {"abstract": reconstruct_abstract(work.get("abstract_inverted_index")),
                          "oa_urls": urls, "type": work.get("type"),
                          "oa_status": (work.get("open_access") or {}).get("oa_status")}
    return found


def unpaywall_urls(fetcher: Fetcher, doi: str) -> list[str]:
    """Unpaywall requires a contact email; skipped without CCU_CONTACT_EMAIL."""
    email = os.getenv("CCU_CONTACT_EMAIL")
    if not email:
        return []
    try:
        raw = fetcher.get(f"https://api.unpaywall.org/v2/{quote(doi, safe='/')}", params={"email": email})
    except (httpx.HTTPError, ValueError, RuntimeError, OSError):
        return []
    urls = []
    for location in json.loads(raw).get("oa_locations") or []:
        for key in ("url_for_landing_page", "url_for_pdf"):
            if location.get(key) and location[key] not in urls:
                urls.append(location[key])
    return urls


def _cached(key: str) -> SourceText | None:
    path = CACHE / (key + ".json")
    if path.exists():
        data = json.loads(path.read_text())
        return SourceText(**data)
    return None


def _store(key: str, value: SourceText) -> SourceText:
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / (key + ".json")).write_text(json.dumps(asdict(value), ensure_ascii=False))
    return value


def obtain(article, source, reader: PageReader, paper: dict | None = None) -> SourceText:
    """Best legally available text for one article: full_text, else abstract, else headline."""
    key = hashlib.sha256(json.dumps([str(article.canonical_url), article.doi, bool(paper)]).encode()).hexdigest()
    cached = _cached(key)
    if cached:
        return cached
    summary = plain(article.summary).replace(article.title, "").strip()
    headline = article.title + ("\n" + summary if summary else "")
    attempts: list[dict] = []
    if source.source_type == "scholarly_metadata":
        paper = paper or {}
        abstract = paper.get("abstract", "")
        urls = list(paper.get("oa_urls") or [])
        if not urls and article.doi:
            urls = unpaywall_urls(reader.fetcher, article.doi)
        for url in urls[:3]:
            if urlsplit(url).scheme != "https":
                continue
            text, final = reader.read(url, attempts)
            if len(text) >= FULL_TEXT_MIN["paper"] and len(text) > len(abstract) + 1000:
                return _store(key, SourceText("full_text", text, final, "open-access copy", attempts))
        if len(abstract) >= ABSTRACT_MIN:
            return _store(key, SourceText("abstract", article.title + "\n\nAbstract: " + abstract,
                                          "https://openalex.org", "OpenAlex abstract", attempts))
        return _store(key, SourceText("headline", headline, None, "title only", attempts))
    if source.content_extractor == "trafilatura":
        text, final = reader.read(str(article.canonical_url), attempts)
        if len(text) >= FULL_TEXT_MIN["page"]:
            return _store(key, SourceText("full_text", article.title + "\n\n" + text, final, "trafilatura", attempts))
    if source.access_method == "federal_register" and len(summary) >= ABSTRACT_MIN:
        return _store(key, SourceText("abstract", headline, str(article.canonical_url), "Federal Register abstract",
                                      attempts))
    return _store(key, SourceText("headline", headline, None, "feed title and snippet", attempts))
