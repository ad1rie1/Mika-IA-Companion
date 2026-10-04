import { describe, it, expect } from "vitest";
import {
  acceptRefusal,
  approvalCard,
  approvalCards,
  approvalFrame,
  approvalResult,
  canAccept,
  cardControls,
  decisionFrame,
  DEFAULT_TITLE,
  EMPTY_APPROVALS,
  EXPIRED,
  expiryLabel,
  isDecisionTaken,
  MAX_CARDS,
  MAX_TEXT_CHARS,
  MAX_TITLE_CHARS,
  nextRefreshDelay,
  REFRESH_MS,
  resultMessage,
  sameCard,
  TEXT_TOO_LONG,
  UNEXPECTED_RESULT,
  UNSHOWN,
  withApprovals,
  withConnection,
  withDecisionSent,
  withResult,
} from "../approvals";
import type { ApprovalsState } from "../approvals";
import type { ApprovalCard } from "../../types";

const NOW = 1_790_602_000_000;
const DIGEST = "3f9c0a1b2c3d4e5f60718293a4b5c6d7";
const RAW = {
  id: 905,
  title: "Appeler « prevision » (meteo) : {\"ville\": \"Lyon\"}",
  text: "Service : meteo\nOutil : prevision\nCe qui partira :\n{\n \"ville\": \"Lyon\"\n}",
  digest: DIGEST,
  blocked: "",
  expires_at: NOW + 4 * 60_000,
};
const card = (over: Partial<ApprovalCard> = {}): ApprovalCard => ({ ...(RAW as ApprovalCard), ...over });

describe("cartes d'accord — validation de la trame (ADR 0064)", () => {
  it("garde une carte valide telle quelle, empreinte et texte compris", () => {
    expect(approvalCards([RAW])).toEqual([RAW]);
    expect(approvalCard(RAW)?.digest).toBe(DIGEST);
    expect(approvalCard(RAW)?.text).toBe(RAW.text);
  });

  it("écarte un identifiant qui n'est pas un entier > 0", () => {
    for (const id of [0, -3, 1.5, "905", null, undefined, NaN, Infinity, 2 ** 60]) {
      expect(approvalCard({ ...RAW, id })).toBeNull();
    }
  });

  it("écarte une empreinte qui n'est pas de l'hexadécimal minuscule (128 au plus)", () => {
    expect(approvalCard({ ...RAW, digest: "3F9C" })).toBeNull();
    expect(approvalCard({ ...RAW, digest: "3f9c…" })).toBeNull();
    expect(approvalCard({ ...RAW, digest: "<b>" })).toBeNull();
    expect(approvalCard({ ...RAW, digest: "a".repeat(129) })).toBeNull();
    expect(approvalCard({ ...RAW, digest: 42 })).toBeNull();
    expect(approvalCard({ ...RAW, digest: "a".repeat(128) })?.digest).toBe("a".repeat(128));
    // vide : rien n'a pu être montré — la carte reste, seul le refus est possible
    expect(approvalCard({ ...RAW, digest: "" })?.digest).toBe("");
  });

  it("écarte un champ texte du mauvais type, une échéance qui n'est ni un nombre ni null", () => {
    expect(approvalCard({ ...RAW, title: 3 })).toBeNull();
    expect(approvalCard({ ...RAW, text: { html: "<script>" } })).toBeNull();
    expect(approvalCard({ ...RAW, blocked: true })).toBeNull();
    expect(approvalCard({ ...RAW, expires_at: "demain" })).toBeNull();
    expect(approvalCard({ ...RAW, expires_at: -1 })).toBeNull();
    expect(approvalCard({ ...RAW, expires_at: NaN })).toBeNull();
    expect(approvalCard({ ...RAW, expires_at: null })?.expires_at).toBeNull();
    expect(approvalCard({ ...RAW, expires_at: undefined })?.expires_at).toBeNull();
  });

  it("borne les chaînes : titre coupé, titre vide remplacé", () => {
    const long = approvalCard({ ...RAW, title: "x".repeat(MAX_TITLE_CHARS + 50) })!;
    expect(long.title.length).toBe(MAX_TITLE_CHARS);
    expect(long.title.endsWith("…")).toBe(true);
    expect(approvalCard({ ...RAW, title: "  " })?.title).toBe(DEFAULT_TITLE);
    expect(approvalCard({ ...RAW, title: undefined })?.title).toBe(DEFAULT_TITLE);
  });

  it("un texte trop long pour être montré en entier bloque l'accord", () => {
    const c = approvalCard({ ...RAW, text: "y".repeat(MAX_TEXT_CHARS + 1) })!;
    expect(c.text.length).toBeLessThanOrEqual(MAX_TEXT_CHARS + 2);
    expect(c.blocked).toBe(TEXT_TOO_LONG);
    expect(canAccept(c, NOW)).toBe(false);
  });

  it("une liste : invalides écartés, doublons ignorés, bornée ; autre chose qu'un tableau → vide", () => {
    const cards = approvalCards([null, 3, "x", { ...RAW, id: 0 }, RAW, { ...RAW, title: "doublon" }, { ...RAW, id: 906 }]);
    expect(cards.map((c) => c.id)).toEqual([905, 906]);
    expect(cards[0].title).toBe(RAW.title);
    const many = Array.from({ length: MAX_CARDS + 10 }, (_, i) => ({ ...RAW, id: i + 1 }));
    expect(approvalCards(many)).toHaveLength(MAX_CARDS);
    expect(approvalCards(undefined)).toEqual([]);
    expect(approvalCards({ items: [RAW] })).toEqual([]);
  });

  it("sameCard : une empreinte changée n'est plus la même carte", () => {
    expect(sameCard(card(), card())).toBe(true);
    expect(sameCard(card(), card({ digest: "ab" }))).toBe(false);
    expect(sameCard(card(), card({ expires_at: null }))).toBe(false);
  });
});

