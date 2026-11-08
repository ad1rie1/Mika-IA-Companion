import { describe, expect, it } from "vitest";
import type { Conversation, OwnPending, Reply, TeamsAccount, TeamsMessage, Thread } from "../../api/teams";
import { ofName } from "../../shared/names";
import { caps, ofName as mailOfName } from "../mail/format";
import {
  authorLabel,
  dayLabel,
  fromHer,
  fromYou,
  messageHtml,
  modeLabel,
  ownBubbles,
  pendingNote,
  replyHash,
  replyState,
  retouched,
  stillSentHere,
  threadCards,
  threadMarks,
  withoutSent,
} from "./format";
import { conversationRow, dock, infoPane, repliesTable, replyCard, threadBody, type ThreadView } from "./markup";

const NOW = new Date(2026, 10, 4, 15, 0).getTime();
const MIN = 60_000;

function reply(extra: Partial<Reply> = {}): Reply {
  return {
    id: "r1",
    account: "principal",
    conversation: "19:marc",
    title: "Marc Delmas",
    in_reply_to: "t1",
    state: "attend",
    mode: "validation",
    at: NOW - 5 * MIN,
    decided_at: 0,
    by: "",
    note: "",
    asked: false,
    edited: false,
    expires: 0,
    body: "Oui, 15 h me va.",
    sent_text: "",
    to_fill: false,
    preview: { text: "Oui, 15 h me va.\n— Mika", digest: "d1", blocked: "" },
    ...extra,
  };
}

function msg(extra: Partial<TeamsMessage>): TeamsMessage {
  return { ref: "t", author: "Marc Delmas", author_id: "8:marc", at: NOW - 30 * MIN, text: "Salut", own: false, mentions_me: false, ...extra };
}

function account(extra: Partial<TeamsAccount> = {}): TeamsAccount {
  return {
    key: "principal",
    name: "Atelier",
    level: "proprietaire",
    enabled: true,
    last_batch: NOW - MIN,
    self_name: "Adrien Moreau",
    extension_key: null,
    drafts_waiting: 0,
    owner_name: "",
    ...extra,
  };
}

/** Léa, sur le compte Atelier qu'Adrien lui partage. */
function shared(level: TeamsAccount["level"] = "lire", extra: Partial<TeamsAccount> = {}): TeamsAccount {
  return account({ level, owner_name: "Adrien Moreau", ...extra });
}

const view = (level: string, extra: Partial<ThreadView> = {}): ThreadView => ({
  now: NOW,
  selfName: "Adrien Moreau",
  caps: caps(level),
  owner: level === "proprietaire" ? "" : "Adrien Moreau",
  // le compte de la discussion : le tien, ou celui qu'Adrien te partage à ce niveau
  account: level === "proprietaire" ? account() : shared(level as TeamsAccount["level"]),
  editing: "",
  pending: [],
  ...extra,
});

describe("l'état de ses réponses, en mots", () => {
  it("chaque état", () => {
    expect(replyState(reply())).toEqual(["warn", "attend ton accord"]);
    expect(replyState(reply({ state: "en_file" }))[1]).toBe("en file");
    expect(replyState(reply({ state: "pose" }))[1]).toBe("posée dans Teams");
    expect(replyState(reply({ state: "parti", sent_text: "Oui, 15 h me va.\n— Mika" }))).toEqual(["ok", "partie"]);
    expect(replyState(reply({ state: "parti", sent_text: "Plutôt 16 h ?" }))).toEqual(["ok", "partie · retouchée"]);
    expect(replyState(reply({ state: "parti", edited: true }))[1]).toBe("partie · retouchée");
    expect(replyState(reply({ state: "inutilise" }))[1]).toBe("pas servie");
    expect(replyState(reply({ state: "refuse" }))[1]).toBe("refusée");
    expect(replyState(reply({ state: "expire" }))[1]).toBe("expirée");
  });
  it("une carte d'accord dit jusqu'à quand", () => {
    expect(replyState(reply({ expires: new Date(2026, 10, 4, 15, 42).getTime() }))[1]).toBe("attend ton accord · jusqu'à 15:42");
  });
  it("retouchée : ce qui est parti n'est pas ce qu'elle avait écrit", () => {
    expect(retouched({ edited: false, sent_text: "", body: "x" })).toBe(false);
    expect(retouched({ edited: false, sent_text: "Oui, 15 h me va. — Mika", body: "Oui, 15 h me va." })).toBe(false);
    expect(modeLabel("brouillon")).toBe("brouillon");
    expect(modeLabel("validation")).toBe("ton accord");
  });
});

