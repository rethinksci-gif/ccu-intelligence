import argparse
import importlib.util
import json
import shutil
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import yaml

from ccu_intelligence.budget import Budget
from ccu_intelligence.collect import Fetcher
from ccu_intelligence.editorial import SECTIONS, read_issue, validate_issue
from ccu_intelligence.llm import date_supported, grounded_analysis, quote_supported, run
from ccu_intelligence.models import Bundle
from ccu_intelligence.workflow import cache_key, execute, triage

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
    inputs = workflow['on']['workflow_dispatch']['inputs']
    assert inputs['mode']['default'] == 'dry-run'
    assert {'max_analyses', 'max_spend_usd', 'token_budget'} <= set(inputs)
    assert workflow['permissions'] == {'contents': 'read'}
    assert 'LLM_API_KEY' not in json.dumps(workflow['env'])
    dry, paid = workflow['jobs']['dry-run'], workflow['jobs']['paid']
    # The dry-run job has no environment and never sees the key.
    assert 'environment' not in dry and 'LLM_API_KEY' not in json.dumps(dry)
    assert dry['env']['RESEARCH_MODE'] == 'dry-run' and "inputs.mode == 'dry-run'" in dry['if']
    # The paid job is gated by mode, repository opt-in, first attempt, default branch and an environment.
    assert paid['environment'] == 'deepseek-paid'
    for gate in ("inputs.mode == 'paid'", "vars.CCU_ENABLE_DEEPSEEK == 'true'", 'github.run_attempt == 1',
                 'default_branch'):
        assert gate in paid['if']
    secret_steps = [s for s in paid['steps'] if 'LLM_API_KEY' in s.get('env', {})]
    assert len(secret_steps) == 1


# --- Relevance filter ---------------------------------------------------------------------------------

SPECIALIST = SimpleNamespace(source_id='dioxycle', source_type='company_announcements_and_annual_reports')
GENERAL = SimpleNamespace(source_id='crossref', source_type='scholarly_metadata')
DAY = date(2026, 9, 20)


def headline(title):
    return SimpleNamespace(title=title, summary='', sample=False, publication_date=DAY)


@pytest.mark.parametrize('source,title,reason', [
    (SPECIALIST, 'Solar park financing', 'specialist feed: unrelated energy topic'),
    (SPECIALIST, 'Battery storage project commissioned', 'specialist feed: unrelated energy topic'),
    (SPECIALIST, 'Nuclear plant construction delayed', 'specialist feed: unrelated energy topic'),
    (SPECIALIST, 'Photovoltaic rooftop permit granted', 'specialist feed: unrelated energy topic'),
    (SPECIALIST, 'Company welcomes new board member', 'no CCU term or milestone keyword'),
    (GENERAL, 'Solar park financing', 'no CCU term'),
    (GENERAL, 'Perovskite solar cell efficiency record', 'no CCU term'),
    (GENERAL, 'Lithium battery recycling plant', 'no CCU term'),
    (GENERAL, 'CO2 footprint of nuclear power', 'CCU term without utilization context'),
    (GENERAL, 'Mapping data centre energy consumption to carbon-dioxide emissions',
     'CCU term without utilization context'),
])
def test_unrelated_headlines_dropped(source, title, reason):
    result = triage(headline(title), source, DAY, DAY)
    assert not result['eligible'] and result['reason'] == reason


@pytest.mark.parametrize('source,title', [
    (GENERAL, 'Solar fuels from CO2: photocatalytic reduction to methanol'),
    (GENERAL, 'Solar-driven CO2 electrolysis to ethylene'),
    (GENERAL, 'CO₂-derived battery materials scale up'),
    (GENERAL, 'Power-to-X plant with solar supply'),
    (GENERAL, 'Power-to-liquid project uses nuclear heat'),
    (GENERAL, 'E-fuels pilot paired with battery storage'),
    (GENERAL, 'e-methanol plant powered by solar'),
    (GENERAL, 'E-kerosene facility to use nuclear electricity'),
    (GENERAL, 'Synthetic fuels from solar hydrogen'),
    (GENERAL, 'Direct air capture with CO2 mineralization powered by solar'),
    (GENERAL, 'Carbon mineralisation of battery waste'),
    (GENERAL, 'Electrosynthesis of arylglycines from carbon dioxide, nitrite and aldehydes'),
    (SPECIALIST, 'Solar-powered CO2 electrolyser commissioned'),
    (SPECIALIST, 'Nuclear-powered e-methanol plant reaches FID'),
    (SPECIALIST, 'CO2-derived battery materials plant commissioned'),
    (SPECIALIST, 'Direct air capture unit with solar supply commissioned'),
    (SPECIALIST, 'FlagshipONE reaches final investment decision'),
])
def test_ccu_headlines_with_energy_words_kept(source, title):
    assert triage(headline(title), source, DAY, DAY)['eligible']


