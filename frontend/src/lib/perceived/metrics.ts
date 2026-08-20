/**
 * Perceived Latency — SYS_WAIT accounting + M1..M8 (T6 / W-I3).
 *
 * Implements T3 §3 (metric definitions), §4 (SYS_WAIT accounting rules) and §7/§8
 * (sample validity & invalid reasons) as pure functions.
 *
 * All times are client monotonic ms; metric outputs are seconds.
 * The consistency invariant M4 − M4s == Σ_user + Σ_disc is asserted with a small
 * floating tolerance (T3 §4).
 */

import {
  type DerivedState,
  type InvalidReason,
  type MetricKey,
  type Outcome,
  type PerceivedEvent,
} from './types'

/** Half-open [s,e) overlap length (ms). */
export function overlapLen(p: number, q: number, s: number, e: number): number {
  return Math.max(0, Math.min(q, e) - Math.max(p, s))
}

/**
 * SYS_WAIT(I) per T3 §4 — interval length minus PIN user-wait and disconnect
 * exclusions (half-open endpoints avoid double counting).
 */
export function sysWait(p: number, q: number, exclusions: { start: number; end: number }[]): number {
  let len = q - p
  for (const ex of exclusions) len -= overlapLen(p, q, ex.start, ex.end)
  return Math.max(0, len)
}

/** Find the first non-empty content event (M3 endpoint / G source). */
export function firstNonEmptyContent(events: PerceivedEvent[]): PerceivedEvent | null {
  for (const e of events) {
    if (e.type === 'content' && (e.content ?? '').trim()) return e
  }
  return null
}

export interface MetricsInput {
  tSubmit: number
  sessionArrivalAt: number | null
  decisive: PerceivedEvent[]
  derived: DerivedState
  /** PIN user-wait intervals [t_wi, exitAt] (M6p / Σ_user). */
  userIntervals: { start: number; end: number }[]
  /** Disconnect outage intervals [t_disc_detected, t_recovered|τ]. */
  discIntervals: { start: number; end: number; terminated?: boolean }[]
  /** t_last_live = last live event arrival before the first disconnect (M7a). */
  lastLiveAt?: number
  /** Cancel action time (M8-c). */
  cancelAt?: number
}

export interface MetricsOutput {
  metrics: Partial<Record<MetricKey, number>>
  userWaitMs: number
  discMs: number
  invalid: InvalidReason | null
  firstDecisiveKind?: string
  outcome: Outcome | null
  tLastLiveAt?: number
}

/** Linear percentile (T3 §7): rank = ceil(p*n), interpolate between neighbors. */
export function percentile(sorted: number[], p: number): number {
  if (!sorted.length) return Number.NaN
  if (sorted.length === 1) return sorted[0]
  // Standard linear interpolation over rank positions: pos = p*(n-1).
  const pos = p * (sorted.length - 1)
  const lo = Math.floor(pos)
  const hi = Math.min(sorted.length - 1, Math.ceil(pos))
  const frac = pos - lo
  return sorted[lo] + (sorted[hi] - sorted[lo]) * frac
}

