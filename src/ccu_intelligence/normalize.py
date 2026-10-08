import hashlib
import re
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .models import Article


def canonical_url(url: str) -> str:
    p = urlsplit(url.strip())
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password:
        raise ValueError("An absolute public HTTP(S) URL is required")
    query = [
        (k, v)
        for k, v in parse_qsl(p.query)
        if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}
    ]
    return urlunsplit(
        (p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/") or "/", urlencode(sorted(query)), "")
    )


def plain(text: str) -> str:
    import html

    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]*>", " ", text))).strip()


def parse_date(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        try:
            return parsedate_to_datetime(str(value)).date()
        except (ValueError, TypeError, OverflowError):
            return None


def normalize(item: dict, source_id: str, sample: bool = False) -> Article:
    url = canonical_url(item["url"])
    title = plain(item.get("title", ""))
    if not title:
        raise ValueError("Missing article title")
    summary = plain(item.get("summary", ""))
    # Exact normalized text catches syndicated copies; fuzzy matches remain editorial work.
    fingerprint = hashlib.sha256(re.sub(r"\W+", "", (title + " " + summary).casefold()).encode()).hexdigest()
    doi = item.get("doi")
    if doi:
        doi = re.sub(r"^(https?://(dx\.)?doi.org/|doi:\s*)", "", doi.strip(), flags=re.I).lower()
    return Article(
        article_id="a-" + hashlib.sha256((doi or url).encode()).hexdigest()[:20],
        source_id=source_id,
        canonical_url=url,
        title=title,
        publication_date=parse_date(item.get("publication_date")),
        source_updated_date=parse_date(item.get("source_updated_date")),
        retrieved_at=datetime.now(UTC),
        doi=doi,
        content_fingerprint=fingerprint,
        summary=summary[:1500],
        sample=sample,
    )
