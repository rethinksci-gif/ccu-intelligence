"""Bounded AI assistance for private drafts; never approves source claims."""

import hashlib
import json
from datetime import date
from pathlib import Path

from .editorial import generate, safe_text, window
from .llm import run
from .models import Bundle, Evidence
from .scoring import score


def generate_ai(bundle: Bundle, as_of: date, output: Path, article_id: str) -> Path:
    # Keep AI proposals outside the website and preserve existing editorial work.
    private = Path("data/runtime").resolve()
    if not output.resolve().is_relative_to(private):
        raise ValueError("AI drafts must be under data/runtime")
    start, end = window(as_of)
    target = output / f"{end}.md"
    if target.exists():
        return target
    article = next(a for a in bundle.articles if a.article_id == article_id)
    if article.sample or not article.publication_date or not start <= article.publication_date < end:
        raise ValueError("Choose a real collected article within the coverage window")
    text = json.dumps(
        {
            "title": article.title,
            "url": str(article.canonical_url),
            "publication_date": str(article.publication_date),
            "summary": article.summary,
            "scope": "Collected metadata only; full text and results have NOT been verified.",
        }
    )
    evidence = Evidence(
        evidence_id="metadata-" + article.article_id,
        source_id=article.source_id,
        url=article.canonical_url,
        retrieved_at=article.retrieved_at,
        publication_date=article.publication_date,
        locator="Collected article title and metadata",
        excerpt=article.title[:1200],
        content_sha256=hashlib.sha256(text.encode()).hexdigest(),
        license_note="Bibliographic metadata only; no publisher abstract or full text redistributed.",
    )
    usage = {}
    analysis = run("extraction", text, [evidence.evidence_id], usage=usage)
    output.mkdir(parents=True, exist_ok=True)
    report = {
        "article_id": article_id,
        "evidence": evidence.model_dump(mode="json"),
        "input": json.loads(text),
        "extraction_usage": usage,
        "deterministic_scores": article.scores.model_dump() if article.scores else None,
        "deterministic_overall_score": article.overall_score,
    }
    report_path = output / f"{end}.analysis.json"
    report_path.write_text(json.dumps(report, indent=2))
    if analysis is None:
        raise RuntimeError("AI extraction unavailable; inspect private usage report")
    report["analysis"] = analysis.model_dump(mode="json")
    report["ai_overall_score"] = score(analysis.scores) if analysis.scores else None
    narrative_usage = {}
    narrative = run(
        "newsletter",
        text + "\nValidated proposal (not human reviewed):\n" + analysis.model_dump_json(),
        [evidence.evidence_id],
        usage=narrative_usage,
    )
    report["newsletter_usage"] = narrative_usage
    report["newsletter"] = narrative.model_dump(mode="json") if narrative else None
    report_path.write_text(json.dumps(report, indent=2))
    if narrative is None:
        raise RuntimeError("AI newsletter unavailable; extraction saved for review")
    target = generate(bundle, as_of, output)
    with target.open("a") as f:
        f.write("\n## AI-assisted research lead — UNVERIFIED, NOT FOR PUBLICATION\n\n")
        f.write(
            "Sample AI-assisted draft using real collected metadata; no fictional news added. "
            "No human-reviewed current news was available. Full text, technical performance, "
            "costs, TRL and project milestones remain unverified or missing. "
            "The economics scenario above is illustrative, not observed data.\n\n"
        )
        f.write(
            f"### {safe_text(article.title)}\n\n[Collected source]({article.canonical_url}) "
            f"— publication date reported by {article.source_id}: {article.publication_date}.\n\n"
        )
        f.write(safe_text(narrative.summary) + "\n\n")
        for claim in narrative.claims:
            f.write(
                f"- **Unreviewed {claim.kind.value}:** {safe_text(claim.text)} "
                f"[Source]({evidence.url}). Uncertainty: {safe_text(claim.uncertainty)}\n"
            )
        f.write(
            "\nTechnical extraction (unreviewed): "
            + safe_text(analysis.technical_significance or "Unknown")
            + "\n"
        )
        f.write("\nUncertainty: " + safe_text(analysis.uncertainty) + "\n")
    return target
