'use client'

import { useState } from 'react'

export interface AnalysisStep {
  step_number: number
  generated_code: string
  status: 'success' | 'error'
  result_summary?: Record<string, unknown> | string | null
  error_message?: string | null
}

export interface CodeBlockProps {
  /** The code that produced the final answer. */
  code: string
  /** Optional full step history for the "what it tried" disclosure (multi-step runs). */
  steps?: AnalysisStep[]
  /** Pre-expand the step list once (used for fallback answers per spec/ui.md). */
  defaultStepsExpanded?: boolean
}

/**
 * Collapsible, monospace code block for the generated pandas code behind an
 * answer. Collapsed by default. If step history is provided (multi-step
 * refine loop), each attempted step is listed with its outcome.
 */
export default function CodeBlock({ code, steps, defaultStepsExpanded = false }: CodeBlockProps) {
  const [showCode, setShowCode] = useState(false)
  const [showSteps, setShowSteps] = useState(defaultStepsExpanded)

  return (
    <div className="mt-3 border-t border-gray-100 pt-2">
      <button
        type="button"
        onClick={() => setShowCode(v => !v)}
        aria-expanded={showCode}
        className="flex items-center gap-1 text-xs font-medium text-gray-600 hover:text-gray-900"
      >
        <span className={`inline-block transition-transform ${showCode ? 'rotate-90' : ''}`}>{'▶'}</span>
        {showCode ? 'Hide code' : 'Show code'}
      </button>

      {showCode && (
        <pre
          data-testid="generated-code"
          className="mt-2 overflow-x-auto rounded-md bg-gray-900 p-3 font-mono text-xs whitespace-pre text-gray-100"
        >
          <code>{code}</code>
        </pre>
      )}

      {steps && steps.length > 1 && (
        <div className="mt-2">
          <button
            type="button"
            onClick={() => setShowSteps(v => !v)}
            aria-expanded={showSteps}
            className="flex items-center gap-1 text-xs font-medium text-gray-600 hover:text-gray-900"
          >
            <span className={`inline-block transition-transform ${showSteps ? 'rotate-90' : ''}`}>{'▶'}</span>
            {showSteps ? 'Hide what it tried' : `What it tried (${steps.length} steps)`}
          </button>

          {showSteps && (
            <ol data-testid="step-list" className="mt-2 space-y-2">
              {steps.map(step => (
                <li key={step.step_number} className="rounded-md border border-gray-200 p-2">
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-medium">Step {step.step_number}</span>
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                        step.status === 'success'
                          ? 'bg-green-100 text-green-800'
                          : 'bg-red-100 text-red-800'
                      }`}
                    >
                      {step.status === 'success' ? 'succeeded' : 'errored'}
                    </span>
                  </div>
                  <pre className="mt-1 overflow-x-auto rounded bg-gray-900 p-2 font-mono text-xs whitespace-pre text-gray-100">
                    <code>{step.generated_code}</code>
                  </pre>
                  {step.status === 'error' && step.error_message && (
                    <p className="mt-1 text-xs text-red-700">{step.error_message}</p>
                  )}
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </div>
  )
}
