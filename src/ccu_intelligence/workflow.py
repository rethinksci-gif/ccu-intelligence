"""Bounded, on-demand biweekly research workflow: collect → full text → two-stage analysis → draft."""

import argparse
import fcntl
import hashlib
import json
import os
import re
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .budget import Budget
from .collect import Fetcher, collect, registry
from .currency import mismatches
from .currency import note as currency_note
from .editorial import validate_issue
from .fulltext import PageReader, SourceText, obtain, openalex_records, select_content
from .models import NOT_STATED, DedupResult, Enrichment, Synthesis, VerificationResult
from .newsletter import render
from .normalize import plain
from .pricing import OFFICIAL_ENDPOINTS, call_cost, projection, roles
from .pricing import load as load_pricing
from .settings import load_environment
from .stages import (
    ENRICHMENT_CHARS,
    PROMPT_VERSION,
    SCREENING_CHARS,
    Caller,
    apply_verification,
    band,
    checklist,
    dedup_groups,
    entity_stories,
    field_coverage,
    ground_enrichment,
    is_compilation,
    merge_stories,
    move_requests,
    newsletter_config,
    numbers,
    screening_schema,
    select,
    story_groups,
    takeaways,
    validate_synthesis,
    word_count,
)
from .store import Store

# Hard ceilings. Dispatch inputs may only lower them; raising one needs a reviewed code change.
MAX_SCREENINGS_CAP = 150  # new screening calls (cheap model)
MAX_ENRICHMENTS_CAP = 60  # items sent to enrichment + verification (strong model)
MAX_REQUESTS_CAP = 400  # 150 screenings + 2 x 60 enrichments/verifications + dedup + synthesis + repairs
MAX_SPEND_USD_CAP = 5.0
MAX_TOKEN_BUDGET = 5_000_000
FULLTEXT_FETCH_CAP = MAX_SCREENINGS_CAP
WORKERS = 4

# CCU terms. Any match also exempts a headline from the unrelated-energy (OFF_TOPIC) rule below,
# so CCU stories that mention solar, batteries or nuclear power are kept. For academic items a term is required;
# news, company, industry and government items reach the gate without one (the terms only raise priority).
CCU_TERMS = [
    r"co2(?!\+)",  # also covers CO2 electrolysis, CO2 mineralization, CO2-derived materials and CO2 offtake
    r"carbon.dioxide",
    r"ccus?",
    r"carbon captur\w*",
    r"carbon minerali[sz]\w*",
    r"direct air capture",
    r"e-?methanol",
    r"e-?methane",
    r"e-?kerosene",
    r"synthetic kerosene",
    r"e-?saf",
    r"e-?fuels?",  # eFuels, e-fuel, efuels (Arcadia eFuels)
    r"electrofuels?",
    r"synthetic fuels?",
    r"solar fuels?",
    r"power.to.(?:x|liquids?|gas|fuels?|methanol)",
    r"ptx",
    r"ptl",
    r"rfnbos?",
    r"fischer.tropsch",
    r"45q",
]
CCU = re.compile(r"\b(?:" + "|".join(CCU_TERMS) + r")\b", re.I)
# Adjacent terms: routed to the gate as borderline (also for academic items), never counted as CCU by themselves.
ADJACENT = re.compile(r"\be-?ammonia\b", re.I)
# Utilization context: generic carbon capture/storage, footprints and optical CO2 transitions are not CCU
# by themselves. Fuel/material terms that only exist as CO2 utilization count as context on their own.
CONVERSION = re.compile(
    r"utili[sz]|convert|conversion|reduc(?:tion|e)|methanol|ethanol|ethylene|minerali[sz]|polyol|carbonate|"
    r"electrofuel|electroly[sz]\w*|electroreduc\w*|electrosynthes\w*|(?:co2|carbon.dioxide).derived|"
    r"from (?:co2|carbon.dioxide)(?!\s+value\b)|e-?kerosene|synthetic kerosene|e-?fuel|e-?saf|e-?methane|"
    r"synthetic fuel|solar fuel|power.to.|ptx|\bptl\b|rfnbo|fischer.tropsch|offtake|off.take",
    re.I,
)
# CCU-specialist sources: ecosystem news (memberships, association updates) is sent to the gate and, if relevant
# but not selected, appears as a headline-only "CCU ecosystem brief".
CCU_SPECIALIST_SOURCES = {"co2-value-europe", "liquid-wind", "dioxycle", "carbicrete"}
BRIEF = "specialist source: borderline, gate decides"
BORDERLINE = "CCU term without utilization context"
NON_ACADEMIC = "news/company/industry/government: gate decides"
# Staff/HR announcements from CCU-specialist sources are dropped; matched on the title only. Membership wording overrides,
# so "CO2 Value Europe welcomes new member X" and "X Joins CO2 Value Europe" still reach the gate.
STAFF = re.compile(
    r"\b(?:welcome|joins? our team|new colleagues?|hiring|we.re hiring|hires|vacanc(?:y|ies)|job openings?|"
    r"internships?)\b",
    re.I,
)
MEMBERSHIP = re.compile(r"\b(?:member(?:s|ship)?|joins?(?! our team))\b", re.I)
# Unrelated energy topics (solar, batteries, nuclear) without any CCU or fuel term are not CCU leads.
OFF_TOPIC = re.compile(r"\b(?:solar|photovoltaic|pv park|batter(?:y|ies)|hydropower|nuclear)\b", re.I)
FUEL = re.compile(r"\b(?:fuels?|hydrogen|h2|methanol|ammonia|saf|aviation|shipping|maritime|refiner\w*|chemicals?)\b",
                  re.I)
