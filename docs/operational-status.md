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

- **dry-run** (default): collects sources, extracts legally available full text, makes zero model requests (cached responses may be reused), uses no environment and never receives `LLM_API_KEY`.
- **paid**: runs in the `deepseek-paid` GitHub Environment, whose only protection rule is the main-branch deployment policy. It also requires the repository variable `CCU_ENABLE_DEEPSEEK=true` and a first run attempt; reruns are refused so a ledger is inspected before spending again.

### Safety model

There are deliberately **no required reviewers** on `deepseek-paid`. Paid spending is bounded by: (1) manual dispatch only, from the default branch, first attempt only; (2) the environment's main-branch policy and the repository opt-in variable; (3) the **USD 5 hard cap** per run (`MAX_SPEND_USD_CAP` in `src/ccu_intelligence/workflow.py`; dispatch inputs can only lower it), reserved before every request at the ceiling rates in `config/models.yaml` (all input charged as a peak-hour cache miss, the full `max_output_tokens` at the peak output rate) and settled to the provider-reported usage at the same rates; requests that would exceed the cap are never sent; and (4) the owner's **prepaid DeepSeek balance** with auto top-up off, the account-level limit independent of this repository. Further hard caps: 150 new screening calls (Flash; dispatch input `max_screenings`), 60 items sent to enrichment and verification (Flash; `max_enrichments`), 400 requests, 5,000,000 tokens (default 2,000,000). `summary` reports `cut_by_screening_cap`, `cut_by_enrichment_cap` and `cut_by_fulltext_cap` (full text is fetched for at most 150 gated items). The key exists only as a `deepseek-paid` environment secret. Nothing is committed, published or approved automatically: output is a draft and audit ledger in a 30-day Actions artifact.

### Pipeline

1. **Collect** sources that have a `run_limit` in `config/sources.yaml`, keeping at most that many in-window items each: OpenAlex (boolean title/abstract CCU query, plus an open-access subset), Crossref, the Federal Register API, CCU company and association feeds, and targeted trade-press search feeds (`news-*`, `evidence_role: news`).
2. **Keyword triage.** Academic items need a CCU term (CO2, e-fuels/eFuels, e-SAF, RFNBO, power-to-liquid/PtL, PtX, Fischer–Tropsch, synthetic kerosene/e-kerosene, e-methane and others in `CCU_TERMS`; e-ammonia counts as adjacent). Every news, company, industry and government item goes to the LLM gate; only clearly off-topic titles (sport, banking, unrelated solar/battery/nuclear news without a fuel or CCU term, staff/HR posts on specialist feeds) are dropped. The terms only set screening priority. `report.json` records every reason.
3. **Full text.** Sources with `content_extractor: trafilatura` have their linked page fetched with our honest User-Agent, robots.txt checked on every redirect hop (RFC 9309: 4xx robots means no restrictions, 5xx or network failure means disallow), per-host spacing and the crawl delay respected. Papers use OpenAlex open-access locations (and Unpaywall when `CCU_CONTACT_EMAIL` is set); HTML via trafilatura, PDF via pypdf. Paywalls, 401/403 responses and firewalls are never bypassed: the item falls back to its abstract or headline. Each record's `input.basis` is `full_text`, `abstract` or `headline`. Extracted text stays in memory and in `data/runtime/fulltext-cache/`, which is **not** uploaded; artifacts hold only its size, hash, origin and fetch log.
4. **Stage 1 — screening** (`deepseek-flash`, 12,000-character head-middle-tail sample): relevance gate `ccu_relevant` (CO2 converted, utilized or mineralized; capture/storage alone is false), 0–10 decision-value score on the rubric in `config/prompts/profile/analysis.md`, one category from `config/taxonomy.yaml` (see `config/newsletter.yaml`), 3–5 tags. Irrelevant items score 0; headline-only items are capped at 6.
5. **Dedup and stories** (`deepseek-flash`): the same event reported by several sources is merged, keeping the most credible outlet (primary company/government/paper > major business press > trade press > regional press; tiers in `config/newsletter.yaml`); the others are listed as "Also reported". A copy whose full text could not be fetched yields to one with text. Related items about one project or company (for example a FEED award, a move into basic engineering and an offtake) are grouped into one story, written as one item that cites every source.
6. **Selection** (`config/newsletter.yaml`): score ≥ 5; per-category caps counted per story (default 5, conversion technology 8); at most 15 stories. When fewer than 10 stories would be selected, capped stories that pass the threshold fill up to 10. The threshold is never relaxed and quotas are never filled with weaker items.
7. **Stage 2 — enrichment** (`deepseek-flash`, thinking, up to 32,000 output tokens, 18,000-character sample): headline; what changed, why it matters, practical implication, optional next action (≤ 180 words); CCU fact sheet (CO2 source, route, catalyst, product, TRL, scale, energy, economics, LCA, partners, location, milestones). Unknown values are exactly "not stated in the supplied material". Every stated value needs a verbatim quote of ≤ 25 words; unsupported values, details and quotes are removed and logged, and event dates must be written in the source.
8. **Verification** (`deepseek-flash`, separate call and prompt): every headline, block, field and detail is checked against the source and marked supported, partially supported (corrected) or unsupported (removed). Corrections that introduce a number not in the source are rejected, and a deterministic check removes any remaining sentence whose numbers do not appear in the source. Items whose core claim fails, or whose verification is unavailable, are excluded and listed in the editor notes.
9. **Synthesis** (`deepseek-flash`): one call writes the issue from verified briefs only: an executive summary in plain prose (printed without citations; they stay in the item sections), 3–5 takeaways when enough stories qualify (one per category first, then further stories scoring ≥ 7), sections by category with one item per story, a one-line limitation per item, what to watch (dated or named next steps only) and editor notes. Unknown citations, uncited text, sentences with unsupported numbers and non-verbatim quotes are removed deterministically; "request/obtain X" advice is moved from item text to the editor notes; any verified item the synthesis omitted is added from its brief. The technology/economics table and the headline-only lists are rendered from data, not prose: **CCU ecosystem briefs** (relevant, unselected news from CCU-specialist companies and associations), **Also noted in research** (relevant papers not selected because of a cap or the threshold) and **Also noted in industry and policy**.

