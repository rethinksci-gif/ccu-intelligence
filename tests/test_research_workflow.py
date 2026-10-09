import json
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import yaml

from ccu_intelligence.budget import Budget
from ccu_intelligence.collect import Fetcher
from ccu_intelligence.llm import date_supported, grounded_analysis, quote_supported, run
from ccu_intelligence.workflow import BORDERLINE, BRIEF, NON_ACADEMIC, triage

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def no_external_network(monkeypatch):
    # conftest.py blocks HTTP transports, DNS and sockets for every test.
    monkeypatch.setattr('ccu_intelligence.workflow.load_environment', lambda: None)
    monkeypatch.setenv('LLM_API_KEY', 'fixture-secret-never-real')
    monkeypatch.setenv('LLM_MODEL', 'deepseek-flash')
    monkeypatch.setenv('LLM_BASE_URL', 'https://api.deepseek.com')
    monkeypatch.delenv('GITHUB_ACTIONS', raising=False)
    monkeypatch.setattr('ccu_intelligence.llm.time.sleep', lambda _: None)


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
    assert {'max_screenings', 'max_enrichments', 'max_spend_usd', 'token_budget', 'screening_model', 'strong_model', 'coverage_end',
            'coverage_days'} <= set(inputs)
    assert inputs['coverage_end']['default'] == '' and inputs['coverage_days']['default'] == '14'
    assert inputs['max_screenings']['default'] == '150' and inputs['max_enrichments']['default'] == '60'
    assert inputs['max_spend_usd']['default'] == '5'
    assert inputs['token_budget']['default'] == '2000000' and inputs['strong_model']['default'] == 'deepseek-v4-pro'
    assert workflow['permissions'] == {'contents': 'read'}
    assert 'LLM_API_KEY' not in json.dumps(workflow['env'])
    dry, paid = workflow['jobs']['dry-run'], workflow['jobs']['paid']
    # The dry-run job has no environment and never sees the key.
    assert 'environment' not in dry and 'LLM_API_KEY' not in json.dumps(dry)
    assert dry['env']['RESEARCH_MODE'] == 'dry-run' and "inputs.mode == 'dry-run'" in dry['if']
    # The paid job is gated by mode, repository opt-in, first attempt, default branch and an environment
    # whose only protection is the main-branch policy (no required reviewers; see docs/operations.md).
    assert paid['environment'] == 'deepseek-paid'
    assert all(job['runs-on'] == 'ubuntu-24.04' for job in workflow['jobs'].values())
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
    (GENERAL, 'Solar park financing', 'no CCU term'),
    (GENERAL, 'Perovskite solar cell efficiency record', 'no CCU term'),
    (GENERAL, 'Lithium battery recycling plant', 'no CCU term'),
])
def test_unrelated_headlines_dropped(source, title, reason):
    result = triage(headline(title), source, DAY, DAY)
    assert not result['eligible'] and result['reason'] == reason


def test_company_news_without_ccu_term_goes_to_the_gate():
    result = triage(headline('Company welcomes new board member'), SPECIALIST, DAY, DAY)
    assert result['eligible'] and result['reason'] == NON_ACADEMIC


@pytest.mark.parametrize('source,title', [
    (GENERAL, 'CO2 footprint of nuclear power'),
    (GENERAL, 'Mapping data centre energy consumption to carbon-dioxide emissions'),
    (GENERAL, 'Highlights from CO2 Value Europe'),
])
def test_keyword_borderline_headlines_go_to_the_llm_gate(source, title):
    # Previously dropped by keyword; the relevance gate now decides with the full text.
    result = triage(headline(title), source, DAY, DAY)
    assert result['eligible'] and result['reason'] == BORDERLINE


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


# --- Ecosystem briefs ---------------------------------------------------------------------------------

ASSOCIATION = SimpleNamespace(source_id='co2-value-europe', source_type='industry_association')
GOVERNMENT = SimpleNamespace(source_id='uk-desnz', source_type='government')


