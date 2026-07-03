'use client'

/**
 * Labelled, non-functional Phase 2 stubs.
 *
 * Every element here is intentionally disabled and carries a visible
 * "Coming in Phase 2" badge/tooltip so it is never mistaken for a bug.
 * None of these wire up to real behaviour until Phase 2.
 */

function Phase2Badge() {
  return (
    <span
      className="ml-2 inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-medium tracking-wide text-amber-800"
      title="Coming in Phase 2"
    >
      Phase 2
    </span>
  )
}

/** Disabled "Charts" tab shown next to the profile panel. */
export function ChartsTabStub() {
  return (
    <button
      type="button"
      disabled
      title="Coming in Phase 2"
      aria-disabled="true"
      className="inline-flex cursor-not-allowed items-center rounded-t-lg border border-b-0 border-gray-200 bg-gray-50 px-4 py-2 text-sm font-medium text-gray-400"
    >
      Charts
      <Phase2Badge />
    </button>
  )
}

/** Disabled multi-file/folder upload toggle next to the Upload Zone. */
export function MultiFileToggleStub() {
  return (
    <label
      title="Coming in Phase 2"
      className="flex cursor-not-allowed items-center gap-2 text-xs text-gray-400 select-none"
    >
      <input type="checkbox" disabled aria-disabled="true" className="cursor-not-allowed" />
      Multi-file / folder upload
      <Phase2Badge />
    </label>
  )
}

/** Disabled "Export" button in the chat header. */
export function ExportButtonStub() {
  return (
    <button
      type="button"
      disabled
      title="Coming in Phase 2"
      aria-disabled="true"
      className="inline-flex cursor-not-allowed items-center rounded-lg border border-gray-200 bg-gray-50 px-3 py-1.5 text-xs font-medium text-gray-400"
    >
      Export
      <Phase2Badge />
    </button>
  )
}

/** Disabled "Session History" sidebar entry. */
export function SessionHistoryStub() {
  return (
    <div
      title="Coming in Phase 2"
      aria-disabled="true"
      className="flex cursor-not-allowed items-center justify-between rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-400"
    >
      <span>Session History</span>
      <Phase2Badge />
    </div>
  )
}

/** Cost-per-query pill — renders "—" until Phase 2 wires a real estimate. */
export function CostPill() {
  return (
    <span
      title="Cost estimate coming in Phase 2"
      className="inline-flex items-center rounded-full border border-gray-200 bg-gray-50 px-2 py-0.5 text-xs font-medium text-gray-400"
    >
      &mdash;
    </span>
  )
}
