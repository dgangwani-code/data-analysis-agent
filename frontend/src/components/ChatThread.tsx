'use client'

import { useEffect, useRef, useState } from 'react'
import MessageBubble from './MessageBubble'
import CodeBlock, { type AnalysisStep } from './CodeBlock'

interface DisplayMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  isError?: boolean
  isFallback?: boolean
  finalCode?: string
  steps?: AnalysisStep[]
}

interface HistoryMessage {
  role: 'user' | 'assistant'
  content: string
  run_id?: string | null
  created_at?: string
}

export interface ChatThreadProps {
  /** The active session for this workspace (set together with datasetId once a dataset is uploaded). */
  sessionId: string | null
  /** The active dataset for this workspace. Chat is disabled until a dataset exists. */
  datasetId: string | null
}

function newId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID()
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

/**
 * The chat thread: message history + composer. Talks to the real backend —
 * loads history via GET /sessions/{id}/messages and asks questions via
 * POST /sessions/{id}/messages. Per spec/ui.md: spinner-only in-flight
 * feedback (no fine-grained step tracker), collapsible code per answer,
 * in-thread error bubbles with retry (never a raw stack trace). The chat
 * header (title + Export stub) is rendered by the parent (page.tsx); this
 * component owns only the message list + composer.
 */
export default function ChatThread({ sessionId, datasetId }: ChatThreadProps) {
  const [messages, setMessages] = useState<DisplayMessage[]>([])
  const [input, setInput] = useState('')
  const [pending, setPending] = useState(false)
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const threadEndRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    let cancelled = false

    if (!sessionId) {
      setMessages([])
      setLoadError(null)
      return
    }

    async function loadHistory() {
      setLoadingHistory(true)
      setLoadError(null)
      try {
        const historyRes = await fetch(`/sessions/${sessionId}/messages`)
        const historyJson = await historyRes.json()
        if (!historyRes.ok) {
          throw new Error(historyJson?.detail?.message ?? `Couldn't load conversation (${historyRes.status})`)
        }
        if (cancelled) return
        const history: HistoryMessage[] = historyJson.data.messages ?? []
        setMessages(
          history.map(m => ({
            id: newId(),
            role: m.role,
            content: m.content,
          }))
        )
      } catch (err) {
        if (!cancelled) {
          setLoadError(err instanceof Error ? err.message : 'Network error — is the server running?')
        }
      } finally {
        if (!cancelled) setLoadingHistory(false)
      }
    }

    loadHistory()
    return () => {
      cancelled = true
    }
  }, [sessionId])

  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, pending])

  async function sendQuestion(content: string) {
    if (!sessionId || pending || !content.trim()) return

    setPending(true)
    setMessages(prev => [...prev, { id: newId(), role: 'user', content }])

    try {
      const res = await fetch(`/sessions/${sessionId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
      })
      const json = await res.json()

      if (!res.ok) {
        const message = json?.detail?.message ?? `Couldn't reach the analysis service — try asking again in a moment.`
        setMessages(prev => [
          ...prev,
          { id: newId(), role: 'assistant', content: message, isError: true },
        ])
        return
      }

      const data = json.data
      setMessages(prev => [
        ...prev,
        {
          id: newId(),
          role: 'assistant',
          content: data.answer,
          isFallback: Boolean(data.is_fallback),
          finalCode: data.final_code,
          steps: data.steps,
        },
      ])
    } catch {
      setMessages(prev => [
        ...prev,
        {
          id: newId(),
          role: 'assistant',
          content: "Couldn't reach the analysis service — try asking again in a moment.",
          isError: true,
        },
      ])
    } finally {
      setPending(false)
    }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const content = input.trim()
    if (!content) return
    setInput('')
    void sendQuestion(content)
  }

  function retry(content: string) {
    void sendQuestion(content)
  }

  const composerDisabled = !datasetId || !sessionId || pending || loadingHistory

  return (
    <div data-testid="chat-thread" className="flex h-full flex-col">
      <div className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
        {!datasetId && (
          <p data-testid="chat-empty-state" className="mt-10 text-center text-sm text-gray-400">
            Upload a dataset to start chatting.
          </p>
        )}

        {datasetId && loadingHistory && messages.length === 0 && (
          <p className="mt-10 text-center text-sm text-gray-400">Loading conversation…</p>
        )}

        {loadError && (
          <div
            data-testid="chat-load-error"
            className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"
          >
            {loadError}
          </div>
        )}

        {messages.map(m => (
          <MessageBubble
            key={m.id}
            role={m.role}
            content={m.content}
            isError={m.isError}
            isFallback={m.isFallback}
          >
            {m.role === 'assistant' && !m.isError && m.finalCode && (
              <CodeBlock code={m.finalCode} steps={m.steps} defaultStepsExpanded={m.isFallback} />
            )}
            {m.isError && (
              <button
                type="button"
                onClick={() => {
                  const lastUser = [...messages].reverse().find(msg => msg.role === 'user')
                  if (lastUser) retry(lastUser.content)
                }}
                className="mt-2 rounded-md border border-red-300 bg-white px-2 py-1 text-xs font-medium text-red-700 hover:bg-red-100"
              >
                Retry
              </button>
            )}
          </MessageBubble>
        ))}

        {pending && (
          <div data-testid="chat-spinner" className="flex items-center gap-2 text-sm text-gray-500">
            <span
              className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-gray-300 border-t-blue-600"
              aria-hidden="true"
            />
            Analyzing…
          </div>
        )}

        <div ref={threadEndRef} />
      </div>

      <form onSubmit={handleSubmit} className="flex gap-2 border-t border-gray-200 p-3">
        <input
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          disabled={composerDisabled}
          placeholder={datasetId ? 'Ask a question about your data…' : 'Upload a dataset first'}
          title={datasetId ? undefined : 'Upload a dataset to start chatting'}
          className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:bg-gray-100 disabled:text-gray-400"
        />
        <button
          type="submit"
          disabled={composerDisabled || !input.trim()}
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          Send
        </button>
      </form>
    </div>
  )
}