describe("le fil", () => {
  it("les repères de jour, et la suite d'un même auteur", () => {
    const yesterday = new Date(2026, 10, 3, 21, 55).getTime();
    const marks = threadMarks(
      [msg({ at: yesterday }), msg({ at: yesterday + MIN }), msg({ at: NOW - 30 * MIN }), msg({ at: NOW - 29 * MIN, own: true, author: "Adrien", author_id: "8:a" })],
      NOW,
    );
    expect(marks.map((m) => m.day)).toEqual(["Hier", "", "Aujourd'hui", ""]);
    expect(marks.map((m) => m.suite)).toEqual([false, true, false, false]);
    expect(dayLabel(new Date(2026, 10, 2, 10, 0).getTime(), NOW)).toBe("lundi 2 novembre");
    expect(dayLabel(new Date(2025, 11, 1, 10, 0).getTime(), NOW)).toBe("lundi 1er décembre 2025");
  });
  it("ta mention en valeur, le reste échappé", () => {
    expect(messageHtml("@Adrien tu peux <valider> ?", "Adrien Moreau", true)).toBe('<span class="tm-at">@Adrien</span> tu peux &lt;valider&gt; ?');
    expect(messageHtml("@Adrien Moreau ok", "Adrien Moreau", true)).toBe('<span class="tm-at">@Adrien Moreau</span> ok');
    expect(messageHtml("@Adrien ok", "Adrien Moreau", false)).toBe("@Adrien ok");
  });
  it("ce que tu as envoyé et qu'elle avait préparé : « rédigé avec Mika »", () => {
    const parti = reply({ state: "parti", sent_text: "Oui, 15 h me va." });
    expect(fromHer({ own: true, text: "Oui, 15 h me va." }, [parti])).toBe(true);
    expect(fromHer({ own: false, text: "Oui, 15 h me va." }, [parti])).toBe(false);
    expect(fromHer({ own: true, text: "Autre chose" }, [parti])).toBe(false);
  });
});

describe("ses réponses en carte, selon le niveau", () => {
  it("la tienne : refuser, la reprendre, retoucher, envoyer d'ici", () => {
    const html = replyCard(reply(), view("proprietaire"));
    for (const k of ["refuser", "reprendre", "retoucher", "envoyer"]) expect(html).toContain(`data-rep="${k}"`);
    expect(html).toContain("— Mika"); // exactement ce qui partira, signature comprise
  });
  it("bloquée par un « [À COMPLÉTER » : pas d'envoi, et pourquoi", () => {
    const html = replyCard(reply({ to_fill: true, preview: { text: "Le [À COMPLÉTER : jour]", digest: "d", blocked: "un passage à compléter" } }), view("proprietaire"));
    expect(html).toMatch(/data-rep="envoyer" disabled/);
    expect(html).toContain("un passage à compléter");
  });
  it("un compte partagé : on lit, le propriétaire décide", () => {
    const html = replyCard(reply(), view("servir"));
    expect(html).not.toContain("data-rep=");
    expect(html).toContain("Adrien Moreau");
  });
  it("posée dans Teams : plus rien à décider ici", () => {
    const html = replyCard(reply({ state: "pose", preview: null }), view("proprietaire"));
    expect(html).toContain("Posée dans la zone de saisie de Teams");
    expect(html).not.toContain("data-rep=");
  });
});

describe("le champ, selon le niveau (ADR 0189)", () => {
  const base = { title: "Marc Delmas", owner: "Adrien Moreau", asked: false, underWay: false, canPrefill: true, quiet: "", sending: false };
  it("le tien : écrire, préremplir, et ce qui part par l'extension, en ton nom", () => {
    const html = dock({ ...base, caps: caps("proprietaire"), level: "proprietaire" });
    expect(html).toContain("data-tm-input");
    expect(html).toContain('data-tm="preremplir"');
    expect(html).toContain("partira par l'extension, dans Teams, en ton nom");
  });
  it("lire : pas de champ", () => {
    const html = dock({ ...base, caps: caps("lire"), level: "lire" });
    expect(html).not.toContain("data-tm-input");
    expect(html).not.toContain("preremplir");
    expect(html).toContain("en lecture");
  });
  it("préparer : seulement « Préremplir »", () => {
    const html = dock({ ...base, caps: caps("preparer"), level: "preparer" });
    expect(html).not.toContain("data-tm-input");
    expect(html).toContain('data-tm="preremplir"');
  });
  it("une réponse demandée : « Elle s'y met… »", () => {
    expect(dock({ ...base, caps: caps("proprietaire"), level: "proprietaire", asked: true })).toContain("Elle s'y met");
  });
  it("un compte décoché : « Préremplir » éteint dit pourquoi", () => {
    const off = "Ce compte Teams est décoché : elle n'y prépare rien.";
    const html = dock({ ...base, caps: caps("proprietaire"), level: "proprietaire", canPrefill: false, prefillOff: off });
    expect(html).toContain(`data-tm="preremplir" disabled title="${off.replace("'", "&#39;")}"`);
  });
});

