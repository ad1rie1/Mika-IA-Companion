import { bootstrap, login, whoami, type AuthState } from "../network/api";

// Full-screen auth gate. Resolves once the user is authenticated, so the app
// only connects the (authenticated) WebSocket afterwards.
//
// Two modes, chosen from what the backend reports:
//   - **login** — the normal case
//   - **bootstrap** — no account exists yet, so this creates the first one.
//     Without it a fresh clone is unusable until someone runs
//     `createsuperuser` in a terminal, which is a poor first five minutes for
//     a project you just cloned to look at an avatar.
//
// Authentication is what makes Mika *certain* who she is talking to: an
// anonymous browser tab is indistinguishable from any other, so nothing said
// in one can be attached to a person with confidence.
export class LoginOverlay {
  private root: HTMLDivElement;

  constructor() {
    this.root = document.createElement("div");
    this.root.id = "login-overlay";
    Object.assign(this.root.style, {
      position: "fixed",
      inset: "0",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      background: "rgba(26, 26, 46, 0.96)",
      zIndex: "1000",
      fontFamily: "'Segoe UI', Tahoma, sans-serif",
    } as CSSStyleDeclaration);
  }

  /** Resolve immediately if already authenticated, else show the right form. */
  async ensureAuthenticated(): Promise<AuthState> {
    const state = await whoami();
    if (state.authenticated) return state;
    // Auth disabled server-side: let the app run anonymously as before.
    if (state.auth_required === false) return state;
    return this.prompt(Boolean(state.needs_bootstrap));
  }

  private render(isBootstrap: boolean): void {
    const title = isBootstrap ? "Bienvenue" : "Connexion";
    const hint = isBootstrap
      ? `<p style="color:#94a3b8; font-size:13px; line-height:1.45;">
           Aucun compte n'existe encore. Crée le tien : c'est lui qui permet à
           Mika de savoir que c'est bien toi.
         </p>`
      : "";
    const action = isBootstrap ? "Créer mon compte" : "Se connecter";
    const autocomplete = isBootstrap ? "new-password" : "current-password";

    this.root.innerHTML = `
      <form id="login-form" style="
          display:flex; flex-direction:column; gap:12px; width:300px;
          padding:28px; background:#16213e; border-radius:12px;
          box-shadow:0 10px 40px rgba(0,0,0,.4);">
        <h2 style="color:#e2e8f0; font-size:18px;">${title}</h2>
        ${hint}
        <input id="login-user" type="text" placeholder="Identifiant" autocomplete="username"
          style="padding:10px; border-radius:8px; border:1px solid #2d3a5e; background:#0f1830; color:#e2e8f0;" />
        <input id="login-pass" type="password" placeholder="Mot de passe" autocomplete="${autocomplete}"
          style="padding:10px; border-radius:8px; border:1px solid #2d3a5e; background:#0f1830; color:#e2e8f0;" />
        <button type="submit" style="
          padding:10px; border:0; border-radius:8px; background:#6366f1; color:#fff;
          font-weight:600; cursor:pointer;">${action}</button>
        <div id="login-error" style="color:#f87171; font-size:13px; min-height:16px;"></div>
      </form>`;
  }

  private prompt(isBootstrap: boolean): Promise<AuthState> {
    this.render(isBootstrap);
    document.body.appendChild(this.root);

    const form = this.root.querySelector<HTMLFormElement>("#login-form")!;
    const errorEl = this.root.querySelector<HTMLDivElement>("#login-error")!;
    const userEl = this.root.querySelector<HTMLInputElement>("#login-user")!;
    const passEl = this.root.querySelector<HTMLInputElement>("#login-pass")!;
    userEl.focus();

    return new Promise<AuthState>((resolve) => {
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        errorEl.textContent = "";
        const username = userEl.value.trim();
        const password = passEl.value;
        if (!username || !password) {
          errorEl.textContent = "Identifiant et mot de passe requis.";
          return;
        }
        try {
          const state = isBootstrap
            ? await bootstrap(username, password)
            : await login(username, password);
          this.root.remove();
          resolve(state);
        } catch (err) {
          // The bootstrap window can close between page load and submit (a
          // second tab got there first). Fall back to the login form rather
          // than leaving the user staring at a form that can't succeed.
          const message =
            err instanceof Error ? err.message : "Identifiants invalides.";
          if (isBootstrap && message.includes("existe deja")) {
            this.root.remove();
            resolve(await this.prompt(false));
            return;
          }
          errorEl.textContent = isBootstrap
            ? message
            : "Identifiants invalides.";
          passEl.value = "";
          passEl.focus();
        }
      });
    });
  }
}
