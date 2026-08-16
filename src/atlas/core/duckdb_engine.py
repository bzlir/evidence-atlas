from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb


class DuckDBEngine:
    """DuckDB engine with lazy parquet view loading, matching evidence's initDB settings."""

    def __init__(self, project_path: str, default_domain_account: str = "") -> None:
        self._project_path = Path(project_path)
        self._default_domain_account = default_domain_account
        self._con: duckdb.DuckDBPyConnection | None = None
        self._loaded_schemas: set[str] = set()
        self._manifest: dict[str, Any] = {}

    @property
    def con(self) -> duckdb.DuckDBPyConnection:
        if self._con is None:
            self._init_db()
        assert self._con is not None
        return self._con

    def _init_db(self) -> None:
        self._con = duckdb.connect()
        self._con.execute("SET ieee_floating_point_ops = false")
        self._con.execute("SET old_implicit_casting = true")

        manifest_path = self._project_path / "build" / "data" / "manifest.json"
        if manifest_path.exists():
            self._manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    def ensure_schema_loaded(self, schema: str) -> None:
        """Lazy-load parquet views for a schema if not already loaded."""
        if schema in self._loaded_schemas:
            return
        self._loaded_schemas.add(schema)

        con = self.con
        con.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')

        files = self._manifest.get("renderedFiles", {}).get(schema, [])
        parquet_base = self._project_path / "build" / "data"

        for f in files:
            fname = f.split("/")[-1].replace(".parquet", "")
            parquet_path = parquet_base / f.replace("static/data/", "")
            if parquet_path.exists():
                con.execute(
                    f'CREATE OR REPLACE VIEW "{schema}"."{fname}" AS '
                    f"SELECT * FROM read_parquet('{parquet_path}')"
                )

        all_schemas = list(self._loaded_schemas)
        con.execute(f"PRAGMA search_path='{','.join(all_schemas)}'")

    def ensure_all_schemas_loaded(self) -> None:
        """Load all schemas from manifest."""
        _ = self.con  # triggers _init_db which loads _manifest
        for schema in self._manifest.get("renderedFiles", {}):
            self.ensure_schema_loaded(schema)

    def execute_query(self, sql: str) -> dict[str, Any]:
        """Execute SQL and return columns + rows as JSON-serializable dict."""
        self.ensure_all_schemas_loaded()
        result = self.con.execute(sql)
        columns = [d[0] for d in result.description] if result.description else []
        rows = result.fetchall()
        return {
            "columns": columns,
            "rows": [list(r) for r in rows],
            "row_count": len(rows),
        }

    def close(self) -> None:
        if self._con:
            self._con.close()
            self._con = None
