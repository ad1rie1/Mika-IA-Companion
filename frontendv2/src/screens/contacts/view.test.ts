import { describe, expect, it } from "vitest";
import type { ContactLine, ContactSheet, ContactsPage } from "../../api/contacts";
import { parseRoute } from "../../shell/router";
import { legacyContactsHash, writeToHash, writeToRoute } from "../mail/format";
import {
  contactHash,
  contactItem,
  forgetFactQuestion,
  forgetQuestion,
  idea,
  lineSub,
  listBody,
  listTools,
  mailHash,
  noteSource,
  phoneHash,
  placeParts,
  privacyNote,
  routeId,
  sheetMarkup,
  sheetPlaceholder,
  teamsHash,
  type ListView,
} from "./view";

const NOW = new Date(2026, 10, 22, 15, 0).getTime();
const at = (d: number, h: number, m: number) => new Date(2026, 10, d, h, m).getTime();

function line(extra: Partial<ContactLine> = {}): ContactLine {
  return {
    id: 12, kind: "person", name: "Claire Dubois", title: "Cheffe de projet", department: "", organisation: { id: 3, name: "Lumen Conseil" },
    linked: false, talks: false, members: 0, last: at(22, 13, 40), identifiers: [{ kind: "email", value: "c.dubois@lumen-conseil.fr" }],
    sources: [{ source: "teams", label: "Teams", count: 64 }, { source: "mail", account: "pro", label: "Pro", count: 23 }],
    ...extra,
  };
}

function sheet(extra: Partial<ContactSheet> = {}): ContactSheet {
  return {
    id: 12, kind: "person", name: "Claire Dubois", title: "Cheffe de projet", department: "", organisation: { id: 3, name: "Lumen Conseil" },
    linked: false, talks: false, last: at(22, 13, 40), first: at(1, 9, 0),
    sources: [{ source: "teams", label: "Teams", count: 64 }, { source: "mail", account: "pro", label: "Pro", count: 23 }],
    identifiers: [
      { kind: "email", label: "E-mail", value: "c.dubois@lumen-conseil.fr", name: "", where: ["Pro", "son profil Teams"], generic: false },
      { kind: "teams", label: "Identifiant Teams", value: "8:orgid:7c2e", name: "", where: ["Teams"], generic: false },
    ],
    facts: [{ kind: "title", label: "Poste", value: "Cheffe de projet", from: "son profil Teams" },
      { kind: "organisation", label: "Organisation", value: "Lumen Conseil", id: 3, from: "son adresse e-mail" }],
    places: [
      { source: "teams", conversation: "equipe~19:claire@unq.gbl.spaces", account: "equipe", title: "Claire Dubois", kind: "dm", count: 41, last: at(22, 13, 40) },
      { source: "mail", box: "pro", box_name: "Pro", count: 23, last: at(22, 13, 0), ref: "pro:<m1@lumen>", subject: "Re: Présentation de jeudi" },
    ],
    members: [], members_total: 0,
    write: { address: "c.dubois@lumen-conseil.fr", name: "Claire Dubois" },
    teams: "equipe~19:claire@unq.gbl.spaces", message: "", privacy: "mine", forget: { allowed: true, reason: "" },
    ...extra,
  };
}

function page(items: ContactLine[], extra: Partial<ContactsPage> = {}): ContactsPage {
  return { total: items.length, page: 1, size: 100, counts: { all: 11, person: 8, org: 3 }, items, ...extra };
}

function view(extra: Partial<ListView> = {}): ListView {
  const items = extra.items ?? [line()];
  return { q: "", kind: "", page: page([...items]), items, selected: 12, loading: false, error: "", now: NOW, ...extra };
}

