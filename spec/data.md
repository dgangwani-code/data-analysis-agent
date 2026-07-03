# Data Model

---

## Storage Technology

**PostgreSQL** (via SQLAlchemy 2.0, declarative `Mapped` style, migrated with Alembic) for all structured metadata: datasets, profiles, chat sessions/messages, analysis runs/steps. Chosen because it's the stated/production DB for this project (see [`architecture.md`](architecture.md#stack)) and because multi-day, multi-file history needs a durable, queryable store, not an ephemeral one.

The **actual uploaded file bytes** are stored on the **local filesystem** (`data/uploads/<dataset_id>/<original_filename>`), not in PostgreSQL — this keeps the DB small/queryable and matches the local-execution model (`local_execute` reads the file straight off disk). `Dataset.storage_path` is the pointer from DB metadata to that file.

## Entities

### Entity: Dataset

One uploaded file (Phase 1: exactly one file per dataset; Phase 2 extends this to a set of files / a folder treated as one dataset — see `Data Lifecycle`).

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | Text (UUID) | yes | Primary key |
| session_id | Text (UUID, FK → ChatSession.id) | no | Session this dataset was uploaded into (nullable — a dataset can exist before a session is opened) |
| filename | Text | yes | Original uploaded filename |
| file_type | Text | yes | `"csv"` \| `"xlsx"` (Phase 2 adds `"pdf"`) |
| storage_path | Text | yes | Local filesystem path to the stored file |
| row_count | Integer | yes | Row count, computed at parse time |
| column_count | Integer | yes | Column count, computed at parse time |
| status | Text | yes | `"profiling"` \| `"ready"` \| `"failed"` |
| error_message | Text | no | Set if parsing/profiling failed |
| created_at | Timestamptz | yes | Upload time |
| updated_at | Timestamptz | yes | Last modified |

### Entity: DatasetProfile

The auto-computed profile for a `Dataset` — schema + summary statistics, computed entirely locally (no LLM call). This is exactly what's allowed to cross the LLM boundary later.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | Text (UUID) | yes | Primary key |
| dataset_id | Text (UUID, FK → Dataset.id) | yes | The dataset this profiles |
| schema_json | JSONB | yes | `[{name, dtype, null_count, distinct_count, min, max, sample_values?}, ...]` — one entry per column; `sample_values` present only for low-cardinality columns, capped at 10 distinct values, never a row sample |
| stats_summary | JSONB | yes | Aggregate stats (`describe()`-style): counts, means, std, quartiles for numeric columns |
| schema_summary_text | Text | yes | Human-readable rendering of the two fields above — this is the literal text `build_context` hands to the LLM |
| profiled_at | Timestamptz | yes | When profiling completed |

### Entity: ChatSession

One ongoing conversation/analysis project. A session may span one or more datasets over multiple days.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | Text (UUID) | yes | Primary key |
| title | Text | no | Optional, derived from the first question if unset |
| active_dataset_id | Text (UUID, FK → Dataset.id) | no | The dataset the session is currently focused on |
| created_at | Timestamptz | yes | Session start |
| updated_at | Timestamptz | yes | Last activity |

### Entity: ChatMessage

One turn in a session — either the user's question or the assistant's answer.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | Text (UUID) | yes | Primary key |
| session_id | Text (UUID, FK → ChatSession.id) | yes | Parent session |
| run_id | Text (UUID, FK → AnalysisRun.id) | no | Set on assistant messages — the run that produced this answer |
| role | Text | yes | `"user"` \| `"assistant"` |
| content | Text | yes | Plain-language text (question or answer) — never raw data |
| created_at | Timestamptz | yes | Turn time, used for ordering |

### Entity: AnalysisRun

