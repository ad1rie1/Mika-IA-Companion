/**
 * Ce que chaque source demande qu'on cite, partout où elle se montre (ADR 0259, 0269 ; le contrat :
 * `output/carte-avis/SUIVI.md`, « Les attributions à afficher ») : une vignette de liste montre son auteur (lié) et sa
 * licence sur la ligne, lisibles — sans crédit, pas de vignette ; une photo de l'office de tourisme montre sa licence
 * dans la bande d'une fiche ; « Google Maps » se lit partout où une note Google se montre (une liste, quelle que soit sa
 * couverture ; un regard de Mika ; l'étiquette d'une fiche avant son bloc Google). Un lieu d'un regard garde sa note.
 */
import { describe, expect, it } from "vitest";
import type { EventItem, Place } from "../../api/carte";
import { eventItem } from "./agenda";
import { photoBand, placeTags } from "./fiche";
import { regardPlace } from "./format";
import { explorerMarkup, placeItem, type ExplorerView } from "./view";

const G1 = "p:3f1c9a0e5b7d2c4e6f8a1b3c5d7e9f02";
const D1 = "p:8e2d4c6b0a1f3e5d7c9b2a4f6e8d0c13";
const never = () => false;
const NOW = new Date(2026, 10, 21, 12, 0).getTime();
const AUTHOR = "https://www.google.com/maps/contrib/100000000000000000001";

