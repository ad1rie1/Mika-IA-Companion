import { describe, expect, it } from "vitest";
import { messageNotes } from "@web/ui/messageNotes";
import type { Regard, Trip } from "../api/carte";
import { goneMini, miniCard, pendingMini, regardMini, tripMini } from "./cards";
import { drawnScene } from "./drawn";
import { MiniMaps, MiniPool, MiniStore, slotKey, slotNote } from "./minis";
import { mapNotes, noteRoute, regardOf, sameMapNotes } from "./notes";
import { encodePolyline6 } from "./polyline";
import { cleanScene, linesGeoJson, sceneBounds, sceneKey, straightLine } from "./scene";

const RAW = [
  { kind: "location", text: "rue Nationale, Lille", at: 1790601490000 },
  { kind: "look", text: "Dormir · près de Talloires", at: 1790601500000, ref: "812" },
  { kind: "map", text: "Trois campings au bord du lac", at: 1790601510000, ref: "815" },
  { kind: "trip", text: "Les Alpes en cinq jours", at: 1790601520000, ref: "640" },
  { kind: "meteo", text: "Soleil", at: 1, ref: "9" }, // une sorte inconnue
  { kind: "trip", text: "", at: 0 }, // un voyage supprimé : vidé, rien à ouvrir
  { kind: "look", text: "Oublié", at: 5 }, // pas de ref : rien à ouvrir
  { kind: "look", text: "illisible", at: 5, ref: "../../x" },
];

describe("les notes de carte d'un de ses messages (ADR 0196)", () => {
  it("garde look, map et trip avec ce qu'ils ouvrent ; ignore une sorte inconnue et une note vidée", () => {
    const notes = mapNotes(RAW);
    expect(notes.map((n) => [n.kind, n.ref])).toEqual([["look", "812"], ["map", "815"], ["trip", "640"]]);
    expect(notes[0]).toEqual({ kind: "look", text: "Dormir · près de Talloires", at: 1790601500000, ref: "812" });
    // la bulle 📍 reste celle du client web, inchangée
    expect(messageNotes(RAW).map((n) => n.kind)).toEqual(["location"]);
  });

  it("une liste illisible ne fait rien perdre", () => {
    expect(mapNotes(null)).toEqual([]);
    expect(mapNotes("trip:640")).toEqual([]);
    expect(mapNotes([null, 3, { kind: "trip", text: "Week-end", ref: 7 }])).toEqual([{ kind: "trip", text: "Week-end", at: 0, ref: "7" }]);
    expect(mapNotes([RAW[1], RAW[1]])).toHaveLength(1); // redite : une fois
  });

  it("s'ouvre dans l'écran Carte : le voyage, ou le regard dans Explorer", () => {
    expect(noteRoute({ kind: "trip", ref: "640" })).toBe("#carte/voyages/640");
    expect(noteRoute({ kind: "look", ref: "812" })).toBe("#carte/explorer/regard-812");
    expect(regardOf("regard-812")).toBe("812");
    expect(regardOf("alpes")).toBeNull();
    expect(sameMapNotes(mapNotes(RAW), mapNotes(RAW))).toBe(true);
    expect(sameMapNotes(mapNotes(RAW), [])).toBe(false);
  });
});

const TRIP: Trip = {
  id: "640", title: "Les Alpes", start: "2027-04-03", mode: "voiture", avoid: [], updated: 1, mika: true,
  days: [
    { n: 1, date: "2027-04-03", stops: [
      { id: "641", name: "Lille", kind: "Ta position", lat: 50.637, lon: 3.063, note: "", by: "toi" },
      { id: "642", name: "Cathédrale de <Reims>", kind: "À voir", lat: 49.258, lon: 4.032, note: "vingt minutes", by: "mika" },
    ] },
    { n: 2, date: "2027-04-04", stops: [{ id: "643", name: "Annecy", kind: "", lat: 45.899, lon: 6.129, note: "", by: "toi" }] },
  ],
};

