from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import sqlglot
import sqlglot.expressions as exp
import yaml

from ..models import Dataset, Page, Param, Project, Query


class MetadataIndex:
    """In-memory index of normalized metadata, built from atlas-normalized.json."""

    def __init__(self) -> None:
        self.projects: dict[str, Project] = {}
        self.pages: dict[str, Page] = {}
        self.datasets: dict[str, Dataset] = {}
        self.queries: dict[str, Query] = {}
        self.params: dict[str, Param] = {}
        self._rels_from: dict[str, list[dict]] = defaultdict(list)
        self._loaded = False
        self._project_path: Path | None = None
        self._datasource_types: dict[str, str] = {}
        self.source_tables: dict[str, list[str]] = {}

    def load(self, json_path: str | Path, project_path: str | Path | None = None) -> None:
        data = json.loads(Path(json_path).read_text(encoding="utf-8"))
        entities = data.get("entities", {})
        relations = data.get("relations", [])

        if project_path is not None:
            self._project_path = Path(project_path)

        for p in entities.get("projects", []):
            proj = Project(**p)
            self.projects[proj.id] = proj

        for p in entities.get("pages", []):
            page = Page(**p)
            self.pages[page.id] = page

        for d in entities.get("datasets", []):
            ds = Dataset(**d)
            self.datasets[ds.id] = ds

        for q in entities.get("queries", []):
            query = Query(**q)
            self.queries[query.id] = query

        for p in entities.get("params", []):
            param = Param(**p)
            self.params[param.id] = param

        self._rels_from = defaultdict(list)
        for rel in relations:
            self._rels_from[rel["from"]].append(rel)

        self._load_datasource_types()
        self._parse_source_tables()

        self._loaded = True

    def _load_datasource_types(self) -> None:
        """Build datasource_name -> connection_type map from sources/*/connection.yaml."""
        self._datasource_types = {}
        if self._project_path is None:
            return
        sources_dir = self._project_path / "sources"
        if not sources_dir.is_dir():
            return
        for conn_yaml in sources_dir.glob("*/connection.yaml"):
            try:
                raw = yaml.safe_load(conn_yaml.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    name = raw.get("name") or conn_yaml.parent.name
                    ctype = raw.get("type", "")
                    if name and ctype:
                        self._datasource_types[name] = ctype
            except (yaml.YAMLError, OSError):
                continue

    def _parse_source_tables(self) -> None:
        """Parse compiled_sql of every source query, extract warehouse table names."""
        self.source_tables = {}
        for qid, query in self.queries.items():
            if not query.source:
                continue
            sql = query.compiled_sql or query.input_sql
            if not sql:
                continue
            dialect = self._datasource_types.get(query.datasource or "", None)
            tables = _extract_tables(sql, dialect)
            if tables:
                self.source_tables[qid] = tables

    def get_dataset_query(self, ds_id: str) -> Query | None:
        ds = self.datasets.get(ds_id)
        if not ds or not ds.resolvable:
            return None
        for rel in self._rels_from.get(ds_id, []):
            if rel["type"] == "BINDS_QUERY":
                return self.queries.get(rel["to"])
        return None

    def get_dataset_params(self, ds_id: str) -> list[Param]:
        result = []
        for rel in self._rels_from.get(ds_id, []):
            if rel["type"] == "REQUIRES_PARAM":
                p = self.params.get(rel["to"])
                if p:
                    result.append(p)
        return result

    def list_resolvable_datasets(self) -> list[Dataset]:
        return [ds for ds in self.datasets.values() if ds.resolvable]

    def list_all_datasets(self) -> list[Dataset]:
        return list(self.datasets.values())

    def find_datasets(self, keyword: str) -> list[Dataset]:
        kw = keyword.lower()
        return [
            ds
            for ds in self.datasets.values()
            if kw in ds.id.lower() or kw in ds.bound_query.lower()
        ]

    def get_projects(self) -> list[Project]:
        return list(self.projects.values())

    def get_project_warehouse_tables(self) -> list[dict[str, str]]:
        """Return deduplicated list of warehouse tables used by this project.

        Walks: dataset -> BINDS_QUERY -> page_query.parquet_dependencies
               -> source_query -> parsed tables.
        Each table carries its connection type ("mysql"/"trino"/etc.) as `source`.
        Table names are lowercased and deduplicated across all source queries.
        """
        seen: dict[str, str] = {}

        for ds in self.datasets.values():
            for rel in self._rels_from.get(ds.id, []):
                if rel["type"] != "BINDS_QUERY":
                    continue
                page_q = self.queries.get(rel["to"])
                if page_q is None:
                    continue
                for dep_qid in page_q.parquet_dependencies:
                    src_q = self.queries.get(dep_qid)
                    if src_q is None or not src_q.source:
                        continue
                    conn_type = self._datasource_types.get(src_q.datasource or "", "")
                    for tbl in self.source_tables.get(dep_qid, []):
                        key = tbl.lower()
                        if key not in seen:
                            seen[key] = conn_type

        return [{"name": name, "source": src} for name, src in sorted(seen.items())]


def _extract_tables(sql: str, dialect: str | None = None) -> list[str]:
    """Extract warehouse table names from SQL, lowercased and deduplicated.

    Uses sqlglot AST to identify Table nodes, skipping CTE names, aliases,
    table functions (UNNEST/generate_series/VALUES), and LATERAL subqueries.
    Recurses into nested subqueries at all depths.
    """
    tables: list[str] = []
    seen: set[str] = set()

    try:
        parsed = sqlglot.parse(sql, dialect=dialect)
    except sqlglot.errors.ParseError:
        return []

    for stmt in parsed:
        if stmt is None:
            continue
        for table_node in stmt.find_all(exp.Table):
            name = table_node.name
            if not name:
                continue
            if _is_cte_name(table_node, stmt):
                continue
            table_copy = table_node.copy()
            table_copy.set("alias", None)
            full = table_copy.sql(dialect=dialect, identify=False)
            lower = full.lower()
            if lower not in seen:
                seen.add(lower)
                tables.append(lower)

    return tables


def _is_cte_name(table_node: exp.Table, stmt: exp.Expr) -> bool:
    """Check if a Table node refers to a CTE defined in the same statement."""
    cte_names: set[str] = set()
    for cte in stmt.find_all(exp.CTE):
        if cte.alias_or_name:
            cte_names.add(cte.alias_or_name.lower())
    return table_node.name.lower() in cte_names
