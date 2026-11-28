import { afterEach, describe, expect, it, vi } from "vitest";
import type { Me } from "../api/me";

const me: Me = {
  username: "adrien",
  name: "Adrien Moreau",
  handle: "user_1",
  person: "user_1",
  operator: true,
  owner: true,
  counts: { mail: 3, teams: 1, phone: 0, projects: 2 },
};

const fetchMe = vi.fn(async () => me);
vi.mock("../api/me", () => ({ fetchMe: () => fetchMe() }));

describe("les pastilles : GET /api/moi", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("repeint les pastilles et passe la lecture entière à qui la suit (le nom du compte, renommé ailleurs)", async () => {
    vi.stubGlobal("document", { addEventListener: vi.fn(), visibilityState: "visible" });
    const { countOf, refreshCounts, startCounts } = await import("./counts");
    const paint = vi.fn();
    const read = vi.fn();
    startCounts(paint, read);
    await refreshCounts();
    expect(countOf("mail")).toBe(3);
    expect(countOf("phone")).toBe("");
    expect(countOf("projects")).toBe(2); // ce qui t'attend dans tes projets : la pastille de « Projets »
    expect(paint).toHaveBeenCalled();
    expect(read).toHaveBeenCalledWith(me);
  });

  it("relues quand le direct dit `me` (ADR 0308), une lecture à la fois ; l'onglet caché attend son retour", async () => {
    const page = { addEventListener: vi.fn(), visibilityState: "visible" };
    vi.stubGlobal("document", page);
    const { live } = await import("../live/live");
    const { refreshCounts } = await import("./counts");
    await refreshCounts();
    fetchMe.mockClear();
    // une rafale : une lecture en vol, une seule après
    live.receive({ type: "changed", changes: [{ topic: "me" }] });
    live.receive({ type: "changed", changes: [{ topic: "me" }] });
    live.receive({ type: "changed", changes: [{ topic: "me" }] });
    await refreshCounts();
    expect(fetchMe).toHaveBeenCalledTimes(2);
    // un autre sujet ne les touche pas
    fetchMe.mockClear();
    live.receive({ type: "changed", changes: [{ topic: "mail", boxes: ["pro"] }] });
    expect(fetchMe).not.toHaveBeenCalled();
    // l'onglet caché : rien sur le moment, une lecture à son retour
    page.visibilityState = "hidden";
    live.receive({ type: "changed", changes: [{ topic: "me" }] });
    expect(fetchMe).not.toHaveBeenCalled();
    page.visibilityState = "visible";
    live.shown();
    await refreshCounts();
    expect(fetchMe).toHaveBeenCalled();
  });
});
