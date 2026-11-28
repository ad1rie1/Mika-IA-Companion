/**
 * Les fichiers du chat, par l'API par personne (`backend/docs/protocole-moi.md` § 14, ADR 0312) : tout ce que tu as
 * envoyé à Mika et ce qu'elle t'a envoyé, sur toute la conversation (pas seulement les messages chargés à l'écran),
 * page par page, cherché par nom, trié par sorte et par qui l'a envoyé. Ce qui se télécharge porte l'adresse que
 * `GET /files/<id>` te rend ; le reste dit pourquoi, sans adresse. Les instants sont en millisecondes.
 */
import { query } from "./mail";
import { getJson, MOI } from "./moi";

/** Les sortes que l'écran trie, dans l'ordre de ses filtres (`app/me/chat.py::SORTES`). */
export const FILE_SORTS = ["image", "pdf", "texte", "tableau", "autre"] as const;
export type FileSort = (typeof FILE_SORTS)[number];

/**
 * Pourquoi un fichier ne se télécharge pas : retiré (trop vieux, la place, une opératrice), ses octets perdus ou
 * introuvables, jamais gardé (`app/me/chat.py::REASONS`). Une pièce gardée se télécharge sans attendre que Mika l'ait
 * lue de près.
 */
export type FileReason = "retention" | "budget" | "operator" | "missing" | "unkept";

export interface ChatFileItem {
  /** Sa clé dans la liste : `id`, ou son message et sa place pour une pièce jamais gardée. */
  key: string;
  id: string;
  name: string;
  mime: string;
  size: number;
  sorte: FileSort;
  from: "toi" | "mika";
  at: number;
  /** Le message qui le porte, et sa place dans ce message (à partir de 0). */
  message: number;
  index: number;
  available: boolean;
  /** `/files/<id>`, seulement s'il se télécharge. */
  url?: string;
  reason?: FileReason;
}

export interface ChatFilesPage {
  items: ChatFileItem[];
  total: number;
  page: number;
  pages: number;
  per: number;
  /** Chaque sorte parmi ceux que la recherche et l'envoyeur gardent ; `""` : toutes. */
  counts: Record<"" | FileSort, number>;
  /** Ceux de la sélection qui ne se téléchargent plus. */
  unavailable: number;
}

export interface ChatFilesQuery {
  q?: string;
  sorte?: FileSort | "";
  de?: "toi" | "mika" | "";
  /** Un fil de travail (mode pro) ; vide : le fil avec elle. */
  fil?: string;
  page?: number;
  par?: number;
}

/** Les bornes que l'API reçoit (`app/me/chat.py`). */
export const CHAT_FILES_LIMITS = { q: 200, perMax: 60 } as const;

const FILES = `${MOI}/chat/fichiers`;

export function chatFiles(params: ChatFilesQuery): Promise<ChatFilesPage> {
  return getJson<ChatFilesPage>(`${FILES}${query({ ...params })}`);
}

/** Les fichiers d'un message (son numéro), où qu'il soit dans la conversation. */
export async function messageFiles(message: number, fil = ""): Promise<ChatFileItem[]> {
  const got = await getJson<{ items: ChatFileItem[] }>(`${FILES}${query({ message, fil })}`);
  return got.items;
}
