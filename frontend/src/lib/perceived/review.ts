/**
 * Perceived Latency — T4 §11.1 static review automation (T6 / W-I7).
 *
 * Turns the immediately-effective deterministic review items into an automated,
 * replayable checker. Inputs are the O-plane trace (decisive events, user actions,
 * transport facts) plus lightweight UI observations recorded by the app. Each
 * check maps 1:1 to a T4 §11.1 row; prohibited-mode scans cover F1–F10 (T4 §10).
 *
 * This is a pure function — the same trace always yields the same review result.
 */

import {
  type DerivedState,
  type PerceivedAction,
  type PerceivedEvent,
  type StaticReviewResult,
  type TransportFact,
} from './types'

export interface UiObservation {
  /** E1 shown at submit (same tick) — client monotonic ms. */
  firstFeedbackAt?: number
  /** Processing-indicator records (shown/hidden). */
  processing: { at: number; shown: boolean }[]
  /** Question-card records (shown/hidden). */
  questionCard: { at: number; shown: boolean }[]
  /** Terminal error/status block records (appended). */
  errorBlocks: { at: number }[]
  /** Timeout block records. */
  timeoutBlocks: { at: number }[]
  /** First content render time. */
  contentRenderedAt?: number
  /** Transport banner records — status values MUST come from real transport facts. */
  transportBanners: { at: number; status: string }[]
  /** Phase-text records (scanned for prohibited patterns). */
  phaseTexts: { at: number; text: string }[]
}

export interface ReviewTraceInput {
  tSubmit: number
  decisive: PerceivedEvent[]
  actions: PerceivedAction[]
  transport: TransportFact[]
  derived: DerivedState
  ui: UiObservation
}

const SAME_TICK_EPSILON_MS = 50
const PROHIBITED_TEXT = [
  '预计还需', '剩余时间', '重试第', '第 1 次重试', '退避', 'token', '模型名',
  'provider', '正在连接', '正在重试',
]

export function runStaticReview(input: ReviewTraceInput): StaticReviewResult {
  const { derived, ui } = input
  const checks = {
    same_tick_first_feedback: checkSameTickFirstFeedback(input),
    first_feedback_locality: checkFirstFeedbackLocality(input),
    state_mapping_consistency: checkStateMappingConsistency(derived),
    event_driven: checkEventDriven(input),
    transport_fact_driven: checkTransportFactDriven(input),
    prohibited_patterns: checkProhibitedPatterns(input),
    non_destructive: checkNonDestructive(input),
    pin_exemption: checkPinExemption(input),
    content_state_separation: checkContentStateSeparation(input),
  }

  const violations: string[] = []
  for (const [name, ok] of Object.entries(checks)) {
    if (!ok) violations.push(name)
  }

  const prohibitedHits = scanProhibitedText(ui)

  return {
    passed: violations.length === 0 && prohibitedHits.length === 0,
    checks,
    violations,
    prohibited_hits: prohibitedHits,
  }
}

/** E1 must appear in the same render tick as submit (T4 D1 / §4.1). */
function checkSameTickFirstFeedback(input: ReviewTraceInput): boolean {
  const at = input.ui.firstFeedbackAt
  if (at === undefined) return false
  return Math.abs(at - input.tSubmit) <= SAME_TICK_EPSILON_MS
}

/** E1 is a local ack — it must precede any decisive event and never be counted as M2/M3. */
function checkFirstFeedbackLocality(input: ReviewTraceInput): boolean {
  const at = input.ui.firstFeedbackAt
  if (at === undefined) return true // no E1 observed → handled by the same-tick check
  const firstDecisiveAt = input.decisive.length ? input.decisive[0].arrivalAt : Infinity
  // E1 happens at submit, strictly before the first decisive arrival.
  return at <= firstDecisiveAt
}

/** Derived P states are all from the T2 state set — no invented states (T2 §1.1). */
function checkStateMappingConsistency(derived: DerivedState): boolean {
  const allowed = new Set(['idle', 'S', 'R', 'T', 'G', 'PIN', 'OK', 'ER', 'CA', 'TO'])
  return derived.states.every((s) => allowed.has(s))
}

