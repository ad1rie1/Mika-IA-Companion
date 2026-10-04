// Backend HTTP API base + session-auth helpers.
//
// Le serveur visé est Mika v2 (`backendv2/`, `python -m mika serve`, port
// 8001 par défaut). Le WebSocket s'authentifie par le cookie de session : le
// frontend se connecte d'abord en HTTP (`/auth/login`), le cookie obtenu
// authentifie ensuite la poignée de main du WebSocket.
//
// Toutes les requêtes partent avec `credentials: "include"`. Quand le
// frontend tourne sur une autre origine que le serveur (Vite sur :3000, le
// serveur sur :8001), le serveur doit admettre cette origine : celles du
// développement (localhost/127.0.0.1, ports 3000 et 4173) le sont par
// défaut ; une autre se déclare par `python -m mika serve --origin <adresse>`.
//
// `VITE_BACKEND_ORIGIN` (voir `frontend/Web/.env.example`) change la cible —
// l'ancien moteur (v1, Django) écoutait sur http://localhost:8000.

const BACKEND_ORIGIN =
  (import.meta as any).env?.VITE_BACKEND_ORIGIN ?? "http://localhost:8001";

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
  /**
   * Operator account (`is_staff`). Only operators may approve or reject a
   * project's pending actions: the server answers 403 to a chat account, so
   * the panel hides the buttons rather than offering a refusal.
   */
  operator?: boolean;
}

/**
 * Read the server's CSRF token from the cookie it sets on `/auth/whoami`.
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

/**
 * POST JSON with credentials + the CSRF token.
 *
 * Exporté : c'est le *seul* chemin correct pour un POST vers le backend.
 * Un `fetch` écrit sur place repart en 404 (URL relative → serveur Vite), en
 * 403 (`CsrfViewMiddleware` est installé et aucune vue n'est exemptée) ou
 * anonyme (cookie de session non joint sans `credentials`).
 */
export async function postJson(path: string, body: unknown): Promise<Response> {
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

/** Ce qu'il faut lancer pour que le serveur admette cette page. */
export function serveCommand(origin: string): string {
  return `python -m mika serve --origin ${origin}`;
}

/**
 * Erreur de transport : le serveur n'a jamais répondu, ou le navigateur a
 * jeté sa réponse (cette origine n'est pas admise par le serveur).
 * Distinguée d'un refus applicatif parce que les deux se soignent très
 * différemment — et que les confondre affiche « identifiants invalides » à
 * quelqu'un dont le mot de passe est juste.
 */
export class BackendUnreachableError extends Error {
  /** L'erreur `fetch` d'origine — `cause` demanderait la lib ES2022. */
  readonly reason?: unknown;

  constructor(reason?: unknown) {
    super(
      `Le serveur de Mika ne répond pas sur ${API_BASE}. Vérifie qu'il tourne ` +
        `(dans backendv2/ : python -m mika serve), et qu'il admet cette page : ` +
        `${serveCommand(location.origin)}. Un autre serveur se vise par ` +
        `VITE_BACKEND_ORIGIN (frontend/Web/.env.example).`
    );
    this.name = "BackendUnreachableError";
    this.reason = reason;
  }
}

export async function whoami(): Promise<AuthState> {
  // Also the call that plants the CSRF cookie (the server sets `csrftoken`
  // on it), so it has to happen before any mutating request.
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

/** Refus applicatif du serveur : il a répondu, il dit non. */
export class LoginRefusedError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
    this.name = "LoginRefusedError";
  }
}

/** Le statut de « un compte existe déjà » : la fenêtre du premier compte est
 * fermée (un autre onglet l'a créé entre-temps). */
export const BOOTSTRAP_CLOSED = 409;

/**
 * Create the first account. Open only while no account exists; the server
 * answers 409 forever once anyone exists — a `LoginRefusedError` carrying
 * that status, which is what the login screen reads (never the wording).
 */
export async function bootstrap(
  username: string,
  password: string
): Promise<AuthState> {
  const resp = await postJson("/auth/bootstrap", { username, password });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new LoginRefusedError(resp.status, body.error || "création du compte refusée");
  }
  return body as AuthState;
}

export async function login(
  username: string,
  password: string
): Promise<AuthState> {
  const resp = await postJson("/auth/login", { username, password });
  if (!resp.ok) {
    // Seul le 401 parle du couple identifiant/mot de passe. Un 403 est un
    // rejet CSRF (cookie absent, ou cette origine non admise par le serveur)
    // — un mot de passe correct n'y changera rien.
    if (resp.status === 401) {
      throw new LoginRefusedError(401, "Identifiants invalides.");
    }
    if (resp.status === 403) {
      throw new LoginRefusedError(
        403,
        "Requête refusée (CSRF). Recharge la page ; si ça persiste, le serveur " +
          `n'admet pas cette page : ${serveCommand(location.origin)}.`
      );
    }
    // Le backend plafonne les échecs par fenêtre glissante : réessayer tout
    // de suite ne fait que prolonger le blocage, il faut le dire.
    if (resp.status === 429) {
      throw new LoginRefusedError(
        429,
        "Trop de tentatives de connexion. Attends une minute avant de réessayer."
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
