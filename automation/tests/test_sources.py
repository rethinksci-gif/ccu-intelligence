import unittest
from automation.source import Metadata
from automation.confirm import published_inventory
from pathlib import Path
from tempfile import TemporaryDirectory

class PublisherTests(unittest.TestCase):
    def test_explicit_eia_article_date_ignores_navigation_dates(self):
        p=Metadata(eia=True)
        p.feed('<li class="date">Oct 29, 2026</li><span class="date">October 30, 2026</span>')
        self.assertEqual(p.dates,['2026-10-30'])

    def test_other_sites_do_not_infer_dates_from_generic_spans(self):
        p=Metadata()
        p.feed('<span class="date">October 30, 2026</span>')
        self.assertEqual(p.dates,[])

    def test_jsonld_publisher_date(self):
        p=Metadata()
        p.feed('<script type="application/ld+json">{"@type":"Article","datePublished":"2026-10-20T10:00:00Z"}</script>')
        self.assertEqual(p.dates,['2026-10-20'])

    def test_historical_publication_inventory_excludes_drafts(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'issues').mkdir()
            (root/'issues/old.md').write_text('---\nstatus: published\ndate: 2026-10-14\n---\nHistorical edition')
            (root/'issues/new.md').write_text('---\nstatus: draft\ndate: 2026-10-26\n---\nDraft')
            self.assertEqual(published_inventory(root),[{'id':'old','date':'2026-10-14','page':'issues/old/index.html'}])
