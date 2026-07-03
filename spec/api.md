# API

---

## API Style

REST (FastAPI). Every route returns the existing envelope convention from `src/api/_common.py`: `ok(data)` → `{"data": ..., "error": null}` on success, or `api_error(code, message, status_code)` → raises `HTTPException` with `{"detail": {"code": ..., "message": ...}}` on failure. Frontend components read `data.data` on success and `data.detail.message` (from a non-2xx `HTTPException`) on failure — matching the pattern already used in `frontend/src/app/page.tsx`.

## Endpoints / Commands

### `POST /datasets`

**Purpose:** Upload one CSV or Excel file; parses and profiles it synchronously (no LLM call) and returns the completed profile. This is the Phase 1 single-file path — Phase 2 extends this route to accept multiple files/a folder.

**Request:** `multipart/form-data`
```
file: <the uploaded .csv or .xlsx file>
session_id: string | null   (optional — creates a new ChatSession if omitted)
```

**Response:**
```json
{
  "data": {
    "dataset_id": "uuid",
    "session_id": "uuid",
    "filename": "sales_q1.csv",
    "status": "ready",
    "row_count": 5231,
    "column_count": 14,
    "profile": {
      "schema": [
        {"name": "order_date", "dtype": "datetime", "null_count": 0, "min": "2024-01-01", "max": "2024-03-31"},
        {"name": "region", "dtype": "string", "null_count": 3, "distinct_count": 6, "sample_values": ["East", "West", "…"]},
        {"name": "revenue", "dtype": "float", "null_count": 0, "min": 12.5, "max": 98234.1}
      ],
      "stats_summary": {"revenue": {"mean": 4021.3, "std": 1899.2, "p50": 3800.0}}
    }
  },
  "error": null
}
```

**Error cases:**
| Status | Condition |
|--------|-----------|
| 400 | Unsupported file type, empty file, or malformed CSV/Excel that pandas cannot parse |
| 413 | File exceeds the configured upload size limit |
| 500 | Unexpected parsing/profiling failure — logged, `Dataset.status` set to `"failed"` |

### `GET /datasets/{dataset_id}`

**Purpose:** Fetch a dataset's metadata + profile (used to re-render the profile panel on session resume).

**Request:** none (path param `dataset_id`)

**Response:** same `data` shape as `POST /datasets`.

**Error cases:**
| Status | Condition |
|--------|-----------|
| 404 | Dataset not found |

### `POST /sessions/{session_id}/messages`

**Purpose:** Ask a question about the session's active dataset. Synchronously runs the bounded LangGraph loop (`src/graph/runner.py`) and returns the finished answer, generated code, and step history for the collapsible "what it tried" view.

**Request:**
```json
{
  "content": "What was the average revenue per region in March?"
}
```

**Response:**
```json
{
  "data": {
    "run_id": "uuid",
    "session_id": "uuid",
    "status": "completed",
    "answer": "Average revenue per region in March was...",
    "final_code": "df[df['order_date'].dt.month == 3].groupby('region')['revenue'].mean()",
    "is_fallback": false,
    "steps": [
      {"step_number": 1, "generated_code": "...", "status": "success", "result_summary": {"East": 4213.1, "West": 3891.4}}
    ]
  },
  "error": null
}
```

**Error cases:**
| Status | Condition |
|--------|-----------|
| 400 | Session has no active dataset yet |
| 404 | Session not found |
| 409 | A run is already in progress for this session (single-run-at-a-time concurrency rule, see [`agent.md`](agent.md#concurrency-model)) |
| 502 | The Gemini API was unavailable/erroring for the whole run's retry budget — `AnalysisRun.status = "failed"` |

### `GET /sessions/{session_id}/messages`

**Purpose:** Fetch the full chat history for a session (used to render the thread on load and on resume).

**Request:** none (path param `session_id`)

**Response:**
```json
{
  "data": {
    "session_id": "uuid",
    "messages": [
      {"role": "user", "content": "What was the average revenue per region in March?", "created_at": "…"},
      {"role": "assistant", "content": "Average revenue per region in March was...", "run_id": "uuid", "created_at": "…"}
    ]
  },
  "error": null
}
```

**Error cases:**
| Status | Condition |
|--------|-----------|
| 404 | Session not found |

### `GET /sessions/{session_id}`

**Purpose:** Fetch session metadata (active dataset, title) — used on load to know which dataset's profile to render alongside the chat thread.

**Response:**
```json
{
  "data": {"session_id": "uuid", "title": "sales_q1.csv analysis", "active_dataset_id": "uuid"},
  "error": null
}
```

**Error cases:**
| Status | Condition |
|--------|-----------|
| 404 | Session not found |

---

### Phase 2 additions (not built in Phase 1; noted here for continuity, not implemented against yet)

- `GET /sessions` — list past sessions for the history-browsing UI.
- `POST /datasets/export` — export the current/derived dataset or result as a downloadable file.
- Chart-ready fields added to the `POST /sessions/{id}/messages` response (`chart_data`) and a `cost_estimate` field (`{tokens_in, tokens_out, estimated_usd}`).

## Authentication

None — single-user local personal tool (per intake). No auth layer is in scope for Phase 1 or Phase 2.
