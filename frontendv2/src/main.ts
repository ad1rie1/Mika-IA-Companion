/**
 * Le démarrage : le thème, ses portraits, `whoami()` → la connexion ou l'application. L'application, c'est le
 * cadre (shell/), Mika (mika/) et les écrans (screens/), sur une connexion `/ws` du compte. Une fermeture en
 * 4401 (session révoquée, déconnexion, droits changés) ramène à la connexion, comme le veut le protocole :
 * `whoami` d'abord, et seulement si la session ne vaut plus, l'écran de connexion.
 */
import "./styles/base.css";
import "./styles/chat.css";
import "./styles/ecrans/outils.css";
import "./styles/ecrans/mail.css";
import "./styles/ecrans/teams.css";
import "./styles/ecrans/telephone.css";
import "./styles/ecrans/carte.css";
import "./styles/ecrans/parametres.css";
import "./styles/app.css";

import { API_BASE, logout, whoami, WS_URL, type AuthState } from "@web/network/api";
import { WebSocketClient } from "@web/network/WebSocketClient";
import { consoleHref } from "@web/ui/chatSync";
import { ensureSession } from "./login/login";
import { setManifest } from "./mika/face";
import { loadManifest } from "./mika/portraits";
import { MikaStore } from "./mika/store";
import { carteScreen } from "./screens/carte";
import { ChatScreen } from "./screens/chat/chat";
import { mailScreen } from "./screens/mail";
import { outilsScreen } from "./screens/outils";
import { parametresScreen } from "./screens/parametres";
import { teamsScreen } from "./screens/teams";
import { telephoneScreen } from "./screens/telephone";
import { startCounts } from "./shell/counts";
import { injectSprite } from "./shell/icons";
import { Shell, type Account } from "./shell/shell";
import { applyTheme, currentChoice, followSystem } from "./shell/theme";

/** Au-delà de tant de reconnexions refusées d'affilée, on cesse de croire `whoami` et on redemande le compte. */
const MAX_QUICK_RETRIES = 3;
/** Une connexion restée ouverte si longtemps n'était pas un refus en boucle. */
const STABLE_MS = 10_000;

function accountOf(state: AuthState): Account {
  const username = state.username ?? "";
  return {
    username,
    displayName: state.display_name || username || "Invité",
    operator: state.operator === true,
    personId: state.person_id ?? "",
  };
}

async function boot(): Promise<void> {
  injectSprite();
  applyTheme(currentChoice(), false);
  followSystem();
  const loginRoot = document.getElementById("login")!;
  const appRoot = document.getElementById("app")!;
  setManifest(await loadManifest());
  const state = await ensureSession(loginRoot);
  startApp(state, loginRoot, appRoot);
}

function startApp(state: AuthState, loginRoot: HTMLElement, appRoot: HTMLElement): void {
  const account = accountOf(state);
  loginRoot.hidden = true;
  loginRoot.innerHTML = "";
  const store = new MikaStore();
  let leaving = false;
  const page = consoleHref("/inspecteur/");
  const shell = new Shell(appRoot, store, account, {
    console: page ? `${API_BASE}${page}` : undefined,
    logout: async () => {
      leaving = true;
      chat.forget();
      try {
        await logout();
      } catch {
        // le serveur ne répond pas : la session tombera d'elle-même ; on repart quand même de la connexion
      }
      history.replaceState(null, "", location.pathname + location.search);
      location.reload();
    },
  });
  const chat = new ChatScreen(shell, store, account);
  shell.register(chat.screen());
  // dans l'ordre de la barre du haut, celui de la maquette
  for (const make of [outilsScreen, mailScreen, teamsScreen, telephoneScreen]) {
    shell.register(make(shell));
  }
  // la carte : « Demander à Mika » ouvre le chat avec une phrase préremplie
  shell.register(carteScreen(shell, { ask: (text) => chat.prefill(text) }));
  shell.register(parametresScreen(shell));
  shell.start();
  startCounts(() => shell.updateCounts());

  // Les reconnexions refusées d'affilée : une connexion restée ouverte un moment remet le compte à zéro, pas
  // une ouverture suivie d'un refus aussitôt (sinon un serveur qui accepte puis refuse ferait tourner en rond).
  let quickRetries = 0;
  let openedAt = 0;
  const connect = () => {
    const ws = new WebSocketClient(WS_URL);
    ws.on("emotion_update", (d) => store.mood(d));
    ws.on("inner_state_update", (d) => store.innerState(d.inner_state));
    ws.on("connection", (d) => {
      if (d.status === "connected") openedAt = Date.now();
      if (d.status === "unauthorized" && !leaving) void unauthorized();
    });
    chat.bind(ws);
    ws.connect();
  };

  /** Fermée en 4401 : la session vaut-elle encore ? Oui, on se reconnecte ; non, on redemande le compte. */
  const unauthorized = async () => {
    if (openedAt && Date.now() - openedAt > STABLE_MS) quickRetries = 0;
    let still: AuthState | null = null;
    try {
      still = await whoami();
    } catch {
      still = null;
    }
    if (still?.authenticated && still.person_id === account.personId && quickRetries < MAX_QUICK_RETRIES) {
      quickRetries += 1;
      connect();
      return;
    }
    appRoot.hidden = true;
    const again = await ensureSession(loginRoot, "Ta session a expiré : reconnecte-toi.");
    if (again.person_id !== account.personId) {
      // quelqu'un d'autre : rien de la personne d'avant ne reste dans la page
      location.reload();
      return;
    }
    loginRoot.hidden = true;
    loginRoot.innerHTML = "";
    appRoot.hidden = false;
    quickRetries = 0;
    connect();
  };

  connect();

  // Sa VRM, à part : three et three-vrm ne retardent pas l'écran ; ?vrm=0 la coupe (portrait seul).
  if (new URLSearchParams(location.search).get("vrm") !== "0") {
    import("./mika/vrm")
      .then((m) => m.startVrm(shell.corner, store))
      .catch((err) => console.warn("VRM indisponible, le portrait reste :", err));
  }
}

void boot();
