# Data dictionary and invariants

Canonical schemas are in `src/ccu_intelligence/models.py`. All models reject unknown fields and non-finite numbers. Nullable means unavailable; it never implies zero.

| Record | Identity and important relationships |
| --- | --- |
| Source | `source_id`; endpoint/access policy, retrieval state, reliability and rights |
| Company | `company_id`; aliases resolve articles, separate from projects |
| Article | Stable DOI/canonical-URL digest; source, dates, fingerprint, claims and scores |
| Evidence | `evidence_id`; URL, locator, retrieval time, rights and optional raw hash |
| Claim | `claim_id`; category, evidence IDs, uncertainty and human review metadata |
| Project | `project_id`; company FK, current snapshot, evidence and nullable metrics |
| ProjectEvent | `event_id`; project FK, previous/new values, dates and evidence IDs |
| Technology | `technology_id`; chemistry, process, performance, references and limitations |

Python uses `co2_source`, `technology_trl`, `capex`, `opex`, and `lca_evidence` for the corresponding uppercase/Unicode fields in the brief. Values retain their units and meaning. IDs and URL slugs are stable; display names may change. Article DOI matching is case-insensitive. Exact fingerprints catch identical normalized title/body copies; near-duplicates require review.

`Capacity` stores `value`, `unit`, `basis`, `substance`, and `evidence_ids`. Bases are `co2_input`, `co2_captured`, `co2_converted`, or `product_output`. Units are explicit: t/year, kg/hour or t/day. The UI filters by identical basis/product/unit and does not silently annualize hourly/day rates or sum unlike products.

`Metric` stores a value, unit, basis, provenance, evidence and assumptions. Provenance is `reported_measurement`, `modeled_result`, `analyst_estimate`, or `theoretical`. A field name alone never establishes provenance. Capture efficiency, purity, Faradaic efficiency, selectivity, lifetime and energy demand can be stored as named/based metrics; do not compare different boundaries.

Project startup forecasts are strings to preserve reporting precision (year, quarter or full date). Actual startup and event/reporting dates use ISO dates or null when unknown. `reporting_date` is not substituted for an unknown `event_date`.

SQLite is version 1, with normalized entity tables and validated JSON payloads. Events are append-only via triggers. The public JSON export is a complete, reference-validated bundle built only from checked-in curated files. It includes sample flags and no source API credentials. `last_successful_retrieval` starts null in registry configuration and is updated in SQLite source state after successful parsing; `status` exposes retrieval success and failure history.

Scoring normalizes 1–5 values with `100 × Σ(weight × (rating−1)/4)`. All 1s give 0, all 5s give 100. Each dimension needs a rationale. Metadata-only heuristic scores carry evidence quality 1 and never clear review requirements. Low-evidence/high-impact claims are explicitly detectable with `needs_review`.


The project tracker supports evidence-confidence, data-availability and source-check-date filters, along with name/date sorting and capacity sorting within an explicitly selected comparable group. Accent-insensitive, word-order-independent search recognizes CO2/CO₂ and Kasso/Kassø. Filters and sorting are retained in the URL. Filtered JSON exports preserve null values and include selected project records, company display names and the active filters; evidence IDs refer to the full curated JSON export. Project detail evidence registers include references used by metrics, climate claims, LCA and historical events as well as the baseline sources. These changes do not add or upgrade project facts.
