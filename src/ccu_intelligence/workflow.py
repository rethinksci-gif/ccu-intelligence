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
from .editorial import safe_text, validate_issue
from .llm import PROMPT_VERSION, prompt_hash, run
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
CCU = re.compile(
    r"\b(?:co2(?!\+)|carbon dioxide|ccu|ccus|carbon captur\w*|carbon minerali\w*|"
    r"e-methanol|electrofuels?|power.to.liquid|direct air capture)\b",
    re.I,
)
EVENT = re.compile(
    r"\b(?:fid|financ\w*|offtake|off.take|construct\w*|operat\w*|commission\w*|"
    r"delay\w*|cancel\w*|bankrupt\w*|investment decision|permit\w*)\b",
    re.I,
)
# Conservative peak cache-miss prices: upper estimate, not an invoice. Verified 2026-10-08.
PRICING = {
    "input_usd_per_million": 0.30,
    "output_usd_per_million": 1.20,
    "source": "https://api-docs.deepseek.com/quick_start/pricing/",
    "checked": "2026-10-08",
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
    eligible = matched or (specialist and bool(EVENT.search(text)))
    return {
        "eligible": eligible,
        "reason": "CCU topic / specialist milestone" if eligible else "no CCU topic",
        "kind": kind,
        "event_lead": kind != "academic" and bool(EVENT.search(text)),
        "priority": int(kind != "academic") * 2 + int(bool(EVENT.search(text))),
    }


def source_text(article):
    # Avoid duplicate title in RSS descriptions and omit URL, dates and generated metadata from LLM input.
    summary = plain(article.summary).replace(article.title, "").strip()
    return article.title + ("\n" + summary[:900] if summary else "")


def cache_key(article, kind, model, endpoint, max_tokens):
    payload = {
        "article_id": article.article_id,
        "text": source_text(article),
        "source_kind": kind,
        "model": model,
        "endpoint": endpoint,
        "prompt_version": PROMPT_VERSION,
        "prompt_hash": prompt_hash("grounded"),
        "max_tokens": max_tokens,
        "temperature": 0,
        "thinking": "disabled",
        "validation_version": 2,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def validate_cached(record, text, evidence_id):
    evidence = Evidence.model_validate(record["evidence"])
    result = Analysis.model_validate(record["analysis"])
    if evidence.evidence_id != evidence_id:
        raise ValueError("Cache evidence mismatch")
    for claim in result.claims:
        if (
            claim.kind == "verified_fact"
            or claim.reviewer
            or claim.reviewed_at
            or claim.text not in text
            or len(claim.text.split()) > 25
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
    path = args.output / f"draft-{date.today()}.md"
    if path.exists():
        return path  # preserve editorial edits
    selected = [r for r in records if r.get("analysis") and r["analysis"]["relevant"]]
    created = datetime.now(UTC).isoformat()
    meta = dict(
        title="CCU Intelligence — Issue 001 preparation",
        issue_number=1,
        editorial_status="draft",
        sample=False,
        publication_date=None,
        scheduled_publication_date=str(args.scheduled_publication) if args.scheduled_publication else None,
        collection_date=date.today().isoformat(),
        collection_cutoff=str(args.until),
        draft_created_at=created,
        last_updated=created,
        coverage_start=str(args.since),
        coverage_end=str(args.until + timedelta(days=1)),
        coverage_end_exclusive=True,
        source_count=len({r["evidence"]["url"] for r in selected}),
        featured_topics=sorted({d for r in selected for d in r["analysis"]["domains"]}),
        article_ids=[r["article_id"] for r in selected],
        reviewer=None,
        reviewed_at=None,
    )
    lines = [
        "# CCU Intelligence — editorial draft",
        "",
        f"Coverage: {args.since} through {args.until} (inclusive). Collected: {date.today()}.",
        "",
        f"Scheduled publication: {args.scheduled_publication or 'not scheduled'}. "
        "Not published. This is preparation for Issue 001, not a completed issue.",
        "",
        "## Evidence status",
        "",
        "Source-supported facts here are limited to the existence and content of retrieved titles and "
        "dated feed/API records. Source assertions are attributed, not independently verified. "
        "No human-verified technical performance, project milestones or economics are established. "
        "AI interpretation is labeled separately. Research papers are not commercialization events.",
        "",
    ]
    articles = {a.article_id: a for a in bundle.articles}
    for kind, heading in [
        ("nonacademic", "Industrial and policy reporting"),
        ("academic", "Research papers"),
    ]:
        lines += ["## " + heading, ""]
        group = [
            r for r in selected if (decisions[r["article_id"]]["kind"] == "academic") == (kind == "academic")
        ]
        if not group:
            lines += ["No eligible source-supported items in this bounded run.", ""]
        for r in group:
            article = articles[r["article_id"]]
            a = r["analysis"]
            lines += [
                f"### {safe_text(article.title)}",
                "",
                f"[{article.source_id}]({article.canonical_url}) — source-reported publication date: "
                f"{article.publication_date}. Evidence `{r['evidence']['evidence_id']}`.",
                "",
                "The retrieved source reports the topic stated in the title above. "
                "Any performance or commercial claim in that title remains unverified.",
                "",
                "**AI technical interpretation:** " + safe_text(a["technical_significance"] or "Unknown"),
                "",
                "**AI industrial interpretation:** " + safe_text(a["industrial_implications"] or "Unknown"),
                "",
                "**Uncertainty:** " + safe_text(a["uncertainty"]),
                "",
            ]
    lines += [
        "## Editorial follow-up",
        "",
        "Review primary documents and corroborate project identity, event date, demonstrated scale, "
        "FID/offtake status, construction and operation independently. Do not equate announcements "
        "with operation or capture with permanent removal. No automatic project events were applied.",
        "",
        "## Coverage limitations",
        "",
        "At most 20 candidate records across eight sources; at most five new model analyses. "
        "Feeds may be stale or incomplete. Undated/updated-only entries and unrelated polymer, "
        "energy or optical-conversion items are excluded before paid analysis. "
        "No full research papers were retrieved. No quantitative cost or climate conclusion is supported.",
        "",
    ]
    path.write_text(
        "---\n" + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True) + "---\n\n" + "\n".join(lines)
    )
    validate_issue(path, bundle)
    return path


def execute(args):
    load_environment()
    if args.until > date.today() or args.since > args.until or (args.until - args.since).days != 13:
        raise ValueError("Use a completed 14-day inclusive collection window ending no later than today")
    if args.scheduled_publication and args.scheduled_publication <= args.until:
        raise ValueError("Scheduled publication must follow the coverage window")
    if not 0 <= args.max_analyses <= 5 or not 0 <= args.max_requests <= 8 or args.token_budget < 1:
        raise ValueError("Pilot caps: <=5 analyses, <=8 requests and positive token budget")
    if not 256 <= args.max_output_tokens <= 1200:
        raise ValueError("Output tokens must be 256–1200")
    if not args.output.resolve().is_relative_to(Path("data/runtime").resolve()):
        raise ValueError("Output must stay private under data/runtime")
    model = os.getenv("LLM_MODEL", "")
    endpoint = os.getenv("LLM_BASE_URL", "").rstrip("/")
    if model != "deepseek-flash" or endpoint not in (
        "https://api.deepseek.com",
        "https://api.deepseek.com/v1",
    ):
        raise ValueError("This pricing/budget profile requires the official deepseek-flash endpoint")
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / ".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        config = {k: str(v) if isinstance(v, (Path, date)) else v for k, v in vars(args).items()}
        config.update(
            model=model,
            endpoint=endpoint,
            prompt_hash=prompt_hash("grounded"),
            sources=SOURCE_LIMITS,
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
            else Budget(max_requests=args.max_requests, max_tokens=args.token_budget, path=ledger)
        )
        store = Store(args.output / "intelligence.sqlite")
        try:
            sources = {s.source_id: s for s in registry()}
            collection_file = args.output / "collection.json"
            collection = json.loads(collection_file.read_text()) if collection_file.exists() else {}
            for source, limit in SOURCE_LIMITS:
                if source not in collection:
                    collection[source] = collect(
                        store, args.since, args.until, source, limit, '"carbon dioxide" utilization'
                    )
                    atomic_json(collection_file, collection)
            bundle = store.bundle()
            atomic_json(args.output / "bundle.json", bundle.model_dump(mode="json"))
            if len(bundle.articles) > 20:
                raise ValueError("Candidate cap exceeded")
            decisions = {
                a.article_id: triage(a, sources[a.source_id], args.since, args.until) for a in bundle.articles
            }
            eligible = sorted(
                [a for a in bundle.articles if decisions[a.article_id]["eligible"]],
                key=lambda a: (-decisions[a.article_id]["priority"], a.article_id),
            )
            records = []
            # The durable attempt marker prevents crashes or reruns increasing the five-article cap.
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
                    records.append(json.loads(result_path.read_text()))
                    continue
                if cache.exists():
                    record = json.loads(cache.read_text())
                    validate_cached(record, text, eid)
                    record = record | {"cache_hit": True, "usage": {}, "estimated_cost_usd": 0.0}
                elif len(attempted) < args.max_analyses and budget.requests < budget.max_requests:
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
                "legacy_cache_note": "Pilot 1 uses a different prompt/schema and cannot pass v2 quote validation; not reused.",
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
    parser.add_argument("--max-analyses", type=int, default=5)
    parser.add_argument("--max-requests", type=int, default=8)
    parser.add_argument("--token-budget", type=int, default=24000)
    parser.add_argument("--max-output-tokens", type=int, default=700)
    execute(parser.parse_args())


if __name__ == "__main__":
    main()
