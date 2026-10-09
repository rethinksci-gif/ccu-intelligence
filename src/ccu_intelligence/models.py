"""Strict, portable records. Unknown quantities remain null, never zero-filled."""

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ClaimKind(StrEnum):
    FACT = "verified_fact"
    COMPANY = "company_reported_claim"
    MODEL = "model_derived_interpretation"
    ANALYST = "analyst_inference"
    UNVERIFIED = "unverified_information"


class Evidence(Record):
    evidence_id: str
    source_id: str
    url: HttpUrl
    retrieved_at: datetime
    publication_date: date | None = None
    locator: str = Field(min_length=1)
    excerpt: str = Field(max_length=1200)
    content_sha256: str | None = None
    license_note: str
    sample: bool = False


class Claim(Record):
    claim_id: str
    text: str = Field(min_length=1)
    kind: ClaimKind = ClaimKind.UNVERIFIED
    evidence_ids: list[str] = Field(default_factory=list)
    uncertainty: str = Field(min_length=1)
    reviewer: str | None = None
    reviewed_at: datetime | None = None

    @model_validator(mode="after")
    def verified_requires_review(self):
        if self.kind == ClaimKind.FACT and not (self.evidence_ids and self.reviewer and self.reviewed_at):
            raise ValueError("Verified facts require evidence and an identified human review")
        return self


class Metric(Record):
    value: float
    unit: str = Field(min_length=1)
    basis: str = Field(min_length=1)
    provenance: Literal["reported_measurement", "modeled_result", "analyst_estimate", "theoretical"]
    evidence_ids: list[str] = Field(default_factory=list)
    assumptions: str


class Capacity(Record):
    value: float = Field(ge=0)
    unit: Literal["t/year", "kg/hour", "t/day"]
    basis: Literal["co2_input", "co2_captured", "co2_converted", "product_output"]
    substance: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)


class Company(Record):
    company_id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    country: str | None = None
    website: HttpUrl | None = None
    watchlist_only: bool = True
    sample: bool = False


class Source(Record):
    source_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    organization: str
    source_type: str
    base_url: HttpUrl
    access_method: Literal["crossref", "openalex", "rss", "federal_register", "gdelt", "govuk_search", "manual",
                           "editor_list"]
    endpoint: HttpUrl | None = None
    update_frequency: str
    reliability_tier: Literal[1, 2, 3]
    last_successful_retrieval: datetime | None = None
    reuse_restrictions: str
    active: bool = True
    automated_access_approved: bool = False
    minimum_interval_seconds: float = Field(default=1, ge=1)
    limitation: str | None = None
    # Research run: sources with a run_limit are collected, at most that many in-window items each.
    run_limit: int | None = Field(default=None, ge=1, le=30)
    # Fetch the linked page (robots.txt permitting) and extract main text for the model.
    content_extractor: Literal["trafilatura"] | None = None
    # News search results are secondary reporting, never primary evidence.
    evidence_role: Literal["primary", "news"] = "primary"
    query: str | None = None
    filters: str | None = None  # extra OpenAlex filter clause, e.g. open_access.is_oa:true
    pages: int = Field(default=1, ge=1, le=25)  # WordPress feed pages (?paged=N); paging stops at the window start
    # Broad feeds: only items whose title or summary matches this case-insensitive regex count toward run_limit.
    include_pattern: str | None = None


class Project(Record):
    project_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    project_name: str
    company: str  # foreign key to Company.company_id
    country: str | None
    region: str
    location: str | None
    co2_source: str | None
    capture_technology: str | None
    conversion_pathway: str | None
    primary_product: str | None
    development_status: str
    technology_trl: int | None = Field(ge=1, le=9)
    announced_capacity: Capacity | None
    operational_capacity: Capacity | None
    capacity_units: str | None
    expected_startup_date: str | None  # preserves year/quarter precision as reported
    actual_startup_date: date | None
    capex: Metric | None
    opex: Metric | None
    energy_requirements: list[Metric] = Field(default_factory=list)
    hydrogen_requirements: list[Metric] = Field(default_factory=list)
    climate_claims: list[Claim] = Field(default_factory=list)
    lca_evidence: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    date_last_verified: date | None
    confidence_level: Confidence
    limitations: str
    sample: bool = False


