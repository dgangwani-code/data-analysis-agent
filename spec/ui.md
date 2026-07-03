# UI

---

## UI Type

Web dashboard / chat interface — a single-page workspace: dataset upload + profile on one side, an ongoing chat thread on the other. Follows `harness/patterns/ui-ux.md` in full (all four states per view, chat responses rendered as markdown, no dual-representation, accessible/keyboard-reachable controls).

## Views / Screens

### Screen: Workspace (single screen, Phase 1's only screen)

**Purpose:** Upload a dataset, see it profiled, and have a running chat conversation about it — the entire primary journey lives on one screen; there is no navigation between "upload" and "ask" as separate steps.

**Layout:** a left/top panel (Upload Zone → Dataset Profile Panel → labelled stub tabs) and a right/main panel (Chat Thread), matching a typical two-pane analysis-tool layout. On narrow viewports the layout stacks vertically (profile panel above chat) with no horizontal scroll or clipping.

**Key elements:**
- **Upload Zone** — drag-and-drop + click-to-pick file input, accepts `.csv`/`.xlsx`. Real and functional in Phase 1 for a single file.
- **Dataset Profile Panel** — appears immediately after upload completes: filename, row count, column count, and a scrollable table of `{column, type, nulls, range/sample}` — real, computed from the actual uploaded file, no LLM involved.
- **Chat Thread** — message bubbles (`user` right-aligned, `assistant` left-aligned), rendered through a markdown renderer (`react-markdown` + `remark-gfm` — never a raw text node, per `harness/patterns/ui-ux.md`).
- **Collapsible Code Block** — under each assistant answer, a "Show code" toggle reveals the generated pandas code (syntax-highlighted, monospace, real newlines/indentation — never a single-line string) that produced the answer. If the run took multiple refine steps, all attempted steps are listed (collapsed), each labelled with its outcome (succeeded / errored and why), giving the "what it tried" view.
- **Loop Spinner** — while a question is in flight, the composer disables and a spinner with contextual copy ("Analyzing…") shows in place of the next assistant bubble. No fine-grained step tracker (per intake) — just the spinner.
- **Message Composer** — text input + send button, disabled while a run is in progress (enforced client-side to match the API's single-run-at-a-time rule).
- **Labelled stub areas (visibly non-functional in Phase 1, never mistaken for bugs):**
  - A "Charts" tab next to the profile panel — disabled, with a tooltip/badge reading "Coming in Phase 2".
  - A multi-file/folder upload toggle next to the Upload Zone — disabled, same "Phase 2" badge.
  - An "Export" button in the chat header — disabled, same badge.
  - A "Session History" entry in a left rail/sidebar — disabled, same badge (Phase 1 has exactly one active session; no history browsing yet, though the data is already being persisted).
  - A cost-per-query pill next to each assistant answer — renders `—` with a tooltip "Cost estimate coming in Phase 2" instead of a number.

**Actions available:**
- Upload a file (drag-drop or file picker).
- Send a chat message (question).
- Toggle "Show code" per answer.
- Expand the "what it tried" step list on a fallback answer.

## Error States

- **Upload error** (unsupported type, unparsable file, size limit): the Upload Zone shows an inline red message naming the problem ("Couldn't read this file — is it a valid CSV or Excel file?") and lets the user try again immediately; never a raw stack trace.
- **Ask error** (Gemini unavailable, dataset missing, run failed): the assistant bubble itself renders the error in plain language ("Couldn't reach the analysis service — try asking again in a moment.") with a retry affordance (re-send the same question), not a red banner detached from the conversation.
- **Fallback answer** (step budget exhausted): rendered as a normal assistant bubble but visibly flagged — a small "best guess" badge — with the "what it tried" disclosure pre-expanded once, so the user immediately sees why confidence is lower.
- **Loading:** Upload Zone shows a determinate/looping progress affordance while parsing+profiling runs (typically a few seconds for Phase 1 file sizes); Chat Thread shows the spinner described above. Neither is a frozen screen.
- **Empty state:** before any file is uploaded, the Profile Panel shows guidance copy ("Upload a CSV or Excel file to get started") and the Chat Thread's composer is disabled with a tooltip explaining a dataset is needed first — never a blank panel with no explanation.

## Tech Stack

Next.js 15 + React 19 (already scaffolded), Tailwind v4 for styling (existing `postcss.config.mjs` / `@source` setup preserved, never overwritten), `react-markdown` + `remark-gfm` for chat rendering (new dependency), static-exported and served by FastAPI at `/app` per `harness/patterns/tech-stack.md`. Phase 1 ships one simple client-rendered summary table for the profile (no charting library yet); Phase 2 adds `recharts` for the Charts tab.

Playwright (`@playwright/test`) is the required E2E tool — `tests/e2e/phase1.spec.ts` (Phase 1) covers: page loads styled, upload → profile renders with real row/column counts, ask a question → real answer with a code block renders, labelled stubs are visibly present and disabled (not silently missing). `tests/e2e/phase2.spec.ts` extends this for multi-file/chart/history/export in Phase 2.
