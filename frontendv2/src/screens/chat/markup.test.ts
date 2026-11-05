import { describe, expect, it } from "vitest";
import type { StoredMessage } from "@web/ui/chatSync";
import { splitBubbles } from "@web/ui/bubbles";
import { EMPTY_APPROVALS, withApprovals, withConnection } from "@web/ui/approvals";
import { toolFrame, withToolFrame, type WorkCard } from "@web/ui/toolActivity";
import { messageNotes } from "@web/ui/messageNotes";
import { miniCard, pendingMini } from "../../map/cards";
import { slotKey } from "../../map/minis";
import { mapNotes } from "../../map/notes";
import {
  approvalsMarkup,
  cardKinds,
  dayAndClock,
  elsewhere,
  inlineHtml,
  sentFile,
  shortWhen,
  sizeLabel,
  splitAttachments,
  threadMarkup,
  workCard,
  type ThreadView,
} from "./markup";

const NOW = new Date(2026, 10, 4, 14, 20).getTime();
const at = (d: number, h: number, m: number) => new Date(2026, 10, d, h, m).getTime();

function view(messages: StoredMessage[], extra: Partial<ThreadView> = {}): ThreadView {
  return {
    messages,
    cards: [],
    operator: false,
    pro: false,
    shown: (_m, total) => total,
    split: splitBubbles,
    typing: false,
    openWork: new Set(),
    verdictErrors: new Map(),
    truncated: false,
    now: NOW,
    api: "http://localhost:8001",
    ...extra,
  };
}

describe("les petites formes", () => {
  it("shortWhen : l'heure aujourd'hui, « hier », le jour de la semaine, puis la date", () => {
    expect(shortWhen(at(4, 13, 31), NOW)).toBe("13:31");
    expect(shortWhen(at(3, 21, 41), NOW)).toBe("hier");
    expect(shortWhen(at(2, 9, 0), NOW)).toBe("lun.");
    expect(shortWhen(at(28 - 31, 9, 0), NOW)).toBe("28 oct.");
    expect(shortWhen(new Date(2025, 0, 2).getTime(), NOW)).toBe("2 janv. 2025");
    expect(shortWhen(0, NOW)).toBe("");
    expect(dayAndClock(at(4, 14, 5), NOW)).toBe("aujourd'hui 14:05");
    expect(dayAndClock(at(3, 21, 41), NOW)).toBe("hier 21:41");
  });

  it("sizeLabel", () => {
    expect(sizeLabel(212 * 1024)).toBe("212 Ko");
    expect(sizeLabel(1.8 * 1024 * 1024)).toBe("1,8 Mo");
    expect(sizeLabel(undefined)).toBe("");
  });

  it("inlineHtml échappe tout, ne pose que le gras, le code et les blocs", () => {
    expect(inlineHtml('<img src=x onerror="alert(1)"> **oui** `a<b`')).toBe(
      '&lt;img src=x onerror=&quot;alert(1)&quot;&gt; <strong>oui</strong> <code>a&lt;b</code>',
    );
    expect(inlineHtml("ligne 1\nligne 2")).toBe("ligne 1<br>ligne 2");
    expect(inlineHtml("avant\n```js\nlet a = '<x>';\n```\naprès")).toBe(
      'avant<pre class="chat-code"><code>let a = &#39;&lt;x&gt;&#39;;</code></pre>après',
    );
  });

  it("splitAttachments : les fichiers que le fil compose, seulement s'ils en ont l'air", () => {
    expect(splitAttachments("regarde ça [photo.jpg, devis-2026.pdf]")).toEqual({
      text: "regarde ça",
      files: ["photo.jpg", "devis-2026.pdf"],
    });
    expect(splitAttachments("[tableau-blanc.jpg]")).toEqual({ text: "", files: ["tableau-blanc.jpg"] });
    expect(splitAttachments("je dis [bonjour]")).toEqual({ text: "je dis [bonjour]", files: [] });
    expect(splitAttachments("collé[a.png]")).toEqual({ text: "collé[a.png]", files: [] });
  });
});

