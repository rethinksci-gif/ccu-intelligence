"""Bounded, on-demand biweekly workflow over the existing collectors and store."""

import argparse
import fcntl
import hashlib
import json
import os
import re
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import yaml

from .budget import Budget
from .collect import collect, registry
from .editorial import SECTIONS, safe_text, validate_issue
from .llm import PROMPT_VERSION, date_supported, prompt_hash, quote_supported, run
from .models import Analysis, Evidence
from .normalize import plain
from .settings import load_environment
from .store import Store

# Feed payloads can contain more entries, but only these <=20 records are considered.
SOURCE_LIMITS = [
    ("liquid-wind", 2),
    ("dioxycle", 2),
    ("carbicrete", 2),
    ("covestro", 2),
    ("co2-value-europe", 3),
    ("uk-desnz", 3),
    ("crossref", 3),
    ("openalex", 3),
]
# CCU terms. Any match also exempts a headline from the unrelated-energy (OFF_TOPIC) rule below,
# so CCU stories that mention solar, batteries or nuclear power are kept.
CCU_TERMS = [
    r"co2(?!\+)",  # also covers CO2 electrolysis, CO2 mineralization and CO2-derived materials
    r"carbon.dioxide",
    r"ccus?",
    r"carbon captur\w*",
    r"carbon minerali[sz]\w*",
    r"direct air capture",
    r"e-?methanol",
    r"e-?kerosene",
    r"e-fuels?",
    r"electrofuels?",
    r"synthetic fuels?",
    r"solar fuels?",
    r"power.to.(?:x|liquids?|gas|fuels?|methanol)",
    r"ptx",
]
CCU = re.compile(r"\b(?:" + "|".join(CCU_TERMS) + r")\b", re.I)
# Utilization context: generic carbon capture/storage, footprints and optical CO2 transitions are not CCU
# by themselves. Fuel/material terms that only exist as CO2 utilization count as context on their own.
CONVERSION = re.compile(
    r"utili[sz]|convert|conversion|reduc(?:tion|e)|methanol|ethanol|ethylene|minerali[sz]|polyol|carbonate|"
    r"electrofuel|electroly[sz]\w*|electroreduc\w*|electrosynthes\w*|(?:co2|carbon.dioxide).derived|"
    r"from (?:co2|carbon.dioxide)|e-?kerosene|e-fuel|synthetic fuel|solar fuel|power.to.|ptx",
    re.I,
)
# Unrelated energy topics on specialist feeds (corporate news about adjacent assets) are not CCU leads.
OFF_TOPIC = re.compile(r"\b(?:solar|photovoltaic|pv park|batter(?:y|ies)|hydropower|nuclear)\b", re.I)
EVENT = re.compile(
    r"\b(?:fid|financ\w*|offtake|off.take|construct\w*|operat\w*|commission\w*|"
    r"delay\w*|cancel\w*|bankrupt\w*|investment decision|permit\w*)\b",
    re.I,
)
# Conservative peak cache-miss prices: upper estimate, not an invoice. Verified 2026-10-09.
PRICING = {
    "input_usd_per_million": 0.30,
    "output_usd_per_million": 1.20,
    "source": "https://api-docs.deepseek.com/quick_start/pricing/",
    "checked": "2026-10-09",
    "basis": "Peak, all input charged as cache miss; conservative estimate",
}


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False))
    tmp.replace(path)


def source_kind(source):
    if source.source_type == "scholarly_metadata":
        return "academic"
    if source.source_type.startswith("company_"):
        return "company"
    return "government" if source.source_type == "government" else "industry"


def triage(article, source, since, until):
    text = plain(article.title + " " + article.summary).replace("₂", "2")
    kind = source_kind(source)
    if article.sample:
        return {"eligible": False, "reason": "sample", "kind": kind}
    if not article.publication_date or not since <= article.publication_date <= until:
        return {"eligible": False, "reason": "unknown or outside publication window", "kind": kind}
    # Specialist company feeds admit project-only headlines, but never broad polymer news.
    matched = bool(CCU.search(text))
    specialist = source.source_id in {"liquid-wind", "dioxycle", "carbicrete"}
    conversion = bool(CONVERSION.search(text))
    event = bool(EVENT.search(text))
    if matched and conversion:
        reason = "CCU topic"
    elif specialist and event and OFF_TOPIC.search(text) and not matched:
        reason = "specialist feed: unrelated energy topic"
    elif specialist and event:
        reason = "specialist milestone"
    elif matched:
        reason = "CCU term without utilization context"
    else:
        reason = "no CCU term" + (" or milestone keyword" if specialist else "")
    return {
        "eligible": reason in ("CCU topic", "specialist milestone"),
        "reason": reason,
        "kind": kind,
        "event_lead": kind != "academic" and event,
        "priority": int(kind != "academic") * 2 + int(event),
    }


