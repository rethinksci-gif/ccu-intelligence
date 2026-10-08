# Implementation verification

Verified locally on **2026-10-08** using Python 3.12.3, Node 24.21.0, Astro 7.3.8 and Playwright 1.64.0. No GitHub push, remote workflow or deployment was performed.

| Check | Result |
| --- | --- |
| Python unit/integration suite | 21 tests passed |
| Ruff Python lint | Passed |
| Astro strict TypeScript diagnostics | 0 errors, 0 warnings, 0 hints |
| Production build at `/` | Passed (initial build) |
| Production build at `/ccu-intelligence/` | Passed; 21 generated HTML pages |
| Internal links/assets at repository subpath | Passed across all 21 pages |
| Playwright desktop and mobile | 12 tests passed |
| Visual inspection | Desktop and mobile homepage screenshots inspected |
| GitHub workflow structural checks | Passed |
| actionlint 1.7.11 | Passed on all three workflows |
| npm dependency audit during install | 0 reported vulnerabilities |
| Crossref live smoke test | HTTP success; 3 metadata records ingested |
| Crossref identical rerun | 0 added, 3 duplicates, 0 failures |
| Anonymous OpenAlex live smoke test | 3 metadata records ingested, 0 failures |
| API coverage caps | Both API tests correctly flagged their 3-record result caps |
| Draft CLI | Created an unpublished review draft for the latest completed window; no live claims promoted |
| No-key operation | Python tests and site work without LLM credentials |
| LLM error handling | Mocked invalid JSON and invented-evidence outputs rejected |

## Browser environment

The host initially lacked `libnspr4`, `libnss3` and `libasound2`. System installation required an unavailable sudo password. Ubuntu packages were downloaded and extracted under `/tmp/ccu-browser-libs/`, without system installation. Browser tests then passed using:

```bash
LD_LIBRARY_PATH=/tmp/ccu-browser-libs/root/usr/lib/x86_64-linux-gnu \
ASTRO_TELEMETRY_DISABLED=1 BASE_PATH=/ccu-intelligence/ npm run test:browser
```

This temporary path is host-specific and is not part of the application. On a normal Linux development/CI machine, use `npx playwright install --with-deps chromium`. GitHub CI includes that installation step.

Astro 7 detects agent sessions and can automatically background preview servers. The browser-test configuration explicitly uses a dedicated foreground server on port 4322 with `--ignore-lock`. The normal developer preview remains on port 4321.

## Scope of the evidence

API smoke tests prove bounded metadata retrieval and deduplication, not source completeness or scientific verification. Collected live candidates remain in ignored local runtime files and are not exported to the public site. Corporate/manual sources have not been bulk-scraped or verified. Browser tests use explicitly fictional fixture projects.

There has been no paid-provider LLM call. GitHub credentials, repository branch protection, scheduled execution, artifact restoration against a real remote, PR creation and Pages deployment remain unverified until the owner provisions and authorizes the remote setup. Structural workflow validation does not prove those external integrations.
