"""Copilot: offline text is grounded in the input; external calls are minimised and disclosed."""
import json
import re

import pytest

from app.config import get_settings
from app.optimizer import copilot
from app.optimizer.examples import generate_examples
from app.optimizer.orchestrator import optimize_query

_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set[float]:
    return {round(float(m.replace(",", "")), 2) for m in _NUM.findall(text)}


def _values(o):
    """All string values (JSON keys such as join_orders_considered are structure, not data)."""
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for v in o.values():
            yield from _values(v)
    elif isinstance(o, list):
        for v in o:
            yield from _values(v)


def _payload(adapter, benchmark=True):
    sql = next(e["sql"] for e in generate_examples(adapter) if e["kind"] in ("join", "multi-join"))
    return optimize_query(adapter, sql, run_benchmark=benchmark, run_index_advisor=True)


@pytest.mark.parametrize("adapter_name", ["ecommerce_adapter", "library_adapter"])
@pytest.mark.parametrize("benchmark", [True, False])
def test_offline_text_contains_no_invented_numbers(request, adapter_name, benchmark):
    payload = _payload(request.getfixturevalue(adapter_name), benchmark)
    text = copilot.explain(payload)["explanation"]
    allowed = _numbers(json.dumps(payload, default=str))
    invented = _numbers(text) - allowed
    assert not invented, f"numbers not in the optimizer output: {sorted(invented)}"


def test_offline_has_required_sections_and_discloses_no_external_ai(ecommerce_adapter, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    get_settings.cache_clear()
    r = copilot.explain(_payload(ecommerce_adapter, benchmark=False))
    assert r["external_ai_used"] is False and r["source"] == "offline" and r["model"] is None
    for h in ("Selected plan", "Why it may be expensive", "What limits confidence", "Most useful next experiment"):
        assert h in r["explanation"]
    assert "Run the benchmark" in r["explanation"]  # nothing measured yet -> that is the experiment


def test_outbound_context_has_no_literals_rows_or_backend_name(ecommerce_adapter):
    payload = _payload(ecommerce_adapter)
    payload["sql"] = "SELECT * FROM orders WHERE status = 'secret_value' AND total > 12345"
    out, _ = copilot._prepare_outbound(copilot.build_context(payload), send_schema=True)
    blob = json.dumps(out)
    assert "secret_value" not in blob and "12345" not in blob
    assert out["database_backend"] is None


def test_schema_obfuscation_round_trip(ecommerce_adapter):
    payload = _payload(ecommerce_adapter)
    payload["sql"] = "SELECT o.status FROM orders o JOIN customers c ON o.customer_id = c.customer_id"
    out, mapping = copilot._prepare_outbound(copilot.build_context(payload), send_schema=False)
    blob = " ".join(_values(out)).lower()
    for name in ("orders", "customers", "customer_id"):
        assert name not in blob
    assert mapping and "orders" in mapping.values()
    assert copilot._restore("scan of ident_0", {"ident_0": "orders"}) == "scan of orders"


def test_external_call_is_labelled_and_never_gets_credentials(ecommerce_adapter, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret-key-123456")
    monkeypatch.setenv("COPILOT_SEND_SCHEMA", "false")
    get_settings.cache_clear()
    seen = {}

    def fake(key, model, context, question):
        seen["context"] = json.dumps(context)
        return "ident_0 looks like the hot spot"

    monkeypatch.setattr(copilot, "_call_openai", fake)
    r = copilot.explain(_payload(ecommerce_adapter))
    get_settings.cache_clear()
    assert r["external_ai_used"] is True and r["source"] == "openai"
    assert "hypotheses" in r["explanation"].lower()
    assert "placeholders" in r["disclosure"] and "no credentials" in r["disclosure"].lower()
    assert "sk-test" not in seen["context"]
    assert "orders" not in " ".join(_values(json.loads(seen["context"]))).lower()
    assert "ident_0" not in r["explanation"]  # restored to the real name


def test_external_failure_falls_back_to_local(ecommerce_adapter, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret-key-123456")
    get_settings.cache_clear()

    def boom(*a, **k):
        raise RuntimeError("down, Authorization: Bearer sk-test-secret-key-123456")

    monkeypatch.setattr(copilot, "_call_openai", boom)
    r = copilot.explain(_payload(ecommerce_adapter, benchmark=False))
    get_settings.cache_clear()
    assert r["external_ai_used"] is False and "sk-test-secret" not in r["warning"]
    assert "Selected plan" in r["explanation"]
