"""Daily unpaid GDELT collection: one query per day into data/runtime/gdelt-cache, read by the research run.

GDELT throttles bursts from shared runner IPs, so instead of four queries in one research run, this job sends one
request a day. It picks the query whose last success is oldest (rotation that also retries yesterday's failure
first), fetches from one day before that success (or SEED_DAYS on first use) through today, and prunes old files.
A throttled request is retried once by the fetcher; then the failure is recorded and the job ends successfully.
"""

import json
import os
from datetime import UTC, date, datetime, timedelta

from ccu_intelligence.collect import GDELT_CACHE, Fetcher, RateLimited, gdelt_items, gdelt_params, registry

SEED_DAYS = 16  # first fetch covers a full 14-day window plus margin
KEEP_DAYS = 35
MAX_RECORDS = 150


def choose(sources, state: dict):
    return min(sources, key=lambda s: (state.get(s.source_id, {}).get("last_success") or "", s.source_id))


def main(today: date | None = None, fetcher: Fetcher | None = None) -> dict:
    today = today or datetime.now(UTC).date()
    GDELT_CACHE.mkdir(parents=True, exist_ok=True)
    state_path = GDELT_CACHE / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    sources = [s for s in registry() if s.access_method == "gdelt" and s.active and s.automated_access_approved]
    source = choose(sources, state)
    last = state.get(source.source_id, {}).get("last_success")
    since = max(date.fromisoformat(last) - timedelta(days=1), today - timedelta(days=SEED_DAYS)) if last else \
        today - timedelta(days=int(os.getenv("SEED_DAYS", SEED_DAYS)))
    entry = state.setdefault(source.source_id, {}) | {"last_attempt": str(today)}
    owned = fetcher is None
    fetcher = fetcher or Fetcher()
    try:
        raw = fetcher.get(str(source.endpoint), params=gdelt_params(source.query, since, today, MAX_RECORDS),
                          interval=source.minimum_interval_seconds)
        articles = json.loads(raw).get("articles", []) if raw.lstrip().startswith(b"{") else None
        if articles is None:
            gdelt_items(raw)  # raises RateLimited or a query error with GDELT's message
        folder = GDELT_CACHE / source.source_id
        folder.mkdir(exist_ok=True)
        (folder / f"{today}.json").write_text(json.dumps({
            "source_id": source.source_id, "since": str(since), "until": str(today),
            "fetched_at": datetime.now(UTC).isoformat(), "articles": articles}, ensure_ascii=False))
        entry |= {"last_success": str(today), "last_error": None, "articles": len(articles)}
    except Exception as exc:  # recorded and retried tomorrow; never fails the scheduled job
        detail = str(exc) if isinstance(exc, (RateLimited, ValueError)) else type(exc).__name__
        entry |= {"last_error": detail[:200]}
    finally:
        if owned:
            fetcher.client.close()
    state[source.source_id] = entry
    for path in GDELT_CACHE.glob("*/*.json"):
        if date.fromisoformat(path.stem) < today - timedelta(days=KEEP_DAYS):
            path.unlink()
    state_path.write_text(json.dumps(state, indent=2))
    print(json.dumps({"source": source.source_id, "since": str(since), "until": str(today)} | entry))
    return entry


if __name__ == "__main__":
    main()