describe("Contacts : les adresses", () => {
  it("une fiche se désigne par son numéro, et rien d'autre", () => {
    expect(contactHash(12)).toBe("#contacts/12");
    expect(routeId("12")).toBe(12);
    for (const bad of [null, "", "0", "abc", "12x", "-3", "1".repeat(16)]) expect(routeId(bad)).toBeNull();
    const screens = new Map([["contacts", { tabs: [] }], ["mail", { tabs: [{ id: "messages" }] }]]);
    expect(parseRoute("#contacts/12", screens)).toEqual({ screen: "contacts", tab: null, item: "12" });
    expect(parseRoute("#contacts", screens)).toEqual({ screen: "contacts", tab: null, item: null });
  });

  it("mène aux écrans Teams, Téléphone et Mail par leurs propres routes", () => {
    expect(teamsHash("equipe~19:a b")).toBe("#teams/discussions/equipe~19%3Aa%20b");
    expect(phoneHash("whatsapp|t1")).toBe("#telephone/messages/whatsapp%7Ct1");
    expect(mailHash("pro:<m1@x>")).toBe("#mail/messages/pro%3A%3Cm1%40x%3E");
    expect(mailHash("")).toBe("#mail/messages");
  });

  it("« Écrire » ouvre le courrier, le destinataire posé ; l'ancien Mail › Contacts mène ici", () => {
    const hash = writeToHash("c.dubois@lumen-conseil.fr", "Claire / Lumen");
    const screens = new Map([["mail", { tabs: [{ id: "messages" }] }]]);
    const route = parseRoute(hash, screens);
    expect(route.tab).toBe("messages");
    expect(writeToRoute(route.item)).toEqual({ address: "c.dubois@lumen-conseil.fr", name: "Claire / Lumen" });
    expect(writeToRoute(parseRoute(writeToHash("a@b.fr"), screens).item)).toEqual({ address: "a@b.fr", name: "" });
    expect(writeToRoute("pro:<m1@x>")).toBeNull();
    expect(writeToRoute("ecrire/")).toBeNull();
    for (const old of ["#mail/contacts", "#mail/contacts/lea%40example.test", "#/mail//contacts"]) expect(legacyContactsHash(old)).toBe("#contacts");
    for (const other of ["#mail", "#mail/messages", "#mail/messages/contacts", "#contacts"]) expect(legacyContactsHash(other)).toBeNull();
  });
});