/** Le texte que l'on voit, sans les balises. */
function text(html: string): string {
  return html.replace(/<[^>]*>/g, "").replace(/&#39;/g, "'").replace(/&amp;/g, "&").replace(/\s+/g, " ");
}

function magmatic(extra: Partial<Place> = {}): Place {
  return { id: "l22871", name: "Magmatic", kind: "restaurant", kind_fr: "Restaurant", category: "manger", lat: 50.63712, lon: 3.06455,
    town: "Lille", distance_m: 240, along_m: null, osm: "n4021153781", cuisine: "Pizza", rating: 4.8, reviews: 15235, price: "€€", ...extra };
}

const CREDITED: Partial<Place> = { photo: G1, photo_source: "google", photo_credit: "Camille R.", photo_credit_url: AUTHOR };

function show(extra: Partial<ExplorerView> = {}): ExplorerView {
  return { info: null, q: "", cat: "manger", where: "moi", places: [magmatic()], addresses: [], error: "", addrError: "", loading: false,
    searched: true, sel: null, regard: null, hint: "", map: "", seen: never, now: NOW, ...extra };
}

function concert(extra: Partial<EventItem> = {}): EventItem {
  return { id: "e:450c81b3-6ffa-3d4e-9c1b-2a7f0e5d8c41", name: "Éclats du rire !", start: "2026-11-21T19:00+01:00", end: "2026-11-21T22:00+01:00",
    when_text: "sam. 21 nov. · 19:00–22:00", place: "L'Aéronef, Lille", lat: 50.636554, lon: 3.074244, distance_m: 780, themes: ["spectacles"],
    free: false, price: "12 €", photo: "", ...extra };
}

describe("une vignette dans une liste cite sa photo sur la ligne (R2-W02)", () => {
  it("une photo de Google : son auteur, lié, et « Google Maps », lisibles hors du texte alternatif", () => {
    const html = placeItem(magmatic(CREDITED), "l22871", { on: false, mika: false, where: "moi", seen: never });
    expect(html).toContain("<img");
    expect(text(html)).toContain("Photo : Camille R. · Google Maps");
    expect(html).toContain(`href="${AUTHOR}"`);
    // le lien de l'auteur n'est pas dans le bouton de la ligne (un lien dans un bouton ne s'ouvre pas)
    expect(html.indexOf(`href="${AUTHOR}"`)).toBeGreaterThan(html.indexOf("</button>"));
  });

  it("sans crédit — un regard de Mika, un serveur d'avant —, pas de vignette : l'icône de la catégorie", () => {
    const html = placeItem(magmatic({ photo: G1 }), "l22871", { on: false, mika: true, where: "moi", seen: never });
    expect(html).not.toContain("<img");
    expect(html).toContain("pl-dot");
    expect(text(html)).not.toContain("Photo :");
  });

  it("un événement et sa photo de l'office de tourisme : son auteur et sa licence", () => {
    const opts = { on: false, mika: false, themes: new Map<string, string>(), seen: never, inDay: true };
    const html = eventItem(concert({ photo: D1, photo_source: "datatourisme", photo_credit: "Hello Lille", photo_credit_url: "", photo_licence: "CC BY-NC-ND 4.0" }), opts);
    expect(html).toContain("<img");
    expect(text(html)).toContain("Photo : Hello Lille · CC BY-NC-ND 4.0 · Office de tourisme");
    expect(eventItem(concert({ photo: D1 }), opts)).not.toContain("<img");
  });
});

describe("la bande d'une fiche cite la licence d'une photo de l'office de tourisme (R2-W03)", () => {
  it("son auteur, puis sa licence, sur la photo", () => {
    const band = photoBand({ scene: { pins: [], lines: [] }, title: "Où est Magmatic", dist: "", seen: never, photos: [
      { ref: D1, path: "", source: "datatourisme", credit: "Hello Lille", credit_url: "", licence: "CC BY-NC-ND 4.0", caption: "", width: null, height: null },
      { ref: G1, path: "", source: "google", credit: "Camille R.", credit_url: AUTHOR, licence: "", caption: "", width: 800, height: 600 },
    ] });
    expect(text(band)).toContain("Hello Lille · CC BY-NC-ND 4.0");
    expect(text(band)).toContain("Camille R.");
  });
});

describe("« Google Maps » partout où une note Google se montre (R2-W04)", () => {
  it("une liste notée le dit, quelle que soit sa couverture", () => {
    for (const coverage of [null, { ready: true, cells: 0, loaded: 0, oldest: 0, note: "" },
      { ready: true, cells: 4, loaded: 1, oldest: 0, note: "Les notes de cet endroit ne sont pas encore toutes lues." }]) {
      expect(text(explorerMarkup(show({ coverage })))).toContain("Google Maps");
    }
    // la date de lecture et la note restent
    const read = text(explorerMarkup(show({ coverage: { ready: true, cells: 1, loaded: 1, oldest: new Date(2026, 10, 18, 8, 0).getTime(), note: "" } })));
    expect(read).toContain("Notes Google Maps lues le 18 novembre");
    // aucune note dans la liste, aucune couverture : rien à citer
    expect(text(explorerMarkup(show({ places: [magmatic({ rating: undefined, reviews: undefined })], coverage: null })))).not.toContain("Google Maps");
  });

  it("un regard de Mika aux lieux notés le dit aussi", () => {
    const html = explorerMarkup(show({ regard: { title: "Manger · Vieux-Lille", route: false, links: [] }, coverage: null }));
    expect(text(html)).toContain("4,8");
    expect(text(html)).toContain("Google Maps");
  });

  it("l'étiquette de note d'une fiche, avant son bloc Google", () => {
    expect(text(placeTags(magmatic(), null))).toContain("Google Maps");
  });

  it("un lieu d'un regard garde sa note, son prix, sa cuisine (R2-W08) — et son identifiant entier (R2-M01)", () => {
    const p = regardPlace({ id: "t:6b0e2f4a-8c1d-3e5f-9a7b-0c2d4e6f8a10", name: "Le Lys", kind: "restaurant", kind_fr: "Restaurant",
      category: "manger", lat: 50.64, lon: 3.06, town: "Lille", distance_m: null, along_m: null, rating: 4.6, reviews: 312, price: "€€",
      cuisine: "Française", photo: G1, tags: ["terrasse"] });
    expect(p).toMatchObject({ id: "t:6b0e2f4a-8c1d-3e5f-9a7b-0c2d4e6f8a10", rating: 4.6, reviews: 312, price: "€€", cuisine: "Française", photo: G1, tags: ["terrasse"] });
    expect(text(placeItem(p, p.id, { on: false, mika: true, where: "moi", seen: never }))).toContain("4,6");
  });
});
