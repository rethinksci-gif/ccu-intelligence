"""Render the research draft. Text is escaped model paraphrase; every claim carries a source link."""

from datetime import UTC, datetime, timedelta

import yaml

from .editorial import safe_text
from .models import NOT_STATED

TABLE = [("Route / catalyst", ("conversion_route", "catalyst")), ("Product", ("product",)),
         ("CO2 source", ("co2_source",)), ("TRL / scale", ("trl", "scale")), ("Energy input", ("energy_input",)),
         ("Cost / economics", ("cost_economics",)), ("LCA claims", ("lca_claims",))]
BASIS_NOTE = {"full_text": "", "abstract": "abstract only", "headline": "headline only"}


def cite(item: dict) -> str:
    label = f"{item['source_name']}, {item['publication_date']}"
    notes = [n for n in ("news report" if item["evidence_role"] == "news" else "",
                         BASIS_NOTE[item["input_basis"]], "editor-submitted" if item.get("editor_submitted") else "")
             if n]
    return f"[{safe_text(label)}]({item['url']})" + (f" ({'; '.join(notes)})" if notes else "")


def cited(text: str, ids: list[str], items: dict) -> str:
    return safe_text(text) + " — " + "; ".join(cite(items[i]) for i in ids)


def cell(fields: dict, names: tuple[str, ...]) -> str:
    values = [fields[n]["value"] for n in names if fields[n]["value"] != NOT_STATED]
    text = "; ".join(values) or "n.s."
    return safe_text(text if len(text) <= 140 else text[:137] + "…")


def story_item(entries: list[dict]) -> dict:
    """One item per story: the lead's full brief, then what changed for each related item."""
    lead, rest = entries[0], entries[1:]
    paragraphs = [{"text": lead["enrichment"][b], "source_ids": [lead["sid"]]}
                  for b in ("what_changed", "why_it_matters", "practical_implication") if lead["enrichment"][b]]
    paragraphs += [{"text": e["enrichment"]["what_changed"], "source_ids": [e["sid"]]} for e in rest]
    return {"source_ids": [e["sid"] for e in entries], "headline": lead["enrichment"]["headline"],
            "paragraphs": paragraphs, "limitation": None}


def deterministic_sections(selected: list[dict], order: list[str]) -> list[dict]:
    """Fallback when synthesis is unavailable: the verified briefs, grouped by category and story."""
    sections = []
    for category in order:
        stories: dict[str, list[dict]] = {}
        for e in selected:
            if e.get("story_category", e["category"]) == category:
                stories.setdefault(e.get("story", e["sid"]), []).append(e)
        if stories:
            sections.append({"category": category, "intro": None,
                             "items": [story_item(entries) for entries in stories.values()]})
    return sections


def limitation(item: dict, items: dict) -> str | None:
    """The model's one-line limitation, or a default from the input basis of the item's sources."""
    if item.get("limitation"):
        return item["limitation"]
    bases = {items[i]["input_basis"] for i in item["source_ids"]}
    roles = {items[i]["evidence_role"] for i in item["source_ids"]}
    if bases == {"headline"}:
        return "Headline only; content not reviewed."
    if bases == {"abstract"}:
        return "Abstract only; results beyond the abstract are unknown."
    if roles == {"news"}:
        return "Secondary news reports; not yet confirmed by a primary source."
    return None


def headline_list(entries: list[dict]) -> list[str]:
    return [f"- [{safe_text(b['title'])}]({b['url']}) — {safe_text(b['source_name'])}, {b['publication_date']}"
            + (" (news report)" if b["evidence_role"] == "news" else "")
            + (" (editor-submitted)" if b.get("editor_submitted") else "") + "." for b in entries]


