"""Promote the existing research pipeline's verified briefs through original-source gates."""
import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from automation.evidence_gate import Model, digest, now, verify, write
from automation.source import original
from ccu_intelligence.editorial import read_issue, safe_text, window
from ccu_intelligence.workflow import execute


def run():
    start, end = window(date.today())
    previous_path = Path('automation/status.json')
    previous = json.loads(previous_path.read_text()) if previous_path.exists() else {}
    status = {'checked_at':now(), 'status':'running', 'window':str(end),
              'last_publication':previous.get('last_publication'),
              'last_successful_check':previous.get('last_successful_check'), 'reasons':[]}
    reports = []
    output = Path('data/runtime') / ('autonomous-' + date.today().isoformat())
    try:
        report = execute(argparse.Namespace(
            since=start, until=date.today()-timedelta(days=1), scheduled_publication=None,
            output=output, max_screenings=20, max_enrichments=6, max_requests=40,
            token_budget=250000, max_spend_usd=0.75, source_limit=2,
            allow_paid=bool(os.getenv('LLM_API_KEY')), dry_run=not bool(os.getenv('LLM_API_KEY')),
            fetch_full_text=True, google_news=False))
        records = {r['article_id']:r for r in report['records']}
        candidates = json.loads((Path('data/runtime/autonomous-input')/(output.name+'.json')).read_text())
        good = []
        model = Model(limit=6)
        seen = set()
        for item in candidates:
            brief = item['enrichment']
            claim = '\n'.join([brief['headline'], brief['what_changed'], brief.get('why_it_matters') or '',
                               brief.get('practical_implication') or '', brief['uncertainty']])
            candidate = {'id':item['article_id'], 'date':item['publication_date'], 'url':item['url'],
                         'claims':[{'en':claim, 'quote':(brief.get('quotes') or [''])[0]}]}
            try:
                source = original(item['url'], 'primary' if item['evidence_role']=='primary' else 'secondary', item['publication_date'])
                candidate['url'] = source['url']
                check = verify(candidate, source, model, seen)
            except Exception as exc:
                check = {'id':item['article_id'], 'status':'QUARANTINED', 'source_url':item['url'],
                         'reasons':['original-source extraction failed: '+type(exc).__name__]}
            reports.append(check)
            if check['status']=='VERIFIED':
                check['eligible_for_window'] = start <= date.fromisoformat(candidate['date']) < end
                if check['eligible_for_window']:
                    good.append((candidate, brief))
                seen.add(candidate['url'])
        for cid, item in records.items():
            if cid not in {r['id'] for r in reports}:
                rejected = not item['triage']['eligible'] or str(item.get('selection','')).startswith('duplicate')
                reports.append({'id':cid,'status':'REJECTED' if rejected else 'QUARANTINED',
                                'source_url':item['url'], 'reasons':[item.get('enrichment_status') or item.get('selection') or item['triage']['reason']]})
        target = Path('src/content/issues') / f'auto-{end}.md'
        existing = [read_issue(p)[0] for p in target.parent.glob('*.md')]
        if target.exists() or any(str(m.get('coverage_end')) == str(end) and m.get('editorial_status') in ('published', 'research_published') for m in existing):
            status.update(status='skipped', reasons=['edition already published'])
        elif len(good)<4:
            status.update(status='skipped', reasons=['fewer than four original-source verified developments'])
        else:
            stamp = now()
            meta = {'title':f'CCU Intelligence — {end}', 'issue_number':(end-date(2026,1,5)).days//14+1,
                    'publication_date':str(date.today()),'coverage_start':str(start),'coverage_end':str(end),
                    'featured_topics':['Verified developments'],'source_count':len(good),
                    'editorial_status':'research_published','last_updated':stamp,'sample':False,
                    'publication_authorization':'automated-evidence-gate-v1',
                    'reviewer':'automated-evidence-gate-v1','reviewed_at':stamp}
            body = ['> RESEARCH EDITION — automatically verified against original sources; full editorial review remains incomplete.',
                    '> Verification establishes source support, not independent replication of reported results.', '',
                    f'Publication identifier: CCU-{end}', '', '## Verified developments', '']
            for candidate, brief in good:
                body += ['### '+safe_text(brief['headline']), '', safe_text(brief['what_changed']), '',
                         safe_text(brief.get('why_it_matters') or ''), '',safe_text(brief.get('practical_implication') or ''),'',
                         '**Uncertainty:** '+safe_text(brief['uncertainty']), '',
                         f"[Original source]({candidate['url']}) · Published {candidate['date']}", '']
            content = '---\n'+yaml.safe_dump(meta, sort_keys=False)+'---\n\n'+'\n'.join(body)+'\n'
            target.write_text(content)
            write(f'automation/publications/CCU-{end}.json', {'id':f'CCU-{end}','file':str(target),
                  'sha256':digest(content),'items':[r for r in reports if r['status']=='VERIFIED' and r.get('eligible_for_window')]})
            status.update(status='publish',last_publication=f'CCU-{end}')
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