Prompts are profile-style markdown in `config/prompts/profile/` (`match`, `analysis`, `enrichment`, `verification`, `dedup`, `synthesis`); the version is `PROMPT_VERSION` in `src/ccu_intelligence/stages.py`. Validated responses are cached by stage, model, thinking mode, prompt text and input, so reruns are free and any prompt, model or input change re-analyses.

### Draft safeguards (added 2026-10-09)

- **Stories:** besides the dedup model's proposals, non-academic items that name the same project or organization (screening returns `projects` and `organizations`) become one story, written as one item citing every source. Multi-project roundups (three or more named projects) never join or bridge stories; they appear under each related story as "Also covered in roundup".
- **Event dates:** enrichment returns the main `event_date` only when it is written in the source. An item whose event predates the window is headed "(background, event date YYYY-MM-DD)", explained in the editor notes and never used as a takeaway; dated milestones outside the window inside an item are listed as background in the notes.
- **Compilations:** poster and abstract collections, research highlights and similar digests (evidence type `compilation`, Peeref DOIs `10.54985/`) are listed under "Also noted in research" with "(compilation)", never as research items.
- **Currency check:** "amount (other-currency amount)" pairs in the verified briefs are compared at fixed approximate reference rates (`src/ccu_intelligence/currency.py`); a gap above 20% becomes an editor note. Numbers are never corrected.
- **Research cap:** at most 4 research papers in the conversion section (`research_caps`), ranked by score with full text counting half a point more than an abstract; the cap is never relaxed to reach the 10-story target. The rest go to "Also noted in research".
- **Section intros** are plain sentences; citations stay with the items.
- **Headline-only items** (`input_basis = headline`) are screened but never enriched, written up or used as takeaways. When a text-backed item in the run covers the same event (a duplicate or the same story), the story is written from it and the headline item is listed as "Also reported" under it; otherwise it is listed under "Also reported (headline only)" with headline and link (specialist sources: "CCU ecosystem briefs"; papers: "Also noted in research").

### Feeds and the daily GDELT cache

