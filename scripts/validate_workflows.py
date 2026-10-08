"""Local structural workflow checks; actionlint adds GitHub expression validation."""

from pathlib import Path

import yaml

for path in Path(".github/workflows").glob("*.yml"):
    data = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
    assert "on" in data and "jobs" in data and "permissions" in data, path
    assert "concurrency" in data, path
    for name, job in data["jobs"].items():
        assert "runs-on" in job and "steps" in job, (path, name)
        assert all("uses" in step or "run" in step for step in job["steps"]), path
    assert "pull_request_target" not in data["on"], path
print("Workflow structure and permission declarations validated")
