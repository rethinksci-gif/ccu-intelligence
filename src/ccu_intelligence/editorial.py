"""Anchored 14-day windows, citation-aware drafts, and explicit publication gates."""

import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import yaml

from .models import Article, Bundle, ClaimKind, RealityAssumptions
from .reality import methanol

ANCHOR = date(2026, 1, 5)  # UTC Monday; coverage windows are [start, end), no overlap
SECTIONS = [
    "Executive Signals",
    "Industry Developments",
    "Technology Spotlight",
    "Project Watch",
    "Economics & Climate Reality Check",
    "Materials & Chemicals Connection",
    "What to Watch Next",
]


def window(as_of: date) -> tuple[date, date]:
    end = ANCHOR + timedelta(days=((as_of - ANCHOR).days // 14) * 14)
    return end - timedelta(days=14), end


def safe_text(text: str) -> str:
    # Markdown output is data, never arbitrary HTML/MDX or embedded remote media.
    text = re.sub(r"<[^>]*>", "", text).replace("\n", " ")
    return re.sub(r"([\\`*_{}\[\]#!|])", r"\\\1", text)


def eligible(article: Article, bundle: Bundle) -> bool:
    evidence = {e.evidence_id: e for e in bundle.evidence}
    return bool(
        not article.sample
        and article.editorial_status == "reviewed"
        and not article.review_required
        and article.claims
        and all(
            c.evidence_ids
            and c.reviewer
            and c.reviewed_at
            and c.kind != ClaimKind.UNVERIFIED
            and all(i in evidence and not evidence[i].sample for i in c.evidence_ids)
            for c in article.claims
        )
    )


def generate(bundle: Bundle, as_of: date, output: Path, sample: bool = False) -> Path:
    start, end = window(as_of)
    output.mkdir(parents=True, exist_ok=True)
    target = output / f"{end}.md"
    if target.exists():
        return target  # preserve editorial changes on reruns
    selected = [
        a
        for a in bundle.articles
        if a.publication_date
        and start <= a.publication_date < end
        and (a.sample if sample else eligible(a, bundle))
    ]
    selected.sort(key=lambda a: (-(a.overall_score or 0), a.article_id))
    selected = selected[:6]
    evidence = {e.evidence_id: e for e in bundle.evidence}
    sources = sorted({str(evidence[e].url) for a in selected for c in a.claims for e in c.evidence_ids})
    events = [e for e in bundle.events if start <= e.reporting_date < end and e.sample == sample][:3]
    meta = dict(
        title=("Sample issue — " if sample else "CCU Intelligence — ") + str(end),
        issue_number=max(1, (end - ANCHOR).days // 14 + 1),
        publication_date=str(end),
        coverage_start=str(start),
        coverage_end=str(end),
        featured_topics=["Industrial readiness", "Methanol"],
        source_count=len(sources),
        editorial_status="sample" if sample else "draft",
        last_updated=datetime.now(UTC).isoformat(),
        sample=sample,
        article_ids=[a.article_id for a in selected],
        executive_signal_ids=[a.article_id for a in selected[:3]],
        event_ids=[e.event_id for e in events],
        reviewer=None,
        reviewed_at=None,
        review_checklist={
            "evidence": False,
            "technical": False,
            "economics": False,
            "climate": False,
            "rights": False,
        },
        watch_milestones=[],
        reality_check={
            "functional_unit": "1 tonne methanol",
            "system_boundary": "Purchased feedstocks and process electricity",
            "reference_scenario": "Assumed fossil methanol price, USD 350/t",
            "geography": "Illustrative, no regional claim",
            "data_year": 2026,
            "assumptions": "USD 80/t CO2, USD 3/kg H2, USD 50/MWh, 1 MWh/t process electricity; 90% CO2 and 95% H2 utilization",
            "source_confidence": "Theoretical mass balance; scenario prices are assumptions",
            "limitations": "Not a full TEA or LCA",
        },
    )
    lines = [
        "---",
        yaml.safe_dump(meta, sort_keys=False).strip(),
        "---",
        "",
        "> SAMPLE — fictional demonstration, not industry news."
        if sample
        else "> DRAFT — requires human editorial review; not published.",
        "",
        f"Coverage: {start} to {end} (end exclusive, UTC).",
        "",
        "## Executive Signals",
        "",
    ]
    for a in selected[:3]:
        lines += [
            f"### {safe_text(a.title)}",
            f"What happened: {safe_text(a.summary)}",
            f"What changed / why it matters: {safe_text(a.industrial_implications or 'Needs editorial assessment.')}",
            f"Uncertainty: {safe_text(a.uncertainty)} [Original source]({a.canonical_url})",
            "",
        ]
    if len(selected) < 3:
        lines += [
            "Insufficient reviewed evidence for three signals. Do not fill the gap with unverified stories.",
            "",
        ]
    lines += ["## Industry Developments", ""]
    for a in selected:
        lines += [
            f"### {safe_text(a.title)}",
            f"Event: {a.event_date or 'not established'} · Published: {a.publication_date} · Organization: {', '.join(a.organization_ids) or 'unresolved'} · Domains: {', '.join(a.domains)}",
            "",
            safe_text(a.summary),
        ]
        for c in a.claims:
            refs = " ".join(f"[Evidence]({evidence[eid].url})" for eid in c.evidence_ids)
            lines += [f"- **{c.kind.value.replace('_', ' ')}:** {safe_text(c.text)} {refs}"]
        lines += [
            f"Technical significance: {safe_text(a.technical_significance or 'Needs editorial assessment.')}",
            f"Industrial implications: {safe_text(a.industrial_implications or 'Needs editorial assessment.')}",
            f"Uncertainty: {safe_text(a.uncertainty)} [Original source]({a.canonical_url})",
            "",
        ]
    lines += [
        "## Technology Spotlight",
        "",
        "### CO₂-to-methanol",
        "",
        "CO₂ + 3 H₂ → CH₃OH + H₂O",
        "",
        "Process: purified CO₂ + hydrogen → compression → catalytic synthesis → condensation → distillation → methanol; unreacted gas recycles with a purge.",
        "",
        "The theoretical mass balance is approximately 1.374 t CO₂ and 0.189 t H₂ per tonne of methanol. Actual feed use depends on conversion, selectivity, losses and recycle. Energy must cover feed preparation, compression and separation. A generic reaction has no single project TRL; require named equipment, scale and run duration. [Process reference](https://www.irena.org/publications/2021/Jan/Innovation-Outlook-Renewable-Methanol)",
        "",
        "Editorial task: establish catalyst, operating conditions, performance and demonstrated scale from the selected evidence; distinguish reported results from models.",
        "",
        "## Project Watch",
        "",
        "| Project | Event | Date | Change |",
        "| --- | --- | --- | --- |",
    ]
    for event in events:
        # Relative links survive GitHub Pages base paths.
        lines += [
            f"| [{event.project_id}](../../projects/{event.project_id}/) | {event.event_type} | {event.event_date or 'Unknown'} | {safe_text(event.description)} |"
        ]
    if not events:
        lines += [
            "",
            "No reviewed project updates in this window. Announced and operational capacity must remain separate.",
        ]
    result = methanol(RealityAssumptions())
    lines += [
        "",
        "## Economics & Climate Reality Check",
        "",
        f"Illustrative partial cost: **USD {result['partial_cost_usd_per_t']:.0f}/t methanol**, versus an assumed USD 350/t fossil benchmark. This is a scenario comparison, not a market quotation or minimum selling price.",
        "",
        "Functional unit: 1 t methanol. Boundary: purchased CO₂, H₂ and process electricity only. Geography: unspecified scenario. Data year: 2026 scenario, not observed prices. Assumptions: USD 80/t CO₂, USD 3/kg H₂, USD 50/MWh; 1 MWh/t process electricity; 90% CO₂ and 95% H₂ utilization. Confidence: stoichiometry is theoretical; prices and utilization are illustrative. Excludes capital recovery, fixed OPEX, heat, water, logistics and margins. Purchased H₂ already includes its production cost. No net-GHG conclusion follows. [Assessment guidance](https://assessccus.globalco2initiative.org/)",
        "",
        "## Materials & Chemicals Connection",
        "",
        "Procurement analysis should compare product specifications, contracted delivery, feedstock traceability and independently supported footprint boundaries. A supply announcement does not demonstrate product qualification or continuous delivery. Identify the specific implications for polymer feedstocks, materials circularity and sourcing in editorial review.",
        "",
        "## What to Watch Next",
        "",
        "Editorial task: add three evidence-linked, falsifiable milestones with named projects, deadlines and disconfirmation criteria. Do not turn an announced startup into a prediction of successful operation.",
        "",
        "## References",
        *[f"- {url}" for url in sources],
        "",
    ]
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def read_issue(path: Path) -> tuple[dict, str]:
    text = path.read_text()
    if not text.startswith("---\n"):
        raise ValueError("Missing issue frontmatter")
    _, frontmatter, body = text.split("---", 2)
    return yaml.safe_load(frontmatter), body


def validate_issue(path: Path, bundle: Bundle):
    meta, body = read_issue(path)
    required = {
        "title",
        "issue_number",
        "publication_date",
        "coverage_start",
        "coverage_end",
        "featured_topics",
        "source_count",
        "editorial_status",
        "last_updated",
    }
    if not required.issubset(meta):
        raise ValueError("Missing required issue metadata")
    if meta["editorial_status"] == "research_published":
        if (
            meta.get("sample")
            or not meta.get("publication_date")
            or not str(meta.get("publication_authorization", "")).strip()
        ):
            raise ValueError("Research publication requires explicit authorization and a date")
        date.fromisoformat(str(meta["publication_date"]))
        if "RESEARCH EDITION" not in body or "full editorial review remains incomplete" not in body:
            raise ValueError("Research publication must disclose incomplete editorial review")
        return
    if meta["editorial_status"] != "published":
        return
    if meta.get("sample") or not meta.get("reviewer") or not meta.get("reviewed_at"):
        raise ValueError("Publication requires a reviewer and cannot contain samples")
    if any(
        meta.get("review_checklist", {}).get(k) is not True
        for k in ["evidence", "technical", "economics", "climate", "rights"]
    ):
        raise ValueError("Editorial review checklist is incomplete")
    selected = [a for a in bundle.articles if a.article_id in meta.get("article_ids", [])]
    if (
        not 4 <= len(selected) <= 6
        or len(selected) != len(set(meta.get("article_ids", [])))
        or not all(eligible(a, bundle) for a in selected)
    ):
        raise ValueError("Published issue needs 4–6 reviewed, evidence-backed developments")
    signals = meta.get("executive_signal_ids", [])
    if (
        len(signals) != 3
        or len(set(signals)) != 3
        or not set(signals).issubset({a.article_id for a in selected})
    ):
        raise ValueError("Three distinct executive signals must reference selected developments")
    start, end = (
        date.fromisoformat(str(meta["coverage_start"])),
        date.fromisoformat(str(meta["coverage_end"])),
    )
    if (end - start).days != 14 or any(
        not a.publication_date or not start <= a.publication_date < end for a in selected
    ):
        raise ValueError("Invalid publication window")
    if (
        any(f"## {s}" not in body for s in SECTIONS)
        or "Editorial task:" in body
        or "Needs editorial assessment" in body
    ):
        raise ValueError("Incomplete issue sections")
    if not 1000 <= len(body.split()) <= 1800:
        raise ValueError("Published issue must target a 5–8 minute read (1000–1800 words)")
    events = [e for e in bundle.events if e.event_id in meta.get("event_ids", [])]
    if (
        not 2 <= len(events) <= 3
        or len(events) != len(set(meta.get("event_ids", [])))
        or any(e.sample or not start <= e.reporting_date < end for e in events)
    ):
        raise ValueError("Project Watch needs 2–3 real event records")
    milestones = meta.get("watch_milestones", [])
    if len(milestones) != 3 or any(
        not all(m.get(k) for k in ["hypothesis", "deadline", "evidence_url", "disconfirmation"])
        for m in milestones
    ):
        raise ValueError("Three falsifiable, dated milestones are required")
    for milestone in milestones:
        if date.fromisoformat(str(milestone["deadline"])) < end:
            raise ValueError("Watch milestone deadline precedes the reporting window end")
        from pydantic import HttpUrl, TypeAdapter

        TypeAdapter(HttpUrl).validate_python(milestone["evidence_url"])
    if not all(
        meta.get("reality_check", {}).get(k)
        for k in [
            "functional_unit",
            "system_boundary",
            "reference_scenario",
            "geography",
            "data_year",
            "assumptions",
            "source_confidence",
            "limitations",
        ]
    ):
        raise ValueError("Reality Check context is incomplete")
    urls = {
        str(e.url)
        for e in bundle.evidence
        if any(e.evidence_id in c.evidence_ids for a in selected for c in a.claims)
    }
    if meta["source_count"] != len(urls) or any(url not in body for url in urls):
        raise ValueError("Source count or citations mismatch")
