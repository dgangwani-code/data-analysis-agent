# Capability: Result Export

> **Phase 2 capability.** In Phase 1 this appears only as a disabled, clearly-labelled "Export" button in the Chat Thread header (see [`ui.md`](../ui.md)) — no backend route exists yet in Phase 1.

## What It Does

Lets the user download the current dataset (as ingested/cleaned) or a derived result table (e.g. the output of a successful analysis step) as a file, on demand.

## Inputs

| Input | Type | Source | Required |
|-------|------|--------|----------|
| `dataset_id` or `run_id` | string (UUID) | `POST /datasets/export` request | yes (one of the two) |
| Desired format | string | `POST /datasets/export` request (`"csv"` \| `"xlsx"`) | yes |

## Outputs

| Output | Type | Destination |
|--------|------|-------------|
| Exported file | binary (CSV/XLSX) | Downloaded by the browser |

## External Calls

| System | Operation | On Failure |
|--------|-----------|------------|
| Local filesystem | Read the source dataset or re-materialize the derived result from a persisted `AnalysisStep` | 404 if the dataset/run no longer has retrievable data |

No LLM call — export is a pure local file-generation operation, same locality guarantee as ingestion.

## Business Rules

- Export never re-invokes the LLM — it operates only on already-local data (the original file or a previously computed, already-summarized/derived result).
- The exported file reflects exactly what the user saw (the dataset as ingested, or the specific result table from a specific `AnalysisStep`) — no silent re-computation with different logic.

## Success Criteria

- [ ] Exporting a dataset produces a file whose contents match the originally ingested data.
- [ ] Exporting a derived result produces a file matching the `result_summary` shown to the user for that step.
- [ ] The Phase 1 "Export" button is visibly present and disabled with a "Coming in Phase 2" label — never silently missing or indistinguishable from a bug.
