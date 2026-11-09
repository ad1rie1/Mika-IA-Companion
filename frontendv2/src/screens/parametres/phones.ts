/**
 * Paramètres › Téléphones (ADR 0190) : l'application Android à télécharger — derrière la connexion, jamais par un lien
 * public : un seul bouton, sur sa carte, à côté de « Copier le lien » —, ses téléphones (les jetons de son compte,
 * révoqués compris), qu'elle révoque elle-même, et ce que l'application lui montre aujourd'hui.
 */
import { APK_URL, revokePhone, type Phone } from "../../api/phone";
import { h } from "../../shell/dom";
import { toast } from "../../shell/float";
import { ico } from "../../shell/icons";
import { row, section } from "./form";
import { ago, confirmModal, copyText, dateWords, toastFailure } from "../../shared/kit";
import type { Host, Page } from "./page";
import * as store from "../../shared/store";

function apkCard(apk: boolean): string {
  const actions = apk
    ? `<div class="row"><a class="btn primary" href="${h(APK_URL)}" download="mika.apk">${ico("download", "sm")}Télécharger l'APK</a>
        <button class="btn" type="button" data-act="copy-apk">${ico("link", "sm")}Copier le lien</button></div>`
    : "";
  return `<div class="apk-card"><span class="apk-ico">${ico("phone")}</span><div class="grow"><h2>Mika pour Android</h2>
    <p class="text-2">${apk ? "L'application est prête à télécharger." : "L'application n'est pas encore déposée sur le serveur : demande à ton opérateur de la déposer."}</p>
    <p class="small muted">Le lien demande d'être connecté : ouvre-le depuis ton téléphone, connecté à Mika. Android te demandera d'autoriser l'installation depuis ton navigateur, puis l'application te demandera ton identifiant et ton mot de passe.</p>
    ${actions}</div></div>`;
}

/** Ce qu'un téléphone reçoit application fermée : ses notifications (Firebase, ADR 0077), ou rien. */
export function pushWords(push: boolean): string {
  return push ? "même application fermée" : "sans notifications";
}

export function phonesTable(items: readonly Phone[], now: number): string {
  if (!items.length) {
    return `<div class="set-row full"><p class="small muted">Aucun téléphone : installe l'application et connecte-toi avec ton identifiant.</p></div>`;
  }
  const rows = items
    .map((p) => `<tr${p.revoked ? ' class="revoked"' : ""}><td>${ico("phone", "sm")} <b>${h(p.label || "Téléphone")}</b> ${p.revoked ? '<span class="tag">révoqué</span>' : '<span class="tag ok">actif</span>'}</td>
      <td class="small">${h(pushWords(p.push))}</td>
      <td class="small">${h(dateWords(p.created_at, now) || "—")}</td><td class="small">${h(p.last_used ? ago(p.last_used, now) : "—")}</td>
      <td class="actions">${p.revoked ? "" : `<button class="btn xs danger" type="button" data-act="phone-revoke" data-id="${p.id}">Révoquer</button>`}</td></tr>`)
    .join("");
  return `<div class="set-row full"><table class="tbl"><thead><tr><th>Libellé</th><th>Notifications</th><th>Créé</th><th>Dernier usage</th><th></th></tr></thead><tbody>${rows}</tbody></table>
    <p class="small muted tbl-help">Révoquer ferme ses connexions ; un téléphone révoqué ne reçoit plus rien, même application fermée. Ses messages restent.</p></div>`;
}

async function revoke(id: number, host: Host): Promise<void> {
  const phone = store.phones.value?.items.find((p) => p.id === id);
  const yes = await confirmModal({
    title: "Révoquer ce téléphone",
    text: `Révoquer « ${phone?.label || "ce téléphone"} » ? Ses connexions se ferment ; il ne reçoit plus rien, même application fermée. Ses messages restent.`,
    ok: "Révoquer",
    danger: true,
  });
  if (!yes) return;
  try {
    const done = await revokePhone(id);
    toast(done.message || "Téléphone révoqué.", { ico: "x" });
    await host.reload(store.phones);
  } catch (err) {
    toastFailure(err);
  }
}

export function phonesView(apk: boolean, items: readonly Phone[], now: number): string {
  const apps = ["WhatsApp", "WhatsApp Business", "Messages"].map((a) => `<span class="tag">${h(a)}</span>`).join("");
  return `<div class="set-page">${apkCard(apk)}
      ${section("Tes téléphones connectés", phonesTable(items, now), { single: true })}
      ${section(
        "Ce que ton téléphone lui montre",
        row("Les apps lues", "Aujourd'hui, l'application lit les notifications de tes messageries. Choisir les apps une à une arrive bientôt.", apps) +
          row("Sur le téléphone", "Ces deux interrupteurs vivent sur le téléphone, coupés par défaut.", `<span class="tag">Lui montrer mes messages</span><span class="tag">Lui dire où je suis</span>`),
      )}</div>`;
}

export const phonesPage: Page = {
  id: "telephones",
  needs: () => [store.phones],
  view() {
    const value = store.phones.value!;
    return phonesView(value.apk, value.items, Date.now());
  },
  // pas d'action de barre de titre : « Télécharger l'APK » vit sur la carte de l'application, une seule fois
  act(name, el, _item, host) {
    if (name === "phone-revoke") void revoke(Number(el.dataset.id), host);
    if (name === "copy-apk") void copyText(APK_URL).then((ok) => toast(ok ? "Lien copié." : "Copie refusée.", { ico: "copy" }));
  },
};
