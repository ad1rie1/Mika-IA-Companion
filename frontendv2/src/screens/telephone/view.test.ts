import { describe, expect, it } from "vitest";
import type { Phone, PhoneConversation, PhoneOffer, PhoneThread } from "../../api/phone";
import { parseRoute } from "../../shell/router";
import {
  appBadge,
  askAboutConversation,
  COMPOSER_NOTE,
  COMPOSER_NOTE_MORE,
  composerMarkup,
  conversationItem,
  distanceWords,
  emptyMessagesMarkup,
  emptyPhone,
  herMark,
  matches,
  NOT_OWNER_NOTE,
  offerMarkup,
  offerTitle,
  offerWords,
  onlyPhone,
  osmUrl,
  PHONES_HREF,
  phoneState,
  phoneStateMarkup,
  positionMarkup,
  positionScene,
  pushNote,
  shortPhone,
  snippetOf,
  TELEPHONE_TABS,
  threadHead,
  threadMarkup,
  timeline,
} from "./view";

const NOW = new Date(2026, 10, 4, 15, 0).getTime();
const at = (d: number, h: number, m: number) => new Date(2026, 10, d, h, m).getTime();

function conv(extra: Partial<PhoneConversation> = {}): PhoneConversation {
  return {
    key: "whatsapp|a1",
    app: "whatsapp",
    app_name: "WhatsApp",
    group: false,
    title: "Julien Roux",
    count: 2,
    last_at: at(4, 12, 52),
    last: { id: "p34", at: at(4, 12, 52), own: false, sender: "Julien Roux", text: "Dis-moi vite" },
    her: null,
    ...extra,
  };
}

function offer(extra: Partial<PhoneOffer> = {}): PhoneOffer {
  return { id: 7, state: "offered", at: at(4, 14, 20), expires: at(4, 16, 52), decided_at: 0, reason: "", reply_to: "p34", text: "Oui <b>!</b>", ...extra };
}

const phone = (id: number, extra: Partial<Phone> = {}): Phone => ({
  id, label: "Android · samsung SM-S931B", created_at: at(1, 9, 0), last_used: at(4, 14, 57), revoked: false, push: true, ...extra,
});

describe("les mots du téléphone", () => {
  it("dit chaque sort d'une proposition en français", () => {
    expect(offerWords("prepared")[1]).toBe("préparée");
    expect(offerWords("offered")).toEqual(["warn", "au téléphone — attend ton geste"]);
    expect(offerWords("sent")).toEqual(["ok", "envoyée"]);
    expect(offerWords("other")[1]).toBe("tu as écrit autre chose");
    expect(offerWords("copied")[1]).toBe("copiée");
    expect(offerWords("ignored")[1]).toBe("laissée");
    expect(offerWords("failed")).toEqual(["danger", "échec"]);
    expect(offerWords("expired")[1]).toBe("expirée");
    expect(offerWords("inconnu")).toEqual(["", "inconnu"]);
  });

  it("donne à chaque appli sa couleur et sa lettre", () => {
    expect(appBadge("whatsapp_business", "WhatsApp Business")).toEqual({ cls: "whatsapp", letter: "W" });
    expect(appBadge("samsung_messages", "Messages")).toEqual({ cls: "sms", letter: "M" });
    expect(appBadge("signal", "son téléphone")).toEqual({ cls: "other", letter: "S" });
  });

  it("raccourcit le nom d'un téléphone, et ne nomme celui d'où vient sa position que s'il n'y en a jamais eu qu'un", () => {
    expect(shortPhone("Android · samsung SM-S931B")).toBe("samsung SM-S931B");
    expect(shortPhone("")).toBe("Téléphone");
    expect(onlyPhone([phone(1)])?.id).toBe(1);
    expect(onlyPhone([phone(1), phone(2, { revoked: true })])).toBeNull();
    expect(onlyPhone([])).toBeNull();
  });

  it("écrit une distance et l'adresse OpenStreetMap", () => {
    expect(distanceWords(12)).toBe("12 m");
    expect(distanceWords(1250)).toBe("1,3 km");
    expect(distanceWords(0)).toBe("");
    expect(osmUrl(50.6365, 3.0635)).toBe("https://www.openstreetmap.org/?mlat=50.636500&mlon=3.063500#map=17/50.636500/3.063500");
  });
});