describe("le fil et « Ses brouillons »", () => {
  const thread: Thread = {
    key: "19:marc",
    account: "principal",
    title: "Marc Delmas",
    kind: "dm",
    messages: [msg({ ref: "t1" }), msg({ ref: "t2", own: true, author: "Adrien Moreau", text: "Pas encore", at: NOW - 20 * MIN })],
    more: true,
    replies: [reply(), reply({ id: "r0", state: "refuse" })],
    under_way: true,
    asked: false,
  };
  it("plus ancien, tes messages à droite, sa réponse en chemin en carte (les décidées n'y sont pas)", () => {
    const html = threadBody(thread, [], view("proprietaire"), false);
    expect(html).toContain("data-plus-ancien");
    expect(html).toContain('class="tm-msg me');
    expect(html.match(/data-reply-card=/g)?.length).toBe(1);
  });
  it("la table : ses états, et décider seulement ce qui attend, sur ton compte", () => {
    const html = repliesTable([reply(), reply({ id: "r2", state: "parti", sent_text: "Plutôt 16 h", asked: true })], {
      now: NOW,
      convs: new Map(),
      decide: () => true,
    });
    expect(html).toContain("attend ton accord");
    expect(html).toContain("partie · retouchée");
    expect(html).toContain("elle avait écrit « Oui, 15 h me va. »");
    expect(html.match(/data-rep="envoyer"/g)?.length).toBe(1);
    expect(html).toContain("demandée");
    const none = repliesTable([reply()], { now: NOW, convs: new Map(), decide: () => false });
    expect(none).not.toContain('data-rep="envoyer"');
  });
});

describe("tes messages en attente, tels que le moteur les dit (ADR 0189)", () => {
  const own = (state: string, extra: Partial<OwnPending> = {}): OwnPending => ({ id: `p-${state}`, body: `ok ${state}`, at: NOW - 10 * MIN, state, by: "user_1", ...extra });
  const base: Thread = {
    key: "19:marc",
    account: "principal",
    title: "Marc Delmas",
    kind: "dm",
    messages: [msg({ ref: "t1" })],
    more: false,
    replies: [],
    under_way: false,
    asked: false,
  };

  it("en file, en cours d'envoi, posé ; puis pas parti", () => {
    expect(pendingNote("en_file")).toEqual({ note: "en file : l'extension l'envoie dans Teams, sous ton nom", failed: false });
    expect(pendingNote("envoi").failed).toBe(false);
    expect(pendingNote("pose").note).toContain("zone de saisie de Teams");
    expect(pendingNote("inutilise")).toMatchObject({ failed: true });
    expect(pendingNote("inutilise").note).toContain("pas parti");
    expect(pendingNote("echec", "envoi sans nouvelles de l'extension").note).toBe("pas parti : l'envoi a échoué (envoi sans nouvelles de l'extension)");
  });

  it("le moteur fait foi pour ce qu'il connaît : un envoi d'ici s'efface dès qu'une lecture commencée après lui revient", () => {
    const sent = [{ conversation: "19:marc", text: "ok 👍", at: NOW - MIN }, { conversation: "19:autre", text: "x", at: NOW - MIN }];
    // lue avant que l'envoi ne soit accepté : il reste
    expect(stillSentHere(sent, { ...base, pending: [] }, NOW - 2 * MIN)).toHaveLength(2);
    // lue après : le moteur le dit (ou l'a déjà rendu) — la bulle d'ici s'efface ; celle d'une autre discussion reste
    expect(stillSentHere(sent, { ...base, pending: [own("en_file", { body: "ok 👍" })] }, NOW)).toEqual([sent[1]]);
    expect(stillSentHere(sent, { ...base, pending: [] }, NOW)).toEqual([sent[1]]);
    // un moteur qui ne dit pas `pending` : l'envoi s'efface quand le même texte revient de toi dans le fil
    expect(stillSentHere(sent, base, NOW)).toHaveLength(2);
    expect(stillSentHere(sent, { ...base, messages: [msg({ own: true, text: "OK 👍 ", at: NOW })] }, NOW)).toEqual([sent[1]]);
  });

  it("les bulles : celles du moteur, de la plus ancienne à la plus récente, puis les envois d'ici", () => {
    const bubbles = ownBubbles([own("inutilise", { at: NOW - 5 * MIN }), own("en_file", { at: NOW - 9 * MIN })], [{ conversation: "19:marc", text: "tout neuf", at: NOW }]);
    expect(bubbles.map((b) => [b.id, b.failed])).toEqual([["p-en_file", false], ["p-inutilise", true], ["", false]]);
    expect(ownBubbles(undefined, [])).toEqual([]);
  });

  it("dans le fil : « en file » ou « pas parti », et le réécrire quand on peut écrire", () => {
    const t: Thread = { ...base, pending: [own("en_file"), own("inutilise")] };
    const v = view("proprietaire", { pending: ownBubbles(t.pending, []) });
    const html = threadBody(t, [], v, false);
    expect(html.match(/class="tm-msg me pending"/g)?.length).toBe(1);
    expect(html.match(/class="tm-msg me pending failed"/g)?.length).toBe(1);
    expect(html).toContain("en file : l&#39;extension l&#39;envoie dans Teams");
    expect(html).toContain("pas parti");
    expect(html).toContain('data-tm="reecrire" data-pending="p-inutilise"');
    expect(html).not.toContain('data-pending="p-en_file"');
    // qui ne peut pas écrire ici ne se voit pas proposer de le réécrire
    expect(threadBody(t, [], view("lire", { pending: ownBubbles(t.pending, []) }), false)).not.toContain("reecrire");
  });

  it("le champ dit sa borne, et son compte se montre près d'elle", () => {
    const html = dock({ title: "Marc", owner: "", asked: false, underWay: false, canPrefill: true, quiet: "", sending: false, caps: caps("proprietaire"), level: "proprietaire" });
    expect(html).toContain('maxlength="4000"');
    expect(html).toMatch(/data-limit="4000" hidden/);
  });
});

