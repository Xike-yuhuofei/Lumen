/**
 * Perceived Latency — sample persistence (T6 / W-I3 data entry for T7).
 *
 * Per-turn T3 §9 samples are appended to a localStorage JSONL buffer (capped),
 * giving T7 the raw data entry without any backend change. A debug hook exposes
 * dump/clear so the buffer can be exported for calibration.
 */

import { buildBaseline, aggregateSamples } from './buckets'
import type { TurnSample } from './types'

const LS_KEY = 'lumen:perceived-samples-v1'
const MAX_SAMPLES = 2000

export function readSamples(): TurnSample[] {
  try {
    const raw = localStorage.getItem(LS_KEY)
    if (!raw) return []
    const lines = raw.split('\n').filter((l) => l.trim())
    return lines
      .map((l) => {
        try {
          return JSON.parse(l) as TurnSample
        } catch {
          return null
        }
      })
      .filter((s): s is TurnSample => s !== null)
  } catch {
    return []
  }
}

export function appendSample(sample: TurnSample): void {
  try {
    const samples = readSamples()
    samples.push(sample)
    const trimmed = samples.slice(-MAX_SAMPLES)
    localStorage.setItem(LS_KEY, trimmed.map((s) => JSON.stringify(s)).join('\n'))
  } catch {
    // Persistence is best-effort; never affect the main path.
  }
}

export function clearSamples(): void {
  try {
    localStorage.removeItem(LS_KEY)
  } catch {
    /* ignore */
  }
}

/** Build the versioned baseline from the persisted samples (T3 §9). */
export function buildPersistedBaseline(appVersion: string) {
  return buildBaseline(readSamples(), { appVersion })
}

export function summaryStats() {
  const samples = readSamples()
  return {
    total: samples.length,
    valid: samples.filter((s) => s.invalid === null).length,
    invalid: samples.filter((s) => s.invalid !== null).length,
    invalid_reasons: samples.reduce<Record<string, number>>((acc, s) => {
      const r = s.invalid ?? 'valid'
      acc[r] = (acc[r] ?? 0) + 1
      return acc
    }, {}),
    buckets: aggregateSamples(samples).map((b) => ({
      scene: b.scene,
      n: Object.values(b.metrics)[0]?.n ?? 0,
      samples_insufficient: b.samples_insufficient,
      invalid_count: b.invalid_count,
    })),
  }
}

/** Debug hook (browser console): __perceivedLatency.dump() / .clear() / .stats(). */
export function installPerceivedDebugHook(appVersion: string): void {
  const g = globalThis as unknown as { __perceivedLatency?: unknown }
  if (g.__perceivedLatency) return
  g.__perceivedLatency = {
    dump: () => buildPersistedBaseline(appVersion),
    stats: () => summaryStats(),
    clear: () => clearSamples(),
  }
}
