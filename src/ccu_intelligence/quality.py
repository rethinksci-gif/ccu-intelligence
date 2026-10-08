"""Publication boundary: working candidates cannot leak into public exports."""

from .editorial import eligible
from .models import Bundle, ClaimKind


def validate_public(bundle: Bundle) -> None:
    companies = {c.company_id: c for c in bundle.companies}
    for a in bundle.articles:
        if not a.sample and not eligible(a, bundle):
            raise ValueError(f"Unreviewed article in public curated data: {a.article_id}")
    for p in bundle.projects:
        if p.sample:
            continue
        if companies[p.company].sample or not p.sources or not p.date_last_verified:
            raise ValueError(
                f"Live project requires real company, evidence and verification date: {p.project_id}"
            )
        for m in [
            p.announced_capacity,
            p.operational_capacity,
            p.capex,
            p.opex,
            *p.energy_requirements,
            *p.hydrogen_requirements,
        ]:
            if m and not m.evidence_ids:
                raise ValueError(f"Unsupported project metric: {p.project_id}")
        for claim in p.climate_claims:
            if (
                not claim.evidence_ids
                or not claim.reviewer
                or not claim.reviewed_at
                or claim.kind == ClaimKind.UNVERIFIED
            ):
                raise ValueError(f"Unreviewed climate claim: {p.project_id}")
