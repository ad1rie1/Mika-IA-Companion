import { describe, expect, it } from "vitest";
import type { EventFiche, PlaceFiche, ReviewsPart } from "../../api/carte";
import { ApiError } from "../../api/moi";
import { eventFicheMarkup, googleBlock, photoBand, placeFicheMarkup, priceWords, viewerMarkup, type EventFicheView, type PlaceFicheView } from "./fiche";
import {
  countWords,
  coverageLine,
  outLink,
  paragraphs,
  photoImg,
  ratingInline,
  ratingWords,
  readWhen,
  safeHref,
  shownPhotos,
  stars,
  telHref,
} from "./sources";

const API = "http://localhost:8001";
/** Le 20 novembre 2026, 23:00 (heure locale). */
const NOW = new Date(2026, 10, 20, 23, 0).getTime();
const G1 = "p:3f1c9a0e5b7d2c4e6f8a1b3c5d7e9f02";
const D1 = "p:8e2d4c6b0a1f3e5d7c9b2a4f6e8d0c13";
const never = () => false;

/** La fiche complète du contrat (`output/carte-avis/SUIVI.md`, « Contrat pour les clients »). */
function fiche(extra: Partial<PlaceFiche> = {}): PlaceFiche {
  return {
    place: { id: "l22871", name: "Magmatic", kind: "restaurant", kind_fr: "Restaurant", category: "manger", lat: 50.63712, lon: 3.06455,
      town: "Lille", distance_m: null, along_m: null, osm: "n4021153781", open_state: "open", open_text: "Ouvert · ferme à 22:30",
      cuisine: "Pizza", rating: 4.8, reviews: 15235, price: "€€", photo: G1, tags: ["terrasse", "vegetarien", "emporter"] },
    osm: { id: "n4021153781", url: "https://www.openstreetmap.org/node/4021153781", address: "13 rue de la Monnaie, Lille",
      phone: "+33 3 20 00 00 00", website: "https://magmatic.example", email: "", hours: "Mo-Su 12:00-14:30,19:00-22:30",
      hours_text: "tous les jours : 12:00–14:30, 19:00–22:30",
      facts: [{ label: "Cuisine", value: "Pizza" }, { label: "Horaires", value: "tous les jours : 12:00–14:30, 19:00–22:30" }, { label: "Terrasse", value: "oui" }],
      wikidata: "", wikipedia: "", extract: "2026-11-16", attribution: "© les contributeurs d'OpenStreetMap", licence_url: "https://www.openstreetmap.org/copyright" },
    tourism: { id: "t:6b0e2f4a-8c1d-3e5f-9a7b-0c2d4e6f8a10", description: "Pizzeria napolitaine du Vieux-Lille.\nPâte maturée 48 heures.",
      labels: ["Qualité Tourisme"], prices: "Pizzas de 11 à 19 €", contacts: [{ label: "Téléphone", value: "+33 3 20 00 00 00" }],
      author: "Hello Lille", updated: "2025-06-03", url: "https://data.datatourisme.fr/6b0e2f4a",
      photos: [{ ref: D1, path: `/api/moi/carte/photo/${D1}`, source: "datatourisme", credit: "Hello Lille", credit_url: "", licence: "CC BY-NC-ND 4.0", caption: "", width: null, height: null }],
      attribution: "DATAtourisme · Hello Lille, mis à jour le 3 juin 2025", licence: "Licence Ouverte 2.0", licence_url: "https://www.etalab.gouv.fr/licence-ouverte-open-licence/" },
    reviews: google(),
    events: [{ id: "e:450c81b3-6ffa-3d4e-9c1b-2a7f0e5d8c41", name: "Éclats du rire !", start: "2026-11-21T19:00:00+01:00", end: "2026-11-21T22:00:00+01:00",
      when_text: "sam. 21 nov. · 19:00–22:00", place: "L'Aéronef, Lille", lat: 50.636554, lon: 3.074244, distance_m: 780, themes: ["spectacles"],
      free: false, price: "12/8€ - Gratuit moins de 18 ans", photo: "" }],
    ...extra,
  };
}

