/**
 * Perceived Latency — scenario bucketing, percentiles & baseline structure (T6 / W-I3).
 *
 * Implements T3 §5 (scenario buckets), §6 (dimension five-tuple), §7 (P50/P95/P99 +
 * min_n + invalid distribution) and §9 (baseline JSON schema, versioned) as pure
 * functions.
 *
 * No real-data thresholds are applied here — absolute values stay CALIBRATION_PENDING
 * (T3 §10 / T4 §3.3); only structural rules are implemented.
 */

import {
  type BaselineBucket,
  type MetricKey,
  type PerceivedBaseline,
  type SampleDimensions,
  type TurnSample,
} from './types'
import { percentile } from './metrics'

/** Minimum valid samples per bucket/metric before it becomes observable (T3 §7). */
export const DEFAULT_MIN_N = 30

/** Dimension keys recorded in the baseline (T3 §9). */
export const BASELINE_DIMENSIONS = ['capability', 'tool_profile', 'outcome', 'transport', 'warmth', 'has_pin']

const METRIC_KEYS: MetricKey[] = [
  'M1', 'M2', 'M3', 'M4', 'M4s', 'M5',
  'time_in_S', 'time_in_R', 'time_in_T', 'time_in_G', 'time_in_PIN',
  'M7a', 'M7b', 'M7c', 'M8', 'M8t2',
]

/** Serialize a sample's dimension tuple for bucketing (JSON-stable key). */
export function sceneKey(dims: SampleDimensions): string {
  return JSON.stringify([dims.capability, dims.tool_profile, dims.outcome, dims.transport, dims.warmth, dims.has_pin])
}

/** Return true when a sample is valid for the percentiles (T3 §7). */
export function isSampleValid(sample: TurnSample): boolean {
  return sample.invalid === null
}

export interface AggregatedBucket {
  scene: SampleDimensions
  metrics: Record<string, { P50: number; P95: number; P99: number; avg: number; max: number; n: number }>
  samples_insufficient: boolean
  invalid_count: number
  invalid_reasons: Record<string, number>
}

/**
 * Aggregate samples into buckets (one per dimension tuple), computing percentiles
 * per metric on valid samples only. Invalid samples are counted separately and
 * never enter the percentiles (T3 §7).
 */
export function aggregateSamples(samples: TurnSample[], minN = DEFAULT_MIN_N): AggregatedBucket[] {
  const buckets = new Map<string, { dims: SampleDimensions; valid: TurnSample[]; invalidCount: number; reasons: Record<string, number> }>()

  for (const sample of samples) {
    const key = sceneKey(sample.dimensions)
    let bucket = buckets.get(key)
    if (!bucket) {
      bucket = { dims: sample.dimensions, valid: [], invalidCount: 0, reasons: {} }
      buckets.set(key, bucket)
    }
    if (isSampleValid(sample)) bucket.valid.push(sample)
    else {
      bucket.invalidCount += 1
      const reason = sample.invalid ?? 'unknown'
      bucket.reasons[reason] = (bucket.reasons[reason] ?? 0) + 1
    }
  }

  const out: AggregatedBucket[] = []
  for (const [, bucket] of buckets) {
    const metrics: AggregatedBucket['metrics'] = {}
    for (const key of METRIC_KEYS) {
      const values: number[] = []
      for (const sample of bucket.valid) {
        const v = sample.metrics[key]
        if (typeof v === 'number' && Number.isFinite(v)) values.push(v)
      }
      if (!values.length) continue
      const sorted = [...values].sort((a, b) => a - b)
      metrics[key] = {
        P50: percentile(sorted, 0.5),
        P95: percentile(sorted, 0.95),
        P99: percentile(sorted, 0.99),
        avg: values.reduce((a, b) => a + b, 0) / values.length,
        max: sorted[sorted.length - 1],
        n: values.length,
      }
    }
    const validN = bucket.valid.length
    out.push({
      scene: bucket.dims,
      metrics,
      samples_insufficient: validN < minN,
      invalid_count: bucket.invalidCount,
      invalid_reasons: bucket.reasons,
    })
  }
  return out
}

/** Build the versioned baseline JSON (T3 §9). */
export function buildBaseline(
  samples: TurnSample[],
  opts: { appVersion: string; generatedAt?: string },
): PerceivedBaseline {
  const buckets: BaselineBucket[] = aggregateSamples(samples).map((b) => ({
    scene: b.scene,
    metrics: b.metrics as BaselineBucket['metrics'],
    samples_insufficient: b.samples_insufficient,
  }))
  return {
    schema_version: '1.0',
    frozen_against: ['t2-perceived-waiting-state-model-v1', 't3-perceived-latency-metrics-v1', 't4-waiting-experience-design-spec-v1'],
    generated_at: opts.generatedAt ?? new Date().toISOString(),
    app_version: opts.appVersion,
    dimensions: [...BASELINE_DIMENSIONS],
    buckets,
    thresholds: {
      M3: { P95_warn_pct: 'CALIBRATION_PENDING', P95_fail_pct: 'CALIBRATION_PENDING', hard_max: 'CALIBRATION_PENDING' },
      M4s: { P95_warn_pct: 'CALIBRATION_PENDING', P95_fail_pct: 'CALIBRATION_PENDING' },
      M5: { P95_warn_pct: 'CALIBRATION_PENDING', P95_fail_pct: 'CALIBRATION_PENDING' },
      M7b: { P95_warn_pct: 'CALIBRATION_PENDING', P95_fail_pct: 'CALIBRATION_PENDING' },
    },
  }
}
