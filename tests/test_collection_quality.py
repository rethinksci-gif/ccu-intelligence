import shutil
from datetime import date
from types import SimpleNamespace

import pytest

from ccu_intelligence.collect import collect, gdelt_items, registry
from ccu_intelligence.normalize import normalize, parse_date
from ccu_intelligence.store import Store
from ccu_intelligence.workflow import triage


@pytest.mark.parametrize('value,expected', [
    ('2026-10-09T00:30:00+02:00', date(2026, 10, 8)),
    ('Thu, 08 Oct 2026 23:30:00 -0400', date(2026, 10, 9)),
    ('2026-10-09', date(2026, 10, 9)),
    ('2026-10-09 garbage', None), ('2026-02-30', None),
])
def test_publication_dates_respect_utc_window(value, expected):
    assert parse_date(value) == expected


def test_index_discovery_is_not_publication():
    item = gdelt_items(b'{"articles":[{"title":"CO2 to methanol plant", "url":"https://example.org/plant", "seendate":"20261008T120000Z"}]}')[0]
    article = normalize(item, 'gdelt-efuels')
    assert article.publication_date is None
    assert article.discovery_date == date(2026, 10, 8)
    source = next(s for s in registry() if s.source_id == 'gdelt-efuels')
    assert not triage(article, source, date(2026, 9, 25), date(2026, 10, 8))['eligible']


def feed(*items):
    return ('<rss><channel>' + ''.join(
        f'<item><title>{name}</title><link>https://example.org/{name}</link><pubDate>{day}</pubDate></item>'
        for name, day in items) + '</channel></rss>').encode()


def test_pinned_old_feed_item_does_not_hide_later_pages(tmp_path, monkeypatch):
    source = next(s for s in registry() if s.source_id == 'news-utilization-carbonherald')
    source = source.model_copy(update={'pages': 3, 'include_pattern': None})
    shutil.copytree("config", tmp_path / "config")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr('ccu_intelligence.collect.registry', lambda: [source])
    pages = {1: feed(('pinned', '2020-01-01'), ('new', '2026-10-08')),
             2: feed(('later', '2026-10-07')), 3: feed(('old', '2020-01-02'))}
    requested = []

    def rss(source, page):
        requested.append(page)
        return pages[page]

    store = Store(tmp_path / 'records.sqlite')
    try:
        counts = collect(store, date(2026, 10, 1), date(2026, 10, 8), source.source_id,
                         fetcher=SimpleNamespace(rss=rss))
        assert requested == [1, 2, 3]
        assert counts['added'] == 2 and counts['outside_window'] == 2
        assert counts['source_failures'] == 0
    finally:
        store.close()


def test_duplicates_do_not_use_new_candidate_allowance(tmp_path, monkeypatch):
    source = next(s for s in registry() if s.source_id == 'news-utilization-carbonherald')
    source = source.model_copy(update={'pages': 1, 'include_pattern': None})
    shutil.copytree("config", tmp_path / "config")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr('ccu_intelligence.collect.registry', lambda: [source])
    raw = feed(('existing', '2026-10-08'), ('existing', '2026-10-08'), ('new', '2026-10-08'))
    store = Store(tmp_path / 'records.sqlite')
    try:
        store.add_article(normalize({'title': 'existing', 'url': 'https://example.org/existing',
                                     'publication_date': '2026-10-08'}, source.source_id))
        counts = collect(store, date(2026, 10, 1), date(2026, 10, 8), source.source_id,
                         limit=1, fetcher=SimpleNamespace(rss=lambda *_: raw))
        assert counts['added'] == 1 and counts['duplicates'] == 2
        assert {a.title for a in store.articles()} == {'existing', 'new'}
    finally:
        store.close()


def test_dated_source_resolves_only_same_identity_discovery_lead(tmp_path):
    store = Store(tmp_path / 'records.sqlite')
    try:
        item = {'title': 'CO2 methanol plant', 'url': 'https://example.org/project',
                'discovery_date': '2026-10-08'}
        original = normalize(item, 'index')
        store.add_article(original)
        store.add_article(normalize(item | {'url': 'https://other.example/copy',
                                            'publication_date': '2026-10-07'}, 'syndication'))
        assert store.articles()[0].publication_date is None
        identity, added = store.add_article(normalize(item | {'publication_date': '2026-10-06'}, 'publisher'))
        assert not added and identity == original.article_id
        resolved = store.articles()[0]
        assert resolved.publication_date == date(2026, 10, 6) and resolved.source_id == 'publisher'
        assert resolved.discovery_date == date(2026, 10, 8)
        store.add_article(normalize(item | {'publication_date': '2026-10-07'}, 'later-feed'))
        assert store.articles()[0].publication_date == date(2026, 10, 6)
    finally:
        store.close()
