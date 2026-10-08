"""Literal metric discovery, with no automatic interpretation of process boundaries."""

import re
from datetime import datetime
from typing import Literal

from pydantic import HttpUrl

from .models import Article, Record


class MetricCandidate(Record):
    article_id: str
    original_url: HttpUrl
    retrieved_at: datetime
    reported_value: str
    reported_unit: str
    context: str
    basis: str | None = None
    verification_status: Literal["unverified_information"] = "unverified_information"
    limitation: str = (
        "Literal text match only. Confirm meaning, unit basis, negation and evidence before use."
    )


PATTERN = re.compile(
    r"(?<![\w.])(?P<value>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<unit>USD/t(?:\s*CO[₂2])?|USD/kg|USD|MWh/t|kWh/kg|t/year|t/yr|tonnes/year|kg/hour|%|hours?)(?!\w)",
    re.IGNORECASE,
)


def extract_metrics(article: Article) -> list[MetricCandidate]:
    text = article.title + " " + article.summary
    return [
        MetricCandidate(
            article_id=article.article_id,
            original_url=article.canonical_url,
            retrieved_at=article.retrieved_at,
            reported_value=m["value"],
            reported_unit=m["unit"],
            context=text[max(0, m.start() - 70) : m.end() + 70],
        )
        for m in PATTERN.finditer(text)
    ]
