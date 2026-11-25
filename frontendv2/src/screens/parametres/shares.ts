/**
 * Paramètres › Partages (ADR 0188) : ce que tu partages — tes boîtes, tes comptes Teams, tes services — avec qui et
 * à quel niveau (lire ; lire et préparer ; s'en servir), ce qu'on te partage, et « Partager… ». Seul le propriétaire
 * partage, et seulement avec une personne qui a un compte (`app/me/sharing.py`).
 */
import { setShare, type GivenShare, type ShareKind } from "../../api/shares";
import { h } from "../../shell/dom";
import { toast } from "../../shell/float";
import { ico, type IconName } from "../../shell/icons";
import { confirmModal, personAvatar, toastFailure } from "../../shared/kit";
import type { Host, Page } from "../../shared/settings";
import { openShareModal, shareables, shareWords, whatLabel } from "../../shared/sharing";
import * as store from "../../shared/store";

const KIND_ICONS: Record<ShareKind, IconName> = { mail: "mail", teams: "teams", mcp: "server", agenda: "agenda" };

function subOf(kind: ShareKind, key: string): string {
  return shareables().find((s) => s.kind === kind && s.key === key)?.sub ?? "";
}

/** Où s'ouvre ce qu'on te partage : une boîte dans Mail, un compte dans Teams, un service sur sa fiche (Paramètres ›
 *  Services MCP, « Partagé avec toi »). */
export function openOf(kind: ShareKind, key: string): string {
  if (kind === "agenda") return "#agenda/semaine";
  return kind === "mail" ? "#mail/messages" : kind === "teams" ? "#teams/discussions" : `#parametres/mcp/${encodeURIComponent(key)}`;
}

async function withdraw(s: GivenShare, host: Host): Promise<void> {
  const yes = await confirmModal({
    title: "Retirer ce partage",
    text: `${s.name} ne verra plus « ${s.title} » dans son Mika, et Mika ne s'en servira plus pour elle ou lui.`,
    ok: "Retirer",
    danger: true,
  });
  if (!yes) return;
  try {
    const done = await setShare(s.kind, s.key, s.person, "");
    toast(done.message || "Partage retiré.", { ico: "x" });
    await host.reload(store.shares, store.boxes, store.teamsAccounts, store.services, store.rights);
  } catch (err) {
    toastFailure(err);
  }
}

// ── La page ──────────────────────────────────────────────────────────

function givenTable(given: readonly GivenShare[]): string {
  if (!given.length) {
    return `<p class="small muted share-none">Tu ne partages rien pour l'instant. « Partager… » ouvre une de tes boîtes, un de tes comptes Teams ou un de tes services à une personne qui a un compte.</p>`;
  }
  return `<table class="tbl"><thead><tr><th>Quoi</th><th>Avec</th><th>Ce que la personne peut</th><th></th></tr></thead><tbody>${given
    .map((s, i) => {
      const sub = subOf(s.kind, s.key);
      return `<tr><td><div class="row">${ico(KIND_ICONS[s.kind], "sm")}<div><b>${h(whatLabel(s.kind, s.title))}</b>${sub ? `<div class="tiny muted">${h(sub)}</div>` : ""}</div></div></td>
        <td><div class="row">${personAvatar(s.name, "sm")}${h(s.name)}</div></td><td><span class="tag accent">${h(shareWords(s.level))}</span></td>
        <td class="actions"><button class="btn xs" type="button" data-act="share-edit" data-i="${i}">Modifier</button> <button class="btn xs ghost danger" type="button" data-act="share-remove" data-i="${i}">Retirer</button></td></tr>`;
    })
    .join("")}</tbody></table>`;
}

function receivedTable(): string {
  const received = store.shares.value?.received ?? [];
  if (!received.length) return `<p class="small muted share-none">Personne ne te partage rien pour l'instant.</p>`;
  return `<table class="tbl"><thead><tr><th>Quoi</th><th>De</th><th>Ce que tu peux</th><th></th></tr></thead><tbody>${received
    .map((s) => `<tr><td><div class="row">${ico(KIND_ICONS[s.kind], "sm")}<b>${h(whatLabel(s.kind, s.title))}</b></div></td>
      <td><div class="row">${personAvatar(s.owner_name, "sm")}${h(s.owner_name)}</div></td><td><span class="tag">${h(shareWords(s.level))}</span></td>
      <td class="actions"><a class="btn xs" href="${openOf(s.kind, s.key)}">Ouvrir</a></td></tr>`)
    .join("")}</tbody></table>`;
}

export const sharesPage: Page = {
  id: "partages",
  needs: () => [store.shares],
  extras: () => [store.boxes, store.teamsAccounts, store.services],
  view() {
    const given = store.shares.value?.given ?? [];
    const received = store.shares.value?.received ?? [];
    return `<div class="set-page">
      <p class="lede">Ce que tu partages apparaît dans le Mika de la personne, à son nom : elle le voit dans son propre Mika. Mika ne lui en dit pas plus que ce que tu ouvres, et tu retires un partage quand tu veux.</p>
      <div><h2 class="section-title">Ce que tu partages <span class="cnt">${given.length}</span></h2>${givenTable(given)}</div>
      <div><h2 class="section-title shared-title">Partagé avec toi <span class="cnt">${received.length}</span></h2>${receivedTable()}</div>
    </div>`;
  },
  actions: () => `<button class="btn primary" type="button" data-act="share-new">${ico("user-plus", "sm")}<span class="lbl">Partager…</span></button>`,
  act(name, el, _item, host) {
    const given = store.shares.value?.given ?? [];
    const s = given[Number(el.dataset.i)];
    if (name === "share-new") void openShareModal(host);
    else if (name === "share-edit" && s) void openShareModal(host, { kind: s.kind, key: s.key, person: s.person, level: s.level, title: s.title, name: s.name });
    else if (name === "share-remove" && s) void withdraw(s, host);
  },
};
