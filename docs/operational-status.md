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

`.github/workflows/deepseek-research.yml` is manual-only (`workflow_dispatch`, no schedule) and runs only from the default branch, so pull requests, forks, tags and other branches can never reach the secret. `dry-run` (the default) collects and filters sources but makes zero model requests and receives no `LLM_API_KEY`. `paid` requires the repository variable `CCU_ENABLE_DEEPSEEK=true`, the secret `LLM_API_KEY` and a first run attempt; reruns are refused so a ledger is inspected before spending again.

Each paid run is capped at 30 new analyses, 60 attempts (one retry on 429/5xx or malformed JSON), a configurable token budget (default 120,000) and a configurable USD reservation (default 0.50 at a conservative ≥1.20 USD per million tokens). Reservations are persisted before every attempt and never refunded. Validated responses are cached by source text, model, endpoint and prompt version, so repeated articles are not paid for twice. Output is a draft and audit ledger uploaded as a 30-day private Actions artifact; nothing is committed, published or approved automatically.

To activate: add the `LLM_API_KEY` secret, set `CCU_ENABLE_DEEPSEEK=true`, run `dry-run` once, review the artifact, then dispatch `paid`. Adding a schedule requires owner approval and `CCU_ALLOW_SCHEDULED_PAID=true`.
