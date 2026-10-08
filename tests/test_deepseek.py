import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from ccu_intelligence.ai_draft import generate_ai
from ccu_intelligence.cli import curated
from ccu_intelligence.llm import run
from ccu_intelligence.settings import load_environment


def test_dotenv_preserves_environment_without_expansion(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("LLM_API_KEY=file-secret\nLLM_MODEL=${LLM_API_KEY}\n")
    monkeypatch.setenv("LLM_API_KEY", "existing-secret")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    load_environment(env)
    import os

    assert os.environ["LLM_API_KEY"] == "existing-secret"
    assert os.environ["LLM_MODEL"] == "${LLM_API_KEY}"


def test_deepseek_budget_usage_and_review_reset(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "fixture-key")
    monkeypatch.setenv("LLM_MODEL", "deepseek-flash")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.deepseek.com")
    result = dict(
        relevant=True,
        domains=["capture"],
        summary="Metadata only",
        uncertainty="No full text",
        claims=[
            dict(
                claim_id="c",
                text="Capture topic",
                evidence_ids=["e"],
                kind="analyst_inference",
                uncertainty="Title only",
                reviewer="fabricated",
            )
        ],
    )

    def handler(request):
        payload = json.loads(request.content)
        assert payload["thinking"] == {"type": "disabled"}
        assert payload["max_tokens"] == 2048
        assert request.url.path == "/chat/completions"
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "total_tokens": 150,
                    "completion_tokens_details": {"reasoning_tokens": 0},
                },
            },
        )

    usage = {}
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        output = run("extraction", "title", ["e"], client, usage=usage)
    assert output.claims[0].reviewer is None
    assert usage["total_tokens"] == 150
    assert usage["attempts"] == 1
    assert usage["status"] == "validated"


@pytest.mark.parametrize("finish,status", [("length", 200), ("stop", 401)])
def test_no_retry_for_truncation_or_auth_failure(monkeypatch, finish, status):
    monkeypatch.setenv("LLM_API_KEY", "fixture-key")
    monkeypatch.setenv("LLM_MODEL", "deepseek-flash")
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status, json={"choices": [{"finish_reason": finish, "message": {"content": "{}"}}]}
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert run("extraction", "title", ["e"], client) is None
    assert len(calls) == 1


def test_ai_cannot_write_site_or_use_sample(tmp_path):
    with pytest.raises(ValueError, match="data/runtime"):
        generate_ai(curated(), date(2026, 10, 12), tmp_path, "sample-article-0")
    with pytest.raises(ValueError, match="real collected"):
        generate_ai(curated(), date(2026, 10, 12), Path("data/runtime/test-no-write"), "sample-article-0")