One question-answering loop invocation (one LangGraph run).

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | Text (UUID) | yes | Primary key — matches `AgentState["run_id"]` |
| session_id | Text (UUID, FK → ChatSession.id) | yes | Parent session |
| dataset_id | Text (UUID, FK → Dataset.id) | yes | Dataset this run analyzed |
| question | Text | yes | The user's question for this run |
| status | Text | yes | `"pending"` \| `"completed"` \| `"completed_with_fallback"` \| `"failed"` |
| final_answer | Text | no | Plain-language answer text |
| final_code | Text | no | The generated code that produced (or last attempted to produce) the answer |
| step_count | Integer | yes | Number of plan/execute cycles actually taken |
| is_fallback | Boolean | yes | True if the best-guess fallback path was taken |
| error_message | Text | no | Set on `status = "failed"` |
| created_at | Timestamptz | yes | Run start |
| completed_at | Timestamptz | no | Run end |

### Entity: AnalysisStep

One iteration of the code-gen/execute loop within an `AnalysisRun` — the persisted, 1:1 mirror of `AgentState["step_history"]` entries.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | Text (UUID) | yes | Primary key |
| run_id | Text (UUID, FK → AnalysisRun.id) | yes | Parent run |
| step_number | Integer | yes | 1-indexed order within the run |
| generated_code | Text | yes | The pandas code generated for this step |
| result_summary | JSONB | no | The aggregated/summarized execution result (never raw rows) |
| status | Text | yes | `"success"` \| `"error"` |
| error_message | Text | no | Execution error text, if any |
| created_at | Timestamptz | yes | Step time |

### Relationships

```
ChatSession 1───* Dataset            (a session can accumulate multiple uploaded datasets over time)
ChatSession 1───* ChatMessage        (the full conversation)
ChatSession 1───* AnalysisRun        (one run per question)
Dataset     1───1 DatasetProfile     (Phase 1: exactly one profile per dataset; Phase 2 extends
                                       Dataset to represent a joined/multi-file group with one
                                       combined DatasetProfile)
Dataset     1───* AnalysisRun        (a dataset can be analyzed across many runs/questions)
AnalysisRun 1───* AnalysisStep       (the refine-loop history, ≤ max_steps = 6 rows)
AnalysisRun 1───1 ChatMessage        (the assistant message that surfaces this run's answer)
```

## Data Lifecycle

- **Created:** `Dataset` + `DatasetProfile` on upload (synchronous, before any question is asked). `ChatSession` on first message if none is active. `ChatMessage`/`AnalysisRun`/`AnalysisStep` rows on every question asked.
- **Updated:** `Dataset.status` transitions `"profiling" → "ready"` (or `"failed"`) as parsing/profiling completes. `ChatSession.updated_at`/`active_dataset_id` update on every new message. `AnalysisRun.status` transitions `"pending" → "completed" | "completed_with_fallback" | "failed"` as the graph runs.
- **Deleted:** Nothing is auto-deleted in Phase 1 or Phase 2 — this is a personal, low-volume tool where the whole point is multi-day persistence; there is no time-boxing or archival requirement from intake. A future phase could add manual delete, but it is out of scope here.
- **Multi-file (Phase 2):** `Dataset` grows an optional `parent_group_id` (self-referential) so several uploaded files can be treated as one logical dataset with one combined `DatasetProfile`; this is additive to the Phase 1 schema, not a redesign.

## Sensitive Data

- The actual data values in uploaded files may be sensitive (this is why the LLM boundary rule exists at all — see [`architecture.md`](architecture.md#llm-boundary-what-crosses-vs-what-stays-local)). Raw file bytes live only on local disk (`data/uploads/`) and are never copied into a DB column, a log line, or an LLM request.
- `DatasetProfile.schema_json`/`stats_summary` may contain column *names* and *aggregate* values (e.g. min/max, sample distinct values for low-cardinality columns) — these are treated as sensitive-adjacent (they can reveal business context) but are explicitly the only data-derived content permitted to cross the LLM boundary, per the architecture's boundary rule.
- `AnalysisStep.result_summary` is capped/aggregated by construction (`local_execute`, ≤20 result rows, already-aggregated) so it can never smuggle a raw-row dump into the DB or back into the LLM.
- No secrets (API keys, credentials) are ever stored in these tables — provider keys live only in `.env`, read via `Settings`.
