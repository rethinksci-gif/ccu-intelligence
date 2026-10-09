# Security and operations

## Trust boundaries

Source text is untrusted. It is stripped to plain text for metadata and escaped for generated Markdown; XML parsing forbids external entities. LLM calls have no tool privileges, no publication permissions, bounded source input, finite timeouts, retries and strict output validation. Unknown evidence IDs are rejected. Every output remains a proposal; prompt wording alone is not considered an injection defense.

Credentials come only from environment variables/secrets. Browser code never imports Python configuration. HTTP logs are suppressed to avoid printing request query strings. Authorization headers and API keys are not stored in raw manifests. Raw external responses remain ignored local files and are not included in workflow artifacts or Pages output.

Collectors require public HTTPS endpoints and do not follow redirects for registry endpoints. RSS access and full-text page reading require an explicit approved registry entry and robots.txt permission, following RFC 9309: a 4xx robots.txt means no restrictions, while a 5xx or network failure fails closed. Full-text reading follows at most five redirects, re-checking the public address and robots.txt for every hop. No browser User-Agent is spoofed and no paywall, login or firewall is bypassed. The registry is trusted maintainer configuration, not user-submitted input. Network egress restrictions should remain enabled in any future multi-user deployment; DNS validation is not a complete defense against hostile DNS rebinding.

The LLM provider receives selected source text. Use only material you are authorized to send to that provider. The application does not bypass paywalls or download proprietary databases. Evidence snippets must comply with source rights; public records are reviewed in Git.

## Failure behavior

Timeout/network errors and 429/5xx statuses retry with bounded exponential backoff. Long retry delays defer collection. Malformed source responses are logged per source; malformed records are skipped where normalization is possible. Successful sources continue independently. Missing metadata stays null. OpenAlex may reject anonymous requests depending on its active service policy; failures are logged and manual ingestion remains available. No paid LLM call is needed to collect, review, calculate, draft or build.

Result caps are visible in retrieval logs. A successful run is not proof of complete coverage. Monitor `last-run.json`, review failed/manual/capped sources, and do not describe a capped search as comprehensive surveillance.

## Durable state and recovery

Collection artifacts retain the cumulative working SQLite state for 90 days. Daily successful runs restore and refresh it. Source raw files are ephemeral on GitHub runners; use approved private storage if long-term raw preservation is required. Reviewed records and immutable event history belong in the repository.

If a prior successful collection exists but its artifact expired, the restore step fails instead of starting from zero. Recover a trusted backup to `data/runtime/intelligence.sqlite`, or explicitly accept a rebuild from curated records and change the restore step for that one run. Rebuilding loses uncurated historical candidates. Back up SQLite using its backup API rather than copying an open WAL database. The CLI closes each connection before the workflow uploads it.

If curated snapshots have advanced beyond restored working projects, initialization reconciles them only when a complete new event chain reproduces every changed field. Unexplained snapshot overwrites and stale event chains are rejected. Include verification-date changes in the event delta too.

On a public repository, Actions artifacts are not a confidential archive. Default API adapters retain metadata rather than abstracts in the bundle. Full text and abstracts read for analysis are kept in memory and in `data/runtime/fulltext-cache/`, which is never uploaded; run artifacts record only the input basis, size, hash and origin, plus our paraphrase and quotes of at most 25 words. Before enabling RSS, ensure summaries and evidence in artifacts are licensed for that exposure; otherwise operate collection in a private repository and export only reviewed material.

## GitHub controls

Use protected branches and required human review. Workflow permission declarations reduce accidental authority but are not a substitute for repository settings. Collection cannot push; drafting can create a review branch/PR; deployment has Pages authority only after the build passes on main. No remote-changing workflow was run during implementation.

Dependabot can be added after the repository is provisioned. Dependency versions are locked; upgrade deliberately and rerun Python, type, link and browser checks. Action major versions are used for maintainability in the starter; production hardening should pin reviewed action commit SHAs and configure automated update PRs.
