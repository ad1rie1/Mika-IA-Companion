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

/**
 * Read Django's CSRF token from the cookie it sets on `/auth/whoami`.
 *
 * The cookie is deliberately not HttpOnly: it is not the secret. What a
 * cross-site page cannot do is produce the *pair* — it can neither read this
 * cookie (same-origin policy) nor set the `X-CSRFToken` header on a
 * cross-origin request without a preflight it will fail.
 */
function csrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : "";
}

/** POST JSON with credentials + the CSRF token. */
async function postJson(path: string, body: unknown): Promise<Response> {
  try {
    return await fetch(`${API_BASE}${path}`, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken(),
      },
      body: JSON.stringify(body),
    });
  } catch (err) {
    throw new BackendUnreachableError(err);
  }
}

/**
 * Erreur de transport : le backend n'a jamais répondu, ou le navigateur a
 * jeté sa réponse (origine absente de CORS_ALLOWED_ORIGINS). Distinguée d'un
 * refus applicatif parce que les deux se soignent très différemment — et que
 * les confondre affiche « identifiants invalides » à quelqu'un dont le mot de
 * passe est juste.
 */
export class BackendUnreachableError extends Error {
  /** L'erreur `fetch` d'origine — `cause` demanderait la lib ES2022. */
  readonly reason?: unknown;

  constructor(reason?: unknown) {
    super(
      `Backend injoignable sur ${API_BASE}. Vérifie qu'il tourne, et que ` +
        `l'origine ${location.origin} est bien dans CORS_ALLOWED_ORIGINS.`
    );
    this.name = "BackendUnreachableError";
    this.reason = reason;
  }
}

export async function whoami(): Promise<AuthState> {
  // Also the call that plants the CSRF cookie (see @ensure_csrf_cookie on
  // the view), so it has to happen before any mutating request.
  //
  // Une panne de transport n'est délibérément plus rattrapée ici : renvoyer
  // `{authenticated:false}` faisait afficher l'écran de login alors que rien
  // ne pouvait aboutir, et chaque tentative repartait en « identifiants
  // invalides ».
  let resp: Response;
  try {
    resp = await fetch(`${API_BASE}/auth/whoami`, { credentials: "include" });
  } catch (err) {
    throw new BackendUnreachableError(err);
  }
  return (await resp.json()) as AuthState;
}

/**
 * Create the first account. Open only while the user table is empty; the
 * backend returns 409 forever once anyone exists.
 */
export async function bootstrap(
  username: string,
  password: string
): Promise<AuthState> {
  const resp = await postJson("/auth/bootstrap", { username, password });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error(body.error || "bootstrap refusé");
  }
  return body as AuthState;
}

/** Refus applicatif du serveur : il a répondu, il dit non. */
export class LoginRefusedError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
    this.name = "LoginRefusedError";
  }
}

export async function login(
  username: string,
  password: string
): Promise<AuthState> {
  const resp = await postJson("/auth/login", { username, password });
  if (!resp.ok) {
    // Seul le 401 parle du couple identifiant/mot de passe. Un 403 est un
    // rejet CSRF (cookie absent, origine non listée dans
    // CSRF_TRUSTED_ORIGINS) — un mot de passe correct n'y changera rien.
    if (resp.status === 401) {
      throw new LoginRefusedError(401, "Identifiants invalides.");
    }
    if (resp.status === 403) {
      throw new LoginRefusedError(
        403,
        "Requête refusée (CSRF). Recharge la page ; si ça persiste, vérifie " +
          `que ${location.origin} est dans CSRF_TRUSTED_ORIGINS.`
      );
    }
    throw new LoginRefusedError(
      resp.status,
      `Le serveur a refusé la connexion (HTTP ${resp.status}).`
    );
  }
  return (await resp.json()) as AuthState;
}

export async function logout(): Promise<void> {
  await fetch(`${API_BASE}/auth/logout`, {
    credentials: "include",
    headers: { "X-CSRFToken": csrfToken() },
  });
}
