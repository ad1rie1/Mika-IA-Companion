import { describe, expect, it } from "vitest";
import {
  BubbleReveal,
  splitBubbles,
  TYPING_MAX_MS,
  TYPING_MIN_MS,
  typingDelayMs,
} from "../bubbles";

/** Des minuteurs qu'on avance à la main. */
function manualTimers() {
  const pending = new Map<number, { fn: () => void; ms: number }>();
  let next = 1;
  return {
    pending,
    set(fn: () => void, ms: number) {
      pending.set(next, { fn, ms });
      return next++;
    },
    clear(handle: number) {
      pending.delete(handle);
    },
    /** Déclenche le seul minuteur en attente, et rend son délai. */
    fire(): number {
      const [handle, t] = [...pending.entries()][0];
      pending.delete(handle);
      t.fn();
      return t.ms;
    },
  };
}

describe("splitBubbles", () => {
  it("cuts on a blank line, never on a single line break", () => {
    expect(splitBubbles("c'est quoi comme réunion ?\n\nen tout cas, bon courage")).toEqual([
      "c'est quoi comme réunion ?",
      "en tout cas, bon courage",
    ]);
    expect(splitBubbles("une ligne\nla suite")).toEqual(["une ligne\nla suite"]);
    expect(splitBubbles("  un  \n \n\n  deux ")).toEqual(["un", "deux"]);
  });
});

describe("typingDelayMs", () => {
  it("grows with the bubble and stays bounded", () => {
    expect(typingDelayMs("ok")).toBe(TYPING_MIN_MS);
    expect(typingDelayMs("x".repeat(40))).toBeGreaterThan(typingDelayMs("x".repeat(10)));
    expect(typingDelayMs("x".repeat(500))).toBe(TYPING_MAX_MS);
  });
});

describe("BubbleReveal", () => {
  it("shows the first bubble, then each next one after the time to type it", () => {
    const timers = manualTimers();
    const steps: boolean[] = [];
    const reveal = new BubbleReveal<string>((done) => steps.push(done), timers);
    reveal.start("r1", "c'est quoi comme réunion ?\n\npourquoi elle te donne tellement envie ?\n\nen tout cas, bon courage");
    expect(reveal.shown("r1", 3)).toBe(1);
    expect(reveal.shown("autre", 2)).toBe(2); // une autre réponse : tout
    expect(timers.fire()).toBe(typingDelayMs("pourquoi elle te donne tellement envie ?"));
    expect(reveal.shown("r1", 3)).toBe(2);
    timers.fire();
    expect(reveal.shown("r1", 3)).toBe(3);
    expect(steps).toEqual([false, true]);
    expect(reveal.writing).toBe(false);
    expect(timers.pending.size).toBe(0);
  });

  it("a single bubble does not wait, and a new reply shows what was left at once", () => {
    const timers = manualTimers();
    const steps: boolean[] = [];
    const reveal = new BubbleReveal<string>((done) => steps.push(done), timers);
    reveal.start("r1", "juste ça");
    expect(reveal.writing).toBe(false);
    expect(timers.pending.size).toBe(0);
    reveal.start("r2", "un\n\ndeux");
    reveal.start("r3", "trois");
    expect(reveal.shown("r2", 2)).toBe(2);
    expect(steps).toEqual([true]);
    expect(timers.pending.size).toBe(0);
  });
});
