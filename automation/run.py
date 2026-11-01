"""Promote the existing research pipeline's verified briefs through original-source gates."""
import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from automation.evidence_gate import Model, digest, now, numbers, verify, write
from automation.source import original
from ccu_intelligence.editorial import read_issue, safe_text, window
from ccu_intelligence.workflow import execute


FIRST_WINDOW = date(2026, 10, 26)  # Issue 001 and the closed 12 October draft precede the automatic windows.
FULL, COMPACT = 4, 2  # verified developments for a regular edition / a compact edition
COMPACT_AFTER = 5  # days of daily retries for a regular edition before a compact one is allowed
BACKFILL = 2  # most recent closed windows still eligible for publication
MAX_COLLECTION_DAYS = 31  # limit enforced by the research workflow
REQUIRED_FIELDS = ('headline', 'what_changed', 'uncertainty')
OPTIONAL_FIELDS = ('why_it_matters', 'practical_implication')


def windows(today):
    """Closed fourteen-day windows (by exclusive end date) that may still publish, oldest first."""
    end = window(today)[1]
    return [w for w in (end - timedelta(days=14 * i) for i in reversed(range(BACKFILL))) if w >= FIRST_WINDOW]


def claims(brief, source):
    """One claim per brief field, each with a verbatim excerpt; optional fields with unsupported numbers are dropped."""
    quote = next((q for q in brief.get('quotes') or [] if isinstance(q, str) and len(q.strip()) >= 20 and q in source['text']), '')
    kept = []
    for field in REQUIRED_FIELDS + OPTIONAL_FIELDS:
        text = brief.get(field)
        if not text:
            continue
        if field in OPTIONAL_FIELDS and numbers(text) - numbers(source['text']):
            continue
        kept.append({'field': field, 'en': text, 'quote': quote})
    return kept


def edition(good, start, end, compact, existing):
    stamp = now()
    meta = {'title':f'CCU Intelligence — {end}', 'issue_number':max((m.get('issue_number', 0) for m in existing), default=0)+1,
            'publication_date':str(date.today()),'coverage_start':str(start),'coverage_end':str(end),
            'featured_topics':['Verified developments'],'source_count':len(good),
            'editorial_status':'research_published','last_updated':stamp,'sample':False,
            'publication_authorization':'automated-evidence-gate-v1',
            'reviewer':'automated-evidence-gate-v1','reviewed_at':stamp}
    body = ['> RESEARCH EDITION — automatically verified against original sources; full editorial review remains incomplete.',
            '> Verification establishes source support, not independent replication of reported results.', '']
    if compact:
        body += [f'> COMPACT EDITION — only {len(good)} developments passed original-source verification, fewer than '
                 f'the usual {FULL}. It is published to keep the biweekly cadence; the gap is not filled with speculation.', '']
    body += [f'Publication identifier: CCU-{end}', '', '## Verified developments', '']
    for candidate in good:
        text = {c['field']: c['en'] for c in candidate['claims']}
        body += ['### '+safe_text(text['headline']), '', safe_text(text['what_changed']), '']
        body += [x for field in OPTIONAL_FIELDS if field in text for x in (safe_text(text[field]), '')]
        body += ['**Uncertainty:** '+safe_text(text['uncertainty']), '',
                 f"[Original source]({candidate['url']}) · Published {candidate['date']}", '']
    return '---\n'+yaml.safe_dump(meta, sort_keys=False)+'---\n\n'+'\n'.join(body)+'\n'


