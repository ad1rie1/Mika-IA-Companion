import { describe, expect, it } from "vitest";
import { mergeHistory, type StoredMessage } from "../chatSync";
import { applyVerdict, nextVerdict, verdictError, verdictFrame } from "../verdicts";

const reply = (id: number, text = "C'est le piège du métier…"): StoredMessage => ({
  text,
  sender: "vtuber",
  ts: id,
  id,
});

describe("nextVerdict", () => {
  it("chooses the clicked opinion, and withdraws it on a second click", () => {
    expect(nextVerdict(undefined, "ko")).toBe("ko");
    expect(nextVerdict("ok", "ko")).toBe("ko");
    expect(nextVerdict("ko", "ko")).toBe("");
  });
});

describe("verdictFrame", () => {
  it("carries the comment only with an opinion", () => {
    expect(verdictFrame(812, "ko", "  trop long : juste « salut ! »  ")).toEqual({
      type: "verdict",
      message_id: 812,
      verdict: "ko",
      comment: "trop long : juste « salut ! »",
    });
    expect(verdictFrame(812, "", "oublié").comment).toBe("");
  });
});

describe("applyVerdict", () => {
  it("sets the opinion on her reply only", () => {
    const history: StoredMessage[] = [{ text: "salut", sender: "user", ts: 1, id: 811 }, reply(812)];
    expect(applyVerdict(history, 812, "ko", " trop long ")).toBe(true);
    expect(history[1]).toMatchObject({ verdict: "ko", verdictNote: "trop long" });
    expect(applyVerdict(history, 811, "ok", "")).toBe(false);
    applyVerdict(history, 812, "", "");
    expect(history[1].verdict).toBeUndefined();
    expect(history[1].verdictNote).toBeUndefined();
  });
});

describe("mergeHistory and verdicts", () => {
  it("brings an opinion given elsewhere onto a reply already shown", () => {
    const history = [reply(812)];
    const got = mergeHistory(
      history,
      [{ id: 812, role: "assistant", text: "C'est le piège du métier…", ts: 812, verdict: "ko", verdict_note: "trop long" }],
      50
    );
    expect(got.judged).toBe(1);
    expect(got.history[0]).toMatchObject({ verdict: "ko", verdictNote: "trop long" });
    // la même ligne une seconde fois : rien ne change
    expect(mergeHistory(got.history, [{ id: 812, role: "assistant", text: "x", ts: 812, verdict: "ko", verdict_note: "trop long" }], 50).judged).toBe(0);
  });

  it("reads the opinion of a new line", () => {
    const got = mergeHistory([], [{ id: 812, role: "assistant", text: "Coucou", ts: 812, verdict: "ok" }], 50);
    expect(got.history[0]).toMatchObject({ verdict: "ok" });
    expect(got.history[0].verdictNote).toBeUndefined();
  });
});

describe("verdictError", () => {
  it("says a refusal in French", () => {
    expect(verdictError("ok")).toBeNull();
    expect(verdictError("forbidden")).toContain("opératrice");
    expect(verdictError("failed")).toContain("réessaie");
  });
});
