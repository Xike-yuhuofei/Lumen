/**
 * T6 / W-I3 — T3 M1–M8 metric computation tests.
 *
 * Verifies the frozen T3 §12 T1–T12 metric examples (values in seconds),
 * SYS_WAIT accounting (§4) and the consistency invariant M4−M4s = Σ_user + Σ_disc.
 */

import { describe, it, expect } from 'vitest'
import {
  cleanDecisive,
  computeMetrics,
  deriveStateSequence,
  type MetricsInput,
  type PerceivedEvent,
  type PerceivedAction,
} from '../../src/lib/perceived'

const ev = (type: string, content: string, atMs: number, metadata: Record<string, unknown> = {}): PerceivedEvent => ({
  type,
  content,
  metadata,
  arrivalAt: atMs,
})
const submit = (at: number): PerceivedAction => ({ kind: 'submit', at })
const cancel = (at: number): PerceivedAction => ({ kind: 'cancel', at })
const timeout = (at: number): PerceivedAction => ({ kind: 'timeout', at })
const reply = (at: number): PerceivedAction => ({ kind: 'submit_user_reply', at })

function compute(
  opts: {
    tSubmit: number
    sessionAt?: number | null
    events: PerceivedEvent[]
    actions?: PerceivedAction[]
    userIntervals?: { start: number; end: number }[]
    discIntervals?: { start: number; end: number; terminated?: boolean }[]
    lastLiveAt?: number
  },
) {
  const { decisive } = cleanDecisive(opts.events)
  const derived = deriveStateSequence({ tSubmit: opts.tSubmit, decisive, actions: opts.actions ?? [] })
  const input: MetricsInput = {
    tSubmit: opts.tSubmit,
    sessionArrivalAt: opts.sessionAt ?? null,
    decisive,
    derived,
    userIntervals: opts.userIntervals ?? [],
    discIntervals: opts.discIntervals ?? [],
    lastLiveAt: opts.lastLiveAt,
    cancelAt: (opts.actions ?? []).find((a) => a.kind === 'cancel')?.at,
  }
  return computeMetrics(input)
}

const close = (a: number, b: number, eps = 0.05) => expect(Math.abs(a - b)).toBeLessThanOrEqual(eps)

