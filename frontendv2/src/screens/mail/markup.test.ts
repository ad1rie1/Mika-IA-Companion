import { describe, expect, it } from "vitest";
import type { MailBox, MailDraft, MailFull, MailRow, SentMail } from "../../api/mail";
import { caps } from "./format";
import { boxesPane, boxViews, composeForm, countSpan, draftRow, draftState, folderView, inlineReply, listFilters, pieceChips, listFoot, listHead, listHolds, mailRow, moveTargets, parseView, readerDraft, readerMail, readerTidy, sentRow, viewHolds, viewKey, type ReaderView, type RowView, type Shown } from "./markup";

const NOW = new Date(2026, 10, 4, 15, 0).getTime();

function box(key: string, level: MailBox["level"], owner = ""): MailBox {
  return {
    key,
    name: key === "pro" ? "Boîte Pro" : "Personnel",
    address: `${key}@exemple.test`,
    level,
    ready: true,
    can_send: true,
    enabled: true,
    signature: "",
    last_poll: 0,
    error: "",
    drafts_waiting: 1,
    owner_name: owner,
    folders: [
      { name: "INBOX", label: "Réception", role: "inbox", polled: true, total: 3, unseen: 2 },
      { name: "Envoyés", label: "Envoyés", role: "sent", polled: false, total: 0, unseen: 0 },
      { name: "Brouillons", label: "Brouillons", role: "drafts", polled: false, total: 0, unseen: 0 },
      { name: "Archives", label: "Archives", role: "archive", polled: false, total: 0, unseen: 0 },
    ],
  };
}

const row: MailRow = {
  ref: "pro:<claire@x>",
  box: "pro",
  folder: "INBOX",
  from: { name: "Claire Dubois", address: "claire@x.test" },
  to: [],
  subject: "Re: Présentation <jeudi>",
  snippet: "Bonjour",
  date: NOW - 3600_000,
  seen: false,
  flagged: true,
  answered: false,
  attachments: 1,
  html: false,
  bulk: false,
  her: { noticed: true, important: true, needs_reply: true, read: true, how: "", draft: "d1", asked: false },
};

const full: MailFull = {
  ...row,
  attachments: [{ part: "0", name: "devis.pdf", mime: "application/pdf", size: 212_000 }],
  cc: [],
  reply_to: "",
  in_reply_to: "",
  body: "Bonjour Adrien,\n\nUn chiffre dès la slide 2 ?",
  complete: true,
  sent: false,
  images: { remote: false, shown: false },
  her: { ...row.her!, summary: "Claire valide la trame." },
};

function view(level: MailBox["level"], extra: Partial<ReaderView> = {}): ReaderView {
  const [bv] = boxViews([box("pro", level, level === "proprietaire" ? "" : "Adrien Moreau")], new Set());
  return { now: NOW, box: bv, caps: caps(level), frame: "http://x/frame", imagesOnce: false, draft: null, asked: false, composer: "", mobile: false, ...extra };
}

describe("les vues de la colonne", () => {
  it("se disent et se relisent", () => {
    for (const key of ["inbox", "flagged", "needs_reply", "sent", "sent:pro", "drafts", "drafts:pro", "folder:pro:INBOX", "folder:pro:A:B"]) {
      expect(viewKey(parseView(key))).toBe(key);
    }
    expect(parseView("n'importe quoi")).toEqual({ kind: "inbox" });
  });
  it("« Envoyés » d'une boîte montre ce qui en est parti, « Brouillons » ses brouillons à elle", () => {
    const b = box("pro", "proprietaire");
    expect(folderView(b, b.folders[1])).toEqual({ kind: "sent", box: "pro" });
    expect(folderView(b, b.folders[2])).toEqual({ kind: "drafts", box: "pro" });
    expect(folderView(b, b.folders[0])).toEqual({ kind: "folder", box: "pro", folder: "INBOX" });
  });
  it("une boîte partagée se montre à son nom, avec son niveau, à part des tiennes", () => {
    const html = boxesPane({
      boxes: boxViews([box("pro", "lire", "Adrien Moreau"), box("perso", "proprietaire")], new Set(["pro", "perso"])),
      view: "inbox",
      unseen: 4,
      waiting: 1,
      plugged: true,
      error: "",
    });
    expect(html.indexOf("Personnel")).toBeLessThan(html.indexOf("Partagée avec toi"));
    expect(html).toContain("Boîte d&#39;Adrien");
    expect(html).toContain("lecture");
    // un dossier qu'elle ne relève pas se montre éteint ; « Envoyés » et « Brouillons » sont les vues de l'API
    expect(html).toMatch(/class="unpolled"[^>]*data-vue="folder:perso:Archives"/);
    expect(html).toContain('data-vue="sent:perso"');
  });
});

