import { describe, expect, it } from "vitest";
import { withoutEmoji } from "../TTSService";

describe("withoutEmoji", () => {
  it("retire ses émojis du texte dit, et laisse muet un message qui n'est qu'un émoji", () => {
    expect(withoutEmoji("trois en même temps 😭")).toBe("trois en même temps");
    expect(withoutEmoji('"un peu" 🙃 ok')).toBe('"un peu" ok');
    expect(withoutEmoji("💀")).toBe("");
    expect(withoutEmoji("👍🏽 d'accord ❤️")).toBe("d'accord");
    expect(withoutEmoji("[LAUGH] non mais attends")).toBe("[LAUGH] non mais attends");
  });
});