describe("cartes d'accord — décider", () => {
  it("la trame porte l'identifiant, la décision et l'empreinte affichée", () => {
    expect(approvalFrame(card(), "accept")).toEqual({
      type: "approval", id: 905, decision: "accept", digest: DIGEST,
    });
    expect(approvalFrame(card(), "refuse")).toEqual({
      type: "approval", id: 905, decision: "refuse", digest: DIGEST,
    });
  });

  it("bloquée, expirée, ou rien de montrable → on ne peut pas accepter, et on dit pourquoi", () => {
    expect(canAccept(card(), NOW)).toBe(true);
    expect(acceptRefusal(card(), NOW)).toBe("");

    const blocked = card({ blocked: "l'outil a changé" });
    expect(canAccept(blocked, NOW)).toBe(false);
    expect(acceptRefusal(blocked, NOW)).toContain("l'outil a changé");

    const expired = card({ expires_at: NOW - 1 });
    expect(canAccept(expired, NOW)).toBe(false);
    expect(acceptRefusal(expired, NOW)).toBe(EXPIRED);
    // pile à l'échéance : déjà trop tard
    expect(canAccept(card({ expires_at: NOW }), NOW)).toBe(false);

    expect(acceptRefusal(card({ digest: "" }), NOW)).toBe(UNSHOWN);
    expect(acceptRefusal(card({ text: "" }), NOW)).toBe(UNSHOWN);
    expect(canAccept(card({ expires_at: null }), NOW)).toBe(true);
  });

  it("l'échéance en mots", () => {
    const at = (ms: number | null) => expiryLabel(card({ expires_at: ms === null ? null : NOW + ms }), NOW);
    expect(at(null)).toBe("");
    expect(at(4 * 60_000)).toBe("expire dans 4 min");
    expect(at(3 * 60_000 + 10_000)).toBe("expire dans 4 min");
    expect(at(30_000)).toBe("expire dans moins d'une minute");
    expect(at(90 * 60_000)).toBe("expire dans 1 h 30");
    expect(at(2 * 3600_000)).toBe("expire dans 2 h");
    expect(at(3 * 86_400_000)).toBe("expire dans 3 jours");
    expect(at(0)).toBe("expirée");
    expect(at(-5_000)).toBe("expirée");
  });

  it("le minuteur : 30 s au plus, plus tôt si une carte expire avant, aucun sans échéance à venir", () => {
    expect(nextRefreshDelay([], NOW)).toBeNull();
    expect(nextRefreshDelay([card({ expires_at: null })], NOW)).toBeNull();
    expect(nextRefreshDelay([card({ expires_at: NOW - 1 })], NOW)).toBeNull();
    expect(nextRefreshDelay([card()], NOW)).toBe(REFRESH_MS);
    const soon = nextRefreshDelay([card(), card({ id: 2, expires_at: NOW + 5_000 })], NOW)!;
    expect(soon).toBeGreaterThan(5_000);
    expect(soon).toBeLessThan(REFRESH_MS);
  });
});