function google(extra: Partial<ReviewsPart> = {}): ReviewsPart {
  return {
    source: "google", source_label: "Google Maps", found: true, id: "ChIJMagmaticExample", rating: 4.8, count: 15235, price: "€€", price_range: "30–50 €",
    summary: "Pizzas au feu de bois dans une salle animée.", facts: [{ label: "Végétarien", value: "oui (selon Google)" }],
    reviews: [{ rating: 5, text: "Pâte légère, service rapide.\nOn reviendra.", author: "Camille R.", author_url: "https://www.google.com/maps/contrib/100000000000000000001",
      at: 1793648460000, relative: "il y a 2 semaines", language: "fr" }],
    photos: [{ ref: G1, path: `/api/moi/carte/photo/${G1}`, source: "google", credit: "Camille R.", credit_url: "https://www.google.com/maps/contrib/100000000000000000001",
      licence: "", caption: "", width: 800, height: 600 }],
    url: "https://maps.google.com/?cid=1234567890", cached: new Date(2026, 10, 20, 22, 0).getTime(), note: "", ...extra,
  };
}

function view(extra: Partial<PlaceFicheView> = {}): PlaceFicheView {
  return { place: null, fiche: fiche(), loading: false, error: null, gone: false, refreshing: false, refreshNote: "",
    back: { href: "#carte/explorer", label: "Les résultats" }, mika: false, here: { lat: 50.6365, lon: 3.0635 }, seen: never, now: NOW, ...extra };
}

const EVIL = '<script>alert(1)</script><img src=x onerror="alert(2)">';

describe("les liens vers le dehors, les numéros, les textes", () => {
  it("http et https seulement : ni javascript:, ni data:, ni un chemin ; un domaine nu devient https", () => {
    expect(safeHref("https://maps.google.com/?cid=1")).toBe("https://maps.google.com/?cid=1");
    expect(safeHref("http://exemple.fr")).toBe("http://exemple.fr/");
    expect(safeHref("magmatic.fr")).toBe("https://magmatic.fr/");
    expect(safeHref("javascript:alert(1)")).toBe("");
    expect(safeHref(" JaVaScRiPt:alert(1)")).toBe("");
    expect(safeHref("data:text/html,<b>x</b>")).toBe("");
    expect(safeHref("//evil.example/x")).toBe("");
    expect(safeHref("/api/moi/auth/logout")).toBe("");
    expect(safeHref("java\nscript:alert(1)")).toBe("");
    expect(safeHref("")).toBe("");
  });

  it("un lien s'ouvre à côté, sans référent ; sans adresse sûre, le texte reste du texte", () => {
    expect(outLink("https://x.example/a", "Camille <R>")).toBe('<a href="https://x.example/a" target="_blank" rel="noopener noreferrer nofollow">Camille &lt;R&gt;</a>');
    expect(outLink("javascript:alert(1)", "Camille")).toBe("Camille");
    expect(outLink('https://x.example/"onmouseover="alert(1)', "x")).not.toContain('"onmouseover');
  });

  it("un numéro à appeler : ses chiffres, le + du début gardé", () => {
    expect(telHref("+33 3 20 00 00 00")).toBe("tel:+33320000000");
    expect(telHref("03.20.00.00.00")).toBe("tel:0320000000");
    expect(telHref("javascript:alert(1)")).toBe("");
    expect(telHref("")).toBe("");
  });

  it("un texte en paragraphes, chacun échappé", () => {
    expect(paragraphs("Pâte légère.\n\nOn reviendra.")).toBe("<p>Pâte légère.</p><p>On reviendra.</p>");
    const evil = paragraphs(EVIL);
    expect(evil).not.toContain("<script>");
    expect(evil).not.toContain("<img");
    expect(evil).toContain("&lt;script&gt;");
  });

  it("une note à la française, des étoiles et le nombre d'avis", () => {
    expect(ratingWords(4.8)).toBe("4,8");
    expect(ratingWords(4)).toBe("4");
    expect(countWords(15235)).toBe("15\u00a0235 avis");
    expect(stars(4.5)).toContain('aria-label="4,5 sur 5"');
    expect((stars(4.5).match(/class="on"/g) ?? []).length).toBe(4);
    expect(stars(4.5)).toContain('class="half"');
    expect(stars(null)).toBe("");
    expect(ratingInline(4.8, 15235)).toContain("4,8");
    expect(ratingInline(4.8, 15235)).toContain("(15\u00a0235)");
    expect(ratingInline(undefined, 3)).toBe("");
  });

  it("quand une source a été lue, et la ligne de couverture d'une liste", () => {
    expect(readWhen(new Date(2026, 10, 20, 22, 0).getTime(), NOW)).toBe("aujourd'hui à 22:00");
    expect(readWhen(new Date(2026, 10, 19, 9, 10).getTime(), NOW)).toBe("hier à 09:10");
    expect(readWhen(new Date(2026, 10, 14, 9, 10).getTime(), NOW)).toBe("le 14 novembre");
    const read = { ready: true, cells: 1, loaded: 1, oldest: new Date(2026, 10, 18, 8, 0).getTime(), note: "" };
    expect(coverageLine(read, "Notes Google Maps lues", NOW)).toBe("Notes Google Maps lues le 18 novembre");
    // la note du serveur, telle quelle
    expect(coverageLine({ ...read, note: "Les notes de cet endroit ne sont pas encore toutes lues : elles le seront au préchargement ou ce soir." }, "x", NOW))
      .toBe("Les notes de cet endroit ne sont pas encore toutes lues : elles le seront au préchargement ou ce soir.");
    expect(coverageLine({ ready: false, cells: 0, loaded: 0, oldest: 0, note: "" }, "x", NOW)).toBe("");
    expect(coverageLine(null, "x", NOW)).toBe("");
  });

  it("une photo : de ce serveur seul, posée tout de suite si elle s'est déjà montrée, sinon en attente", () => {
    const waiting = photoImg(G1, "Le welsh", never);
    expect(waiting).toContain(`data-src="${API}/api/moi/carte/photo/${G1}"`);
    expect(waiting).not.toMatch(/\ssrc=/);
    expect(photoImg(G1, "", () => true)).toContain(`src="${API}/api/moi/carte/photo/${G1}"`);
    expect(photoImg("https://lh3.googleusercontent.com/a.jpg", "x", never)).toBe("");
    expect(photoImg(G1, EVIL, never)).not.toContain("<script>");
    // celles qu'on montre : l'office de tourisme d'abord, puis Google, sans doublon ni référence fausse
    const f = fiche();
    const bad = { ...f.reviews!.photos[0], ref: "https://evil.example/a.jpg" };
    expect(shownPhotos(f.tourism!.photos, [...f.reviews!.photos, bad, f.reviews!.photos[0]]).map((p) => p.ref)).toEqual([D1, G1]);
  });
});

