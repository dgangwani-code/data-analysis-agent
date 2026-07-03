'use client'

import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

export type ChatRole = 'user' | 'assistant'

export interface MessageBubbleProps {
  role: ChatRole
  content: string
  /** Set when the run exhausted its step budget and this is a flagged best-guess answer. */
  isFallback?: boolean
  /** Set when the assistant turn represents an error (never a raw stack trace — plain language only). */
  isError?: boolean
  children?: React.ReactNode
}

/**
 * Renders one chat turn. User turns are right-aligned, assistant turns are
 * left-aligned, per spec/ui.md. Assistant content is always rendered through
 * a markdown renderer (react-markdown + remark-gfm) — never a raw text node.
 */
export default function MessageBubble({ role, content, isFallback, isError, children }: MessageBubbleProps) {
  const isUser = role === 'user'

  return (
    <div
      data-testid={`message-${role}`}
      className={`flex w-full ${isUser ? 'justify-end' : 'justify-start'}`}
    >
      <div
        className={`max-w-[85%] rounded-lg px-4 py-3 text-sm shadow-sm ${
          isUser
            ? 'bg-blue-600 text-white'
            : isError
              ? 'border border-red-200 bg-red-50 text-red-700'
              : 'border border-gray-200 bg-white text-gray-900'
        }`}
      >
        {isFallback && (
          <span
            data-testid="fallback-badge"
            className="mb-2 inline-block rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800"
            title="The agent could not fully resolve this within its step budget — this is its best guess."
          >
            best guess
          </span>
        )}
        {isUser ? (
          <p className="whitespace-pre-wrap">{content}</p>
        ) : (
          <div className="markdown-body space-y-2 [&_a]:text-blue-600 [&_a]:underline [&_code]:rounded [&_code]:bg-gray-100 [&_code]:px-1 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-xs [&_li]:ml-4 [&_li]:list-disc [&_strong]:font-semibold [&_table]:w-full [&_table]:border-collapse [&_td]:border [&_td]:border-gray-200 [&_td]:px-2 [&_td]:py-1 [&_th]:border [&_th]:border-gray-200 [&_th]:bg-gray-50 [&_th]:px-2 [&_th]:py-1">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
          </div>
        )}
        {children}
      </div>
    </div>
  )
}
