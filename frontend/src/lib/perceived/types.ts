/**
 * Perceived Latency — O-plane types & frozen-contract constants (T6 / W-I1..W-I7).
 *
 * This module is the PURE contract layer for the frozen T2/T3/T4 baselines. It has
 * NO imports from the app code so it can be replayed / unit-tested deterministically.
 *
 * Only references frozen semantics — it never modifies them (T1–T5 FROZEN BASELINE).
 */

/** P-plane states (T2 §1.1). */
export type PState = 'idle' | 'S' | 'R' | 'T' | 'G' | 'PIN' | 'OK' | 'ER' | 'CA' | 'TO'

/** Outcome buckets (T3 §5). */
export type Outcome = 'ok' | 'er' | 'ca' | 'to'

/** Tool profile dimension (T3 §6). */
export type ToolProfile = 'no_tool' | 'retrieval_only' | 'tool_only' | 'mixed'

/** Transport dimension (T3 §6). */
export type TransportBucket = 'clean' | 'disconnected_recovered' | 'disconnected_terminated'

/** Warmth dimension (T3 §6 — cold_first = first turn / Kernel cold start, G6/S3). */
export type Warmth = 'cold_first' | 'warm'

/** Decisive event types — the only events that advance P state / feed the metric axis (T2 §5/§11.4). */
export const DECISIVE_TYPES: ReadonlySet<string> = new Set([
  'content',
  'tool_call',
  'sources',
  'tool_result',
  'wait_for_input',
  'done',
  'error',
])

/** Terminal decisive event types (T2 §3). */
export const TERMINAL_DECISIVE_TYPES: ReadonlySet<string> = new Set(['done', 'error'])

/** Retrieval-kind tool names → R (T2 §1.1/§2.2). */
export const RETRIEVAL_TOOLS: ReadonlySet<string> = new Set(['rag', 'kb_files', 'read_source'])

/** A decisive-only, seq-cleaned, arrival-ordered event (O-plane fact, client monotonic clock). */
export interface PerceivedEvent {
  type: string
  content: string
  metadata: Record<string, unknown>
  seq?: number
  /** Client monotonic arrival time (ms). Required for the metric axis (T3 §1). */
  arrivalAt: number
}

/** Client-local actions — O-plane facts (T2 §0 / P1-4). */
export type PerceivedAction =
  | { kind: 'submit'; at: number }
  | { kind: 'submit_user_reply'; at: number }
  | { kind: 'cancel'; at: number }
  | { kind: 'timeout'; at: number }

/** Transport overlay fact (T2 §1.2) — ONLY set by the real transport layer, never by silence. */
export interface TransportFact {
  status: 'connected' | 'reconnecting' | 'disconnected'
  at: number
}

/** A single derived P-state segment (T3 §3.3). Times are client monotonic ms. */
export interface StateSegment {
  state: PState
  startAt: number
  endAt: number
}

/** Derived state-machine output (T2 §9 / T3 §11 DERIVE). */
export interface DerivedState {
  segments: StateSegment[]
  /** Ordered state visits (with repeats) for the trace, e.g. S,G,OK. */
  states: PState[]
  terminal: PState | null
  terminalAt: number | null
}

/** Per-turn dimensions (T3 §6 five-tuple + has_pin). */
export interface SampleDimensions {
  capability: string
  tool_profile: ToolProfile
  outcome: Outcome
  transport: TransportBucket
  warmth: Warmth
  has_pin: boolean
}

/** Invalid sample reasons (T3 §7). */
export type InvalidReason =
  | 'clock'
  | 'missing_ack'
  | 'missing_decisive'
  | 'no_value'
  | 'overlap_error'
  | 'replay_ambiguous'

/** Perceived metric keys (seconds). */
export type MetricKey =
  | 'M1'
  | 'M2'
  | 'M3'
  | 'M4'
  | 'M4s'
  | 'M5'
  | 'time_in_S'
  | 'time_in_R'
  | 'time_in_T'
  | 'time_in_G'
  | 'time_in_PIN'
  | 'M7a'
  | 'M7b'
  | 'M7c'
  | 'M8'
  | 'M8t2'

/** One completed-turn sample (T3 §9 baseline schema — one JSONL line). */
export interface TurnSample {
  schema_version: '1.0'
  session_id?: string
  turn_id?: string
  app_version?: string
  generated_at: string
  dimensions: SampleDimensions
  metrics: Partial<Record<MetricKey, number>>
  first_decisive_kind?: string
  invalid: InvalidReason | null
  /** Number of user (PIN) seconds subtracted; Σ_user. */
  user_wait_s?: number
  /** Number of disconnect seconds subtracted; Σ_disc. */
  disconnect_s?: number
  /** Static review outcome for this turn (T4 §11.1). */
  review?: StaticReviewResult
}

/** T4 §11.1 static-review result (W-I7). */
export interface StaticReviewResult {
  passed: boolean
  checks: {
    same_tick_first_feedback: boolean
    first_feedback_locality: boolean
    state_mapping_consistency: boolean
    event_driven: boolean
    transport_fact_driven: boolean
    prohibited_patterns: boolean
    non_destructive: boolean
    pin_exemption: boolean
    content_state_separation: boolean
  }
  /** Any violated check names (empty when passed). */
  violations: string[]
  /** F1–F10 hits found (empty when none). */
  prohibited_hits: string[]
}

/** Baseline schema (T3 §9). */
export interface PerceivedBaseline {
  schema_version: string
  frozen_against: string[]
  generated_at: string
  app_version: string
  dimensions: string[]
  buckets: BaselineBucket[]
  thresholds: Record<string, Record<string, string>>
}

export interface BaselineBucket {
  scene: SampleDimensions
  metrics: Record<string, { P50: number; P95: number; P99: number; avg: number; max: number; n: number }>
  samples_insufficient: boolean
}
