/**
 * L'écran « teams » (ADR 0187, 0189, 0191) : tes discussions Teams, ce que tu y écris, ce que Mika y prépare.
 */
import { countOf } from "../../shell/counts";
import type { Shell, ScreenDef } from "../../shell/shell";
import { TeamsScreen } from "./teams";

export function teamsScreen(shell: Shell): ScreenDef {
  return {
    ...new TeamsScreen(shell).screen(),
    count: () => countOf("teams"),
  };
}
