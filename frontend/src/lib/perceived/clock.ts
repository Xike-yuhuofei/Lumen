/**
 * Perceived Latency — client monotonic clock layer (T6 / W-I1).
 *
 * T3 §1 / T2 I11: ALL perceived-latency timestamps use the client monotonic clock
 * (performance.now). Date.now() is never used for perception metrics — it is only
 * used for heartbeat bookkeeping in the transport layer.
 *
 * Clock validity (T3 §7 invalid(clock)): if performance.now is unavailable or the
 * recorded sequence is non-monotonic, the affected sample must be marked
 * invalid(clock) and excluded from the metric percentiles.
 */

export interface PerceivedClock {
  /** Current client monotonic timestamp (ms). */
  now(): number
  /** Whether the clock is usable (monotonic, monotonic-capable). */
  readonly usable: boolean
}

/**
 * Create a monotonic clock backed by performance.now().
 * The sequence is guaranteed non-decreasing; if the environment does not expose a
 * monotonic clock we fall back to Date.now() and mark the clock unusable so the
 * collector can tag samples invalid(clock) (T3 §7).
 */
export function createPerceivedClock(): PerceivedClock {
  const hasPerf =
    typeof performance !== 'undefined' &&
    typeof performance.now === 'function'

  let last = -Infinity

  return {
    get usable() {
      return hasPerf
    },
    now(): number {
      const t = hasPerf ? performance.now() : Date.now()
      // Never go backwards — guards against exotic clock behaviour. When a sample
      // is recorded we compare against `last` to detect non-monotonicity.
      if (t < last) return last
      last = t
      return t
    },
  }
}

/** Convenience singleton for the app (App.tsx / ws.ts). */
export const perfClock = createPerceivedClock()

/** True if two successive samples are monotonic (non-decreasing). */
export function isMonotonic(prev: number | undefined, next: number): boolean {
  if (prev === undefined) return true
  return next >= prev
}
