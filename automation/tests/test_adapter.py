import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from datetime import date
from pathlib import Path
from unittest.mock import patch

from automation import run as adapter
from automation.evidence_gate import CHECKS
from automation.validate import validate

TEXT='The laboratory reported 50 kWh at 200 C under dry conditions. This is an experimental result.'

class Day(date):
    @classmethod
    def today(cls):return cls(2026,10,31)

class AdapterTests(unittest.TestCase):
    def pipeline(self,count=4,broken=False,dates=None,today=None,why=None,role='primary'):
        def execute(args):
            self.args=args
            values=[];records=[]
            for index in range(count):
                url=f'https://example.org/{index}'
                values.append({'article_id':str(index),'publication_date':(dates or {}).get(index,'2026-10-20'),'url':url,'evidence_role':role,'source_name':'Carbon Herald',
                               'enrichment':{'headline':'Laboratory result','what_changed':TEXT,'why_it_matters':why,
                                             'practical_implication':None,'uncertainty':'Experimental result.', 'quotes':[TEXT]}})
                records.append({'article_id':str(index),'triage':{'eligible':True,'reason':'relevant'},'url':url})
            path=Path('data/runtime/autonomous-input')/(args.output.name+'.json')
            path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(values))
            return {'records':records}
        def original(url,authority,when):
            if broken and url.endswith('/0'):raise ValueError('broken source')
            return {'url':url,'authority':authority,'status':200,'date':when,'date_verified':True,'text':TEXT}
        def semantic(*args):return {'checks':dict.fromkeys(CHECKS,True),'reasons':[],'citations':[TEXT]}
        stack=ExitStack()
        stack.enter_context(patch.object(adapter,'execute',execute))
        stack.enter_context(patch.object(adapter,'original',original))
        stack.enter_context(patch.object(adapter,'Model',lambda **kwargs:semantic))
        day=type('Today',(date,),{'today':classmethod(lambda cls:cls.fromisoformat(today))}) if today else Day
        stack.enter_context(patch.object(adapter,'date',day))
        stack.enter_context(patch('automation.evidence_gate.date',day))
        return stack

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.cwd=os.getcwd();os.chdir(self.temp.name)
        Path('src/content/issues').mkdir(parents=True)

    def tearDown(self):
        os.chdir(self.cwd);self.temp.cleanup()

    def test_valid_publication_and_same_edition_rerun(self):
        with self.pipeline():
            self.assertEqual(adapter.run()['status'],'publish')
            validate()
            self.assertIn('publication_date: \'2026-10-31\'', Path('src/content/issues/auto-2026-10-26.md').read_text())
            original=Path('src/content/issues/auto-2026-10-26.md').read_bytes()
            self.assertEqual(adapter.run()['status'],'skipped')
            self.assertEqual(Path('src/content/issues/auto-2026-10-26.md').read_bytes(),original)

    def test_empty_collection(self):
        with self.pipeline(count=0):self.assertEqual(adapter.run()['status'],'skipped')
        self.assertFalse(list(Path('src/content/issues').glob('*.md')))

    def test_item_failure_allows_unrelated_verified_items(self):
        with self.pipeline(count=5,broken=True):self.assertEqual(adapter.run()['status'],'publish')
        records=json.loads(Path('automation/verification.json').read_text())
        self.assertEqual([r['status'] for r in records].count('QUARANTINED'),1)
        validate()

    def test_missing_key_never_authorizes_paid_calls(self):
        with self.pipeline(count=0),patch.dict(os.environ,{},clear=True):
            original_execute=adapter.execute
            def execute(args):
                self.assertFalse(args.allow_paid)
                self.assertTrue(args.dry_run)
                return original_execute(args)
            with patch.object(adapter,'execute',execute):self.assertEqual(adapter.run()['status'],'skipped')

    def test_compact_edition_after_retry_period(self):
        with self.pipeline(count=2):self.assertEqual(adapter.run()['status'],'publish')
        validate()
        page=Path('src/content/issues/auto-2026-10-26.md').read_text()
        self.assertIn('COMPACT EDITION — only 2 developments',page)
        self.assertIn('issue_number: 1',page)

    def test_compact_edition_waits_for_regular_retries(self):
        with self.pipeline(count=3,today='2026-10-28'):self.assertEqual(adapter.run()['status'],'skipped')
        self.assertFalse(list(Path('src/content/issues').glob('*.md')))

    def test_previous_window_is_backfilled_with_sequential_issue_numbers(self):
        dates={0:'2026-10-20',1:'2026-10-21',2:'2026-10-27',3:'2026-11-02',4:'2026-11-03',5:'2026-11-04'}
        with self.pipeline(count=6,dates=dates,today='2026-11-10'):status=adapter.run()
        self.assertEqual(status['windows'],{'2026-10-26':'published compact edition','2026-11-09':'published'})
        self.assertIn('issue_number: 1',Path('src/content/issues/auto-2026-10-26.md').read_text())
        self.assertIn('issue_number: 2',Path('src/content/issues/auto-2026-11-09.md').read_text())
        self.assertEqual(self.args.since,date(2026,10,12))
        validate()

    def test_collection_covers_only_closed_windows_within_workflow_limit(self):
        with self.pipeline(count=0,today='2026-11-22'):adapter.run()
        self.assertEqual((self.args.since,self.args.until),(date(2026,10,12),date(2026,11,8)))
        with self.pipeline(count=0,today='2026-12-06'):adapter.run()
        self.assertLessEqual((self.args.until-self.args.since).days+1,31)

    def test_optional_sentence_with_unsupported_number_is_dropped(self):
        with self.pipeline(why='This could cut costs by 40%.'):self.assertEqual(adapter.run()['status'],'publish')
        page=Path('src/content/issues/auto-2026-10-26.md').read_text()
        self.assertNotIn('40%',page)
        self.assertIn('Experimental result.',page)

    def test_trade_press_is_admitted_with_secondary_label(self):
        with self.pipeline(role='news'):self.assertEqual(adapter.run()['status'],'publish')
        page=Path('src/content/issues/auto-2026-10-26.md').read_text()
        self.assertIn('Reported by Carbon Herald (trade press)',page)
        self.assertIn('[Trade-press report](https://example.org/0)',page)
        self.assertNotIn('[Original source]',page)
        validate()

    def test_unreachable_doi_falls_back_to_open_access_copy(self):
        fetched=[]
        def original(url,authority,when):
            fetched.append(url)
            if 'doi.org' in url:raise ValueError('publisher refused')
            return {'url':url,'authority':authority,'status':200,'date':when,'date_verified':True,'text':TEXT}
        with self.pipeline(),patch.object(adapter,'original',original),\
             patch.object(adapter,'academic_copies',lambda url:['https://repository.example/copy/'+url.rsplit('/',1)[1]]),\
             patch.object(adapter,'execute',self.doi_execute()):
            self.assertEqual(adapter.run()['status'],'publish')
        self.assertIn('[Original source](https://repository.example/copy/0)',Path('src/content/issues/auto-2026-10-26.md').read_text())
        self.assertEqual(fetched[:2],['https://doi.org/10.1000/0','https://repository.example/copy/0'])

    def test_academic_copies_only_for_doi_links(self):
        self.assertEqual(adapter.academic_copies('https://example.org/article'),[])

    def doi_execute(self):
        def execute(args):
            values=[{'article_id':'0','publication_date':'2026-10-20','url':'https://doi.org/10.1000/0','evidence_role':'primary',
                     'enrichment':{'headline':'Laboratory result','what_changed':TEXT,'why_it_matters':None,
                                   'practical_implication':None,'uncertainty':'Experimental result.','quotes':[TEXT]}}]*4
            values=[dict(v,article_id=str(i),url=f'https://doi.org/10.1000/{i}') for i,v in enumerate(values)]
            path=Path('data/runtime/autonomous-input')/(args.output.name+'.json')
            path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(values))
            return {'records':[{'article_id':v['article_id'],'triage':{'eligible':True,'reason':'relevant'},'url':v['url']} for v in values]}
        return execute