describe("la fiche d'un lieu", () => {
  it("la bande : le plan d'abord, puis les photos, chacune avec sa source et son crédit lié", () => {
    const html = placeFicheMarkup(view());
    const band = html.slice(html.indexOf("ph-band"), html.indexOf("fiche-tags"));
    expect(band.indexOf("data-plan")).toBeLessThan(band.indexOf('data-photo="0"'));
    expect(band).toContain('data-photo="1"');
    expect(band).toContain("Office de tourisme");
    expect(band).toContain("Google Maps");
    expect(band).toContain('<a href="https://www.google.com/maps/contrib/100000000000000000001" target="_blank" rel="noopener noreferrer nofollow">Camille R.</a>');
    expect(band).toContain("2 photos");
    // les photos attendent de paraître : aucune ne se charge d'un coup
    expect(band).not.toMatch(/<img[^>]*\ssrc=/);
  });

  it("sans photo, le plan seul", () => {
    const f = fiche({ tourism: null, reviews: google({ photos: [] }) });
    const html = placeFicheMarkup(view({ fiche: f }));
    expect(html).toContain('class="ph-band solo"');
    expect(html).toContain("data-plan");
    expect(html).not.toContain("data-photo=");
  });

  it("les étiquettes : ouvert, la cuisine, le prix, la note ; les actions, Appeler et Site compris", () => {
    const html = placeFicheMarkup(view());
    expect(html).toContain('<span class="tag ok">');
    expect(html).toContain("Ouvert · ferme à 22:30");
    expect(html).toContain('<span class="tag">Pizza</span>');
    expect(html).toContain('<span class="tag">€€</span>');
    expect(html).toContain("data-go-route");
    expect(html).toContain("data-add-trip");
    expect(html).toContain("data-ask-place");
    expect(html).toContain('href="tel:+33320000000"');
    expect(html).toContain('href="https://magmatic.example/"');
    expect(html).toContain("Appeler");
    expect(html).toContain(">Site</a>");
  });

  it("Google Maps : la note, les avis, le prix et sa fourchette, le résumé, ce qu'il ajoute, chaque avis avec son auteur, son lien et sa date", () => {
    const html = googleBlock(google(), { refreshing: false, refreshNote: "", now: NOW });
    expect(html).toContain('<span class="g-logo">Google Maps</span>');
    expect(html).toContain('href="https://maps.google.com/?cid=1234567890"');
    expect(html).toContain("Voir sur Google Maps");
    expect(html).toContain("<b>4,8</b>");
    expect(html).toContain("15\u00a0235 avis");
    expect(html).toContain("€€ · 30–50 €");
    expect(html).toContain("Pizzas au feu de bois dans une salle animée.");
    expect(html).toContain("<dt>Végétarien</dt><dd>oui (selon Google)</dd>");
    expect(html).toContain('class="g-author" href="https://www.google.com/maps/contrib/100000000000000000001"');
    expect(html).toContain("· il y a 2 semaines");
    expect(html).toContain("<p>Pâte légère, service rapide.</p><p>On reviendra.</p>");
    expect(html).toContain("Lu aujourd&#39;hui à 22:00 · gardé sur ce serveur");
    expect(html).toContain("data-refresh");
    // Google ne donne ni répartition ni sous-notes, et Tripadvisor n'est plus nulle part
    expect(html).not.toMatch(/Excellent|Très bon|Rapport qualité|Tripadvisor/);
  });

  it("un long avis se replie, « Lire la suite » le déplie ; un court, non", () => {
    const long = googleBlock(google({ reviews: [{ ...google().reviews[0], text: "Très bien. ".repeat(60) }] }), { refreshing: false, refreshNote: "", now: NOW });
    expect(long).toContain('class="g-review long"');
    expect(long).toContain("data-review-more");
    expect(long).toContain("Lire la suite");
    const short = googleBlock(google(), { refreshing: false, refreshNote: "", now: NOW });
    expect(short).not.toContain("data-review-more");
  });

  it("un avis, un nom, un résumé, un crédit qui portent du HTML restent du texte ; un lien javascript: n'est pas un lien", () => {
    const r = google({
      summary: EVIL,
      facts: [{ label: EVIL, value: EVIL }],
      reviews: [{ rating: 1, text: EVIL, author: EVIL, author_url: "javascript:alert(3)", at: 1, relative: EVIL, language: "fr" }],
      photos: [{ ...google().photos[0], credit: EVIL, credit_url: "javascript:alert(4)", caption: EVIL }],
      url: "javascript:alert(5)",
    });
    const f = fiche({ place: { ...fiche().place, name: EVIL, cuisine: EVIL, open_text: EVIL }, reviews: r,
      tourism: { ...fiche().tourism!, description: EVIL, labels: [EVIL], prices: EVIL, attribution: EVIL, url: "javascript:alert(6)" },
      osm: { ...fiche().osm!, address: EVIL, website: "javascript:alert(7)", facts: [{ label: "Horaires", value: EVIL }] } });
    const html = placeFicheMarkup(view({ fiche: f }));
    expect(html).not.toContain("<script>");
    // échappé, un attribut n'en est plus un : ni guillemet ni chevron ne sortent du texte
    expect(html).not.toContain('onerror="');
    expect(html).not.toContain("javascript:");
    expect(html).toContain("&lt;script&gt;alert(1)&lt;/script&gt;");
    expect(html).not.toContain("Voir sur Google Maps"); // son lien n'était pas sûr
    const viewer = viewerMarkup(r.photos, 0);
    expect(viewer).not.toContain("<script>");
    expect(viewer).not.toContain("javascript:");
  });

  it("OpenStreetMap : les infos pratiques, sous « © les contributeurs d'OpenStreetMap », la date de l'extrait, « Corriger »", () => {
    const html = placeFicheMarkup(view());
    expect(html).toContain("Infos pratiques");
    expect(html).toContain("<dt>Adresse</dt><dd>13 rue de la Monnaie, Lille</dd>");
    expect(html).toContain("<dt>Terrasse</dt><dd>oui</dd>");
    expect(html).toContain('href="https://www.openstreetmap.org/copyright"');
    expect(html).toContain("© les contributeurs d&#39;OpenStreetMap");
    expect(html).toContain("extrait du 16 novembre");
    expect(html).toContain('href="https://www.openstreetmap.org/node/4021153781"');
    expect(html).toContain("Corriger sur OpenStreetMap");
  });

  it("l'office de tourisme : sa description, ses labels, ses tarifs, son auteur et sa date, la Licence Ouverte", () => {
    const html = placeFicheMarkup(view());
    expect(html).toContain("Ce qu'en dit l'office de tourisme");
    expect(html).toContain('<p class="fiche-desc">Pizzeria napolitaine du Vieux-Lille.</p><p class="fiche-desc">Pâte maturée 48 heures.</p>');
    expect(html).toContain("Qualité Tourisme");
    expect(html).toContain("<dt>Tarifs</dt><dd>Pizzas de 11 à 19 €</dd>");
    expect(html).toContain("DATAtourisme · Hello Lille, mis à jour le 3 juin 2025");
    expect(html).toContain('href="https://www.etalab.gouv.fr/licence-ouverte-open-licence/"');
    expect(html).toContain("Licence Ouverte 2.0");
  });

  it("les événements tout près ouvrent leur fiche", () => {
    const html = placeFicheMarkup(view());
    expect(html).toContain("Bientôt, tout près");
    expect(html).toContain('href="#carte/evenements/e%3A450c81b3-6ffa-3d4e-9c1b-2a7f0e5d8c41"');
    expect(html).toContain("sam. 21 nov. · 19:00–22:00 · 780 m · 12/8€ - Gratuit moins de 18 ans");
  });

  it("un lieu que Google ne connaît pas le dit simplement ; un lieu dont on ne dit rien, aussi", () => {
    const none = fiche({ reviews: google({ found: false, id: "", rating: null, count: null, reviews: [], photos: [], url: "",
      note: "Rien trouvé sur Google sous ce nom à moins de 100 m (cherché le 20 novembre)." }) });
    const html = placeFicheMarkup(view({ fiche: none }));
    expect(html).toContain("Rien trouvé sur Google sous ce nom à moins de 100 m (cherché le 20 novembre).");
    expect(html).toContain("g-sec none");
    expect(html).not.toContain("Voir sur Google Maps");
    expect(html).toContain("data-refresh");
    const silent = placeFicheMarkup(view({ fiche: fiche({ reviews: null }) }));
    expect(silent).toContain("Pas de note ni d'avis Google Maps pour ce lieu.");
    expect(silent).toContain("Actualiser la fiche");
  });

  it("« Actualiser » : en cours, puis ce qui n'a pas pu se relire, en mots", () => {
    expect(placeFicheMarkup(view({ refreshing: true }))).toContain("Actualisation…");
    const said = placeFicheMarkup(view({ refreshNote: "Le quota du mois de Google (fiches avec avis) est atteint : il revient le 1er décembre à 09:00." }));
    expect(said).toContain('role="status"');
    expect(said).toContain("Le quota du mois de Google (fiches avec avis) est atteint : il revient le 1er décembre à 09:00.");
  });

  it("en lecture, sa ligne de la liste ; plus là (404) ; une panne : de quoi réessayer", () => {
    const row = fiche().place;
    const loading = placeFicheMarkup(view({ fiche: null, place: row, loading: true }));
    expect(loading).toContain("Magmatic");
    expect(loading).toContain("Lecture de la fiche…");
    const gone = placeFicheMarkup(view({ fiche: null, place: null, gone: true, error: new ApiError(404, "Introuvable.") }));
    expect(gone).toContain("Ce lieu n'est plus là");
    const down = placeFicheMarkup(view({ fiche: null, place: row, error: new ApiError(429, "Trop de fiches et d'événements demandés d'affilée : attends une minute.") }));
    expect(down).toContain("Trop de fiches et d&#39;événements demandés d&#39;affilée : attends une minute.");
    expect(down).toContain("data-fiche-retry");
  });

  it("revenir à la liste d'où elle vient ; ce que Mika a proposé, en rose", () => {
    const html = placeFicheMarkup(view({ mika: true, back: { href: "#carte/explorer/regard-36", label: "Ce que Mika a cherché" } }));
    expect(html).toContain('href="#carte/explorer/regard-36"');
    expect(html).toContain("Ce que Mika a cherché");
    expect(html).toContain('class="fiche by-mika"');
    expect(html).toContain("Mika te l'a proposé");
  });
});

