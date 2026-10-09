"""Full-text input, two-stage analysis, verification, selection and synthesis — mocked API, no network."""

import argparse
import importlib.util
import json
import shutil
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import yaml

from ccu_intelligence import pricing
from ccu_intelligence.budget import Budget
from ccu_intelligence.collect import Fetched, Fetcher
from ccu_intelligence.editorial import read_issue
from ccu_intelligence.fulltext import MARKERS, PageReader, SourceText, obtain, select_content
from ccu_intelligence.llm import complete_json
from ccu_intelligence.models import NOT_STATED, DedupResult, Enrichment, Screening, VerificationResult
from ccu_intelligence.stages import (
    apply_verification,
    dedup_groups,
    ground_enrichment,
    keep_supported_numbers,
    merge_stories,
    move_requests,
    newsletter_config,
    numbers,
    select,
    short_line,
    story_groups,
    takeaways,
)
from ccu_intelligence.workflow import execute, triage

ROOT = Path(__file__).resolve().parents[1]
SENTINEL = "Sentinel publisher sentence that must never leave the private cache"


def page(text: str) -> bytes:
    paragraphs = "".join(f"<p>{p}</p>" for p in text.split("\n\n"))
    return (f"<html><head><title>t</title></head><body><nav>Menu</nav><article><h1>Headline</h1>{paragraphs}"
            "</article><footer>Footer</footer></body></html>").encode()


