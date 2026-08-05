import type { SleepPhase } from "./sleep";
import type { AvatarStateSnapshot } from "./animation";

// ── Wire payload fragments ──────────────────────────────────────────

export type VoicePersona = "speaking" | "inner";

/**
 * Voice identity multipliers sent by the backend (pipeline/voice.py).
 * The INNER persona — Mika thinking out loud rather than talking to you —
 * arrives quieter, slower and slightly lower.
 */
export interface VoiceProfile {
  pitch: number;
  rate: number;
  gain: number;
}

export type EmotionBlend = Array<{ emotion: string; weight: number }>;

export interface ProjectSummary {
  id: number;
  title: string;
  status: string;
  priority: string;
  origin: string;
  emotion_policy: string;
  schedule_rule: string;
  next_run_at: string | null;
  tasks_total: number;
  tasks_done: number;
  tasks_blocked: number;
}

export interface PendingProjectAction {
  id: number;
  project_id: number;
  project_title: string;
  proposal: string;
  payload_kind: string;
  created_at: string;
}

export interface InnerState {
  drives?: Record<string, { tension: number; last_satisfied: number }>;
  energy?: number;
  circadian?: {
    phase: "morning" | "afternoon" | "evening" | "night";
    hour: number;
    energy: number;
    bias_emotion: string;
  };
  sleep_phase?: SleepPhase;
  today_journal?: {
    date: string;
    narrative: string;
    dominant_emotion: string;
    persons_interacted: string[];
  };
  last_dream?: {
    content: string;
    dream_type: "associative" | "nightmare" | "pleasant" | "mundane";
    vividness: number;
    emotion: string;
    night_of: string;
    recalled: boolean;
  };
  projects?: ProjectSummary[];
  pending_project_actions?: PendingProjectAction[];
  self_narrative?: {
    content: string;
    key_themes: string[];
    key_people: string[];
    dominant_mood: string;
    created_at: string;
  };
  ruminations?: Array<{
    summary: string;
    intensity: number;
    emotion: string;
  }>;
  person_profile?: {
    name: string;
    summary: string;
    closeness: string;
    preferred_tone: string;
    topics_of_interest: string[];
    sensitive_topics: string[];
    interaction_count: number;
  };
  pending_commitments?: string[];
  /**
   * Whether this payload was collected *for* an identifiable person, and so
   * whether `identity` / `person_profile` / `pending_commitments` are
   * authoritative. A section with nothing to report is omitted from the
   * payload, so without this flag "she knows nothing about you" and "this
   * frame is not about anyone" look the same — and a panel that clears what
   * it is handed nothing for lost the identity block on every sleep-phase
   * transition.
   */
  person_scope?: boolean;
  /**
   * Who Mika thinks she is talking to, and how sure (identity/trust.py).
   * Present for any non-throwaway person_id — unlike `person_profile`, which
   * is withheld entirely until she is convinced. That asymmetry is the point:
   * the panel can show "someone claims to be Thomas" without showing any of
   * Thomas's history.
   */
  identity?: {
    known_as: string;
    /** 0..1 — see identity/trust.py::Certainty. */
    certainty: number;
    /** One French sentence describing the situation, not a score. */
    level: string;
    /** "authenticated" | "account" | "public" | "internal" */
    trust: string;
    pending_claims: Array<{
      id: number;
      name: string;
      kind: string;
      evidence: string;
      created_at: string;
    }>;
  };
}

// ── Server → client frames ──────────────────────────────────────────

export interface SpeechMessage {
  type: "speech";
  text?: string;
  emotion?: string;
  emotion_intensity?: number;
  emotion_blend?: EmotionBlend;
  emotion_state?: Record<string, unknown>;
  source?: string;
  person_id?: string;
  inner_state?: InnerState;
  speak?: boolean;
  voice_reason?: string;
  voice_persona?: VoicePersona;
  voice_profile?: VoiceProfile;
  /**
   * Persistence cursors (backend/communication/history.py). `message_id` is
   * this reply's row; the client keeps the highest it has rendered and asks
   * for everything after it on reconnect. Null when the turn was not
   * persisted — a message the server did not record must never advance the
   * cursor past it.
   */
  message_id?: number | null;
  user_message_id?: number | null;
  /** Echo of the id the browser attached to its own optimistic bubble. */
  client_msg_id?: string | null;
}