def source_text(article):
    # Avoid duplicate title in RSS descriptions and omit URL, dates and generated metadata from LLM input.
    summary = plain(article.summary).replace(article.title, "").strip()
    return article.title + ("\n" + summary[:900] if summary else "")


def cache_key(article, kind, model, endpoint, max_tokens):
    payload = {
        "article_id": article.article_id,
        "publication_date": str(article.publication_date),
        "source_url": str(article.canonical_url),
        "text": source_text(article),
        "source_kind": kind,
        "model": model,
        "endpoint": endpoint,
        "prompt_version": PROMPT_VERSION,
        "prompt_hash": prompt_hash("grounded"),
        "max_tokens": max_tokens,
        "temperature": 0,
        "thinking": "disabled",
        "validation_version": 3,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def validate_cached(record, text, evidence_id):
    evidence = Evidence.model_validate(record["evidence"])
    result = Analysis.model_validate(record["analysis"])
    if evidence.evidence_id != evidence_id:
        raise ValueError("Cache evidence mismatch")
    if evidence.content_sha256 != hashlib.sha256(text.encode()).hexdigest():
        raise ValueError("Cache source text mismatch")
    if result.proposed_events:
        raise ValueError("Cache cannot contain committed event records")
    for detail in [*result.technical_information, *result.economic_information, *result.milestone_proposals]:
        if not quote_supported(detail.quote, text):
            raise ValueError("Cache contains unsupported extraction")
        if getattr(detail, "event_date", None) and not date_supported(detail.event_date, text):
            raise ValueError("Cache contains unsupported event date")
    for claim in result.claims:
        if (
            claim.kind == "verified_fact"
            or claim.reviewer
            or claim.reviewed_at
            or not quote_supported(claim.text, text)
            or claim.evidence_ids != [evidence_id]
        ):
            raise ValueError("Cache contains unsupported claims")
    return result


def estimated_cost(usage):
    if usage.get("attempts", 0) and not usage.get("usage_reported"):
        return None
    return round(
        (
            usage.get("prompt_tokens", 0) * PRICING["input_usd_per_million"]
            + usage.get("completion_tokens", 0) * PRICING["output_usd_per_million"]
        )
        / 1_000_000,
        8,
    )


def write_draft(bundle, records, decisions, args):
    """Compose the seven-section draft from cited DeepSeek summaries; never approve it."""
    path = args.output / "draft.md"
    if path.exists():
        return path
    selected = [r for r in records if r.get("analysis") and r["analysis"]["relevant"]]
    created = datetime.now(UTC).isoformat()
    meta = dict(
        title=f"CCU Intelligence — research draft through {args.until}",
        issue_number=0,  # Human editor assigns publication numbering.
        editorial_status="draft", sample=False, publication_date=None,
        coverage_start=str(args.since), coverage_end=str(args.until + timedelta(days=1)),
        last_updated=created, source_count=len({r["evidence"]["url"] for r in selected}),
        featured_topics=sorted({d for r in selected for d in r["analysis"]["domains"]}),
        article_ids=[r["article_id"] for r in selected], executive_signal_ids=[], event_ids=[],
        reviewer=None, reviewed_at=None, watch_milestones=[],
        review_checklist={k: False for k in ("evidence", "technical", "economics", "climate", "rights")},
    )
    articles = {a.article_id: a for a in bundle.articles}
    lines = [
        "> DRAFT — AI proposals and source metadata only. Human review required; not published.",
        "", f"Coverage: {args.since} through {args.until} inclusive (UTC).", "",
        "Missing evidence stays unknown. Company/government reporting is attributed, not independent verification.",
    ]
    def citation(record):
        a = articles[record["article_id"]]
        return f"[{safe_text(a.source_id)}]({a.canonical_url}) — {a.publication_date}; evidence `{record['evidence']['evidence_id']}`."

    for heading in SECTIONS:
        lines += ["", "## " + heading, ""]
        group = selected[:3] if heading == "Executive Signals" else selected
        wrote = False
        for r in group:
            a = r["analysis"]
            content = []
            if heading in ("Executive Signals", "Industry Developments"):
                content = ["AI draft summary: " + safe_text(a["summary"])]
            elif heading == "Technology Spotlight":
                content = [safe_text(d["text"]) + " Uncertainty: " + safe_text(d["uncertainty"])
                           for d in a.get("technical_information", [])]
            elif heading == "Project Watch":
                content = [safe_text(d["event_type"]) + " proposal: " + safe_text(d["text"])
                           + " Event date: " + str(d["event_date"] or "unknown")
                           + ". Uncertainty: " + safe_text(d["uncertainty"])
                           for d in a.get("milestone_proposals", [])]
            elif heading == "Economics & Climate Reality Check":
                content = [safe_text(d["text"]) + " Uncertainty: " + safe_text(d["uncertainty"])
                           for d in a.get("economic_information", [])]
            elif heading == "Materials & Chemicals Connection" and a.get("industrial_implications"):
                content = ["AI interpretation: " + safe_text(a["industrial_implications"])]
            elif heading == "What to Watch Next":
                content = ["Verification needed: " + safe_text(a["uncertainty"])]
            if content:
                wrote = True
                lines += ["### " + safe_text(articles[r["article_id"]].title), "", *content,
                          "", citation(r), "", "Uncertainty: " + safe_text(a["uncertainty"]), ""]
        if not wrote:
            lines += ["No supported analysis available. Additional evidence and editorial review required."]
    lines += ["", "## Candidate inbox and limitations", "",
              "Coverage is bounded; unavailable sources and exact-date gaps are recorded in collection.json. "
              "No project events or human approvals are applied. Quotes and interpretations require original-source review.", ""]
    for article in bundle.articles:
        if decisions[article.article_id]["eligible"]:
            lines += [f"- [{safe_text(article.title)}]({article.canonical_url}) — {article.publication_date}. Metadata lead only."]
    path.write_text("---\n" + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True)
                    + "---\n\n" + "\n".join(lines) + "\n")
    validate_issue(path, bundle)
    return path