# --- Source failure isolation -------------------------------------------------------------------------

def test_failing_sources_never_abort_run(research, monkeypatch):
    args, calls = research
    working = Fetcher.get

    def get(self, url, **kwargs):
        if 'co2value.eu' in url:
            request = httpx.Request('GET', url)
            raise httpx.HTTPStatusError('403', request=request, response=httpx.Response(403, request=request))
        if 'covestro.com' in url:
            raise RuntimeError('unexpected parser or transport failure')
        return working(self, url, **kwargs)

    monkeypatch.setattr(Fetcher, 'get', get)
    report = execute(args)
    collection = json.loads((args.output / 'collection.json').read_text())
    assert collection['co2-value-europe']['failed'] == collection['covestro']['failed'] == 1
    assert len(calls) == report['requests_reserved'] == 3


def test_user_agent_identifies_bot_without_blocked_word():
    agent = Fetcher().client.headers['User-Agent']
    assert agent.startswith('CCUIntelligence/') and 'https://' in agent and 'research' not in agent.lower()


# --- Grounding normalization --------------------------------------------------------------------------

@pytest.mark.parametrize('quote,source', [
    ('Liquid Wind\'s "FlagshipONE" plant', 'Liquid Wind’s “FlagshipONE” plant'),
    ('Liquid Wind’s “FlagshipONE” plant', 'Liquid Wind\'s "FlagshipONE" plant'),
    ('capacity of 70 000 t per year', 'capacity of\n70 000   t per year'),
    ('CO2 electrolysis', 'Scaling CO₂ electrolysis'),
    ('2025-2026 programme', 'the 2025–2026 programme'),
    ('electrochemical reactor', 'an electro­chemical reactor'),
    ('electrochemical reactor', 'an electro-\nchemical reactor'),
    ('CO2-derived polyols', 'uses CO2-\nderived polyols'),
    ('ＦＩＤ reached', 'FID reached'),
])
def test_quotes_match_after_normalization(quote, source):
    assert quote_supported(quote, source)


@pytest.mark.parametrize('quote,source', [
    ('co2 electrolysis', 'CO2 electrolysis'),  # case is not normalized
    ('capacity of 70 kt per year', 'capacity of 70 000 t per year'),  # paraphrase
    ('pilot commissioned plant', 'pilot commissioned. The plant'),  # combined fragments
    ('electrochemical reactor', 'an electro- chemical reactor'),  # hyphen not at a line break
    ('electro-chemical reactor', 'an electrochemical reactor'),  # hyphen inserted
    ('', 'anything'),
    (' '.join(['word'] * 26), ' '.join(['word'] * 26)),  # over 25 words
])
def test_quotes_rejected_beyond_normalization(quote, source):
    assert not quote_supported(quote, source)


@pytest.mark.parametrize('text', [
    'Commissioned on 2026-10-09.', 'Commissioned on 2026‑10‑09.', 'on 9 October 2026', 'on 09 October 2026',
    'on the 9th of October, 2026', 'on October 9, 2026', 'on Oct. 9, 2026', 'on 9 Oct 2026', 'OCTOBER 9 2026',
])
def test_event_dates_in_explicit_formats_accepted(text):
    assert date_supported(date(2026, 10, 9), text)


@pytest.mark.parametrize('text', [
    'on 09/10/2026', 'on 10/09/2026', 'on 09.10.2026', 'in October 2026', 'on 9 October 2025',
    'on 19 October 2026', 'on 29 Oct 2026', 'on October 19, 2026', 'on 2026-10-19', 'on 2026-10-091',
    'on 9 October 20261', 'published 2026-10-08',
])
def test_ambiguous_or_different_dates_rejected(text):
    assert not date_supported(date(2026, 10, 9), text)


