import { describe, expect, it } from "vitest";
import type { MailFull } from "../../api/mail";
import { openGone, openShows, pageShows, readerChange, viewGone } from "./live";

const named = (...boxes: string[]) => new Set(boxes);

const mail: MailFull = {
  ref: "pro:<claire@x>",
  box: "pro",
  folder: "INBOX",
  from: { name: "Claire Dubois", address: "claire@x.test" },
  to: [],
  subject: "Présentation",
  snippet: "Bonjour",
  date: 1_000,
  seen: false,
  flagged: false,
  answered: false,
  attachments: [],
  html: false,
  bulk: false,
  her: { noticed: true, important: false, needs_reply: true, read: false, how: "", draft: "", asked: false },
  cc: [],
  reply_to: "",
  in_reply_to: "",
  body: "Un chiffre dès la slide 2 ?",
  complete: true,
  sent: false,
  images: { remote: false, shown: false },
  work: null,
};

describe("Mail face au direct : la page de messages affichée (§ 2 bis, `mail`)", () => {
  it("une vue de toutes tes boîtes relit, quelle que soit la boîte nommée", () => {
    for (const kind of ["inbox", "flagged", "needs_reply"] as const) expect(pageShows({ kind }, named("perso"))).toBe(true);
    expect(pageShows({ kind: "sent", box: "" }, named("perso"))).toBe(true);
  });

  it("une boîte ne relit que si elle est nommée (ou tout le domaine)", () => {
    const pro = { kind: "folder" as const, box: "pro", folder: "INBOX" };
    expect(pageShows(pro, named("pro"))).toBe(true);
    expect(pageShows(pro, named("perso"))).toBe(false);
    expect(pageShows(pro, null)).toBe(true);
    expect(pageShows({ kind: "sent", box: "pro" }, named("perso"))).toBe(false);
    expect(pageShows({ kind: "sent", box: "pro" }, named("pro", "perso"))).toBe(true);
  });

  it("ses brouillons ont leur sujet à eux (`mail.drafts`)", () => {
    expect(pageShows({ kind: "drafts", box: "" }, null)).toBe(false);
    expect(pageShows({ kind: "drafts", box: "pro" }, named("pro"))).toBe(false);
  });

  it("le mail ouvert relit s'il est dans une boîte nommée", () => {
    expect(openShows(mail, named("pro"))).toBe(true);
    expect(openShows(mail, named("perso"))).toBe(false);
    expect(openShows(mail, null)).toBe(true);
    expect(openShows(null, null)).toBe(false);
  });
});

describe("ce que le direct change de la liseuse (readerChange)", () => {
  it("rien de changé : rien ne se repeint", () => {
    expect(readerChange(mail, { ...mail, her: { ...mail.her! } })).toBe("same");
  });

  it("lu, suivi, où elle en est, la demande : repeints en place (la réponse commencée, le cadre, le défilement restent)", () => {
    expect(readerChange(mail, { ...mail, seen: true })).toBe("parts");
    expect(readerChange(mail, { ...mail, flagged: true })).toBe("parts");
    expect(readerChange(mail, { ...mail, work: { step: "thinking", label: "", since: 2, started: 1 } })).toBe("parts");
    expect(readerChange(mail, { ...mail, her: { ...mail.her!, asked: true } })).toBe("parts");
  });

  it("ce que la liseuse montre d'autre la redessine : une étiquette, son brouillon, ce qu'elle en sait, le texte complet", () => {
    expect(readerChange(mail, { ...mail, answered: true })).toBe("whole");
    expect(readerChange(mail, { ...mail, her: { ...mail.her!, draft: "d1" } })).toBe("whole");
    expect(readerChange(mail, { ...mail, her: { ...mail.her!, summary: "Claire valide." } })).toBe("whole");
    expect(readerChange({ ...mail, complete: false }, mail)).toBe("whole");
    expect(readerChange({ ...mail, her: null }, mail)).toBe("whole");
    expect(readerChange(mail, { ...mail, seen: true, answered: true })).toBe("whole");
  });
});

describe("Mail face au direct : une boîte qui n'est plus à toi (§ 2 bis, son partage retiré)", () => {
  const folder = (name: string) => ({ name, label: name, role: name === "INBOX" ? "inbox" : "", polled: true, total: 0, unseen: 0 });
  const boxes = [{ key: "pro", folders: [folder("INBOX"), folder("Factures")] }, { key: "vide", folders: [] }];

  it("la vue d'une boîte partie, de ses envoyés, de ses brouillons, d'un dossier disparu : retour à toutes les réceptions", () => {
    expect(viewGone({ kind: "folder", box: "anna", folder: "INBOX" }, boxes)).toBe(true);
    expect(viewGone({ kind: "sent", box: "anna" }, boxes)).toBe(true);
    expect(viewGone({ kind: "drafts", box: "anna" }, boxes)).toBe(true);
    expect(viewGone({ kind: "folder", box: "pro", folder: "Archives" }, boxes)).toBe(true);
  });

  it("une vue qui tient encore reste ; une boîte dont les dossiers ne se disent pas garde la sienne", () => {
    expect(viewGone({ kind: "folder", box: "pro", folder: "Factures" }, boxes)).toBe(false);
    expect(viewGone({ kind: "sent", box: "pro" }, boxes)).toBe(false);
    expect(viewGone({ kind: "folder", box: "vide", folder: "INBOX" }, boxes)).toBe(false);
    for (const kind of ["inbox", "flagged", "needs_reply"] as const) expect(viewGone({ kind }, [])).toBe(false);
    expect(viewGone({ kind: "sent", box: "" }, [])).toBe(false);
    expect(viewGone({ kind: "drafts", box: "" }, [])).toBe(false);
  });

  it("le mail ouvert d'une boîte partie se ferme ; rien d'ouvert, rien à fermer", () => {
    expect(openGone(mail, [{ key: "perso" }])).toBe(true);
    expect(openGone(mail, [{ key: "pro" }])).toBe(false);
    expect(openGone(null, [])).toBe(false);
  });
});
