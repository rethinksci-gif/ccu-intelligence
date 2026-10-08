# CCU Intelligence — Carbon Capture & Utilization

An evidence-driven, static-first intelligence platform connecting scientific progress, engineering feasibility, industrial deployment, economics and climate performance.

**Status:** MVP configured for GitHub Pages at https://rethinksci-gif.github.io/ccu-intelligence/ (repository: https://github.com/rethinksci-gif/ccu-intelligence). The initial project records and newsletter example are explicitly fictional; there are no published live issues. Public reference articles and transparent calculations are separate from news. Real metadata collection does not constitute factual verification.

## Architecture

```text
Permitted APIs / approved RSS / manual evidence
                  │
         bounded retrieval + raw hash
                  │
     SQLite working store + candidate JSON
                  │
 normalize → deduplicate → classify → resolve entities
                  │
 deterministic scores + proposed events + literal metric proposals + optional LLM proposals
                  │
        HUMAN EVIDENCE / EDITORIAL REVIEW
                  │
 reviewed JSON + immutable events + Markdown issue in a PR
                  │
       validation → Astro static build → GitHub Pages
```

Python 3.12, Pydantic 2, SQLite and HTTPX implement the processing layer. Astro 7 and strict TypeScript generate HTML with small vanilla TypeScript interactions. A shared CSS design system supplies responsive and print layouts; Tailwind is intentionally unnecessary for this MVP. There is no browser API credential, public database server, or LLM dependency in the site.

SQLite separates companies, evidence, projects, technologies, articles, claims, claim/evidence relationships, events, retrieval logs and audits. Indexed URL, DOI and content fingerprints support deterministic deduplication. Each table retains a validated JSON payload for portable schema evolution; indexed keys and relational links enforce identity. Events cannot be updated or deleted, and applying an event checks the previous values transactionally.

## Local setup

Requirements: **Node 22.12+** (24 recommended), npm, Python **3.12**, and a working package registry connection for the first install. Run all commands from the repository root.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
npm ci
export PYTHONPATH=src
export ASTRO_TELEMETRY_DISABLED=1
.venv/bin/python -m ccu_intelligence.cli init
npm run dev
```

Open **http://127.0.0.1:4321/**. To inspect the production output:

```bash
npm run build
npm run preview
```

`npm run build` validates publication eligibility and regenerates the public JSON before Astro runs. It also checks every generated internal link and asset. Set `ASTRO_TELEMETRY_DISABLED=1` in restricted environments to avoid an unnecessary write to the user configuration directory.

## What works

- Home, newsletter archive, project tracker, Technology Atlas, Insights & Learning, and methodology pages.
- Search and combined project filters: region, country, company, pathway, product, status, TRL, sample/live scope and compatible announced capacity.
- Persistent project URLs, evidence, unknown-value labels and event history with previous/new values.
- Three pathway profiles, original process diagrams, and seven sourced technical primers.
- Interactive methanol feedstock/energy sensitivity model, backed by the same documented Python formula.
- English seven-section Markdown newsletter drafts with structured metadata, date windows and adjacent citations.
- Published-only archive and RSS; draft content has no public route. A separate noindex sample issue demonstrates the format.
- Semantic HTML, keyboard navigation, mobile menu, print CSS, canonical/SEO/social text metadata and sitemap.
- Crossref/OpenAlex collectors, configurable RSS/Atom adapter, manual ingestion, raw preservation, deduplication, conservative classification, literal metric extraction, entity matching, scoring and event proposals.
- Optional configurable OpenAI-compatible JSON analysis, without automatic authority to approve or publish.
- Manual collection and biweekly-window draft PR workflows; main-branch deployment with validation gates. Scheduled collection and drafting are disabled for the first deployment.

## Pipeline commands

```bash
export PYTHONPATH=src
# Start an idempotent local working database from curated reference/sample data.
.venv/bin/python -m ccu_intelligence.cli init

# Small real API query. Metadata only; nothing is published.
.venv/bin/python -m ccu_intelligence.cli collect --source crossref --limit 10
.venv/bin/python -m ccu_intelligence.cli collect --source openalex --limit 10
.venv/bin/python -m ccu_intelligence.cli status

# Import a complete, schema-valid evidence bundle. See docs/editorial.md.
.venv/bin/python -m ccu_intelligence.cli import data/manual/review.json
.venv/bin/python -m ccu_intelligence.cli apply-event data/manual/event.json

# Save working records for review; this may include unreviewed candidates.
.venv/bin/python -m ccu_intelligence.cli snapshot data/candidates/review-bundle.json

