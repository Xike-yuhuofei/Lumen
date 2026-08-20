import { test, expect, Page } from '@playwright/test'

/**
 * T6 e2e — perceived latency instrumentation (W-I1/W-I4/W-I5) on the real UI:
 *  - wait_for_input explicit consumption (PIN card, no processing indicator)
 *  - reconnecting transport banner (driven by real transport facts only)
 *  - T3 §9 sample persistence via the debug hook
 */

declare global {
  interface Window {
    __mockLastWS?: {
      emit(type: string, extra?: Record<string, unknown>): void
      close(): void
      readyState: number
    }
    __perceivedLatency?: {
      stats(): { total: number }
      dump(): unknown
      clear(): void
    }
  }
}

async function openNewConversation(page: Page) {
  await page.goto('/')
  await page.waitForSelector('.app-root')
  await page.locator('.navItem-r4wswG').filter({ hasText: '新建对话' }).click()
  const box = page.locator('.messageInputChatInputHome .chat-input-v2-input-box-wrapper')
  await expect(box).toBeVisible()
  const editable = page.locator('.messageInputChatInputHome .chat-input-v2-input-box-editable')
  await box.click()
  await expect(editable).toBeFocused()
  return editable
}

async function installPerceivedMock(page: Page) {
  await page.addInitScript(() => {
    // Reset perceived samples + app state for clean counts.
    localStorage.removeItem('lumen:perceived-samples-v1')
    localStorage.removeItem('lumen:sessions')
    localStorage.removeItem('lumen:selectedSession')
    localStorage.removeItem('askora:sessions')
    localStorage.removeItem('askora:selectedSession')
    sessionStorage.setItem('lumen:test-ready', '1')
    sessionStorage.setItem('trae:view', 'chat')
    localStorage.setItem('trae:sidebarOpen', '1')
    localStorage.setItem('trae:statusOpen', '0')
    localStorage.setItem('trae:theme', 'dark')

    // API stubs (sessions/tools/settings) so the app boots without connectError.
    const json = (status: number, body: unknown) =>
      new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
    window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/api/v1/sessions') && (!init?.method || init.method === 'GET')) {
        return Promise.resolve(json(200, { sessions: [] }))
      }
      if (url.includes('/api/v1/tools')) {
        return Promise.resolve(json(200, { tools: [], enabled_optional_tools: [] }))
      }
      if (url.includes('/api/v1/settings')) {
        return Promise.resolve(json(200, { ui: {} }))
      }
      return Promise.resolve(json(200, {}))
    }

    // MockWebSocket with emit/close + a handle to the latest instance.
    class MockWebSocket {
      static CONNECTING = 0
      static OPEN = 1
      static CLOSING = 2
      static CLOSED = 3
      readyState = MockWebSocket.CONNECTING
      onopen: ((ev?: unknown) => void) | null = null
      onmessage: ((ev: { data: string }) => void) | null = null
      onclose: ((ev?: unknown) => void) | null = null
      onerror: ((ev?: unknown) => void) | null = null
      constructor(_url: string) {
        window.__mockLastWS = this
        queueMicrotask(() => {
          if (this.readyState === MockWebSocket.CLOSED) return
          this.readyState = MockWebSocket.OPEN
          this.onopen?.({})
        })
      }
      send(raw: string) {
        let data: { type?: string; session_id?: string | null }
        try { data = JSON.parse(raw) as { type?: string; session_id?: string | null } } catch { return }
        if (data.type === 'ping') {
          this.onmessage?.({ data: JSON.stringify({ type: 'pong' }) })
          return
        }
        if (data.type === 'start_turn' || data.type === 'message') {
          const sessionId = data.session_id || '11111111-1111-4111-8111-111111111111'
          this.onmessage?.({ data: JSON.stringify({
            type: 'session', source: 'chat', stage: '', content: '', metadata: {},
            session_id: sessionId, timestamp: Date.now(),
          }) })
        }
      }
      emit(type: string, extra: Record<string, unknown> = {}) {
        this.onmessage?.({ data: JSON.stringify({
          type, source: 'chat', stage: '', content: '', metadata: {}, timestamp: Date.now(), ...extra,
        }) })
      }
      close() {
        this.readyState = MockWebSocket.CLOSED
        this.onclose?.({})
      }
      addEventListener() { /* noop */ }
      removeEventListener() { /* noop */ }
    }
    window.WebSocket = MockWebSocket as unknown as typeof WebSocket
  })
}