def run():
    today = date.today()
    previous_path = Path('automation/status.json')
    previous = json.loads(previous_path.read_text()) if previous_path.exists() else {}
    issues = Path('src/content/issues')
    existing = [read_issue(p)[0] for p in issues.glob('*.md')]
    def published(end):
        return Path(f'automation/publications/CCU-{end}.json').exists() or (issues/f'auto-{end}.md').exists() or any(
            str(m.get('coverage_end')) == str(end) and m.get('editorial_status') in ('published', 'research_published') for m in existing)
    open_windows = [w for w in windows(today) if not published(w)]
    status = {'checked_at':now(), 'status':'running', 'window':str(window(today)[1]),
              'last_publication':previous.get('last_publication'),
              'last_successful_check':previous.get('last_successful_check'), 'reasons':[], 'windows':{}}
    reports = []
    output = Path('data/runtime') / ('autonomous-' + today.isoformat())
    try:
        if not open_windows:
            status.update(status='skipped', reasons=['edition already published'], last_successful_check=now())
            return status
        # Items from the still-open window cannot publish yet; keep enrichment budget for closed windows.
        until = min(today - timedelta(days=1), open_windows[-1] - timedelta(days=1))
        since = max(open_windows[0] - timedelta(days=14), until - timedelta(days=MAX_COLLECTION_DAYS - 1))
        report = execute(argparse.Namespace(
            since=since, until=until, scheduled_publication=None,
            output=output, max_screenings=40, max_enrichments=15, max_requests=100,
            token_budget=600000, max_spend_usd=1.50, source_limit=2,
            allow_paid=bool(os.getenv('LLM_API_KEY')), dry_run=not bool(os.getenv('LLM_API_KEY')),
            fetch_full_text=True, google_news=False))
        records = {r['article_id']:r for r in report['records']}
        candidates = json.loads((Path('data/runtime/autonomous-input')/(output.name+'.json')).read_text())
        good = {w:[] for w in open_windows}
        model = Model(limit=15)
        seen = set()
        for item in candidates:
            brief = item['enrichment']
            candidate = {'id':item['article_id'], 'date':item['publication_date'], 'url':item['url'], 'claims':[]}
            target = next((w for w in open_windows if w-timedelta(days=14) <= date.fromisoformat(str(item['publication_date'])) < w), None)
            try:
                if target is None:
                    check = {'id':item['article_id'], 'status':'REJECTED', 'source_url':item['url'], 'reasons':['outside publication window']}
                else:
                    source = original(item['url'], 'primary' if item['evidence_role']=='primary' else 'secondary', item['publication_date'])
                    candidate['url'] = source['url']
                    candidate['claims'] = claims(brief, source)
                    check = verify(candidate, source, model, seen)
            except Exception as exc:
                check = {'id':item['article_id'], 'status':'QUARANTINED', 'source_url':item['url'],
                         'reasons':['original-source extraction failed: '+type(exc).__name__]}
            reports.append(check)
            if check['status']=='VERIFIED':
                check['window'] = str(target)
                check['eligible_for_window'] = True
                good[target].append(candidate)
                seen.add(candidate['url'])
        for cid, item in records.items():
            if cid not in {r['id'] for r in reports}:
                rejected = not item['triage']['eligible'] or str(item.get('selection','')).startswith('duplicate')
                reports.append({'id':cid,'status':'REJECTED' if rejected else 'QUARANTINED',
                                'source_url':item['url'], 'reasons':[item.get('enrichment_status') or item.get('selection') or item['triage']['reason']]})
        published_any = False
        for end in open_windows:
            verified = good[end]
            compact = FULL > len(verified) >= COMPACT and today >= end + timedelta(days=COMPACT_AFTER)
            if len(verified) < FULL and not compact:
                status['windows'][str(end)] = f'skipped: {len(verified)} original-source verified developments (regular edition needs {FULL}' + (
                    f', compact edition {COMPACT} from {end+timedelta(days=COMPACT_AFTER)})' if len(verified) >= COMPACT else f', compact edition {COMPACT})')
                continue
            target = issues / f'auto-{end}.md'
            content = edition(verified, end-timedelta(days=14), end, compact, existing)
            target.write_text(content)
            existing.append(read_issue(target)[0])
            urls = {c['url'] for c in verified}
            write(f'automation/publications/CCU-{end}.json', {'id':f'CCU-{end}','file':str(target),'compact':compact,
                  'sha256':digest(content),'items':[r for r in reports if r['status']=='VERIFIED' and r.get('window')==str(end) and r['source_url'] in urls]})
            status['windows'][str(end)] = 'published compact edition' if compact else 'published'
            status['last_publication'] = f'CCU-{end}'
            published_any = True
        if published_any:
            status.update(status='publish')
        else:
            status.update(status='skipped', reasons=['fewer than four original-source verified developments']+list(status['windows'].values()))
        status['last_successful_check']=now()
    except Exception as exc:
        status.update(status='failed',reasons=[type(exc).__name__ + ': no content may be committed'])
        raise
    finally:
        write('automation/verification.json',reports)
        write(previous_path,status)
    return status


if __name__=='__main__':
    print(json.dumps(run(),indent=2))