# Clearly off-topic titles (sport, banking and personal finance, entertainment) are dropped for every source kind.
OFF_TOPIC_TITLE = re.compile(
    r"\b(?:formula (?:1|one)|f1|grand prix|motorsport|racing|football|soccer|cricket|tennis|golf|rugby|olympics?|"
    r"world cup|premier league|solar (?:car|challenge|race)|banks? (?:open|closed|shut|strike|holidays?)|"
    r"bank strike|interest rates?|mortgages?|stock market|sensex|nifty|horoscopes?|recipes?|box office|"
    r"celebrit(?:y|ies))\b",
    re.I,
)
EVENT = re.compile(
    r"\b(?:fid|financ\w*|offtake|off.take|construct\w*|operat\w*|commission\w*|"
    r"delay\w*|cancel\w*|bankrupt\w*|investment decision|permit\w*)\b",
    re.I,
)
GATED = {"CCU topic", "specialist milestone", BRIEF, BORDERLINE, NON_ACADEMIC}


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str))
    tmp.replace(path)


def source_kind(source):
    if source.source_type == "scholarly_metadata":
        return "academic"
    if source.source_type == "news_search" or getattr(source, "evidence_role", "primary") == "news":
        return "news"
    if source.source_type.startswith("company_"):
        return "company"
    return "government" if source.source_type == "government" else "industry"


def triage(article, source, since, until):
    """Keyword pre-filter. Academic items need a CCU term; news, company, industry and government items all go
    to the LLM gate unless the title is clearly off-topic (sport, banking, unrelated energy, staff news)."""
    text = plain(article.title + " " + article.summary).replace("₂", "2")
    title = plain(article.title)
    kind = source_kind(source)
    if article.sample:
        return {"eligible": False, "reason": "sample", "kind": kind}
    if not article.publication_date or not since <= article.publication_date <= until:
        return {"eligible": False, "reason": "unknown or outside publication window", "kind": kind}
    matched = bool(CCU.search(text))
    adjacent = bool(ADJACENT.search(text))
    specialist = source.source_id in {"liquid-wind", "dioxycle", "carbicrete"}
    conversion = bool(CONVERSION.search(text))
    event = bool(EVENT.search(text))
    ccu_specialist = source.source_id in CCU_SPECIALIST_SOURCES
    unrelated_energy = OFF_TOPIC.search(text) and not matched and not adjacent and not FUEL.search(text)
    if ccu_specialist and STAFF.search(article.title) and not MEMBERSHIP.search(article.title):
        # Applies before any other rule so job ads never reach the model, even if they mention CO2 utilisation.
        reason = "specialist source: staff/HR announcement"
    elif matched and conversion:
        reason = "CCU topic"
    elif OFF_TOPIC_TITLE.search(title) and not matched:
        reason = "clearly off-topic title"
    elif specialist and event and unrelated_energy:
        reason = "specialist feed: unrelated energy topic"
    elif specialist and event:
        reason = "specialist milestone"
    elif matched and ccu_specialist:
        reason = BRIEF
    elif matched or adjacent or (conversion and kind == "news"):
        reason = BORDERLINE
    elif kind != "academic" and unrelated_energy:
        reason = "unrelated energy topic"
    elif kind != "academic":
        reason = NON_ACADEMIC
    else:
        reason = "no CCU term"
    strength = {"CCU topic": 2, "specialist milestone": 2, NON_ACADEMIC: 0}.get(reason, 1)
    return {
        "eligible": reason in GATED,
        "reason": reason,
        "kind": kind,
        "event_lead": kind not in ("academic", "news") and event,
        "priority": strength * 10 + {"academic": 0, "news": 1}.get(kind, 2) * 2 + int(event),
    }