describe("la liste", () => {
  it("dit ce qu'elle en a fait, à part de ton non-lu", () => {
    const html = mailRow(row, { now: NOW, selected: "", checked: new Set(), many: true, boxes: new Map(boxViews([box("pro", "proprietaire")], new Set()).map((b) => [b.box.key, b])) }, true);
    expect(html).toContain("unread");
    expect(html).toContain("important");
    expect(html).toContain("réponse attendue");
    expect(html).toContain("lu par elle");
    expect(html).toContain("brouillon prêt");
    expect(html).toContain("Boîte Pro");
    expect(html).toContain("Re: Présentation &lt;jeudi&gt;");
    expect(html).toContain("data-coche");
  });
  it("sans droit de ranger, pas de case à cocher", () => {
    const html = mailRow(row, { now: NOW, selected: "", checked: new Set(), many: false, boxes: new Map() }, false);
    expect(html).not.toContain("data-coche");
  });
  it("la pagination, quand il y a plus d'une page", () => {
    expect(listFoot(20, 1, 25)).toBe("");
    expect(listFoot(60, 2, 25)).toContain("26–50 sur 60");
  });
});

describe("la liseuse respecte le niveau (ADR 0188)", () => {
  it("la sienne : répondre, transférer, préremplir, ranger, et la réponse en place", () => {
    const html = readerMail(full, view("proprietaire"), (p) => `f${p}`);
    for (const act of ["repondre", "tous", "transferer", "preremplir", "archiver", "lu", "suivre", "corbeille"]) expect(html).toContain(`data-act="${act}"`);
    expect(html).toContain("rd-reply-stub");
    expect(html).not.toContain("rd-shared");
    expect(html).toContain("« Claire valide la trame. »");
    expect(html).toContain('href="f0"');
  });
  it("lire : ni écrire, ni ranger, ni préremplir ; le bandeau le dit", () => {
    const html = readerMail(full, view("lire"), (p) => p);
    expect(html).not.toMatch(/data-act="(repondre|tous|transferer|preremplir|archiver|corbeille)"/);
    expect(html).not.toContain("rd-reply-stub");
    expect(html).toContain("rd-shared");
    expect(html).toContain("Boîte d&#39;Adrien Moreau");
  });
  it("préparer : seulement « Préremplir avec Mika »", () => {
    const html = readerMail(full, view("preparer"), (p) => p);
    expect(html).toContain('data-act="preremplir"');
    expect(html).not.toMatch(/data-act="(repondre|tous|transferer|archiver|corbeille)"/);
  });
  it("une réponse demandée : « Elle s'y met… »", () => {
    expect(readerMail(full, view("proprietaire", { asked: true }), (p) => p)).toContain("Elle s'y met");
  });
  it("une copie revenue de ton propre mail : on y répond, à ses destinataires ; elle n'y prépare rien", () => {
    const mine: MailFull = {
      ...full,
      from: { name: "Adrien Moreau", address: "pro@exemple.test" },
      to: [{ name: "Léa Martin", address: "lea@x.test" }],
      sent: true,
      received: true,
    };
    const html = readerMail(mine, view("proprietaire"), (p) => p);
    expect(html).toContain('data-act="repondre"');
    expect(html).not.toContain('data-act="preremplir"');  // l'API refuse un mail parti de ta boîte (409)
    expect(html).toContain("Répondre à Léa…");  // pas « à Adrien » : la réponse ira à Léa
    expect(readerMail(full, view("proprietaire"), (p) => p)).toContain("Répondre à Claire…");
  });
  it("un mail HTML dans son cadre isolé, ses images distantes masquées jusqu'à ce qu'on les permette", () => {
    const html = readerMail({ ...full, html: true, images: { remote: true, shown: false } }, view("proprietaire", { owner: true }), (p) => p);
    expect(html).toContain('sandbox="allow-popups allow-popups-to-escape-sandbox allow-same-origin"');
    expect(html).toContain('data-images="fois"');
    expect(html).toContain('data-images="toujours"');
    const once = readerMail({ ...full, html: true, images: { remote: true, shown: false } }, view("lire", { imagesOnce: true }), (p) => p);
    expect(once).not.toContain('data-images="fois"');
  });
  it("« Toujours pour cet expéditeur » vaut pour tout le serveur : une de ses propriétaires seulement", () => {
    const masked = { ...full, html: true, images: { remote: true, shown: false } };
    // sa boîte à elle, mais pas une de ses propriétaires : « cette fois » seulement
    const html = readerMail(masked, view("proprietaire", { owner: false }), (p) => p);
    expect(html).toContain('data-images="fois"');
    expect(html).not.toContain('data-images="toujours"');
    expect(readerMail({ ...masked, images: { remote: true, shown: true } }, view("proprietaire"), (p) => p)).not.toContain('data-images="jamais"');
    // une propriétaire, sur une boîte qu'on lui partage seulement en lecture : pas davantage
    expect(readerMail(masked, view("lire", { owner: true }), (p) => p)).not.toContain('data-images="toujours"');
    expect(readerMail({ ...masked, images: { remote: true, shown: true } }, view("proprietaire", { owner: true }), (p) => p)).toContain('data-images="jamais"');
  });
  it("un mail parti de sa boîte se transfère, il ne se répond pas (l'API refuse)", () => {
    const html = readerMail({ ...full, sent: true }, view("proprietaire", { draft }), (p) => p);
    expect(html).toContain('data-act="transferer"');
    expect(html).not.toMatch(/data-act="(repondre|tous|reprendre-brouillon|preremplir)"/);
    expect(html).not.toContain("rd-reply-stub");
    expect(html).toContain("parti de ta boîte");
  });
});