EventType = Literal[
    "ANNOUNCED",
    "FEED_STARTED",
    "FID_REACHED",
    "FINANCING_SECURED",
    "CONSTRUCTION_STARTED",
    "COMMISSIONED",
    "OPERATIONAL",
    "CAPACITY_EXPANDED",
    "STARTUP_DELAYED",
    "SUSPENDED",
    "CANCELLED",
    "OFFTAKE_SIGNED",
    "UPDATED",
]


class ProjectEvent(Record):
    event_id: str
    project_id: str
    event_type: EventType
    event_date: date | None
    reporting_date: date
    previous_value: dict[str, Any]
    new_value: dict[str, Any]
    description: str
    evidence_links: list[str] = Field(min_length=1)
    confidence_level: Confidence
    sample: bool = False


class Technology(Record):
    technology_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    technology_name: str
    pathway_category: str
    chemical_reactions: list[str]
    feedstocks: list[str]
    products: list[str]
    catalysts: list[str]
    process_conditions: str
    process_flow: list[str]
    technical_performance: list[Metric]
    current_trl: int | None = Field(ge=1, le=9)
    demonstrated_scale: str
    known_limitations: list[str]
    reference_projects: list[str]
    economics: str
    lifecycle_evidence: str
    references: list[HttpUrl] = Field(min_length=1)
    last_updated: date


class Scores(Record):
    industrial_relevance: int = Field(ge=1, le=5)
    technical_significance: int = Field(ge=1, le=5)
    economic_implications: int = Field(ge=1, le=5)
    climate_relevance: int = Field(ge=1, le=5)
    evidence_quality: int = Field(ge=1, le=5)
    novelty: int = Field(ge=1, le=5)
    rationales: dict[str, str]

    @model_validator(mode="after")
    def all_rationales(self):
        for key in type(self).model_fields:
            if key != "rationales" and not self.rationales.get(key):
                raise ValueError(f"Missing scoring rationale: {key}")
        return self


class Article(Record):
    article_id: str
    source_id: str
    canonical_url: HttpUrl
    title: str = Field(min_length=1)
    publication_date: date | None
    source_updated_date: date | None = None
    event_date: date | None = None
    retrieved_at: datetime
    doi: str | None = None
    content_fingerprint: str
    summary: str = ""
    organization_ids: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    scores: Scores | None = None
    overall_score: float | None = Field(default=None, ge=0, le=100)
    review_required: bool = True
    editorial_status: Literal["candidate", "reviewed", "rejected"] = "candidate"
    technical_significance: str | None = None
    industrial_implications: str | None = None
    uncertainty: str = "Source metadata alone does not establish industrial readiness."
    sample: bool = False


class GroundedDetail(Record):
    text: str = Field(min_length=1, max_length=400)
    quote: str = Field(min_length=1, max_length=500)
    uncertainty: str = Field(min_length=1, max_length=300)


class GroundedMilestone(GroundedDetail):
    event_type: EventType
    project_name: str | None = None
    event_date: date | None = None


class Analysis(Record):
    technical_information: list[GroundedDetail] = Field(default_factory=list, max_length=3)
    economic_information: list[GroundedDetail] = Field(default_factory=list, max_length=3)
    milestone_proposals: list[GroundedMilestone] = Field(default_factory=list, max_length=3)
    scores: Scores | None = None
    relevant: bool
    domains: list[str]
    claims: list[Claim]
    summary: str
    technical_significance: str | None = None
    industrial_implications: str | None = None
    uncertainty: str
    proposed_events: list[ProjectEvent] = Field(default_factory=list)


class RealityAssumptions(Record):
    co2_usd_per_t: float = Field(default=80, ge=0, le=10000)
    h2_usd_per_kg: float = Field(default=3, ge=0, le=100)
    electricity_usd_per_mwh: float = Field(default=50, ge=0, le=10000)
    process_mwh_per_t: float = Field(default=1, ge=0, le=100)
    co2_utilization: float = Field(default=0.9, gt=0, le=1)
    h2_utilization: float = Field(default=0.95, gt=0, le=1)
    fossil_benchmark_usd_per_t: float = Field(default=350, ge=0, le=10000)
    geography: str = "User-defined scenario; no regional price claim"
    data_year: int = Field(default=2026, ge=1900, le=2200)