# Draft the latest completed 14-day window, without overwriting existing edits.
.venv/bin/python -m ccu_intelligence.cli draft
.venv/bin/python -m ccu_intelligence.cli draft --as-of 2026-10-12 --sample --output /tmp/ccu-sample

# Validate the curated publication boundary; export only checked-in curated data.
.venv/bin/python -m ccu_intelligence.cli validate
.venv/bin/python -m ccu_intelligence.cli export

# Deterministic calculator, optional assumption JSON file.
.venv/bin/python -m ccu_intelligence.cli calculate
.venv/bin/python -m ccu_intelligence.cli calculate --assumptions data/manual/assumptions.json

# Optional LLM proposal. Missing keys, timeouts and invalid JSON fall back safely.
.venv/bin/python -m ccu_intelligence.cli analyze data/manual/source.txt --task extraction
```

Use `--db /path/to/file.sqlite` **before** the subcommand to isolate a run. Raw responses are under ignored `data/raw/`; working SQLite and collection logs are under ignored `data/runtime/`; proposed articles/events are under ignored `data/candidates/`. Never place credentials or restricted source files in `public/` or `data/curated/`.

`config/sources.yaml` is the source registry. It includes 15 company monitoring candidates, not commercial rankings. Crossref and OpenAlex are active metadata adapters. Other registry entries require manual access review. To enable RSS, provide a canonical HTTPS endpoint, record its reuse terms, select `access_method: rss`, and explicitly set `automated_access_approved: true`. The adapter checks robots.txt, request intervals, response size and status. Redirects and unknown robots access fail closed; review and update the endpoint rather than bypass restrictions.

Retrieval is deliberately bounded to one response per API/run (default 50, maximum 100 records); reaching the cap is logged as incomplete coverage. RSS and XML entity parsing are protected. Host addresses must be public, HTTPS is required, and automatic redirects are disabled. Only repository maintainers may edit the source registry; this is not a public URL-fetching service.

## Editorial and data integrity

See [editorial runbook](docs/editorial.md), [data dictionary](docs/data-model.md), and [security and operations](docs/operations.md).

An LLM or keyword match produces proposals, never independently verified facts. Source metadata alone cannot prove an industrial milestone. Claims distinguish `verified_fact`, `company_reported_claim`, `model_derived_interpretation`, `analyst_inference`, and `unverified_information`. Substantive claims need evidence plus uncertainty. Publishing requires identified human review and a completed checklist.

Windows are anchored on **2026-01-05 at 00:00 UTC**, using `[coverage_start, coverage_end)`. January 5 is a scheduling anchor, not a claimed first publication. Daily draft checks resolve the latest completed 14-day window; deterministic filenames/branches make reruns safe and permit catch-up after a delayed scheduled run. Review may take longer than the window. No fixed story count is fabricated when quality evidence is insufficient.

Production publication requires 4–6 reviewed developments, 2–3 non-sample project events, three dated falsifiable milestones, all seven sections, citations, economics/LCA context, 1000–1800 words, reviewer metadata and an explicit review checklist. The initial sample draft intentionally does **not** satisfy publication requirements. Structural validation cannot prove prose is scientifically correct; reviewer accountability and protected branches are essential.

The site never sums unlike capacity metrics. Unknown is not zero. The methanol model uses 44.01/32.04 t CO₂ and 6.048/32.04 t H₂ per tonne methanol, then divides by user-assumed utilization. The approximate 1.375 t CO₂ figure in the brief is represented with more precise molar masses (≈1.374). Defaults are scenario assumptions, not current market prices. The calculation excludes capital recovery and multiple operating costs and provides no LCA result.

## Tests and verification

```bash
export PYTHONPATH=src ASTRO_TELEMETRY_DISABLED=1
.venv/bin/python -m pytest -q
.venv/bin/ruff check src/ccu_intelligence tests scripts
.venv/bin/python scripts/validate_workflows.py
npm run build
npx playwright install --with-deps chromium
npm run test:browser

# Reproduce a project-site deployment path locally.
SITE_URL=https://your-account.github.io BASE_PATH=/ccu-intelligence/ npm run build
BASE_PATH=/ccu-intelligence/ npm run test:browser
```

Playwright covers desktop/mobile navigation, filtering, empty states, capacity comparability, calculator changes, sample exclusions, and historical dates. Python tests cover parsers, missing metadata, deduplication/provenance, scoring, validation, immutable/stale events, date windows, draft idempotency, model calculations and API/LLM failure behavior. Live API checks are not required for tests. See [verification report](docs/verification.md) for results from implementation.

## Environment variables

No environment variables or API secrets are required for local sample mode.

| Variable | Purpose |
| --- | --- |
| `PYTHONPATH=src` | Locate the Python package without editable installation. |
| `CCU_DB` | Working database path; default `data/runtime/intelligence.sqlite`. |
| `CCU_CONTACT_EMAIL` | Optional Crossref polite-pool contact; use a role account. |
| `OPENALEX_API_KEY` | Optional OpenAlex credential; basic anonymous access is attempted without it. |
| `LLM_API_KEY` | Optional provider credential, read only by Python. |
| `LLM_BASE_URL` | HTTPS OpenAI-compatible API root, default `https://api.openai.com/v1`. |
| `LLM_MODEL` | Explicit model identifier; no paid model is selected automatically. |
| `SITE_URL` | Static site's public origin; default `http://localhost:4321`. |
| `BASE_PATH` | `/` locally or `/repository-name/` for GitHub project Pages. |
| `ASTRO_TELEMETRY_DISABLED=1` | Disable Astro telemetry. |

