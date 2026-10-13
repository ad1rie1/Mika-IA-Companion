import {
  SERVER_FRAME_TYPES,
  type ClientFrame,
  type ServerFrame,
} from "./protocol.g";

/**
 * Lire et écrire le fil du monde (`mika.world/1`). Le noyau a validé ce
 * qu'il envoie ; ce client ne revalide pas le contenu, il reconnaît la trame
 * par son `type` et ignore sans planter ce qu'il ne connaît pas — une trame
 * plus récente que lui (backendv2/docs/protocole-monde.md § 10).
 */

export type ServerRead =
  | { frame: ServerFrame; error?: undefined; seq?: undefined }
  | { frame: null; error: string; seq: number | null };

const KNOWN: ReadonlySet<string> = new Set(SERVER_FRAME_TYPES);

export function readServer(text: string): ServerRead {
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    return { frame: null, error: "JSON illisible", seq: null };
  }
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return { frame: null, error: "une trame est un objet JSON", seq: null };
  }
  const o = raw as Record<string, unknown>;
  const seq = typeof o.seq === "number" ? o.seq : null;
  if (typeof o.type !== "string") return { frame: null, error: "trame sans « type »", seq };
  if (!KNOWN.has(o.type)) return { frame: null, error: `type inconnu « ${o.type} »`, seq };
  return { frame: raw as ServerFrame };
}

export function writeClient(frame: ClientFrame): string {
  return JSON.stringify(frame);
}
