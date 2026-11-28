/**
 * Le cadre de l'écran Carte (`index.ts`), monté sur un faux shell, un faux corps et une API jouée : un regard
 * d'événements ouvert dans Explorer (une miniature du chat pas encore lue) part dans l'onglet Événements sans empiler
 * d'entrée — « Retour » ramène au chat, pas sur lui-même ; une fiche ouverte par un lien d'une fiche de l'autre onglet
 * (« Bientôt, tout près », le lieu d'un événement) a un retour qui y ramène.
 */
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { Regard } from "../../api/carte";
import type { ScreenContext, Shell } from "../../shell/shell";
import { carteScreen } from "./index";

const INFO = {
  places: { ready: true, count: 1, built: 1 }, addresses: { ready: false }, routing: { ready: false, provider: "", modes: [], avoid: [] },
  categories: [], themes: [], tourism: { ready: true, places: 1, events: 1, synced: 1 },
};
const REGARD: Regard = { kind: "look", title: "Ce week-end", what: "evenements", places: [], route: null, trip: "", at: 1,
  events: [{ id: "e:450c81b3-6ffa-3d4e-9c1b-2a7f0e5d8c41", name: "Éclats du rire !", start: "2026-11-21T19:00+01:00", end: "",
    when_text: "sam. 21 nov. · 19:00–22:00", place: "L'Aéronef, Lille", lat: 50.63, lon: 3.07 }] };

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

/** L'API par personne, jouée : ce que l'écran lit. */
async function api(input: RequestInfo | URL): Promise<Response> {
  const path = new URL(String(input), "http://mika.test").pathname;
  if (path.endsWith("/api/moi/carte")) return json(INFO);
  if (path.endsWith("/carte/fond")) return json({ ready: false, reason: "Aucune carte réglée." });
  if (path.endsWith("/phone/position")) return json({ known: false });
  if (path.endsWith("/carte/regards/840")) return json(REGARD);
  return json({ error: "Ce serveur ne répond pas ici." }, 503);
}

/** Un corps de page qui garde ce qu'on y dessine (sans DOM). */
function body() {
  return { innerHTML: "", isConnected: true, querySelector: () => null, querySelectorAll: () => [], contains: () => false };
}

const history = { length: 3, replaceState: vi.fn((_state: unknown, _title: string, url: string) => { location.hash = url; }) };
const location = { hash: "" };

function shell() {
  const went: string[] = [];
  const s = {
    ctx: { screen: "carte" } as ScreenContext | null,
    go: (hash: string) => {
      went.push(hash);
      history.length += 1;
    },
    refresh: vi.fn(),
    refreshHead: () => undefined,
  };
  return { shell: s as unknown as Shell, went, refresh: s.refresh };
}

beforeAll(() => {
  vi.stubGlobal("window", globalThis);
  vi.stubGlobal("addEventListener", () => undefined);
  vi.stubGlobal("document", { activeElement: null });
  vi.stubGlobal("HTMLInputElement", class {});
  vi.stubGlobal("history", history);
  vi.stubGlobal("location", location);
  vi.stubGlobal("fetch", vi.fn(api));
});

beforeEach(() => {
  history.length = 3;
  history.replaceState.mockClear();
});

// ce que l'écran lit encore après le dernier test (ses lectures en cours) se termine avant qu'on rende le décor
afterAll(async () => {
  await new Promise((resolve) => setTimeout(resolve, 100));
  vi.unstubAllGlobals();
});

describe("un regard d'événements ouvert dans Explorer (R2-W01)", () => {
  it("part dans Événements en remplaçant l'entrée : « Retour » ne revient pas sur lui", async () => {
    const { shell: s, went, refresh } = shell();
    const def = carteScreen(s, { ask: () => undefined });
    const page = body();
    def.render(page as unknown as HTMLElement, { screen: "carte", tab: "explorer", item: "regard-840", el: page } as unknown as ScreenContext);
    await vi.waitFor(() => expect(history.replaceState.mock.calls.length + went.length).toBeGreaterThan(0));
    expect(went).toEqual([]); // rien d'empilé
    expect(history.replaceState).toHaveBeenCalledWith(null, "", "#carte/evenements/regard-840");
    expect(refresh).toHaveBeenCalled();
    expect(history.length).toBe(3);
  });
});

describe("une fiche ouverte depuis une fiche de l'autre onglet (R2-W06)", () => {
  it("son retour ramène à la fiche d'où l'on vient", () => {
    const { shell: s } = shell();
    const def = carteScreen(s, { ask: () => undefined });
    const page = body();
    const ctx = (tab: string, item: string | null) => ({ screen: "carte", tab, item, el: page }) as unknown as ScreenContext;
    def.render(page as unknown as HTMLElement, ctx("explorer", "lieu-w84451082"));
    def.render(page as unknown as HTMLElement, ctx("evenements", "e:450c81b3-6ffa-3d4e-9c1b-2a7f0e5d8c41"));
    expect(page.innerHTML).toContain('href="#carte/explorer/lieu-w84451082" data-fiche-back');
    def.render(page as unknown as HTMLElement, ctx("explorer", "lieu-t:6b0e2f4a-8c1d-3e5f-9a7b-0c2d4e6f8a10"));
    expect(page.innerHTML).toContain('href="#carte/evenements/e%3A450c81b3-6ffa-3d4e-9c1b-2a7f0e5d8c41" data-fiche-back');
    // le « Retour » du navigateur, le long du lien (le lieu d'où l'on avait ouvert l'événement) : pas d'aller-retour,
    // le lieu garde son retour à lui (la liste)
    def.render(page as unknown as HTMLElement, ctx("explorer", "lieu-w84451082"));
    def.render(page as unknown as HTMLElement, ctx("evenements", "e:450c81b3-6ffa-3d4e-9c1b-2a7f0e5d8c41"));
    def.render(page as unknown as HTMLElement, ctx("explorer", "lieu-w84451082"));
    expect(page.innerHTML).not.toContain("Retour à l&#39;événement");
    expect(page.innerHTML).toContain('href="#carte/explorer" data-fiche-back');
    // revenue à la liste, puis une fiche de la liste : son retour est la liste
    def.render(page as unknown as HTMLElement, ctx("explorer", null));
    def.render(page as unknown as HTMLElement, ctx("explorer", "lieu-n4021153781"));
    expect(page.innerHTML).toContain('href="#carte/explorer" data-fiche-back');
  });
});