`.env.example` documents the variables. Python does not automatically load a `.env` file; export only the variables you need. Never prefix secrets with `PUBLIC_`. LLM prompts live separately in `config/prompts/` for relevance, extraction, economics, project changes, verification, editorial, learning and newsletter tasks.

## GitHub Pages deployment

The public repository is `rethinksci-gif/ccu-intelligence`. Pages uses GitHub Actions and the existing `.github/workflows/deploy.yml`, triggered by pushes to `main` or manual dispatch. Pull requests validate without deploying.

The production build sets `SITE_URL=https://rethinksci-gif.github.io` and `BASE_PATH=/ccu-intelligence/`, uploads only `dist/`, and deploys through the `github-pages` environment. The build has `contents: read`; deployment has `pages: write` and `id-token: write`.

Collection and draft workflows are **manual-only**. No scheduled industry collection, automated newsletter publication, API secrets, or paid LLM calls are enabled by this deployment. Any future automation requires a separate operational decision. Optional branch protection and human environment reviewers can be configured in repository settings.

Collection restores the latest successful default-branch `collection-state` artifact and uploads a new SQLite snapshot. Raw responses are **not uploaded**. Working state retention is 90 days; candidate artifacts last 30 days. Export and commit reviewed history regularly and maintain backups. If a previous run exists but its artifact cannot be retrieved, restoration fails rather than silently discarding history. See the operations runbook for recovery.

PR workflows triggered by `GITHUB_TOKEN` can require a maintainer to select **Approve workflows to run**. A narrowly scoped GitHub App token can support unattended triggers if needed. Keep branch protection enabled. See [GitHub workflow-trigger documentation](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow).

## Repository tree

```text
.github/workflows/       collect.yml, draft-issue.yml, deploy.yml
config/                  source registry, taxonomy, weights, eight prompts
src/ccu_intelligence/     schemas, SQLite, collectors, analysis, LLM, scoring,
                         calculation, editorial gates, CLI
src/content/             Markdown issues and seven learning articles
src/components/          interactive Reality Check
src/layouts/             shared accessible page layout
src/pages/               home, issues, projects, atlas, learning, RSS, methodology
src/styles/              design system, responsive and print styles
src/lib/                 typed data and base-path helpers
data/curated/            reviewed reference material + explicitly marked fixtures
data/manual/             local manual-ingestion workspace
public/data/             generated curated JSON (no runtime candidates)
public/                  favicon and public assets
scripts/                 build/data/workflow/link checks and state restore
tests/                   Python integration/unit tests, RSS fixture, browser tests
docs/                    editorial, data model, operations, verification
requirements.lock        exact Python dependency versions
package-lock.json        exact npm dependency resolution
```

## Known limitations and next work

- No real project database or current newsletter has been editorially verified yet. Human review is the remaining content work, not an API-key workaround.
- Collection is bounded keyword search, not exhaustive discovery. Add cursor pagination, per-source incremental checkpoints, retrieval checksums across dates and broader regional/language queries next.
- Exact URL/DOI/text deduplication works. Semantic syndication clustering and a project alias-resolution interface remain future work.
- Event detection is conservative keyword triage; structured extraction and optional LLM outputs require review before insertion. LLM tasks use one common validated envelope and were tested with mocked failures, not a paid provider call.
- The database is a single-editor SQLite working store; repository review and immutable events preserve curated history. Multi-editor conflict handling, explicit migration tooling, long-term backups and richer audit identities are next operational improvements.
- Only methanol has a quantitative scenario model. Broader TEA/LCA, commercial-readiness assessment, project delay analytics and time-series regional trends need curated longitudinal data.
- Collection and draft PR workflows remain manual-only and have not been exercised remotely during the first Pages deployment.
- Native fonts avoid third-party font requests. No copyrighted images, articles or proprietary databases are redistributed. Accessible behavior is tested, but a full WCAG audit is not claimed.