def account_balance(endpoint: str) -> dict | None:
    """Prepaid balance per currency (DeepSeek /user/balance); only the before/after difference is reported."""
    key = os.getenv("LLM_API_KEY")
    if not key:
        return None
    try:
        with httpx.Client(timeout=20, follow_redirects=False) as client:
            response = client.get(endpoint + "/user/balance", headers={"Authorization": "Bearer " + key})
            response.raise_for_status()
            return {b["currency"]: float(b["total_balance"]) for b in response.json().get("balance_infos", [])}
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return None


def item_metadata(article, source, decision, text: SourceText) -> dict:
    return {
        "title": article.title,
        "source": source.organization,
        "source_kind": decision["kind"],
        "evidence_role": source.evidence_role,
        "publication_date": str(article.publication_date),
        "input_basis": text.basis,
    }


def allowed_numbers(article, text: str) -> set[str]:
    """Numbers the brief may use: the supplied text plus the title and publication date."""
    return numbers(text) | numbers(article.title) | numbers(str(article.publication_date))


def check_args(args):
    args.dry_run = getattr(args, "dry_run", False) or not getattr(args, "allow_paid", False)
    args.max_spend_usd = getattr(args, "max_spend_usd", MAX_SPEND_USD_CAP)
    args.source_limit = getattr(args, "source_limit", None)
    args.fetch_full_text = getattr(args, "fetch_full_text", True)
    args.google_news = getattr(args, "google_news", False)  # documented robots exception: research runs only
    if args.source_limit is not None and not 1 <= args.source_limit <= 30:
        raise ValueError("Per-source candidate cap must be 1–30")
    if args.until > date.today() or args.since > args.until or not 1 <= (args.until - args.since).days + 1 <= 31:
        raise ValueError("Use a 1–31 day inclusive collection window ending no later than today")
    if args.scheduled_publication and args.scheduled_publication <= args.until:
        raise ValueError("Scheduled publication must follow the coverage window")
    args.max_enrichments = getattr(args, "max_enrichments", MAX_ENRICHMENTS_CAP)
    if not 0 <= args.max_screenings <= MAX_SCREENINGS_CAP or not 0 <= args.max_requests <= MAX_REQUESTS_CAP:
        raise ValueError(f"Caps: <={MAX_SCREENINGS_CAP} new screenings and <={MAX_REQUESTS_CAP} requests")
    if not 0 <= args.max_enrichments <= MAX_ENRICHMENTS_CAP:
        raise ValueError(f"Caps: <={MAX_ENRICHMENTS_CAP} enrichments")
    if not 1 <= args.token_budget <= MAX_TOKEN_BUDGET:
        raise ValueError(f"Token budget must be 1–{MAX_TOKEN_BUDGET}")
    if not 0 <= args.max_spend_usd <= MAX_SPEND_USD_CAP:
        raise ValueError(f"Spending cap must be between 0 and {MAX_SPEND_USD_CAP} USD")
    if not args.output.resolve().is_relative_to(Path("data/runtime").resolve()):
        raise ValueError("Output must stay private under data/runtime")
    if not args.dry_run and os.getenv("GITHUB_ACTIONS") == "true":
        event = os.getenv("GITHUB_EVENT_NAME")
        trusted = os.getenv("GITHUB_REF") == "refs/heads/" + os.getenv("DEFAULT_BRANCH", "main")
        if not trusted or event != "workflow_dispatch" or os.getenv("GITHUB_RUN_ATTEMPT") != "1":
            raise ValueError("Paid processing requires a trusted default-branch dispatch and first attempt")
    if not args.dry_run and not os.getenv("LLM_API_KEY"):
        raise ValueError("Paid processing requires LLM_API_KEY")


def execute(args):
    load_environment()
    check_args(args)
    pricing = load_pricing()
    stage_roles = roles(pricing)  # rejects any model missing from the pricing table
    endpoint = os.getenv("LLM_BASE_URL", pricing["endpoint"]).rstrip("/")
    if endpoint not in OFFICIAL_ENDPOINTS:
        raise ValueError("This pricing/budget profile requires the official DeepSeek endpoint")
    os.environ["LLM_BASE_URL"] = endpoint
    config = newsletter_config()
    categories = list(config["categories"])
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / ".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        run_config = {k: str(v) if isinstance(v, (Path, date)) else v for k, v in vars(args).items()}
        run_config.update(
            endpoint=endpoint,
            models={stage: {"model": r.model, "thinking": r.thinking, "max_output_tokens": r.max_output_tokens,
                            "ceiling_usd_per_million": vars(r.rates)} for stage, r in stage_roles.items()},
            prompt_version=PROMPT_VERSION,
            source_registry_hash=hashlib.sha256(Path("config/sources.yaml").read_bytes()).hexdigest(),
        )
        run_config = json.loads(json.dumps(run_config))
        config_path = args.output / "config.json"
        if config_path.exists() and json.loads(config_path.read_text()) != run_config:
            raise ValueError("Existing run has different configuration; use another output directory")
        atomic_json(config_path, run_config)
        report_path = args.output / "report.json"
        if report_path.exists():
            report = json.loads(report_path.read_text())
            print(json.dumps(report["summary"], indent=2))
            return report
        ledger = args.output / "budget.json"
        budget = Budget(**json.loads(ledger.read_text())) if ledger.exists() else Budget(
            max_requests=0 if args.dry_run else args.max_requests, max_tokens=args.token_budget,
            max_spend_usd=args.max_spend_usd)
        budget.path = ledger
        budget.save()
        balance_before = None if args.dry_run else account_balance(endpoint)
        store = Store(args.output / "intelligence.sqlite")
        try:
            return _run(args, store, budget, stage_roles, pricing, config, categories, endpoint, balance_before)
        finally:
            store.close()


