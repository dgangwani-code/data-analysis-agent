'use client'

import { useCallback, useRef, useState } from 'react'
import { MultiFileToggleStub } from './StubPanels'

export interface ColumnProfile {
  name: string
  dtype: string
  null_count: number
  distinct_count?: number
  sample_values?: string[]
  min?: string | number | null
  max?: string | number | null
}

export interface DatasetProfileData {
  dataset_id: string
  session_id: string
  filename: string
  status: string
  row_count: number
  column_count: number
  profile: {
    schema: ColumnProfile[]
    stats_summary?: Record<string, Record<string, number>>
  }
}

const ACCEPTED_EXTENSIONS = ['.csv', '.xlsx']

function hasAcceptedExtension(filename: string): boolean {
  const lower = filename.toLowerCase()
  return ACCEPTED_EXTENSIONS.some(ext => lower.endsWith(ext))
}

interface UploadZoneProps {
  sessionId: string | null
  onUploaded: (profile: DatasetProfileData) => void
}

export default function UploadZone({ sessionId, onUploaded }: UploadZoneProps) {
  const [isDragging, setIsDragging] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const uploadFile = useCallback(
    async (file: File) => {
      setError(null)

      if (!hasAcceptedExtension(file.name)) {
        setError("Couldn't read this file — is it a valid CSV or Excel file?")
        return
      }

      setLoading(true)
      try {
        const formData = new FormData()
        formData.append('file', file)
        if (sessionId) {
          formData.append('session_id', sessionId)
        }

        const res = await fetch('/datasets', {
          method: 'POST',
          body: formData,
        })

        let payload: any = null
        try {
          payload = await res.json()
        } catch {
          payload = null
        }

        if (!res.ok) {
          const message =
            payload?.detail?.message ??
            (res.status === 413
              ? 'This file is too large to upload.'
              : "Couldn't read this file — is it a valid CSV or Excel file?")
          setError(message)
          return
        }

        if (!payload?.data) {
          setError("Couldn't read this file — is it a valid CSV or Excel file?")
          return
        }

        onUploaded(payload.data as DatasetProfileData)
      } catch {
        setError('Network error — is the server running?')
      } finally {
        setLoading(false)
      }
    },
    [sessionId, onUploaded]
  )

  function handleDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setIsDragging(false)
    const file = e.dataTransfer.files?.[0]
    if (file) void uploadFile(file)
  }

  function handleDragOver(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setIsDragging(true)
  }

  function handleDragLeave(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setIsDragging(false)
  }

  function handlePick() {
    inputRef.current?.click()
  }

  function handleFileInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (file) void uploadFile(file)
    e.target.value = ''
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-700">Upload dataset</h2>
        <MultiFileToggleStub />
      </div>

      <div
        role="button"
        tabIndex={0}
        aria-label="Upload a CSV or Excel file"
        onClick={handlePick}
        onKeyDown={e => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            handlePick()
          }
        }}
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        className={`flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed p-8 text-center transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 ${
          isDragging ? 'border-blue-500 bg-blue-50' : 'border-gray-300 bg-white hover:bg-gray-50'
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".csv,.xlsx"
          onChange={handleFileInputChange}
          className="hidden"
          aria-hidden="true"
          disabled={loading}
        />

        {loading ? (
          <div className="flex flex-col items-center gap-2">
            <div
              className="h-6 w-6 animate-spin rounded-full border-2 border-blue-600 border-t-transparent"
              role="status"
              aria-label="Uploading and profiling"
            />
            <p className="text-sm text-gray-500">Uploading &amp; profiling…</p>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-1">
            <p className="text-sm font-medium text-gray-700">
              Drag &amp; drop a CSV or Excel file here
            </p>
            <p className="text-xs text-gray-400">or click to browse — .csv, .xlsx</p>
          </div>
        )}
      </div>

      {error && (
        <div
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"
        >
          {error}
          <button
            type="button"
            onClick={handlePick}
            className="ml-2 font-medium underline underline-offset-2 hover:text-red-900"
          >
            Try again
          </button>
        </div>
      )}
    </div>
  )
}
