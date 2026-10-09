import json
import runpy
from pathlib import Path

from ccu_intelligence.models import Bundle
from ccu_intelligence.normalize import normalize


def test_unpaid_draft_preserves_candidate_links_without_review(monkeypatch, tmp_path):
    script = Path('scripts/prepare-draft.py').resolve()
    article = normalize({
        'title': 'CO2 electrolysis research',
        'url': 'https://example.org/research',
        'publication_date': '2026-09-20',
    }, 'crossref')

    def collect_without_model(args):
        assert args.max_screenings == args.max_requests == 0
        assert str(args.since) == '2026-09-14'
        assert str(args.until) == '2026-09-27'
        args.output.mkdir(parents=True)
        (args.output / 'bundle.json').write_text(Bundle(articles=[article]).model_dump_json())
        (args.output / 'collection.json').write_text('{}')
        return {'triage': {article.article_id: {'eligible': True}}, 'promising_candidates': 1}

    monkeypatch.setattr('ccu_intelligence.workflow.execute', collect_without_model)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr('sys.argv', ['prepare-draft.py', '--as-of', '2026-09-28'])
    runpy.run_path(str(script), run_name='__main__')
    text = Path('src/content/issues/2026-09-28.md').read_text()
    assert 'editorial_status: draft' in text
    assert 'reviewer: null' in text
    assert 'https://example.org/research' in text
    assert 'Candidate source inbox' in text
    assert json.loads(Path('data/review/2026-09-28/run.json').read_text())['model_calls'] == 0
