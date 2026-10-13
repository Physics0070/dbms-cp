"""Settings must actually change behaviour, not just exist."""
import pytest

from app.config import get_settings
from app.optimizer.examples import generate_examples


@pytest.fixture
def env(monkeypatch):
    def set_(**kv):
        for k, v in kv.items():
            monkeypatch.setenv(k, str(v))
        get_settings.cache_clear()
    yield set_
    get_settings.cache_clear()


def test_cors_origins_come_from_config(env):
    env(CORS_ORIGINS="https://app.example.com, https://other.example.com ,")
    assert get_settings().cors_origin_list == ["https://app.example.com", "https://other.example.com"]


def test_example_limit_is_respected(env, ecommerce_adapter):
    env(EXAMPLE_LIMIT=2)
    assert len(generate_examples(ecommerce_adapter)) == 2
    assert len(generate_examples(ecommerce_adapter, limit=1)) == 1  # explicit argument wins


def test_history_path_is_configurable(env, tmp_path):
    from app import history_store
    target = tmp_path / "custom_history.json"
    env(HISTORY_PATH=str(target))
    assert history_store._default_path() == target
    env(HISTORY_PATH="")
    assert history_store._default_path().name == "query_history.json"


def test_openai_call_uses_configured_endpoint_and_options(env, monkeypatch):
    import httpx
    from app.optimizer import copilot

    env(OPENAI_API_URL="https://llm.internal/v1/chat", OPENAI_TEMPERATURE="0.9", OPENAI_TIMEOUT_S="7")
    seen = {}

    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return {"choices": [{"message": {"content": " hi "}}]}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen.update(url=url, temperature=json["temperature"], timeout=timeout)
        return FakeResp()

    monkeypatch.setattr(httpx, "post", fake_post)
    assert copilot._call_openai("key", "m", {}, None) == "hi"
    assert seen == {"url": "https://llm.internal/v1/chat", "temperature": 0.9, "timeout": 7.0}
