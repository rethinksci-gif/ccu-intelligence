import argparse
import json
import shutil
from dataclasses import replace
from datetime import date
from pathlib import Path

import httpx
import pytest
import yaml

from ccu_intelligence.budget import Budget
from ccu_intelligence.collect import Fetcher
from ccu_intelligence.editorial import SECTIONS, read_issue, validate_issue
from ccu_intelligence.llm import run
from ccu_intelligence.models import Bundle
from ccu_intelligence.workflow import execute

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def no_external_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Tests must never use an external HTTP transport')
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', forbidden)
    monkeypatch.setattr('ccu_intelligence.workflow.load_environment', lambda: None)
    monkeypatch.setenv('LLM_API_KEY', 'fixture-secret-never-real')
    monkeypatch.setenv('LLM_MODEL', 'deepseek-flash')
    monkeypatch.setenv('LLM_BASE_URL', 'https://api.deepseek.com')
    monkeypatch.delenv('GITHUB_ACTIONS', raising=False)
    monkeypatch.setattr('ccu_intelligence.llm.time.sleep', lambda _: None)


@pytest.fixture
def research(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    shutil.copytree(ROOT / 'config', 'config')
    company = ('<item><title>CO2 methanol pilot commissioned</title><link>https://example.org/pilot</link>'
               '<pubDate>Sun, 20 Sep 2026 12:00:00 GMT</pubDate>'
               '<description>Commissioned on 2026-09-20. Investment USD 10 million.</description></item>')
    other = ('<item><title>Solar park financing</title><link>https://example.org/solar</link>'
             '<pubDate>Sun, 20 Sep 2026 12:00:00 GMT</pubDate></item>')

    def rss(items):
        return ('<rss><channel>' + items + '</channel></rss>').encode()

    def get(self, url, **kwargs):
        if url.endswith('robots.txt'):
            return b'User-agent: *\nAllow: /\n'
        if 'api.crossref.org' in url:
            assert kwargs['params']['sort'] == 'score'
            assert 'query.title' in kwargs['params']
            return json.dumps({'message': {'items': [{
                'title': ['CO2 reduction to methanol review'], 'URL': 'https://doi.org/10.1/ccu',
                'DOI': '10.1/ccu', 'published': {'date-parts': [[2026, 9, 20]]},
            }]}}).encode()
        if 'api.openalex.org' in url:
            return json.dumps({'results': [{
                'display_name': 'CO2 reduction to methanol review', 'doi': 'https://doi.org/10.1/ccu',
                'id': 'https://openalex.org/W1', 'publication_date': '2026-09-20',
            }]}).encode()
        if 'liquidwind.com' in url:
            return rss(company + company)
        if 'carbicrete.com' in url:
            return rss(company.replace('/pilot', '/syndicated'))
        if 'gov.uk' in url:
            return (b'<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
                    b'<title>CO2 conversion funding programme</title><link href="https://example.org/gov"/>'
                    b'<published>2026-09-21</published></entry><entry>'
                    b'<title>CO2 conversion update</title><link href="https://example.org/undated"/>'
                    b'<updated>2026-09-21</updated></entry></feed>')
        return rss(other)

    monkeypatch.setattr(Fetcher, 'get', get)
    options = argparse.Namespace(
        since=date(2026, 9, 14), until=date(2026, 9, 27), scheduled_publication=None,
        output=Path('data/runtime/test-run'), max_analyses=30, max_requests=60,
        token_budget=120000, max_output_tokens=1200, allow_paid=True, dry_run=False,
        max_spend_usd=0.5, rate_ceiling=1.2, source_limit=15,
    )
    calls = []

    def handler(request):
        data = json.loads(request.content)
        assert data['model'] == 'deepseek-flash' and data['thinking'] == {'type': 'disabled'}
        assert data['max_tokens'] == 1200
        source = json.loads(data['messages'][1]['content'])['source_text']
        calls.append(source)
        proposal = dict(relevant=True, domains=['conversion'], quotes=[source.split('\n')[0]],
                        draft_summary='Source reports a CO2 conversion topic; review required.',
                        technical_significance='Source-reported topic only.',
                        industrial_implications='Commercial output is not independently established.',
                        uncertainty='Needs original source review.',
                        technical_information=[], economic_information=[], milestone_proposals=[])
        if 'Investment USD 10 million.' in source:
            proposal['economic_information'] = [dict(text='Reported investment: USD 10 million.',
                quote='Investment USD 10 million.', uncertainty='Reported, not audited.')]
            proposal['technical_information'] = [dict(text='Methanol pilot described.',
                quote='CO2 methanol pilot commissioned', uncertainty='Performance unknown.')]
            proposal['milestone_proposals'] = [dict(text='Reported commissioning.',
                quote='Commissioned on 2026-09-20.', uncertainty='Needs verification.',
                event_type='COMMISSIONED', event_date='2026-09-20', project_name=None)]
        return httpx.Response(200, json={
            'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(proposal)}}],
            'usage': {'prompt_tokens': 200, 'completion_tokens': 100, 'total_tokens': 300},
        })

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr('ccu_intelligence.workflow.run', lambda *a, **kw: run(*a, client=client, **kw))
    yield options, calls
    client.close()


def test_complete_pipeline_deduplicates_filters_extracts_and_drafts(research, capsys):
    args, calls = research
    report = execute(args)
    assert len(calls) == report['requests_reserved'] == 3
    assert report['promising_candidates'] == 3
    assert all('Solar' not in text and 'update' not in text for text in calls)
    assert len([s for s in calls if 'pilot' in s]) == 1
    draft = Path(report['draft'])
    meta, body = read_issue(draft)
    assert meta['editorial_status'] == 'draft' and meta['reviewer'] is None
    assert meta['event_ids'] == [] and not any(meta['review_checklist'].values())
    assert all('## ' + heading in body for heading in SECTIONS)
    assert 'USD 10 million' in body and 'COMMISSIONED' in body
    assert 'https://example.org/pilot' in body and 'https://doi.org/10.1/ccu' in body
    assert 'fixture-secret' not in capsys.readouterr().out
    assert not Path('public').exists() and not Path('src/content/issues').exists()
    bundle = Bundle.model_validate_json((args.output / 'bundle.json').read_text())
    assert bundle.events == [] and all(a.review_required for a in bundle.articles)
    validate_issue(draft, bundle)
    unpublished = draft.read_text().replace('editorial_status: draft', 'editorial_status: published')
    draft.write_text(unpublished)
    with pytest.raises(ValueError, match='reviewer'):
        validate_issue(draft, bundle)


def test_cache_and_completed_run_make_no_repeat_paid_calls(research):
    args, calls = research
    report = execute(args)
    execute(args)
    assert len(calls) == 3
    args.output = Path('data/runtime/second-run')
    cached = execute(args)
    assert len(calls) == 3 and cached['cache_hits'] == 3 and cached['requests_reserved'] == 0
    assert report['reserved_cost_usd'] > 0 and cached['reserved_cost_usd'] == 0


@pytest.mark.parametrize('mode', ['explicit', 'default', 'zero-spend', 'zero-tokens'])
def test_zero_paid_requests(research, mode):
    args, calls = research
    if mode == 'explicit':
        args.dry_run = True
    elif mode == 'default':
        del args.allow_paid
    elif mode == 'zero-spend':
        args.max_spend_usd = 0
    else:
        args.token_budget = 1
    report = execute(args)
    assert calls == [] and report['requests_reserved'] == 0
    assert 'https://example.org/pilot' in Path(report['draft']).read_text()


def test_invalid_caps_fail_before_collection(research):
    args, calls = research
    args.max_analyses = 31
    with pytest.raises(ValueError, match='30'):
        execute(args)
    assert not args.output.exists() and calls == []


@pytest.mark.parametrize('event,ref,attempt', [
    ('pull_request', 'refs/heads/main', '1'),
    ('pull_request_target', 'refs/heads/main', '1'),
    ('workflow_dispatch', 'refs/heads/untrusted', '1'),
    ('workflow_dispatch', 'refs/heads/main', '2'),
    ('schedule', 'refs/heads/main', '1'),
])
def test_untrusted_or_retry_run_rejected_before_payment(research, monkeypatch, event, ref, attempt):
    args, calls = research
    monkeypatch.setenv('GITHUB_ACTIONS', 'true')
    monkeypatch.setenv('GITHUB_EVENT_NAME', event)
    monkeypatch.setenv('GITHUB_REF', ref)
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT', attempt)
    with pytest.raises(ValueError, match='trusted'):
        execute(args)
    assert calls == []


def test_attempt_marker_survives_crash_without_repaying(research, monkeypatch):
    args, calls = research
    args.max_analyses = 1
    def crash(*a, **kw):
        assert kw['budget'].reserve(1000)
        raise RuntimeError('simulated crash after request reservation')
    monkeypatch.setattr('ccu_intelligence.workflow.run', crash)
    with pytest.raises(RuntimeError):
        execute(args)
    report = execute(args)
    assert report['new_analyses_attempted'] == report['requests_reserved'] == 1
    assert calls == []


def test_tampered_cached_extraction_rejected(research):
    args, calls = research
    execute(args)
    for path in Path('data/runtime/llm-cache').glob('*.json'):
        data = json.loads(path.read_text())
        data['analysis']['economic_information'] = [dict(text='Invented', quote='not in source', uncertainty='?')]
        path.write_text(json.dumps(data))
    args.output = Path('data/runtime/new-run')
    with pytest.raises(ValueError, match='unsupported extraction'):
        execute(args)
    assert len(calls) == 3


def test_money_reservations_survive_restart_and_are_never_refunded(tmp_path):
    path = tmp_path / 'budget.json'
    budget = Budget(max_tokens=10000, max_spend_usd=0.0012, path=path)
    assert budget.reserve(1000)
    budget.settle(1000, 10)
    budget = Budget(**json.loads(path.read_text()), path=path)
    assert budget.charged_tokens == 10
    assert budget.reserved_cost_microusd == 1200
    assert not budget.reserve(1)
    assert not replace(budget, max_requests=0).reserve(1)


@pytest.mark.parametrize('amount', [-1, float('nan'), float('inf')])
def test_invalid_dollar_budgets_rejected(amount):
    with pytest.raises(ValueError):
        Budget(max_spend_usd=amount)


def test_uncertain_usage_and_retry_cannot_escape_budget():
    budget = Budget(max_requests=1, max_tokens=100000, max_spend_usd=1)
    calls = []
    def fail(request):
        calls.append(request)
        return httpx.Response(503)
    with httpx.Client(transport=httpx.MockTransport(fail)) as client:
        result = run('grounded', 'CO2 conversion', ['e'], client=client, budget=budget)
    assert result is None and len(calls) == 1 and budget.requests == 1
    charged = budget.charged_tokens
    for usage in (None, -10, True, charged + 1):
        budget.settle(charged, usage)
        assert budget.charged_tokens == charged


def test_workflow_has_no_schedule_or_pr_payment_trigger():
    workflow = yaml.load((ROOT / '.github/workflows/deepseek-research.yml').read_text(), Loader=yaml.BaseLoader)
    assert set(workflow['on']) == {'workflow_dispatch'}
    assert workflow['on']['workflow_dispatch']['inputs']['mode']['default'] == 'dry-run'
    assert workflow['permissions'] == {'contents': 'read'}
    steps = workflow['jobs']['research']['steps']
    secret_steps = [s for s in steps if 'LLM_API_KEY' in s.get('env', {})]
    assert len(secret_steps) == 1
    assert "inputs.mode == 'paid'" in secret_steps[0]['if']
    assert "vars.CCU_ENABLE_DEEPSEEK == 'true'" in secret_steps[0]['if']
    assert 'github.run_attempt == 1' in secret_steps[0]['if']