describe("threadMarkup", () => {
  const conversation: StoredMessage[] = [
    { text: "hello ça va ?", sender: "user", ts: at(4, 8, 12), id: 10, status: "sent" },
    { text: "salut. ça va\n\nun peu ailleurs", sender: "vtuber", ts: at(4, 8, 14), id: 11 },
    { text: "et toi ?", sender: "user", ts: at(4, 8, 18), id: 12, status: "sent" },
    { text: "pas encore parti", sender: "user", ts: at(4, 8, 19), cid: "c1", status: "pending" },
    { text: "refusé", sender: "user", ts: at(4, 8, 20), cid: "c2", status: "failed", reason: "trop de messages d'affilée" },
  ];

  it("ses bulles une par une, lu avant sa dernière réponse, envoyé après", () => {
    const html = threadMarkup(view(conversation));
    expect(html.match(/class="bubble"/g)?.length).toBe(6);
    expect(html).toContain('<div class="day"><span>Aujourd&#39;hui</span></div>');
    // « hello » est lu (elle a répondu après), « et toi ? » seulement envoyé
    const hello = html.indexOf("hello ça va");
    const toi = html.indexOf("et toi ?");
    expect(html.slice(hello, html.indexOf("</div></div>", hello) + 50)).toContain(" lu");
    expect(html.slice(toi, html.indexOf("msg-meta", toi) + 200)).toContain("envoyé");
    expect(html).toContain("en attente d'envoi");
    expect(html).toContain("refusé — trop de messages d&#39;affilée");
    expect(html).toContain('class="msg-meta ko"');
  });

  it("une réponse qui s'écrit encore ne montre que ses bulles déjà tapées", () => {
    const html = threadMarkup(view(conversation, { shown: (m, total) => (m.id === 11 ? 1 : total) }));
    expect(html).toContain("salut. ça va");
    expect(html).not.toContain("un peu ailleurs");
  });

  it("le texte du serveur est échappé partout", () => {
    const evil: StoredMessage[] = [
      { text: "<script>x()</script>", sender: "user", ts: at(4, 9, 0), id: 1, status: "sent" },
      { text: "<b>gras</b>", sender: "vtuber", ts: at(4, 9, 1), id: 2, notes: [{ kind: "location", text: "<i>Lille</i>", at: at(4, 8, 0) }] },
    ];
    const html = threadMarkup(view(evil));
    expect(html).not.toContain("<script>");
    expect(html).not.toContain("<b>gras");
    expect(html).not.toContain("<i>Lille");
    expect(html).toContain("Mika a regardé où tu es · &lt;i&gt;Lille&lt;/i&gt; · position de 08:00");
  });

  it("une opératrice juge ses réponses ; les autres comptes ne voient rien", () => {
    expect(threadMarkup(view(conversation))).not.toContain("data-verdict");
    const html = threadMarkup(view(conversation, { operator: true }));
    expect(html).toContain('data-verdict="ok" data-mid="11"');
    expect(html).toContain("/inspecteur/parole/11");
  });

  it("une réponse pro forme une seule bulle en Markdown, ses outils relus repliés au-dessus", () => {
    const pro: StoredMessage[] = [
      { text: "compare", sender: "user", ts: at(4, 13, 31), id: 20, status: "sent", mode: "pro", strand: "s1" },
      {
        text: "| Poste | Écart |\n|---|---:|\n| Sol | +290 € |\n\nUne **conclusion**.",
        sender: "vtuber",
        ts: at(4, 13, 32),
        id: 21,
        mode: "pro",
        strand: "s1",
        tools: [{ name: "forge_db_query", ok: true }, { name: "email_draft", ok: false }],
      },
    ];
    const html = threadMarkup(view(pro, { pro: true }));
    expect(html).toContain('class="bubble md"');
    expect(html).toContain("<table>");
    expect(html).toContain("<strong>conclusion</strong>");
    expect(html).toContain("2 outils · 1 échec");
    expect(html).toContain("mode pro");
  });

  it("sa carte de travail se pose après la question, ouverte tant qu'elle travaille", () => {
    let cards: WorkCard[] = [];
    for (const raw of [
      { type: "tool", episode: "e1", reply_to: 20, phase: "start", call_id: "a", name: "memory_search", args: '{"query": "Léa"}', at: 1000 },
      { type: "tool", episode: "e1", reply_to: 20, phase: "end", call_id: "a", name: "memory_search", args: "", ok: true, result: "3 souvenirs", duration_ms: 182, at: 1182 },
      { type: "tool", episode: "e1", reply_to: 20, phase: "start", call_id: "b", name: "email_read", args: "{}", at: 1200 },
    ]) {
      cards = withToolFrame(cards, toolFrame(raw)!);
    }
    const asked: StoredMessage[] = [{ text: "cherche", sender: "user", ts: at(4, 13, 31), id: 20, status: "sent", mode: "pro" }];
    const html = threadMarkup(view(asked, { pro: true, cards }));
    expect(html.indexOf("cherche")).toBeLessThan(html.indexOf("tools-card"));
    expect(html).toContain('class="tools-card live"');
    expect(html).toContain(" open>");
    expect(html).toContain("Au travail… · 2 outils");
    expect(html).toContain("<code>memory_search</code>");
    expect(html).toContain("182 ms");
    expect(html).toContain('<i class="spin"></i>');
    // repliée, elle garde son résumé
    expect(workCard(cards[0], true, false)).toContain("2 outils");
  });

  it("« Mika écrit… » : la ligne est là, cachée ou non", () => {
    expect(threadMarkup(view([]))).toContain("data-typing hidden");
    expect(threadMarkup(view([], { typing: true }))).not.toContain("data-typing hidden");
  });

  it("une recherche ne garde que ce qui la contient", () => {
    const html = threadMarkup(view(conversation, { filter: (m) => m.text.includes("toi") }));
    expect(html).toContain("et toi ?");
    expect(html).not.toContain("hello");
  });
});