/** One persisted message as the history frame carries it. */
export interface HistoryEntry {
  id: number;
  role: string;
  text: string;
  /** Epoch milliseconds — read straight into `new Date()`. */
  ts: number;
  source?: string;
  emotion?: string;
  emotion_intensity?: number;
  attachments?: unknown[];
}

/**
 * The conversation as the server holds it. Sent unprompted at connect
 * (`mode: "initial"`) and in answer to a `sync` (`mode: "catchup"`).
 *
 * `truncated` means the gap was wider than the server will ship at once and
 * the *oldest* missed messages were dropped. It is reported rather than
 * hidden: a silent cap would advance the cursor past messages that were
 * never displayed, which is the same hole this protocol closes, wearing the
 * appearance of a complete sync.
 */
export interface HistoryMessage {
  type: "history";
  mode: "initial" | "catchup";
  messages: HistoryEntry[];
  last_id: number;
  truncated: boolean;
}

/**
 * What became of a frame the client sent. Emitted before the pipeline runs:
 * "the server has it" and "she answered" are different facts, and treating
 * them as one is what made a queued message look delivered.
 */
export interface AckMessage {
  type: "ack";
  client_msg_id: string;
  /**
   * Anything other than `accepted` means no reply is ever coming. The list
   * must stay in step with the consumer (`_send_ack` call sites in
   * communication/channels/web_frontend.py): a status missing here is
   * still treated as a refusal at runtime, but the type would be claiming
   * the server cannot send it.
   */
  status:
    | "accepted"
    | "rate_limited"
    | "empty"
    | "overloaded"
    | "too_long"
    | "attachments_rejected"
    // Refus émis par le client lui-même (WebSocketClient), jamais reçus du
    // serveur : un frame trop gros est rejeté par le transport avant
    // d'atteindre le consumer (fermeture 1009, donc aucun ack), et un frame
    // que la file a fini par abandonner n'est jamais parti. Ils empruntent le
    // même chemin d'affichage — un refus reste un refus.
    | "frame_too_large"
    | "send_abandoned";
}

/** Answer to the client's keepalive; `t` is echoed back verbatim. */
export interface PongMessage {
  type: "pong";
  t?: number;
}

export interface InnerStateUpdateMessage {
  type: "inner_state_update";
  inner_state?: InnerState;
}

/**
 * Live emotional state, pushed between turns (backend/emotion/sync.py).
 * Same emotion fields as `speech`, no text and no inner state: the PAD
 * oscillators keep moving while Mika is silent, and this is what stops the
 * face and the readout from freezing on the last reply. Applied as ambient
 * drift — expression, gaze and hand mood follow it, body one-shots do not.
 */
export interface EmotionUpdateMessage {
  type: "emotion_update";
  person_id?: string;
  emotion?: string;
  emotion_intensity?: number;
  emotion_blend?: EmotionBlend;
  emotion_state?: Record<string, unknown>;
}

export interface ProjectReportMessage {
  type: "project_report";
  project_id: number;
  project_title: string;
  text: string;
}

/**
 * v2 (reserved, not yet emitted by the backend): authoritative body
 * state broadcast so all clients render the same pose. The frontend
 * will interpolate toward it and demote its local sleep-phase→pose
 * inference to a fallback.
 */
export interface AvatarStateMessage {
  type: "avatar_state";
  state: AvatarStateSnapshot;
}

/** Synthetic local event emitted by WebSocketClient (not from the wire). */
export interface ConnectionEvent {
  /** "unauthorized" is terminal: the socket was refused (4401) and no
   *  amount of retrying changes that — the session has to. */
  status: "connected" | "disconnected" | "reconnecting" | "unauthorized";
  retryInMs?: number;
}

export interface ServerMessageMap {
  speech: SpeechMessage;
  history: HistoryMessage;
  ack: AckMessage;
  pong: PongMessage;
  inner_state_update: InnerStateUpdateMessage;
  emotion_update: EmotionUpdateMessage;
  project_report: ProjectReportMessage;
  avatar_state: AvatarStateMessage;
  connection: ConnectionEvent;
}
