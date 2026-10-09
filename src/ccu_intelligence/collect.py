"""Bounded, rate-limited API/RSS collection; raw responses stay private."""

import hashlib
import ipaddress
import json
import logging
import os
import socket
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
import yaml
from defusedxml import ElementTree as ET

from .analysis import analyze, event_candidates
from .extraction import extract_metrics
from .models import Source
from .normalize import normalize
from .normalize import parse_date as normalize_date
from .store import Store

LOG = logging.getLogger(__name__)
MAX_BYTES = 5_000_000
AGENT = "CCUIntelligence"


def registry(path: Path = Path("config/sources.yaml")) -> list[Source]:
    sources = [Source.model_validate(s) for s in yaml.safe_load(path.read_text())["sources"]]
    if len({s.source_id for s in sources}) != len(sources):
        raise ValueError("Duplicate source ID")
    return sources


def public_url(url: str):
    p = urlsplit(url)
    if p.scheme != "https" or not p.hostname or p.username or p.password or p.port not in (None, 443):
        raise ValueError("Collector requires public HTTPS on port 443")
    addresses = socket.getaddrinfo(p.hostname, 443)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError("Private and reserved network addresses are forbidden")


@dataclass
class Fetched:
    status: int
    headers: httpx.Headers
    body: bytes
    url: str


class Fetcher:
    def __init__(self, client: httpx.Client | None = None):
        self.client = client or httpx.Client(
            timeout=30,
            follow_redirects=False,
            # Identify the bot with a contact URL. Avoid the word "research": co2value.eu's firewall returns 403
            # to any User-Agent containing it (diagnosed 2026-10-09; robots.txt allows all agents).
            headers={"User-Agent": AGENT + "/0.1 (+https://rethinksci-gif.github.io/ccu-intelligence/)"},
        )
        self.last_request: dict[str, float] = {}
        self.robots_cache: dict[str, RobotFileParser | None] = {}

    def fetch(self, url: str, *, params=None, headers=None, interval=1.0, max_bytes=MAX_BYTES) -> Fetched:
        """One polite GET: public HTTPS only, per-host spacing, bounded retries on 429/5xx, no redirects."""
        public_url(url)
        host = urlsplit(url).hostname
        for attempt in range(3):
            delay = interval - (time.monotonic() - self.last_request.get(host, 0))
            if delay > 0:
                time.sleep(delay)
            self.last_request[host] = time.monotonic()
            try:
                with self.client.stream("GET", url, params=params, headers=headers) as response:
                    if response.status_code == 429 or response.status_code >= 500:
                        if attempt == 2:
                            response.raise_for_status()
                        retry_after = response.headers.get("Retry-After", "")
                        # Long Retry-After means defer until the next collection run.
                        if retry_after.isdigit() and int(retry_after) > 30:
                            raise ValueError("Server requested a long retry delay; deferred")
                        pause = float(retry_after) if retry_after.isdigit() else 2**attempt
                        time.sleep(max(pause, 2**attempt))
                        continue
                    chunks, size = [], 0
                    if 200 <= response.status_code < 300:
                        for chunk in response.iter_bytes():
                            size += len(chunk)
                            if size > max_bytes:
                                raise ValueError("Response exceeds preservation limit")
                            chunks.append(chunk)
                    return Fetched(response.status_code, response.headers, b"".join(chunks), str(response.url))
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt == 2:
                    raise
                time.sleep(2**attempt)
        raise RuntimeError("Retrieval failed")

    def get(self, url: str, *, params=None, headers=None, interval=1.0) -> bytes:
        result = self.fetch(url, params=params, headers=headers, interval=interval)
        if not 200 <= result.status < 300:
            # Redirects require a reviewed registry endpoint; 4xx are not retried.
            request = httpx.Request("GET", url)
            raise httpx.HTTPStatusError(
                f"HTTP {result.status}", request=request, response=httpx.Response(result.status, request=request)
            )
        return result.body

    def robots(self, url: str) -> RobotFileParser | None:
        """robots.txt per RFC 9309: 4xx means no restrictions (None); 5xx or network failure disallows all."""
        p = urlsplit(url)
        origin = f"{p.scheme}://{p.netloc}"
        if origin not in self.robots_cache:
            parser = RobotFileParser()
            target = origin + "/robots.txt"
            try:
                for _ in range(5):  # RFC 9309: follow at least five redirects
                    result = self.fetch(target)
                    location = result.headers.get("location")
                    if result.status in (301, 302, 303, 307, 308) and location:
                        target = urljoin(target, location)
                        continue
                    break
            except (httpx.HTTPError, ValueError, RuntimeError, OSError):
                parser.disallow_all = True
            else:
                if 200 <= result.status < 300:
                    parser.parse(result.body.decode("utf-8", errors="replace").splitlines())
                elif 400 <= result.status < 500:
                    parser = None
                else:
                    parser.disallow_all = True  # server errors and redirect loops fail closed
            self.robots_cache[origin] = parser
        return self.robots_cache[origin]

    def allowed(self, url: str, minimum_interval: float = 1.0) -> tuple[bool, float]:
        """Whether robots.txt permits our agent, and the polite interval for that host."""
        robots = self.robots(url)
        if robots is None:
            return True, minimum_interval
        if not robots.can_fetch(AGENT, url):
            return False, minimum_interval
        delay = robots.crawl_delay(AGENT) or 0
        rate = robots.request_rate(AGENT)
        return True, max(minimum_interval, float(delay), rate.seconds / rate.requests if rate else 0)

    def rss(self, source: Source, page: int = 1) -> bytes:
        endpoint = str(source.endpoint or source.base_url)
        if page > 1:
            endpoint += ("&" if "?" in endpoint else "?") + f"paged={page}"
        # Fail closed when robots cannot be read. Manual ingestion stays available.
        permitted, interval = self.allowed(endpoint, source.minimum_interval_seconds)
        if not permitted:
            raise ValueError("robots.txt disallows collection")
        return self.get(endpoint, interval=interval)


