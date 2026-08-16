from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

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

    def load(self, json_path: str | Path) -> None:
        data = json.loads(Path(json_path).read_text(encoding="utf-8"))
        entities = data.get("entities", {})
        relations = data.get("relations", [])

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

        self._loaded = True

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
