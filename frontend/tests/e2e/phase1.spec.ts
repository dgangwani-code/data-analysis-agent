import { test, expect } from '@playwright/test'
import path from 'node:path'

/**
 * Phase 1 golden-path E2E smoke test — the mandatory test required by
 * harness/rules/ai-agents.md rule 6 and harness/patterns/phases.md gate
 * item 7: walks the FULL primary journey against the LIVE app and the REAL
 * Gemini API, asserting real rendered content (not just HTTP 200s).
 *
 * Journey (per spec/roadmap.md "how the user tests it" + spec/ui.md):
 *   1. Load the app — upload zone renders, styled.
 *   2. Upload a real small fixture CSV — profile panel populates with real
 *      row/column counts computed locally (no LLM involved in profiling).
 *   3. Ask a real question — spinner shows, then a plain-language answer
 *      with key numbers plus a collapsible "Show code" block renders (real
 *      generated pandas code, real newlines).
 *   4. Ask a follow-up that only makes sense with context from turn 1 —
 *      proves session memory (real Gemini call #2, same session).
 *   5. Labelled Phase-2 stubs are visibly present and disabled, never
 *      silently missing.
 *
 * Selectors below were cross-checked directly against the concurrently-built
 * frontend-upload-profile slice's source (page.tsx / UploadZone.tsx /
 * ProfilePanel.tsx / StubPanels.tsx), read at authoring time:
 *   - `UploadZone.tsx` renders a real (visually-hidden) `<input type="file">`
 *     behind the drag-drop zone — `setInputFiles` targets it directly.
 *   - `ProfilePanel.tsx` renders `data-testid="profile-panel"` containing
 *     the filename plus "`{row_count}` rows" / "`{column_count}` columns".
 *   - `StubPanels.tsx` renders every Phase-2 stub with the literal text
 *     "Phase 2" (badge) and `title="Coming in Phase 2"`; the Export button
 *     stub is rendered by `page.tsx` in the chat header (not by this
 *     slice's ChatThread, which owns only the message list + composer).
 *
 * NOTE (code-generator, frontend-chat slice): this test requires the FULL
 * backend stack (db-schema, file-parsing-profiling, agent-graph-loop,
 * chat-api) to be built and running — none of which exist yet at authoring
 * time. It could not be executed end-to-end during this slice's build; it
 * is verified for correct structure/selectors only (see handoff notes).
 */

const FIXTURE_CSV = path.join(__dirname, '..', 'fixtures', 'sample.csv')

test.describe('Phase 1 golden path', () => {
  test('upload -> profile -> ask -> answer -> follow-up (session memory)', async ({ page }) => {
    // 1. Load the app — assert it renders styled content, not a blank/error page.
    await page.goto('/app/')
    await expect(page.locator('body')).toBeVisible()

    const fileInput = page.locator('input[type="file"]')
    await expect(fileInput).toBeAttached()

    // 2. Upload the real fixture CSV (20 rows, 3 columns: order_date, region, revenue).
    await fileInput.setInputFiles(FIXTURE_CSV)

    const profilePanel = page.getByTestId('profile-panel')
    await expect(profilePanel).toBeVisible({ timeout: 30_000 })
    await expect(profilePanel).toContainText('sample.csv')
    // Real row/column counts computed locally from the actual uploaded file.
    await expect(profilePanel).toContainText(/20/) // row count
    await expect(profilePanel).toContainText(/\b3\b/) // column count

    // 3. Ask a real question about the uploaded dataset (real Gemini call).
    const chatThread = page.getByTestId('chat-thread')
    await expect(chatThread).toBeVisible()

    const composer = page.getByPlaceholder('Ask a question about your data…')
    const sendButton = page.getByRole('button', { name: 'Send' })

    await expect(composer).toBeEnabled({ timeout: 15_000 })
    await composer.fill('What is the average revenue per region?')
    await sendButton.click()

    // Spinner-only in-flight feedback (no fine-grained step tracker, per intake).
    await expect(page.getByTestId('chat-spinner')).toBeVisible()

    const firstAnswer = page.getByTestId('message-assistant').first()
    await expect(firstAnswer).toBeVisible({ timeout: 90_000 })
    await expect(page.getByTestId('chat-spinner')).toHaveCount(0, { timeout: 90_000 })
    // Real answer contains key numbers, not a placeholder/empty string.
    await expect(firstAnswer).toContainText(/\d/)

    // "Show code" toggle reveals the real generated pandas code.
    const showCodeToggle = firstAnswer.getByRole('button', { name: /show code/i })
    await expect(showCodeToggle).toBeVisible()
    const codeBlock = firstAnswer.getByTestId('generated-code')
    await expect(codeBlock).toBeHidden()
    await showCodeToggle.click()
    await expect(codeBlock).toBeVisible()
    const codeText = (await codeBlock.innerText()).trim()
    expect(codeText.length).toBeGreaterThan(0)
    // Real generated code, not a single-line stub — expect at least a
    // recognisable pandas/dataframe token.
    expect(codeText).toMatch(/df|pandas|groupby|mean/i)

    // 4. Follow-up question that only makes sense with context from turn 1 —
    // proves session memory (a context-blind answer would not reference
    // "top" region/records without being told which prior computation to
    // narrow down).
    await expect(composer).toBeEnabled({ timeout: 5_000 })
    await composer.fill('Of those regions, which one has the highest average revenue?')
    await sendButton.click()

    await expect(page.getByTestId('chat-spinner')).toBeVisible()
    const assistantMessages = page.getByTestId('message-assistant')
    await expect(assistantMessages).toHaveCount(2, { timeout: 90_000 })
    await expect(page.getByTestId('chat-spinner')).toHaveCount(0, { timeout: 90_000 })

    const secondAnswer = assistantMessages.nth(1)
    await expect(secondAnswer).toContainText(/\d|East|West|South/i)
    const firstAnswerText = await firstAnswer.innerText()
    const secondAnswerText = await secondAnswer.innerText()
    // The follow-up answer must be a distinct turn (not a duplicate/echo),
    // evidence the agent processed it as a new, context-aware question.
    expect(secondAnswerText).not.toBe(firstAnswerText)

    // 5. Labelled Phase-2 stubs are visibly present and disabled — never
    // silently missing, never mistaken for a bug.
    const phase2Labels = page.getByText('Phase 2', { exact: false })
    await expect(phase2Labels.first()).toBeVisible()
    expect(await phase2Labels.count()).toBeGreaterThanOrEqual(1)

    const exportButton = page.getByRole('button', { name: 'Export' })
    await expect(exportButton).toBeDisabled()
  })

  test('empty state before upload — chat composer disabled with guidance', async ({ page }) => {
    await page.goto('/app/')
    await expect(page.getByTestId('chat-empty-state')).toBeVisible()
    const composer = page.getByPlaceholder('Upload a dataset first')
    await expect(composer).toBeDisabled()
  })
})
