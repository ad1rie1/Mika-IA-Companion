/**
 * La connexion, dans le thème de la maquette (qui n'en avait pas) : une carte au centre, la marque, son
 * visage, « Nom d'utilisateur », « Mot de passe », « Se connecter ». Sans aucun compte, la même carte crée
 * le premier (`needs_bootstrap`), avec le code de premier démarrage quand le serveur le demande
 * (`bootstrap_code_required`). Les textes d'erreur sont ceux de `@web/network/api.ts`.
 *
 * Pilotée par le serveur (`/auth/whoami`), jamais par une option de construction : un client qui ne
 * demanderait pas de compte à un serveur qui l'exige verrait sa connexion refusée.
 */
import { API_BASE, bootstrap, login, whoami, type AuthState } from "@web/network/api";
import { bootstrapClosed } from "@web/ui/LoginOverlay";
import { mikaAvatar } from "../mika/face";
import { $, h } from "../shell/dom";
import { ico } from "../shell/icons";
import { applyTheme, currentChoice, nextTheme, THEME_LABELS } from "../shell/theme";

export type LoginMode = "login" | "bootstrap";

export interface LoginFields {
  username: string;
  password: string;
  code: string;
}

/** Ce qui manque avant d'envoyer, en français — ou `null`. */
export function loginProblem(mode: LoginMode, codeRequired: boolean, f: LoginFields): string | null {
  if (!f.username.trim() || !f.password) return "Nom d'utilisateur et mot de passe requis.";
  if (mode === "bootstrap" && codeRequired && !f.code.trim()) {
    return "Le code de premier démarrage est dans le journal du serveur.";
  }
  return null;
}

function themeButton(): string {
  const choice = currentChoice();
  const dark = document.documentElement.dataset.theme === "dark";
  return `<button class="btn icon ghost login-theme" type="button" data-login-theme title="Thème : ${THEME_LABELS[choice]} (cliquer pour changer)">${ico(
    choice === "system" ? "monitor" : dark ? "moon" : "sun",
  )}</button>`;
}

function frame(inner: string): string {
  return `<div class="login-wrap">${themeButton()}
    <div class="login-card">
      <div class="login-brand"><span class="brand-mark" aria-hidden="true">M</span><span>Mika</span></div>
      ${inner}
    </div>
    <p class="login-server">Serveur : ${h(API_BASE)}</p></div>`;
}

function formMarkup(mode: LoginMode, codeRequired: boolean, note: string): string {
  const first = mode === "bootstrap";
  const code = first && codeRequired
    ? `<label class="field"><span>Code de premier démarrage</span><input name="code" type="text" autocomplete="one-time-code" spellcheck="false">
        <small class="muted">Il est écrit dans le journal du serveur, à son démarrage.</small></label>`
    : "";
  return frame(`<div class="login-face">${mikaAvatar("xl", undefined, "wave")}</div>
    <h1 id="login-title">${first ? "Bienvenue" : "Connexion"}</h1>
    <p class="login-lede">${first
      ? "Aucun compte n'existe encore. Crée le tien : c'est lui qui permet à Mika de savoir que c'est bien toi. Ce premier compte sera aussi son opérateur."
      : "Retrouve Mika, et ce qui est à toi."}</p>
    ${note ? `<p class="login-note" role="status">${ico("info", "sm")}<span>${h(note)}</span></p>` : ""}
    <form class="login-form" novalidate>
      ${code}
      <label class="field"><span>Nom d'utilisateur</span><input name="username" type="text" autocomplete="username" autocapitalize="none" spellcheck="false"></label>
      <label class="field"><span>Mot de passe</span><input name="password" type="password" autocomplete="${first ? "new-password" : "current-password"}"></label>
      <p class="login-error" role="alert" hidden></p>
      <button class="btn primary login-submit" type="submit">${first ? "Créer mon compte" : "Se connecter"}</button>
    </form>`);
}

