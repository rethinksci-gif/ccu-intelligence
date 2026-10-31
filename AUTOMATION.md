# Autonomous publishing

Normal publishing requires no content approval, PR merge, or manual deployment. `.github/workflows/autonomous.yml` runs daily at **05:47 UTC** on the default branch. GitHub may delay scheduled jobs. `workflow_dispatch` is an optional diagnostic/recovery trigger; `dry_run=true` does all checks and builds without committing or deploying.

The pipeline collects sources, extracts claims, verifies each item, renders eligible CCU research editions, runs tests and the existing site build, commits the bounded publication paths, dispatches the existing deployment workflow, waits for that run, and checks its live-confirmation artifact. The deployment workflow itself fetches the live receipt and every HTML page and compares SHA-256 hashes to the exact build. A successful dispatch alone is never deployment success.

Publication uses immutable fourteen-day windows, anchored to Monday 12 October 2026 (CCU retains its equivalent 5 January anchor). A window closes on 26 October, 9 November, 23 November, and so on. Daily retries can publish the last completed window once enough evidence exists. The minimum is **4 verified developments**. No filler or empty edition is generated. Existing edition files are never overwritten on reruns.

## Evidence boundary

Candidates receive `VERIFIED`, `QUARANTINED`, or `REJECTED` in `automation/verification.json`, with source references and reasons. Deterministic checks establish dates, provenance, duplicates, excerpts and numerical consistency. The semantic reviewer must pass every required check, including units, operating conditions, contradictions, legal dates/status and bilingual meaning where applicable. Model agreement is not independent confirmation; corporate assertions remain corporate assertions.

Missing keys, inaccessible originals, ambiguous publication dates, unsupported claims and incomplete model responses fail closed. A quarantined item cannot enter a publication. Unrelated verified items may proceed. Edition-wide contradictions still block publication. Build failure prevents the content commit and deployment trigger. Deployment/confirmation failure fails the run and preserves audit evidence; GitHub Pages deployments use the existing site deployment system. No repository protections or environment approval rules are removed by this implementation.

`automation/publications/*.json` binds each automatic edition to its reviewed items and content hashes. CI rejects later content changes without a matching new evidence record. Historical manually curated content is preserved and is not retrospectively claimed to have passed the new gates.

## Operations and credentials

Required credentials: **deepseek-paid environment LLM_API_KEY**. Secrets are supplied only to default-branch scheduled/dispatch processing, never PR jobs. The publication job has contents write and actions write for its commit and deploy dispatch. The deployment job has Pages/OIDC permissions. No PAT or protection bypass is used. Current main branches have no required-review protection; if protections change, a rejected push fails visibly rather than bypassing them.

Model calls are bounded (CCU existing research: 40 calls / 250,000 tokens / $0.75 reservation ceiling, plus at most 6 original-source semantic checks; Electrification: 32 calls, 5,000 output tokens each; Plastics: 40 calls under its existing client limits). Provider pricing and balances remain external operational dependencies. Budget exhaustion never authorizes publication.

`automation/status.json` records the last research check, prepared publication, skip reasons, and, after deployment, the confirmed revision, last confirmed publication and deploy run URL. Actions retains `evidence-audit-*` and `live-confirmation` artifacts for audit; failures before a status commit remain visible in the Actions run/artifact. Private extracted full text is not copied into website output. Quarantine audits are retained in the repository, while their unsupported claims are excluded from public articles.

## Tests

Run the existing Python tests plus `automation/tests` (Electrification uses `python -m unittest discover -s automation/tests -v`), then the existing site build and browser suite where present. Tests cover successful publication, item quarantine, missing/broken evidence, duplicates, conflicting numbers, policy dates, bilingual semantic drift, empty input, missing keys, incomplete verifier responses, edition reruns, build failure, deployment receipt failure and changed live content. Network/provider failures may still occur in production and are recorded rather than treated as verification.