describe("la carte miniature", () => {
  it("un voyage : ses arrêts numérotés, roses quand elle les a ajoutés, reliés (jamais un trajet demandé)", () => {
    const mini = tripMini(TRIP);
    expect(mini.title).toBe("Voyage · Les Alpes");
    expect(mini.sub).toBe("2 jours · 3 arrêts · 1 de Mika");
    expect(mini.href).toBe("#carte/voyages/640");
    expect(mini.scene.pins.map((p) => [p.label, !!p.mika])).toEqual([["1", false], ["2", true], ["3", false]]);
    expect(mini.scene.lines).toHaveLength(1);
    expect(mini.scene.lines[0].straight).toBe(true);
  });

  it("un regard : ses lieux, ou le trajet qu'elle a gardé ; une carte : son tracé ou ses lieux reliés", () => {
    const places: Regard = { kind: "look", title: "Dormir · près de Talloires", what: "lieux", route: null, trip: "", at: 1,
      places: [{ id: "l3", name: "Camping de l'Horizon", lat: 45.856, lon: 6.169 }, { id: "l4", name: "La Chèvrerie", lat: 45.81, lon: 6.23 }] };
    const mini = regardMini("812", places);
    expect(mini.sub).toBe("Mika a cherché · 2 lieux");
    expect(mini.href).toBe("#carte/explorer/regard-812");
    expect(mini.scene.pins.every((p) => p.mika)).toBe(true);
    const route: Regard = { kind: "look", title: "Annecy → Chambéry", what: "trajet", trip: "", at: 1,
      route: { mode: "voiture", distance_m: 58_015, duration_s: 3200, shape: encodePolyline6([[45.9, 6.13], [45.8, 6.05], [45.56, 5.92]]) },
      places: [{ name: "Annecy", lat: 45.9, lon: 6.13 }, { name: "Chambéry", lat: 45.56, lon: 5.92 }] };
    const r = regardMini("820", route);
    expect(r.href).toBe("#carte/itineraire/regard-820");
    expect(r.sub).toBe("Mika a calculé le trajet · 58 km · 53 min en voiture");
    expect(r.scene.lines[0].points).toHaveLength(3);
    expect(r.scene.pins.map((p) => p.label)).toEqual(["A", "B"]);
    const shown: Regard = { kind: "map", title: "Le tour du lac", what: "", trip: "640", at: 1, route: { mode: "velo" },
      places: places.places };
    const m = regardMini("830", shown);
    expect(m.href).toBe("#carte/voyages/640"); // la carte d'un voyage s'ouvre sur lui
    expect(m.scene.lines[0].straight).toBe(true);
  });

  it("le balisage : un lien vers l'écran Carte, son plan dessiné, tout texte échappé, la mention sans lien", () => {
    const html = miniCard(slotKey("812", { kind: "trip", ref: "640" }), tripMini(TRIP), "© OpenStreetMap");
    expect(html).toContain('href="#carte/voyages/640"');
    expect(html).toContain('data-mini="812|trip:640"');
    expect(html).toContain("<svg class=\"drawn-map\"");
    expect(html).not.toContain("<Reims>");
    expect(html).toContain('<span class="mm-attrib">© OpenStreetMap</span>');
    expect(html.match(/<a /g)).toHaveLength(1); // aucun lien dans le lien
    const pending = pendingMini({ kind: "look", text: "Dormir <près>", at: 0, ref: "812" });
    expect(miniCard("1|look:812", pending, "© OpenStreetMap")).toContain("Dormir &lt;près&gt;");
    expect(goneMini({ kind: "trip", text: "", at: 0, ref: "640" }).gone).toBe(true);
  });

  it("la clé d'une miniature dit ce qu'elle montre", () => {
    expect(slotNote("812|trip:640")).toEqual({ kind: "trip", ref: "640" });
    expect(slotNote("t17|look:9")).toEqual({ kind: "look", ref: "9" });
    expect(slotNote("812|meteo:3")).toBeNull();
  });

  it("au plus quatre cartes vivantes : une place rendue se reprend", () => {
    const pool = new MiniPool(4);
    const granted = ["a", "b", "c", "d", "e", "f"].map((k) => pool.take(k));
    expect(granted).toEqual([true, true, true, true, false, false]);
    expect(pool.take("a")).toBe(true); // elle l'a déjà
    pool.give("b");
    expect(pool.take("e")).toBe(true);
    expect(pool.take("f")).toBe(false);
    expect(pool.size).toBe(4);
  });

  it("ce qu'elles montrent se lit une fois pour la page : un changement vu par le chat se relit dans l'écran Carte", async () => {
    const store = new MiniStore();
    let reads = 0;
    const load = async () => ({ ...tripMini({ ...TRIP, updated: 100 + reads }), sub: `lu ${++reads}` });
    const chat = new MiniMaps(load, store);
    const carte = new MiniMaps(load, store);
    const note = { kind: "trip" as const, ref: "640" };
    await store.read("trip:640", load);
    await store.read("trip:640", load);
    expect(reads).toBe(1);
    expect(carte.dataOf(note)?.sub).toBe("lu 1");
    chat.invalidate(note); // elle a changé le voyage, dit le chat
    expect(store.fresh("trip:640")).toBe(false);
    expect(carte.dataOf(note)?.sub).toBe("lu 1"); // l'ancienne se montre jusqu'à la relecture
    await store.read("trip:640", load);
    expect(reads).toBe(2);
    expect(store.fresh("trip:640")).toBe(true);
  });

  it("une liste qui dit un voyage changé depuis le fait relire ; une lecture partie avant un changement ne le rajeunit pas", async () => {
    const store = new MiniStore();
    let updated = 100;
    let reads = 0;
    const load = async () => {
      reads += 1;
      return tripMini({ ...TRIP, updated });
    };
    await store.read("trip:640", load);
    expect(store.peek("trip:640", 100)?.version).toBe(100);
    expect(store.fresh("trip:640")).toBe(true); // la même version : rien à relire
    updated = 200;
    store.peek("trip:640", 200); // la liste dit plus récent (changé ailleurs)
    expect(store.fresh("trip:640")).toBe(false);
    const pending = store.read("trip:640", load);
    store.invalidate("trip:640"); // changé pendant la lecture
    await pending;
    expect(store.fresh("trip:640")).toBe(false);
    await store.read("trip:640", load);
    expect(reads).toBe(3);
    expect(store.fresh("trip:640")).toBe(true);
    expect(store.peek("trip:640", 150)?.version).toBe(200); // une liste plus vieille ne fait rien relire
    expect(store.fresh("trip:640")).toBe(true);
  });
});

