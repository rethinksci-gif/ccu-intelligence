"""Conservative deterministic triage. No extracted numbers are promoted to facts."""

import re
from functools import lru_cache
from pathlib import Path

import yaml

from .models import Article, Company, Scores
from .scoring import score


@lru_cache(maxsize=8)
def _taxonomy(path: str, mtime_ns: int) -> dict[str, list[str]]:
    return yaml.safe_load(Path(path).read_text())


def taxonomy(path: Path = Path("config/taxonomy.yaml")) -> dict[str, list[str]]:
    # Keyed on absolute path and mtime so edits and working-directory changes are honoured.
    resolved = path.resolve()
    return _taxonomy(str(resolved), resolved.stat().st_mtime_ns)


def analyze(article: Article, companies: list[Company]) -> Article:
    text = (article.title + " " + article.summary).casefold()
    domains = [domain for domain, terms in taxonomy().items() if any(term in text for term in terms)]
    ids = []
    for company in companies:
        if any(
            re.search(r"(?<!\w)" + re.escape(alias.casefold()) + r"(?!\w)", text)
            for alias in [company.name, *company.aliases]
        ):
            ids.append(company.company_id)
    impact = (
        4
        if any(
            t in text
            for t in ["cancel", "suspend", "financing", "investment decision", "commission", "delay"]
        )
        else 2
    )
    values = dict(
        industrial_relevance=impact,
        technical_significance=3 if "conversion" in domains else 2,
        economic_implications=impact,
        climate_relevance=2,
        evidence_quality=1,
        novelty=2,
    )
    rationales = {k: "Conservative metadata-only triage; requires source and analyst review." for k in values}
    rationales["industrial_relevance"] = (
        "Project milestone or adverse development keyword detected."
        if impact == 4
        else "Industrial relevance not established from metadata."
    )
    scores = Scores(**values, rationales=rationales)
    return article.model_copy(
        update={
            "domains": domains,
            "organization_ids": ids,
            "scores": scores,
            "overall_score": score(scores),
            "review_required": True,
        }
    )


def event_candidates(article: Article) -> list[dict]:
    keywords = {
        "CANCELLED": ["cancelled", "canceled"],
        "SUSPENDED": ["suspended"],
        "STARTUP_DELAYED": ["delayed", "postponed"],
        "FID_REACHED": ["final investment decision"],
        "CONSTRUCTION_STARTED": ["construction started", "broke ground"],
        "COMMISSIONED": ["commissioned"],
        "OPERATIONAL": ["began operations", "started operations"],
        "FINANCING_SECURED": ["financing secured", "raised"],
        "FEED_STARTED": ["feed study"],
        "ANNOUNCED": ["announced"],
        "CAPACITY_EXPANDED": ["expanded capacity"],
    }
    text = (article.title + " " + article.summary).lower()
    return [
        {
            "event_type": kind,
            "article_id": article.article_id,
            "organization_ids": article.organization_ids,
            "status": "unverified proposal",
            "event_date": None,
            "uncertainty": "Keyword match may be negated, planned, or unrelated. Resolve project and dates manually.",
        }
        for kind, words in keywords.items()
        if any(w in text for w in words)
    ]
