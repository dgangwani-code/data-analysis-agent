# Capability: Dataset Ingestion & Profiling

## What It Does

Parses an uploaded file locally and computes its schema and summary statistics before any question is asked, entirely without an LLM call.

## Inputs

| Input | Type | Source | Required |
|-------|------|--------|----------|
| Uploaded file | CSV or Excel binary (Phase 1); + PDF/scanned-PDF, multiple files, or a folder (Phase 2) | `POST /datasets` multipart upload | yes |
| session_id | string (UUID) | `POST /datasets` request | no (creates a new session if omitted) |

## Outputs

| Output | Type | Destination |
|--------|------|-------------|
| `Dataset` row | DB record | PostgreSQL |
| `DatasetProfile` row (schema + stats + `schema_summary_text`) | DB record | PostgreSQL |
| Profile response | JSON | Returned synchronously to the UI, rendered in the Profile Panel |
| Raw file bytes | file | Local filesystem (`data/uploads/<dataset_id>/…`) — never the DB, never the LLM |

## External Calls

| System | Operation | On Failure |
|--------|-----------|------------|
| Local filesystem | Save uploaded bytes | Fatal — 500, `Dataset.status = "failed"` |
| pandas (`file_parser`) | Parse CSV/Excel into a DataFrame | 400 if unparsable — clear message, no stack trace |
| PostgreSQL | Persist `Dataset` + `DatasetProfile` | Fatal — 500, logged |

No LLM call is made by this capability at all — profiling is pure local computation, which trivially satisfies the no-raw-data-to-LLM rule for this path.

## Business Rules

- Profiling happens synchronously on upload, before any question can be asked — the profile must be visible in the UI before the chat composer is enabled.
- `schema_json`/`stats_summary` never contain a row-level sample — only per-column aggregates (min/max/null-count/distinct-count) and, for low-cardinality columns only, a capped (≤10) list of distinct values.
- Phase 1: exactly one file per dataset (CSV or XLSX). Phase 2 extends this to multiple files/a folder treated as one dataset (via `Dataset.parent_group_id`, see [`data.md`](../data.md#data-lifecycle)) and adds PDF/scanned-PDF ingestion via OCR.
- An unsupported file type or unparsable file never creates a `Dataset` row in `"ready"` state — it fails cleanly with a specific message.

## Success Criteria

- [ ] Uploading a valid CSV or XLSX file returns a profile (column names, types, ranges/sample stats, row count) within a few seconds, with no LLM call made.
- [ ] The returned profile's row/column counts exactly match an independent `pandas.read_csv`/`read_excel` of the same file.
- [ ] Uploading a malformed or unsupported file returns a 400 with a specific, human-readable message and no `Dataset` row left in `"ready"` state.
- [ ] `DatasetProfile.schema_json` never contains a full row of raw data — verified by a test asserting no entry contains more than 10 sample values for any column.
