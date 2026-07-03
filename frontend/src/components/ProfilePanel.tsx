'use client'

import type { DatasetProfileData } from './UploadZone'
import { ChartsTabStub } from './StubPanels'

interface ProfilePanelProps {
  profile: DatasetProfileData | null
}

function formatRange(col: DatasetProfileData['profile']['schema'][number]): string {
  if (col.min !== undefined && col.min !== null && col.max !== undefined && col.max !== null) {
    return `${col.min} – ${col.max}`
  }
  if (col.sample_values && col.sample_values.length > 0) {
    return col.sample_values.join(', ')
  }
  return '—'
}

export default function ProfilePanel({ profile }: ProfilePanelProps) {
  return (
    <div className="space-y-3">
      <div className="flex items-end gap-2">
        <h2 className="text-sm font-semibold text-gray-700">Dataset Profile</h2>
        <div className="ml-auto">
          <ChartsTabStub />
        </div>
      </div>

      {!profile && (
        <div className="rounded-lg border border-gray-200 bg-white p-6 text-center text-sm text-gray-500">
          Upload a CSV or Excel file to get started.
        </div>
      )}

      {profile && (
        <div
          className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
          data-testid="profile-panel"
        >
          <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
            <span className="font-medium text-gray-900">{profile.filename}</span>
            <span className="text-gray-500">{profile.row_count.toLocaleString()} rows</span>
            <span className="text-gray-400" aria-hidden="true">·</span>
            <span className="text-gray-500">{profile.column_count} columns</span>
          </div>

          <div className="max-h-80 overflow-y-auto rounded-md border border-gray-100">
            <table className="w-full text-left text-xs">
              <thead className="sticky top-0 bg-gray-50 text-gray-500">
                <tr>
                  <th className="px-3 py-2 font-medium">Column</th>
                  <th className="px-3 py-2 font-medium">Type</th>
                  <th className="px-3 py-2 font-medium">Nulls</th>
                  <th className="px-3 py-2 font-medium">Range / sample</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {profile.profile.schema.map(col => (
                  <tr key={col.name}>
                    <td className="px-3 py-2 font-medium text-gray-800">{col.name}</td>
                    <td className="px-3 py-2 text-gray-500">{col.dtype}</td>
                    <td className="px-3 py-2 text-gray-500">{col.null_count}</td>
                    <td className="px-3 py-2 text-gray-500">{formatRange(col)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