@pytest.mark.parametrize('source,title', [
    (ASSOCIATION, 'MVV Umwelt Joins CO₂ Value Europe'),
    (ASSOCIATION, 'CO2 Value Europe annual general assembly'),
    (SPECIALIST, 'Dioxycle joins CO2 industry alliance'),
])
def test_specialist_ecosystem_news_goes_to_the_gate(source, title):
    # The gate decides; relevant items below the threshold become headline-only briefs in the draft.
    result = triage(headline(title), source, DAY, DAY)
    assert result['reason'] == BRIEF and result['eligible']


@pytest.mark.parametrize('source,title', [
    (GENERAL, 'Ultrasonic-Swing Carbon Dioxide Release Using Aralkylamines for Direct Air Capture'),
    (GENERAL, 'A Research Strategy for Ocean-based Carbon Dioxide Removal and Sequestration'),
    (GOVERNMENT, 'Carbon capture and storage cluster sequencing update'),
])
def test_pure_capture_and_removal_are_left_to_the_gate(source, title):
    result = triage(headline(title), source, DAY, DAY)
    assert result['eligible'] and result['reason'] == BORDERLINE


@pytest.mark.parametrize('source,title', [
    (ASSOCIATION, 'Welcome to our new events officer'),  # no CCU term: dropped
    (SPECIALIST, 'Solar park financing'),
])
def test_non_ccu_specialist_items_still_dropped(source, title):
    assert not triage(headline(title), source, DAY, DAY)['eligible']


def ecosystem_headline(title):
    # The CCU term sits in the summary, as in real association feeds.
    return SimpleNamespace(title=title, summary='News from CO2 Value Europe.', sample=False, publication_date=DAY)


@pytest.mark.parametrize('title', [
    'Welcome to Our New Communication & Events Officer, Giulia!',
    'WELCOME our new policy officer',
    'Anna joins our team as project manager',
    'Meet our new colleague',
    "We're hiring: CO2 utilisation analyst",
    'Vacancy: Policy Officer',
    'Job opening – events coordinator',
    'Internship in EU affairs',
])
def test_staff_announcements_dropped_from_briefs(title):
    result = triage(ecosystem_headline(title), ASSOCIATION, DAY, DAY)
    assert not result['eligible'] and result['reason'] == 'specialist source: staff/HR announcement'


@pytest.mark.parametrize('title', [
    'MVV Umwelt Joins CO₂ Value Europe',
    'Carbon Clean joins CO2 Value Europe',
    'CO2 Value Europe welcomes new member Carbon Clean',
    'Welcome to our new members: Topsoe and Dioxycle',
    'CO2 Value Europe general assembly',
])
def test_membership_news_still_reaches_the_gate(title):
    result = triage(ecosystem_headline(title), ASSOCIATION, DAY, DAY)
    assert result['reason'] == BRIEF and result['eligible']


# --- Fetcher politeness: low frequency, backoff, no hammering on 403/429 --------------------------------

@pytest.fixture
def polite(monkeypatch):
    sleeps, requests, responses = [], [], []
    monkeypatch.setattr('ccu_intelligence.collect.public_url', lambda url: None)
    monkeypatch.setattr('ccu_intelligence.collect.time.sleep', sleeps.append)

    def handler(request):
        requests.append(request)
        return responses.pop(0)

    fetcher = Fetcher(client=httpx.Client(transport=httpx.MockTransport(handler)))
    yield fetcher, responses, requests, sleeps
    fetcher.client.close()


def test_forbidden_403_is_not_retried(polite):
    fetcher, responses, requests, sleeps = polite
    responses.append(httpx.Response(403))
    with pytest.raises(httpx.HTTPStatusError):
        fetcher.get('https://example.org/feed')
    assert len(requests) == 1 and sleeps == []


def test_429_backs_off_and_gives_up_after_one_retry(polite):
    fetcher, responses, requests, sleeps = polite
    responses.extend([httpx.Response(429)] * 2)
    with pytest.raises(httpx.HTTPStatusError):
        fetcher.get('https://example.org/feed', interval=0)
    assert len(requests) == 2 and sleeps == pytest.approx([1], abs=0.01)  # interval 0: at least 1 s


def test_long_retry_after_defers_to_next_run(polite):
    fetcher, responses, requests, sleeps = polite
    responses.append(httpx.Response(429, headers={'Retry-After': '120'}))
    with pytest.raises(ValueError, match='deferred'):
        fetcher.get('https://example.org/feed')
    assert len(requests) == 1 and sleeps == []


