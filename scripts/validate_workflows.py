"""Local structural workflow checks; actionlint adds GitHub expression validation."""

import re
from pathlib import Path

import yaml

# Minimum majors: everything at or above runs on Node 24, not the deprecated Node 20 runtime.
MINIMUM_MAJOR = {
    "actions/checkout": 6,
    "actions/setup-python": 6,
    "actions/setup-node": 6,
    "actions/cache": 5,
    "actions/upload-artifact": 6,
    "actions/upload-pages-artifact": 4,
    "actions/deploy-pages": 5,
}

for path in Path(".github/workflows").glob("*.yml"):
    data = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
    assert "on" in data and "jobs" in data and "permissions" in data, path
    assert "concurrency" in data, path
    for name, job in data["jobs"].items():
        assert "runs-on" in job and "steps" in job, (path, name)
        assert job["runs-on"] == "ubuntu-24.04", (path, name, "pin the runner image")
        assert all("uses" in step or "run" in step for step in job["steps"]), path
        for step in job["steps"]:
            match = re.fullmatch(r"(actions/[\w-]+)(?:/[\w-]+)?@v(\d+)", step.get("uses", ""))
            if match and match.group(1) in MINIMUM_MAJOR:
                assert int(match.group(2)) >= MINIMUM_MAJOR[match.group(1)], (path, step["uses"])
    assert "pull_request_target" not in data["on"], path

research = yaml.load(Path(".github/workflows/deepseek-research.yml").read_text(), Loader=yaml.BaseLoader)
assert set(research["on"]) == {"workflow_dispatch"}, "paid research must stay manual: no schedule or push"
assert research["permissions"] == {"contents": "read"}, "research must never write to the repository"
assert research["env"]["LLM_MODEL"] == research["env"]["LLM_SCREENING_MODEL"] == "deepseek-flash"
assert not {"screening_model", "strong_model"} & research["on"]["workflow_dispatch"]["inputs"].keys()
print("Workflow structure, runners, action majors and permission declarations validated")