describe("les photos", () => {
  it("la visionneuse : la photo en grand, son auteur lié, sa source, sa place ; sa licence pour l'office de tourisme", () => {
    const f = fiche();
    const photos = shownPhotos(f.tourism!.photos, f.reviews!.photos);
    const first = viewerMarkup(photos, 0);
    expect(first).toContain(`src="${API}/api/moi/carte/photo/${D1}"`);
    expect(first).toContain("CC BY-NC-ND 4.0");
    expect(first).toContain("Office de tourisme");
    expect(first).toContain("1 / 2");
    expect(first).toContain('data-vw="1"');
    const second = viewerMarkup(photos, 1);
    expect(second).toContain('<a href="https://www.google.com/maps/contrib/100000000000000000001" target="_blank" rel="noopener noreferrer nofollow">Camille R.</a>');
    expect(second).toContain("Google Maps");
    expect(second).toContain("2 / 2");
    // elle fait le tour
    expect(viewerMarkup(photos, 2)).toContain("1 / 2");
    expect(viewerMarkup(photos, -1)).toContain("2 / 2");
    expect(viewerMarkup([], 0)).toContain("Aucune photo.");
  });

  it("une bande sans photo montrable (une référence d'ailleurs) : le plan seul", () => {
    const band = photoBand({ scene: { pins: [], lines: [] }, title: "x", dist: "", photos: shownPhotos([{ ...google().photos[0], ref: "https://evil.example/a.jpg" }]), seen: never });
    expect(band).toContain("solo");
    expect(band).not.toContain("evil.example");
  });
});