describe("les conversations", () => {
  it("précède le dernier message de qui l'a écrit, dans un groupe ou quand c'est toi", () => {
    expect(snippetOf(conv())).toBe("Dis-moi vite");
    expect(snippetOf(conv({ group: true, last: { ...conv().last, sender: "Thomas Girard" } }))).toBe("Thomas : Dis-moi vite");
    expect(snippetOf(conv({ last: { ...conv().last, own: true } }))).toBe("Toi : Dis-moi vite");
  });

  it("cherche sans accents dans le titre, l'appli et le dernier message", () => {
    expect(matches(conv({ title: "Léa" }), "lea")).toBe(true);
    expect(matches(conv(), "whatsapp")).toBe(true);
    expect(matches(conv(), "garage")).toBe(false);
    expect(matches(conv(), "  ")).toBe(true);
  });

  const her = (state: string) => conv({ her: { state, id: 3, decided_at: state === "offered" || state === "prepared" ? 0 : at(4, 14, 30) } });

  it("marque une conversation d'après sa réponse : en chemin, partie, copiée, en échec ; rien de ce qui n'est pas une nouvelle", () => {
    expect(herMark(her("prepared"))).toEqual(["warn", "réponse proposée"]);
    expect(herMark(her("offered"))).toEqual(["warn", "réponse proposée"]);
    expect(herMark(her("sent"))).toEqual(["ok", "Mika a répondu"]);
    expect(herMark(her("copied"))).toEqual(["info", "copiée"]);
    expect(herMark(her("failed"))).toEqual(["danger", "échec"]);
    for (const state of ["other", "ignored", "expired"]) expect(herMark(her(state))).toBeNull();
    expect(herMark(conv())).toBeNull();
  });

  it("montre la marque dans la liste : en chemin en rose, partie en rose discret, un échec en rouge", () => {
    expect(conversationItem(her("offered"), false, NOW)).toContain('<span class="mk">');
    expect(conversationItem(her("offered"), false, NOW)).toContain("réponse proposée");
    const sent = conversationItem(her("sent"), false, NOW);
    expect(sent).toContain('<span class="mk quiet">');
    expect(sent).toContain("Mika a répondu");
    expect(conversationItem(her("copied"), false, NOW)).toContain("copiée");
    expect(conversationItem(her("failed"), false, NOW)).toContain('<span class="tag danger">');
    for (const state of ["other", "ignored", "expired"]) expect(conversationItem(her(state), false, NOW)).not.toContain("li-marks");
    expect(conversationItem(conv(), false, NOW)).not.toContain("li-marks");
  });
});

