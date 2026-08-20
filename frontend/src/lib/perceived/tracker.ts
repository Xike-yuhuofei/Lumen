/**
 * Perceived Latency — per-turn runtime tracker (T6 / W-I1..W-I5 integration).
 *
 * A PerceivedTurnTracker collects O-plane facts for one turn and, on finalize(),
 * deterministically derives the P-state sequence (W-I2), computes M1–M8 with
 * SYS_WAIT accounting (W-I3), records PIN (W-I4) and transport (W-I5) facts and
 * produces a T3 §9 TurnSample (one JSONL line).
 */

import { createPerceivedClock, type PerceivedClock } from './clock'
import { cleanDecisive, deriveStateSequence, toolProfileFromEvents } from './state'
import { computeMetrics, type MetricsInput } from './metrics'
import { runStaticReview, type UiObservation } from './review'
import {
  type Outcome,
  type PerceivedAction,
  type PerceivedEvent,
  type SampleDimensions,
  type TransportBucket,
  type TransportFact,
  type TurnSample,
  type Warmth,
} from './types'

export interface TrackerInit {
  sessionId?: string
  turnId?: string
  capability: string
  appVersion: string
  warmth: Warmth
  tSubmit: number
  clock?: PerceivedClock
}

export class PerceivedTurnTracker {
  readonly tSubmit: number
  readonly sessionId?: string
  turnId?: string
  readonly capability: string
  readonly appVersion: string
  readonly warmth: Warmth
  private readonly clock: PerceivedClock

  private events: PerceivedEvent[] = []
  private actions: PerceivedAction[] = []
  private sessionArrivalAt: number | null = null
  private lastEventAt: number | null = null

  /** PIN user-wait intervals [t_wi, exit]. */
  private userIntervals: { start: number; end: number }[] = []
  private pinOpenAt: number | null = null

  /** Disconnect outage intervals. */
  private discIntervals: { start: number; end: number; terminated?: boolean }[] = []
  private discPendingStart: number | null = null
  private discLastLiveAt: number | null = null
  private transportFacts: TransportFact[] = []

  private ui: UiObservation = { processing: [], questionCard: [], errorBlocks: [], timeoutBlocks: [], phaseTexts: [], transportBanners: [] }
  private finalized = false

  constructor(init: TrackerInit) {
    this.tSubmit = init.tSubmit
    this.sessionId = init.sessionId
    this.turnId = init.turnId
    this.capability = init.capability
    this.appVersion = init.appVersion
    this.warmth = init.warmth
    this.clock = init.clock ?? createPerceivedClock()
  }

  /** Feed any WS event (arrival-ordered). */
  onEvent(event: PerceivedEvent): void {
    if (this.finalized) return
    // Close a pending disconnect interval on the first post-reconnect event (T3 M7b).
    if (this.discPendingStart != null) {
      this.discIntervals.push({ start: this.discPendingStart, end: event.arrivalAt })
      this.discPendingStart = null
    }
    this.events.push(event)
    this.lastEventAt = event.arrivalAt
    if (event.type === 'session') this.sessionArrivalAt = event.arrivalAt
    if (event.type === 'wait_for_input' && this.pinOpenAt === null) {
      this.pinOpenAt = event.arrivalAt // t_wi
    }
  }

  /** Record a user action (client monotonic time). */
  onAction(action: PerceivedAction): void {
    if (this.finalized) return
    this.actions.push(action)
    if (action.kind === 'submit_user_reply' || action.kind === 'cancel' || action.kind === 'timeout') {
      if (this.pinOpenAt !== null) {
        this.userIntervals.push({ start: this.pinOpenAt, end: action.at })
        this.pinOpenAt = null
      }
    }
    // A terminal user action closes an open disconnect interval as terminated.
    if (action.kind === 'cancel' || action.kind === 'timeout') {
      if (this.discPendingStart !== null) {
        this.discIntervals.push({ start: this.discPendingStart, end: action.at, terminated: true })
        this.discPendingStart = null
      }
    }
  }

  /** Record a transport-layer fact (only real transport events — never silence). */
  onTransport(fact: TransportFact): void {
    if (this.finalized) return
    this.transportFacts.push(fact)
    if (fact.status === 'reconnecting' || fact.status === 'disconnected') {
      if (this.discPendingStart === null) {
        this.discPendingStart = fact.at // t_disc_detected
        this.discLastLiveAt = this.lastEventAt
      }
    }
    if (fact.status === 'connected') {
      // Recovery completes on the first event after reconnect (T3 M7b), so we
      // keep the interval open until onEvent closes it.
    }
  }

