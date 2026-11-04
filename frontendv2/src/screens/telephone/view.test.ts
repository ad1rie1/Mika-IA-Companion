import { describe, expect, it } from "vitest";
import type { Phone, PhoneConversation, PhoneOffer, PhoneThread } from "../../api/phone";
import {
  appBadge,
  byApp,
  conversationTag,
  distanceWords,
  matches,
  offerMarkup,
  offerWords,
  onlyPhone,
  osmUrl,
  phoneSwitch,
  positionMarkup,
  shortPhone,
  snippetOf,
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

  it("raccourcit le nom d'un téléphone, et ne nomme celui d'un message que s'il n'y en a jamais eu qu'un", () => {
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

  it("range par appli, dans l'ordre d'arrivée, et étiquette chacune", () => {
    const groups = byApp([conv({ key: "a" }), conv({ key: "b", app: "messages", app_name: "Messages" }), conv({ key: "c" })]);
    expect(groups.map((g) => [g.name, g.items.map((c) => c.key)])).toEqual([["WhatsApp", ["a", "c"]], ["Messages", ["b"]]]);
    expect(conversationTag(conv())).toEqual(["", "reçue"]);
    expect(conversationTag(conv({ last: { ...conv().last, own: true } }))).toEqual(["ok", "répondu par toi"]);
    expect(conversationTag(conv({ her: { state: "offered", id: 3 } }))).toEqual(["warn", "réponse proposée"]);
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
    expect(html).toContain("au téléphone — attend ton geste · expire dans 1 h 52");
    expect(html).toContain("Répondre à Julien Roux (WhatsApp) ?");
  });

  it("une proposition réglée dit quand, sans aide au geste", () => {
    const html = offerMarkup(offer({ state: "sent", decided_at: at(4, 14, 30) }), thread, "Julien", NOW);
    expect(html).toContain("envoyée · il y a 30 min");
    expect(html).not.toContain("prop-help");
  });
});

describe("la position et le sélecteur", () => {
  it("dit qu'elle ne sait pas, sans plan", () => {
    const html = positionMarkup({ known: false }, null, NOW);
    expect(html).toContain("Mika ne sait pas où tu es");
    expect(html).not.toContain('class="map"');
  });

  it("montre le lieu, la précision, l'heure, et le lien vers la vraie carte", () => {
    const html = positionMarkup({ known: true, coords: { lat: 50.6365, lon: 3.0635 }, label: "rue Nationale, Lille", accuracy_m: 12, at: at(4, 14, 10) }, phone(1), NOW);
    expect(html).toContain("rue Nationale, Lille");
    expect(html).toContain("à 12 m près · aujourd&#39;hui à 14:10");
    expect(html).toContain('href="https://www.openstreetmap.org/?mlat=50.636500&amp;mlon=3.063500#map=17/50.636500/3.063500" target="_blank" rel="noopener"');
    expect(html).toContain("Android · samsung SM-S931B, application ouverte");
    expect(html).toContain('class="map"');  // sans carte servie : le plan dessiné
  });

  it("la vraie carte, servie par le serveur, prend la place du plan", () => {
    const html = positionMarkup({ known: true, coords: { lat: 50.6365, lon: 3.0635 }, label: "rue Nationale, Lille", accuracy_m: 12, at: at(4, 14, 10) }, phone(1), NOW, true);
    expect(html).toContain('class="map-live" data-map');
    expect(html).not.toContain('class="map"');
    expect(html).not.toContain("Un plan dessiné");
    expect(html).toContain("rue Nationale, Lille");  // la légende reste
  });

  it("le sélecteur nomme tous les téléphones, ou celui choisi", () => {
    expect(phoneSwitch([phone(1), phone(2, { revoked: true })], null, NOW)).toContain("Tous tes téléphones");
    expect(phoneSwitch([], null, NOW)).toContain("Aucun téléphone");
    const one = phoneSwitch([phone(1)], 1, NOW);
    expect(one).toContain("samsung SM-S931B");
    expect(one).toContain("vu il y a 3 min");
  });
});