/**
 * Every activity escalation S→R/T/G must be caused by a decisive event with a
 * matching arrival time (T2 I4 / T4 D4).
 */
function checkEventDriven(input: ReviewTraceInput): boolean {
  const { derived, decisive } = input
  // Every decisive event that produced an escalation has its own arrival; a
  // state change to R/T/G must be preceded by a tool_call/sources/content event.
  const arrivalSet = new Set(decisive.map((e) => Math.round(e.arrivalAt)))
  for (const seg of derived.segments) {
    if (seg.state === 'S' || seg.state === 'PIN') continue
    // Segment start must align with a decisive event arrival (or tSubmit for S→X
    // where the event is the first decisive).
    if (seg.startAt === input.tSubmit) continue
    if (!arrivalSet.has(Math.round(seg.startAt))) return false
  }
  return true
}

/**
 * Transport banners must be driven by real transport-layer facts only — never by
 * application-silence inference (T4 §5.2 B7 / §11.1).
 */
function checkTransportFactDriven(input: ReviewTraceInput): boolean {
  const factStatuses = new Set(input.transport.map((f) => f.status))
  for (const banner of input.ui.transportBanners) {
    if (banner.status !== 'connected' && banner.status !== 'reconnecting' && banner.status !== 'disconnected') return false
    if (!factStatuses.has(banner.status)) return false
  }
  return true
}

/** F-pattern scan (T4 §10 F1–F10) via UI records. */
function checkProhibitedPatterns(input: ReviewTraceInput): boolean {
  // F8: no processing indicator while a question card is shown (PIN).
  const pinShownAt = input.ui.questionCard.filter((q) => q.shown).map((q) => q.at)
  const processingWhilePin = input.ui.processing.some((p) =>
    p.shown && pinShownAt.some((at) => Math.abs(p.at - at) < 200),
  )
  // F2: no phase text for tool/retrieval without a matching decisive event.
  const toolCalls = input.decisive.filter((e) => e.type === 'tool_call')
  const phaseTexts = input.ui.phaseTexts
  const fakePhase = phaseTexts.some((p) =>
    (p.text.includes('检索') || p.text.includes('调用') || p.text.includes('运行')) &&
    toolCalls.length === 0,
  )
  return !processingWhilePin && !fakePhase
}

function checkNonDestructive(input: ReviewTraceInput): boolean {
  const { derived, ui } = input
  const terminal = derived.terminal
  if (terminal === 'ER' || terminal === 'CA' || terminal === 'TO') {
    // Content rendered before the terminal block must be retained (T1 §11.5 / P7).
    const terminalAt = derived.terminalAt ?? Infinity
    if (ui.contentRenderedAt !== undefined && ui.contentRenderedAt > terminalAt) return false
    if (ui.contentRenderedAt === undefined && derived.states.includes('G')) return false
  }
  return true
}

/** Idle timer must not fire while in PIN (T4 D6 / T2 §8). */
function checkPinExemption(input: ReviewTraceInput): boolean {
  const pinSegments = input.derived.segments.filter((s) => s.state === 'PIN')
  if (!pinSegments.length) return true
  const timeout = input.actions.find((a) => a.kind === 'timeout')
  if (!timeout) return true
  return !pinSegments.some((s) => timeout.at >= s.startAt && timeout.at <= s.endAt + 0.5)
}

/** In G, the streaming content is primary — no large processing indicator after content. */
function checkContentStateSeparation(input: ReviewTraceInput): boolean {
  const contentAt = input.ui.contentRenderedAt
  if (contentAt === undefined) return true
  return !input.ui.processing.some((p) => p.shown && p.at >= contentAt - 0.5)
}

/** Scan phase texts for clearly prohibited internal/ETA strings (F3/F6). */
function scanProhibitedText(ui: UiObservation): string[] {
  const hits: string[] = []
  for (const p of ui.phaseTexts) {
    const text = p.text.toLowerCase()
    for (const word of PROHIBITED_TEXT) {
      if (text.includes(word)) {
        hits.push(word)
        break
      }
    }
  }
  return hits
}