def _run(args, store, budget, stage_roles, pricing, config, categories, endpoint, balance_before):
    sources = {s.source_id: s for s in registry()}
    limits = [(s.source_id, min(s.run_limit, args.source_limit or s.run_limit))
              for s in sources.values() if s.run_limit and s.active and s.automated_access_approved
              and (args.google_news or s.access_method != "google_news")]
    collection_file = args.output / "collection.json"
    collection = json.loads(collection_file.read_text()) if collection_file.exists() else {}
    shared = Fetcher()
    try:
        for source_id, limit in limits:
            if source_id not in collection:
                collection[source_id] = collect(store, args.since, args.until, source_id, limit,
                                                '"carbon dioxide" utilization', fetcher=shared,
                                                google_news=args.google_news)
                atomic_json(collection_file, collection)
    finally:
        shared.client.close()
    bundle = store.bundle()
    atomic_json(args.output / "bundle.json", bundle.model_dump(mode="json"))
    if len(bundle.articles) > sum(limit for _, limit in limits):
        raise ValueError("Candidate cap exceeded")
    articles = {a.article_id: a for a in bundle.articles}
    decisions = {a.article_id: triage(a, sources[a.source_id], args.since, args.until) for a in bundle.articles}
    gated = sorted([a for a in bundle.articles if decisions[a.article_id]["eligible"]],
                   key=lambda a: (-decisions[a.article_id]["priority"], a.article_id))

    # Full text: robots-respecting extraction and open-access papers. Text stays in memory and a private cache.
    texts: dict[str, SourceText] = {}
    fetcher = Fetcher()
    try:
        papers = {}
        if args.fetch_full_text:
            dois = [a.doi for a in gated[:FULLTEXT_FETCH_CAP] if a.doi and decisions[a.article_id]["kind"] == "academic"]
            papers = openalex_records(fetcher, dois) if dois else {}
        reader = PageReader(fetcher)
        for index, article in enumerate(gated):
            source = sources[article.source_id]
            if args.fetch_full_text and index < FULLTEXT_FETCH_CAP:
                texts[article.article_id] = obtain(article, source, reader, papers.get(article.doi or ""))
            else:
                summary = plain(article.summary).replace(article.title, "").strip()
                texts[article.article_id] = SourceText("headline", article.title + ("\n" + summary if summary else ""),
                                                       None, "feed title and snippet")
    finally:
        fetcher.client.close()

    caller = Caller(stage_roles, budget, config, paid=not args.dry_run)

    def label(article, source) -> str:
        """Citation label: the outlet for GDELT results, the organization otherwise (without search notes)."""
        if source.access_method == "google_news":  # the publisher, never Google, is the outlet
            host = urlsplit(str(article.canonical_url)).hostname
            publisher = re.sub(r"^Publisher: ", "", plain(article.summary)) or "publisher unknown"
            return host.removeprefix("www.") if host != "news.google.com" else f"{publisher} (via Google News)"
        if source.access_method in ("gdelt", "editor_list"):
            return urlsplit(str(article.canonical_url)).hostname.removeprefix("www.")
        return re.sub(r"\s*\((?:site search|open-access subset)[^)]*\)", "", source.organization)

    records = {a.article_id: {
        "article_id": a.article_id, "title": a.title, "url": str(a.canonical_url), "source_id": a.source_id,
        "source_name": label(a, sources[a.source_id]), "evidence_role": sources[a.source_id].evidence_role,
        "publication_date": str(a.publication_date), "triage": decisions[a.article_id],
        "editor_submitted": sources[a.source_id].access_method == "editor_list",
        "input": texts[a.article_id].record() if a.article_id in texts else None,
    } for a in bundle.articles}

    # Stage 1: relevance gate and decision-value score (screening model) on every gated item, within the cap.
    attempted_path = args.output / "attempted.json"
    attempted = json.loads(attempted_path.read_text()) if attempted_path.exists() else []
    guard = threading.Lock()
    schema = screening_schema(categories)

    def screen(article):
        record, text = records[article.article_id], texts[article.article_id]
        payload = item_metadata(article, sources[article.source_id], decisions[article.article_id], text) | {
            "content": select_content(text.text, SCREENING_CHARS)}
        key = caller.key("screening", schema, payload)
        cached = (Path("data/runtime/llm-cache") / f"{key}.json").exists()
        with guard:
            if not cached and article.article_id not in attempted:
                if len(attempted) >= args.max_screenings or args.dry_run:
                    record["screening_status"] = "not analysed: dry run" if args.dry_run else "not analysed: cap"
                    return
                attempted.append(article.article_id)
                atomic_json(attempted_path, attempted)
        result = caller("screening", schema, payload, article.article_id)
        if result is None:
            record["screening_status"] = "failed or budget exhausted" if not args.dry_run else "not analysed: dry run"
            return
        score = 0.0 if not result.ccu_relevant else float(result.score)
        if text.basis == "headline":
            score = min(score, config["headline_score_cap"])
        record["screening_status"] = "screened"
        record["screening"] = result.model_dump() | {"score": score, "model_score": result.score, "band": band(score)}

    with ThreadPoolExecutor(WORKERS) as pool:
        list(pool.map(screen, gated))

    entries = []
    for article in gated:
        record = records[article.article_id]
        screening = record.get("screening")
        if screening and screening["ccu_relevant"]:
            entries.append({"article_id": article.article_id, "score": screening["score"],
                            "category": screening["category"], "evidence_role": record["evidence_role"],
                            "input_basis": texts[article.article_id].basis, "record": record,
                            "kind": decisions[article.article_id]["kind"]})
    # Compilations of several studies (poster collections, highlights) are listed, never primary research items.
    for entry in [e for e in entries if e["kind"] == "academic" and is_compilation(e)]:
        records[entry["article_id"]]["selection"] = "compilation (listed only)"
        entries.remove(entry)

    # Cross-source dedup of the same event (strong model) over everything that could be selected.
    eligible = sorted([e for e in entries if e["score"] >= config["threshold"]], key=lambda e: (-e["score"]))
    for number, entry in enumerate(eligible, 1):
        entry["sid"] = f"D{number}"
    merged, story_of = {}, {}
    if len(eligible) > 1:
        payload = {"items": [{"id": e["sid"], "title": e["record"]["title"], "source": e["record"]["source_name"],
                              "evidence_role": e["evidence_role"],
                              "outlet": urlsplit(e["record"]["url"]).hostname.removeprefix("www."),
                              "date": e["record"]["publication_date"],
                              "score": e["score"], "category": e["category"],
                              "tags": e["record"]["screening"]["tags"],
                              "summary": e["record"]["screening"]["summary"]} for e in eligible]}
        groups = caller("dedup", DedupResult, payload, "dedup")
        merged = dedup_groups(groups, eligible, config)
        story_of = story_groups(groups, eligible, merged)
    story_of, roundups = entity_stories(eligible, story_of, merged)
    also: dict[str, list] = {}
    for duplicate, kept in merged.items():
        records[duplicate]["selection"] = f"duplicate of {kept}"
        also.setdefault(kept, []).append(records[duplicate])
    chosen, selection = select([e for e in entries if e["article_id"] not in merged], config, story_of)
    # Enrichment cap: items beyond it (in selection order) are not sent to the strong model.
    for entry in chosen[args.max_enrichments:]:
        selection[entry["article_id"]] = "selected, not enriched: enrichment cap"
    cut_by_enrichment_cap = len(chosen[args.max_enrichments:])
    chosen = chosen[: args.max_enrichments]
    for article_id, status in selection.items():
        records[article_id]["selection"] = status
        if article_id in story_of:
            records[article_id]["story"] = story_of[article_id]

    # Stage 2: enrichment, deterministic grounding, independent verification (strong model).
    def enrich(entry):
        article = articles[entry["article_id"]]
        record, text = entry["record"], texts[article.article_id]
        content = select_content(text.text, ENRICHMENT_CHARS)
        payload = item_metadata(article, sources[article.source_id], decisions[article.article_id], text) | {
            "screening": {k: record["screening"][k] for k in ("category", "tags", "summary")}, "content": content}
        result = caller("enrichment", Enrichment, payload, article.article_id)
        if result is None:
            record["enrichment_status"] = "failed or not run"
            return None
        result, removed = ground_enrichment(result, content)
        record["grounding_removed"] = removed
        allowed = allowed_numbers(article, content)
        checks = caller("verification", VerificationResult,
                        {"source_text": content, "items_to_check": checklist(result)}, article.article_id)
        if checks is None:
            record["enrichment_status"] = "verification unavailable: excluded"
            return None
        verified, log = apply_verification(result, checks, content, allowed, article.title)
        record["verification"] = log
        if verified is None:
            record["enrichment_status"] = "core claim unsupported: excluded"
            return None
        record["enrichment_status"] = "verified"
        event = verified.event_date
        if event and not args.since <= event <= args.until:
            record["background_event_date"] = str(event)
        record["enrichment"] = verified.model_dump(mode="json")
        record["fields"] = field_coverage(verified)
        record["brief_words"] = word_count(verified)
        return entry | {"enrichment": record["enrichment"], "content": content}

    with ThreadPoolExecutor(WORKERS) as pool:
        verified = [e for e in pool.map(enrich, chosen) if e]
    kept_ids = {e["article_id"] for e in verified}
    for entry in chosen:
        if entry["article_id"] not in kept_ids:
            records[entry["article_id"]]["selection"] = "selected, then excluded at enrichment/verification"
    # Story members stay together, under the category and rank of the story's best item.
    story_lead = {}
    for entry in sorted(verified, key=lambda e: -e["score"]):
        story_lead.setdefault(story_of.get(entry["article_id"], entry["article_id"]), entry)

    def order(entry):
        lead = story_lead[story_of.get(entry["article_id"], entry["article_id"])]
        return categories.index(lead["category"]), -lead["score"], lead["article_id"], -entry["score"]

    verified.sort(key=order)
    final = []
    for number, entry in enumerate(verified, 1):
        record = entry["record"]
        story = story_of.get(entry["article_id"], entry["article_id"])
        final.append({"sid": f"S{number}", "article_id": entry["article_id"], "title": record["title"],
                      "story": story, "story_category": story_lead[story]["category"],
                      "editor_submitted": record["editor_submitted"], "kind": entry["kind"],
                      "background": record.get("background_event_date"),
                      "url": record["url"], "source_name": record["source_name"],
                      "evidence_role": entry["evidence_role"], "publication_date": record["publication_date"],
                      "input_basis": entry["input_basis"], "category": entry["category"], "score": entry["score"],
                      "enrichment": entry["enrichment"], "content": entry["content"]})
    leads = takeaways(final, config)
    story_sids: dict[str, list[str]] = {}
    for e in final:
        story_sids.setdefault(e["story"], []).append(e["sid"])
    sid_story = {sid: story for story, sids in story_sids.items() if len(sids) > 1 for sid in sids}

    # Final synthesis (strong model) over verified briefs only, then deterministic citation/number/quote checks.
    synthesis, synthesis_issues = None, []
    if final:
        items = {}
        for e in final:
            brief = e["enrichment"]
            items[e["sid"]] = {
                "source_id": e["sid"], "category": e["story_category"], "title": e["title"],
                "source_name": e["source_name"], "evidence_role": e["evidence_role"],
                "input_basis": e["input_basis"], "publication_date": e["publication_date"],
                "brief": {k: brief[k] for k in ("headline", "what_changed", "why_it_matters",
                                                "practical_implication", "next_action")},
                "facts": {k: v["value"] for k, v in brief["fields"].items() if v["value"] != NOT_STATED},
                "technical": [d["text"] for d in brief["technical_information"]],
                "economic": [d["text"] for d in brief["economic_information"]],
                "milestones": [{k: d[k] for k in ("text", "event_type", "event_date", "project_name")}
                               for d in brief["milestone_proposals"]],
                "quotes": brief["quotes"], "uncertainty": brief["uncertainty"],
                "also_reported_by": [d["source_name"] for d in also.get(e["article_id"], [])],
                "story_id": e["story"] if e["sid"] in sid_story else None,
                "background_event_date": e["background"],
                "related_roundups": [records[r]["title"] for r in roundups.get(e["article_id"], [])],
            }
        payload = {
            "coverage": {"start": str(args.since), "end_inclusive": str(args.until)},
            "section_order": [{"category": k, "name": config["categories"][k]["name"]} for k in categories
                              if any(e["story_category"] == k for e in final)],
            "stories": [sids for sids in story_sids.values() if len(sids) > 1],
            "takeaway_plan": [{"category": e["story_category"], "source_ids": story_sids[e["story"]]}
                              for e in leads],
            "items": list(items.values()),
        }
        result = caller("synthesis", Synthesis, payload, "synthesis")
        if result is not None:
            result, synthesis_issues = validate_synthesis(result, items, {e["sid"]: e["content"] for e in final},
                                                          categories)
            synthesis = result.model_dump()
            merge_stories(synthesis, sid_story)
            synthesis["editor_notes"] += move_requests(synthesis)

    headlines = {e["sid"]: e["enrichment"]["headline"] for e in final}
    notes = [re.sub(r"\bS\d+\b", lambda m: f"'{headlines[m.group(0)]}'" if m.group(0) in headlines else m.group(0), n)
             for n in (synthesis or {}).get("editor_notes", [])]
    for e in final:
        for issue in {i["text"]: i for i in mismatches(json.dumps(e["enrichment"], ensure_ascii=False))}.values():
            notes.append(currency_note(e["enrichment"]["headline"], issue))
        if e["background"]:
            notes.append(f"'{e['enrichment']['headline']}' reports an event dated {e['background']}, before the "
                         "coverage window; it is labelled background and kept out of the takeaways.")
        for milestone in e["enrichment"]["milestone_proposals"]:
            when = milestone.get("event_date")
            if when and not str(args.since) <= str(when) <= str(args.until):
                notes.append(f"Background in '{e['enrichment']['headline']}': {milestone['text']} (event date {when}).")
    if any(e["input_basis"] == "headline" for e in final):
        notes.append("Some items rest on a headline only; open the original before using them.")
    if final and synthesis is None:
        notes.append("Synthesis was unavailable; sections show the verified per-item briefs.")
    # Relevant items that were not selected, headline and link only: specialist-source news ("CCU ecosystem
    # briefs"), papers ("Also noted in research") and other news, company and policy items.
    leftovers = sorted([r for r in records.values() if r.get("screening") and r["screening"]["ccu_relevant"]
                        and r.get("selection") in ("below threshold", "category cap", "overall cap", "research cap",
                                                    "compilation (listed only)")
                        and r["screening"]["score"] >= config.get("also_noted_min_score", 3)],
                       key=lambda r: (-r["screening"]["score"], r["title"]))
    briefs = [r for r in leftovers if r["source_id"] in CCU_SPECIALIST_SOURCES]
    research = [r for r in leftovers if r not in briefs and r["triage"]["kind"] == "academic"]
    other = [r for r in leftovers if r not in briefs and r not in research]
    pending = [records[e["article_id"]] for e in chosen if e["article_id"] not in {f["article_id"] for f in final}]
    inbox = [r | {"status": r.get("screening_status", "")} for r in records.values()
             if r["triage"]["eligible"] and not r.get("screening")]
    draft = args.output / "draft.md"
    draft.write_text(render(
        args=args, meta_counts={"collected": len(bundle.articles),
                                "screened": sum(bool(r.get("screening")) for r in records.values())},
        roundups={e["sid"]: [records[r] for r in roundups.get(e["article_id"], [])] for e in final},
        config=config, selected=final, synthesis=synthesis, takeaway_entries=leads, briefs=briefs,
        also_research=research, also_other=other, also=also, notes=notes, pending=pending, inbox=inbox))
    validate_issue(draft, bundle)

    calls = caller.calls
    for call in calls:
        if call.get("usage") and "cost" not in call:
            call["cost"] = call_cost(call["model"], call["usage"], datetime.fromisoformat(call["at"]), pricing)
    by_model = {}
    for call in calls:
        if call.get("usage"):
            agg = by_model.setdefault(call["model"], Counter())
            agg.update({k: v or 0 for k, v in call["usage"].items()} | {"calls": 1})
            agg.update({"upper_bound_usd_micro": int(call["cost"]["upper_bound_usd"] * 1e6),
                        "estimate_usd_micro": int(call["cost"]["estimate_usd"] * 1e6)})
    balance_after = None if args.dry_run else account_balance(endpoint)
    balance_delta = ({c: round(balance_before[c] - balance_after.get(c, balance_before[c]), 6)
                      for c in balance_before} if balance_before and balance_after else None)
    # Cost projection for the calls a paid run would still have to make (cache hits are free).
    to_screen = min(sum(r.get("screening_status") == "not analysed: dry run" for r in records.values()),
                    max(args.max_screenings - len(attempted), 0))
    stories_low, stories_high = config["target_min_items"], config["overall_cap"]
    projected = None
    if args.dry_run:
        projected = {
            "uncached_screenings": to_screen,
            "assumption": f"{stories_low}–{stories_high} enriched items (the selection target), one dedup and one "
                          "synthesis call; average tokens per call from config/models.yaml",
            "low": projection(stage_roles, {"screening": to_screen, "dedup": 1, "enrichment": stories_low,
                                            "verification": stories_low, "synthesis": 1}, pricing),
            "high": projection(stage_roles, {"screening": to_screen, "dedup": 1, "enrichment": stories_high,
                                             "verification": stories_high, "synthesis": 1}, pricing),
        }
    summary = {
        "coverage": {"start": str(args.since), "end_inclusive": str(args.until)},
        "collected_articles": len(bundle.articles),
        "candidate_records_considered": sum(c["considered"] for c in collection.values()),
        "coverage_by_source_kind": dict(Counter(source_kind(sources[a.source_id]) for a in bundle.articles)),
        "gated_for_llm": len(gated),
        "promising_candidates": len(gated),
        "dropped_by_keyword": sum(not d["eligible"] for d in decisions.values()),
        "input_basis": dict(Counter(t.basis for t in texts.values())),
        "screened": sum(bool(r.get("screening")) for r in records.values()),
        "ccu_relevant": len(entries),
        "above_threshold": len(eligible),
        "duplicates_merged": len(merged),
        "selected_for_enrichment": len(chosen),
        "verified_in_draft": len(final),
        "takeaways": len(leads),
        "synthesis": "validated" if synthesis else ("unavailable" if final else "not needed"),
        "synthesis_issues": len(synthesis_issues),
        "new_analyses_attempted": len(attempted),
        "cache_hits": sum(c.get("status") == "cache_hit" for c in calls),
        "dry_run": args.dry_run,
        "max_new_screenings": args.max_screenings,
        "max_enrichments": args.max_enrichments,
        "cut_by_screening_cap": sum(r.get("screening_status") == "not analysed: cap" for r in records.values())
        + max(sum(r.get("screening_status") == "not analysed: dry run" for r in records.values()) - to_screen, 0),
        "cut_by_enrichment_cap": cut_by_enrichment_cap,
        "cut_by_fulltext_cap": max(len(gated) - FULLTEXT_FETCH_CAP, 0) if args.fetch_full_text else 0,
        "max_spend_usd": args.max_spend_usd,
        "token_budget": args.token_budget,
        "requests_reserved": budget.requests,
        "tokens_charged_to_budget": budget.charged_tokens,
        "reserved_cost_usd": budget.reserved_cost_microusd / 1_000_000,
        "usage_by_model": {m: dict(v) for m, v in by_model.items()},
        "cost_upper_bound_usd": round(sum(c["cost"]["upper_bound_usd"] for c in calls if c.get("cost")), 6),
        "cost_estimate_usd": round(sum(c["cost"]["estimate_usd"] for c in calls if c.get("cost")), 6),
        "cost_complete": all(c.get("usage_reported", True) for c in calls if c.get("http_status") == 200),
        "balance_delta": balance_delta,
        "pricing": {"source": pricing["source"], "checked": pricing["checked"]},
        "draft": str(draft),
        "paid_run_projection": projected,
        "editor_submitted": [{"title": r["title"], "url": r["url"], "gate": (r.get("screening") or {}).get(
            "ccu_relevant"), "score": (r.get("screening") or {}).get("score"), "selection": r.get("selection"),
            "input_basis": (r.get("input") or {}).get("basis")} for r in records.values() if r["editor_submitted"]],
    }
    report = {"summary": summary, "triage": decisions, "promising_candidates": len(gated),
              "ecosystem_briefs": len(briefs), "also_noted_research": len(research), "also_noted_other": len(other),
              "records": list(records.values()),
              "synthesis_issues": synthesis_issues, "calls": calls}
    atomic_json(args.output / "report.json", report)
    print(json.dumps(summary, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    # Default: the most recent 14 complete days, ending yesterday.
    parser.add_argument("--since", type=date.fromisoformat, default=date.today() - timedelta(days=14))
    parser.add_argument("--until", type=date.fromisoformat, default=date.today() - timedelta(days=1))
    parser.add_argument("--scheduled-publication", type=date.fromisoformat)
    parser.add_argument("--output", type=Path, default=Path("data/runtime") / f"biweekly-{date.today()}")
    parser.add_argument("--max-screenings", type=int, default=MAX_SCREENINGS_CAP)
    parser.add_argument("--max-enrichments", type=int, default=MAX_ENRICHMENTS_CAP)
    parser.add_argument("--max-requests", type=int, default=MAX_REQUESTS_CAP)
    parser.add_argument("--token-budget", type=int, default=2_000_000)
    parser.add_argument("--source-limit", type=int)
    parser.add_argument("--dry-run", action="store_true", help="Collect and draft; zero paid requests")
    parser.add_argument("--allow-paid", action="store_true", help="Explicitly authorize bounded model calls")
    parser.add_argument("--max-spend-usd", type=float, default=MAX_SPEND_USD_CAP)
    execute(parser.parse_args())


if __name__ == "__main__":
    main()