def rss_items(raw: bytes) -> list[dict]:
    root = ET.fromstring(raw)
    atom = {"a": "http://www.w3.org/2005/Atom"}
    if root.tag.endswith("feed"):
        return [
            {
                "title": item.findtext("a:title", default="", namespaces=atom),
                "url": next(
                    (
                        link.get("href", "")
                        for link in item.findall("a:link", atom)
                        if link.get("rel", "alternate") == "alternate"
                    ),
                    "",
                ),
                "publication_date": item.findtext("a:published", namespaces=atom),
                "source_updated_date": item.findtext("a:updated", namespaces=atom),
                "summary": item.findtext("a:summary", default="", namespaces=atom),
            }
            for item in root.findall("a:entry", atom)
        ]
    return [
        {
            "title": item.findtext("title", ""),
            "url": item.findtext("link", ""),
            "publication_date": item.findtext("pubDate"),
            "summary": item.findtext("description", ""),
        }
        for item in root.findall(".//item")
    ]


def crossref_items(raw: bytes) -> list[dict]:
    result = []
    for item in json.loads(raw)["message"]["items"]:
        parts = item.get("published", {}).get("date-parts", [[]])[0]
        try:
            published = date(*parts[:3]).isoformat() if len(parts) >= 3 else None
        except (ValueError, TypeError):
            published = None
        result.append(
            {
                "title": next(iter(item.get("title", [])), ""),
                "url": item.get("URL", ""),
                "doi": item.get("DOI"),
                "publication_date": published,
                "summary": "",
            }
        )  # do not redistribute publisher abstracts
    return result


def openalex_items(raw: bytes) -> list[dict]:
    return [
        {
            "title": i.get("display_name") or "",
            "url": i.get("doi") or i["id"],
            "doi": i.get("doi"),
            "publication_date": i.get("publication_date"),
            "summary": "",
        }
        for i in json.loads(raw)["results"]
    ]


def federal_register_items(raw: bytes) -> list[dict]:
    # Federal Register abstracts are US government works; the analysis may read them.
    return [
        {
            "title": r.get("title") or "",
            "url": r.get("html_url") or "",
            "publication_date": r.get("publication_date"),
            "summary": r.get("abstract") or "",
        }
        for r in json.loads(raw).get("results", [])
    ]


