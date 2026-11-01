import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from automation.confirm import confirm, receipt
from automation.evidence_gate import CHECKS, Model, digest, numbers, verify
from automation.validate import validate

TEXT = 'On 2026-10-01 the official laboratory measured 50 kWh at 200 C under dry conditions. The result is experimental, not operational capacity.'


def fixture():
    candidate={'id':'fixture-1','url':'https://example.org/report','date':'2026-10-01',
               'claims':[{'en':'The laboratory measured 50 kWh at 200 C under dry conditions.',
                          'quote':'the official laboratory measured 50 kWh at 200 C under dry conditions.'}]}
    source={'status':200,'url':candidate['url'],'date':candidate['date'],'date_verified':True,'authority':'official','text':TEXT}
    return candidate,source


def support(instruction,data):
    return {'checks':{key:True for key in CHECKS},'reasons':[],
            'citations':['the official laboratory measured 50 kWh at 200 C under dry conditions.']}


class EvidenceCases(unittest.TestCase):
    def test_valid_article_eligible(self):
        c,s=fixture()
        self.assertEqual(verify(c,s,support)['status'],'VERIFIED')

    def test_invalid_article_quarantined(self):
        c,s=fixture(); c['claims'][0]['en']='<script>unsafe</script>'
        self.assertEqual(verify(c,s,support)['status'],'QUARANTINED')

    def test_broken_link(self):
        c,s=fixture();s['status']=404
        self.assertEqual(verify(c,s,support)['status'],'QUARANTINED')

    def test_conflicting_unit_with_same_number(self):
        c,s=fixture();c['claims'][0]['en']=c['claims'][0]['en'].replace('kWh','MWh')
        self.assertEqual(verify(c,s,support)['status'],'QUARANTINED')

    def test_missing_source_evidence(self):
        c,s=fixture();s['text']='No evidence available'
        self.assertEqual(verify(c,s,support)['status'],'QUARANTINED')

    def test_duplicated_article(self):
        c,s=fixture()
        self.assertEqual(verify(c,s,support,{c['url']})['status'],'REJECTED')

    def test_conflicting_numbers(self):
        c,s=fixture();c['claims'][0]['en']=c['claims'][0]['en'].replace('50','500')
        self.assertEqual(verify(c,s,support)['status'],'QUARANTINED')

    def test_wrong_policy_effective_date(self):
        c,s=fixture()
        def invalid(*args):
            result=support(*args)
            result['checks']['legal_status_effective_date']=False
            result['reasons']=['Adoption date is not the application date']
            return result
        self.assertEqual(verify(c,s,invalid)['status'],'QUARANTINED')

    def test_missing_key(self):
        c,s=fixture()
        with patch.dict(os.environ,{},clear=True):
            self.assertEqual(verify(c,s,Model())['status'],'QUARANTINED')

    def test_semantic_fail_does_not_block_other_item(self):
        c,s=fixture()
        bad=copy.deepcopy(c);bad['claims'][0]['quote']='fabricated quotation of something else'
        self.assertEqual([verify(x,s,support)['status'] for x in [bad,c]],['QUARANTINED','VERIFIED'])

    def test_model_agreement_cannot_supply_evidence(self):
        c,s=fixture();s['authority']='media'
        self.assertEqual(verify(c,s,support)['status'],'QUARANTINED')

    def test_bilingual_semantic_mismatch(self):
        c,s=fixture();c['bilingual']=True;c['claims'][0]['zh']='在 200 C 下运行容量为 50 kWh。'
        def wrong(*args):
            result=support(*args);result['checks']['translation_meaning']=False
            return result
        self.assertEqual(verify(c,s,wrong)['status'],'QUARANTINED')

    def test_incomplete_verifier(self):
        c,s=fixture()
        self.assertEqual(verify(c,s,lambda *args:{'checks':{'support':True}})['status'],'QUARANTINED')

    def test_chinese_attached_numbers_match_english(self):
        self.assertEqual(numbers('2026年增长16%，容量50kWh'), numbers('In 2026 growth was 16%, capacity 50kWh'))
        self.assertNotEqual(numbers('-20 °C'), numbers('20 °C'))

    def test_chinese_dates_and_scale_words_match_english(self):
        self.assertEqual(numbers('2026年10月29日签署，规模4.8万吨'), numbers('Signed on 29 October 2026 for 48,000 tonnes'))
        self.assertEqual(numbers('10月29日宣布'), numbers('announced on October 29'))
        self.assertEqual(numbers('投资12亿美元'), numbers('investing $1.2 billion'))
        self.assertNotEqual(numbers('2026年10月29日'), numbers('29 November 2026'))

    def test_claim_date_without_year_supported_by_dated_source(self):
        c,s=fixture();c['bilingual']=True;s['text']='On October 1, 2026 '+TEXT
        c['claims'][0]['en']='On 1 October the laboratory measured 50 kWh at 200 C under dry conditions.'
        c['claims'][0]['zh']='10月1日，该实验室在 200 C 干燥条件下测得 50 kWh。'
        self.assertEqual(verify(c,s,support)['status'],'VERIFIED')

    def test_confirmation_notes_do_not_fail_review(self):
        c,s=fixture()
        def noted(*args):
            result=support(*args);del result['reasons']
            result.update(errors=[],notes=['The 50 kWh figure is supported by the source.'])
            return result
        report=verify(c,s,noted)
        self.assertEqual(report['status'],'VERIFIED')
        self.assertEqual(report['notes'],['The 50 kWh figure is supported by the source.'])

    def test_reported_errors_fail_review(self):
        c,s=fixture()
        def erroneous(*args):
            result=support(*args);result['errors']=['Capacity is planned, not operational']
            return result
        self.assertEqual(verify(c,s,erroneous)['status'],'QUARANTINED')

    def test_negated_check_name_is_not_accepted(self):
        c,s=fixture()
        def legacy(*args):
            result=support(*args);del result['checks']['no_contradictions'];result['checks']['contradictions']=False
            return result
        self.assertEqual(verify(c,s,legacy)['status'],'QUARANTINED')

    def test_wrong_original_date(self):
        c,s=fixture();s['date']='2026-09-01'
        self.assertEqual(verify(c,s,support)['status'],'QUARANTINED')


