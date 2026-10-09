"""GitHub Actions entrypoint: opt-in research only, no publishing or repository writes."""

import argparse
import math
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from ccu_intelligence.pricing import roles
from ccu_intelligence.workflow import MAX_ANALYSES_CAP, MAX_SPEND_USD_CAP, MAX_TOKEN_BUDGET, execute

# Hard per-run ceilings live in workflow.py; dispatch inputs may only lower them.


def coverage(today: date) -> tuple[date, date]:
    """Inclusive coverage window. Default: the most recent COVERAGE_DAYS (14) complete UTC days, ending yesterday.

    COVERAGE_END (YYYY-MM-DD, inclusive) moves the end; it must be before today so every covered day is complete.
    """
    days = int(os.getenv('COVERAGE_DAYS') or 14)
    end = os.getenv('COVERAGE_END') or ''
    until = date.fromisoformat(end) if end else today - timedelta(days=1)
    if not 1 <= days <= 31:
        raise ValueError('Coverage must be 1–31 days')
    if until >= today:
        raise ValueError('Coverage must end before today (UTC)')
    return until - timedelta(days=days - 1), until


def configuration():
    mode = os.getenv('RESEARCH_MODE', 'dry-run')
    if mode not in ('dry-run', 'paid'):
        raise ValueError('Invalid research mode')
    paid = mode == 'paid'
    if paid and os.getenv('ALLOW_PAID') != 'true':
        raise ValueError('Paid processing needs explicit repository opt-in')
    if paid and os.getenv('GITHUB_ACTIONS') == 'true' and os.getenv('GITHUB_RUN_ATTEMPT') != '1':
        raise ValueError('Paid reruns are disabled; inspect the previous ledger before a new dispatch')
    since, until = coverage(datetime.now(UTC).date())
    options = argparse.Namespace(
        since=since, until=until, scheduled_publication=None,
        output=Path('data/runtime/deepseek-research') / mode / str(until + timedelta(days=1)),
        max_analyses=int(os.getenv('MAX_ANALYSES', str(MAX_ANALYSES_CAP))), max_requests=200,
        token_budget=int(os.getenv('TOKEN_BUDGET', '2000000')),
        max_spend_usd=float(os.getenv('MAX_SPEND_USD', str(MAX_SPEND_USD_CAP))),
        source_limit=None, allow_paid=paid, dry_run=not paid,
    )
    if not 0 <= options.max_analyses <= MAX_ANALYSES_CAP:
        raise ValueError(f'Maximum new analyses must be between 0 and {MAX_ANALYSES_CAP}')
    if not math.isfinite(options.max_spend_usd) or not 0 <= options.max_spend_usd <= MAX_SPEND_USD_CAP:
        raise ValueError(f'Spending cap must be between 0 and {MAX_SPEND_USD_CAP} USD')
    if not 1 <= options.token_budget <= MAX_TOKEN_BUDGET:
        raise ValueError(f'Token budget must be between 1 and {MAX_TOKEN_BUDGET}')
    roles()  # every configured model must be in the pricing table
    return options


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    try:
        options = configuration()
        if args.check:
            print(f'Research configuration valid; coverage {options.since} to {options.until} inclusive (UTC); '
                  'no API requests made.')
        else:
            execute(options)
    except (ValueError, TypeError, OSError):
        # No exception bodies or environment values: they may include untrusted inputs.
        raise SystemExit('Research stopped: check configuration, credentials, state and budget.') from None


if __name__ == '__main__':
    main()