def tiny_pdf(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [b"<</Type/Catalog/Pages 2 0 R>>", b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
               b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
               b"<</Length %d>>stream\n" % len(stream) + stream + b"\nendstream",
               b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>"]
    out, offsets = b"%PDF-1.4\n", []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    return out + b"trailer<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)


def long_text(core: str, filler: int = 12) -> str:
    padding = "\n\n".join(f"Paragraph {i} discusses process context, operating experience and plans in detail "
                          f"so that the extracted article is clearly longer than a feed snippet." for i in range(filler))
    return core + "\n\n" + padding + "\n\n" + SENTINEL + "."


class FakeWeb:
    """Routes Fetcher.fetch by URL; records every request."""

    def __init__(self, routes: dict, disallow: tuple = ()):
        self.routes, self.disallow, self.requests = routes, disallow, []

    def __call__(self, fetcher, url, **kwargs):
        self.requests.append(url)
        if url.endswith("/robots.txt"):
            body = b"User-agent: *\nDisallow: /\n" if any(h in url for h in self.disallow) else b"User-agent: *\nAllow: /\n"
            return Fetched(200, httpx.Headers({}), body, url)
        for prefix, (status, kind, body) in self.routes.items():
            if url.startswith(prefix):
                return Fetched(status, httpx.Headers({"content-type": kind} | (
                    {"location": body.decode()} if 300 <= status < 400 else {})), body, url)
        return Fetched(404, httpx.Headers({}), b"", url)


# --- head-middle-tail sampling --------------------------------------------------------------------------

def test_head_middle_tail_keeps_opening_middle_and_conclusion():
    text = "OPENING " + "a" * 10_000 + " MIDDLE " + "b" * 10_000 + " CONCLUSION"
    sample = select_content(text, 12_000)
    assert len(sample) <= 12_000
    assert sample.startswith(MARKERS[0] + "OPENING") and sample.rstrip().endswith("CONCLUSION")
    assert "MIDDLE" in sample and all(marker.strip() in sample for marker in MARKERS)
    opening = sample.split(MARKERS[1])[0]
    assert 0.35 < len(opening) / 12_000 < 0.45  # 40/30/30 split


def test_short_text_is_not_sampled_and_prefix_mode_truncates():
    assert select_content("  short text  ", 12_000) == "short text"
    assert select_content("x" * 20_000, 18_000, "prefix") == "x" * 18_000


# --- extraction and fallback ----------------------------------------------------------------------------

@pytest.fixture
def web(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    state = {}

    def install(routes, disallow=()):
        state["web"] = FakeWeb(routes, disallow)
        monkeypatch.setattr(Fetcher, "fetch", lambda self, url, **kw: state["web"](self, url, **kw))
        return state["web"]

    return install


def article(url="https://news.example/a", doi=None, title="CO2 to methanol plant", summary="Short snippet."):
    return SimpleNamespace(canonical_url=url, doi=doi, title=title, summary=summary)


PAGE_SOURCE = SimpleNamespace(source_type="company_announcements", content_extractor="trafilatura",
                              access_method="rss")
PAPER_SOURCE = SimpleNamespace(source_type="scholarly_metadata", content_extractor=None, access_method="openalex")


def test_trafilatura_extracts_main_text_with_honest_redirects(web):
    body = long_text("The plant converts 70,000 tonnes of CO2 per year into e-methanol.")
    fake = web({"https://news.example/a": (301, "", b"https://www.news.example/a"),
                "https://www.news.example/a": (200, "text/html", page(body))})
    result = obtain(article(), PAGE_SOURCE, PageReader(Fetcher()))
    assert result.basis == "full_text" and "70,000 tonnes" in result.text
    assert "Menu" not in result.text and "Footer" not in result.text
    assert result.origin == "https://www.news.example/a"
    # robots.txt is checked for the redirect target's host too
    assert "https://www.news.example/robots.txt" in fake.requests
    record = result.record()
    assert "text" not in record and record["chars"] == len(result.text) and len(record["sha256"]) == 64


@pytest.mark.parametrize("routes,disallow,why", [
    ({"https://news.example/a": (200, "text/html", page(long_text("x")))}, ("news.example",), "robots"),
    ({"https://news.example/a": (403, "text/html", b"")}, (), "paywall or firewall: no bypass"),
    ({"https://news.example/a": (200, "text/html", page("Too short."))}, (), "teaser only"),
    ({"https://news.example/a": (200, "image/png", b"\x89PNG")}, (), "unsupported type"),
])
def test_page_extraction_falls_back_to_headline(web, routes, disallow, why):
    fake = web(routes, disallow)
    result = obtain(article(), PAGE_SOURCE, PageReader(Fetcher()))
    assert result.basis == "headline", why
    assert result.text == "CO2 to methanol plant\nShort snippet."
    if disallow:
        assert "https://news.example/a" not in fake.requests  # never fetched against robots.txt


def test_open_access_paper_full_text_from_pdf(web):
    pdf = tiny_pdf("Copper converts CO2 to ethylene " + "with stable operation " * 450)
    web({"https://oa.example/paper.pdf": (200, "application/pdf", pdf)})
    paper = {"abstract": "A" * 400, "oa_urls": ["https://oa.example/paper.pdf"]}
    result = obtain(article(doi="10.1/x"), PAPER_SOURCE, PageReader(Fetcher()), paper)
    assert result.basis == "full_text" and result.method == "open-access copy"
    assert "Copper converts CO2" in result.text


def test_abstract_only_landing_page_is_not_labelled_full_text(web):
    # Paid run 1: a publisher page gave ~4,000 characters (abstract and front matter); that is not full text.
    web({"https://oa.example/landing": (200, "text/html", page(long_text("Abstract of the paper.", filler=20)))})
    paper = {"abstract": "We report CO2 electroreduction to ethylene. " * 10, "oa_urls": ["https://oa.example/landing"]}
    result = obtain(article(doi="10.1/landing"), PAPER_SOURCE, PageReader(Fetcher()), paper)
    assert result.basis == "abstract"


def test_paper_falls_back_to_abstract_then_title(web):
    web({"https://publisher.example/x": (403, "text/html", b"")})
    paper = {"abstract": "We report CO2 electroreduction to ethylene. " * 10,
             "oa_urls": ["https://publisher.example/x"]}
    result = obtain(article(doi="10.1/y"), PAPER_SOURCE, PageReader(Fetcher()), paper)
    assert result.basis == "abstract" and "Abstract: We report" in result.text
    titled = obtain(article(doi="10.1/z", title="Another paper"), PAPER_SOURCE, PageReader(Fetcher()), {})
    assert titled.basis == "headline"


# --- robots.txt (RFC 9309) ------------------------------------------------------------------------------

@pytest.mark.parametrize("status,allowed", [(404, True), (410, True), (503, False)])
def test_robots_unavailable_versus_unreachable(monkeypatch, status, allowed):
    monkeypatch.setattr(Fetcher, "fetch", lambda self, url, **kw: Fetched(status, httpx.Headers({}), b"", url))
    assert Fetcher().allowed("https://example.org/feed")[0] is allowed


def test_robots_crawl_delay_sets_interval(monkeypatch):
    body = b"User-agent: *\nCrawl-delay: 9\nDisallow: /private\n"
    monkeypatch.setattr(Fetcher, "fetch", lambda self, url, **kw: Fetched(200, httpx.Headers({}), body, url))
    fetcher = Fetcher()
    assert fetcher.allowed("https://example.org/news/a", 2) == (True, 9.0)
    assert fetcher.allowed("https://example.org/private/x")[0] is False


# --- keyword triage: drop only clearly unrelated items --------------------------------------------------

NEWS = SimpleNamespace(source_id="news-utilization-carbonherald", source_type="news_search", evidence_role="news")
PAPERS = SimpleNamespace(source_id="openalex", source_type="scholarly_metadata", evidence_role="primary")
DAY = date(2026, 9, 20)


def headline(title, summary=""):
    return SimpleNamespace(title=title, summary=summary, sample=False, publication_date=DAY)


@pytest.mark.parametrize("source,title", [
    (PAPERS, "CO2 footprint of nuclear power"),  # borderline: the gate decides
    (NEWS, "Carbon capture hub reaches FID"),
    (NEWS, "Uniper advances NorthStarH2 e-methanol plant"),
    (NEWS, "EU RFNBO delegated act published"),
])
def test_borderline_items_go_to_the_gate(source, title):
    result = triage(headline(title), source, DAY, DAY)
    assert result["eligible"] and result["kind"] in ("news", "academic")


COMPANY = SimpleNamespace(source_id="covestro", source_type="company_announcements_and_annual_reports",
                          evidence_role="primary")
GOV = SimpleNamespace(source_id="govuk-search-ccu", source_type="government", evidence_role="primary")

# Dropped as "no CCU term" in paid run 37929580610 and never seen by the gate.
MISSED = [
    (NEWS, "Uniper and Arcadia eFuels sign long-term agreement to accelerate aviation decarbonization"),
    (NEWS, "Uniper advances NorthStarH2 into basic engineering"),
    (NEWS, "Argus – EU may drop binding green hydrogen targets in next RED"),
    (NEWS, "Velocys expands Fischer-Tropsch reactor roadmap with AlphaCore 800 for larger-scale SAF and e-fuels"),
    (NEWS, "US SAF market faces policy uncertainty as new production technologies emerge"),
    (NEWS, "Has biofuel’s moment in shipping finally arrived?"),
]


@pytest.mark.parametrize("source,title", MISSED)
def test_previously_missed_items_reach_the_gate(source, title):
    result = triage(headline(title), source, DAY, DAY)
    assert result["eligible"], result


@pytest.mark.parametrize("title", [
    "Uniper and Arcadia eFuels sign long-term agreement to accelerate aviation decarbonization",
    "Velocys expands Fischer-Tropsch reactor roadmap with AlphaCore 800 for larger-scale SAF and e-fuels",
])
def test_e_fuel_terms_rank_as_ccu_topics(title):
    assert triage(headline(title), NEWS, DAY, DAY)["reason"] == "CCU topic"


@pytest.mark.parametrize("term", [
    "eFuels", "e-fuel", "e-fuels", "e-SAF", "eSAF", "RFNBO", "power-to-liquid", "PtL", "PtX", "Fischer-Tropsch",
    "synthetic kerosene", "e-kerosene", "e-methane", "CO2 offtake",
])
def test_e_fuel_terms_admit_academic_items(term):
    result = triage(headline(f"Process study of {term} production"), PAPERS, DAY, DAY)
    assert result["eligible"] and result["reason"] == "CCU topic"


def test_e_ammonia_is_adjacent_and_left_to_the_gate():
    result = triage(headline("Techno-economics of e-ammonia for shipping"), PAPERS, DAY, DAY)
    assert result["eligible"] and result["reason"] == "CCU term without utilization context"


@pytest.mark.parametrize("source,title", [
    (NEWS, "Shipping fuel future hinges on what regulators do next"),
    (COMPANY, "Toward circular elastomers: company opens pilot plant"),
    (GOV, "Draft strategic policy guidance for electricity networks growth"),
])
def test_news_company_and_government_items_go_to_the_gate_without_a_term(source, title):
    result = triage(headline(title), source, DAY, DAY)
    assert result["eligible"] and result["kind"] != "academic"


@pytest.mark.parametrize("source,title", [
    (PAPERS, "Perovskite solar cell efficiency record"),
    (NEWS, "Perovskite solar cell record"),
    (NEWS, "Red Mist: Forget Azerbaijan. Let talk Formula 1 V10s"),
    (NEWS, "Banks Open Today Ahead of 3-Day Strike, Certain Services Restricted"),
    (COMPANY, "Team Sonnenwagen successfully completes the challenging 2026 iLumen European Solar Challenge"),
    (GOV, "Premier League stadium safety guidance"),
])
def test_clearly_unrelated_items_dropped_by_keyword(source, title):
    assert not triage(headline(title), source, DAY, DAY)["eligible"]


def test_off_topic_words_never_drop_a_ccu_title():
    assert triage(headline("Interest rates weigh on e-methanol project financing"), NEWS, DAY, DAY)["eligible"]


# --- stage logic -----------------------------------------------------------------------------------------

SOURCE = ("Liquid Wind said it secured EUR 100 million on 21 September 2026. The plant will convert "
          "70,000 tonnes of biogenic CO2 per year into e-methanol in Örnsköldsvik, Sweden.")


def enrichment(**overrides):
    data = dict(
        headline="Liquid Wind finances Swedish e-methanol plant",
        what_changed="Liquid Wind says it secured EUR 100 million. The plant targets 70,000 tonnes of CO2 a year.",
        why_it_matters="Financing moves a commercial e-methanol route toward construction.",
        practical_implication="Offtakers can expect 90,000 tonnes from 2027. Track construction.",
        next_action="Request the offtake terms.",
        fields={"scale": {"value": "70,000 t/yr biogenic CO2 input (design)",
                          "quote": "70,000 tonnes of biogenic CO2 per year"},
                "partners": {"value": "Ørsted", "quote": "Ørsted is a partner"},
                "location": {"value": "Örnsköldsvik, Sweden", "quote": "in Örnsköldsvik, Sweden"},
                "trl": {"value": "Not stated in the supplied material.", "quote": None}},
        economic_information=[{"text": "EUR 100 million secured.", "quote": "secured EUR 100 million",
                               "uncertainty": "Company statement."}],
        milestone_proposals=[{"text": "Financing secured.", "quote": "secured EUR 100 million on 21 September 2026",
                              "uncertainty": "Company statement.", "event_type": "FINANCING_SECURED",
                              "event_date": "2026-09-22"}],
        quotes=["The plant will convert 70,000 tonnes", "invented quote not in source"],
        uncertainty="Construction start not stated.",
    )
    return Enrichment.model_validate(data | overrides)


def test_grounding_removes_non_verbatim_fields_quotes_and_unwritten_dates():
    result, removed = ground_enrichment(enrichment(), SOURCE)
    assert result.fields.partners.value == NOT_STATED and result.fields.partners.quote is None
    assert result.fields.scale.value.startswith("70,000") and result.fields.trl.value == NOT_STATED
    assert result.quotes == ["The plant will convert 70,000 tonnes"]
    assert result.milestone_proposals[0].event_date is None  # 22 September is not written in the source
    assert {r["item"] for r in removed} >= {"field:partners", "quote", "milestone_proposals:0"}


def test_verification_removes_unsupported_claims_and_rejects_corrections_with_new_numbers():
    grounded, _ = ground_enrichment(enrichment(), SOURCE)
    checks = VerificationResult.model_validate({"checks": [
        {"id": "field:location", "verdict": "unsupported", "problem": "not in source"},
        {"id": "block:why_it_matters", "verdict": "partially_supported", "problem": "overstated",
         "corrected_text": "Financing supports a planned e-methanol plant."},
        {"id": "block:next_action", "verdict": "partially_supported", "problem": "adds a number",
         "corrected_text": "Request terms for the 50,000 t offtake."},
        {"id": "headline", "verdict": "supported"},
    ]})
    allowed = numbers(SOURCE) | numbers("2026-09-20")
    result, log = apply_verification(grounded, checks, SOURCE, allowed, "Original title")
    assert result.fields.location.value == NOT_STATED
    assert result.why_it_matters == "Financing supports a planned e-methanol plant."
    assert result.next_action is None  # its correction introduced 50,000, which is not in the source
    # The deterministic number check removes the sentence with 90,000 / 2027 even though no check flagged it.
    assert result.practical_implication == "Track construction."
    assert any("90,000" in r["sentence"] for r in log["number_removed"])
    assert {r["item"] for r in log["removed"]} == {"field:location", "block:next_action"}
    assert "block:what_changed" in log["unchecked"]


def test_unsupported_core_claim_drops_the_item():
    grounded, _ = ground_enrichment(enrichment(), SOURCE)
    checks = VerificationResult.model_validate(
        {"checks": [{"id": "block:what_changed", "verdict": "unsupported", "problem": "fabricated"}]})
    result, log = apply_verification(grounded, checks, SOURCE, numbers(SOURCE), "Original title")
    assert result is None and "dropped_item" in log


def test_number_normalization_and_sentence_filter():
    assert numbers("70 000 t, 70,000 t, 1,5 %, CO2, H2O, C2+ and 45Q") == {"70000", "1.5", "45"}
    text, removed = keep_supported_numbers("Output is 5 t/d. Cost is USD 900/t.", {"5"})
    assert text == "Output is 5 t/d." and removed == ["Cost is USD 900/t."]


def entry(article_id, score, category, role="primary", basis="full_text"):
    return {"article_id": article_id, "sid": article_id.upper(), "score": score, "category": category,
            "evidence_role": role, "input_basis": basis}


def test_dedup_keeps_primary_source_over_news_report():
    items = [entry("a", 8, "commercialization", "news"), entry("b", 7, "commercialization")]
    merged = dedup_groups(DedupResult(groups=[["A", "B"], ["B", "X"]]), items)
    assert merged == {"a": "b"}
    assert dedup_groups(None, items) == {} and dedup_groups(DedupResult(groups=[["A"]]), items) == {}


def test_selection_caps_and_never_fills_with_weak_items():
    config = {"threshold": 5, "per_category_cap": 2, "overall_cap": 3, "max_takeaways": 5}
    items = [entry("a", 9, "conversion"), entry("b", 8, "conversion"), entry("c", 7, "conversion"),
             entry("d", 6, "products"), entry("e", 5.5, "economics_climate_policy"), entry("f", 4.9, "products")]
    chosen, decisions = select(items, config)
    assert [c["article_id"] for c in chosen] == ["a", "b", "d"]
    assert decisions == {"a": "selected", "b": "selected", "c": "category cap", "d": "selected",
                         "e": "overall cap", "f": "below threshold"}
    leads = takeaways(chosen, config)
    assert [e["article_id"] for e in leads] == ["a", "d"]  # distinct categories only
    assert takeaways([entry("x", 4, "products")], config) == []


def test_news_ties_rank_below_primary_and_full_text_above_headline():
    config = {"threshold": 5, "per_category_cap": 1, "overall_cap": 5}
    chosen, _ = select([entry("n", 7, "products", "news"), entry("p", 7, "products", basis="headline")], config)
    assert chosen[0]["article_id"] == "p"


def test_category_caps_override_default_and_target_relaxes_caps_not_threshold():
    config = {"threshold": 5, "per_category_cap": 2, "category_caps": {"conversion": 3}, "overall_cap": 15}
    items = [entry(f"c{i}", 6, "conversion") for i in range(6)] + [entry("p1", 7, "products"),
                                                                   entry("p2", 6, "products"),
                                                                   entry("p3", 6, "products"),
                                                                   entry("w", 4.9, "products")]
    chosen, decisions = select(items, config)
    assert sum(c["category"] == "conversion" for c in chosen) == 3 and len(chosen) == 5
    chosen, decisions = select(items, config | {"target_min_items": 8})
    assert len(chosen) == 8 and decisions["w"] == "below threshold"
    assert list(decisions.values()).count("selected (cap relaxed to reach target)") == 3
    # Never more than the qualifying items, never above the overall cap.
    assert len(select(items, config | {"target_min_items": 20})[0]) == 9
    assert len(select(items, config | {"target_min_items": 20, "overall_cap": 4})[0]) == 4


def test_newsletter_targets_ten_to_fifteen_items_with_eight_conversion_papers():
    config = newsletter_config()
    assert config["target_min_items"] == 10 and config["overall_cap"] == 15
    assert config["category_caps"]["conversion"] == 8 and 3 <= config["min_takeaways"] <= config["max_takeaways"] == 5
    papers = [entry(f"c{i}", 6 if i < 4 else 5, "conversion") for i in range(11)]
    projects = [entry("p1", 7, "commercialization", "news"), entry("p2", 6, "commercialization", "news")]
    chosen, decisions = select(papers + projects, config)
    assert len(chosen) == 10 and decisions["c8"] == "category cap"  # 8 papers + 2 projects


def test_story_counts_once_against_caps_and_members_follow_the_lead():
    config = {"threshold": 5, "per_category_cap": 1, "overall_cap": 2}
    items = [entry("feed", 7, "commercialization", "news"), entry("basic", 6, "commercialization", "news"),
             entry("offtake", 7, "products", "news"), entry("other", 6, "commercialization")]
    story = {"feed": "feed", "basic": "feed", "offtake": "feed"}
    chosen, decisions = select(items, config, story)
    assert {c["article_id"] for c in chosen} == {"feed", "basic", "offtake"}
    assert decisions["basic"] == decisions["offtake"] == "selected (same story)"
    assert decisions["other"] == "category cap"  # the story used the commercialization slot


def test_takeaways_aim_for_three_to_five_one_per_story():
    config = {"threshold": 5, "min_takeaways": 3, "max_takeaways": 5, "takeaway_extra_score": 7}
    two_categories = [entry("a", 8, "commercialization"), entry("b", 6, "conversion"), entry("c", 6, "conversion"),
                      entry("d", 5, "conversion")]
    assert [e["article_id"] for e in takeaways(two_categories, config)] == ["a", "b", "c"]
    strong = [entry(x, 8, "conversion") for x in "abcdefg"]
    assert len(takeaways(strong, config)) == 5
    story = [entry("a", 8, "commercialization") | {"story": "a"}, entry("b", 7, "commercialization") | {"story": "a"},
             entry("c", 6, "conversion")]
    assert [e["article_id"] for e in takeaways(story, config)] == ["a", "c"]  # only two stories qualify
    assert takeaways([entry("x", 4, "products")], config) == []


def press(article_id, host, basis="full_text", role="news", score=6):
    return entry(article_id, score, "commercialization", role, basis) | {"url": f"https://www.{host}/story"}


def test_dedup_prefers_the_more_credible_outlet():
    config = newsletter_config()
    items = [press("regional", "sentinelassam.com", score=6), press("business", "business-standard.com", score=5),
             press("trade", "hydrogen-central.com", score=6)]
    merged = dedup_groups(DedupResult(groups=[["REGIONAL", "TRADE", "BUSINESS"]]), items, config)
    assert merged == {"regional": "business", "trade": "business"}
    company = press("company", "uniper.energy", role="primary", score=5)
    merged = dedup_groups(DedupResult(groups=[["BUSINESS", "COMPANY"]]), [items[1], company], config)
    assert merged == {"business": "company"}


def test_dedup_falls_back_when_the_credible_outlets_full_text_is_unavailable():
    config = newsletter_config()
    items = [press("business", "business-standard.com", basis="headline"), press("regional", "sentinelassam.com")]
    assert dedup_groups(DedupResult(groups=[["BUSINESS", "REGIONAL"]]), items, config) == {"business": "regional"}


def test_story_groups_resolve_duplicates_and_ignore_singletons():
    items = [entry("feed", 6, "commercialization"), entry("basic", 7, "commercialization"),
             entry("dup", 6, "commercialization"), entry("offtake", 6, "products")]
    result = DedupResult(groups=[["BASIC", "DUP"]], stories=[["FEED", "DUP", "OFFTAKE"], ["X", "FEED"]])
    merged = dedup_groups(result, items)
    story = story_groups(result, items, merged)
    assert story == {"feed": "basic", "basic": "basic", "offtake": "basic"}
    assert story_groups(None, items, {}) == {}


def test_story_items_merge_and_request_advice_moves_to_editor_notes():
    synthesis = {"sections": [{"category": "commercialization", "intro": None, "items": [
        {"source_ids": ["S1"], "headline": "FEED award", "limitation": None,
         "paragraphs": [{"text": "AFRY won FEED. Request the FEED basis from Uniper.", "source_ids": ["S1"]}]},
        {"source_ids": ["S3"], "headline": "Unrelated", "limitation": None,
         "paragraphs": [{"text": "Something else.", "source_ids": ["S3"]}]},
        {"source_ids": ["S2"], "headline": "Basic engineering", "limitation": "Trade-press report.",
         "paragraphs": [{"text": "Uniper moved to basic engineering.", "source_ids": ["S2"]}]}]}]}
    merge_stories(synthesis, {"S1": "a", "S2": "a"})
    items = synthesis["sections"][0]["items"]
    assert [i["source_ids"] for i in items] == [["S1", "S2"], ["S3"]]
    assert items[0]["limitation"] == "Trade-press report." and len(items[0]["paragraphs"]) == 2
    notes = move_requests(synthesis)
    assert notes == ["FEED award: Request the FEED basis from Uniper."]
    assert items[0]["paragraphs"][0]["text"] == "AFRY won FEED."


def test_limitation_is_one_short_line():
    assert short_line("Abstract only; potential and durability not reported. Request the full text.") == \
        "Abstract only; potential and durability not reported."
    long = ("Abstract only; potential, current density, electrolyte, cell area, flow rate, temperature, pressure "
            "and durability are not reported in the supplied material; independent replication is not available.")
    assert len(short_line(long).split()) <= 20 and short_line(None) is None


# --- limits, pricing and budget -------------------------------------------------------------------------

def entrypoint():
    spec = importlib.util.spec_from_file_location("research_entry", ROOT / "scripts/deepseek-research.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_run_limits(monkeypatch):
    for name in ("MAX_ANALYSES", "MAX_SPEND_USD", "TOKEN_BUDGET", "LLM_MODEL", "LLM_SCREENING_MODEL"):
        monkeypatch.delenv(name, raising=False)
    options = entrypoint().configuration()
    assert options.max_analyses == 60 and options.max_spend_usd == 5.0 and options.token_budget == 2_000_000
    assert options.dry_run


def test_default_coverage_is_the_most_recent_fourteen_complete_days(monkeypatch):
    for name in ("COVERAGE_END", "COVERAGE_DAYS", "MAX_ANALYSES", "MAX_SPEND_USD", "TOKEN_BUDGET", "LLM_MODEL",
                 "LLM_SCREENING_MODEL"):
        monkeypatch.delenv(name, raising=False)
    module = entrypoint()
    assert module.coverage(date(2026, 10, 9)) == (date(2026, 9, 25), date(2026, 10, 8))
    monkeypatch.setenv("COVERAGE_END", "2026-09-27")
    assert module.coverage(date(2026, 10, 9)) == (date(2026, 9, 14), date(2026, 9, 27))
    monkeypatch.setenv("COVERAGE_END", "")
    monkeypatch.setenv("COVERAGE_DAYS", "11")
    assert module.coverage(date(2026, 10, 9)) == (date(2026, 9, 28), date(2026, 10, 8))
    options = module.configuration()
    assert (options.until - options.since).days == 10 and options.output.name == str(options.until + timedelta(1))


@pytest.mark.parametrize("name,value", [("COVERAGE_END", "2999-01-01"), ("COVERAGE_END", "yesterday"),
                                        ("COVERAGE_DAYS", "0"), ("COVERAGE_DAYS", "32")])
def test_invalid_coverage_rejected(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        entrypoint().configuration()


@pytest.mark.parametrize("name,value", [
    ("MAX_ANALYSES", "61"), ("MAX_ANALYSES", "-1"), ("MAX_SPEND_USD", "5.01"), ("MAX_SPEND_USD", "nan"),
    ("MAX_SPEND_USD", "inf"), ("TOKEN_BUDGET", "5000001"), ("TOKEN_BUDGET", "0"),
    ("LLM_MODEL", "deepseek-unpriced"), ("LLM_SCREENING_MODEL", "gpt-x"),
])
def test_dispatch_inputs_cannot_exceed_hard_caps_or_use_unpriced_models(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        entrypoint().configuration()


def test_roles_use_strongest_model_for_quality_stages(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_SCREENING_MODEL", raising=False)
    stage = pricing.roles()
    assert stage["screening"].model == "deepseek-flash" and not stage["screening"].thinking
    assert {stage[s].model for s in ("enrichment", "verification", "dedup", "synthesis")} == {"deepseek-v4-pro"}
    assert stage["enrichment"].rates == pricing.Rates(1.32, 3.96)


def test_rate_ceiling_below_official_price_rejected(tmp_path):
    config = yaml.safe_load((ROOT / "config/models.yaml").read_text())
    config["rate_ceilings"]["deepseek-v4-pro"]["output"] = 1.0
    path = tmp_path / "models.yaml"
    path.write_text(yaml.safe_dump(config))
    with pytest.raises(ValueError, match="official peak"):
        pricing.load(path)


def test_peak_and_off_peak_cost_estimates():
    usage = {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000, "prompt_cache_hit_tokens": 0}
    from datetime import UTC, datetime
    peak = pricing.call_cost("deepseek-v4-pro", usage, datetime(2026, 10, 8, 7, tzinfo=UTC))
    weekend = pricing.call_cost("deepseek-v4-pro", usage, datetime(2026, 10, 10, 7, tzinfo=UTC))
    assert peak == {"upper_bound_usd": 5.28, "estimate_usd": 5.28}
    assert weekend["estimate_usd"] == 2.64 and weekend["upper_bound_usd"] == 5.28


def test_priced_reservation_settles_to_reported_usage_and_survives_restart(tmp_path):
    path = tmp_path / "budget.json"
    budget = Budget(max_requests=5, max_tokens=100_000, max_spend_usd=0.10, path=path)
    reserved = budget.reserve_priced(20_000, 10_000, 1.32, 3.96)  # 0.0264 + 0.0396 USD
    assert reserved == 66_000 and budget.reserved_cost_microusd == 66_000
    budget.settle_priced(30_000, reserved, {"prompt_tokens": 1000, "completion_tokens": 500}, 1.32, 3.96)
    assert budget.charged_tokens == 1500 and budget.reserved_cost_microusd == 3300
    budget = Budget(**json.loads(path.read_text()), path=path)
    assert budget.reserved_cost_microusd == 3300
    # Missing or implausible usage keeps the whole reservation.
    reserved = budget.reserve_priced(20_000, 10_000, 1.32, 3.96)
    for usage in (None, {}, {"prompt_tokens": -1, "completion_tokens": 5}, {"prompt_tokens": 10**9,
                                                                            "completion_tokens": 0}):
        budget.settle_priced(30_000, reserved, usage, 1.32, 3.96)
    assert budget.reserved_cost_microusd == 3300 + 66_000
    assert not budget.reserve_priced(20_000, 10_000, 1.32, 3.96)  # would exceed USD 0.10


# --- JSON calls: thinking fallback, repair, budget ------------------------------------------------------

def role(stage="verification", thinking=True, max_tokens=4000):
    return pricing.Role(stage, "deepseek-v4-pro", thinking, max_tokens, pricing.Rates(1.32, 3.96))


def chat(content, usage=None, finish="stop"):
    return httpx.Response(200, json={"choices": [{"finish_reason": finish, "message": {
        "content": content, "reasoning_content": "private chain of thought"}}],
        "usage": usage or {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}})


def test_thinking_rejected_falls_back_and_schema_errors_get_one_repair(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "fixture-secret-never-real")
    monkeypatch.setattr("ccu_intelligence.llm.time.sleep", lambda _: None)
    bodies = []
    replies = [httpx.Response(400, json={"error": "thinking unsupported with json mode"}),
               chat('{"groups": "not a list"}'), chat('```json\n{"groups": [["S1", "S2"]]}\n```')]

    def handler(request):
        bodies.append(json.loads(request.content))
        return replies.pop(0)

    calls, budget = [], Budget(max_requests=10, max_tokens=100_000, max_spend_usd=1)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = complete_json(role(), "json system", {"items": []}, DedupResult, budget=budget, calls=calls,
                               client=client)
    assert result.groups == [["S1", "S2"]]
    assert bodies[0]["thinking"] == {"type": "enabled"} and "temperature" not in bodies[0]
    assert bodies[1]["thinking"] == {"type": "disabled"} and bodies[1]["temperature"] == 0
    assert [c["status"] for c in calls] == ["thinking_rejected", "schema_error", "validated"]
    assert "private chain of thought" not in json.dumps(calls)
    assert budget.requests == 3 and budget.reserved_cost_microusd < 1_000_000


def test_truncated_output_is_not_regenerated_and_budget_refusal_makes_no_request(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "fixture-secret-never-real")
    requests = []

    def handler(request):
        requests.append(request)
        return chat("{", finish="length")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        calls = []
        assert complete_json(role(), "s", {}, DedupResult, budget=Budget(max_requests=5, max_tokens=10**6),
                             calls=calls, client=client) is None
        assert len(requests) == 1 and calls[0]["status"] == "incomplete_output"
        calls = []
        tiny = Budget(max_requests=5, max_tokens=10**6, max_spend_usd=0.001)
        assert complete_json(role(), "s", {}, DedupResult, budget=tiny, calls=calls, client=client) is None
        assert len(requests) == 1 and calls == [{"stage": "verification", "status": "budget_exhausted"}]


# --- end to end with mocked sources and model ------------------------------------------------------------

LW = long_text("Liquid Wind said it secured EUR 100 million on 21 September 2026 for its e-methanol plant. "
               "The plant will convert 70,000 tonnes of biogenic CO2 per year into e-methanol in "
               "Örnsköldsvik, Sweden.")
PAPER = long_text("We report CO2 electroreduction to ethylene on copper with a Faradaic efficiency of 62% "
                  "at 300 mA/cm2 for 500 hours.", filler=60)
SOURCES = [
    {"source_id": "liquid-wind", "organization": "Liquid Wind", "endpoint": "https://www.liquidwind.com/news/rss.xml"},
    {"source_id": "news-utilization-carbonherald", "organization": "Carbon Herald (site search: utilization)",
     "source_type": "news_search", "evidence_role": "news",
     "endpoint": "https://carbonherald.com/?s=utilization&feed=rss2&orderby=date&order=DESC", "pages": 1},
    {"source_id": "openalex-oa", "organization": "OpenAlex (open-access subset)", "source_type": "scholarly_metadata",
     "access_method": "openalex", "endpoint": "https://api.openalex.org/works", "query": '("CO2 reduction")',
     "filters": "open_access.is_oa:true", "content_extractor": None},
]


def rss(*items):
    body = "".join(f"<item><title>{t}</title><link>{u}</link><pubDate>{d}</pubDate><description>{s}</description></item>"
                   for t, u, d, s in items)
    return f"<rss><channel>{body}</channel></rss>".encode()


def routes():
    day = "Mon, 21 Sep 2026 09:00:00 GMT"
    return {
        "https://www.liquidwind.com/news/rss.xml": (200, "application/rss+xml", rss(
            ("Liquid Wind secures financing for e-methanol plant", "https://www.liquidwind.com/news/financing", day,
             "Financing for the CO2-to-methanol project."),
            ("Liquid Wind hires communications lead", "https://www.liquidwind.com/news/hire", day, "Staff news."))),
        "https://carbonherald.com/?s=utilization": (200, "application/rss+xml", rss(
            ("Liquid Wind closes e-methanol financing", "https://carbonherald.com/lw", day, "CO2 utilization deal."),
            ("Carbon credit prices rise on CO2 market", "https://carbonherald.com/credits", day, "Carbon credits."),
            ("CO2 mineralization startup raises funds", "https://blocked.example/minerals", day, "Concrete CO2."),
            ("Perovskite solar cell record", "https://carbonherald.com/pv", day, "Solar."))),
        "https://api.openalex.org/works": (200, "application/json", json.dumps({"results": [{
            "id": "https://openalex.org/W1", "display_name": "CO2 electroreduction to ethylene on copper",
            "doi": "https://doi.org/10.1/cu", "publication_date": "2026-09-22",
            "abstract_inverted_index": {"We": [0], "report": [1], "ethylene": [2]},
            "best_oa_location": {"is_oa": True, "landing_page_url": "https://oa.example/cu"}, "locations": [],
            "open_access": {"oa_status": "gold"}}]}).encode()),
        "https://oa.example/cu": (200, "text/html", page(PAPER)),
        "https://www.liquidwind.com/news/financing": (200, "text/html", page(LW)),
        "https://carbonherald.com/lw": (200, "text/html", page(long_text(
            "Liquid Wind closed EUR 100 million in financing, Carbon Herald reports."))),
        "https://carbonherald.com/credits": (200, "text/html", page(long_text("Carbon credit prices rose."))),
    }


SCREEN = {
    "Liquid Wind secures": dict(ccu_relevant=True, score=8.5, category="commercialization"),
    "Liquid Wind closes": dict(ccu_relevant=True, score=8, category="commercialization"),
    "CO2 electroreduction": dict(ccu_relevant=True, score=6, category="conversion"),
    "Carbon credit": dict(ccu_relevant=False, score=4, category="economics_climate_policy"),
    "CO2 mineralization": dict(ccu_relevant=True, score=9, category="products"),
}


def STORIES(ids):  # noqa: N802 - patched per test
    return []


def llm_handler(log):
    def handler(request):
        body = json.loads(request.content)
        system, payload = body["messages"][0]["content"], json.loads(body["messages"][1]["content"])
        if "# Relevance gate" in system:
            stage = "screening"
            spec = next(v for k, v in SCREEN.items() if payload["title"].startswith(k))
            content = Screening(relevance_reason="Mock gate.", reason="Mock rubric.", tags=["e-methanol", "Sweden",
                                "financing"], summary="Mock summary.", evidence_type="company_announcement",
                                **spec).model_dump()
        elif "You deduplicate and group items" in system:
            stage = "dedup"
            ids = {i["title"][:18]: i["id"] for i in payload["items"]}
            content = {"groups": [[ids["Liquid Wind closes"], ids["Liquid Wind secure"]]],
                       "stories": STORIES(ids)}
        elif "# Fact sheet" in system:
            stage = "enrichment"
            if payload["title"].startswith("Liquid Wind"):
                content = enrichment().model_dump(mode="json")
            elif payload["input_basis"] == "headline":
                content = Enrichment(headline="CO2 mineralization startup raises funds",
                                     what_changed="Only the headline was available: a CO2 mineralization startup "
                                                  "raised funds.", uncertainty="Headline only.").model_dump(mode="json")
            else:
                content = enrichment(
                    headline="Copper catalyst reaches 500 hours in CO2 electroreduction",
                    what_changed="The authors report 62% Faradaic efficiency to ethylene at 300 mA/cm2 for 500 hours.",
                    why_it_matters="Durability is the main barrier for CO2 electrolysis.",
                    practical_implication=None, next_action=None,
                    fields={"catalyst": {"value": "copper", "quote": "electroreduction to ethylene on copper"}},
                    economic_information=[], milestone_proposals=[], quotes=[]).model_dump(mode="json")
        elif "independent fact-checker" in system:
            stage = "verification"
            ids = [i["id"] for i in payload["items_to_check"]]
            checks = [{"id": i, "verdict": "supported"} for i in ids]
            if "field:location" in ids:
                checks = [c if c["id"] != "field:location" else
                          {"id": "field:location", "verdict": "unsupported", "problem": "not in source"} for c in checks]
            content = {"checks": checks}
        elif "editor-in-chief" in system:
            stage = "synthesis"
            ids = [i["source_id"] for i in payload["items"]]
            content = {
                "title": "Financing and durability lead the fortnight",
                "dek": {"text": "A financing round and a durability result stand out.", "source_ids": ids},
                "takeaways": [{"text": f"Takeaway for {t['category']}.", "source_ids": t["source_ids"]}
                              for t in payload["takeaway_plan"]],
                "sections": [{"category": s["category"], "intro": None, "items": [{
                    "source_ids": [i["source_id"]], "headline": i["brief"]["headline"],
                    "paragraphs": [{"text": i["brief"]["what_changed"] + " Revenue could reach USD 999 million.",
                                    "source_ids": [i["source_id"]]},
                                   {"text": "This cites an unknown item.", "source_ids": ["S99"]}]}
                    for i in payload["items"] if i["category"] == s["category"]]} for s in payload["section_order"]],
                "watch_next": [], "editor_notes": ["Confirm the financing terms."],
            }
        log.append(stage)
        return chat(json.dumps(content), {"prompt_tokens": 1000, "completion_tokens": 200, "total_tokens": 1200,
                                          "prompt_cache_hit_tokens": 0})
    return handler


@pytest.fixture
def research(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    shutil.copytree(ROOT / "config", "config")
    base = yaml.safe_load((ROOT / "config/sources.yaml").read_text())["sources"]
    defaults = {s["source_id"]: s for s in base}
    sources = [defaults[s["source_id"]] | s for s in SOURCES]
    Path("config/sources.yaml").write_text(yaml.safe_dump({"sources": sources}))
    monkeypatch.setattr("ccu_intelligence.workflow.load_environment", lambda: None)
    monkeypatch.setattr("ccu_intelligence.collect.time.sleep", lambda _: None)
    monkeypatch.setattr("ccu_intelligence.llm.time.sleep", lambda _: None)
    for name in ("GITHUB_ACTIONS", "LLM_MODEL", "LLM_SCREENING_MODEL", "CCU_CONTACT_EMAIL", "OPENALEX_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_API_KEY", "fixture-secret-never-real")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.deepseek.com")
    web = FakeWeb(routes(), disallow=("blocked.example",))
    monkeypatch.setattr(Fetcher, "fetch", lambda self, url, **kw: web(self, url, **kw))
    stages = []
    client = httpx.Client(transport=httpx.MockTransport(llm_handler(stages)))
    real = complete_json
    monkeypatch.setattr("ccu_intelligence.stages.complete_json", lambda *a, **kw: real(*a, **(kw | {"client": client})))
    monkeypatch.setattr("ccu_intelligence.workflow.account_balance", lambda endpoint: None)
    args = argparse.Namespace(since=date(2026, 9, 14), until=date(2026, 9, 27), scheduled_publication=None,
                              output=Path("data/runtime/test-run"), max_analyses=60, max_requests=200,
                              token_budget=2_000_000, max_spend_usd=5.0, allow_paid=True, dry_run=False)
    yield args, stages, web
    client.close()


def records(report):
    return {r["title"]: r for r in report["records"]}


def test_end_to_end_full_text_two_stage_verification_and_synthesis(research, capsys):
    args, stages, web = research
    report = execute(args)
    summary, by_title = report["summary"], records(report)
    # Keyword pre-filter dropped only the clearly unrelated items; the gate saw every borderline item.
    assert by_title["Perovskite solar cell record"]["triage"]["eligible"] is False
    assert by_title["Liquid Wind hires communications lead"]["triage"]["eligible"] is False
    assert stages.count("screening") == 5 and summary["screened"] == 5
    # input_basis per article
    assert by_title["Liquid Wind secures financing for e-methanol plant"]["input"]["basis"] == "full_text"
    assert by_title["CO2 electroreduction to ethylene on copper"]["input"]["basis"] == "full_text"
    minerals = by_title["CO2 mineralization startup raises funds"]
    assert minerals["input"]["basis"] == "headline" and "https://blocked.example/minerals" not in web.requests
    # Gate and headline cap: irrelevant scores 0; a headline-only 9 becomes 6.
    assert by_title["Carbon credit prices rise on CO2 market"]["screening"]["score"] == 0
    assert minerals["screening"]["score"] == 6 and minerals["screening"]["model_score"] == 9
    # Dedup merged the news report into the primary company source.
    news = by_title["Liquid Wind closes e-methanol financing"]
    assert news["selection"].startswith("duplicate of")
    # Enrichment and verification ran on selected items only, with the strong model.
    assert stages.count("enrichment") == stages.count("verification") == 3
    lw = by_title["Liquid Wind secures financing for e-methanol plant"]
    assert lw["enrichment_status"] == "verified"
    assert "partners" in lw["fields"]["not_stated"] and "scale" in lw["fields"]["filled"]
    assert {r["item"] for r in lw["verification"]["removed"]} == {"field:location"}
    assert lw["enrichment"]["fields"]["location"]["value"] == NOT_STATED
    assert any("90,000" in r["sentence"] for r in lw["verification"]["number_removed"])
    models = {c["stage"]: c["model"] for c in report["calls"] if c.get("model")}
    assert models["screening"] == "deepseek-flash" and models["synthesis"] == "deepseek-v4-pro"
    # Draft: takeaways, category sections, table, briefs, links; validated synthesis.
    meta, body = read_issue(Path(summary["draft"]))
    assert meta["editorial_status"] == "draft" and meta["reviewer"] is None
    for heading in ("## Key takeaways", "## Projects, finance & deployment", "## Conversion technology",
                    "## Technology and economics at a glance", "## CCU ecosystem briefs", "## Sources"):
        assert heading in body
    assert "https://www.liquidwind.com/news/financing" in body and "https://oa.example" not in body
    assert "Also reported: [Liquid Wind closes e-methanol financing](https://carbonherald.com/lw)" in body
    assert "999" not in body and "unknown item" not in body and "S99" not in body
    assert "headline only" in body  # the headline-only item is labelled wherever cited
    assert "[Carbon Herald, 2026-09-21](https://blocked.example/minerals)" in body  # clean outlet label
    assert "site search" not in body and "open-access subset" not in body
    dek = next(line for line in body.splitlines() if line.startswith("*A financing round"))
    assert "](" not in dek  # the executive summary is plain prose; citations stay in the item sections
    assert "*Headline only; content not reviewed.*" in body  # default one-line limitation
    assert {i["issue"] for i in report["synthesis_issues"]} >= {"unsupported number", "uncited text removed"}
    # Publisher text never leaves the private cache: not in the draft, report, bundle or stage cache.
    for path in [*args.output.rglob("*"), *Path("data/runtime/llm-cache").rglob("*")]:
        if path.is_file() and path.suffix in (".md", ".json"):
            assert SENTINEL not in path.read_text(), path
    assert any(SENTINEL in p.read_text() for p in Path("data/runtime/fulltext-cache").glob("*.json"))
    assert "fixture-secret" not in capsys.readouterr().out
    assert summary["cost_upper_bound_usd"] > 0 and summary["reserved_cost_usd"] <= 5


def test_story_members_render_as_one_item_citing_every_source(research, monkeypatch):
    args, stages, _ = research
    monkeypatch.setitem(globals(), "STORIES", lambda ids: [[ids["Liquid Wind secure"], ids["CO2 mineralization"]]])
    report = execute(args)
    by_title = records(report)
    lead = by_title["Liquid Wind secures financing for e-methanol plant"]["article_id"]
    assert by_title["CO2 mineralization startup raises funds"]["story"] == lead
    body = Path(report["summary"]["draft"]).read_text()
    section = body.split("## Projects, finance & deployment")[1].split("\n## ")[0]
    assert "https://blocked.example/minerals" in section and "## Products & markets" not in body
    assert section.count("### ") == 1  # one story item citing both sources


def test_cache_makes_reruns_free_and_prompt_change_invalidates(research, monkeypatch):
    args, stages, _ = research
    execute(args)
    first = len(stages)
    args.output = Path("data/runtime/second-run")
    report = execute(args)
    assert len(stages) == first and report["summary"]["requests_reserved"] == 0
    assert report["summary"]["cache_hits"] == first
    monkeypatch.setattr("ccu_intelligence.stages.PROMPT_VERSION", "ccu-profile-next")
    args.output = Path("data/runtime/third-run")
    execute(args)
    assert len(stages) == 2 * first


def test_max_analyses_caps_new_screening_calls(research):
    args, stages, _ = research
    args.max_analyses = 2
    report = execute(args)
    assert stages.count("screening") == 2 and report["summary"]["new_analyses_attempted"] == 2
    assert sum(r.get("screening_status") == "not analysed: cap" for r in report["records"]) == 3


@pytest.mark.parametrize("mode", ["explicit", "default", "zero-spend"])
def test_zero_paid_requests(research, mode):
    args, stages, _ = research
    if mode == "explicit":
        args.dry_run = True
    elif mode == "default":
        del args.allow_paid
    else:
        args.max_spend_usd = 0
    report = execute(args)
    assert report["summary"]["requests_reserved"] == 0
    assert stages == []
    if mode == "explicit":
        projected = report["summary"]["paid_run_projection"]
        assert projected["uncached_screenings"] == 5
        assert 0 < projected["low"]["expected_usd"] <= projected["high"]["expected_usd"]
        assert projected["high"]["expected_usd"] <= projected["high"]["worst_case_usd"]
    body = Path(report["summary"]["draft"]).read_text()
    assert "No model analysis in this run" in body and "at a glance" not in body


def test_spend_cap_stops_requests_before_exceeding_it(research):
    args, stages, _ = research
    args.max_spend_usd = 0.02  # enough for a few screening calls, not for the strong-model stages
    report = execute(args)
    assert report["summary"]["reserved_cost_usd"] <= 0.02
    assert "synthesis" not in stages and stages.count("screening") >= 1


@pytest.mark.parametrize("field,value", [("max_analyses", 61), ("max_spend_usd", 5.5), ("token_budget", 0),
                                         ("max_requests", 301)])
def test_invalid_caps_fail_before_collection(research, field, value):
    args, stages, web = research
    setattr(args, field, value)
    with pytest.raises(ValueError):
        execute(args)
    assert not args.output.exists() and stages == [] and web.requests == []


@pytest.mark.parametrize("event,ref,attempt", [
    ("pull_request", "refs/heads/main", "1"), ("workflow_dispatch", "refs/heads/feature", "1"),
    ("workflow_dispatch", "refs/heads/main", "2"), ("schedule", "refs/heads/main", "1"),
])
def test_untrusted_or_retry_run_rejected_before_payment(research, monkeypatch, event, ref, attempt):
    args, stages, _ = research
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_EVENT_NAME", event)
    monkeypatch.setenv("GITHUB_REF", ref)
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", attempt)
    with pytest.raises(ValueError, match="trusted"):
        execute(args)
    assert stages == []


def test_newsletter_categories_come_from_taxonomy():
    config = newsletter_config()
    taxonomy = yaml.safe_load((ROOT / "config/taxonomy.yaml").read_text())
    assert set(config["categories"]) <= set(taxonomy)
    assert config["threshold"] == 5 and config["max_takeaways"] == 5


def test_source_text_record_never_contains_text():
    record = SourceText("full_text", SENTINEL, "https://x.example", "trafilatura").record()
    assert SENTINEL not in json.dumps(record)


def test_failing_source_never_aborts_the_run(research, monkeypatch):
    args, stages, web = research
    original = web.routes.copy()
    web.routes = {k: v for k, v in original.items() if not k.startswith("https://www.liquidwind.com/news/rss")}
    web.routes["https://www.liquidwind.com/news/rss.xml"] = (503, "text/html", b"")
    report = execute(args)
    collection = json.loads((args.output / "collection.json").read_text())
    assert collection["liquid-wind"]["failed"] == 1 and collection["openalex-oa"]["added"] == 1
    assert report["summary"]["verified_in_draft"] >= 1


def test_wordpress_feed_pages_stop_once_before_the_window(monkeypatch, tmp_path):
    from ccu_intelligence.collect import collect
    from ccu_intelligence.store import Store

    monkeypatch.chdir(tmp_path)
    shutil.copytree(ROOT / "config", "config")
    source = yaml.safe_load((ROOT / "config/sources.yaml").read_text())["sources"]
    news = next(s for s in source if s["source_id"] == "news-utilization-carbonherald")
    Path("config/sources.yaml").write_text(yaml.safe_dump({"sources": [news]}))
    monkeypatch.setattr("ccu_intelligence.collect.time.sleep", lambda _: None)
    pages = {1: rss(("New item", "https://carbonherald.com/new", "Thu, 08 Oct 2026 09:00:00 GMT", "CO2 use")),
             2: rss(("In window", "https://carbonherald.com/in", "Mon, 21 Sep 2026 09:00:00 GMT", "CO2 use"),
                    ("Too old", "https://carbonherald.com/old", "Mon, 07 Sep 2026 09:00:00 GMT", "CO2 use"))}
    seen = []

    def fetch(self, url, **kw):
        if url.endswith("/robots.txt"):
            return Fetched(200, httpx.Headers({}), b"User-agent: *\nAllow: /\n", url)
        page_number = int(url.split("paged=")[1]) if "paged=" in url else 1
        seen.append(page_number)
        return Fetched(200, httpx.Headers({}), pages.get(page_number, rss()), url)

    monkeypatch.setattr(Fetcher, "fetch", fetch)
    store = Store(tmp_path / "s.sqlite")
    try:
        counts = collect(store, date(2026, 9, 14), date(2026, 9, 27), news["source_id"], 10)
        assert seen == [1, 2] and counts["added"] == 1 and counts["outside_window"] == 2
        assert [a.title for a in store.articles()] == ["In window"]
    finally:
        store.close()


def test_gdelt_and_govuk_parsers():
    from ccu_intelligence.collect import gdelt_items, govuk_items

    gdelt = json.dumps({"articles": [{"title": "Port e-methanol plant", "url": "https://news.example/x",
                                      "seendate": "20260927T101500Z"}, {"title": "No date", "url": "https://n.example/y"}]})
    assert gdelt_items(gdelt.encode()) == [
        {"title": "Port e-methanol plant", "url": "https://news.example/x", "publication_date": "2026-09-27",
         "summary": ""},
        {"title": "No date", "url": "https://n.example/y", "publication_date": None, "summary": ""}]
    govuk = json.dumps({"results": [{"title": "UK carbon management challenge", "link": "/government/x",
                                     "public_timestamp": "2026-09-14T10:00:00Z", "description": "Funding."}]})
    assert govuk_items(govuk.encode())[0]["url"] == "https://www.gov.uk/government/x"


def test_bot_challenge_page_is_logged_not_bypassed(monkeypatch, tmp_path):
    from ccu_intelligence.collect import collect
    from ccu_intelligence.store import Store

    monkeypatch.chdir(tmp_path)
    shutil.copytree(ROOT / "config", "config")
    sources = yaml.safe_load((ROOT / "config/sources.yaml").read_text())["sources"]
    Path("config/sources.yaml").write_text(yaml.safe_dump({"sources": [
        s for s in sources if s["source_id"] in ("news-utilization-carbonherald", "news-45q-carbonherald")]}))
    requests = []

    def fetch(self, url, **kw):
        requests.append(url)
        if url.endswith("/robots.txt"):
            return Fetched(200, httpx.Headers({}), b"User-agent: *\nAllow: /\n", url)
        return Fetched(202, httpx.Headers({"content-type": "text/html"}),
                       b"<html><meta http-equiv='refresh' content='0;/.well-known/sgcaptcha/'></html>", url)

    monkeypatch.setattr(Fetcher, "fetch", fetch)
    store = Store(tmp_path / "s.sqlite")
    try:
        shared = Fetcher()
        for sid in ("news-utilization-carbonherald", "news-45q-carbonherald"):
            counts = collect(store, date(2026, 9, 14), date(2026, 9, 27), sid, 10, fetcher=shared)
            assert counts["failed"] == 1
            assert counts["errors"] == ["non-feed response (possible bot challenge; not bypassed)"]
        # One feed request per source, no retries or challenge-solving, and robots.txt fetched once per run.
        assert sum(u.endswith("/robots.txt") for u in requests) == 1 and len(requests) == 3
        assert not any("sgcaptcha" in u for u in requests)
    finally:
        store.close()


def test_retries_never_run_faster_than_the_polite_interval(monkeypatch):
    sleeps, replies = [], [httpx.Response(429), httpx.Response(200, content=b"ok")]
    monkeypatch.setattr("ccu_intelligence.collect.public_url", lambda url: None)
    monkeypatch.setattr("ccu_intelligence.collect.time.sleep", sleeps.append)
    fetcher = Fetcher(client=httpx.Client(transport=httpx.MockTransport(lambda r: replies.pop(0))))
    try:
        assert fetcher.get("https://api.example/doc", interval=6) == b"ok"
        assert sleeps[0] >= 6  # back-off after the 429 (later sleeps are ordinary host spacing)
    finally:
        fetcher.client.close()