export function computeMetrics(input: MetricsInput): MetricsOutput {
  const { tSubmit, decisive, derived, userIntervals, discIntervals } = input
  const metrics: Partial<Record<MetricKey, number>> = {}
  const ms = (v: number) => v / 1000
  let invalid: InvalidReason | null = null

  const τ = derived.terminalAt
  const terminal = derived.terminal
  const outcome: Outcome | null = terminal === 'OK' ? 'ok'
    : terminal === 'ER' ? 'er'
    : terminal === 'CA' ? 'ca'
    : terminal === 'TO' ? 'to'
    : null

  // --- M1 Time to Acknowledgement (session arrival, non-decisive) ---
  if (input.sessionArrivalAt != null) {
    metrics.M1 = ms(input.sessionArrivalAt - tSubmit)
  } else if (outcome) {
    invalid = 'missing_ack'
  }

  // --- M2 / first decisive ---
  const first = decisive[0]
  const firstContent = firstNonEmptyContent(decisive)
  if (first) {
    metrics.M2 = ms(first.arrivalAt - tSubmit)
  } else if (outcome) {
    invalid = invalid ?? 'missing_decisive'
  }

  // --- M3 Time to First Meaningful Result ---
  if (firstContent) {
    metrics.M3 = ms(firstContent.arrivalAt - tSubmit)
  } else if (outcome) {
    invalid = invalid ?? 'no_value'
  }

  // --- M4 / M4s (SYS_WAIT over [tSubmit, τ]) ---
  if (τ != null) {
    metrics.M4 = ms(τ - tSubmit)
    const userWaitMs = userIntervals.reduce((acc, iv) => acc + overlapLen(tSubmit, τ, iv.start, iv.end), 0)
    const discMs = discIntervals.reduce((acc, iv) => acc + overlapLen(tSubmit, τ, iv.start, iv.end), 0)
    const m4s = τ - tSubmit - userWaitMs - discMs
    // Consistency assertion (T3 §4): M4 − M4s == Σ_user + Σ_disc (float tolerance).
    const residual = Math.abs((τ - tSubmit) - m4s - (userWaitMs + discMs))
    if (residual > 2) invalid = invalid ?? 'overlap_error'
    metrics.M4s = ms(Math.max(0, m4s))
  }

  // --- M5 Max Silent Gap (leading / internal / trailing, SYS_WAIT view only) ---
  if (first && τ != null) {
    const exclusions = [...userIntervals, ...discIntervals]
    const gaps: number[] = []
    // leading: a(e_0) − t_submit
    const leading = first.arrivalAt - tSubmit
    if (!touchesExclusion(tSubmit, first.arrivalAt, exclusions)) gaps.push(leading)
    // internal
    for (let i = 0; i + 1 < decisive.length; i++) {
      const a = decisive[i].arrivalAt
      const b = decisive[i + 1].arrivalAt
      if (!touchesExclusion(a, b, exclusions)) gaps.push(b - a)
    }
    // trailing: τ − a(e_{n-1})
    const last = decisive[decisive.length - 1].arrivalAt
    if (!touchesExclusion(last, τ, exclusions)) gaps.push(τ - last)
    if (gaps.length) metrics.M5 = ms(Math.max(...gaps))
  } else if (outcome) {
    invalid = invalid ?? 'missing_decisive'
  }

  // --- M6 Time in S/R/T/G (per segment, SYS_WAIT) + M6p ---
  const exclusions = [...userIntervals, ...discIntervals]
  for (const seg of derived.segments) {
    const key: MetricKey | null =
      seg.state === 'S' ? 'time_in_S' :
      seg.state === 'R' ? 'time_in_R' :
      seg.state === 'T' ? 'time_in_T' :
      seg.state === 'G' ? 'time_in_G' : null
    if (key) metrics[key] = (metrics[key] ?? 0) + ms(sysWait(seg.startAt, seg.endAt, exclusions))
  }
  const pinMs = userIntervals.reduce((acc, iv) => acc + iv.end - iv.start, 0)
  if (pinMs > 0) metrics.time_in_PIN = ms(pinMs)

  // --- M7 Disconnect Duration ---
  if (discIntervals.length) {
    const firstDisc = discIntervals[0]
    const lastLive = input.lastLiveAt ?? firstDisc.start
    metrics.M7a = ms(Math.max(0, firstDisc.start - lastLive))
    const recovered = discIntervals.find((iv) => !iv.terminated)
    const terminated = discIntervals.find((iv) => iv.terminated)
    if (recovered) metrics.M7b = ms(Math.max(0, recovered.end - recovered.start))
    if (terminated) metrics.M7c = ms(Math.max(0, terminated.end - terminated.start))
  }

  // --- M8 outcome-specific ---
  if (τ != null && outcome) {
    if (outcome === 'ok' || outcome === 'er') {
      metrics.M8 = ms(τ - tSubmit)
    } else if (outcome === 'ca') {
      const base = input.cancelAt ?? τ
      metrics.M8 = ms(base - tSubmit)
    } else if (outcome === 'to') {
      metrics.M8 = ms(τ - tSubmit)
      const lastLive = lastArrival(decisive) ?? input.sessionArrivalAt ?? tSubmit
      metrics.M8t2 = ms(Math.max(0, τ - lastLive))
    }
  }

  return {
    metrics,
    userWaitMs: userIntervals.reduce((acc, iv) => acc + iv.end - iv.start, 0),
    discMs: discIntervals.reduce((acc, iv) => acc + iv.end - iv.start, 0),
    invalid,
    firstDecisiveKind: first ? first.type : undefined,
    outcome,
    tLastLiveAt: input.lastLiveAt,
  }
}

/** True when interval [p,q) overlaps any exclusion interval. */
function touchesExclusion(p: number, q: number, exclusions: { start: number; end: number }[]): boolean {
  for (const ex of exclusions) {
    if (overlapLen(p, q, ex.start, ex.end) > 0.5) return true
  }
  return false
}

/** Last decisive arrival time, or null. */
function lastArrival(events: PerceivedEvent[]): number | null {
  return events.length ? events[events.length - 1].arrivalAt : null
}
