"""Create explicitly fictional demonstration fixtures and public reference material."""

import json
from pathlib import Path

import yaml

watch = [
    ("Svante", "https://svanteinc.com"),
    ("Carbon Clean", "https://www.carbonclean.com"),
    ("Climeworks", "https://climeworks.com"),
    ("SLB Capturi", "https://www.capturi.slb.com"),
    ("Twelve", "https://www.twelve.co"),
    ("Dioxycle", "https://dioxycle.com"),
    ("Oxylus Energy", "https://www.oxylusenergy.com"),
    ("Carbon Recycling International", "https://www.carbonrecycling.com"),
    ("Liquid Wind", "https://www.liquidwind.com"),
    ("HIF Global", "https://hifglobal.com"),
    ("LanzaTech", "https://lanzatech.com"),
    ("Covestro", "https://www.covestro.com"),
    ("CarbonCure", "https://www.carboncure.com"),
    ("CarbonBuilt", "https://carbonbuilt.com"),
    ("CarbiCrete", "https://carbicrete.com"),
]
companies = [
    {
        "company_id": n.lower().replace(" ", "-"),
        "name": n,
        "website": u,
        "watchlist_only": True,
        "sample": False,
    }
    for n, u in watch
]
sources = []
for sid, org, url, method, endpoint, tier in [
    ("crossref", "Crossref", "https://www.crossref.org", "crossref", "https://api.crossref.org/works", 2),
    ("openalex", "OpenAlex", "https://openalex.org", "openalex", "https://api.openalex.org/works", 2),
    (
        "iea",
        "IEA CCUS Projects Database",
        "https://www.iea.org/data-and-statistics/data-product/ccus-projects-database",
        "manual",
        None,
        1,
    ),
    ("co2-value-europe", "CO2 Value Europe", "https://co2value.eu", "manual", None, 2),
    ("global-co2", "Global CO2 Initiative", "https://www.globalco2initiative.org", "manual", None, 1),
    ("netl", "US DOE / NETL", "https://netl.doe.gov", "manual", None, 1),
    ("doe-funding", "US Department of Energy funding", "https://www.energy.gov", "manual", None, 1),
    ("nature-energy", "Nature Energy", "https://www.nature.com/nenergy/", "manual", None, 2),
    ("chemical-engineering", "Chemical Engineering", "https://www.chemengonline.com", "manual", None, 3),
]:
    sources.append(
        dict(
            source_id=sid,
            organization=org,
            source_type="scholarly_metadata" if method != "manual" else "reference_or_publisher",
            base_url=url,
            access_method=method,
            endpoint=endpoint,
            update_frequency="daily" if method != "manual" else "biweekly manual review",
            reliability_tier=tier,
            last_successful_retrieval=None,
            reuse_restrictions="Metadata only; do not republish publisher abstracts or full text."
            if method != "manual"
            else "Review page-specific license before reuse; link and paraphrase only.",
            active=True,
            automated_access_approved=method != "manual",
            minimum_interval_seconds=1,
            limitation=None
            if method != "manual"
            else "No automated adapter approved; use manual ingestion. Availability and rights require review.",
        )
    )
for c in companies:
    sources.append(
        dict(
            source_id=c["company_id"],
            organization=c["name"],
            source_type="company_announcements_and_annual_reports",
            base_url=c["website"],
            access_method="manual",
            update_frequency="biweekly manual review",
            reliability_tier=3,
            last_successful_retrieval=None,
            reuse_restrictions="Company claims are not independent verification. Link to original; do not copy reports.",
            active=True,
            automated_access_approved=False,
            limitation="Monitoring candidate; specific IR/report URL and automation rights not verified.",
        )
    )
Path("config/sources.yaml").write_text(yaml.safe_dump({"sources": sources}, sort_keys=False))
Path("data/curated/companies.json").write_text(json.dumps({"companies": companies}, indent=2))

