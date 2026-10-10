"""Schema discovery + statistics endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ...database.turso_adapter import TursoAdapter
from ..deps import adapter_dep

router = APIRouter(tags=["schema"])


def _table_to_dict(adapter: TursoAdapter, name: str, with_rows: bool = True) -> dict:
    ts = adapter.get_table_schema(name)
    d = {
        "name": ts.name,
        "primary_key": ts.primary_key,
        "columns": [
            {
                "name": c.name,
                "data_type": c.data_type,
                "nullable": c.nullable,
                "primary_key": c.primary_key,
                "default": c.default,
            }
            for c in ts.columns
        ],
        "indexes": [
            {"name": i.name, "columns": i.columns, "unique": i.unique, "origin": i.origin}
            for i in ts.indexes
        ],
        "foreign_keys": [
            {
                "columns": fk.columns,
                "ref_table": fk.ref_table,
                "ref_columns": fk.ref_columns,
                "on_update": fk.on_update,
                "on_delete": fk.on_delete,
            }
            for fk in ts.foreign_keys
        ],
    }
    if with_rows:
        d["row_count"] = adapter.get_statistics(name).row_count
    return d


@router.get("/api/schema")
def get_schema(adapter: TursoAdapter = Depends(adapter_dep)) -> dict:
    tables = adapter.get_tables()
    relationships = []
    for t in tables:
        for fk in adapter.get_foreign_keys(t):
            relationships.append({
                "from_table": t,
                "from_columns": fk.columns,
                "to_table": fk.ref_table,
                "to_columns": fk.ref_columns,
            })
    return {
        "database_backend": adapter.backend_name,
        "tables": [_table_to_dict(adapter, t) for t in tables],
        "relationships": relationships,
    }


@router.get("/api/examples")
def get_examples(adapter: TursoAdapter = Depends(adapter_dep)) -> dict:
    """Example queries generated from the live schema + statistics (never hardcoded)."""
    from ...optimizer.examples import generate_examples

    return {"examples": generate_examples(adapter)}


@router.get("/api/schema/tables")
def get_tables(adapter: TursoAdapter = Depends(adapter_dep)) -> dict:
    return {"tables": adapter.get_tables()}


@router.get("/api/schema/{table}")
def get_table(table: str, adapter: TursoAdapter = Depends(adapter_dep)) -> dict:
    if table not in adapter.get_tables():
        raise HTTPException(status_code=404, detail=f"Unknown table: {table}")
    return _table_to_dict(adapter, table)


@router.get("/api/statistics/{table}")
def get_statistics(table: str, adapter: TursoAdapter = Depends(adapter_dep)) -> dict:
    if table not in adapter.get_tables():
        raise HTTPException(status_code=404, detail=f"Unknown table: {table}")
    return adapter.get_statistics(table).to_dict()
