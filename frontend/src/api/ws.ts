import { wsUrl } from './http'

export type StreamEventType =
  | 'stage_start'
  | 'stage_end'
  | 'thinking'
  | 'observation'
  | 'content'
  | 'tool_call'
  | 'tool_result'
  | 'progress'
  | 'sources'
  | 'result'
  | 'error'
  | 'session'
  | 'session_meta'
  | 'done'
  | 'wait_for_input'

export interface StreamEvent {
  type: StreamEventType
  source: string
  stage: string
  content: string
  metadata: Record<string, unknown>
  session_id?: string
  turn_id?: string
  seq?: number
  timestamp: number
  /** Client monotonic arrival time (ms) — set by the transport layer at onmessage
   *  boundary. This is the O-plane perception clock (T2 I11 / T3 §1); never
   *  sent back to the server. */
  clientArrivalAt?: number
}

export interface StartTurnMessage {
  type: 'message' | 'start_turn'
  content: string
  tools?: string[]
  capability?: string | null
  session_id?: string | null
  attachments?: {
    type: string
    url?: string
    base64?: string
    filename?: string
    mime_type?: string
  }[]
  language?: string
  config?: Record<string, unknown>
  /** Learning goal (``book_id``) to bind this turn to (learn mode). */
  mastery_path_id?: string
}

export interface SubscribeSessionMessage {
  type: 'subscribe_session'
  session_id: string
  after_seq?: number
}

export interface ResumeTurnMessage {
  type: 'resume_from'
  turn_id: string
  seq?: number
}

export interface CancelTurnMessage {
  type: 'cancel_turn'
  turn_id: string
}

export interface RegenerateMessage {
  type: 'regenerate'
  session_id: string
  /** Backend message id of the turn to re-run (rolls back it + everything after). */
  message_id?: number
  /** 0-based position of the target message within the session's message list —
   *  fallback used when the persisted message id is unknown. */
  message_index?: number
  overrides?: Record<string, unknown>
}

/** Answer a paused ``ask_user`` question and resume the turn. */
export interface SubmitUserReplyMessage {
  type: 'submit_user_reply'
  turn_id: string
  /** Legacy single free-form reply. */
  text?: string
  /** Structured per-question answers ``{questionId, text}`` (v2 shape). */
  answers?: { questionId: string; text: string }[]
}

export type ClientMessage =
  | StartTurnMessage
  | SubscribeSessionMessage
  | ResumeTurnMessage
  | CancelTurnMessage
  | RegenerateMessage
  | SubmitUserReplyMessage

export type EventHandler = (event: StreamEvent) => void

/** Transport overlay state exposed to the UI (T2 §1.2) — ONLY real transport facts. */
export interface TransportState {
  status: 'connected' | 'reconnecting' | 'disconnected'
  /** Client monotonic time (ms) of the transition. */
  at: number
}

/** Client monotonic clock (O-plane perception clock, T3 §1). */
function perfNow(): number {
  if (typeof performance !== 'undefined' && typeof performance.now === 'function') {
    return performance.now()
  }
  return Date.now()
}

const HEARTBEAT_INTERVAL_MS = 30_000
const HEARTBEAT_TIMEOUT_MS = 45_000
const MAX_RECONNECT_ATTEMPTS = 5
const BASE_RECONNECT_DELAY_MS = 200

export class UnifiedWSClient {
  private ws: WebSocket | null = null
  private onEvent: EventHandler
  private onClose?: () => void
  private onOpen?: () => void
  /** Transport-state listener (W-I5): reconnecting/disconnected/connected. */
  private onTransportState?: (state: TransportState) => void

  private heartbeatTimer: ReturnType<typeof setInterval> | null = null
  private lastReceivedAt = 0

  private reconnectAttempt = 0
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private intentionalClose = false

  private activeTurnId: string | null = null
  private lastSeq = 0
  private pending: ClientMessage[] = []

  constructor(
    onEvent: EventHandler,
    onClose?: () => void,
    onOpen?: () => void,
    onTransportState?: (state: TransportState) => void,
  ) {
    this.onEvent = onEvent
    this.onClose = onClose
    this.onOpen = onOpen
    this.onTransportState = onTransportState
  }

  private reportTransport(status: TransportState['status']): void {
    this.onTransportState?.({ status, at: perfNow() })
  }

  setResumeState(turnId: string | null, seq: number): void {
    this.activeTurnId = turnId
    this.lastSeq = seq
  }

  connect(): void {
    if (this.ws && this.ws.readyState <= WebSocket.OPEN) return
    this.intentionalClose = false

    this.ws = new WebSocket(wsUrl('/api/v1/ws'))

    this.ws.onopen = () => {
      this.reconnectAttempt = 0
      this.lastReceivedAt = Date.now()
      this.startHeartbeat()
      this.onOpen?.()
      this.reportTransport('connected')
      for (const msg of this.pending) {
        this.ws?.send(JSON.stringify(msg))
      }
      this.pending = []
      if (this.activeTurnId) {
        this.send({
          type: 'resume_from',
          turn_id: this.activeTurnId,
          seq: this.lastSeq,
        })
      }
    }

    this.ws.onmessage = (ev) => {
      const arrival = perfNow()
      this.lastReceivedAt = Date.now()
      try {
        const event = JSON.parse(ev.data) as StreamEvent
        const type = (event as { type?: string }).type
        if (type === 'ping' || type === 'pong') return
        event.clientArrivalAt = arrival
        if (event.turn_id) this.activeTurnId = event.turn_id
        if (event.seq != null) this.lastSeq = Math.max(this.lastSeq, event.seq)
        this.onEvent(event)
      } catch {
        console.warn('Unparseable WS message:', ev.data)
      }
    }

    this.ws.onclose = () => {
      this.ws = null
      this.stopHeartbeat()
      if (!this.intentionalClose) this.attemptReconnect()
    }

    this.ws.onerror = (err) => {
      console.error('WS error:', err)
    }
  }

  send(msg: ClientMessage): boolean {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      this.pending.push(msg)
      if (!this.ws) this.connect()
      return true
    }
    this.ws.send(JSON.stringify(msg))
    return true
  }

  disconnect(): void {
    this.intentionalClose = true
    this.stopHeartbeat()
    this.clearReconnectTimer()
    this.ws?.close()
    this.ws = null
    this.resetResumeState()
  }

  get connected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN
  }

  private startHeartbeat(): void {
    this.stopHeartbeat()
    this.heartbeatTimer = setInterval(() => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return
      if (Date.now() - this.lastReceivedAt > HEARTBEAT_TIMEOUT_MS) {
        this.ws.close()
        return
      }
      try {
        this.ws.send(JSON.stringify({ type: 'ping' }))
      } catch {
        /* ignore */
      }
    }, HEARTBEAT_INTERVAL_MS)
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer)
      this.heartbeatTimer = null
    }
  }

  private attemptReconnect(): void {
    if (this.reconnectAttempt >= MAX_RECONNECT_ATTEMPTS) {
      // Reconnect exhausted → transport is truly gone (T2 §1.2 disconnected).
      this.reportTransport('disconnected')
      this.resetResumeState()
      this.onClose?.()
      return
    }
    // Seeking to reconnect (T2 §1.2 reconnecting).
    this.reportTransport('reconnecting')
    const delay = BASE_RECONNECT_DELAY_MS * 2 ** this.reconnectAttempt
    this.reconnectAttempt += 1
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      this.connect()
    }, delay)
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
  }

  private resetResumeState(): void {
    this.activeTurnId = null
    this.lastSeq = 0
    this.reconnectAttempt = 0
  }
}