Company newsroom feeds: INERATEC, European Energy and Liquid Wind (robots verified 2026-10-09). Uniper and Arcadia eFuels answer HTTP 403 to our declared agent, which we respect; HIF Global, Infinium, Twelve, Norsk e-Fuel and Syzygy Plasmonics have no RSS feed. These are recorded as manual sources. Trade-press feeds that load from runners: Offshore Energy (latest 50 items only), Biofuels Digest, Chemical Engineering, Manifold Times, Renewable Carbon News and a Bioenergy Insight search feed. Broad feeds use `include_pattern`: only items whose title or summary matches the CCU/e-fuel pattern count toward `run_limit`; paging stops at the window start.

`.github/workflows/gdelt-daily.yml` runs daily without secrets. `scripts/gdelt-daily.py` sends one GDELT request: the query whose last success is oldest (so a throttled query is retried first the next day), from one day before that success (16 days on first use) through today, saved under `data/runtime/gdelt-cache/` in the Actions cache. The research workflow restores the cache read-only and reads GDELT results from it, querying GDELT live only when nothing cached overlaps the window (`collection.json` records `gdelt_cache` coverage). Cache files older than 35 days are pruned.

### Editor-submitted items

When the automated sources miss a story (for example when GDELT is throttled), an editor can list it in `config/editor-submitted.yaml`: source (`editor-submitted-company` for official announcement text, `editor-submitted-news` for a press report), publisher headline, URL and publication date. Only pointers are stored, never text. The run applies the coverage window, fetches the text from the URL with the normal robots-respecting reader, and sends the item through the same gate, scoring, dedup, grounding and verification. Citations in the draft carry "editor-submitted", and `summary.editor_submitted` lists each item with its gate result, score and selection.

### Coverage window

The research workflow covers the most recent **14 complete UTC days, ending yesterday** by default: a dispatch on 2026-10-09 covers 2026-09-25 to 2026-10-08 inclusive. The dispatch inputs `coverage_end` (last covered day, `YYYY-MM-DD`, must be before today) and `coverage_days` (1–31) change it, for example to continue exactly where the previous issue ended. `python scripts/deepseek-research.py --check` prints the window without making any request. Run 37929580610 predates this: it used the anchored biweekly windows of the scheduled draft workflow (`editorial.window`, 14-day periods from Monday 2026-01-05), whose latest completed period on 2026-10-09 was 2026-09-14 to 2026-09-27. Those anchored windows still apply to the scheduled unpaid draft PRs.

A dry run also reports `paid_run_projection` in `summary`: the uncached screening calls, plus 10 and 15 enriched items with one dedup and one synthesis call, priced at ceiling rates from the average tokens per call in `config/models.yaml` (`estimates`). `worst_case_usd` charges every call its full output allowance; the USD 5 cap applies regardless.

### Models and prices

