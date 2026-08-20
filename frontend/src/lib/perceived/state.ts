/**
 * Perceived Latency — decisive cleaning + T2 P-state machine derivation (T6 / W-I2).
 *
 * Implements:
 *  - T3 §11 CLEAN: seq dedup, terminal latch, decisive-only filtering.
 *  - T2 §2.1 transition table (deterministic — unique target per edge).
 *  - T2 §9 invariants I1/I2/I4/I6/I7 (terminal latch, G only from non-empty content,
 *    activity causality, seq monotonicity, terminal mutual exclusion).
 *
 * Pure & replayable (T2 I9): deriveStateSequence is a pure function of the input
 * sequence; replaying the same ordered trace from a cold machine yields the same
 * state sequence and terminal.
 */

import {
  DECISIVE_TYPES,
  TERMINAL_DECISIVE_TYPES,
  RETRIEVAL_TOOLS,
  type PState,
  type PerceivedAction,
  type PerceivedEvent,
  type DerivedState,
  type StateSegment,
  type ToolProfile,
} from './types'

/** Merge-ordered state input (time order, events before actions on exact ties). */
export type StateInput =
  | {
      kind: 'event'
      type: 'content' | 'tool_call' | 'sources' | 'tool_result' | 'wait_for_input' | 'done' | 'error'
      content: string
      metadata: Record<string, unknown>
      at: number
    }
  | { kind: 'submit_user_reply'; at: number }
  | { kind: 'cancel'; at: number }
  | { kind: 'timeout'; at: number }

/** Tie-break priority: terminal/event first (T9: done beats cancel on exact tie). */
function inputPriority(input: StateInput): number {
  if (input.kind === 'event') return 0
  if (input.kind === 'timeout') return 2
  return 1
}

/** T3 §11 CLEAN — seq dedup + terminal latch + decisive-only. */
export function cleanDecisive(events: PerceivedEvent[]): {
  decisive: PerceivedEvent[]
  terminal: PerceivedEvent | null
} {
  const decisive: PerceivedEvent[] = []
  let lastSeq = 0
  let terminal: PerceivedEvent | null = null
  for (const e of events) {
    // Seq monotonic guard (T2 I6 / T3 §8): stale/replayed events are dropped.
    if (e.seq != null && e.seq > 0) {
      if (e.seq <= lastSeq) continue
      lastSeq = e.seq
    }
    // I1 terminal latch: once a terminal is reached, ALL later events are dropped
    // (T2 §9 conflict rule #1 — idempotent).
    if (terminal !== null) continue
    // content(空) is text-level / non-decisive (T2 §5/§11.4) — only non-empty
    // content is the metric axis / G source (T2 I2).
    if (e.type === 'content' && !(e.content ?? '').trim()) continue
    if (!DECISIVE_TYPES.has(e.type)) continue
    decisive.push(e)
    if (TERMINAL_DECISIVE_TYPES.has(e.type)) terminal = e
  }
  return { decisive, terminal }
}

/** Resolve the P-state produced by a done event (T2 §3). */
export function resolveDoneState(event: { content?: string; metadata?: Record<string, unknown> }): PState {
  const status = String(event.metadata?.status ?? '')
  if (status === 'cancelled') return 'CA'
  if (status === 'failed') return 'ER'
  return 'OK'
}

/** Resolve the P-state produced by an error event (T2 §3). */
export function resolveErrorState(event: { content?: string; metadata?: Record<string, unknown> }): PState {
  const status = String(event.metadata?.status ?? '')
  if (status === 'cancelled') return 'CA'
  if (/cancelled/i.test(event.content ?? '')) return 'CA'
  return 'ER'
}

/** True when a tool_call name is a retrieval-kind tool (→ R). */
export function isRetrievalTool(name: string): boolean {
  return RETRIEVAL_TOOLS.has(name)
}

/** Infer the tool profile dimension (T3 §6) from the cleaned decisive events. */
export function toolProfileFromEvents(events: PerceivedEvent[]): ToolProfile {
  let hasRetrieval = false
  let hasOther = false
  for (const e of events) {
    if (e.type !== 'tool_call') continue
    if (isRetrievalTool(e.content)) hasRetrieval = true
    else hasOther = true
  }
  if (!hasRetrieval && !hasOther) return 'no_tool'
  if (hasRetrieval && !hasOther) return 'retrieval_only'
  if (!hasRetrieval && hasOther) return 'tool_only'
  return 'mixed'
}

/** Map a decisive event to its state-machine input. */
function toStateInput(event: PerceivedEvent): StateInput & { kind: 'event' } {
  return {
    kind: 'event',
    type: event.type as 'content' | 'tool_call' | 'sources' | 'tool_result' | 'wait_for_input' | 'done' | 'error',
    content: event.content,
    metadata: event.metadata,
    at: event.arrivalAt,
  }
}

/**
 * Deterministically derive the P-state sequence from an ordered trace.
 *
 * `actions` may include `submit` (the turn opener at tSubmit), `submit_user_reply`,
 * `cancel` and `timeout`. `submit` is expected first; inputs are then merged by
 * (arrival time, priority) so ties resolve deterministically (T2 I9).
 */