describe("la scène et son plan dessiné", () => {
  it("écarte ce qui n'est pas sur la Terre, et cadre ce qui reste", () => {
    const scene = cleanScene({ pins: [{ id: "a", lat: 45.9, lon: 6.1 }, { id: "x", lat: 200, lon: 0 }], lines: [{ points: [[45.9, 6.1]] }] });
    expect(scene.pins.map((p) => p.id)).toEqual(["a"]);
    expect(scene.lines).toEqual([]); // une ligne d'un point n'en est pas une
    const b = sceneBounds(scene)!;
    expect(b[2] - b[0]).toBeCloseTo(0.02, 6);
    expect(sceneBounds({ pins: [], lines: [] })).toBeNull();
  });

  it("des tracés en GeoJSON (lon, lat), et une empreinte qui suit ce qui change", () => {
    const line = straightLine([[45.9, 6.1], [45.5, 5.9]])!;
    const geo = linesGeoJson({ pins: [], lines: [line] });
    expect(geo.features[0].geometry).toEqual({ type: "LineString", coordinates: [[6.1, 45.9], [5.9, 45.5]] });
    expect(sceneKey({ pins: [], lines: [line] })).toBe(sceneKey({ pins: [], lines: [{ ...line }] }));
    expect(sceneKey({ pins: [], lines: [line] })).not.toBe(sceneKey({ pins: [], lines: [{ ...line, points: [[45.9, 6.1], [45.4, 5.9]] }] }));
  });

  it("le plan : ses épingles à leur place, ses noms échappés", () => {
    const svg = drawnScene({ pins: [{ id: "a", lat: 45.9, lon: 6.1, label: "1" }, { id: "b", lat: 45.5, lon: 5.9, label: "<b>", mika: true }],
      lines: [{ points: [[45.9, 6.1], [45.5, 5.9]] }] }, { width: 340, height: 150, title: "Le <lac>" });
    expect(svg).toContain('aria-label="Le &lt;lac&gt;"');
    expect(svg).toContain('class="dm-pin mika"');
    expect(svg).toContain("&lt;b&gt;");
    expect(svg).not.toContain("<b>");
    expect(svg).toContain('class="dm-line"');
    expect(drawnScene({ pins: [], lines: [] }, { width: 340, height: 150, title: "Vide" })).not.toContain("dm-pin");
  });
});
