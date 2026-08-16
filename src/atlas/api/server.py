from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi import Query as QueryParam

from ..config import Config, load_config
from ..core.duckdb_engine import DuckDBEngine
from ..core.metadata import MetadataIndex
from ..core.substitutor import substitute_placeholders
from ..models import Dataset, Param


def create_app(config: Config | None = None) -> FastAPI:
    if config is None:
        config = load_config()

    app = FastAPI(title="evidence-atlas", version="0.2.0")
    app.state.config = config

    # Initialize metadata index for each project
    indexes: dict[str, MetadataIndex] = {}
    engines: dict[str, DuckDBEngine] = {}

    for proj in config.projects:
        idx = MetadataIndex()
        normalized_path = Path(proj.path) / "build" / "api" / "atlas-normalized.json"
        if normalized_path.exists():
            idx.load(normalized_path)
            indexes[proj.id] = idx
        engines[proj.id] = DuckDBEngine(
            proj.path,
            default_domain_account=config.default_domain_account,
        )

    def get_index(project_id: str) -> MetadataIndex:
        idx = indexes.get(project_id)
        if idx is None:
            raise HTTPException(status_code=404, detail=f"project not found: {project_id}")
        return idx

    def get_engine(project_id: str) -> DuckDBEngine:
        eng = engines.get(project_id)
        if eng is None:
            raise HTTPException(status_code=404, detail=f"project not found: {project_id}")
        return eng

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/projects")
    async def list_projects() -> list[dict]:
        return [{"id": p.id, "name": p.name, "path": p.path} for p in config.projects]

    @app.get("/projects/{project_id}/datasets")
    async def list_datasets(
        project_id: str,
        resolvable_only: bool = QueryParam(default=True),
    ) -> list[dict]:
        idx = get_index(project_id)
        datasets = idx.list_resolvable_datasets() if resolvable_only else idx.list_all_datasets()
        return [_dataset_to_dict(ds, idx) for ds in datasets]

    @app.get("/projects/{project_id}/datasets/search")
    async def search_datasets(
        project_id: str,
        q: str = QueryParam(...),
    ) -> list[dict]:
        idx = get_index(project_id)
        results = idx.find_datasets(q)
        return [_dataset_to_dict(ds, idx) for ds in results]

    @app.get("/datasets/{dataset_id}")
    async def get_dataset(
        dataset_id: str,
        project_id: str = QueryParam(...),
    ) -> dict:
        idx = get_index(project_id)
        ds = idx.datasets.get(dataset_id)
        if ds is None:
            raise HTTPException(status_code=404, detail=f"dataset not found: {dataset_id}")
        return _dataset_to_dict(ds, idx)

    @app.get("/datasets/{dataset_id}/params")
    async def get_dataset_params(
        dataset_id: str,
        project_id: str = QueryParam(...),
    ) -> list[dict]:
        idx = get_index(project_id)
        ds = idx.datasets.get(dataset_id)
        if ds is None:
            raise HTTPException(status_code=404, detail=f"dataset not found: {dataset_id}")
        params = idx.get_dataset_params(dataset_id)
        return [_param_to_dict(p) for p in params]

    @app.post("/datasets/{dataset_id}/data")
    async def get_dataset_data(
        dataset_id: str,
        project_id: str = QueryParam(...),
        body: dict | None = None,
    ) -> dict:
        idx = get_index(project_id)
        ds = idx.datasets.get(dataset_id)
        if ds is None:
            raise HTTPException(status_code=404, detail=f"dataset not found: {dataset_id}")
        if not ds.resolvable:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"dataset {dataset_id} is not resolvable "
                    f"(bound_query={ds.bound_query} is a svelte variable)"
                ),
            )

        query = idx.get_dataset_query(dataset_id)
        if query is None:
            raise HTTPException(status_code=422, detail=f"no bound query for dataset {dataset_id}")

        params = idx.get_dataset_params(dataset_id)
        overrides = (body or {}).get("params", {})

        sql = substitute_placeholders(
            query.compiled_sql,
            params,
            overrides=overrides,
            default_domain_account=config.default_domain_account,
        )

        engine = get_engine(project_id)
        try:
            result = engine.execute_query(sql)
        except Exception as e:
            raise HTTPException(
                status_code=503,
                detail={"error": str(e)[:500], "sql_preview": sql[:500]},
            ) from e

        return {
            "dataset_id": dataset_id,
            "query_id": query.id,
            "params_used": {p.name: overrides.get(p.name, p.default) for p in params},
            **result,
        }

    return app


def _dataset_to_dict(ds: Dataset, idx: MetadataIndex) -> dict:
    query = idx.get_dataset_query(ds.id)
    params = idx.get_dataset_params(ds.id)
    return {
        "id": ds.id,
        "component_type": ds.component_type,
        "bound_query": ds.bound_query,
        "resolvable": ds.resolvable,
        "page_id": ds.page_id,
        "partial": ds.partial,
        "ordinal": ds.ordinal,
        "query_compiled": query.compiled if query else None,
        "params": [_param_to_dict(p) for p in params],
    }


def _param_to_dict(p: Param) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "type": p.type,
        "required": p.required,
        "default": p.default,
        "options": [{"value": o.value, "label": o.label, "default": o.default} for o in p.options]
        if p.options
        else [],
    }