def render(*, args, meta_counts: dict, config: dict, selected: list[dict], synthesis: dict | None,
           takeaway_entries: list[dict], briefs: list[dict], also: dict, notes: list[str],
           pending: list[dict], inbox: list[dict], also_research: list[dict] = (),
           also_other: list[dict] = ()) -> str:
    items = {e["sid"]: e for e in selected}
    names = {k: c["name"] for k, c in config["categories"].items()}
    order = list(config["categories"])
    created = datetime.now(UTC).isoformat()
    meta = dict(
        title=(synthesis or {}).get("title") or f"CCU Intelligence — research draft through {args.until}",
        issue_number=0,  # Human editor assigns publication numbering.
        editorial_status="draft", sample=False, publication_date=None,
        coverage_start=str(args.since), coverage_end=str(args.until + timedelta(days=1)),
        last_updated=created, source_count=len({e["url"] for e in selected}),
        featured_topics=[names[c] for c in order if any(e["category"] == c for e in selected)],
        article_ids=[e["article_id"] for e in selected], executive_signal_ids=[], event_ids=[],
        reviewer=None, reviewed_at=None, watch_milestones=[],
        review_checklist={k: False for k in ("evidence", "technical", "economics", "climate", "rights")},
    )
    lines = [
        "> DRAFT — AI-assisted research draft from verified model briefs. Human review required; not published.",
        "> Text is our paraphrase with short attributed quotes; follow each link for the original source.",
        "",
        f"Coverage: {args.since} through {args.until} inclusive (UTC). Screened {meta_counts['screened']} of "
        f"{meta_counts['collected']} collected items; {len(selected)} selected after scoring, deduplication, "
        "caps and verification.",
        "",
    ]
    if synthesis:  # plain prose; every claim is cited in the item sections below
        lines += [f"*{safe_text(synthesis['dek']['text'])}*", ""]
    lines += ["## Key takeaways", ""]
    if synthesis and synthesis["takeaways"]:
        lines += [f"- {cited(t['text'], t['source_ids'], items)}" for t in synthesis["takeaways"]]
    elif takeaway_entries:
        lines += [f"- **{safe_text(names[e['category']])}:** "
                  + cited(e["enrichment"]["what_changed"], [e["sid"]], items) for e in takeaway_entries]
    elif not meta_counts["screened"]:
        lines += ["No model analysis in this run (dry run, cap or budget); see the candidate inbox below."]
    else:
        lines += ["No development met the decision-value threshold in this window."]
    sections = (synthesis or {}).get("sections") or deterministic_sections(selected, order)
    covered = {i for s in sections for item in s["items"] for i in item["source_ids"]}
    missing = [e for e in selected if e["sid"] not in covered]
    if missing:  # synthesis omitted verified items: keep them, using their verified brief
        story_items = {items[i].get("story"): item for s in sections for item in s["items"] for i in item["source_ids"]}
        for entry in [e for e in missing if e.get("story") in story_items]:  # join their story's item
            item = story_items[entry["story"]]
            item["source_ids"].append(entry["sid"])
            item["paragraphs"].append({"text": entry["enrichment"]["what_changed"], "source_ids": [entry["sid"]]})
        extra = deterministic_sections([e for e in missing if e.get("story") not in story_items], order)
        by_category = {s["category"]: s for s in sections}
        for section in extra:
            if section["category"] in by_category:
                by_category[section["category"]]["items"] += section["items"]
            else:
                sections.append(section)
    sections.sort(key=lambda s: order.index(s["category"]))
    for section in sections:
        lines += ["", f"## {safe_text(names[section['category']])}", ""]
        if section.get("intro"):
            lines += [cited(section["intro"]["text"], section["intro"]["source_ids"], items), ""]
        for item in section["items"]:
            lines += [f"### {safe_text(item['headline'])}", ""]
            for paragraph in item["paragraphs"]:
                lines += [cited(paragraph["text"], paragraph["source_ids"], items), ""]
            if note := limitation(item, items):
                lines += [f"*{safe_text(note)}*", ""]
            for sid in item["source_ids"]:
                for dup in also.get(items[sid]["article_id"], []):
                    lines += [f"Also reported: [{safe_text(dup['title'])}]({dup['url']}) — "
                              f"{safe_text(dup['source_name'])}, {dup['publication_date']}.", ""]
    if selected:
        lines += ["", "## Technology and economics at a glance", "",
                  "Values come from the verified fact sheets; n.s. = not stated in the supplied material.", "",
                  "| Development | " + " | ".join(h for h, _ in TABLE) + " | Source |",
                  "| --- " * (len(TABLE) + 2) + "|"]
    for entry in sorted(selected, key=lambda e: order.index(e["category"])):
        fields = entry["enrichment"]["fields"]
        lines += ["| " + safe_text(entry["enrichment"]["headline"]) + " | "
                  + " | ".join(cell(fields, n) for _, n in TABLE) + f" | {cite(entry)} |"]
    if synthesis and synthesis["watch_next"]:
        lines += ["", "## What to watch", ""]
        lines += [f"- {cited(w['text'], w['source_ids'], items)}" for w in synthesis["watch_next"]]
    lines += ["", "## CCU ecosystem briefs", "",
              "Relevant news from CCU-specialist companies and associations that was not selected. Headline and "
              "link only; not summarised.", ""]
    lines += headline_list(briefs) or ["No ecosystem briefs in this window."]
    if also_research:
        lines += ["", "## Also noted in research", "",
                  "Relevant papers not selected (category cap or below the threshold). Headline and link only.", ""]
        lines += headline_list(also_research)
    if also_other:
        lines += ["", "## Also noted in industry and policy", "",
                  "Relevant news, company and policy items not selected. Headline and link only.", ""]
        lines += headline_list(also_other)
    lines += ["", "## Editor notes", ""]
    lines += [f"- {safe_text(n)}" for n in notes] or ["- None recorded."]
    if pending:
        lines += ["- Not included because verification was unavailable or removed the core claim: "
                  + "; ".join(f"[{safe_text(p['title'])}]({p['url']})" for p in pending) + "."]
    lines += ["", "## Sources", ""]
    for number, entry in enumerate(sorted(selected, key=lambda e: e["sid"]), 1):
        lines += [f"{number}. {cite(entry)} — {safe_text(entry['title'])}. Score {entry['score']:g}/10; "
                  f"input: {entry['input_basis'].replace('_', ' ')}."]
    lines += ["", "## Candidate inbox and limitations", "",
              "Coverage is bounded by per-source caps; failed sources and exact-date gaps are in collection.json. "
              "News reports are secondary and never primary evidence. No project events or human approvals are "
              "applied. Verify quotes and numbers against the original before publication.", ""]
    lines += [f"- [{safe_text(i['title'])}]({i['url']}) — {i['publication_date']}. {safe_text(i['status'])}."
              for i in inbox]
    return "---\n" + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True) + "---\n\n" + "\n".join(lines) + "\n"