  /** Attach UI observations for the T4 §11.1 static review (W-I7). */
  setUiObservation(patch: Partial<UiObservation>): void {
    this.ui = {
      processing: patch.processing ?? this.ui.processing,
      questionCard: patch.questionCard ?? this.ui.questionCard,
      errorBlocks: patch.errorBlocks ?? this.ui.errorBlocks,
      timeoutBlocks: patch.timeoutBlocks ?? this.ui.timeoutBlocks,
      phaseTexts: patch.phaseTexts ?? this.ui.phaseTexts,
      contentRenderedAt: patch.contentRenderedAt ?? this.ui.contentRenderedAt,
      firstFeedbackAt: patch.firstFeedbackAt ?? this.ui.firstFeedbackAt,
      transportBanners: patch.transportBanners ?? this.ui.transportBanners,
    }
  }

  // --- Append-style UI observation helpers (called by App.tsx) ---

  /** E1 shown at submit (same tick as t_submit, T4 D1). */
  recordFirstFeedback(at: number): void {
    if (this.ui.firstFeedbackAt === undefined) this.ui.firstFeedbackAt = at
  }

  recordProcessing(at: number, shown: boolean): void {
    this.ui.processing.push({ at, shown })
  }

  recordQuestionCard(at: number, shown: boolean): void {
    this.ui.questionCard.push({ at, shown })
  }

  recordErrorBlock(at: number): void {
    this.ui.errorBlocks.push({ at })
  }

  recordTimeoutBlock(at: number): void {
    this.ui.timeoutBlocks.push({ at })
  }

  /** First non-empty content rendered (G enters → indicator hidden, T4 §4.5). */
  recordContentRendered(at: number): void {
    if (this.ui.contentRenderedAt === undefined) this.ui.contentRenderedAt = at
  }

  recordTransportBanner(at: number, status: string): void {
    this.ui.transportBanners.push({ at, status })
  }

  recordPhaseText(at: number, text: string): void {
    this.ui.phaseTexts.push({ at, text })
  }

  /** Close any open PIN / disconnect interval at the terminal time. */
  private closeAtTerminal(τ: number): void {
    if (this.pinOpenAt !== null) {
      this.userIntervals.push({ start: this.pinOpenAt, end: τ })
      this.pinOpenAt = null
    }
    if (this.discPendingStart !== null) {
      this.discIntervals.push({ start: this.discPendingStart, end: τ, terminated: true })
      this.discPendingStart = null
    }
  }

  /** Produce the T3 §9 sample. Returns null when the turn never reached a terminal. */
  finalize(): TurnSample | null {
    if (this.finalized) return null
    this.finalized = true

    const { decisive } = cleanDecisive(this.events)
    const actions = this.actions
    const derived = deriveStateSequence({ tSubmit: this.tSubmit, decisive, actions })

    // Close PIN / disconnect at the terminal time (I1 latch).
    const τ = derived.terminalAt
    if (τ != null) this.closeAtTerminal(τ)

    // Only turns that reached a terminal produce a usable sample (T3 §8).
    if (derived.terminal === null || τ === null) return null

    const outcome: Outcome | null =
      derived.terminal === 'OK' ? 'ok'
        : derived.terminal === 'ER' ? 'er'
        : derived.terminal === 'CA' ? 'ca'
        : derived.terminal === 'TO' ? 'to'
        : null

    const hasPin = this.userIntervals.length > 0
    const hasDisc = this.discIntervals.length > 0
    const transport: TransportBucket =
      this.discIntervals.some((iv) => iv.terminated)
        ? 'disconnected_terminated'
        : hasDisc ? 'disconnected_recovered'
          : 'clean'

    const metricsInput: MetricsInput = {
      tSubmit: this.tSubmit,
      sessionArrivalAt: this.sessionArrivalAt,
      decisive,
      derived,
      userIntervals: this.userIntervals,
      discIntervals: this.discIntervals,
      lastLiveAt: this.discLastLiveAt ?? undefined,
      cancelAt: actions.find((a) => a.kind === 'cancel')?.at,
    }
    const m = computeMetrics(metricsInput)

    const dims: SampleDimensions = {
      capability: this.capability,
      tool_profile: toolProfileFromEvents(decisive),
      outcome: outcome ?? 'ok',
      transport,
      warmth: this.warmth,
      has_pin: hasPin,
    }

    const review = runStaticReview({
      tSubmit: this.tSubmit,
      decisive,
      actions,
      transport: this.transportFacts,
      derived,
      ui: this.ui,
    })

    return {
      schema_version: '1.0',
      session_id: this.sessionId,
      turn_id: this.turnId,
      app_version: this.appVersion,
      generated_at: new Date().toISOString(),
      dimensions: dims,
      metrics: m.metrics,
      first_decisive_kind: m.firstDecisiveKind,
      invalid: m.invalid,
      user_wait_s: m.userWaitMs / 1000,
      disconnect_s: m.discMs / 1000,
      review,
    }
  }

  get hasTerminal(): boolean {
    return this.actions.some((a) => a.kind === 'cancel' || a.kind === 'timeout') ||
      this.events.some((e) => e.type === 'done' || e.type === 'error')
  }
}
