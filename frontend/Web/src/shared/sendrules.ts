/**
 * Comment part ce qu'elle prépare (ADR 0207) : la règle d'envoi d'un de ses comptes, Teams ou boîte. Les réglages d'un
 * compte Teams (`screens/teams/settings.ts`) et la fiche d'une boîte (`screens/mail/settings.ts`) la dessinent et
 * l'enregistrent par les mêmes pièces : le tableau à régler (`rulesEditor`), les changements d'un formulaire sans ceux
 * de la règle (`withoutRule`), ce qui part au serveur (`ruleUpdate`). Pur : des chaînes HTML.
 */
import type { RuleLine } from "../api/rights";
import type { SendChoice, SendRules, SendRulesUpdate } from "../api/settings";
import { h } from "../shell/dom";
import { ico } from "../shell/icons";
import { seg, select, type FormValue } from "./settings";

/** Un champ de la règle : `rule.<n>.prepare`, `rule.<n>.reply` — `<n>` sa ligne (à partir de 1), `d` la ligne par
 *  défaut. Ils partent à part (`saveSendRules`), jamais avec les réglages du compte. */
const RULE = "rule.";
const PREPARE = [["oui", "Oui"], ["non", "Non"]] as const;
/** Comment ça part, dans les mots du moteur (`vocab.access.REPLY_WORDS`). */
const SENDS = [["accord", "ton accord"], ["seule", "seule"], ["brouillon", "brouillon — c'est toi qui l'envoies"], ["non", "non"]] as const;

export type RulesKind = "mail" | "teams";

/** Les choix de « comment ça part » d'une ligne : le courrier n'a pas de brouillon que tu envoies toi-même (la console
 *  le grise) — sauf sur une ligne qui l'a déjà, qu'on montre telle qu'elle est. */
export function sendChoices(kind: RulesKind, current: string): (readonly [string, string])[] {
  return SENDS.filter(([k]) => k !== "brouillon" || kind === "teams" || current === "brouillon");
}

function ruleWho(l: RuleLine): string {
  return [l.who || "Tout le monde", l.when && l.when !== "toujours" ? l.when : ""].filter(Boolean).join(" · ");
}

/** La règle d'un de ses comptes, à régler : pour chaque ligne et pour le défaut, préparer d'elle-même et comment ça
 *  part ; qui écrit et l'ordre des lignes restent à la console. */
export function rulesEditor(rules: SendRules, kind: RulesKind): string {
  const line = (n: string, l: RuleLine, def = false) =>
    `<tr${def ? ' class="def"' : ""}><td class="muted">${def ? "—" : h(n)}</td><td>${def ? '<b>Par défaut</b> <span class="small muted">quand aucune ligne au-dessus ne correspond</span>' : h(ruleWho(l))}</td>
      <td>${seg(`${RULE}${n}.prepare`, PREPARE, l.prepare ? "oui" : "non")}</td>
      <td>${select(`${RULE}${n}.reply`, sendChoices(kind, l.reply), l.reply, 'class="sm-select"')}</td></tr>`;
  const rows = rules.lines.map((l, i) => line(String(i + 1), l)).join("");
  const where = kind === "teams" ? "Teams" : "Mail";
  const origin = rules.set
    ? ""
    : rules.common
      ? ` Ce compte suit la règle de tout ${kind === "teams" ? "Teams" : "le courrier"}, réglée dans la console : l'enregistrer ici lui en donne une à lui.`
      : " Elle n'a jamais été réglée : c'est sa règle de départ.";
  const help = `Lue de haut en bas : la première ligne qui correspond décide. Tu règles ici ce qu'elle prépare d'elle-même et comment ça part ; qui écrit et l'ordre des lignes se règlent dans la console.${kind === "mail" ? " Le courrier n'a pas de brouillon que tu envoies toi-même : « ton accord » en tient lieu." : ""} Ce qu'elle prépare se relit dans ${where}, dans « Ses brouillons ».${origin}`;
  return `<div class="set-row full"><table class="tbl"><thead><tr><th>#</th><th>${kind === "teams" ? "Qui écrit (ou quelle discussion)" : "Qui écrit (une adresse, un @domaine)"}</th><th>Préparer d'elle-même</th><th>Comment ça part</th></tr></thead>
    <tbody>${rows}${line("d", rules.default, true)}</tbody></table>
    <p class="small muted tbl-help">${h(help)}</p>
    <div class="row tbl-help"><a class="btn xs ghost" href="#outils/droits/${encodeURIComponent(rules.canal)}">${ico("tools", "xs")}Ses outils dans Outils</a></div></div>`;
}

/** Les changements d'un formulaire sans ceux de la règle, qui partent à part ; `rule` : une case de la règle a bougé. */
export function withoutRule(changes: Record<string, FormValue>): { rule: boolean; rest: Record<string, FormValue> } {
  const rest: Record<string, FormValue> = {};
  let rule = false;
  for (const [k, v] of Object.entries(changes)) {
    if (k.startsWith(RULE)) rule = true;
    else rest[k] = v;
  }
  return { rule, rest };
}

/** Ce qui part au serveur quand une case de la règle a bougé : toute la règle, telle que le formulaire la montre, avec
 *  l'empreinte de celle qu'on a lue. */
export function ruleUpdate(rules: SendRules, values: Record<string, FormValue>): SendRulesUpdate {
  const pick = (n: string, l: RuleLine): SendChoice => {
    const prepare = values[`${RULE}${n}.prepare`];
    const reply = values[`${RULE}${n}.reply`];
    return { prepare: prepare === undefined ? l.prepare : prepare === "oui", reply: typeof reply === "string" && reply ? reply : l.reply };
  };
  return { canal: rules.canal, version: rules.version, lines: rules.lines.map((l, i) => pick(String(i + 1), l)), default: pick("d", rules.default) };
}
