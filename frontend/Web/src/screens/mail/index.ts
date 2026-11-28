/**
 * L'écran « mail » (ADR 0187, 0191) : ses boîtes, leurs messages, ce que Mika en sait et ce qu'elle a préparé.
 */
import { countOf } from "../../shell/counts";
import type { Shell, ScreenDef } from "../../shell/shell";
import { MailScreen } from "./mail";

export function mailScreen(shell: Shell): ScreenDef {
  return {
    ...new MailScreen(shell).screen(),
    count: () => countOf("mail"),
  };
}