function unreachableMarkup(message: string): string {
  return frame(`<div class="login-face down">${ico("wifi", "lg")}</div>
    <h1>Connexion au serveur impossible</h1>
    <p class="login-error" role="alert">${h(message)}</p>
    <button class="btn primary login-submit" type="button" data-retry>Réessayer</button>`);
}

function bindTheme(root: HTMLElement, repaint: () => void): void {
  root.querySelector("[data-login-theme]")?.addEventListener("click", () => {
    applyTheme(nextTheme(currentChoice()));
    repaint();
  });
}

/**
 * Résout quand la personne est connectée (ou que le serveur ne demande pas de compte). `note` : ce qui
 * s'est passé avant (« Ta session a expiré »).
 */
export async function ensureSession(root: HTMLElement, note = ""): Promise<AuthState> {
  for (;;) {
    let state: AuthState;
    try {
      state = await whoami();
    } catch (err) {
      // Le serveur ne répond pas : le dire, pas montrer un formulaire qui ne pourrait pas aboutir.
      await unreachable(root, err instanceof Error ? err.message : String(err));
      continue;
    }
    if (state.authenticated || state.auth_required === false) return state;
    return prompt(root, state.needs_bootstrap ? "bootstrap" : "login", Boolean(state.bootstrap_code_required), note);
  }
}

function unreachable(root: HTMLElement, message: string): Promise<void> {
  return new Promise((resolve) => {
    const paint = () => {
      root.innerHTML = unreachableMarkup(message);
      root.hidden = false;
      bindTheme(root, paint);
      root.querySelector("[data-retry]")!.addEventListener("click", () => resolve(), { once: true });
    };
    paint();
  });
}

function prompt(root: HTMLElement, mode: LoginMode, codeRequired: boolean, note: string): Promise<AuthState> {
  return new Promise((resolve) => {
    const values: LoginFields = { username: "", password: "", code: "" };
    const paint = () => {
      root.innerHTML = formMarkup(mode, codeRequired, note);
      root.hidden = false;
      bindTheme(root, () => {
        keep();
        paint();
      });
      const form = $<HTMLFormElement>(".login-form", root)!;
      const field = (name: keyof LoginFields) => form.querySelector<HTMLInputElement>(`[name="${name}"]`);
      for (const name of ["username", "password", "code"] as const) {
        const el = field(name);
        if (el) el.value = values[name];
      }
      (field("code") && !values.code ? field("code") : !values.username ? field("username") : field("password"))?.focus();
      const error = $(".login-error", root)!;
      const submit = $<HTMLButtonElement>(".login-submit", root)!;
      const fail = (text: string) => {
        error.innerHTML = `${ico("alert", "sm")}<span>${h(text)}</span>`;
        error.hidden = false;
      };
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        keep();
        error.hidden = true;
        const problem = loginProblem(mode, codeRequired, values);
        if (problem) {
          fail(problem);
          return;
        }
        submit.disabled = true;
        try {
          const state =
            mode === "bootstrap"
              ? await bootstrap(values.username.trim(), values.password, values.code.trim())
              : await login(values.username.trim(), values.password);
          resolve(state);
        } catch (err) {
          // un autre onglet a créé le premier compte entre-temps : on se connecte
          if (mode === "bootstrap" && bootstrapClosed(err)) {
            mode = "login";
            note = "Un compte existe déjà : connecte-toi.";
            values.password = "";
            paint();
            return;
          }
          // le message de `login()` distingue déjà le 401 d'un refus CSRF ou d'un serveur injoignable
          fail(err instanceof Error ? err.message : "Identifiants invalides.");
          values.password = "";
          const pass = field("password");
          if (pass) {
            pass.value = "";
            pass.focus();
          }
          submit.disabled = false;
        }
      });
    };
    const keep = () => {
      for (const name of ["username", "password", "code"] as const) {
        const el = root.querySelector<HTMLInputElement>(`.login-form [name="${name}"]`);
        if (el) values[name] = el.value;
      }
    };
    paint();
  });
}
