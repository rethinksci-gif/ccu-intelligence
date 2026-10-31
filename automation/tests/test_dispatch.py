import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from automation import dispatch


class DeploymentTransactionTests(unittest.TestCase):
    def test_failed_deploy_preserves_previous_confirmed_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous=os.getcwd()
            try:
                os.chdir(tmp)
                Path('automation').mkdir()
                path=Path('automation/status.json')
                original='{"confirmed_revision":"last-known-good"}'
                path.write_text(original)
                failed=[{'databaseId':1,'createdAt':'2999-01-01T00:00:00Z','status':'completed',
                         'conclusion':'failure','url':'https://example.org/run/1'}]
                with patch.dict(os.environ,{'DEFAULT_BRANCH':'main'}), \
                     patch.object(dispatch.subprocess,'check_output',return_value='new-revision\n'), \
                     patch.object(dispatch,'gh',side_effect=['',json.dumps(failed)]):
                    with self.assertRaisesRegex(RuntimeError,'deployment failed'):
                        dispatch.main('pages.yml')
                self.assertEqual(path.read_text(),original)
            finally:
                os.chdir(previous)

    def test_successful_job_without_matching_live_confirmation_is_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous=os.getcwd()
            try:
                os.chdir(tmp)
                Path('automation/runtime/confirmed').mkdir(parents=True)
                path=Path('automation/status.json');path.write_text('{"confirmed_revision":"last-known-good"}')
                Path('automation/runtime/confirmed/confirmation.json').write_text('{"status":"confirmed","revision":"wrong"}')
                success=[{'databaseId':1,'createdAt':'2999-01-01T00:00:00Z','status':'completed',
                          'conclusion':'success','url':'https://example.org/run/1'}]
                with patch.dict(os.environ,{'DEFAULT_BRANCH':'main'}), \
                     patch.object(dispatch.subprocess,'check_output',return_value='new-revision\n'), \
                     patch.object(dispatch,'gh',side_effect=['',json.dumps(success),'']):
                    with self.assertRaisesRegex(RuntimeError,'did not confirm'):
                        dispatch.main('pages.yml')
                self.assertEqual(json.loads(path.read_text())['confirmed_revision'],'last-known-good')
            finally:
                os.chdir(previous)
