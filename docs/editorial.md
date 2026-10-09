# Editorial runbook

## Review working candidates

Run collection, then inspect `data/candidates/articles.json` and `event-proposals.json`, and literal `metric-proposals.json`. These proposals are not verified facts or committed project events. Check original sources, reporting dates and whether syndicated articles share an original company release. Missing publication dates are retained in candidates but excluded from dated newsletters.

Use `snapshot` to save a working bundle, or build a bundle from `data/curated/samples.json` as a **shape reference only**. Never convert fictional sample records to live content by toggling their flags. Include all referenced companies/evidence/projects in an import bundle; Pydantic checks relationships before a transaction begins.

For a real record:

1. Add the source to `config/sources.yaml`, including access rights and limitations.
2. Create an evidence record with the original URL, retrieval timestamp, publication date if known, a precise locator, short excerpt or paraphrase, reuse note and raw-content SHA-256 when available.
3. Create claims with evidence IDs, explicit uncertainty, and the correct claim category. Company reporting stays attributed even after review. Set `reviewer` and `reviewed_at` only after actual human review.
4. Resolve organizations and project IDs. Never use a company as a substitute for a specific plant.
5. Review dimension scores/rationales; set article `editorial_status: reviewed` and `review_required: false` only after examining the original evidence.
6. Import with `ccu_intelligence.cli import`. An existing article may receive reviewed analysis, but its URL/fingerprint identity cannot be changed silently.

## Apply a project change

Create a `ProjectEvent` with the affected fields in both `previous_value` and `new_value`, their exact stored values, dates, evidence IDs and a stable event ID. Run `apply-event`. It rejects stale previous values, unknown evidence, sample/production mixing and attempted event rewrites. Rerunning an identical event is a no-op. A correction is a new event, never a replacement for an old event.

When a startup slips, retain the old date in `previous_value`. Preserve announced and operational capacities independently. Retain year/quarter date precision rather than inventing a day. Initial project import may include a historical baseline snapshot plus its earlier event history; subsequent changes use `apply-event`.

The working database is not a public data source. Copy the reviewed records and their required relationships into `data/curated/` in an editorial branch. Preserve all previously committed events/evidence. `export` validates the curated boundary and builds `public/data/intelligence.json`. Do not copy a whole candidate snapshot into curated data.

## Draft and publish an issue

Run `draft` to select eligible records in the latest completed 14-day window. Low volume results in an incomplete draft; do not manufacture developments. Existing files are left untouched, protecting editorial changes.

Complete the seven sections. Use three executive signals, 4–6 developments, 2–3 project updates and three falsifiable milestones when evidence supports a full issue. Supply chemistry, feedstocks, catalysts, conditions, performance, scale and limitations in the spotlight. Expand the materials/chemicals section around the actual developments. Aim for 1000–1800 words.

Each milestone frontmatter entry needs `hypothesis`, `deadline`, `evidence_url`, and `disconfirmation`. The `reality_check` mapping needs a functional unit, system boundary, reference scenario, geography, data year, assumptions, source confidence and limitations. `source_count` counts unique evidence URLs attached to selected articles, not every background reading link.

Keep `article_ids` and `event_ids` aligned with the issue; `executive_signal_ids` must identify three distinct selected articles. Set the five `review_checklist` fields to true after review, add `reviewer` and `reviewed_at`, then set `editorial_status: published`. Run validation and the build, inspect the rendered page and print view, and request the repository's normal editorial approval.

Drafts have no public route and do not appear in RSS. Sample content has its own route, visible warnings and noindex metadata. The default PR workflow never sets `published`. Structural checks cannot verify every sentence: the editor remains responsible for adjacent citations, source interpretation, rights and scientific accuracy.

## Owner-authorized research editions

An explicit owner request to publish an existing draft can use `editorial_status: research_published`, with a dated `publication_authorization` recording that instruction and a publication date. This publishes the existing text in the homepage, archive, issue route and RSS as a research edition. The body must disclose “RESEARCH EDITION” and “full editorial review remains incomplete”. Sample content remains excluded. Do not populate reviewer timestamps or completed checklists to imply checks that did not occur. The full `published` validation gates remain in effect for reviewed editions; automated drafts still use `draft`.

Issue 001 was authorized for direct publication by the repository owner on 2026-10-09. Its existing editor-edited text and source links are retained.