describe("ce qui reste du champ une fois le message parti", () => {
  it("le texte parti s'en retire, ce qu'on a tapé pendant l'envoi reste", () => {
    expect(withoutSent("Je regarde ça", "Je regarde ça")).toBe("");
    expect(withoutSent("  Je regarde ça et je te redis", "Je regarde ça")).toBe("et je te redis");
    expect(withoutSent("Autre chose", "Je regarde ça")).toBeNull(); // réécrit : on n'y touche pas
    expect(withoutSent("", "Je regarde ça")).toBeNull();
  });
});

// ── Audit du 2026-11-05 ─────────────────────────────────────────────────

describe("un tête-à-tête a un nom (F2-01)", () => {
  it("le champ dit où l'on répond, et rien de vide quand la discussion n'a pas de nom", () => {
    const base = { owner: "", asked: false, underWay: false, canPrefill: true, quiet: "", sending: false, caps: caps("proprietaire"), level: "proprietaire" };
    expect(dock({ ...base, title: "Alice Fontaine" })).toContain('placeholder="Répondre dans « Alice Fontaine »…"');
    const blank = dock({ ...base, title: "  " });
    expect(blank).toContain('placeholder="Répondre…"');
    expect(blank).not.toContain("« ");
  });
});

describe("qui a écrit, sur un compte qu'on te partage (F2-02)", () => {
  const adrien = msg({ own: true, author: "Adrien Moreau", author_id: "8:a", text: "Oui, je regarde ça ce soir." });
  it("« Toi » seulement sur un compte à toi ; sinon la personne du compte, ou son propriétaire", () => {
    expect(authorLabel(adrien, account())).toBe("Toi");
    expect(authorLabel(adrien, shared())).toBe("Adrien Moreau");
    expect(authorLabel(adrien, shared("lire", { self_name: "" }))).toBe("Adrien Moreau"); // son propriétaire
    expect(authorLabel(adrien, null)).toBe("Adrien Moreau"); // un compte inconnu : jamais « Toi »
    expect(authorLabel(msg({}), shared())).toBe("Marc Delmas");
    expect(fromYou(adrien, account())).toBe(true);
    expect(fromYou(adrien, shared("servir"))).toBe(false);
  });
  it("la bulle d'Adrien est à gauche, à son nom ; la tienne, à droite", () => {
    const thread: Thread = { key: "19:marc", account: "principal", title: "Marc Delmas", kind: "dm", messages: [adrien], more: false, replies: [], under_way: false, asked: false };
    const theirs = threadBody(thread, [], view("lire", { account: shared() }), false);
    expect(theirs).not.toContain('class="tm-msg me');
    expect(theirs).toContain("<b>Adrien Moreau</b>");
    expect(theirs).not.toContain("<b>Toi</b>");
    const mine = threadBody(thread, [], view("proprietaire", { account: account() }), false);
    expect(mine).toContain('class="tm-msg me');
    expect(mine).toContain("<b>Toi</b>");
  });
  it("la liste, les participants, et ce qu'on sait de ses réponses en lecture seule", () => {
    const conv: Conversation = { key: "19:hebdo", account: "principal", title: "Point hebdo", kind: "group", last_at: NOW, messages: 3, last: { ...adrien, text: "J'ajoute le point" }, her: null };
    expect(conversationRow(conv, "", NOW, false, shared())).toContain("Adrien : J&#39;ajoute le point");
    expect(conversationRow(conv, "", NOW, false, account())).toContain("Toi : J&#39;ajoute le point");
    const info = infoPane({ conv, selfName: "Adrien Moreau", people: [{ name: "Adrien Moreau", key: "8:a", own: true, count: 2 }], account: shared(), replies: [], now: NOW });
    expect(info).toContain("<b>Adrien Moreau</b>");
    expect(info).not.toContain("<b>Toi</b>");
    expect(info).toContain("Ses réponses sur ce compte sont l'affaire d&#39;Adrien Moreau.");
    expect(info).not.toContain("Elle n'a rien préparé");
    const own = infoPane({ conv, selfName: "Adrien Moreau", people: [{ name: "Adrien Moreau", key: "8:a", own: true, count: 2 }], account: account(), replies: [], now: NOW });
    expect(own).toContain("<b>Toi</b>");
    expect(own).toContain("Elle n'a rien préparé dans cette discussion.");
  });
  it("« d'Adrien » : un seul `ofName`, que Mail réexporte", () => {
    expect(ofName("Adrien Moreau")).toBe("d'Adrien Moreau");
    expect(ofName("Léa")).toBe("de Léa");
    expect(mailOfName).toBe(ofName);
  });
});