export function deriveStateSequence(opts: {
  tSubmit: number
  decisive: PerceivedEvent[]
  actions: PerceivedAction[]
}): DerivedState {
  const { tSubmit, decisive } = opts

  // Build the merged input list, submit first (it defines the turn start).
  const inputs: StateInput[] = []
  for (const a of opts.actions) {
    if (a.kind === 'submit') continue
    if (a.kind === 'submit_user_reply') inputs.push({ kind: 'submit_user_reply', at: a.at })
    else if (a.kind === 'cancel') inputs.push({ kind: 'cancel', at: a.at })
    else if (a.kind === 'timeout') inputs.push({ kind: 'timeout', at: a.at })
  }
  for (const e of decisive) inputs.push(toStateInput(e))
  inputs.sort((x, y) => (x.at - y.at) || (inputPriority(x) - inputPriority(y)))

  const segments: StateSegment[] = []
  let st: PState = 'idle'
  let segStart = tSubmit
  let terminal: PState | null = null
  let terminalAt: number | null = null

  // Read through a function so TS never narrows `st` to a single literal across
  // the closure reassignments (keeps the comparisons type-safe).
  const getState = (): PState => st

  const advance = (next: PState, at: number) => {
    if (getState() !== 'idle') segments.push({ state: st, startAt: segStart, endAt: at })
    st = next
    segStart = at
  }

  const latch = (next: PState, at: number) => {
    // I1 terminal latch: first terminal wins; ignore anything later.
    if (terminal !== null) return
    terminal = next
    terminalAt = at
    // Close the current active segment at the terminal time.
    if (getState() !== 'idle') segments.push({ state: st, startAt: segStart, endAt: at })
    st = next
    segStart = at
  }

  // Opener: submit → S (I5). If absent, stay idle (defensive).
  const submitAt = opts.actions.find((a) => a.kind === 'submit')?.at ?? tSubmit
  st = 'S'
  segStart = submitAt

  for (const input of inputs) {
    if (terminal !== null) break // latch (I1) — later inputs dropped
    const at = input.at

    if (input.kind === 'event') {
      const type = input.type
      if (type === 'content') {
        const text = (input.content ?? '').trim()
        if (!text) continue // empty content is non-decisive (T2 §5)
        if (getState() !== 'G') advance('G', at)
        continue
      }
      if (type === 'tool_call') {
        const next = isRetrievalTool(input.content) ? 'R' : 'T'
        if (getState() !== next) advance(next, at)
        continue
      }
      if (type === 'sources') {
        if (getState() !== 'R') advance('R', at)
        continue
      }
      if (type === 'tool_result') {
        // Confirms/keeps the current R/T class (T2 §2.2) — no class change.
        continue
      }
      if (type === 'wait_for_input') {
        if (getState() !== 'PIN') advance('PIN', at)
        continue
      }
      if (type === 'done') {
        latch(resolveDoneState(input), at)
        continue
      }
      if (type === 'error') {
        latch(resolveErrorState(input), at)
        continue
      }
      continue
    }

    if (input.kind === 'submit_user_reply') {
      // PIN → S (T2 §2.1). Ignored outside PIN (no valid edge).
      if (getState() === 'PIN') advance('S', at)
      continue
    }
    if (input.kind === 'cancel') {
      latch('CA', at)
      continue
    }
    if (input.kind === 'timeout') {
      // Idle timer only fires from non-PIN active states (T2 I3; PIN exempt D6).
      const cur = getState()
      if (cur === 'PIN') continue
      if (cur === 'S' || cur === 'R' || cur === 'T' || cur === 'G') latch('TO', at)
      continue
    }
  }

  // If no terminal arrived, close the current active segment at the last observed time.
  if (terminal === null && getState() !== 'idle') {
    const lastAt = inputs.length ? inputs[inputs.length - 1].at : submitAt
    if (getState() !== 'idle') segments.push({ state: st, startAt: segStart, endAt: Math.max(lastAt, segStart) })
  }

  const states: PState[] = []
  for (const seg of segments) {
    if (states[states.length - 1] !== seg.state) states.push(seg.state)
  }
  if (terminal !== null) states.push(terminal)

  return { segments, states, terminal, terminalAt }
}

/**
 * T3 §11 replay helper — given a logged trace (events + actions) produce the same
 * derived state as the realtime machine. Because deriveStateSequence is a pure
 * function, replaying the same ordered inputs always yields the same result (T2 I9).
 */
export function replayTrace(opts: {
  tSubmit: number
  events: PerceivedEvent[]
  actions: PerceivedAction[]
}): DerivedState {
  const { decisive, terminal } = cleanDecisive(opts.events)
  const derived = deriveStateSequence({ tSubmit: opts.tSubmit, decisive, actions: opts.actions })
  if (terminal && derived.terminal === null) {
    // Latch the terminal even if the machine already closed (defensive replay).
    return { ...derived, terminal: resolveTerminalFromEvent(terminal), terminalAt: terminal.arrivalAt }
  }
  return derived
}

function resolveTerminalFromEvent(event: PerceivedEvent): PState {
  if (event.type === 'done') return resolveDoneState(event)
  if (event.type === 'error') return resolveErrorState(event)
  return 'OK'
}