/** La fiche d'événement du contrat. */
function eventFiche(extra: Partial<EventFiche> = {}): EventFiche {
  return {
    event: { id: "e:9a03e72c-35c0-3b1d-8e4f-6a2b0c1d3e5f", name: "Exposition « Fiat lux ! Une quête effrénée de lumière au XIXᵉ siècle »",
      start: "2026-11-21T10:00:00+01:00", end: "2026-11-21T18:00:00+01:00", when_text: "du mer. au lun. · 10:00–18:00",
      place: "Maison natale de Charles de Gaulle, Lille", lat: 50.645994, lon: 3.058752, distance_m: null, themes: ["expositions"], free: false,
      price: "Tarif 8 € / Réduit 6 €", photo: "" },
    description: "Une exposition sur la lumière au XIXᵉ siècle…",
    dates: [{ start: "2026-11-18", end: "2027-01-04", text: "du 18 nov. au 4 janv. · du mer. au lun. · 10:00–18:00", days: ["mer.", "jeu."] }],
    more_dates: 0, prices: "Tarif 8 € / Réduit 6 €", contacts: [{ label: "Site web", value: "https://www.musees.example/fiat-lux" }, { label: "Téléphone", value: "+33 3 59 73 00 30" }],
    address: "9 rue Princesse, 59800 Lille", town: "Lille", venue: "Maison natale de Charles de Gaulle", venue_place: "w84451082",
    author: "Hello Lille", updated: "2026-10-02", url: "https://data.datatourisme.fr/9a03e72c", photos: [], merged: 3,
    attribution: "DATAtourisme · Hello Lille, mis à jour le 2 octobre 2026", licence: "Licence Ouverte 2.0",
    licence_url: "https://www.etalab.gouv.fr/licence-ouverte-open-licence/", ...extra,
  };
}