describe("joindre et copier en cachette (ADR 0214)", () => {
  const blank = { boxes: [], box: "", to: [], cc: [], subject: "", body: "", attachments: 0, quote: null };
  it("la fenêtre d'un mail nouveau propose la Cci et le dépôt ; la retouche d'un brouillon, ni l'un ni l'autre", () => {
    const written = composeForm({ kind: "new", ...blank });
    expect(written).toContain("data-bcc");
    expect(written).toContain('data-rcpt="bcc"');
    expect(written).toContain("data-depot");
    expect(written).toContain('type="file" multiple hidden data-fichiers');
    expect(written).toContain("25 Mo par pièce");
    const edited = composeForm({ kind: "edit", ...blank });
    expect(edited).not.toContain("data-bcc");
    expect(edited).not.toContain("data-depot");
    expect(edited).not.toContain("data-fichiers");
  });
  it("une pièce se montre à son nom, échappé, avec sa taille, et se retire à son rang", () => {
    const html = pieceChips([{ name: "a.pdf", size: 2048 }, { name: "<b>.png", size: 10 }]);
    expect(html).toContain('data-retirer-piece="0"');
    expect(html).toContain('data-retirer-piece="1"');
    expect(html).toContain("&lt;b&gt;.png");
    expect(html).not.toContain("<b>.png");
    expect(html).toContain("2 Ko");
  });
  it("une réponse a son bouton « Joindre », ses pièces et sa Cci", () => {
    const start = { all: false, to: [], cc: [], showCc: false, bcc: [], subject: "Re: x", body: "", quote: true, fromDraft: "", filled: "", sending: false, error: "" };
    const closed = inlineReply({ ...start, showBcc: false, files: [] }, null, true);
    expect(closed).toContain("data-joindre");
    expect(closed).toContain('data-act="cci"');
    expect(closed).not.toContain('data-rcpt="bcc"');
    const open = inlineReply({ ...start, showBcc: true, files: [new File(["x"], "plan.pdf")] }, null, true);
    expect(open).toContain('data-rcpt="bcc"');
    expect(open).not.toContain('data-act="cci"');
    expect(open).toContain("plan.pdf");
  });
});