describe("sentFile", () => {
  const api = "http://localhost:8001";
  it("une image en vignette, un fichier en lien, retiré : son nom barré", () => {
    const id = "0123456789abcdef0123456789abcdef";
    expect(sentFile({ id, name: "dessin.png", kind: "image", size: 2048, url: `/files/${id}`, available: true }, api)).toContain(
      `<img src="${api}/files/${id}"`,
    );
    expect(sentFile({ id, name: "courses.md", kind: "file", url: `/files/${id}`, available: true }, api)).toContain('download="courses.md"');
    expect(sentFile({ id, name: "vieux.md", kind: "file", url: `/files/${id}`, available: false }, api)).toContain("plus disponible");
  });
});

describe("approvalsMarkup", () => {
  const card = {
    id: 905,
    title: "Appeler « prevision » (meteo) : {\"ville\": \"<Lyon>\"}",
    text: "Service : meteo\nCe qui partira :\n{\"ville\": \"Lyon\"}",
    digest: "3f9c",
    blocked: "",
    expires_at: NOW + 4 * 60_000 - 5000,
  };

  it("la carte, échappée, ses boutons selon la connexion et l'échéance", () => {
    const state = withApprovals(withConnection(EMPTY_APPROVALS, "connected"), [card]);
    const html = approvalsMarkup(state, NOW, { note: null, auto: false, open: new Set() });
    expect(html).toContain("&lt;Lyon&gt;");
    expect(html).toContain("expire dans 4 min");
    expect(html).toMatch(/data-ap="accept" data-id="905">/);
    expect(html).not.toContain("Hors ligne");
  });

  it("hors ligne : les boutons éteints, et on le dit", () => {
    const state = withApprovals(EMPTY_APPROVALS, [card]);
    const html = approvalsMarkup(state, NOW, { note: null, auto: false, open: new Set() });
    expect(html).toContain("Hors ligne");
    expect(html).toMatch(/data-ap="accept" data-id="905" disabled/);
  });

  it("bloquée : seul le refus reste", () => {
    const state = withApprovals(withConnection(EMPTY_APPROVALS, "connected"), [{ ...card, blocked: "l'outil a changé" }]);
    const html = approvalsMarkup(state, NOW, { note: null, auto: false, open: new Set() });
    expect(html).toContain("Ne peut pas partir tel quel — l&#39;outil a changé");
    expect(html).toMatch(/data-ap="accept" data-id="905" disabled/);
    expect(html).toMatch(/data-ap="refuse" data-id="905">/);
  });
});

