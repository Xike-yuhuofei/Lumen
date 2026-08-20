/**
 * T6 / W-I7 — T4 §11.1 static-review automation tests.
 */

import { describe, it, expect } from 'vitest'
import {
  runStaticReview,
  type ReviewTraceInput,
  type PerceivedEvent,
} from '../../src/lib/perceived'
import { cleanDecisive, deriveStateSequence } from '../../src/lib/perceived'

const ev = (type: string, content: string, atMs: number, metadata: Record<string, unknown> = {}): PerceivedEvent => ({
  type,
  content,
  metadata,
  arrivalAt: atMs,
})

function baseInput(overrides: Partial<ReviewTraceInput> = {}): ReviewTraceInput {
  const events = [
    ev('session', '', 10),
    ev('content', 'answer', 2000),
    ev('done', '', 3000),
  ]
  const { decisive } = cleanDecisive(events)
  const derived = deriveStateSequence({ tSubmit: 0, decisive, actions: [] })
  return {
    tSubmit: 0,
    decisive,
    actions: [],
    transport: [],
    derived,
    ui: {
      firstFeedbackAt: 0,
      processing: [{ at: 0, shown: true }, { at: 2000, shown: false }],
      questionCard: [],
      errorBlocks: [],
      timeoutBlocks: [],
      contentRenderedAt: 2000,
      phaseTexts: [{ at: 0, text: '正在处理…' }],
      transportBanners: [],
    },
    ...overrides,
  }
}

describe('T4 §11.1 static review', () => {
  it('正常 chat 轨迹全 PASS', () => {
    const r = runStaticReview(baseInput())
    expect(r.passed).toBe(true)
    expect(r.violations).toEqual([])
    expect(r.prohibited_hits).toEqual([])
  })

  it('同 tick 首反馈：E1 必须与 tSubmit 同 tick', () => {
    const bad = baseInput({ ui: { ...baseInput().ui, firstFeedbackAt: 500 } })
    expect(runStaticReview(bad).checks.same_tick_first_feedback).toBe(false)
    const good = baseInput()
    expect(runStaticReview(good).checks.same_tick_first_feedback).toBe(true)
  })

  it('首反馈本地性：E1 必须先于首个决定性事件（非 TTFD/M3）', () => {
    const bad = baseInput({ ui: { ...baseInput().ui, firstFeedbackAt: 2500 } })
    expect(runStaticReview(bad).checks.first_feedback_locality).toBe(false)
  })

  it('传输事实驱动：banner 状态必须来自真实传输事实，禁止静默推断', () => {
    // Banner with a status never produced by the transport layer → FAIL (B7).
    const bad = baseInput({
      transport: [],
      ui: { ...baseInput().ui, transportBanners: [{ at: 1000, status: 'disconnected' }] },
    })
    expect(runStaticReview(bad).checks.transport_fact_driven).toBe(false)

    // Banner backed by a real transport fact → PASS.
    const good = baseInput({
      transport: [{ status: 'disconnected', at: 1000 }],
      ui: { ...baseInput().ui, transportBanners: [{ at: 1000, status: 'disconnected' }] },
    })
    expect(runStaticReview(good).checks.transport_fact_driven).toBe(true)
  })

  it('F8 禁止：PIN 中不得有处理指示', () => {
    const bad = baseInput({
      ui: {
        ...baseInput().ui,
        questionCard: [{ at: 1000, shown: true }],
        processing: [{ at: 1000, shown: true }],
      },
    })
    expect(runStaticReview(bad).checks.prohibited_patterns).toBe(false)
  })

  it('非破坏性：ER/CA/TO 终态保留已渲染内容（尾部追加）', () => {
    const events = [
      ev('content', 'part1', 1000),
      ev('error', 'failed', 2000),
    ]
    const { decisive } = cleanDecisive(events)
    const derived = deriveStateSequence({ tSubmit: 0, decisive, actions: [] })
    const good = baseInput({
      decisive,
      derived,
      ui: {
        ...baseInput().ui,
        contentRenderedAt: 1000,
        errorBlocks: [{ at: 2000 }],
        processing: [{ at: 0, shown: true }, { at: 1000, shown: false }],
      },
    })
    expect(runStaticReview(good).checks.non_destructive).toBe(true)
  })

  it('PIN 豁免：PIN 中 idle timer 不得触发 TO', () => {
    const events = [
      ev('content', 'c', 1000),
      ev('wait_for_input', '', 2000),
      ev('content', 'c2', 9000),
      ev('done', '', 10000),
    ]
    const { decisive } = cleanDecisive(events)
    const derived = deriveStateSequence({ tSubmit: 0, decisive, actions: [{ kind: 'submit_user_reply', at: 8500 }] })
    const input: ReviewTraceInput = {
      tSubmit: 0,
      decisive,
      actions: [{ kind: 'submit_user_reply', at: 8500 }],
      transport: [],
      derived,
      ui: { ...baseInput().ui, questionCard: [{ at: 2000, shown: true }] },
    }
    expect(runStaticReview(input).checks.pin_exemption).toBe(true)
  })
})
