'use client'

import { useState } from 'react'
import UploadZone, { type DatasetProfileData } from '@/components/UploadZone'
import ProfilePanel from '@/components/ProfilePanel'
import {
  ExportButtonStub,
  SessionHistoryStub,
} from '@/components/StubPanels'
import ChatThread from '@/components/ChatThread'

export default function Home() {
  const [profile, setProfile] = useState<DatasetProfileData | null>(null)

  const sessionId = profile?.session_id ?? null
  const datasetId = profile?.dataset_id ?? null

  return (
    <main className="mx-auto flex min-h-screen max-w-7xl flex-col gap-6 px-4 py-8 md:h-screen md:flex-row md:overflow-hidden">
      {/* Left / top panel — sidebar rail + upload + profile + stub tabs */}
      <section className="flex w-full flex-col gap-6 md:h-full md:w-[420px] md:shrink-0 md:overflow-y-auto md:pr-2">
        <div>
          <h1 className="mb-1 text-2xl font-bold tracking-tight text-gray-900">
            Data Analysis Agent
          </h1>
          <p className="text-sm text-gray-500">
            Upload a dataset, see it profiled instantly, then ask questions about it.
          </p>
        </div>

        <SessionHistoryStub />

        <UploadZone sessionId={sessionId} onUploaded={setProfile} />

        <ProfilePanel profile={profile} />
      </section>

      {/* Right / main panel — chat thread */}
      <section className="flex min-h-[60vh] w-full flex-1 flex-col overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm md:h-full">
        <header className="flex items-center justify-between border-b border-gray-200 px-4 py-3">
          <h2 className="text-sm font-semibold text-gray-700">Chat</h2>
          <ExportButtonStub />
        </header>

        <div className="flex-1 overflow-hidden">
          <ChatThread sessionId={sessionId} datasetId={datasetId} />
        </div>
      </section>
    </main>
  )
}
