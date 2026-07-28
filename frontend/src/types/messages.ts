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
}

export interface InnerStateUpdateMessage {
  type: "inner_state_update";
  inner_state?: InnerState;
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
  inner_state_update: InnerStateUpdateMessage;
  project_report: ProjectReportMessage;
  avatar_state: AvatarStateMessage;
  connection: ConnectionEvent;
}