def execute(args):
    load_environment()
    args.dry_run = getattr(args, "dry_run", False) or not getattr(args, "allow_paid", False)
    args.max_spend_usd = getattr(args, "max_spend_usd", 0.50)
    args.rate_ceiling = getattr(args, "rate_ceiling", 1.20)
    args.source_limit = getattr(args, "source_limit", None)
    if args.source_limit is not None and not 1 <= args.source_limit <= 30:
        raise ValueError("Per-source candidate cap must be 1–30")
    limits = [(sid, args.source_limit or limit) for sid, limit in SOURCE_LIMITS]
    if not args.dry_run and os.getenv("GITHUB_ACTIONS") == "true":
        event = os.getenv("GITHUB_EVENT_NAME")
        trusted = os.getenv("GITHUB_REF") == "refs/heads/" + os.getenv("DEFAULT_BRANCH", "main")
        scheduled = event == "schedule" and os.getenv("CCU_ALLOW_SCHEDULED_PAID") == "true"
        if not trusted or (event != "workflow_dispatch" and not scheduled) or os.getenv("GITHUB_RUN_ATTEMPT") != "1":
            raise ValueError("Paid processing requires a trusted default-branch dispatch and first attempt")
    if not args.dry_run and not os.getenv("LLM_API_KEY"):
        raise ValueError("Paid processing requires LLM_API_KEY")
    if args.until > date.today() or args.since > args.until or (args.until - args.since).days != 13:
        raise ValueError("Use a completed 14-day inclusive collection window ending no later than today")
    if args.scheduled_publication and args.scheduled_publication <= args.until:
        raise ValueError("Scheduled publication must follow the coverage window")
    if not 0 <= args.max_analyses <= 30 or not 0 <= args.max_requests <= 60 or args.token_budget < 1:
        raise ValueError("Caps: <=30 new analyses, <=60 attempts and positive token budget")
    if not 256 <= args.max_output_tokens <= 2048:
        raise ValueError("Output tokens must be 256–2048")
    if not args.output.resolve().is_relative_to(Path("data/runtime").resolve()):
        raise ValueError("Output must stay private under data/runtime")
    model = os.getenv("LLM_MODEL", "")
    endpoint = os.getenv("LLM_BASE_URL", "").rstrip("/")
    if model != "deepseek-flash" or endpoint not in (
        "https://api.deepseek.com",
        "https://api.deepseek.com/v1",
    ):
        raise ValueError("This pricing/budget profile requires the official deepseek-flash endpoint")
    initial_budget = Budget(max_requests=0 if args.dry_run else args.max_requests,
                            max_tokens=args.token_budget, max_spend_usd=args.max_spend_usd,
                            usd_per_million_tokens=args.rate_ceiling)
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / ".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        config = {k: str(v) if isinstance(v, (Path, date)) else v for k, v in vars(args).items()}
        config.update(
            model=model,
            endpoint=endpoint,
            prompt_hash=prompt_hash("grounded"),
            sources=limits,
            source_registry_hash=hashlib.sha256(Path("config/sources.yaml").read_bytes()).hexdigest(),
        )
        config = json.loads(json.dumps(config))
        config_path = args.output / "config.json"
        if config_path.exists() and json.loads(config_path.read_text()) != config:
            raise ValueError("Existing run has different configuration; use another output directory")
        atomic_json(config_path, config)
        report_path = args.output / "report.json"
        if report_path.exists():
            report = json.loads(report_path.read_text())
            print(json.dumps({k: v for k, v in report.items() if k not in ("records", "triage")}, indent=2))
            return report
        ledger = args.output / "budget.json"
        budget = (
            Budget(**json.loads(ledger.read_text()), path=ledger)
            if ledger.exists()
            else initial_budget
        )
        budget.path = ledger
        budget.save()
        store = Store(args.output / "intelligence.sqlite")
        try:
            sources = {s.source_id: s for s in registry()}
            collection_file = args.output / "collection.json"
            collection = json.loads(collection_file.read_text()) if collection_file.exists() else {}
            for source, limit in limits:
                if source not in collection:
                    collection[source] = collect(
                        store, args.since, args.until, source, limit, '"carbon dioxide" utilization'
                    )
                    atomic_json(collection_file, collection)
            bundle = store.bundle()
            atomic_json(args.output / "bundle.json", bundle.model_dump(mode="json"))
            if len(bundle.articles) > sum(limit for _, limit in limits):
                raise ValueError("Candidate cap exceeded")
            decisions = {
                a.article_id: triage(a, sources[a.source_id], args.since, args.until) for a in bundle.articles
            }
            eligible = sorted(
                [a for a in bundle.articles if decisions[a.article_id]["eligible"]],
                key=lambda a: (-decisions[a.article_id]["priority"], a.article_id),
            )
            records = []
            # The durable attempt marker prevents crashes or reruns increasing the 30-article cap.
            attempted_path = args.output / "attempted.json"
            attempted = json.loads(attempted_path.read_text()) if attempted_path.exists() else []
            for article in eligible:
                kind = decisions[article.article_id]["kind"]
                text = source_text(article)
                eid = "metadata-" + article.article_id
                key = cache_key(article, kind, model, endpoint, args.max_output_tokens)
                cache = Path("data/runtime/llm-cache") / (key + ".json")
                result_path = args.output / (article.article_id + ".json")
                if result_path.exists():
                    record = json.loads(result_path.read_text())
                    if record.get("cache_key") != key:
                        raise ValueError("Saved result configuration mismatch")
                    if record.get("analysis"):
                        validate_cached(record, text, eid)
                    records.append(record)
                    continue
                if cache.exists():
                    record = json.loads(cache.read_text())
                    if record.get("cache_key") != key:
                        raise ValueError("Cache key mismatch")
                    validate_cached(record, text, eid)
                    record = record | {"cache_hit": True, "usage": {}, "estimated_cost_usd": 0.0}
                elif not args.dry_run and article.article_id not in attempted and len(attempted) < args.max_analyses and budget.requests < budget.max_requests:
                    attempted.append(article.article_id)
                    atomic_json(attempted_path, attempted)
                    evidence = Evidence(
                        evidence_id=eid,
                        source_id=article.source_id,
                        url=article.canonical_url,
                        publication_date=article.publication_date,
                        retrieved_at=article.retrieved_at,
                        locator="API/feed title and short description",
                        excerpt=text[:1200],
                        content_sha256=hashlib.sha256(text.encode()).hexdigest(),
                        license_note=sources[article.source_id].reuse_restrictions,
                    )
                    usage = {}
                    analysis = run(
                        "grounded",
                        text,
                        [eid],
                        usage=usage,
                        budget=budget,
                        max_tokens=args.max_output_tokens,
                        source_kind=kind,
                    )
                    record = {
                        "article_id": article.article_id,
                        "cache_key": key,
                        "cache_hit": False,
                        "model": model,
                        "prompt_version": PROMPT_VERSION,
                        "input": text,
                        "evidence": evidence.model_dump(mode="json"),
                        "usage": usage,
                        "estimated_cost_usd": estimated_cost(usage),
                        "analysis": analysis.model_dump(mode="json") if analysis else None,
                    }
                    if analysis:
                        validate_cached(record, text, eid)
                        atomic_json(cache, record)
                else:
                    continue
                atomic_json(result_path, record)
                records.append(record)
            draft = write_draft(bundle, records, decisions, args)
            usage = {
                k: sum(r["usage"].get(k, 0) for r in records)
                for k in (
                    "attempts",
                    "prompt_tokens",
                    "completion_tokens",
                    "total_tokens",
                    "prompt_cache_hit_tokens",
                )
            }
            report = {
                "collected_articles": len(bundle.articles),
                "candidate_records_considered": sum(c["considered"] for c in collection.values()),
                "coverage_by_source_kind": dict(
                    Counter(source_kind(sources[a.source_id]) for a in bundle.articles)
                ),
                "promising_candidates": len(eligible),
                "new_analyses_attempted": len(attempted),
                "new_analyses_validated": sum(bool(r["analysis"]) and not r["cache_hit"] for r in records),
                "cache_hits": sum(r["cache_hit"] for r in records),
                "dry_run": args.dry_run,
                "max_new_analyses": args.max_analyses,
                "max_spend_usd": args.max_spend_usd,
                "reserved_cost_usd": budget.reserved_cost_microusd / 1_000_000,
                "rate_ceiling_usd_per_million": args.rate_ceiling,
                "usage": usage,
                "requests_reserved": budget.requests,
                "tokens_charged_to_budget": budget.charged_tokens,
                "estimated_cost_usd": round(sum(r["estimated_cost_usd"] or 0 for r in records), 8),
                "cost_complete": all(r["estimated_cost_usd"] is not None for r in records),
                "pricing": PRICING,
                "draft": str(draft),
                "triage": decisions,
                "records": records,
            }
            atomic_json(report_path, report)
            print(json.dumps({k: v for k, v in report.items() if k not in ("records", "triage")}, indent=2))
            return report
        finally:
            store.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", type=date.fromisoformat, default=date.today() - timedelta(days=13))
    parser.add_argument("--until", type=date.fromisoformat, default=date.today())
    parser.add_argument("--scheduled-publication", type=date.fromisoformat)
    parser.add_argument("--output", type=Path, default=Path("data/runtime") / f"biweekly-{date.today()}")
    parser.add_argument("--max-analyses", type=int, default=30)
    parser.add_argument("--max-requests", type=int, default=60)
    parser.add_argument("--token-budget", type=int, default=120000)
    parser.add_argument("--max-output-tokens", type=int, default=1200)
    parser.add_argument("--source-limit", type=int, default=15)
    parser.add_argument("--dry-run", action="store_true", help="Collect and draft; zero paid requests")
    parser.add_argument("--allow-paid", action="store_true", help="Explicitly authorize bounded model calls")
    parser.add_argument("--max-spend-usd", type=float, default=0.50)
    parser.add_argument("--rate-ceiling", type=float, default=1.20,
                        help="Conservative USD per million tokens, at least the higher current peak price")
    execute(parser.parse_args())


if __name__ == "__main__":
    main()