def test_short_retry_after_is_honoured(polite):
    fetcher, responses, requests, sleeps = polite
    responses.extend([httpx.Response(503, headers={'Retry-After': '7'}), httpx.Response(200, content=b'ok')])
    assert fetcher.get('https://example.org/feed', interval=0) == b'ok'
    assert len(requests) == 2 and sleeps == pytest.approx([7], abs=0.01)


def test_minimum_interval_between_requests_to_same_host(polite):
    fetcher, responses, requests, sleeps = polite
    responses.extend([httpx.Response(200, content=b'robots'), httpx.Response(200, content=b'feed')])
    fetcher.get('https://example.org/robots.txt', interval=5)
    fetcher.get('https://example.org/feed', interval=5)
    assert len(requests) == 2 and len(sleeps) == 1 and 4.5 < sleeps[0] <= 5


def test_dropped_connection_is_retried_with_interval_based_backoff(polite):
    # GDELT closes the connection without a response when it throttles (RemoteProtocolError, run 37957332241).
    fetcher, responses, requests, sleeps = polite
    responses.extend([httpx.RemoteProtocolError('Server disconnected without sending a response.'),
                      httpx.Response(200, content=b'ok')])

    def handler(request):
        requests.append(request)
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    fetcher.client = httpx.Client(transport=httpx.MockTransport(handler))
    assert fetcher.get('https://api.example.org/doc', interval=15) == b'ok'
    assert len(requests) == 2 and sleeps == pytest.approx([15], abs=0.01)


def test_429_backoff_scales_with_the_hosts_interval(polite):
    fetcher, responses, requests, sleeps = polite
    responses.extend([httpx.Response(429), httpx.Response(200, content=b'ok')])
    assert fetcher.get('https://api.example.org/doc', interval=15) == b'ok'
    assert sleeps == pytest.approx([15], abs=0.01)


def test_spacing_counts_from_the_end_of_a_slow_response(polite, monkeypatch):
    fetcher, responses, requests, sleeps = polite
    clock = iter([100.0, 110.0, 110.0, 110.0])  # the first response takes 10 s
    monkeypatch.setattr('ccu_intelligence.collect.time.monotonic', lambda: next(clock))
    responses.extend([httpx.Response(200, content=b'a'), httpx.Response(200, content=b'b')])
    fetcher.get('https://api.example.org/doc', interval=15)
    fetcher.get('https://api.example.org/doc', interval=15)
    assert sleeps == [15]  # a start-to-start rule would have slept only 5 s


def test_unreadable_robots_fails_closed_with_a_diagnosis(polite):
    fetcher, responses, requests, sleeps = polite
    responses.extend([httpx.ReadTimeout('timed out')] * 2)

    def handler(request):
        requests.append(request)
        raise responses.pop(0)

    fetcher.client = httpx.Client(transport=httpx.MockTransport(handler))
    source = SimpleNamespace(endpoint='https://news.example.org/?s=x&feed=rss2', base_url=None,
                             minimum_interval_seconds=3)
    with pytest.raises(ValueError, match=r'robots.txt unreadable \(ReadTimeout\); collection fails closed'):
        fetcher.rss(source)
    assert len(requests) == 2 and sleeps == pytest.approx([1], abs=0.01)  # robots.txt only; the feed itself is never requested


# --- Prompt v4 dates ----------------------------------------------------------------------------------

@pytest.mark.parametrize('event_date', ['2026-10-10', '2026-11-09', '2025-10-09', '2026-09-10'])
def test_month_name_date_absent_from_source_is_rejected(event_date):
    text = 'FlagshipONE was commissioned on 9 October 2026.'
    milestone = dict(text='Reported commissioning.', quote='FlagshipONE was commissioned', uncertainty='?',
                     event_type='COMMISSIONED', event_date=event_date)
    assert not date_supported(date.fromisoformat(event_date), text)
    with pytest.raises(ValueError, match='Event date'):
        grounded_analysis(proposal(milestone_proposals=[milestone]), text, ['e1'], 'company')
