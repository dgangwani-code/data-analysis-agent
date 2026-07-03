# Capability: Chat Session Persistence

## What It Does

Persists the ongoing conversation (questions and answers) and the active dataset for a session, so the current chat has real turn-by-turn memory within the session (Phase 1), and — once Phase 2 exposes a browsing UI — can be resumed across days.

## Inputs

| Input | Type | Source | Required |
|-------|------|--------|----------|
| `session_id` | string (UUID) | Path param on `GET/POST /sessions/{id}/*` | yes |
| New message content | string | `POST /sessions/{id}/messages` (the question) or the graph runner (the answer) | yes |

## Outputs

| Output | Type | Destination |
|--------|------|-------------|
| `ChatSession` row | DB record | PostgreSQL |
| `ChatMessage` rows (user + assistant, in order) | DB records | PostgreSQL |
| Full message history | JSON | `GET /sessions/{id}/messages` response, rendered as the Chat Thread |

## External Calls

| System | Operation | On Failure |
|--------|-----------|------------|
| PostgreSQL | Create/update `ChatSession`; insert `ChatMessage` rows | Fatal — 500, logged |

No LLM or external API is called directly by this capability — it is pure persistence, consumed by `iterative-question-answering`'s `build_context` node (which reads `context_messages`) and `finalize` node (which writes the assistant's `ChatMessage`).

## Business Rules

- A session's `context_messages`, as loaded by `build_context`, is capped at the last 20 turns for Phase 1 — see [`agent.md`](../agent.md#memory--context).
- Message content is always plain text (question or plain-language answer) — never a raw data value, so persisting/loading history never risks violating the LLM boundary.
- Phase 1 persists across-session data (the rows exist and are correct) but does not yet expose a browsing UI to resume a *different* past session — that UI is a labelled stub until Phase 2 (see [`ui.md`](../ui.md)).
- A session's `active_dataset_id` updates whenever a new dataset is uploaded into that session.

## Success Criteria

- [ ] Sending a second question in the same session and inspecting the Gemini prompt for that second call shows the first Q&A pair present in context.
- [ ] Reloading the Workspace screen mid-session (same `session_id`) re-renders the full chat thread from `GET /sessions/{id}/messages` exactly as it was, in order.
- [ ] `ChatMessage.content` never contains a value traceable to a raw data row — verified alongside the LLM-boundary test since the same persisted text is what's replayed into future prompts.
