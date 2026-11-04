/**
 * Paramètres › Compte : son nom (celui sous lequel Mika la connaît), son identifiant, son rôle ; son mot de passe
 * (le changer ferme toutes ses sessions : on se reconnecte) ; le thème de ce navigateur.
 */
import type { Me } from "../../api/me";
import { ApiError } from "../../api/moi";
import { savePassword, saveName } from "../../api/settings";
import { h } from "../../shell/dom";
import { closeModal, openModal, toast } from "../../shell/float";
import { ico } from "../../shell/icons";
import { currentChoice } from "../../shell/theme";
import { readForm, row, section, seg, showFieldErrors, subTabs, text } from "./form";
import { failureText } from "./kit";
import type { Page } from "./page";
import * as store from "./store";
import { fieldErrors } from "./words";

const SUBS = [["compte", "Ton compte"], ["securite", "Mot de passe"], ["apparence", "Apparence"]] as const;

function roleTags(me: Me): string {
  const tags = [
    ...(me.owner ? ['<span class="tag accent">Propriétaire</span>'] : []),
    ...(me.operator ? ['<span class="tag">Opérateur</span>'] : []),
  ];
  return tags.join("") || '<span class="tag">Une personne</span>';
}

function roleHelp(me: Me): string {
  if (me.operator) return "Un opérateur parle avec elle et ouvre aussi la console : tout ce qu'elle vit, sa configuration, les approbations et les apps.";
  if (me.owner) return "Une de ses propriétaires : ce qui est « à toi » est à toi.";
  return "Une personne qui a un compte : ce que tu branches ici est à toi seule.";
}

export const PASSWORD_HELP = "8 caractères au moins, pas seulement des chiffres, sans ton identifiant dedans.";
/** La borne de `current` et `password` dans l'API (au-delà : 400, jamais coupé). */
const PASSWORD_MAX = 200;

function passwordModal(): void {
  const el = openModal({
    title: "Changer le mot de passe",
    size: "narrow",
    body: `<form class="stack" data-pw>
      <label class="field"><span>Mot de passe actuel</span><input type="password" name="current" autocomplete="current-password" maxlength="${PASSWORD_MAX}"></label>
      <label class="field"><span>Nouveau mot de passe</span><input type="password" name="password" autocomplete="new-password" maxlength="${PASSWORD_MAX}"></label>
      <label class="field"><span>Encore une fois</span><input type="password" name="again" autocomplete="new-password" maxlength="${PASSWORD_MAX}"></label>
      <p class="small muted">${h(PASSWORD_HELP)} Toutes tes sessions se fermeront, celle-ci comprise : tu te reconnecteras.</p>
      <p class="small cf-error" data-erreur hidden></p></form>`,
    foot: `<span class="grow"></span><button class="btn" type="button" data-close>Annuler</button>
      <button class="btn primary" type="button" data-ok>${ico("key", "sm")}Changer</button>`,
  });
  const form = el.querySelector<HTMLFormElement>("[data-pw]")!;
  const ok = el.querySelector<HTMLButtonElement>("[data-ok]")!;
  const error = el.querySelector<HTMLElement>("[data-erreur]")!;
  /** Un refus sans champ (trop d'essais : 429, le serveur muet) : dit dans la fenêtre, qui reste ouverte. */
  const say = (text: string) => {
    error.innerHTML = text ? `${ico("alert", "xs")}<span>${h(text)}</span>` : "";
    error.hidden = !text;
  };
  const submit = async () => {
    const v = readForm(form);
    const errors: Record<string, string> = {};
    if (!v.current) errors.current = "ton mot de passe actuel";
    if (!v.password) errors.password = "le nouveau";
    else if (v.password !== v.again) errors.again = "les deux ne sont pas les mêmes";
    say("");
    if (Object.keys(errors).length) {
      showFieldErrors(form, errors);
      return;
    }
    ok.disabled = true;
    try {
      const done = await savePassword(String(v.current), String(v.password));
      closeModal();
      toast(done.message || "Mot de passe changé : reconnecte-toi.", { ico: "key", duration: 3000 });
      // ses sessions sont fermées : la connexion, avec le nouveau
      window.setTimeout(() => location.reload(), 1600);
    } catch (err) {
      ok.disabled = false;
      if (err instanceof ApiError && Object.keys(err.fields).length) {
        const rest = showFieldErrors(form, fieldErrors(err.fields));
        if (rest.length) say(rest.join(" ; "));
      } else say(failureText(err));
    }
  };
  ok.addEventListener("click", () => void submit());
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    void submit();
  });
}

export const accountPage: Page = {
  id: "compte",
  needs: () => [store.me],
  view(_item, host) {
    const me = store.me.value!;
    const active = host.sub("compte", "compte");
    const account = section(
      "Ton compte",
      row("Nom affiché", "Le nom sous lequel elle te connaît.", text("name", me.name, 'autocomplete="name" maxlength="120"')) +
        row("Identifiant", "Celui de la connexion, sur le web comme sur le téléphone.", `<span class="mono">${h(me.username)}</span><span class="tag">ne change pas</span>`) +
        row("Ton rôle", roleHelp(me), roleTags(me)) +
        row("Ce qu'elle sait de toi", "Ce qu'elle a retenu de toi se demande à elle, dans le chat.", `<a class="btn xs ghost" href="#chat">${ico("sparkle", "xs")}Lui demander</a>`),
      { sub: "compte", hidden: active !== "compte" },
    );
    const security = section(
      "Mot de passe",
      row("Mot de passe", PASSWORD_HELP, `<button class="btn sm" type="button" data-act="password">${ico("key", "sm")}Changer le mot de passe</button>`) +
        row("Tes téléphones", "Chaque téléphone a sa propre clé : tu le révoques sans toucher au mot de passe.", `<a class="btn sm" href="#parametres/telephones">${ico("phone", "sm")}Tes téléphones</a>`),
      { sub: "securite", hidden: active !== "securite" },
    );
    const looks = `<div data-ignore>${section(
      "Apparence",
      row("Thème", "Celui du système, ou toujours clair, ou toujours sombre. Il vaut pour ce navigateur.", seg("theme", [["system", "Système"], ["light", "Clair"], ["dark", "Sombre"]], currentChoice())),
      { sub: "apparence", hidden: active !== "apparence" },
    )}</div>`;
    return `<form class="set-page" data-form="compte">${subTabs("compte", SUBS, active)}${account}${security}${looks}</form>`;
  },
  act(name) {
    if (name === "password") passwordModal();
  },
  async save(form, changes, _values, _item, host) {
    if (!("name" in changes)) return true;
    const name = String(changes.name).trim();
    try {
      const done = await saveName(name);
      toast(done.message || "Enregistré.", { ico: "check" });
      host.shell.setAccount({ ...host.shell.user, displayName: name });
      await host.reload(store.me);
      return true;
    } catch (err) {
      if (err instanceof ApiError && Object.keys(err.fields).length) showFieldErrors(form, fieldErrors(err.fields));
      else toast(failureText(err), { ico: "alert" });
      return false;
    }
  },
};
