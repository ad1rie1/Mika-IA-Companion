import { afterEach, describe, expect, it, vi } from "vitest";
import type { Me } from "../api/me";

const me: Me = {
  username: "adrien",
  name: "Adrien Moreau",
  handle: "user_1",
  person: "user_1",
  operator: true,
  owner: true,
  counts: { mail: 3, teams: 1, phone: 0 },
};

vi.mock("../api/me", () => ({ fetchMe: vi.fn(async () => me) }));

describe("la relecture de GET /api/moi", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("repeint les pastilles et passe la lecture entière à qui la suit (le nom du compte, renommé ailleurs)", async () => {
    vi.stubGlobal("window", { setInterval: vi.fn() });
    vi.stubGlobal("document", { addEventListener: vi.fn(), visibilityState: "visible" });
    const { countOf, refreshCounts, startCounts } = await import("./counts");
    const paint = vi.fn();
    const read = vi.fn();
    startCounts(paint, read);
    await refreshCounts();
    expect(countOf("mail")).toBe(3);
    expect(countOf("phone")).toBe("");
    expect(paint).toHaveBeenCalled();
    expect(read).toHaveBeenCalledWith(me);
  });
});