class PublicationCases(unittest.TestCase):
    def test_build_failure_no_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):receipt(Path(tmp),'sha')
            self.assertFalse((Path(tmp)/'publication-receipt.json').exists())

    def test_live_success_and_deployment_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'index.html').write_text('Publication identifier: TEST-001')
            expected=receipt(root,'sha',root)
            files={'publication-receipt.json':json.dumps(expected).encode(),'index.html':(root/'index.html').read_bytes()}
            self.assertEqual(confirm('',expected,files.__getitem__)['status'],'confirmed')
            files['index.html']=b'previous known good publication'
            with self.assertRaises(ValueError):confirm('',expected,files.__getitem__)

    def test_rerunning_same_receipt_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'index.html').write_text('TEST-001')
            self.assertEqual(receipt(root,'sha',root),receipt(root,'sha',root))

    def test_built_publication_must_contain_expected_identifier(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous=os.getcwd()
            try:
                os.chdir(tmp)
                Path('automation/publications').mkdir(parents=True)
                Path('automation/publications/test.json').write_text(json.dumps({
                    'id':'EXPECTED-001','file':'issues/test.md'}))
                root=Path('dist');(root/'issues/test').mkdir(parents=True)
                (root/'issues/test/index.html').write_text('Old content without the expected edition')
                with self.assertRaisesRegex(ValueError,'identifier missing'):
                    receipt(root,'sha')
            finally:
                os.chdir(previous)

    def test_missing_live_receipt_is_failure(self):
        with self.assertRaises(KeyError):confirm('',{'revision':'sha','pages':{}},{}.__getitem__)

    def test_manifest_detects_changed_article(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'automation/publications').mkdir(parents=True)
            text='TEST-001 https://example.org/report'
            (root/'edition.md').write_text(text)
            record={'id':'TEST-001','file':'edition.md','sha256':digest(text),
                    'items':[{'status':'VERIFIED','reasons':[],'source_url':'https://example.org/report'}]}
            (root/'automation/publications/test.json').write_text(json.dumps(record))
            validate(root)
            (root/'edition.md').write_text(text+' unsupported change')
            with self.assertRaises(ValueError):validate(root)


if __name__=='__main__':unittest.main()
