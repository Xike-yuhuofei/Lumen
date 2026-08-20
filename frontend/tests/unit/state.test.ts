/**
 * T6 / W-I2 — T2 P-state machine determinism tests.
 *
 * Covers the frozen T2 §12 T1–T12 representative trajectories plus the
 * seq-cleaning & terminal-latch rules (T2 I1/I6/I7) and replay determinism (I9).
 */

import { describe, it, expect } from 'vitest'
import {
  cleanDecisive,
  deriveStateSequence,
  replayTrace,
  toolProfileFromEvents,
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

function derive(tSubmit: number, events: PerceivedEvent[], actions: PerceivedAction[] = []) {
  const { decisive } = cleanDecisive(events)
  return deriveStateSequence({ tSubmit, decisive, actions })
}

describe('cleanDecisive (T3 §11 CLEAN)', () => {
  it('drops non-decisive events and empty content', () => {
    const events = [
      ev('session', '', 10),
      ev('thinking', 'x', 20),
      ev('content', '', 30),
      ev('content', 'hi', 40),
      ev('done', '', 50),
    ]
    const { decisive } = cleanDecisive(events)
    expect(decisive.map((e) => e.type)).toEqual(['content', 'done'])
  })

  it('seq dedup: drops stale seq ≤ lastSeq (I6)', () => {
    const events = [
      { ...ev('content', 'a', 10), seq: 5 },
      { ...ev('content', 'b', 20), seq: 3 },
      { ...ev('content', 'c', 30), seq: 6 },
    ]
    const { decisive } = cleanDecisive(events)
    expect(decisive.map((e) => e.content)).toEqual(['a', 'c'])
  })

  it('terminal latch: events after the first terminal are dropped (I1)', () => {
    const events = [
      ev('content', 'a', 10),
      ev('done', '', 20, { status: 'completed' }),
      ev('error', 'late', 30),
      ev('content', 'late2', 40),
    ]
    const { decisive, terminal } = cleanDecisive(events)
    expect(decisive.map((e) => e.type)).toEqual(['content', 'done'])
    expect(terminal?.type).toBe('done')
  })
})

describe('T2 §12 trajectories', () => {
  it('T1 正常生成 → S → G → OK', () => {
    const d = derive(0, [
      ev('session', '', 13),
      ev('content', 'A', 8269),
      ev('content', 'B', 9990),
      ev('result', '', 9950),
      ev('done', '', 10000, { status: 'completed' }),
    ], [submit(0)])
    expect(d.states).toEqual(['S', 'G', 'OK'])
    expect(d.terminal).toBe('OK')
  })

  it('T2 检索 → S → R → G → OK', () => {
    const d = derive(0, [
      ev('session', '', 13),
      ev('tool_call', 'rag', 1100, { args: {} }),
      ev('tool_result', '', 2300),
      ev('content', 'x', 6900),
      ev('done', '', 7800),
    ], [submit(0)])
    expect(d.states).toEqual(['S', 'R', 'G', 'OK'])
  })

  it('T3 多步 Agent → S → R → G → T → G → OK', () => {
    const d = derive(0, [
      ev('tool_call', 'rag', 1000, { args: {} }),
      ev('tool_result', '', 2000),
      ev('content', 'a', 5000),
      ev('tool_call', 'web_fetch', 6000, { args: {} }),
      ev('tool_result', '', 7000),
      ev('content', 'b', 8000),
      ev('done', '', 9000),
    ], [submit(0)])
    expect(d.states).toEqual(['S', 'R', 'G', 'T', 'G', 'OK'])
  })

  it('T4 WAIT_FOR_INPUT → S → G → PIN → S → G → OK', () => {
    const d = derive(0, [
      ev('content', 'c', 2000),
      ev('wait_for_input', '', 3000),
      ev('content', 'c2', 9000),
      ev('done', '', 10000),
    ], [submit(0), reply(8500)])
    expect(d.states).toEqual(['S', 'G', 'PIN', 'S', 'G', 'OK'])
  })

  it('T5 重试静默（无事件）→ S 原地 → G → OK（无假进度）', () => {
    const d = derive(0, [
      ev('session', '', 10),
      ev('content', 'x', 25000),
      ev('done', '', 26000),
    ], [submit(0)])
    expect(d.states).toEqual(['S', 'G', 'OK'])
  })

  it('T7 取消 → S → G → CA', () => {
    const d = derive(0, [
      ev('content', 'c', 3000),
      ev('error', 'Turn cancelled', 4000, { status: 'cancelled' }),
      ev('done', '', 4000, { status: 'cancelled' }),
    ], [submit(0), cancel(4000)])
    expect(d.states).toEqual(['S', 'G', 'CA'])
    expect(d.terminal).toBe('CA')
  })

  it('T8 超时 → S → TO（无决定性 → 由 idle timer 终结）', () => {
    const d = derive(0, [
      ev('session', '', 10),
    ], [submit(0), timeout(180000)])
    expect(d.states).toEqual(['S', 'TO'])
    expect(d.terminal).toBe('TO')
    expect(d.terminalAt).toBe(180000)
  })

  it('T9 竞态 done vs cancel：同刻 done 先处理 → OK（先到者胜 I7）', () => {
    const d = derive(0, [
      ev('content', 'c', 3000),
      ev('done', '', 4000, { status: 'completed' }),
    ], [submit(0), cancel(4000)])
    expect(d.states).toEqual(['S', 'G', 'OK'])
    expect(d.terminal).toBe('OK')
  })

  it('T10 done 迟到 vs TO：timer 先触发 → TO（I1 闩锁）', () => {
    const d = derive(0, [
      ev('session', '', 10),
      ev('done', '', 181000),
    ], [submit(0), timeout(180000)])
    expect(d.states).toEqual(['S', 'TO'])
    expect(d.terminal).toBe('TO')
  })

  it('T12 thinking 不产生 G → S → G → OK', () => {
    const d = derive(0, [
      ev('session', '', 10),
      ev('thinking', '思考中', 5000),
      ev('content', 'x', 7000),
      ev('done', '', 8000),
    ], [submit(0)])
    expect(d.states).toEqual(['S', 'G', 'OK'])
  })
})

describe('turn isolation & replay (T2 I9 / §2.4)', () => {
  it('T11 断线后新 submit：旧 Turn CA、新 Turn OK，活动态不重叠', () => {
    // Old turn: user gives up (cancelled) then a new turn starts.
    const oldTurn = derive(0, [
      ev('content', 'c', 3000),
      ev('done', '', 4000, { status: 'cancelled' }),
    ], [submit(0), cancel(4000)])
    expect(oldTurn.states).toEqual(['S', 'G', 'CA'])

    const newTurn = derive(5000, [
      ev('session', '', 5010),
      ev('content', 'x', 8000),
      ev('done', '', 9000),
    ], [submit(5000)])
    expect(newTurn.states).toEqual(['S', 'G', 'OK'])
  })

  it('replay 与实时推导得到一致状态序列（I9）', () => {
    const tSubmit = 0
    const events = [
      ev('tool_call', 'rag', 1000),
      ev('tool_result', '', 2000),
      ev('content', 'a', 5000),
      ev('tool_call', 'web_fetch', 6000),
      ev('tool_result', '', 7000),
      ev('content', 'b', 8000),
      ev('done', '', 9000),
    ]
    const actions = [submit(0)]
    const realtime = derive(tSubmit, events, actions)
    const replay = replayTrace({ tSubmit, events, actions })
    expect(replay.states).toEqual(realtime.states)
    expect(replay.terminal).toEqual(realtime.terminal)
    expect(replay.terminalAt).toEqual(realtime.terminalAt)
  })
})

describe('tool profile inference (T3 §6)', () => {
  it('no_tool / retrieval_only / tool_only / mixed', () => {
    expect(toolProfileFromEvents([ev('content', 'x', 1)])).toBe('no_tool')
    expect(toolProfileFromEvents([ev('tool_call', 'rag', 1)])).toBe('retrieval_only')
    expect(toolProfileFromEvents([ev('tool_call', 'web_search', 1)])).toBe('tool_only')
    expect(toolProfileFromEvents([ev('tool_call', 'rag', 1), ev('tool_call', 'web_search', 2)])).toBe('mixed')
  })
})
