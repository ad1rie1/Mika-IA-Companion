/**
 * Persistent identity for a web visitor.
 *
 * Stores a stable `person_id` in localStorage so that:
 *   - reconnecting the WebSocket doesn't change who Mika thinks you are
 *   - `PersonProfile` / `Commitment` / emotional memory per-person actually
 *     accumulate across sessions (otherwise each reconnect = new UUID =
 *     Mika never recognizes returning visitors on the web)
 *
 * The ID is prefixed with "web_" so it cannot collide with Telegram IDs
 * (which use "tg_<user_id>") or backend-internal IDs.
 *
 * If localStorage is unavailable (SSR, private mode restrictions), we
 * fall back to a per-session ID that lasts only as long as the tab.
 */

const STORAGE_KEY = "vtuber.person_id";
const DISPLAY_NAME_KEY = "vtuber.display_name";
const ID_PREFIX = "web_";

function generateId(): string {
  // 12 hex chars = 48 bits — enough for a visitor pool without collisions.
  const rand = new Uint8Array(6);
  crypto.getRandomValues(rand);
  return ID_PREFIX + Array.from(rand).map((b) => b.toString(16).padStart(2, "0")).join("");
}

function safeGet(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function safeSet(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* private mode / storage disabled — ignore */
  }
}

export class IdentityService {
  private _personId: string;
  private _displayName: string | null;

  constructor() {
    const existing = safeGet(STORAGE_KEY);
    if (existing && existing.startsWith(ID_PREFIX)) {
      this._personId = existing;
    } else {
      this._personId = generateId();
      safeSet(STORAGE_KEY, this._personId);
    }
    this._displayName = safeGet(DISPLAY_NAME_KEY);
  }

  get personId(): string {
    return this._personId;
  }

  get displayName(): string | null {
    return this._displayName;
  }

  setDisplayName(name: string): void {
    const trimmed = name.trim().slice(0, 80);
    this._displayName = trimmed || null;
    if (trimmed) {
      safeSet(DISPLAY_NAME_KEY, trimmed);
    } else {
      try {
        localStorage.removeItem(DISPLAY_NAME_KEY);
      } catch {
        /* ignore */
      }
    }
  }

  /** Drop the persisted ID — next reload starts fresh. */
  reset(): void {
    try {
      localStorage.removeItem(STORAGE_KEY);
      localStorage.removeItem(DISPLAY_NAME_KEY);
    } catch {
      /* ignore */
    }
    this._personId = generateId();
    this._displayName = null;
    safeSet(STORAGE_KEY, this._personId);
  }
}
