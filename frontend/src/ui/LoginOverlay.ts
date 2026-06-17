import { login, whoami, type AuthState } from "../network/api";

// Full-screen login gate. Resolves once the user is authenticated, so the app
// only connects the (authenticated) WebSocket afterwards.
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
    this.root.innerHTML = `
      <form id="login-form" style="
          display:flex; flex-direction:column; gap:12px; width:280px;
          padding:28px; background:#16213e; border-radius:12px;
          box-shadow:0 10px 40px rgba(0,0,0,.4);">
        <h2 style="color:#e2e8f0; font-size:18px; margin-bottom:6px;">Connexion</h2>
        <input id="login-user" type="text" placeholder="Identifiant" autocomplete="username"
          style="padding:10px; border-radius:8px; border:1px solid #2d3a5e; background:#0f1830; color:#e2e8f0;" />
        <input id="login-pass" type="password" placeholder="Mot de passe" autocomplete="current-password"
          style="padding:10px; border-radius:8px; border:1px solid #2d3a5e; background:#0f1830; color:#e2e8f0;" />
        <button type="submit" style="
          padding:10px; border:0; border-radius:8px; background:#6366f1; color:#fff;
          font-weight:600; cursor:pointer;">Se connecter</button>
        <div id="login-error" style="color:#f87171; font-size:13px; min-height:16px;"></div>
      </form>`;
  }

  /** Resolve immediately if already authenticated, else show the form. */
  async ensureAuthenticated(): Promise<AuthState> {
    const state = await whoami();
    if (state.authenticated) return state;
    return this.prompt();
  }

  private prompt(): Promise<AuthState> {
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
        try {
          const state = await login(userEl.value.trim(), passEl.value);
          this.root.remove();
          resolve(state);
        } catch {
          errorEl.textContent = "Identifiants invalides.";
          passEl.value = "";
          passEl.focus();
        }
      });
    });
  }
}
