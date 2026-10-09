"""Prepare a bounded, unpaid candidate draft for manual editorial review."""
import argparse
import json
from datetime import date, timedelta
from pathlib import Path

from ccu_intelligence.editorial import generate, window
from ccu_intelligence.models import Bundle
from ccu_intelligence.workflow import execute

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--as-of', type=date.fromisoformat, default=date.today())
args = parser.parse_args()
start, end = window(args.as_of)
output = Path('data/runtime') / f'scheduled-{end}'
report = execute(argparse.Namespace(
    since=start, until=end - timedelta(days=1), scheduled_publication=None,
    output=output, max_screenings=0, max_enrichments=0, max_requests=0,
    token_budget=16000, fetch_full_text=False,
))
bundle = Bundle.model_validate_json((output / 'bundle.json').read_text())
target = Path('src/content/issues') / f'{end}.md'
if target.exists():
    raise SystemExit('Existing editorial draft preserved; no overwrite')
path = generate(bundle, end, target.parent)
lines = ['\n## Candidate source inbox — not approved for publication\n']
for article in bundle.articles:
    if not report['triage'][article.article_id]['eligible']:
        continue
    from ccu_intelligence.editorial import safe_text
    lines += [f'- [{safe_text(article.title)}]({article.canonical_url}) — '
              f'{article.publication_date}; source: {article.source_id}. '
              'Metadata lead only; check the original before approving any claim.']
if len(lines) == 1:
    lines += ['No eligible leads in this bounded run. Do not fabricate stories.']
path.write_text(path.read_text() + '\n'.join(lines) + '\n')
review = Path('data/review') / str(end)
review.mkdir(parents=True, exist_ok=True)
(review / 'candidates.json').write_text(bundle.model_dump_json(indent=2))
(review / 'collection.json').write_text((output / 'collection.json').read_text())
(review / 'run.json').write_text(json.dumps({
    'coverage_start':str(start), 'coverage_end_exclusive':str(end),
    'model_calls':0, 'paid_calls_enabled':False,
    'candidate_count':len(bundle.articles),
    'eligible_leads':report['promising_candidates'],
}, indent=2))
print(path)