class Bundle(Record):
    companies: list[Company] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    events: list[ProjectEvent] = Field(default_factory=list)
    technologies: list[Technology] = Field(default_factory=list)
    articles: list[Article] = Field(default_factory=list)

    @model_validator(mode="after")
    def relationships(self):
        for field, id_field in [
            ("companies", "company_id"),
            ("evidence", "evidence_id"),
            ("projects", "project_id"),
            ("events", "event_id"),
            ("technologies", "technology_id"),
            ("articles", "article_id"),
        ]:
            ids = [getattr(x, id_field) for x in getattr(self, field)]
            if len(ids) != len(set(ids)):
                raise ValueError(f"Duplicate identifiers in {field}")
        companies = {c.company_id for c in self.companies}
        evidence = {e.evidence_id: e for e in self.evidence}
        projects = {p.project_id: p for p in self.projects}

        def refs(ids, sample):
            if any(i not in evidence for i in ids):
                raise ValueError("Unresolved evidence reference")
            if not sample and any(evidence[i].sample for i in ids):
                raise ValueError("Production records cannot cite sample evidence")

        for p in self.projects:
            if p.company not in companies:
                raise ValueError("Unknown company")
            refs(p.sources + p.lca_evidence, p.sample)
            for c in p.climate_claims:
                refs(c.evidence_ids, p.sample)
            for m in [
                p.announced_capacity,
                p.operational_capacity,
                p.capex,
                p.opex,
                *p.energy_requirements,
                *p.hydrogen_requirements,
            ]:
                if m:
                    refs(m.evidence_ids, p.sample)
        for e in self.events:
            if e.project_id not in projects or e.sample != projects[e.project_id].sample:
                raise ValueError("Event must match an existing project's sample status")
            refs(e.evidence_links, e.sample)
        for a in self.articles:
            if not set(a.organization_ids).issubset(companies):
                raise ValueError("Unknown article organization")
            for c in a.claims:
                refs(c.evidence_ids, a.sample)
            if a.editorial_status == "reviewed" and (a.review_required or not a.claims):
                raise ValueError("Reviewed articles need claims and a cleared review flag")
        for t in self.technologies:
            if not set(t.reference_projects).issubset(projects):
                raise ValueError("Unknown technology reference project")
            for m in t.technical_performance:
                refs(m.evidence_ids, False)
        return self


class GroundedProposal(Record):
    """Small LLM wire format: source quotations and explicitly separate interpretation.

    No verified-fact or reviewer fields are offered to the model. Existing Claim
    validation remains authoritative after conversion to Analysis.
    """

    draft_summary: str = Field(default="", max_length=700)
    technical_information: list[GroundedDetail] = Field(default_factory=list, max_length=3)
    economic_information: list[GroundedDetail] = Field(default_factory=list, max_length=3)
    milestone_proposals: list[GroundedMilestone] = Field(default_factory=list, max_length=3)
    relevant: bool
    domains: list[str] = Field(max_length=4)
    quotes: list[str] = Field(max_length=2)
    technical_significance: str = Field(max_length=500)
    industrial_implications: str = Field(max_length=500)
    uncertainty: str = Field(min_length=1, max_length=400)


# --- Two-stage research wire formats (untrusted model output, validated and grounded after parsing) ---------

NOT_STATED = "not stated in the supplied material"
CCU_FIELDS = (
    "co2_source",
    "conversion_route",
    "catalyst",
    "product",
    "trl",
    "scale",
    "energy_input",
    "cost_economics",
    "lca_claims",
    "partners",
    "location",
    "milestones",
)
class Wire(Record):
    """Model output: unknown extra keys are dropped rather than failing validation (no facts are added by them)."""

    model_config = ConfigDict(extra="ignore")


class WireDetail(GroundedDetail):
    model_config = ConfigDict(extra="ignore")


class WireMilestone(GroundedMilestone):
    model_config = ConfigDict(extra="ignore")


EvidenceType = Literal[
    "original_research",
    "review_article",
    "company_announcement",
    "government_document",
    "news_report",
    "association_update",
    "market_report",
    "compilation",
    "other",
]


