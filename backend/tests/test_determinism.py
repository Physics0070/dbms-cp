"""The optimizer must give the same answer on every run.

Python randomizes string hashing per process, so any code that iterates a `set` of
relation names can break cost ties differently from one server start to the next.
Each seed below runs in its own interpreter to expose that.
"""
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent

PROBE = """
import os, sys
sys.path.insert(0, ".")
from app.database.sqlite_adapter import SqliteAdapter
from app.optimizer.examples import generate_examples
from app.optimizer.orchestrator import optimize_query
a = SqliteAdapter(os.environ['DATABASE_PATH'])
rows = []
for e in generate_examples(a):
    r = optimize_query(a, e["sql"], run_index_advisor=False)
    rows.append((r["optimization"]["selected"]["join_order"],
                 round(r["summary"]["selected_total_cost"], 4),
                 r["optimized_query"]["status"], r["optimized_query"]["sql"]))
print(rows)
"""


def _run(db_path: str, seed: int) -> str:
    import os
    env = dict(os.environ, PYTHONHASHSEED=str(seed), DATABASE_PATH=db_path,
               PYTHONIOENCODING="utf-8")
    p = subprocess.run([sys.executable, "-c", PROBE], cwd=BACKEND, env=env,
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr
    return p.stdout


def test_plan_and_rewrite_independent_of_hash_seed(ecommerce_adapter):
    db = str(ecommerce_adapter.path)
    outputs = {seed: _run(db, seed) for seed in (0, 1, 2, 3)}
    assert len(set(outputs.values())) == 1, "optimizer output changed with PYTHONHASHSEED"