projects, events, evidence, articles, sample_companies = [], [], [], [], []
scenarios = [
    (
        "northport-methanol",
        "Northport Methanol Demonstrator",
        "Example Nordic Chemicals",
        "Sweden",
        "Europe",
        "CO₂ hydrogenation",
        "Methanol",
        "FEED",
        6,
        12000,
        None,
        "2028",
        "FEED_STARTED",
    ),
    (
        "riverbend-carbonate",
        "Riverbend Carbonate Pilot",
        "Example Mineral Systems",
        "United States",
        "North America",
        "Mineralization",
        "Carbonate aggregate",
        "PILOT",
        5,
        2500,
        500,
        "2027",
        "CAPACITY_EXPANDED",
    ),
    (
        "eastbay-electrolysis",
        "Eastbay Electrolysis Pilot",
        "Example Electrochemical Works",
        "China",
        "China",
        "Electrochemical reduction",
        "Carbon monoxide",
        "STARTUP_DELAYED",
        5,
        1000,
        None,
        "2029",
        "STARTUP_DELAYED",
    ),
    (
        "coastal-polyol",
        "Coastal Polyol Demonstrator",
        "Example Polymer Research",
        "Japan",
        "Other",
        "Copolymerization",
        "Polyol",
        "ANNOUNCED",
        None,
        None,
        None,
        None,
        "ANNOUNCED",
    ),
]
for idx, (
    pid,
    name,
    company,
    country,
    region,
    pathway,
    product,
    status,
    trl,
    announced,
    operational,
    startup,
    event_type,
) in enumerate(scenarios):
    cid, eid = f"sample-company-{idx}", f"sample-evidence-{idx}"
    sample_companies.append(dict(company_id=cid, name=company, watchlist_only=False, sample=True))
    evidence.append(
        dict(
            evidence_id=eid,
            source_id="sample-fixture",
            url=f"https://example.org/ccu-fixtures/{pid}",
            retrieved_at="2026-10-04T10:00:00Z",
            publication_date="2026-10-02",
            locator="Fictional test record",
            excerpt="Fictional data created to exercise software behavior; no real-world claim.",
            license_note="Original synthetic fixture",
            sample=True,
        )
    )

    def cap(value):
        return (
            None
            if value is None
            else dict(
                value=value, unit="t/year", basis="product_output", substance=product, evidence_ids=[eid]
            )
        )

    projects.append(
        dict(
            project_id=pid,
            project_name=name,
            company=cid,
            country=country,
            region=region,
            location=None,
            co2_source="Fictional industrial point source",
            capture_technology=None,
            conversion_pathway=pathway,
            primary_product=product,
            development_status=status,
            technology_trl=trl,
            announced_capacity=cap(announced),
            operational_capacity=cap(operational),
            capacity_units="t/year product output" if announced else None,
            expected_startup_date=startup,
            actual_startup_date=None,
            capex=None,
            opex=None,
            energy_requirements=[],
            hydrogen_requirements=[],
            climate_claims=[],
            lca_evidence=[],
            sources=[eid],
            date_last_verified=None,
            confidence_level="low",
            limitations="SAMPLE: entirely fictional; figures and statuses are for interface testing only.",
            sample=True,
        )
    )
    events.append(
        dict(
            event_id=f"sample-event-{idx}",
            project_id=pid,
            event_type=event_type,
            event_date="2026-10-01",
            reporting_date="2026-10-02",
            previous_value={"expected_startup_date": "2027"}
            if idx == 2
            else {"development_status": "ANNOUNCED"},
            new_value={"expected_startup_date": "2029"} if idx == 2 else {"development_status": status},
            description="Fictional startup moved from 2027 to 2029."
            if idx == 2
            else f"Fictional {event_type.lower().replace('_', ' ')} milestone.",
            evidence_links=[eid],
            confidence_level="low",
            sample=True,
        )
    )
    articles.append(
        dict(
            article_id=f"sample-article-{idx}",
            source_id="sample-fixture",
            canonical_url=f"https://example.org/ccu-fixtures/{pid}",
            title=[
                "Sample: engineering study precedes investment decision",
                "Sample: pilot capacity differs from announced expansion",
                "Sample: startup delay changes the delivery outlook",
                "Sample: polymer announcement lacks operating data",
            ][idx],
            publication_date="2026-10-02",
            event_date="2026-10-01",
            retrieved_at="2026-10-04T10:00:00Z",
            content_fingerprint=f"sample-{idx}",
            summary="Fictional development used to demonstrate evidence-aware editorial review.",
            organization_ids=[cid],
            domains=["commercialization"],
            claims=[
                dict(
                    claim_id=f"sample-claim-{idx}",
                    text="This fictional project illustrates an editorial distinction, not a verified industrial development.",
                    kind="unverified_information",
                    evidence_ids=[eid],
                    uncertainty="Sample data only.",
                )
            ],
            overall_score=75 - idx * 5,
            review_required=True,
            editorial_status="candidate",
            technical_significance="Reported scale must be linked to the specific operating system.",
            industrial_implications="Engineering, finance and offtake must be evaluated separately.",
            uncertainty="No real-world inference is possible from this sample.",
            sample=True,
        )
    )
Path("data/curated/samples.json").write_text(
    json.dumps(
        dict(
            companies=sample_companies, projects=projects, events=events, evidence=evidence, articles=articles
        ),
        indent=2,
    )
)

# data/curated/technologies.json is maintained directly as a reviewed reference file;
# reseeding must not overwrite the curated pathway profiles.