describe("« Ses brouillons » sur un téléphone, et la route d'une réponse (F2-06, F1-08)", () => {
  it("une carte par réponse : ses cellules se nomment, « Comment ça part » peut s'effacer", () => {
    const html = repliesTable([reply()], { now: NOW, convs: new Map(), decide: () => true });
    expect(html).toContain('class="tbl tm-replies"');
    for (const cls of ["tm-r-conv", "tm-r-text", "tm-r-mode", "tm-r-state", "tm-r-when"]) expect(html).toContain(cls);
  });
  it("#teams/brouillons/<id> : la réponse désignée est surlignée", () => {
    expect(replyHash("t0123456789ab")).toBe("#teams/brouillons/t0123456789ab");
    const html = repliesTable([reply(), reply({ id: "r2" })], { now: NOW, convs: new Map(), decide: () => true, focus: "r2" });
    expect(html).toContain('data-reply-row="r2" class="focus" aria-current="true"');
    expect(html).not.toContain('data-reply-row="r1" class="focus"');
  });
});

describe("répondu autrement (ADR 0199)", () => {
  const answered = reply({ state: "refuse", answered: true, decided_at: NOW - 2 * MIN, preview: null, note: "Répondu autrement, dans la discussion même : cette réponse n'a plus lieu d'être." });
  it("la carte le dit, sans plus rien à décider", () => {
    const html = replyCard(answered, view("proprietaire"));
    expect(html).toContain("Répondu autrement, dans la discussion : elle ne partira pas.");
    expect(html).not.toContain("data-rep=");
    // même avant que le moteur ne l'ait refusée
    expect(replyCard(reply({ answered: true }), view("proprietaire"))).not.toContain("data-rep=");
    expect(replyState(reply({ answered: true }))[1]).toBe("répondu autrement");
    expect(replyState(answered)[1]).toBe("refusée · répondu autrement"); // « Ses brouillons » le dit, même sans la note
  });
  it("le fil la montre tant que rien n'est venu depuis ; « Ses brouillons » ne la fait plus envoyer", () => {
    expect(threadCards([answered], NOW - 5 * MIN)).toEqual([answered]);
    expect(threadCards([answered], NOW)).toEqual([]); // ton message est revenu dans le fil, après
    expect(threadCards([reply({ id: "r9", state: "refuse" })], 0)).toEqual([]);
    expect(threadCards([reply()], NOW)).toHaveLength(1); // en chemin : toujours
    const html = repliesTable([reply({ answered: true })], { now: NOW, convs: new Map(), decide: () => true });
    expect(html).not.toContain('data-rep="envoyer"');
  });
});