describe("Contacts : la liste", () => {
  it("dit l'organisation, sinon ce qu'on sait de lui, et d'où il vient avec combien", () => {
    const html = contactItem(line(), true, NOW);
    expect(html).toContain('data-cx="12" aria-selected="true"');
    expect(html).toContain("Claire Dubois") ;
    expect(html).toContain('<span class="cx-org">Lumen Conseil</span>');
    expect(html).toContain('title="Teams · 64"') ;
    expect(html).toContain('title="Pro · 23"');
    expect(html).toContain("<time>13:40</time>");
    expect(lineSub(line({ organisation: null }))).toBe("Cheffe de projet");
    expect(lineSub(line({ organisation: null, title: "", identifiers: [] }))).toBe("");
    expect(contactItem(line({ organisation: null, title: "", identifiers: [] }), false, NOW)).not.toContain("cx-org");
    expect(lineSub(line({ organisation: null, title: "", identifiers: [], linked: true, talks: true }))).toBe("parle aussi à Mika");
    // reliée à une personne qui n'a jamais écrit à Mika : elle n'a qu'un compte (relecture, mineur 1)
    expect(lineSub(line({ organisation: null, title: "", identifiers: [], linked: true, talks: false }))).toBe("a un compte");
    expect(lineSub(line({ kind: "org", members: 5 }))).toBe("Organisation · 5 personnes");
    expect(idea({ title: "Développeur", department: "R&D" })).toBe("Développeur · R&D");
  });

  it("une organisation a un avatar carré ; une source vue par un profil seul n'a pas de nombre", () => {
    expect(contactItem(line({ kind: "org" }), false, NOW)).toMatch(/class="av sm sq c\d"/);
    expect(contactItem(line(), false, NOW)).not.toMatch(/ sq /);
    const html = contactItem(line({ sources: [{ source: "teams", label: "Teams", count: 0 }] }), false, NOW);
    expect(html).toContain('title="Teams"');
  });

  it("échappe tout ce qui vient d'ailleurs", () => {
    const evil = '<img src=x onerror="alert(1)">';
    const html = contactItem(line({ name: evil, organisation: { id: 1, name: evil }, sources: [{ source: "mail", label: evil, count: 1 }] }), false, NOW)
      + sheetMarkup(sheet({ name: evil, title: evil, organisation: { id: 1, name: evil },
        identifiers: [{ kind: "email", label: evil, value: evil, name: "", where: [evil], generic: false }],
        facts: [{ kind: "title", label: evil, value: evil, from: evil }],
        places: [{ source: "mail", box: "pro", box_name: evil, count: 1, last: NOW, ref: "x", subject: evil }],
        forget: { allowed: false, reason: evil } }), NOW)
      + listBody(view({ q: evil, items: [] }));
    expect(html).not.toContain("<img");
    expect(html).toContain("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;");
  });

  it("Tous / Personnes / Organisations, avec leurs nombres ; la recherche gardée", () => {
    const html = listTools(view({ q: "clai", kind: "org" }));
    expect(html).toContain('data-cxsorte="" aria-pressed="false">Tous <span class="cnt">11</span>');
    expect(html).toContain('data-cxsorte="person" aria-pressed="false">Personnes <span class="cnt">8</span>');
    expect(html).toContain('data-cxsorte="org" aria-pressed="true">Organisations <span class="cnt">3</span>');
    expect(html).toContain('value="clai"');
    expect(html).toContain('placeholder="Un nom, un e-mail, un numéro…"');
  });

  it("dit pourquoi elle est vide, et propose la suite d'une longue liste", () => {
    expect(listBody(view({ q: "zzz", items: [] }))).toContain("Aucun contact ne correspond à « zzz »");
    expect(listBody(view({ items: [] }))).toContain("Aucun contact");
    expect(listBody(view({ kind: "org", items: [] }))).toContain("Aucune organisation");
    expect(listBody(view({ page: null, items: [] }))).toContain("Chargement");
    expect(listBody(view({ page: null, items: [], error: "Le serveur de Mika ne répond pas." }))).toContain("data-cx-relire");
    const items = [line()];
    expect(listBody(view({ items, page: page(items, { total: 250 }) }))).toContain("Afficher les suivants (249)");
    expect(listBody(view({ items }))).not.toContain("data-cx-plus");
  });
});

