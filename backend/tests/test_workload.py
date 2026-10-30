"""Workload CSV parsing, fingerprinting, ranking and API validation."""
import pytest
from fastapi.testclient import TestClient

from app import workload as wl

CSV = (
    "query,calls,total_time,errors\n"
    "SELECT * FROM t WHERE id = 1,10,500,0\n"
    "SELECT * FROM t WHERE id = 22,5,250,1\n"
    "SELECT name FROM u,100,300,0\n"
)


def _run(csv_text, mapping):
    h, r = wl.read_csv(csv_text.encode())
    return wl.analyze(h, r, mapping)


def test_fingerprint_groups_literals():
    assert wl.fingerprint("select * from t where id = 1") == wl.fingerprint("SELECT *  FROM t WHERE id = 22")
    assert wl.fingerprint("select 'a'") == wl.fingerprint("select 'b'")


def test_grouping_and_ranking_by_total_time():
    out = _run(CSV, {"sql": "query", "count": "calls", "total_ms": "total_time", "errors": "errors"})
    g = out["groups"]
    assert len(g) == 2 and g[0]["executions"] == 15 and g[0]["total_ms"] == 750 and g[0]["errors"] == 1
    assert g[0]["rank"] == 1 and g[0]["avg_ms"] == 50 and out["score_basis"].startswith("total recorded")
    assert abs(sum(x["share_pct"] for x in g) - 100) < 0.1


def test_derived_total_flagged_and_count_fallback():
    out = _run("q,n,avg\nselect 1,4,10\n", {"sql": "q", "count": "n", "avg_ms": "avg"})
    assert out["groups"][0]["total_ms"] == 40 and out["groups"][0]["derived_total"]
    out = _run("q\nselect 1\nselect 2\n", {"sql": "q"})
    assert out["groups"][0]["executions"] == 2 and "count" in out["score_basis"]
    assert out["groups"][0]["total_ms"] is None  # nothing invented


def test_bad_rows_reported_not_silently_dropped():
    out = _run("q,t\nselect 1,abc\nselect 2,5\n", {"sql": "q", "total_ms": "t"})
    assert out["skipped_count"] == 1 and "not a number" in out["skipped"][0]["reason"]


@pytest.mark.parametrize("data,msg", [(b"", "empty"), (b"a,b\n", "no data"), (b"\xff\xfe\x00", "UTF-8")])
def test_read_csv_errors(data, msg):
    with pytest.raises(wl.WorkloadError, match=msg):
        wl.read_csv(data)


def test_mapping_validation():
    with pytest.raises(wl.WorkloadError, match="required"):
        _run(CSV, {})
    with pytest.raises(wl.WorkloadError, match="not in the file"):
        _run(CSV, {"sql": "nope"})


def test_api_preview_analyze_and_size_cap(monkeypatch):
    from app.main import app

    c = TestClient(app)
    p = c.post("/api/workload/preview", content=CSV).json()
    assert p["suggested_mapping"]["sql"] == "query" and p["row_count"] == 3
    a = c.post("/api/workload/analyze?sql=query&count=calls&total_ms=total_time", content=CSV)
    assert a.status_code == 200 and a.json()["groups"][0]["total_ms"] == 750
    assert c.post("/api/workload/analyze", content=CSV).status_code == 400
    monkeypatch.setattr(wl, "MAX_BYTES", 10)
    assert c.post("/api/workload/preview", content=CSV).status_code == 413
