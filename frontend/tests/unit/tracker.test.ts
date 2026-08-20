/**
 * T6 — tracker end-to-end + bucket aggregation + baseline structure tests (W-I3).
 */

import { describe, it, expect } from 'vitest'
import {
  PerceivedTurnTracker,
  aggregateSamples,
  buildBaseline,
  percentile,
  type TurnSample,
} from '../../src/lib/perceived'

function makeTracker(tSubmit = 0) {
  return new PerceivedTurnTracker({
    sessionId: 's1',
    capability: 'chat',
    appVersion: '0.1.0-test',
    warmth: 'cold_first',
    tSubmit,
  })
}

describe('PerceivedTurnTracker (W-I1..W-I5 integration)', () => {
  it('正常 chat 回合产生有效 sample 与静态审查 PASS', () => {
    const t = makeTracker()
    t.recordFirstFeedback(0)
    t.recordProcessing(0, true)
    t.onEvent({ type: 'session', content: '', metadata: {}, arrivalAt: 13 })
    t.onEvent({ type: 'content', content: 'hi', metadata: {}, arrivalAt: 8269 })
    t.recordContentRendered(8269)
    t.recordProcessing(8269, false)
    t.onEvent({ type: 'done', content: '', metadata: { status: 'completed' }, arrivalAt: 10000 })

    const sample = t.finalize()
    expect(sample).not.toBeNull()
    expect(sample!.dimensions.outcome).toBe('ok')
    expect(sample!.dimensions.tool_profile).toBe('no_tool')
    expect(sample!.dimensions.transport).toBe('clean')
    expect(sample!.invalid).toBeNull()
    expect(sample!.review?.passed).toBe(true)
    expect(sample!.metrics.M3).toBeCloseTo(8.269, 2)
  })

  it('PIN 回合：wait_for_input 显式消费 + t_wi/t_ur 计入 M6p', () => {
    const t = makeTracker()
    t.onEvent({ type: 'content', content: 'c', metadata: {}, arrivalAt: 2000 })
    t.onEvent({ type: 'wait_for_input', content: '', metadata: {}, arrivalAt: 3000 })
    t.onAction({ kind: 'submit_user_reply', at: 8500 })
    t.onEvent({ type: 'content', content: 'c2', metadata: {}, arrivalAt: 9000 })
    t.onEvent({ type: 'done', content: '', metadata: {}, arrivalAt: 10000 })

    const sample = t.finalize()
    expect(sample).not.toBeNull()
    expect(sample!.dimensions.has_pin).toBe(true)
    expect(sample!.metrics.time_in_PIN).toBeCloseTo(5.5, 2)
    expect(sample!.user_wait_s).toBeCloseTo(5.5, 2)
  })

  it('断线恢复：transport 事实被消费并计入 M7/Σ_disc', () => {
    const t = makeTracker()
    t.onEvent({ type: 'content', content: 'c', metadata: {}, arrivalAt: 2000 })
    t.onTransport({ status: 'reconnecting', at: 4000 })
    t.onEvent({ type: 'content', content: 'c2', metadata: {}, arrivalAt: 6000 }) // recovery
    t.onEvent({ type: 'done', content: '', metadata: {}, arrivalAt: 7000 })

    const sample = t.finalize()
    expect(sample).not.toBeNull()
    expect(sample!.dimensions.transport).toBe('disconnected_recovered')
    expect(sample!.metrics.M7b).toBeCloseTo(2, 2)
    expect(sample!.disconnect_s).toBeCloseTo(2, 2)
  })

  it('取消：cancel 动作 → CA sample', () => {
    const t = makeTracker()
    t.onEvent({ type: 'content', content: 'c', metadata: {}, arrivalAt: 3000 })
    t.onAction({ kind: 'cancel', at: 4000 })
    const sample = t.finalize()
    expect(sample).not.toBeNull()
    expect(sample!.dimensions.outcome).toBe('ca')
  })

  it('无终态（被丢弃）→ finalize 返回 null', () => {
    const t = makeTracker()
    t.onEvent({ type: 'content', content: 'partial', metadata: {}, arrivalAt: 2000 })
    expect(t.finalize()).toBeNull()
  })
})

describe('bucket aggregation & baseline (T3 §5/§7/§9)', () => {
  const sample = (over: Partial<TurnSample>): TurnSample => ({
    schema_version: '1.0',
    dimensions: { capability: 'chat', tool_profile: 'no_tool', outcome: 'ok', transport: 'clean', warmth: 'warm', has_pin: false },
    metrics: { M3: 2, M4s: 3, M5: 1 },
    invalid: null,
    generated_at: new Date().toISOString(),
    app_version: '0.1.0',
    user_wait_s: 0,
    disconnect_s: 0,
    ...over,
  })

  it('percentile 线性分位（P50/P95/P99）', () => {
    const sorted = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    expect(percentile(sorted, 0.5)).toBeCloseTo(5.5, 6)
    expect(percentile(sorted, 0.95)).toBeCloseTo(9.55, 6)
    expect(percentile(sorted, 0.99)).toBeCloseTo(9.91, 6)
  })

  it('aggregateSamples 只聚合有效样本，invalid 单独计数', () => {
    const samples = [
      sample({ metrics: { M3: 2, M4s: 3 } }),
      sample({ metrics: { M3: 4, M4s: 5 } }),
      sample({ metrics: { M3: 6, M4s: 7 } }),
      sample({ invalid: 'missing_decisive' }),
    ]
    const buckets = aggregateSamples(samples)
    expect(buckets.length).toBe(1)
    expect(buckets[0].invalid_count).toBe(1)
    expect(buckets[0].metrics.M3.n).toBe(3)
    expect(buckets[0].metrics.M3.P50).toBeCloseTo(4, 6)
    expect(buckets[0].samples_insufficient).toBe(true) // n=3 < min_n=30
  })

  it('buildBaseline 输出版本化 schema 与 CALIBRATION_PENDING 阈值', () => {
    const base = buildBaseline([sample({})], { appVersion: '0.1.0-test' })
    expect(base.schema_version).toBe('1.0')
    expect(base.frozen_against).toContain('t2-perceived-waiting-state-model-v1')
    expect(base.dimensions).toContain('capability')
    expect(base.thresholds.M3.P95_warn_pct).toBe('CALIBRATION_PENDING')
    expect(base.buckets[0].samples_insufficient).toBe(true)
  })
})
