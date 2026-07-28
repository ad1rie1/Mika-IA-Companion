// Backend HTTP API base + session-auth helpers.
//
// The VTuber WebSocket authenticates via the Django session cookie
// (AuthMiddlewareStack on the backend). The frontend logs in over HTTP first;
// the resulting session cookie then authenticates the WebSocket handshake.
//
// All requests use `credentials: "include"` so the session cookie is sent.
// When the frontend runs on a different origin than the backend (e.g. Vite on
// :3000 vs backend on :8000), the backend must enable credentialed CORS
// (CORS_ALLOW_CREDENTIALS=True + explicit CORS_ALLOWED_ORIGINS) and an
// appropriate SESSION_COOKIE_SAMESITE.

const BACKEND_ORIGIN =
  (import.meta as any).env?.VITE_BACKEND_ORIGIN ?? "http://localhost:8000";

export const API_BASE = BACKEND_ORIGIN;
export const WS_URL =
  BACKEND_ORIGIN.replace(/^http/, "ws") + "/ws";

export interface AuthState {
  authenticated: boolean;
  username?: string;
  /** Name Mika should call you — full name when set, else the username. */
  display_name?: string;
  /**
   * Server-issued identity. Authoritative: an authenticated connection is
   * bound to this id server-side and any client-supplied one is ignored, so
   * the app must use this rather than its locally generated `web_*` id.
   */
  person_id?: string;
  /** Whether the backend refuses unauthenticated WebSocket connections. */
  auth_required?: boolean;
  /** True while no account exists yet — the bootstrap window. */
  needs_bootstrap?: boolean;
}

export async function whoami(): Promise<AuthState> {
  try {
    const resp = await fetch(`${API_BASE}/auth/whoami`, {
      credentials: "include",
    });
    return (await resp.json()) as AuthState;
  } catch {
    return { authenticated: false };
  }
}

/**
 * Create the first account. Open only while the user table is empty; the
 * backend returns 409 forever once anyone exists.
 */
export async function bootstrap(
  username: string,
  password: string
): Promise<AuthState> {
  const resp = await fetch(`${API_BASE}/auth/bootstrap`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error(body.error || "bootstrap refusé");
  }
  return body as AuthState;
}

export async function login(
  username: string,
  password: string
): Promise<AuthState> {
  const resp = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!resp.ok) {
    throw new Error("invalid credentials");
  }
  return (await resp.json()) as AuthState;
}

export async function logout(): Promise<void> {
  await fetch(`${API_BASE}/auth/logout`, { credentials: "include" });
}
