# Operational status — 9 October 2026

Live website: https://rethinksci-gif.github.io/ccu-intelligence/

## Public content

Three source-checked project baselines replace fictional projects: Kassø (European Energy), Jiangsu Sailboat (CRI) and POSEIDON Mannheim (project consortium). Sources are linked on each record and retained with retrieval dates and SHA-256 checksums. Reported design output is separate from measured operational output, which remains unknown. Climate benefits, current utilisation and achieved TRLs are not asserted without evidence. Historical commissioning is not recast as current news.

Fictional JSON remains in the repository for pipeline tests, but export excludes all sample records. The sample issue and fictional project routes are removed from the deployed site. Learning material and the explicitly assumed calculator remain unchanged.

## First newsletter

Issue 001 covers 25 September–8 October 2026. Its real-source draft has seven sections and adjacent citations. One precisely dated Crossref research lead falls in the reporting window; older project and programme announcements are explicitly background. The original UNCOVER announcement is 17 September, despite later syndication.

Status: draft, not publishable yet. Human review, 4–6 supported in-window developments, 2–3 real in-window project events and the existing checklist are required. No human reviewer identity or approval has been invented. The public archive and RSS remain empty until those gates are met.

The existing DeepSeek grounded pipeline screened collected metadata and primary-source excerpts under one persistent budget: five request reservations, 3,335 reported tokens, maximum 16,000 tokens. Raw pages and model responses remain under ignored `data/runtime/` and `data/raw/`. The review PR contains a concise provenance report, not secrets or full source pages.

## Schedule and approval

The draft workflow checks daily at 07:17 UTC. It produces at most one PR for each completed anchored 14-day window; existing branch/file checks preserve editorial edits and allow a delayed run to catch up. The first scheduled draft is **12 October 2026 at 07:17 UTC (09:17 Stockholm)**, covering 28 September–11 October inclusive; the following window ends 26 October. GitHub scheduling may run late. The bootstrap issue has a different, explicitly stated window and is not counted as a scheduled fortnight.

Each scheduled run considers at most 20 records across the existing eight sources. It has no `LLM_API_KEY`, `max_analyses=0` and `max_requests=0`; there are no scheduled paid calls. A candidate inbox, original links, collection diagnostics and metadata are committed only to an editorial review branch. The workflow creates a draft PR and never merges it, approves it or sets `published`.

An editor must examine primary evidence, complete publication requirements and reviewer metadata, mark the PR ready, and manually approve publication through the normal merge process. Merging unchanged draft content does not publish it. If evidence is insufficient, keep the draft open; do not relax the publication gate to fill an issue.

## Optional DeepSeek research workflow

`.github/workflows/deepseek-research.yml` is manual-only (`workflow_dispatch`, no schedule) and runs only from the default branch, so pull requests, forks, tags and other branches can never reach the secret. It has two jobs:

- **dry-run** (default): collects and filters sources, makes zero model requests, uses no environment and never receives `LLM_API_KEY`.
- **paid**: runs in the `deepseek-paid` GitHub Environment, so a required reviewer must approve every run before the job starts and the key is read from that environment's secrets. It also requires the repository variable `CCU_ENABLE_DEEPSEEK=true` and a first run attempt; reruns are refused so a ledger is inspected before spending again.

Each run is capped at 30 new analyses and USD 0.50 (hard caps in `scripts/deepseek-research.py`; dispatch inputs can only lower them), 60 attempts (one retry on 429/5xx or malformed JSON) and a configurable token budget (default 120,000). Every token is reserved at ≥ USD 1.20 per million, the highest `deepseek-flash` price (peak output; checked 2026-10-09). Reservations are persisted before every attempt and never refunded. Validated responses are cached by source text, model, endpoint, prompt version and prompt text, so repeated articles are not paid for twice and any prompt or model change re-analyses. Output is a draft and audit ledger uploaded as a 30-day private Actions artifact; nothing is committed, published or approved automatically.

Deterministic filtering runs before any model call. `report.json` records the triage reason for every article (`CCU topic`, `specialist milestone`, `no CCU term`, `CCU term without utilization context`, `specialist feed: unrelated energy topic`); the CCU term list is `CCU_TERMS` in `src/ccu_intelligence/workflow.py`.

Pure capture or removal items with no utilization step are dropped. The exception is ecosystem news from CCU-specialist sources (`CCU_SPECIALIST_SOURCES`: CO2 Value Europe, Liquid Wind, Dioxycle, Carbicrete) that mentions a CCU term: it is listed under **CCU Ecosystem Briefs** in `draft.md` (title, source, date, link) with reason `specialist source: headline-only brief`, and is never sent to the model.

Collection is low-frequency: each source receives `robots.txt` plus one feed or API request per run, at least `minimum_interval_seconds` (or the robots crawl delay, if longer) apart per host. 403 and other 4xx responses are not retried. 429/5xx are retried at most twice with backoff of at least 1 s then 2 s, honouring a short `Retry-After`; a `Retry-After` above 30 s defers the source to the next run.

### Activation

1. Merge the PR after review.
2. In **Settings → Environments**, create `deepseek-paid`. Add yourself as a **required reviewer**, enable *Prevent self-review* only if another maintainer will approve, and restrict *Deployment branches* to the default branch.
3. Add `LLM_API_KEY` as a secret **of the `deepseek-paid` environment** (not a repository secret). Remove any repository-level `LLM_API_KEY`.
4. In **Settings → Variables**, set the repository variable `CCU_ENABLE_DEEPSEEK=true`.
5. On the DeepSeek platform, use a **prepaid low balance** (for example USD 2–5) and keep auto top-up off; that balance is the account-level hard limit independent of this repository.
6. Run the workflow with `mode=dry-run` and review the artifact's `report.json` triage reasons and candidate list.
7. Run `mode=paid` with the recommended first-run parameters **`max_analyses=6`, `max_spend_usd=0.10`**, default token budget and rate ceiling, and approve the environment deployment.

Adding a schedule requires owner approval, a cron trigger and `CCU_ALLOW_SCHEDULED_PAID=true`; none exist now.

### Evaluating the first paid run

Use the artifact's `report.json`, `budget.json` and `draft.md`:

- [ ] **Validation rejection rate**: `new_analyses_validated / new_analyses_attempted`. Investigate if fewer than ~80% validate; inspect which quote or date check failed before changing the prompt (never loosen matching).
- [ ] **Missed key information**: for each analysed article, compare the source against the extracted technical, economic and milestone entries. Record omitted capacities, costs, dates and project names.
- [ ] **False relevance**: articles marked relevant that are not CCU (for example supercritical-CO2 solvent processing), and triage drops that should have been kept.
- [ ] **Actual tokens per article**: `usage.total_tokens / new_analyses_attempted`, versus the per-request reservation. Use it to size `token_budget` and `max_spend_usd` for a 30-article run.
- [ ] **Actual cost**: compare `estimated_cost_usd` with the DeepSeek dashboard charge for the run.