class Screening(Wire):
    """Stage 1: relevance gate, 0–10 decision-value score, category and tags."""

    ccu_relevant: bool
    relevance_reason: str = Field(min_length=1, max_length=500)
    score: float = Field(ge=0, le=10)
    reason: str = Field(min_length=1, max_length=700)
    category: str = Field(min_length=1, max_length=60)
    tags: list[str] = Field(min_length=1, max_length=5)
    summary: str = Field(min_length=1, max_length=500)
    evidence_type: EvidenceType
    # Named projects/plants and organizations the item is about; used to group related items into one story.
    projects: list[str] = Field(default_factory=list, max_length=8)
    organizations: list[str] = Field(default_factory=list, max_length=10)


class SourcedValue(Wire):
    value: str = Field(default=NOT_STATED, min_length=1, max_length=400)
    quote: str | None = Field(default=None, max_length=500)


class CCUFields(Wire):
    co2_source: SourcedValue = SourcedValue()
    conversion_route: SourcedValue = SourcedValue()
    catalyst: SourcedValue = SourcedValue()
    product: SourcedValue = SourcedValue()
    trl: SourcedValue = SourcedValue()
    scale: SourcedValue = SourcedValue()
    energy_input: SourcedValue = SourcedValue()
    cost_economics: SourcedValue = SourcedValue()
    lca_claims: SourcedValue = SourcedValue()
    partners: SourcedValue = SourcedValue()
    location: SourcedValue = SourcedValue()
    milestones: SourcedValue = SourcedValue()


class Enrichment(Wire):
    """Stage 2: decision brief (four blocks, <=180 words) plus grounded CCU fields."""

    headline: str = Field(min_length=1, max_length=160)
    # Date of the main development, only when written explicitly in the source (checked after parsing).
    event_date: date | None = None
    what_changed: str = Field(min_length=1, max_length=1000)
    why_it_matters: str | None = Field(default=None, max_length=800)
    practical_implication: str | None = Field(default=None, max_length=800)
    next_action: str | None = Field(default=None, max_length=500)
    fields: CCUFields = CCUFields()
    technical_information: list[WireDetail] = Field(default_factory=list, max_length=4)
    economic_information: list[WireDetail] = Field(default_factory=list, max_length=4)
    milestone_proposals: list[WireMilestone] = Field(default_factory=list, max_length=4)
    quotes: list[str] = Field(default_factory=list, max_length=3)
    uncertainty: str = Field(min_length=1, max_length=600)


class VerificationCheck(Wire):
    id: str = Field(min_length=1, max_length=60)
    verdict: Literal["supported", "partially_supported", "unsupported"]
    problem: str = Field(default="", max_length=600)
    corrected_text: str | None = Field(default=None, max_length=1000)


class VerificationResult(Wire):
    checks: list[VerificationCheck] = Field(max_length=120)
    overall_note: str = Field(default="", max_length=800)


class DedupResult(Wire):
    groups: list[list[str]] = Field(default_factory=list, max_length=60)  # the identical event
    stories: list[list[str]] = Field(default_factory=list, max_length=30)  # same project/company, related events


class Cited(Wire):
    text: str = Field(min_length=1, max_length=1600)
    source_ids: list[str] = Field(min_length=1, max_length=8)


class SynthesisItem(Wire):
    source_ids: list[str] = Field(min_length=1, max_length=8)
    headline: str = Field(min_length=1, max_length=180)
    paragraphs: list[Cited] = Field(min_length=1, max_length=4)
    limitation: str | None = Field(default=None, max_length=300)  # one short line on what the source leaves open


class SynthesisSection(Wire):
    category: str = Field(min_length=1, max_length=60)
    intro: Cited | None = None
    items: list[SynthesisItem] = Field(min_length=1, max_length=12)


class Synthesis(Wire):
    title: str = Field(min_length=1, max_length=180)
    dek: Cited
    takeaways: list[Cited] = Field(default_factory=list, max_length=5)
    sections: list[SynthesisSection] = Field(default_factory=list, max_length=8)
    watch_next: list[Cited] = Field(default_factory=list, max_length=6)
    editor_notes: list[str] = Field(default_factory=list, max_length=20)