describe('T3 §12 metric examples', () => {
  it('T1 正常 chat: M2=M3=8.269, M4s=10, M5=8.269, S=8.269/G=1.731', () => {
    const r = compute({
      tSubmit: 0,
      sessionAt: 13,
      events: [
        ev('session', '', 13),
        ev('content', 'A', 8269),
        ev('content', 'B', 9990),
        ev('result', '', 9950),
        ev('done', '', 10000),
      ],
      actions: [submit(0)],
    })
    close(r.metrics.M1!, 0.013)
    close(r.metrics.M2!, 8.269)
    close(r.metrics.M3!, 8.269)
    close(r.metrics.M4!, 10)
    close(r.metrics.M4s!, 10)
    close(r.metrics.M5!, 8.269)
    close(r.metrics.time_in_S!, 8.269)
    close(r.metrics.time_in_G!, 1.731)
    close(r.metrics.M8!, 10)
    expect(r.outcome).toBe('ok')
  })

  it('T2 检索: M2=1.1, M3=6.9, M4s=7.8, M5=4.6, S=1.1/R=5.8/G=0.9', () => {
    const r = compute({
      tSubmit: 0,
      sessionAt: 13,
      events: [
        ev('session', '', 13),
        ev('tool_call', 'rag', 1100),
        ev('tool_result', '', 2300),
        ev('content', 'x', 6900),
        ev('done', '', 7800),
      ],
      actions: [submit(0)],
    })
    close(r.metrics.M2!, 1.1)
    close(r.metrics.M3!, 6.9)
    close(r.metrics.M4s!, 7.8)
    close(r.metrics.M5!, 4.6)
    close(r.metrics.time_in_S!, 1.1)
    close(r.metrics.time_in_R!, 5.8)
    close(r.metrics.time_in_G!, 0.9)
    expect(r.firstDecisiveKind).toBe('tool_call')
  })

  it('T3 多步 Agent: M4s=9, M5=3, S=1/R=4/G=2/T=2', () => {
    const r = compute({
      tSubmit: 0,
      sessionAt: 10,
      events: [
        ev('tool_call', 'rag', 1000),
        ev('tool_result', '', 2000),
        ev('content', 'a', 5000),
        ev('tool_call', 'web_fetch', 6000),
        ev('tool_result', '', 7000),
        ev('content', 'b', 8000),
        ev('done', '', 9000),
      ],
      actions: [submit(0)],
    })
    close(r.metrics.M4s!, 9)
    close(r.metrics.M5!, 3)
    close(r.metrics.time_in_S!, 1)
    close(r.metrics.time_in_R!, 4)
    close(r.metrics.time_in_T!, 2)
    close(r.metrics.time_in_G!, 2)
  })

  it('T4 WAIT_FOR_INPUT: PIN 用户思考剔除 M4=10→M4s=4.5, M6p=5.5, M5=2', () => {
    const r = compute({
      tSubmit: 0,
      sessionAt: 10,
      events: [
        ev('content', 'c', 2000),
        ev('wait_for_input', '', 3000),
        ev('content', 'c2', 9000),
        ev('done', '', 10000),
      ],
      actions: [submit(0), reply(8500)],
      userIntervals: [{ start: 3000, end: 8500 }],
    })
    close(r.metrics.M4!, 10)
    close(r.metrics.M4s!, 4.5)
    close(r.metrics.time_in_PIN!, 5.5)
    close(r.metrics.M5!, 2)
    close(r.userWaitMs, 5500)
  })

  it('T5 重试静默: 全部归 S, M4s=26, S=25/G=1（无假进度）', () => {
    const r = compute({
      tSubmit: 0,
      sessionAt: 10,
      events: [
        ev('content', 'x', 25000),
        ev('done', '', 26000),
      ],
      actions: [submit(0)],
    })
    close(r.metrics.M4s!, 26)
    close(r.metrics.M5!, 25)
    close(r.metrics.time_in_S!, 25)
    close(r.metrics.time_in_G!, 1)
  })

  it('T6 断线恢复: M4=7, Σ_disc=2 → M4s=5, M7b=2, M5=2', () => {
    const r = compute({
      tSubmit: 0,
      sessionAt: 10,
      events: [
        ev('content', 'c', 2000),
        ev('done', '', 7000),
      ],
      actions: [submit(0)],
      discIntervals: [{ start: 4000, end: 6000 }],
      lastLiveAt: 2000,
    })
    close(r.metrics.M4!, 7)
    close(r.metrics.M4s!, 5)
    close(r.metrics.M7b!, 2)
    close(r.metrics.M5!, 2)
    close(r.discMs, 2000)
  })

  it('T7 取消: M8-c=4, M5=3, G=1', () => {
    const r = compute({
      tSubmit: 0,
      sessionAt: 10,
      events: [
        ev('content', 'c', 3000),
        ev('error', 'Turn cancelled', 4000, { status: 'cancelled' }),
      ],
      actions: [submit(0), cancel(4000)],
    })
    close(r.metrics.M8!, 4)
    close(r.metrics.M5!, 3)
    close(r.metrics.time_in_G!, 1)
    expect(r.outcome).toBe('ca')
  })

  it('T8 超时: M2/M3/M5 undef → invalid(missing_decisive), M8=180', () => {
    const r = compute({
      tSubmit: 0,
      sessionAt: 10,
      events: [ev('session', '', 10)],
      actions: [submit(0), timeout(180000)],
    })
    expect(r.metrics.M2).toBeUndefined()
    expect(r.metrics.M3).toBeUndefined()
    expect(r.metrics.M5).toBeUndefined()
    close(r.metrics.M8!, 180)
    expect(r.invalid).toBe('missing_decisive')
    expect(r.outcome).toBe('to')
  })

  it('T9 竞态 done vs cancel 同刻: done 先处理 → OK, M8=4', () => {
    const r = compute({
      tSubmit: 0,
      sessionAt: 10,
      events: [
        ev('content', 'c', 3000),
        ev('done', '', 4000),
      ],
      actions: [submit(0), cancel(4000)],
    })
    expect(r.outcome).toBe('ok')
    close(r.metrics.M8!, 4)
  })

  it('T12 thinking 不进 G: M2=M3=7, M5=7, S=7/G=1', () => {
    const r = compute({
      tSubmit: 0,
      sessionAt: 10,
      events: [
        ev('session', '', 10),
        ev('thinking', '思考中', 5000),
        ev('content', 'x', 7000),
        ev('done', '', 8000),
      ],
      actions: [submit(0)],
    })
    close(r.metrics.M2!, 7)
    close(r.metrics.M3!, 7)
    close(r.metrics.M5!, 7)
    close(r.metrics.time_in_S!, 7)
    close(r.metrics.time_in_G!, 1)
  })
})

describe('SYS_WAIT consistency (T3 §4)', () => {
  it('M4 − M4s == Σ_user + Σ_disc', () => {
    const r = compute({
      tSubmit: 0,
      sessionAt: 10,
      events: [
        ev('content', 'c', 2000),
        ev('wait_for_input', '', 3000),
        ev('content', 'c2', 9000),
        ev('done', '', 10000),
      ],
      actions: [submit(0), reply(8500)],
      userIntervals: [{ start: 3000, end: 8500 }],
      discIntervals: [{ start: 7000, end: 8000 }],
    })
    const m4 = r.metrics.M4! * 1000
    const m4s = r.metrics.M4s! * 1000
    expect(Math.abs(m4 - m4s - r.userWaitMs - r.discMs)).toBeLessThanOrEqual(2)
  })
})
