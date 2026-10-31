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
    def pipeline(self,count=4,broken=False):
        def execute(args):
            values=[];records=[]
            for index in range(count):
                url=f'https://example.org/{index}'
                values.append({'article_id':str(index),'publication_date':'2026-10-20','url':url,'evidence_role':'primary',
                               'enrichment':{'headline':'Laboratory result','what_changed':TEXT,'why_it_matters':None,
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
        stack.enter_context(patch.object(adapter,'date',Day))
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