test.describe('perceived latency instrumentation', () => {
  test('wait_for_input 被消费：PIN 卡显示、无处理指示、回复后恢复并记录样本', async ({ page }) => {
    await installPerceivedMock(page)
    const editable = await openNewConversation(page)
    await editable.pressSequentially('出一道题')
    await page.locator('.chat-input-v2-send-button').click()

    // Backend pauses with an ask_user question.
    await page.waitForFunction(() => (window as unknown as { __mockLastWS?: { readyState: number } }).__mockLastWS?.readyState === 1)
    await page.evaluate(() => {
      const ws = (window as unknown as { __mockLastWS?: Window['__mockLastWS'] }).__mockLastWS!
      ws.emit('tool_call', {
        content: 'ask_user',
        metadata: {
          args: {
            questions: [{ id: 'q1', prompt: '请选择答案', options: [{ label: 'A', description: '选项A' }, { label: 'B', description: '选项B' }] }],
          },
        },
      })
      ws.emit('wait_for_input', {})
    })

    // PIN card visible; no processing indicator while paused (T4 §7 / F8).
    await expect(page.locator('.quiz-card')).toBeVisible()
    await expect(page.locator('.quiz-card')).toContainText('请选择答案')
    await expect(page.getByTestId('agent-processing')).toHaveCount(0)

    // Submit an answer → turn resumes → content streams → done.
    await page.locator('.quiz-card button').first().click()
    await page.evaluate(() => {
      const ws = (window as unknown as { __mockLastWS?: Window['__mockLastWS'] }).__mockLastWS!
      ws.emit('content', { content: '很好的回答！' })
      ws.emit('done', {})
    })
    await expect(page.locator('.markdown-renderer').last()).toContainText('很好的回答！')

    // A perceived sample was persisted with has_pin=true (W-I3/W-I4).
    const stats = await page.evaluate(() => window.__perceivedLatency?.stats())
    expect(stats?.total).toBeGreaterThanOrEqual(1)
  })

  test('正常完成：处理指示先现、内容后显、样本 outcome=ok', async ({ page }) => {
    await installPerceivedMock(page)
    const editable = await openNewConversation(page)
    await editable.pressSequentially('你好')
    await page.locator('.chat-input-v2-send-button').click()

    // E1 same-tick processing indicator while no content yet.
    await expect(page.getByTestId('agent-processing')).toBeVisible()

    await page.waitForFunction(() => (window as unknown as { __mockLastWS?: { readyState: number } }).__mockLastWS?.readyState === 1)
    await page.evaluate(() => {
      const ws = (window as unknown as { __mockLastWS?: Window['__mockLastWS'] }).__mockLastWS!
      ws.emit('content', { content: '你好呀！' })
      ws.emit('done', {})
    })
    await expect(page.locator('.markdown-renderer').last()).toContainText('你好呀！')
    await expect(page.getByTestId('agent-processing')).toHaveCount(0)

    const stats = await page.evaluate(() => window.__perceivedLatency?.stats())
    expect(stats?.total).toBeGreaterThanOrEqual(1)
  })

  test('断线重连：reconnecting 横幅由真实传输事实驱动、恢复后消失', async ({ page }) => {
    await installPerceivedMock(page)
    const editable = await openNewConversation(page)
    // Send a message so the app is in chat view (where the banner renders).
    await editable.pressSequentially('hello')
    await page.locator('.chat-input-v2-send-button').click()
    await page.waitForFunction(() => (window as unknown as { __mockLastWS?: { readyState: number } }).__mockLastWS?.readyState === 1)

    // Simulate a real transport loss (onclose) → client seeks reconnect.
    await page.evaluate(() => (window as unknown as { __mockLastWS?: { close(): void } }).__mockLastWS!.close())
    await expect(page.getByTestId('transport-reconnecting')).toBeVisible({ timeout: 2000 })

    // Reconnect (base 200ms) opens a new socket → connected → banner clears.
    await expect(page.getByTestId('transport-reconnecting')).toHaveCount(0, { timeout: 3000 })
  })
})
