import json
import os
from datetime import datetime, timezone
from pathlib import Path

Path('automation/run-result.json').write_text(json.dumps({
    'status': os.environ['RUN_OUTCOME'],
    'checked_at': datetime.now(timezone.utc).isoformat(),
    'run_url': 'https://github.com/' + os.environ['GITHUB_REPOSITORY'] + '/actions/runs/' + os.environ['GITHUB_RUN_ID'],
    'deployment_confirmation': 'Recorded separately in the deployment workflow live-confirmation artifact; dispatch is not deployment success'
}, indent=2))
