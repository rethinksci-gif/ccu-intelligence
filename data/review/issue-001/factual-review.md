# Issue 001 factual review — 9 October 2026

**Decision: not ready to merge for publication. Keep PR #1 as a draft.** This is an AI-assisted factual review, not human editorial approval. No reviewer identity or checklist approval has been supplied. No website, automation or publication-gate code is changed.

## Blocking corrections made

1. **Research scope:** The original [Crossref record](https://api.crossref.org/works/10.26434/chemrxiv.15009603/v1) identifies the item as `posted-content`, subtype `preprint`; the abstract describes a literature review of CoPc-mediated CO₂/CO reduction. Corrected the issue so it cannot be read as reporting a new experimental demonstration. Both `posted` and `published` are 29 September 2026. The [DOI](https://doi.org/10.26434/chemrxiv.15009603/v1) resolves to ChemRxiv, but the full-text request returned HTTP 403. No full-text performance claim or peer-reviewed successor is verified.
2. **Evidence provenance:** Added a source-linked bibliographic claim and an evidence record with locator, retrieval timestamp and SHA-256 of the original Crossref response to the review-only candidate bundle. The abstract is paraphrased, not redistributed. Candidate status and human-review requirements remain intact. The single source count corresponds to its evidence URL; background links are not counted as approved developments.
3. **Model evidence quality:** Clarified that earlier DeepSeek screening examined title-level metadata and short supplied excerpts. Its `validated` status denotes output checks, not scientific verification. Missing facts in an excerpt cannot establish their absence from the original source. No paid model calls were made during this review.
4. **Economic provenance:** Re-ran the unchanged calculator. Result: USD 768.19436231/t, comprising CO₂ USD 122.09737828/t, H₂ USD 596.09698403/t and electricity USD 50/t. Rounded values now appear in the issue. Added the previously missing `reality_check` metadata, including scenario year, boundary, assumptions and exclusions. These are illustrative inputs, not market prices.

## Source and date assessment

| Source | Finding | Permitted use in this issue |
| --- | --- | --- |
| [Crossref preprint metadata](https://api.crossref.org/works/10.26434/chemrxiv.15009603/v1) | Posting date 29 September 2026; literature-review scope established from deposited abstract. Full text inaccessible during review. | One in-window bibliographic candidate; no novel experimental, scale or performance claim. |
| [Kassø company release](https://europeanenergy.com/2025/05/13/kasso-e-methanol-facility-officially-inaugurated/) | Original release dated 13 May 2025; reports inauguration and 42,000 t/year capacity. | Historical, attributed baseline. Capacity is not audited annual output; not October 2026 news. |
| [Sailboat technology-provider page](https://carbonrecycling.com/projects/sailboat) | Key facts say commissioned in 2023; body gives 100,000 tonnes/year. Page mixes forward-looking prose with commissioning facts and has no reliably established publication year in its displayed month/day. | Historical CRI-reported baseline only. No current throughput, exact startup day or climate saving inferred. |
| [POSEIDON consortium page](https://project-poseidon.eu/about/synthetic-methanol-pilot-plant/) | Reports module installation in September 2026, without a day. Describes 500 L/day as planned capacity. | Attributed pilot background. Cannot locate the event in 25 September–8 October; cannot infer operation, demonstrated output or achieved TRL. |
| [UNCOVER announcement](https://co2value.eu/new-eu-funded-project-uncover-to-advance-the-market-uptake-of-co2-utilisation-technologies/) | Original displayed date 17 September 2026, corroborated by page `datePublished` metadata. | Out-of-window background; later syndication does not create a new original event. Programme goals remain goals. |
| [IRENA / Methanol Institute outlook](https://www.irena.org/publications/2021/Jan/Innovation-Outlook-Renewable-Methanol) | January 2021 reference publication. | General methanol background, not evidence of 2026 prices or project performance. |
| [AssessCCUS](https://assessccus.globalco2initiative.org/) | Assessment guidance. | Boundary and comparability guidance, not validation of this scenario or any project's climate benefit. |

The theoretical feed balances reproduce 44.01/32.04 = 1.3735955 t CO₂ and 6.048/32.04 = 0.1887640 t H₂ per tonne methanol. No lifecycle saving, durable removal, achieved TRL, catalyst efficiency or current operating output is asserted. Unknowns are described as not established by the cited evidence, not as universally unknowable.

## Publication validation

- `PYTHONPATH=src .venv/bin/python -m ccu_intelligence.cli validate`: **passes as a draft**. The validator returns early for draft content; this is not publication clearance.
- A temporary copy with only `editorial_status` changed to `published`, passed to the unchanged `validate_issue` and current curated bundle: **fails**, with `Publication requires a reviewer and cannot contain samples`. This issue is non-sample; the active cause is absent reviewer metadata. No approval was fabricated to bypass that check; the actual PR remains a draft.
- Independent checks against the remaining gate requirements identify **zero eligible selected articles in curated data**, versus 4–6 required; **one** signal identifier, versus three required; **zero** selected events, versus 2–3 required; and **zero** watch milestones, versus three required. The sole candidate remains in review data, not curated publication data. Even human sign-off alone would not resolve these gaps.
- The body has all seven sections and 1,278 whitespace-delimited words; the coverage window is 14 days. Reality-check fields are now complete. The three prose verification deadlines are editorial tasks, not supported, falsifiable project milestones, and have not been misrepresented as such.

Machine-readable results: [publication-validation.json](publication-validation.json).

To become publishable, the issue needs sufficient supported in-window material and real event records, aligned curated evidence/claims/identifiers, three evidence-based watch milestones, and actual human approval. These cannot be supplied by reclassifying historical announcements or inventing facts. Merge and publication remain subject to the user's explicit approval.
