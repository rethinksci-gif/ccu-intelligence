"""Dispatch the existing deploy workflow and wait for its live-site confirmation."""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def gh(*args):
    return subprocess.check_output(['gh', *args], text=True)


def main(workflow):
    sha = subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    started = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    gh('workflow','run',workflow,'--ref',os.environ['DEFAULT_BRANCH'])
    run = None
    for _ in range(120):
        runs = json.loads(gh('run','list','--workflow',workflow,'--commit',sha,'--event','workflow_dispatch',
                             '--json','databaseId,createdAt,status,conclusion,url','--limit','10'))
        matching = [r for r in runs if r['createdAt'] >= started]
        if matching:
            run = min(matching,key=lambda r:r['databaseId'])
            if run['status']=='completed':
                break
        time.sleep(10)
    if not run or run['status']!='completed' or run['conclusion']!='success':
        raise RuntimeError('deployment failed or did not confirm before timeout: '+str(run and run['url']))
    out = Path('automation/runtime/confirmed')
    out.mkdir(parents=True,exist_ok=True)
    gh('run','download',str(run['databaseId']),'-n','live-confirmation','-D',str(out))
    confirmation = json.loads((out/'confirmation.json').read_text())
    if confirmation.get('status')!='confirmed' or confirmation.get('revision')!=sha:
        raise RuntimeError('deployment run did not confirm the committed revision')
    status_path=Path('automation/status.json')
    status=json.loads(status_path.read_text())
    status.update(deployment_status='confirmed', confirmed_revision=sha, deployment_run_url=run['url'],
                  last_confirmed_publication=confirmation.get('last_publication'),
                  last_successful_check=confirmation['confirmed_at'])
    if not status.get('last_publication'):
        status['last_publication'] = confirmation.get('last_publication')
    status_path.write_text(json.dumps(status,indent=2)+'\n')
    print(json.dumps({'deployment_run':run['url'],**confirmation},indent=2))


if __name__=='__main__':
    main(sys.argv[1])