describe("Contacts : la fiche", () => {
  it("sa tête : ce qu'on sait, son organisation, Écrire, Teams ; « parle aussi à Mika » s'il lui parle", () => {
    const html = sheetMarkup(sheet(), NOW);
    expect(html).toContain("<h2>Claire Dubois</h2>");
    expect(html).toContain('<a href="#contacts/3" data-cx-lien="3">Lumen Conseil</a>');
    expect(html).toContain('href="#mail/messages/ecrire/c.dubois%40lumen-conseil.fr/Claire%20Dubois"');
    expect(html).toContain(`href="${teamsHash("equipe~19:claire@unq.gbl.spaces")}"`);
    expect(html).not.toContain("Message</a>");
    expect(html).not.toContain("parle aussi à Mika");
    expect(sheetMarkup(sheet({ linked: true, talks: true }), NOW)).toContain('<span class="tag ok">parle aussi à Mika</span>');
    expect(sheetMarkup(sheet({ linked: true, talks: false }), NOW)).toContain('<span class="tag">a un compte</span>');
    const bare = sheetMarkup(sheet({ write: null, teams: "", message: "whatsapp|t1" }), NOW);
    expect(bare).not.toContain("Écrire</a>");
    expect(bare).not.toContain("Teams</a>");
    expect(bare).toContain("Message</a>");
    expect(bare).toContain('href="#telephone/messages/whatsapp%7Ct1"');
  });

  it("la ligne des faits : chaque source avec son nombre, le dernier échange", () => {
    const html = sheetMarkup(sheet(), NOW);
    expect(html).toContain("Teams · 64");
    expect(html).toContain("Pro · 23");
    expect(html).toContain("dernier échange aujourd&#39;hui 13:40");
  });

  it("ce qui l'identifie dit d'où elle le tient ; un contact du téléphone se dit par son nom, jamais sa clé", () => {
    const html = sheetMarkup(sheet(), NOW);
    expect(html).toContain("<b>c.dubois@lumen-conseil.fr</b><small>Pro, son profil Teams</small>");
    const phone = sheetMarkup(sheet({ identifiers: [{ kind: "phone_app", label: "Contact WhatsApp", value: "", name: "Maman", where: ["ton téléphone"], generic: false }] }), NOW);
    expect(phone).toContain('<span class="muted">Contact WhatsApp</span><span class="cx-val"><b>Maman</b><small>ton téléphone</small>');
    const noName = sheetMarkup(sheet({ identifiers: [{ kind: "phone_app", label: "Contact SMS", value: "", name: "", where: ["ton téléphone"], generic: false }] }), NOW);
    expect(noName).toContain("<b>hors de ton carnet</b>");
    const generic = sheetMarkup(sheet({ kind: "org", identifiers: [{ kind: "email", label: "E-mail", value: "noreply@lumen.fr", name: "", where: ["Pro"], generic: true }] }), NOW);
    expect(generic).toContain("<small>Pro, sans personne derrière</small>");
    expect(sheetMarkup(sheet({ identifiers: [] }), NOW)).toContain("tu lui en as seulement parlé");
  });

  it("ce que Mika a compris de ses messages : chaque fait d'où il vient, une croix pour ceux de tes comptes", () => {
    const evil = "<img src=x onerror=alert(1)>";
    const mine = { kind: "note", id: 41, label: "", value: "Elle prépare la présentation de jeudi.", from: "ses messages dans Teams", sort: "topic", confidence: 0.8, place: "en tête-à-tête", at: NOW, forget: true };
    const shared = { kind: "note", id: 42, label: "", value: evil, from: "ses mails à Atelier", sort: "other", confidence: 0.55, place: "", at: NOW, forget: false };
    const html = sheetMarkup(sheet({ facts: [...sheet().facts, mine, shared] }), NOW);
    expect(html).toContain('<li class="cx-note-fait"><p>Elle prépare la présentation de jeudi.</p><small>d&#39;après ses messages dans Teams · en tête-à-tête · sûre à 80 %</small><button class="btn xs ghost" type="button" data-cx-oublier-fait="41"');
    expect(html).not.toContain('data-cx-oublier-fait="42"'); // un compte qui n'est pas à toi : pas de croix
    expect(html).not.toContain(evil);
    expect(html).toContain("&lt;img src=x onerror=alert(1)&gt;</p><small>d&#39;après ses mails à Atelier · sûre à 55 %</small></li>");
    expect(noteSource({ kind: "note", label: "", value: "x", from: "" })).toBe("");
    expect(forgetFactQuestion(mine)).toContain("« Elle prépare la présentation de jeudi. »");
    expect(forgetFactQuestion(mine)).toContain("ne le réapprendra pas");
  });

  it("ce que Mika en sait : le poste et l'organisation, d'où ; rien à oublier sans fait tiré de ses messages", () => {
    const html = sheetMarkup(sheet(), NOW);
    expect(html).toContain('<li><p><span class="muted">Poste</span>Cheffe de projet</p><small>d\'après son profil Teams</small></li>');
    expect(html).toContain('<a href="#contacts/3" data-cx-lien="3">Lumen Conseil</a></p><small>d\'après son adresse e-mail</small>');
    expect(html).not.toContain("data-cx-oublier-fait");
    expect(sheetMarkup(sheet({ facts: [] }), NOW)).toContain("Rien de plus que ce qui l'identifie.");
  });

  it("où vous vous croisez : chaque lieu mène à son écran", () => {
    const [teams, mail] = sheet().places.map((p) => placeParts(p, "Claire Dubois", NOW));
    expect(teams).toEqual({ icon: "teams", title: "Claire Dubois", detail: "tête-à-tête · 41 messages", href: "#teams/discussions/equipe~19%3Aclaire%40unq.gbl.spaces" });
    expect(mail).toEqual({ icon: "mail", title: "Re: Présentation de jeudi", detail: "Pro · 23 mails · aujourd'hui 13:00", href: "#mail/messages/pro%3A%3Cm1%40lumen%3E" });
    const group = placeParts({ source: "phone", conversation: "whatsapp|g1", app: "whatsapp", app_name: "WhatsApp", title: "Rando dimanche", group: true, count: 3, last: NOW }, "Julien", NOW);
    expect(group).toEqual({ icon: "chat", title: "Rando dimanche", detail: "WhatsApp · groupe · 3 messages", href: "#telephone/messages/whatsapp%7Cg1" });
    const sms = placeParts({ source: "phone", conversation: "messages|t2", app: "messages", app_name: "Messages", title: "", group: false, count: 1, last: NOW }, "Maman", NOW);
    expect(sms).toMatchObject({ icon: "phone", title: "Maman", detail: "Messages · 1 message" });
    const empty = placeParts({ source: "mail", box: "perso", box_name: "Perso", count: 8, last: 0, ref: "", subject: "" }, "Léa", NOW);
    expect(empty).toEqual({ icon: "mail", title: "8 mails", detail: "Perso", href: "#mail/messages" });
    expect(sheetMarkup(sheet({ places: [] }), NOW)).not.toContain("Où vous vous croisez");
  });

  it("une organisation : ses personnes parmi tes contacts, et combien d'autres", () => {
    const org = sheet({ kind: "org", name: "Lumen Conseil", organisation: null, title: "", facts: [], members_total: 7,
      members: [{ id: 12, name: "Claire Dubois", title: "Cheffe de projet", department: "", last: NOW, linked: false, talks: false },
        { id: 13, name: "Marc Delmas", title: "", department: "", last: NOW, linked: true, talks: true }] });
    const html = sheetMarkup(org, NOW);
    expect(html).toContain("Ses personnes parmi tes contacts");
    expect(html).toContain('data-cx="12"');
    expect(html).toContain("et 5 autres");
    expect(html).toContain("Organisation · 7 personnes parmi tes contacts");
    expect(html).toMatch(/class="av xl sq c\d"/);
    expect(sheetMarkup(sheet(), NOW)).not.toContain("Ses personnes");
  });

  it("la phrase sur ce qu'elle en sait, et l'oubli : jamais de qui d'autre c'est le contact", () => {
    expect(privacyNote(sheet())).toBe("Ce que Mika sait de Claire Dubois vient de tes comptes et de ce que tu lui as dit : elle n'en parle qu'à toi.");
    expect(privacyNote(sheet({ privacy: "shared" }))).toContain("d'autres que toi peuvent le lire");
    const refused = sheetMarkup(sheet({ forget: { allowed: false, reason: "Ce contact ne vient pas que de tes comptes." } }), NOW);
    expect(refused).toContain('data-cx-oublier title="Ce contact ne vient pas que de tes comptes."');
    expect(sheetMarkup(sheet(), NOW)).toContain("data-cx-oublier>");
    expect(forgetQuestion(sheet())).toContain("Les messages restent dans leurs boîtes.");
    // la fiche ne nomme aucune autre personne : rien qui dise « contact de … »
    expect(sheetMarkup(sheet(), NOW)).not.toMatch(/contact d[e']/i);
  });

  it("pendant sa lecture, introuvable, en échec, ou rien de choisi", () => {
    expect(sheetPlaceholder("loading")).toContain("Chargement");
    expect(sheetPlaceholder("missing")).toContain("Contact introuvable");
    expect(sheetPlaceholder("error", "Le serveur de Mika ne répond pas.")).toContain("data-cx-relire");
    expect(sheetPlaceholder("none")).toContain("Choisis un contact");
    for (const s of ["loading", "missing", "error"] as const) expect(sheetPlaceholder(s)).toContain("data-retour-cx");
  });
});

describe("Mail › Contacts a quitté le courrier (ADR 0298)", () => {
  it("le courrier n'a plus que ses messages ; ses correspondants sont dans Contacts", async () => {
    const { mailScreen } = await import("../mail");
    const def = mailScreen({} as Parameters<typeof mailScreen>[0]);
    expect((def.tabs ?? []).map((t) => t.id)).toEqual(["messages"]);
  });
});