describe("les cartes qui se décident ailleurs (ADR 0191)", () => {
  it("relève la sorte de chaque carte dans la trame brute", () => {
    const kinds = cardKinds([
      { id: 1, capability: "email.send", draft: "d9" },
      { id: 2, capability: "teams.send", draft: "t3" },
      { id: 3, capability: "mcp.call" },
      { id: "x", capability: "email.send" },
      null,
    ]);
    expect([...kinds.keys()]).toEqual([1, 2, 3]);
    expect(kinds.get(3)).toEqual({ capability: "mcp.call", draft: "" });
    expect(cardKinds("pas une liste").size).toBe(0);
  });

  it("mène un brouillon de mail à Mail, une réponse Teams à Teams, et garde les autres cartes ici", () => {
    expect(elsewhere({ capability: "email.send", draft: "d 9" })?.href).toBe("#mail/messages/brouillon/d%209");
    expect(elsewhere({ capability: "teams.send", draft: "t3" })?.where).toBe("Teams");
    expect(elsewhere({ capability: "email.send", draft: "" })).toBeNull();
    expect(elsewhere({ capability: "mcp.call", draft: "" })).toBeNull();
    expect(elsewhere(undefined)).toBeNull();
  });

  it("dessine un lien, sans boutons qui décident", () => {
    const state = { ...EMPTY_APPROVALS, connected: true, cards: [
      { id: 7, title: "Répondre à Claire", text: "Bonjour", digest: "ab12", blocked: "", expires_at: null }] };
    const html = approvalsMarkup(state, Date.now(), {
      note: null, auto: false, open: new Set(), kinds: new Map([[7, { capability: "email.send", draft: "d9" }]]) });
    expect(html).toContain('href="#mail/messages/brouillon/d9"');
    expect(html).toContain("Ouvrir dans Mail");
    expect(html).not.toContain('data-ap="accept"');
  });
});

describe("ses cartes dans le fil (ADR 0196)", () => {
  // une ligne d'elle, telle que le fil relu la porte : la bulle 📍, un regard, un voyage, une sorte inconnue, une note vidée
  const notes = [
    { kind: "location", text: "rue Nationale, Lille", at: at(4, 14, 10) },
    { kind: "look", text: "Dormir · près de Talloires", at: at(4, 14, 18), ref: "812" },
    { kind: "trip", text: "Les Alpes en cinq jours", at: at(4, 14, 19), ref: "640" },
    { kind: "meteo", text: "Soleil", at: 1, ref: "9" },
    { kind: "map", text: "", at: 0 },
  ];
  const msg = {
    text: "je t'ai fait une première version", sender: "vtuber", ts: at(4, 14, 20), id: 900,
    notes: messageNotes(notes), maps: mapNotes(notes),
  } as StoredMessage;
  const cards = (m: StoredMessage) =>
    mapNotes((m as { maps?: unknown }).maps).map((n) => miniCard(slotKey(String(m.id), n), pendingMini(n), "© OpenStreetMap")).join("");

  it("montre un regard et un voyage en cartes miniatures qui s'ouvrent dans Carte ; la bulle 📍 ne change pas", () => {
    const html = threadMarkup(view([msg], { mapCards: cards }));
    expect(html).toContain("Mika a regardé où tu es · rue Nationale, Lille");
    expect(html).toContain('href="#carte/explorer/regard-812"');
    expect(html).toContain('href="#carte/voyages/640"');
    expect(html).toContain('data-mini="900|trip:640"');
    expect(html.match(/class="msg-map/g)).toHaveLength(2); // ni la sorte inconnue, ni la note vidée
    expect(html.indexOf("msg-map")).toBeGreaterThan(html.indexOf("première version")); // sous ses bulles
  });

  it("attend la fin de ses bulles, comme ses fichiers", () => {
    const html = threadMarkup(view([{ ...msg, text: "un\n\ndeux" } as StoredMessage], { mapCards: cards, shown: () => 1 }));
    expect(html).not.toContain("msg-map");
  });
});