describe("écrire, dans les bornes de l'API", () => {
  it("le message et l'objet ont leur maxlength, et le compte du message se montre près de sa borne", () => {
    const reply = inlineReply({ all: false, to: [], cc: [], showCc: false, bcc: [], showBcc: false, files: [], subject: "Re: x", body: "x".repeat(19_000), quote: true, fromDraft: "", filled: "", sending: false, error: "" }, null, true);
    expect(reply).toContain('maxlength="20000"');
    expect(reply).toMatch(/data-limit="20000"[^>]*>19\u202f000 \/ 20\u202f000</);
    const form = composeForm({ kind: "new", boxes: [], box: "", to: [], cc: [], subject: "", body: "", attachments: 0, quote: null });
    expect(form).toContain('data-objet value="" placeholder="Objet" maxlength="200"');
    expect(form).toContain('maxlength="20000"');
    expect(form).toMatch(/data-limit="20000" hidden>/);
    expect(countSpan("x".repeat(4000), 4000)).toContain(" full");
  });
});

const draft: MailDraft = {
  id: "d1",
  box: "pro",
  state: "attend",
  at: NOW - 60_000,
  decided_at: 0,
  by: "",
  note: "",
  in_reply_to: "pro:<claire@x>",
  original: { subject: "Re: Présentation", from: "Claire Dubois" },
  to: "claire@x.test",
  to_people: [{ name: "Claire Dubois", address: "claire@x.test" }],
  cc: "",
  subject: "Re: Présentation",
  body: "Bonjour Claire,\n\nLe [À COMPLÉTER : jour].",
  quote: true,
  edited: false,
  to_fill: true,
  preview: { sender: "Mika <pro@exemple.test>", to: "claire@x.test", cc: "", subject: "Re: Présentation", text: "Bonjour Claire,\n\nLe [À COMPLÉTER : jour].", digest: "abc", blocked: "il reste un passage à compléter" },
};

describe("ses brouillons", () => {
  it("exactement ce qui partira ; un « [À COMPLÉTER » bloque l'envoi et dit pourquoi", () => {
    const [bv] = boxViews([box("pro", "proprietaire")], new Set());
    const html = readerDraft(draft, { now: NOW, box: bv, caps: caps("proprietaire"), mobile: false });
    expect(html).toContain("Ce qui partira");
    expect(html).toContain("Mika &lt;pro@exemple.test&gt;");
    expect(html).toContain('<mark class="completer">[À COMPLÉTER : jour]</mark>');
    expect(html).toMatch(/data-decide="envoyer" disabled/);
    expect(html).toContain("il reste un passage à compléter");
    for (const d of ["refuser", "reprendre", "retoucher"]) expect(html).toContain(`data-decide="${d}"`);
  });
  it("une boîte qui n'est pas la tienne : on lit, le propriétaire décide", () => {
    const [bv] = boxViews([box("pro", "servir", "Adrien Moreau")], new Set());
    const html = readerDraft({ ...draft, to_fill: false, preview: { ...draft.preview!, blocked: "" } }, { now: NOW, box: bv, caps: caps("servir"), mobile: false });
    expect(html).not.toContain("data-decide");
    expect(html).toContain("Adrien Moreau");
  });
  it("décidé : son état, sa note", () => {
    expect(draftState({ state: "parti", edited: true })).toEqual(["ok", "parti · retouché par toi"]);
    expect(draftState({ state: "refuse", edited: false })).toEqual(["", "refusé"]);
    const html = readerDraft({ ...draft, state: "refuse", note: "trop sec", preview: null, decided_at: NOW }, { now: NOW, box: null, caps: caps("proprietaire"), mobile: false });
    expect(html).toContain("Note : « trop sec »");
    expect(html).not.toContain("data-decide");
  });
});