describe("le fil", () => {
  const thread: PhoneThread = {
    key: "whatsapp|a1", app: "whatsapp", app_name: "WhatsApp", group: false, title: "",
    messages: [
      { id: "p1", at: at(3, 19, 2), own: false, sender: "Julien", text: "t'es chaud ?" },
      { id: "p2", at: at(4, 14, 8), own: false, sender: "Julien", text: "alors <dimanche> ?" },
    ],
    more: false,
    offers: [offer()],
  };

  it("mêle messages et propositions dans l'ordre du temps, un repère par jour", () => {
    const items = timeline(thread.messages, thread.offers, NOW);
    expect(items.map((i) => (i.kind === "day" ? i.label : i.kind))).toEqual(["Hier", "message", "Aujourd'hui", "message", "offer"]);
  });

  it("échappe les textes et dit ce qu'attend une proposition", () => {
    const html = threadMarkup(thread, "Julien Roux", NOW);
    expect(html).toContain("alors &lt;dimanche&gt; ?");
    expect(html).not.toContain("<dimanche>");
    expect(html).toContain("« Oui &lt;b&gt;!&lt;/b&gt; »");
    expect(html).toContain("au téléphone — attend ton geste</span>");
    expect(html).toContain('<span class="small muted">expire dans 1 h 52</span>');
    expect(html).toContain("Répondre à Julien Roux (WhatsApp) ?");
  });

  it("une proposition réglée dit quand, à côté de son étiquette, sans aide au geste", () => {
    const html = offerMarkup(offer({ state: "sent", decided_at: at(4, 14, 30) }), thread, "Julien", NOW);
    // l'état dans l'étiquette, l'heure à côté : sur un téléphone, chacune passe à la ligne sans sortir de la carte
    expect(html).toContain("envoyée</span><span class=\"small muted\">il y a 30 min</span>");
    expect(html).not.toContain("prop-help");
    const late = offerMarkup(offer({ expires: at(4, 14, 50) }), thread, "Julien", NOW);
    expect(late).toContain('<span class="small muted">échue</span>');
    expect(offerMarkup(offer({ expires: 0 }), thread, "Julien", NOW)).not.toContain("small muted\">");
  });

  it("l'en-tête d'un fil dit l'appli et ses messages, sans nommer un téléphone que le serveur ne connaît pas", () => {
    const html = threadHead(conv({ count: 4 }));
    expect(html).toContain('<p class="small muted">WhatsApp · 4 messages</p>');
    expect(html).not.toContain("tel-where");
    expect(html).not.toContain("samsung");
  });

  it("la saisie coupée garde sa note, dont le début tient seul sur une ligne", () => {
    const html = composerMarkup("Julien Roux");
    expect(html).toContain('class="composer tel-cmp"');
    const esc = (t: string) => t.replace(/'/g, "&#39;");
    expect(html).toContain(`${esc(COMPOSER_NOTE)}<span class="tel-soon-more"> : ${esc(COMPOSER_NOTE_MORE)}</span>.`);
    expect(COMPOSER_NOTE.length).toBeLessThan(40);
  });

  it("titre une réponse selon son sort : proposée en chemin, puis partie ou non", () => {
    for (const state of ["prepared", "offered"]) expect(offerTitle(state)).toBe("Réponse proposée par Mika");
    for (const state of ["sent", "copied"]) expect(offerTitle(state)).toBe("Réponse de Mika");
    for (const state of ["other", "ignored", "failed", "expired"]) expect(offerTitle(state)).toBe("Réponse de Mika, non partie");
    const sent = offerMarkup(offer({ state: "sent", decided_at: at(4, 14, 30) }), thread, "Julien", NOW);
    expect(sent).toContain("<b>Réponse de Mika</b>");
    expect(sent).not.toContain("Réponse proposée par Mika");
    expect(sent).toContain('class="prop settled"'); // le rose de Mika, atténué
    const waiting = offerMarkup(offer(), thread, "Julien", NOW);
    expect(waiting).toContain("<b>Réponse proposée par Mika</b>");
    expect(waiting).toContain('class="prop"');
  });
});

describe("un téléphone d'où rien ne vient", () => {
  it("à une propriétaire, le réglage qui lui manque : le téléphone à installer, ou ses messages à montrer", () => {
    const none = emptyPhone(true, 0);
    expect(none.text).toContain("Installe Mika sur ton téléphone");
    expect(none.href).toBe("#parametres/telephones");
    const one = emptyPhone(true, 1);
    expect(one.text).toContain("allume « Lui montrer mes messages »");
    expect(one.href).toBe("#parametres/telephones");
    expect(one.label).toBe("Tes téléphones");
    // son compte pas encore lu : le conseil d'une propriétaire, comme avant
    expect(emptyPhone(undefined, 1)).toEqual(one);
  });

  it("à un compte qui n'est pas propriétaire, la vraie raison, et sa position plutôt qu'un réglage", () => {
    for (const phones of [0, 1]) {
      const e = emptyPhone(false, phones);
      expect(e.text).toBe(NOT_OWNER_NOTE);
      expect(e.text).toBe("Mika ne lit les messages du téléphone que pour une de ses propriétaires. Ta position, elle, se voit dans l'onglet Position.");
      expect(e.href).toBe("#telephone/position");
    }
    const html = emptyMessagesMarkup(false, 1);
    expect(html).toContain('href="#telephone/position"');
    expect(html).not.toContain("#parametres/telephones");
    expect(html).not.toContain("Lui montrer mes messages");
    expect(emptyMessagesMarkup(true, 1)).toContain('href="#parametres/telephones"');
  });

  it("aucun numéro d'ADR dans ce que montre le Téléphone", () => {
    const shown = [
      emptyMessagesMarkup(true, 0), emptyMessagesMarkup(true, 1), emptyMessagesMarkup(false, 1),
      conversationItem(conv(), true, NOW), threadHead(conv()), composerMarkup("Julien Roux"),
      phoneStateMarkup(phoneState([phone(1, { push: false })], NOW)), phoneStateMarkup(phoneState([], NOW)),
      ...["prepared", "offered", "sent", "failed", "expired"].map((state) => offerMarkup(offer({ state }), { app_name: "WhatsApp" }, "Julien Roux", NOW)),
    ];
    for (const html of shown) expect(html).not.toMatch(/ADR\s*\d/);
  });
});

describe("les onglets", () => {
  it("Messages et Position seulement : Notifications ne redit pas Messages tant que l'application ne lit que les messageries", () => {
    expect(TELEPHONE_TABS.map((t) => [t.id, t.title])).toEqual([["messages", "Messages"], ["position", "Position"]]);
  });

  it("l'ancienne adresse de Notifications retombe sur Messages", () => {
    const screens = new Map([["telephone", { tabs: TELEPHONE_TABS, defaultTab: "messages" }]]);
    expect(parseRoute("#telephone/notifications", screens)).toEqual({ screen: "telephone", tab: "messages", item: null });
    expect(parseRoute("#telephone/position", screens)).toEqual({ screen: "telephone", tab: "position", item: null });
  });
});

describe("en parler à Mika", () => {
  it("prépare une phrase qui nomme la conversation, à compléter", () => {
    expect(askAboutConversation(conv({ title: "Léa Martin" }))).toBe("À propos de ma conversation WhatsApp avec Léa Martin : ");
    expect(askAboutConversation(conv({ title: "Famille Moreau", group: true }))).toBe("À propos de ma conversation WhatsApp avec le groupe Famille Moreau : ");
    expect(askAboutConversation(conv({ title: " ", app_name: "Messages" }))).toBe("À propos d'une de mes conversations Messages : ");
  });
});

describe("la position", () => {
  it("dit qu'elle ne sait pas, sans plan", () => {
    const html = positionMarkup({ known: false }, null, NOW);
    expect(html).toContain("Mika ne sait pas où tu es");
    expect(html).not.toContain("drawn-map");
  });

  it("montre le lieu, la précision, l'heure, et le lien vers la vraie carte", () => {
    const html = positionMarkup({ known: true, coords: { lat: 50.6365, lon: 3.0635 }, label: "rue Nationale, Lille", accuracy_m: 12, at: at(4, 14, 10) }, phone(1), NOW);
    expect(html).toContain("rue Nationale, Lille");
    expect(html).toContain("à 12 m près · aujourd&#39;hui à 14:10");
    expect(html).toContain('href="https://www.openstreetmap.org/?mlat=50.636500&amp;mlon=3.063500#map=17/50.636500/3.063500" target="_blank" rel="noopener"');
    expect(html).toContain("Android · samsung SM-S931B, application ouverte");
    expect(html).toContain('class="drawn-map"');  // sans carte servie : le plan dessiné
  });

  it("la vraie carte, servie par le serveur, prend la place du plan", () => {
    const html = positionMarkup({ known: true, coords: { lat: 50.6365, lon: 3.0635 }, label: "rue Nationale, Lille", accuracy_m: 12, at: at(4, 14, 10) }, phone(1), NOW, true);
    expect(html).toContain('class="map-live" data-map');
    expect(html).not.toContain("drawn-map");
    expect(html).not.toContain("Un plan dessiné");
    expect(html).toContain("rue Nationale, Lille");  // la légende reste
  });

  const HERE = { lat: 50.6365, lon: 3.0635 };
  const POS = { known: true as const, coords: HERE, label: "rue Nationale, Lille", accuracy_m: 12, at: at(4, 14, 10) };

  it("une carte qui ne se montre pas (refusée ici, hors de sa zone : `map/live.ts`) laisse le plan et sa note", () => {
    const html = positionMarkup(POS, phone(1), NOW, false);
    expect(html).toContain('class="drawn-map"');
    expect(html).not.toContain("data-map");
    expect(html).toContain("Un plan dessiné, pas une carte");
  });

  it("la vraie carte et le plan montrent la même scène : la position et sa précision, rien d'autre (F3-09)", () => {
    expect(positionScene(HERE, 12)).toEqual({ pins: [], lines: [], here: { lat: 50.6365, lon: 3.0635, accuracy_m: 12 } });
    expect(positionScene(null, 12)).toEqual({ pins: [], lines: [], here: null }); // sans coordonnées : rien à montrer
  });

  it("le plan dessiné ne montre que la position et sa précision : ni rue, ni rivière, ni parc inventés (F3-08)", () => {
    const html = positionMarkup(POS, phone(1), NOW);
    for (const made of ["m-water", "m-road", "m-park", "m-block"]) expect(html).not.toContain(made);
    expect(html).toContain('<svg class="drawn-map"');
    expect(html).toContain('aria-label="Plan autour de rue Nationale, Lille"');
    // 12 m, à l'échelle d'un plan de 300 m de haut (560 - 2 × 48 = 464 unités) : un cercle, pas un point
    const r = Number(html.match(/<circle class="dm-here-acc" cx="400\.0" [^>]*r="([\d.]+)"\/>/)?.[1]);
    expect(r).toBeCloseTo((12 / 300) * 464, 0);
    expect(html).toContain('<circle class="dm-here" cx="400.0"');
    expect(html).toContain("Un plan dessiné, pas une carte : le lien ouvre la vraie, sur OpenStreetMap.");
    // une autre précision, un autre cercle : le dessin suit la position, il n'est plus le même partout
    const wide = positionMarkup({ ...POS, accuracy_m: 150 }, phone(1), NOW);
    expect(Number(wide.match(/class="dm-here-acc" [^>]*r="([\d.]+)"/)?.[1])).toBeCloseTo((150 / 750) * 464, 0);
  });

  it("sans coordonnées, un plan vide et la note qui le dit", () => {
    const html = positionMarkup({ ...POS, coords: null }, phone(1), NOW);
    expect(html).toContain('<svg class="drawn-map"');
    expect(html).not.toContain("dm-here");
    expect(html).toContain("Un plan dessiné, pas une carte : le serveur n'a pas ses coordonnées.");
    expect(html).toContain("rue Nationale, Lille"); // la légende reste
  });

});

describe("l'état de ses téléphones, dans la barre de titre", () => {
  it("un seul téléphone : son nom, vu quand, et un point qui dit s'il reçoit les notifications", () => {
    const s = phoneState([phone(1, { label: "Android · Google Pixel 8" }), phone(2, { revoked: true })], NOW);
    expect(s).toEqual({
      label: "Google Pixel 8",
      seen: "vu il y a 3 min",
      dot: "ok",
      push: "reçoit les notifications",
      title: "Google Pixel 8, vu il y a 3 min, reçoit les notifications — Paramètres › Téléphones",
    });
    // un lien vers Paramètres › Téléphones : ni menu, ni chevron, ni « Tous tes téléphones 1 »
    const html = phoneStateMarkup(s);
    expect(PHONES_HREF).toBe("#parametres/telephones");
    expect(html).toMatch(/^<a class="phone-state" href="#parametres\/telephones" data-tel-state /);
    expect(html).toContain('aria-label="Google Pixel 8, vu il y a 3 min, reçoit les notifications — Paramètres › Téléphones"');
    expect(html).toContain('<span class="dot ok" title="reçoit les notifications"></span>');
    expect(html).toContain('<span class="muted tel-seen">vu il y a 3 min</span>');
    expect(html).not.toContain("tel-push"); // tout va bien : le point vert suffit, ses mots au survol
    for (const gone of ["data-tel-switch", "chev-down", "Tous tes téléphones", "<button"]) expect(html).not.toContain(gone);
  });

  it("un téléphone sans notifications : le point orange le dit, au survol, à voix haute et en clair", () => {
    const s = phoneState([phone(1, { push: false })], NOW);
    expect(s.dot).toBe("warn");
    expect(s.push).toBe("ne reçoit pas les notifications");
    expect(s.title).toBe("samsung SM-S931B, vu il y a 3 min, ne reçoit pas les notifications — Paramètres › Téléphones");
    const html = phoneStateMarkup(s);
    expect(html).toContain('<span class="dot warn" title="ne reçoit pas les notifications"></span><span class="tel-push">ne reçoit pas les notifications</span>');
    expect(pushNote(true)).toBe("reçoit les notifications");
    expect(pushNote(false)).toBe("ne reçoit pas les notifications");
  });

  it("deux téléphones : leur nombre, le plus récent, et chacun dans l'infobulle", () => {
    const two = [
      phone(1, { label: "Android · Google Pixel 8", push: false }),
      phone(2, { last_used: at(3, 18, 5) }),
      phone(3, { revoked: true, last_used: at(4, 14, 59) }), // révoqué : ne compte pas, même vu plus tard
    ];
    const s = phoneState(two, NOW);
    expect(s.label).toBe("2 téléphones");
    expect(s.seen).toBe("vu il y a 3 min");
    expect(s.dot).toBe("warn");
    expect(s.push).toBe("1 sur 2 ne reçoit pas les notifications");
    expect(s.title).toBe(
      "2 téléphones — Google Pixel 8 : vu il y a 3 min, ne reçoit pas les notifications ; samsung SM-S931B : vu hier à 18:05, reçoit les notifications — Paramètres › Téléphones",
    );
    expect(phoneState([phone(1), phone(2)], NOW).push).toBe("les 2 reçoivent les notifications");
    expect(phoneState([phone(1), phone(2)], NOW).dot).toBe("ok");
    expect(phoneState([phone(1, { push: false }), phone(2, { push: false })], NOW).push).toBe("aucun ne reçoit les notifications");
  });

  it("aucun téléphone : ni point ni « vu », et le lien mène où en connecter un", () => {
    for (const phones of [[], [phone(1, { revoked: true })]]) {
      const s = phoneState(phones, NOW);
      expect(s).toEqual({ label: "Aucun téléphone", seen: "", dot: null, push: "", title: "Aucun téléphone : en connecter un, dans Paramètres › Téléphones" });
      const html = phoneStateMarkup(s);
      expect(html).toContain('href="#parametres/telephones"');
      expect(html).toContain("<b>Aucun téléphone</b>");
      expect(html).not.toContain('class="dot');
      expect(html).not.toContain("tel-seen");
    }
  });

  it("un téléphone qui n'a jamais servi ne dit pas « vu »", () => {
    const s = phoneState([phone(1, { last_used: 0 })], NOW);
    expect(s.seen).toBe("");
    expect(s.title).toBe("samsung SM-S931B, reçoit les notifications — Paramètres › Téléphones");
  });
});