function eventView(extra: Partial<EventFicheView> = {}): EventFicheView {
  return { event: null, fiche: eventFiche(), loading: false, error: null, gone: false, back: { href: "#carte/evenements", label: "Les événements" },
    mika: false, themes: new Map([["expositions", "Expositions"]]), here: null, seen: never, ...extra };
}

describe("la fiche d'un événement", () => {
  it("quand, où, combien ; le programme, ses dates, le pratique, son auteur et sa date sous la Licence Ouverte", () => {
    const html = eventFicheMarkup(eventView());
    expect(html).toContain("Exposition « Fiat lux ! Une quête effrénée de lumière au XIXᵉ siècle »");
    expect(html).toContain("Expositions · Lille");
    expect(html).toContain("du mer. au lun. · 10:00–18:00");
    expect(html).toContain("Tarif 8 € / Réduit 6 €");
    expect(html).toContain("Le programme");
    expect(html).toContain("du 18 nov. au 4 janv. · du mer. au lun. · 10:00–18:00");
    expect(html).toContain('<a href="#carte/explorer/lieu-w84451082">Maison natale de Charles de Gaulle</a>');
    expect(html).toContain("<dt>Adresse</dt><dd>9 rue Princesse, 59800 Lille</dd>");
    expect(html).toContain('href="tel:+33359730030"');
    expect(html).toContain('href="https://www.musees.example/fiat-lux"');
    expect(html).toContain("DATAtourisme · Hello Lille, mis à jour le 2 octobre 2026");
    expect(html).toContain("Licence Ouverte 2.0");
    expect(html).toContain("3 fiches de l&#39;office réunies");
    expect(html).toContain("data-ev-route");
    expect(html).toContain("data-ev-trip");
    expect(html).toContain("data-ev-ask");
    // sans photo, le plan seul
    expect(html).toContain("ph-band solo");
  });

  it("ses photos, avec leur crédit et leur licence ; un texte du dehors reste du texte", () => {
    const html = eventFicheMarkup(eventView({ fiche: eventFiche({
      description: EVIL, venue: EVIL, venue_place: "javascript:alert(1)", prices: EVIL,
      photos: [{ ref: D1, path: "", source: "datatourisme", credit: "Office de Roubaix", credit_url: "", licence: "CC BY-SA 4.0", caption: "La salle", width: null, height: null }],
    }) }));
    expect(html).toContain('data-photo="0"');
    expect(html).toContain("Office de Roubaix");
    // sa licence, dans la bande même, à côté de son auteur — pas seulement dans la visionneuse (R2-W03, R2-W11)
    const band = html.slice(html.indexOf('class="ph-wrap"'), html.indexOf("fiche-tags") > 0 ? html.indexOf("fiche-tags") : undefined);
    expect(band).toContain("Office de Roubaix · CC BY-SA 4.0");
    expect(html).not.toContain("<script>");
    expect(html).not.toContain("javascript:");
    expect(html).not.toContain("#carte/explorer/lieu-"); // pas un lieu de l'index : pas de lien
  });

  it("gratuit, plus là, en lecture", () => {
    const free = eventFicheMarkup(eventView({ fiche: eventFiche({ event: { ...eventFiche().event, free: true, price: "Entrée libre" } }) }));
    expect(free).toContain("Gratuit · Entrée libre");
    // ses tarifs le disent déjà : pas deux fois
    expect(priceWords({ free: true, price: "Gratuit - Entrée libre dans le hall du musée" })).toBe("Gratuit - Entrée libre dans le hall du musée");
    expect(priceWords({ free: true, price: "gratuit" })).toBe("Gratuit");
    expect(priceWords({ free: true, price: "" })).toBe("Gratuit");
    expect(priceWords({ free: null, price: "" })).toBe("");
    expect(priceWords({ free: false, price: "10 €" })).toBe("10 €");
    expect(eventFicheMarkup(eventView({ fiche: null, gone: true, error: new ApiError(404, "Introuvable.") }))).toContain("Cet événement n'est plus là");
    expect(eventFicheMarkup(eventView({ fiche: null, event: eventFiche().event, loading: true }))).toContain("Lecture de la fiche…");
  });
});