def collect(
    store: Store,
    since: date,
    until: date,
    only: str | None = None,
    limit: int = 50,
    query: str = "carbon dioxide utilization",
) -> dict:
    if since > until or not 1 <= limit <= 100:
        raise ValueError("Invalid date window or limit (1–100)")
    sources = registry()
    if only and only not in {s.source_id for s in sources}:
        raise ValueError("Unknown source")
    counts = {
        "added": 0,
        "duplicates": 0,
        "failed": 0,
        "limited": 0,
        "considered": 0,
        "outside_window": 0,
        "unknown_date": 0,
        "raw_files": [],
    }
    fetcher = Fetcher()
    companies = store.bundle().companies
    try:
        for source in sources:
            if not source.active or (only and source.source_id != only):
                continue
            if source.access_method == "manual" or not source.automated_access_approved:
                store.log(
                    source.source_id, "manual_required", source.limitation or "Automated access not approved"
                )
                continue
            try:
                endpoint = str(source.endpoint or source.base_url)
                source_query = source.query or query
                if source.access_method == "crossref":
                    params = {
                        "query.title": source_query,
                        "filter": f"from-pub-date:{since},until-pub-date:{until}",
                        "rows": min(100, limit * 3),
                        "sort": "score",
                        "order": "desc",
                    }
                    if os.getenv("CCU_CONTACT_EMAIL"):
                        params["mailto"] = os.environ["CCU_CONTACT_EMAIL"]
                    pages = [fetcher.get(endpoint, params=params, interval=source.minimum_interval_seconds)]
                    parser = crossref_items
                elif source.access_method == "openalex":
                    headers = (
                        {"Authorization": "Bearer " + os.environ["OPENALEX_API_KEY"]}
                        if os.getenv("OPENALEX_API_KEY")
                        else {}
                    )
                    window = f"from_publication_date:{since},to_publication_date:{until}"
                    if source.query:
                        # Boolean title/abstract search; plain full-text search returned mostly off-topic works.
                        clauses = [f"title_and_abstract.search:{source.query}", window, "has_abstract:true",
                                   "type:article|review"]
                        params = {"filter": ",".join(clauses + ([source.filters] if source.filters else [])),
                                  "per_page": min(100, limit * 3)}
                    else:
                        params = {"search": query, "filter": window, "per_page": limit}
                    if os.getenv("CCU_CONTACT_EMAIL"):
                        params["mailto"] = os.environ["CCU_CONTACT_EMAIL"]
                    pages = [fetcher.get(endpoint, params=params, headers=headers,
                                         interval=source.minimum_interval_seconds)]
                    parser = openalex_items
                elif source.access_method == "federal_register":
                    params = {
                        "conditions[term]": source_query,
                        "conditions[publication_date][gte]": str(since),
                        "conditions[publication_date][lte]": str(until),
                        "per_page": min(100, limit * 3),
                        "order": "relevance",
                        "fields[]": ["title", "publication_date", "html_url", "abstract", "type"],
                    }
                    pages = [fetcher.get(endpoint, params=params, interval=source.minimum_interval_seconds)]
                    parser = federal_register_items
                else:
                    pages = []
                    for page in range(1, source.pages + 1):
                        raw = fetcher.rss(source, page)
                        pages.append(raw)
                        dates = [normalize_date(i.get("publication_date")) for i in rss_items(raw)]
                        # Newest-first feeds: stop once a page reaches back before the window.
                        if not dates or any(d and d < since for d in dates):
                            break
                    parser = rss_items
                items = []
                for raw in pages:
                    digest = hashlib.sha256(raw).hexdigest()
                    folder = Path("data/raw") / source.source_id
                    folder.mkdir(parents=True, exist_ok=True)
                    (folder / f"{digest}.bin").write_bytes(raw)
                    # URLs contain no keys; credentials and request query strings are never logged.
                    (folder / f"{digest}.json").write_text(
                        json.dumps(
                            {
                                "source_id": source.source_id,
                                "url": endpoint,
                                "retrieved_at": datetime.now(UTC).isoformat(),
                                "sha256": digest,
                                "reuse_restrictions": source.reuse_restrictions,
                                "since": str(since),
                                "until": str(until),
                                "query": source_query,
                                "limit": limit,
                            },
                            indent=2,
                        )
                    )
                    counts["raw_files"].append(str(folder / f"{digest}.bin"))
                    items += parser(raw)
                kept = 0
                for item in items:
                    if kept >= limit:
                        break
                    counts["considered"] += 1
                    try:
                        article = analyze(normalize(item, source.source_id), companies)
                        effective_date = article.publication_date or article.source_updated_date
                        if effective_date and not since <= effective_date <= until:
                            counts["outside_window"] += 1
                            continue
                        if effective_date is None:
                            counts["unknown_date"] += 1
                            continue
                        kept += 1
                        _, added = store.add_article(article)
                        counts["added" if added else "duplicates"] += 1
                    except (ValueError, KeyError, TypeError):
                        counts["failed"] += 1
                        store.log(
                            source.source_id,
                            "invalid_item",
                            "Malformed article skipped; inspect private raw response",
                        )
                source.last_successful_retrieval = datetime.now(UTC)
                with store.db:
                    store.db.execute(
                        "INSERT INTO sources VALUES(?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                        (source.source_id, source.model_dump_json()),
                    )
                if kept >= limit:
                    counts["limited"] += 1
                    store.log(
                        source.source_id,
                        "bounded",
                        f"Reached configured {limit}-record cap; coverage is incomplete",
                    )
                store.log(source.source_id, "success", f"Parsed {len(items)} metadata records")
            except Exception as exc:
                # Do not log exception text: HTTP errors can contain request secrets.
                counts["failed"] += 1
                store.log(
                    source.source_id, "failed", type(exc).__name__ + "; use manual ingestion or retry later"
                )
                LOG.warning("Source %s unavailable (%s)", source.source_id, type(exc).__name__)
    finally:
        fetcher.client.close()
    candidates = Path("data/candidates")
    candidates.mkdir(parents=True, exist_ok=True)
    (candidates / "articles.json").write_text(
        json.dumps([a.model_dump(mode="json") for a in store.articles()], indent=2)
    )
    (candidates / "event-proposals.json").write_text(
        json.dumps([e for a in store.articles() for e in event_candidates(a)], indent=2)
    )
    (candidates / "metric-proposals.json").write_text(
        json.dumps(
            [m.model_dump(mode="json") for a in store.articles() for m in extract_metrics(a)], indent=2
        )
    )
    return counts