// ── audit du 2026-11-05 (lot L13) ──

function rows(boxes: MailBox[] = [box("pro", "proprietaire")]): RowView {
  return { now: NOW, selected: "", checked: new Set(), many: false, boxes: new Map(boxViews(boxes, new Set()).map((b) => [b.box.key, b])) };
}

describe("la colonne : un nom, un sens (ADR 0200)", () => {
  const pane = (boxes: MailBox[]) => boxesPane({ boxes: boxViews(boxes, new Set()), view: "inbox", unseen: 2, waiting: 0, plugged: true, error: "" });
  it("« Réponse attendue » dans la colonne ; « Où Mika est passée » reste un filtre de la liste", () => {
    const html = pane([box("pro", "proprietaire")]);
    expect(html).toContain('data-vue="needs_reply"');
    expect(html).toContain("Réponse attendue");
    expect(html).not.toContain("Où Mika est passée");
    expect(listFilters("")).toContain("Où Mika est passée");
  });
  it("une boîte partagée dit son niveau, et son non-lu à côté", () => {
    const html = pane([box("perso", "proprietaire"), box("pro", "lire", "Adrien Moreau")]);
    expect(html).toMatch(/lecture<\/span><span class="cnt" title="Non lus dans sa réception">2<\/span>/);
  });
});

describe("à qui l'on a écrit : des noms, l'adresse au survol", () => {
  it("Envoyés", () => {
    const s: SentMail = { ref: "pro:<s1>", box: "pro", to: [{ name: "Camille Durand", address: "camille.durand@example.test" }], cc: [], subject: "Dîner", snippet: "À samedi", date: NOW, by: "user_1", draft: "", attachments: 0 };
    const html = sentRow(s, rows());
    expect(html).toContain("À Camille Durand");
    expect(html).toContain('title="camille.durand@example.test"');
  });
  it("ses brouillons : le nom que la boîte connaît, sinon l'adresse", () => {
    expect(draftRow(draft, rows())).toContain("À Claire Dubois");
    expect(draftRow(draft, rows())).toContain('title="claire@x.test"');
    const bare = draftRow({ ...draft, to_people: [], preview: null }, rows());
    expect(bare).toContain("À claire@x.test");
  });
});

describe("la liseuse", () => {
  it("la réponse ouverte : « Préremplir avec Mika » une seule fois, dans sa barre", () => {
    const composer = inlineReply({ all: false, to: [], cc: [], showCc: false, bcc: [], showBcc: false, files: [], subject: "Re: x", body: "", quote: true, fromDraft: "", filled: "", sending: false, error: "" }, null, true);
    const html = readerMail(full, view("proprietaire", { composer }), (p) => p);
    expect(html.match(/data-act="preremplir"/g)).toHaveLength(1);
    expect(readerMail(full, view("proprietaire"), (p) => p).match(/data-act="preremplir"/g)).toHaveLength(1);
  });
  it("« Déplacer » dans la liseuse et sur la sélection (ADR 0200)", () => {
    expect(readerTidy(full)).toContain('data-act="deplacer"');
    expect(listHead("Réception", 3, 2)).toContain('data-groupe="move"');
    const b = box("pro", "proprietaire");
    // ses dossiers, sauf celui où il est, « Envoyés » et « Brouillons » (les vues de ce qui est parti et de ses brouillons)
    expect(moveTargets(b, "INBOX").map((f) => f.name)).toEqual(["Archives"]);
    expect(moveTargets(b, "Archives").map((f) => f.name)).toEqual(["INBOX"]);
  });
});

