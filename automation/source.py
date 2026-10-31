"""Retrieve original documents and explicit publisher dates, without inferring crawl dates."""
import json
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from .evidence_gate import canonical, fetch


class Metadata(HTMLParser):
    def __init__(self, eia=False):
        super().__init__()
        self.dates = []
        self.eia = eia
        self.visible_date = False
        self.canonical = None
        self.jsonld = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self.eia and tag == "span" and a.get("class") == "date":
            self.visible_date = True
        if tag == 'meta' and (a.get('property') or a.get('name')) in (
            'article:published_time', 'datePublished', 'citation_publication_date', 'DC.date.issued', 'dc.date.issued'):
            self.dates.append(a.get('content', '')[:10].replace('/', '-'))
        if tag == 'link' and a.get('rel') == 'canonical':
            self.canonical = a.get('href')
        if tag == 'script' and a.get('type') == 'application/ld+json':
            self.jsonld = True

    def handle_endtag(self, tag):
        if tag == "span":
            self.visible_date = False
        if tag == 'script' and self.jsonld:
            try:
                self.walk(json.loads(''.join(self.parts)))
            except ValueError:
                pass
            self.jsonld = False
            self.parts = []

    def handle_data(self, data):
        if self.visible_date:
            try:
                self.dates.append(datetime.strptime(data.strip(), '%B %d, %Y').date().isoformat())
            except ValueError:
                pass
        if self.jsonld:
            self.parts.append(data)

    def walk(self, obj):
        if isinstance(obj, dict):
            if isinstance(obj.get('datePublished'), str):
                self.dates.append(obj['datePublished'][:10])
            for value in obj.values():
                self.walk(value)
        elif isinstance(obj, list):
            for value in obj:
                self.walk(value)


def original(url, authority, expected_date=None):
    import trafilatura
    final, raw, content_type = fetch(url)
    if 'html' not in content_type:
        raise ValueError('unsupported source format; preserve for later extraction')
    html = raw.decode('utf-8', errors='replace')
    meta = Metadata(eia=urlsplit(final).hostname == 'www.eia.gov' and urlsplit(final).path.startswith('/todayinenergy/'))
    meta.feed(html)
    canonical_url = canonical(urljoin(final, meta.canonical)) if meta.canonical else final
    # Canonical aliases must resolve to the same document, not merely be asserted by markup.
    if canonical_url != final:
        resolved, other, _ = fetch(canonical_url)
        if other != raw and resolved != final:
            raise ValueError('canonical document differs from fetched evidence')
    text = trafilatura.extract(html, include_tables=True, include_comments=False) or ''
    if len(text) < 500:
        raise ValueError('original source text insufficient')
    unique = sorted(set(meta.dates))
    when = expected_date or (unique[0] if len(unique) == 1 else None)
    return {'url':canonical_url, 'status':200, 'text':text[:50000], 'authority':authority,
            'date':when, 'date_verified':bool(when and when in unique), 'publisher_dates':unique}
