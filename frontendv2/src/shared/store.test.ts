/**
 * Les copies partagées et le direct (ADR 0308) : chaque ouverture de la connexion les invalide toutes, rien n'étant
 * rattrapé. Une copie ajoutée à `store.ts` est prise d'office (elle s'y inscrit à sa création) : ce test échoue si l'une
 * d'elles ne l'était pas.
 */
import { describe, expect, it, vi } from "vitest";
import { Live } from "../live/live";
import { Cached, CachedMap } from "./kit";
import * as store from "./store";

/** Les copies que `store.ts` exporte, par leur nom. */
function copies(): Array<[string, { invalidate(): void }]> {
  return Object.entries(store as Record<string, unknown>).filter((e): e is [string, Cached<unknown> | CachedMap<unknown>] =>
    e[1] instanceof Cached || e[1] instanceof CachedMap);
}

/** Un service du direct branché sur une connexion qu'on ouvre à la main. */
function connected(): { service: Live; open: () => void } {
  const service = new Live();
  const handlers = new Map<string, (data: unknown) => void>();
  service.bind({ on: (type, handler) => handlers.set(type, handler) });
  return { service, open: () => handlers.get("connection")?.({ status: "connected" }) };
}

describe("les copies partagées à la resynchronisation", () => {
  it("la lecture voit les copies du module (sans elles, le test passerait sur une liste vide)", () => {
    const names = copies().map(([name]) => name);
    for (const known of ["me", "boxes", "boxSettings", "position", "agendaRights"]) expect(names).toContain(known);
  });

  it("chaque copie exportée par store.ts est invalidée à chaque ouverture de la connexion", () => {
    const { service, open } = connected();
    store.followChanges(service);
    const spies = copies().map(([name, copy]) => [name, vi.spyOn(copy, "invalidate")] as const);
    try {
      open();
      const missed = spies.filter(([, spy]) => spy.mock.calls.length !== 1).map(([name]) => name);
      expect(missed).toEqual([]);
    } finally {
      for (const [, spy] of spies) spy.mockRestore();
    }
  });
});
