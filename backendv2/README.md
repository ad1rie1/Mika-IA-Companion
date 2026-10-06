# Mika v2 — démarrer en local

Ce qu'il faut pour la faire tourner sur ta machine et lui parler, pas à pas.
L'architecture est dans `ARCHITECTURE.md`, ses choix dans `docs/adr/`, et
l'installation en service (systemd, sauvegardes, mandataire TLS) dans
`deploy/README.md`.

## 1. Installer

```bash
cd backendv2
python3 -m venv .venv
.venv/bin/pip install -e ".[llm,memory]"     # + documents (lire les PDF), dev (les tests)
```

Bubblewrap (`dnf install bubblewrap`, `apt install bubblewrap`) n'est utile
qu'à ce qui exécute du code : la Forge et les ateliers de ses projets.

## 2. Lancer

```bash
.venv/bin/python -m mika serve
```

Elle écoute sur `http://127.0.0.1:8001` ; sa vie est rangée dans `./data/v2`
(relatif au dossier courant ; `--data <dossier>` pour un autre). Un seul
serveur par dossier : un second est refusé.

## 3. La console : ton compte, puis un modèle

Ouvre `http://127.0.0.1:8001/` (qui mène à `/inspecteur/`).

1. **Le compte opérateur.** Sans aucun compte, la page de connexion le crée :
   le premier compte est opérateur — il ouvre la console et le chat. (En
   ligne de commande, serveur arrêté : `mika account <nom> --operator`, le mot
   de passe est demandé sans écho.)
2. **Un fournisseur de modèles.** Configuration › Fournisseurs › Ajouter :
   son type (Claude, Claude Code, compatible OpenAI, Ollama…), le modèle, la
   clé s'il en faut une. **Le premier fournisseur déclaré la fait parler** :
   il sert « répondre » d'office, et tous les autres rôles (rêver, retenir,
   trier le courrier…) y retombent. « Qui sert quoi » n'est à toucher que pour
   confier un rôle à un autre fournisseur.

Tant qu'aucun modèle ne sert « répondre », chaque message reste sans réponse
et le tableau de bord le dit (« À traiter » › Modèles) ; `/health` aussi.

## 4. Le frontend

```bash
cd frontend/Web
npm install
npm run dev        # http://localhost:3000
```

Il vise `http://localhost:8001` par défaut ; pour une autre adresse,
`VITE_BACKEND_ORIGIN` dans `frontend/Web/.env.local` (voir `frontend/Web/.env.example`).
Le serveur admet les origines de développement (`localhost:3000`, `:4173`) ;
servi d'ailleurs, ajoute `--origin <adresse du frontend>` à `serve`.

Connecte-toi avec le compte créé à l'étape 3, et parle-lui.

## Et ensuite

- **Lui écrire** se fait par une application dédiée (le frontend web, le client
  Unity, l'application Android de `frontend/Android/`), avec un compte : il n'y a
  plus de robot Telegram (ADR 0060). Un client natif s'authentifie par un jeton de
  son compte : l'application Android l'obtient elle-même par identifiant et mot de
  passe (`POST /auth/token`), un moteur de jeu le reçoit en ligne de commande
  (`python -m mika token create <compte> --label …`). L'application Android est une
  messagerie : elle reçoit en arrière-plan, et Mika peut y écrire la première ; elle
  peut aussi y envoyer des fichiers (ADR 0062, `docs/protocole-chat.md`).
- **La faire agir depuis un script** : déclare un réveil (Configuration › Plugins › Réveils par API), génère sa
  clé sur sa fiche, puis `POST /api/wake/<nom>` avec `Authorization: Bearer <clé>` et `{"text": "…"}` (ADR 0068).
- **Lui faire lire Teams, et y répondre à ta place** : installe l'extension de `frontend/Extension/` dans le
  navigateur où tu ouvres Teams, génère sa clé (Configuration › Sens › Teams, ou `python -m mika teams key`) et
  colle-la dans l'extension. Ses réponses sont posées dans Teams pour que tu les envoies, ou partent après ton accord,
  ou seules — selon le mode (ADR 0069).
- **Le tableau de bord** (`/inspecteur/`) dit ce qui attend ton attention ;
  « Pourquoi a-t-elle dit ça ? » s'ouvre depuis chacune de ses paroles.
- **Tout se règle aussi en ligne de commande** : `python -m mika --help`.
- **Les tests** : `pip install -e ".[dev]"`, puis `python -m pytest -q` (les tests longs —
  scénarios complets, vies de plusieurs semaines, performances — sont écartés par défaut :
  `--slow` les ajoute, `-m slow` ne lance qu'eux).