describe("cartes d'accord — le sort d'une décision", () => {
  it("chaque statut a sa phrase française", () => {
    for (const s of ["approved", "rejected", "unknown", "changed", "blocked", "expired", "forbidden"]) {
      expect(resultMessage(s)).not.toBe(UNEXPECTED_RESULT);
    }
    expect(resultMessage("approved")).toContain("Accepté");
    expect(resultMessage("rejected")).toContain("Refusé");
    expect(resultMessage("changed")).toContain("relis la carte");
  });

  it("un statut inconnu n'est jamais un succès", () => {
    for (const s of ["ok", "success", "accepted", "toString", "constructor", "", undefined, 1]) {
      expect(resultMessage(s)).toBe(UNEXPECTED_RESULT);
      expect(isDecisionTaken(s)).toBe(false);
    }
    expect(isDecisionTaken("approved")).toBe(true);
    expect(isDecisionTaken("rejected")).toBe(true);
    expect(isDecisionTaken("changed")).toBe(false);
  });

  it("une trame approval_result illisible est ignorée", () => {
    expect(approvalResult({ type: "approval_result", id: 905, status: "approved" }))
      .toEqual({ id: 905, status: "approved" });
    expect(approvalResult({ id: "905", status: "approved" })).toBeNull();
    expect(approvalResult({ id: 905 })).toBeNull();
    expect(approvalResult({ id: 905, status: "x".repeat(100) })).toBeNull();
    expect(approvalResult(null)).toBeNull();
  });
});

describe("cartes d'accord — l'état de la bande", () => {
  const open = (): ApprovalsState => withConnection(EMPTY_APPROVALS, "connected");

  it("chaque (re)connexion repart d'une liste vide : le serveur ne renvoie que s'il y a des cartes", () => {
    let s = withApprovals(open(), [RAW]);
    s = withDecisionSent(s, 905);
    expect(s.cards).toHaveLength(1);
    // coupée : les cartes restent, boutons éteints, la décision en vol est oubliée
    s = withConnection(s, "disconnected");
    expect(s.cards).toHaveLength(1);
    expect(s.sent).toEqual([]);
    expect(cardControls(s, s.cards[0], NOW)).toEqual({ accept: false, refuse: false, sending: false });
    s = withConnection(s, "reconnecting");
    expect(s.cards).toHaveLength(1);
    // rouverte : plus rien tant que le serveur n'a rien dit
    s = withConnection(s, "connected");
    expect(s).toEqual({ cards: [], sent: [], connected: true });
  });

  it("refusée (4401) : plus rien ne peut être décidé, les cartes s'en vont", () => {
    const s = withConnection(withApprovals(open(), [RAW]), "unauthorized");
    expect(s.cards).toEqual([]);
    expect(s.connected).toBe(false);
  });

  it("une trame approvals remplace la liste entière ; une carte absente est partie", () => {
    let s = withApprovals(open(), [RAW, { ...RAW, id: 906 }]);
    expect(s.cards.map((c) => c.id)).toEqual([905, 906]);
    s = withApprovals(s, [{ ...RAW, id: 906 }]);
    expect(s.cards.map((c) => c.id)).toEqual([906]);
    s = withApprovals(s, []);
    expect(s.cards).toEqual([]);
  });

  it("une décision partie éteint les deux boutons jusqu'à la réponse ou la liste suivante", () => {
    let s = withApprovals(open(), [RAW, { ...RAW, id: 906 }]);
    expect(cardControls(s, s.cards[0], NOW)).toEqual({ accept: true, refuse: true, sending: false });
    s = withDecisionSent(s, 905);
    expect(cardControls(s, s.cards[0], NOW)).toEqual({ accept: false, refuse: false, sending: true });
    // l'autre carte reste décidable
    expect(cardControls(s, s.cards[1], NOW).accept).toBe(true);
    expect(decisionFrame(s, 905, "refuse", NOW)).toBeNull();
    expect(withResult(s, 905).sent).toEqual([]);
    expect(withApprovals(s, [RAW]).sent).toEqual([]);
  });

  it("decisionFrame : seulement ce que les boutons permettent", () => {
    const s = withApprovals(open(), [RAW, { ...RAW, id: 907, blocked: "plus servi" }]);
    expect(decisionFrame(s, 905, "accept", NOW)).toEqual({
      type: "approval", id: 905, decision: "accept", digest: DIGEST,
    });
    // bloquée : refuser oui, accepter non
    expect(decisionFrame(s, 907, "accept", NOW)).toBeNull();
    expect(decisionFrame(s, 907, "refuse", NOW)?.decision).toBe("refuse");
    // expirée entre deux peintures
    expect(decisionFrame(s, 905, "accept", RAW.expires_at)).toBeNull();
    expect(decisionFrame(s, 905, "refuse", RAW.expires_at)?.decision).toBe("refuse");
    // une carte qui n'est plus dans la liste, une connexion fermée
    expect(decisionFrame(s, 999, "refuse", NOW)).toBeNull();
    expect(decisionFrame(withConnection(s, "disconnected"), 905, "refuse", NOW)).toBeNull();
  });
});