def test_september_abbreviation_accepted():
    assert date_supported(date(2026, 9, 20), 'on 20 Sept. 2026') and date_supported(date(2026, 9, 20), 'Sep 20, 2026')


def proposal(**extra):
    base = dict(relevant=True, domains=['conversion'], quotes=[], technical_significance='',
                industrial_implications='', uncertainty='Needs review.')
    return json.dumps({**base, **extra})


def test_grounded_analysis_normalizes_quotes_and_dates():
    text = 'Liquid Wind’s FlagshipONE was commissioned on 9 October 2026.'
    milestone = dict(text='Reported commissioning.', quote="Liquid Wind's FlagshipONE was commissioned",
                     uncertainty='Needs verification.', event_type='COMMISSIONED', event_date='2026-10-09')
    result = grounded_analysis(proposal(quotes=['Liquid Wind\'s FlagshipONE'], milestone_proposals=[milestone]),
                               text, ['e1'], 'company')
    assert result.milestone_proposals[0].event_date == date(2026, 10, 9) and len(result.claims) == 1
    with pytest.raises(ValueError, match='Event date'):
        grounded_analysis(proposal(milestone_proposals=[{**milestone, 'event_date': '2026-10-10'}]),
                          text, ['e1'], 'company')
    with pytest.raises(ValueError, match='quotation'):
        grounded_analysis(proposal(quotes=['liquid wind’s flagshipone']), text, ['e1'], 'company')


# --- Cache key ----------------------------------------------------------------------------------------

def article_stub():
    return SimpleNamespace(article_id='a1', publication_date=DAY, canonical_url='https://example.org/a',
                           title='CO2 methanol pilot', summary='Commissioned.')


def test_cache_key_changes_with_prompt_model_and_endpoint(monkeypatch):
    base = dict(kind='company', model='deepseek-flash', endpoint='https://api.deepseek.com', max_tokens=1200)
    key = cache_key(article_stub(), **base)
    assert key == cache_key(article_stub(), **base)
    assert key != cache_key(article_stub(), **{**base, 'model': 'deepseek-v4-pro'})
    assert key != cache_key(article_stub(), **{**base, 'endpoint': 'https://api.deepseek.com/v1'})
    monkeypatch.setattr('ccu_intelligence.workflow.PROMPT_VERSION', 'grounded-next')
    assert key != cache_key(article_stub(), **base)
    monkeypatch.undo()
    monkeypatch.setattr('ccu_intelligence.workflow.prompt_hash', lambda task: 'edited prompt text')
    assert key != cache_key(article_stub(), **base)


def test_prompt_version_change_invalidates_cached_responses(research, monkeypatch):
    args, calls = research
    execute(args)
    assert len(calls) == 3
    monkeypatch.setattr('ccu_intelligence.workflow.PROMPT_VERSION', 'grounded-next')
    args.output = Path('data/runtime/after-prompt-change')
    report = execute(args)
    assert report['cache_hits'] == 0 and len(calls) == 6


# --- Entry-point hard caps ----------------------------------------------------------------------------

def entrypoint():
    spec = importlib.util.spec_from_file_location('research_entry', ROOT / 'scripts/deepseek-research.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('name,value', [
    ('MAX_ANALYSES', '31'), ('MAX_ANALYSES', '-1'),
    ('MAX_SPEND_USD', '0.51'), ('MAX_SPEND_USD', 'nan'), ('MAX_SPEND_USD', 'inf'), ('MAX_SPEND_USD', '-0.01'),
])
def test_dispatch_inputs_cannot_exceed_hard_caps(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        entrypoint().configuration()


def test_recommended_first_paid_run_parameters_accepted(monkeypatch):
    monkeypatch.setenv('MAX_ANALYSES', '6')
    monkeypatch.setenv('MAX_SPEND_USD', '0.10')
    options = entrypoint().configuration()
    assert options.max_analyses == 6 and options.max_spend_usd == 0.10 and options.dry_run