`config/models.yaml` holds the per-model price table (checked against <https://api-docs.deepseek.com/quick_start/pricing/> on 2026-10-09), ceiling rates (never below the official peak) and stage roles. All stages use **`deepseek-flash` only**, including screening, enrichment, verification, dedup and synthesis. Workflow model selection has been removed and both model environment variables are fixed to Flash. Local `LLM_SCREENING_MODEL` / `LLM_MODEL` values other than `deepseek-flash` fail before requests are sent; direct completion calls enforce the same rule. Pro prices remain solely for historical cost accounting and do not authorize Pro calls. Existing response caches include the model in their key, so old Pro responses are not reused by Flash stages. If the API rejects thinking together with JSON mode, the call is retried once with thinking disabled and the fallback is logged. `report.json` gives per-call usage, an upper-bound cost (peak, all input as cache miss) and a time-of-day estimate including cache hits, plus the prepaid-balance difference before and after the run when the balance endpoint is available.

### Google News: documented robots.txt exception

`news.google.com/robots.txt` disallows `/rss/search` for all agents, and its feed terms are aimed at personal feed readers. On 2026-10-09 the owner decided to use it anyway as a **supplementary** source, as a deliberate exception for this **personal, non-commercial learning project**, because GDELT throttles GitHub runner IPs and several trade-press feeds serve bot challenges to them. The exception is narrow:

- **Scope:** only the four `google-news-*` sources, one per GDELT query, with the same topics. `Source.robots_exception` must document the decision and is rejected by validation for any other source or host.
- **Frequency:** one feed request per query per research run (`scripts/deepseek-research.py` sets `google_news=True`). Scheduled drafts, manual collection and every other caller skip these sources.
- **Content:** headlines, dates, publisher names and links from the feed only. The window is expressed as `after:`/`before:` operators.
- **Identity:** our honest User-Agent; no browser spoofing.
- **Articles:** Google's article links are encoded redirects and are never followed or decoded through Google. The article is looked up on the publisher's own site (its WordPress search feed, matching the exact headline) and fetched under that publisher's robots.txt. If it cannot be found, the item stays a headline-only lead labelled "<publisher> (via Google News)" and is screened at most as a headline (score cap 6).
- **Dedup:** the same story from Google News, GDELT or a trade-press feed is merged by the dedup stage, keeping the more credible outlet.

`collection.json` records `publisher_resolved` and `publisher_unresolved` per Google News source. Revisit this exception if the project stops being personal or non-commercial.

The fetcher spaces requests to one host from the **end** of the previous response (GDELT can take about 10 s to answer), and retries 429/5xx responses and transport errors (timeouts, dropped connections) once, after max(Retry-After, the source's interval, 1 s); then the source is marked failed and the run continues. A Retry-After above 60 s defers the source to the next run. GDELT sources are spaced 15 s apart. GDELT rate-limits by IP and sometimes drops connections instead of answering (`RemoteProtocolError`, seen 2026-10-09; HTTP 429 persisted for over two minutes from one IP), so its queries remain best effort: one retry, then the source is marked failed. E-fuels, e-methanol, e-SAF and RFNBO news does not depend on GDELT: the Carbon Herald, GreenAir News and Biofuels International search feeds cover it. GDELT answers some errors as plain text with HTTP 200; these are logged as `RateLimited` or `GDELT query error: <message>`. GDELT rejects quoted phrases shorter than four characters, so 45Q/45V are searched as "45Q tax credit"/"45V tax credit".

**Hydrogen Central** (four search feeds) is deactivated as of 2026-10-09: the server completes TCP and TLS but never sends an HTTP response, even for `robots.txt` and with a generic agent, from GitHub runners and from a residential IP. An unreadable robots.txt fails closed (RFC 9309), which the collector now reports as `robots.txt unreadable (ReadTimeout); collection fails closed`. Its coverage moved to Carbon Herald search feeds (`e-methanol`, `RFNBO`) and GreenAir News search feeds (`e-SAF`, `power-to-liquid`), whose robots.txt permit access. Re-enable Hydrogen Central by setting `active: true` once it answers again.

Some trade-press sites serve an anti-bot challenge page instead of the feed to datacenter IPs such as GitHub-hosted runners (seen 2026-10-09 for Carbon Herald and CO2 Value Europe; Hydrogen Central timed out). These are logged as `non-feed response (possible bot challenge; not bypassed)` and never circumvented; the run continues with the other sources.

### Activation

1. In **Settings → Environments**, create `deepseek-paid` and restrict *Deployment branches* to the default branch. Do not add required reviewers (see the safety model).
2. Add `LLM_API_KEY` as a secret **of the `deepseek-paid` environment** (not a repository secret).
3. In **Settings → Variables**, set the repository variable `CCU_ENABLE_DEEPSEEK=true`.
4. On the DeepSeek platform, keep a **prepaid balance** with auto top-up off.
5. Optional: add `CCU_CONTACT_EMAIL` (enables Unpaywall and the OpenAlex/Crossref polite pools) and `OPENALEX_API_KEY` as secrets.
6. Run `mode=dry-run` and review `report.json` (triage reasons, `input.basis` per item), then run `mode=paid` with the defaults.

### Evaluating a paid run

Use the artifact's `report.json`, `budget.json` and `draft.md`:

- [ ] **Input quality**: `summary.input_basis`; items on `headline` cannot support detailed claims.
- [ ] **Gate and scores**: per record `screening` (`ccu_relevant`, `score`, `band`, `reason`); check false positives and missed CCU items.
- [ ] **Fact sheets**: per record `fields.filled` / `fields.not_stated` against the original source.
- [ ] **Verification**: per record `grounding_removed` and `verification` (`removed`, `corrected`, `number_removed`, `unchecked`); `synthesis_issues` for the issue text.
- [ ] **Cost**: `summary.usage_by_model`, `cost_upper_bound_usd`, `cost_estimate_usd` and `balance_delta`, versus the DeepSeek dashboard.
