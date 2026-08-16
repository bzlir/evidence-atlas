# Multi-project DuckDB instance isolation

## Context

Gateway serves multiple evidence projects, each with its own set of parquet files produced by `evidence build`. Page queries' SQL is authored with schema-qualified table refs (e.g. `FROM my_datasource.my_table`) and is frozen — gateway cannot rewrite it without brittleness (SQL rewriting would conflict with `${inputs.*}` / `${currentUser}` placeholder substitution).

Each project's parquets sit under `build/data/<datasource>/<table>/<hash>/<table>.parquet`, with `<datasource>` naming matching the schema prefix in page query SQL.

## Decision

**One DuckDB instance per project**, with lazy spawn + LRU eviction:

- Each project gets its own DuckDB instance when first queried; idle instances close after a configurable timeout
- Each instance attaches its project's parquet files under the schemas named in the SQL (e.g. `my_datasource_a`, `my_datasource_b`)
- Page query SQL runs unmodified — `FROM my_datasource.my_table` resolves to the project's attached parquet
- DuckDB internal threads capped at `min(CPU cores, 4)` per instance to prevent one heavy query from starving other instances

## Rejected: Single shared DuckDB with per-project schemas

Would require SQL rewriting (`FROM my_datasource.X` → `FROM project_a.my_datasource.X`). Three problems:

1. **DuckDB doesn't natively support 3-level namespace** — would require view-based simulation, adding operational complexity
2. **SQL rewriting is fragile** — it competes with `${inputs.*}` and `${ref}` substitution at the same string positions, and any rewrite bug silently corrupts results
3. **Schema name collision** — two projects both having `sources/my_datasource/orders.sql` (different SQL, same name) cannot coexist under a shared `my_datasource` schema

The only scenario where shared DuckDB wins — cross-project SQL JOINs — is rare in BI dashboard domain. Cross-project comparison happens at application layer (query two projects' vizes separately and join in API response).

## QPS and resource envelope

- **Data size per project**: 30-100MB parquet total (typical baseline: ~33MB across ~32 parquets). All metadata-cached in DuckDB, working set typically fits in memory.
- **Idle memory per instance**: ~100-200MB (DuckDB base + parquet footer/column statistics cache)
- **Loaded memory per instance**: ~150-300MB (idle + working set, mostly cached)
- **Single query latency**: 5-50ms on cached parquet, <1M rows
- **Single instance QPS**: 100-1000 (DuckDB internal parallelism, parquet cached)
- **Practical ceiling**: 10-50 concurrent active projects × per-instance parallelism ≈ 100-500 aggregate QPS, 2-15GB total memory

## Scaling path beyond ceiling

When QPS > 500 or project count > 50 active:

1. **Result cache** — key on (query_id, param_values) hash → cached result. High hit rate expected since most slicer combinations are common.
2. **Parquet → DuckDB native table import** — trade disk for speed; ~2-5× faster than attach-parquet-at-query-time.
3. **Read replicas** — for hot projects, spawn multiple DuckDB instances of the same parquets behind a load balancer.

## Consequences

- Project lifecycle is isolated: rebuild/reload/failure of one project does not affect others
- Hook output (`atlas-normalized.json`) stays project-scoped — `parquet_path` is relative to project root, no cross-project namespace needed
- Cross-project SQL not supported by design; cross-project comparison is application-layer concern
- The "single shared DB" assumption a future reader might bring to a Python backend is explicitly rejected here — this is a deliberate deviation from the conventional pattern

## Related

- Hook contract: `@evidence-atlas/hook` emits per-project `parquet_path` (relative) + `parquet_dependencies` per page query. Hook is agnostic to instance management — that lives here.
