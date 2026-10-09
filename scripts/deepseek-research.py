"""GitHub Actions entrypoint: opt-in research only, no publishing or repository writes."""

import argparse
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ccu_intelligence.budget import Budget
from ccu_intelligence.editorial import window
from ccu_intelligence.workflow import execute

# Hard per-run ceilings; dispatch inputs may only lower them. Raising either needs a reviewed code change.
MAX_ANALYSES_CAP = 30
MAX_SPEND_USD_CAP = 0.50


def configuration():
    mode = os.getenv('RESEARCH_MODE', 'dry-run')
    if mode not in ('dry-run', 'paid'):
        raise ValueError('Invalid research mode')
    paid = mode == 'paid'
    if paid and os.getenv('ALLOW_PAID') != 'true':
        raise ValueError('Paid processing needs explicit repository opt-in')
    if paid and os.getenv('GITHUB_ACTIONS') == 'true' and os.getenv('GITHUB_RUN_ATTEMPT') != '1':
        raise ValueError('Paid reruns are disabled; inspect the previous ledger before a new dispatch')
    start, end = window(datetime.now(UTC).date())
    options = argparse.Namespace(
        since=start, until=end - timedelta(days=1), scheduled_publication=None,
        output=Path('data/runtime/deepseek-research') / mode / str(end),
        max_analyses=int(os.getenv('MAX_ANALYSES', '30')), max_requests=60,
        token_budget=int(os.getenv('TOKEN_BUDGET', '120000')),
        max_spend_usd=float(os.getenv('MAX_SPEND_USD', '0.50')),
        rate_ceiling=float(os.getenv('RATE_CEILING', '1.20')),
        max_output_tokens=1200, source_limit=15, allow_paid=paid, dry_run=not paid,
    )
    if not 0 <= options.max_analyses <= MAX_ANALYSES_CAP:
        raise ValueError(f'Maximum new analyses must be between 0 and {MAX_ANALYSES_CAP}')
    if not 0 <= options.max_spend_usd <= MAX_SPEND_USD_CAP:
        raise ValueError(f'Spending cap must be between 0 and {MAX_SPEND_USD_CAP} USD')
    Budget(max_requests=60, max_tokens=options.token_budget,
           max_spend_usd=options.max_spend_usd, usd_per_million_tokens=options.rate_ceiling)
    return options


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    try:
        options = configuration()
        if args.check:
            print('Research configuration valid; no API requests made.')
        else:
            execute(options)
    except (ValueError, TypeError, OSError):
        # No exception bodies or environment values: they may include untrusted inputs.
        raise SystemExit('Research stopped: check configuration, credentials, state and budget.') from None


if __name__ == '__main__':
    main()