describe("la liseuse quitte une vue qui ne montre plus ce qu'elle lit", () => {
  const mail = (more: Partial<MailFull> = {}): Shown => ({ kind: "mail", mail: { ...full, ...more }, common: true });
  it("un brouillon reste dans « Ses brouillons », pas ailleurs", () => {
    const d: Shown = { kind: "draft", box: "pro" };
    expect(viewHolds({ kind: "drafts", box: "" }, "", d)).toBe(true);
    expect(viewHolds({ kind: "drafts", box: "pro" }, "", d)).toBe(true);
    expect(viewHolds({ kind: "drafts", box: "perso" }, "", d)).toBe(false);
    expect(viewHolds({ kind: "sent", box: "" }, "", d)).toBe(false);
  });
  it("un mail reçu : sa réception, son dossier, ses états — pas « Envoyés » ni « Ses brouillons »", () => {
    expect(viewHolds({ kind: "inbox" }, "", mail())).toBe(true);
    expect(viewHolds({ kind: "folder", box: "pro", folder: "INBOX" }, "", mail())).toBe(true);
    expect(viewHolds({ kind: "folder", box: "pro", folder: "Archives" }, "", mail())).toBe(false);
    expect(viewHolds({ kind: "flagged" }, "", mail())).toBe(true);
    expect(viewHolds({ kind: "flagged" }, "", mail({ flagged: false }))).toBe(false);
    expect(viewHolds({ kind: "needs_reply" }, "", mail({ her: { ...full.her!, read: false } }))).toBe(true);
    // lu par elle : jamais dans « Réponse attendue »
    expect(viewHolds({ kind: "needs_reply" }, "", mail())).toBe(false);
    expect(viewHolds({ kind: "needs_reply" }, "", mail({ her: { ...full.her!, needs_reply: false, read: false } }))).toBe(false);
    // le drapeau du serveur n'est pas le « lu » de la liste : lu dans un autre client, l'API peut encore le lister
    // (elle ne le sait qu'à la relève) ; c'est la liste chargée qui tranche
    expect(viewHolds({ kind: "needs_reply" }, "", mail({ seen: true, her: { ...full.her!, read: false } }))).toBe(true);
    expect(viewHolds({ kind: "sent", box: "" }, "", mail())).toBe(false);
    expect(viewHolds({ kind: "drafts", box: "" }, "", mail())).toBe(false);
    expect(viewHolds({ kind: "sent", box: "pro" }, "", mail({ sent: true }))).toBe(true);
  });
  it("le filtre compte, et une boîte partagée en lecture n'est pas dans tes vues communes", () => {
    expect(viewHolds({ kind: "inbox" }, "unread", mail({ seen: true }))).toBe(false);
    expect(viewHolds({ kind: "inbox" }, "noticed", mail())).toBe(true);
    expect(viewHolds({ kind: "inbox" }, "", { kind: "mail", mail: full, common: false })).toBe(false);
    expect(viewHolds({ kind: "folder", box: "pro", folder: "INBOX" }, "", { kind: "mail", mail: full, common: false })).toBe(true);
    expect(viewHolds({ kind: "inbox" }, "", { kind: "mail", mail: null, common: true })).toBe(false);
  });
  it("la liste chargée tranche : à gauche, il reste ; absent d'une liste entière, il se ferme", () => {
    const rows = [{ ref: "pro:<a@x>" }, { ref: "pro:<b@x>" }];
    expect(listHolds("pro:<b@x>", rows, 2)).toBe(true);
    expect(listHolds("pro:<b@x>", rows, 40)).toBe(true);
    // remis en non-lu après lecture : l'API ne le liste plus, quoi qu'en dise son drapeau
    expect(listHolds("pro:<c@x>", rows, 2)).toBe(false);
    expect(listHolds("pro:<c@x>", [], 0)).toBe(false);
    // d'autres pages : peut-être plus loin, `viewHolds` a jugé
    expect(listHolds("pro:<c@x>", rows, 40)).toBe(null);
  });
});
