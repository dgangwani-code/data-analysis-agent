# Capability: Iterative Question Answering

## What It Does

Answers a free-text question about the active dataset by running a bounded (≤6-step) local code-gen/execute/inspect/refine loop: the LLM writes pandas code, the code runs locally against the real data, the result is inspected, and the LLM refines on failure — up to the step cap, after which it returns a flagged best-guess answer.

## Inputs

| Input | Type | Source | Required |
|-------|------|--------|----------|
| `content` (the question) | string | `POST /sessions/{id}/messages` | yes |
| `DatasetProfile` (schema + stats) | JSON | PostgreSQL, loaded by `build_context` | yes |
| `context_messages` (prior turns) | list of `{role, content}` | PostgreSQL `ChatMessage`, loaded by `build_context` | no (empty on the first question) |
| The real dataset | pandas DataFrame | Local filesystem, loaded by `local_execute` only | yes |

## Outputs

| Output | Type | Destination |
|--------|------|-------------|
| `final_answer` | plain-language text | `ChatMessage` (role=`assistant`) + API response, rendered in the Chat Thread |
| `final_code` | python source text | `AnalysisRun.final_code` + API response, rendered in the Collapsible Code Block |
| `step_history` | list of `{code, result_summary, status, error}` | `AnalysisStep` rows + API response, rendered in the "what it tried" disclosure |
| `AnalysisRun` row | DB record | PostgreSQL |

## External Calls

| System | Operation | On Failure |
|--------|-----------|------------|
| Gemini API (`plan_generate_code`) | Generate the next step's pandas code | One retry, then fatal → `handle_error`, run marked `"failed"` |
| Local sandbox (`sandbox_exec.run`, no network) | Execute the generated code against the real DataFrame | Non-fatal — captured as a step error, routed into the refine loop or the fallback path |
| Gemini API (`finalize_answer` / `best_guess_fallback`) | Compose the final plain-language answer | One retry, then fatal → `handle_error` |
| PostgreSQL | Persist the run and every step | Fatal on write failure, logged; answer is still returned to the caller |

## Business Rules

- The loop is capped at `MAX_STEPS = 6` (see [`agent.md`](../agent.md#agent-state)). Exhausting the budget without a successful execution never fails the request — it returns a best-guess answer explicitly flagged as such, with the attempted steps visible.
- **No raw data row is ever sent to Gemini** — every prompt built for `plan_generate_code`, `finalize_answer`, and `best_guess_fallback` is constructed exclusively from `schema_summary`, `profile_stats`, `question`/`context_messages`, and `step_history` (itself already aggregated). See [`architecture.md`](../architecture.md#llm-boundary-what-crosses-vs-what-stays-local) for the exact boundary.
- Generated code executes with no network access and a 15-second wall-clock timeout per step; only an allowlisted set of imports (`pandas`, `numpy`, `math`, `statistics`, `datetime`, `re`) is permitted.
- Only one run may be in progress per session at a time (`409` on a concurrent request).
- If the model is uncertain enough to need input rather than guess, it may return a clarifying question instead of code on the first step of a run — this ends the run without ever touching the sandbox.
- Conversation history from the same session is included in context so a follow-up question is answered with awareness of prior Q&A (session memory).

## Success Criteria

- [ ] A well-formed question about the dataset returns a plain-language answer whose key numbers match an independently computed ground truth over the *full* dataset (not a sample) — tested against a ≥5,000-row fixture.
- [ ] The outbound Gemini request payload, inspected across every step of a real multi-step run, never contains a raw data value from the fixture dataset — only schema/stats/code/question/error text.
- [ ] A question that requires refinement (the first generated code errors) is retried automatically and a correct answer is still produced within the step cap, with all attempted steps visible in `step_history`.
- [ ] A question that cannot be resolved within 6 steps returns a flagged best-guess answer (not an error, not a silent failure) with a description of what was tried.
- [ ] A second question in the same session that references the first answer (e.g. "and just the top 10 of that") is answered correctly using the persisted conversation history.
