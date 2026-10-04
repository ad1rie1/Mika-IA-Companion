#!/usr/bin/env bash
# ============================================================================
# AI Pipeline - Configuration
# ============================================================================

# -- Projet ------------------------------------------------------------------
# PROJECT_ROOT est DÉDUIT de l'emplacement de ce fichier, jamais écrit en dur :
# le pipeline a déjà été copié d'un projet à l'autre avec un chemin absolu qui
# pointait ailleurs, et il tournait silencieusement sur le mauvais dépôt.
_CONFIG_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "${_CONFIG_DIR}/../.." && pwd)}"
REPO_REMOTE="origin"
BASE_BRANCH="main"
BRANCH_PREFIX="ai"                          # branches: ai/bugs-20260802-1430

# Point de départ de toute branche de travail : l'état DISTANT de la branche de
# base. Le pipeline ne fait plus de `git pull` sur le `main` local de
# l'utilisateur — il ne touche plus du tout à sa copie de travail (cf. WORK_ROOT).
BASE_REF="${REPO_REMOTE}/${BASE_BRANCH}"

# Dépôt GitHub visé, déduit du remote. `gh` résout sinon le dépôt depuis le
# répertoire courant : run.sh interroge les issues sans faire de `cd`, les modes
# en font un vers le worktree — les deux moitiés de la boucle parlaient donc
# potentiellement de deux dépôts différents. GH_REPO est lu par toutes les
# commandes gh, ce qui lève l'ambiguïté partout d'un coup.
GH_REPO="${GH_REPO:-$(git -C "$PROJECT_ROOT" remote get-url "$REPO_REMOTE" 2>/dev/null \
    | sed -E 's#^(git@|https://|ssh://git@)github\.com[:/]##; s#\.git$##')}"
export GH_REPO

# -- Espace de travail --------------------------------------------------------
# Le pipeline travaille dans SON worktree git, jamais dans la copie de travail
# de PROJECT_ROOT. Il y faisait autrefois `git checkout`, `git pull`, et, sur
# Ctrl+C ou en cas d'échec, `git checkout -- .` puis `git clean -fd` : les
# modifications non commitées et les fichiers non suivis de l'utilisateur — ou
# d'une autre session qui travaillait dans le même dépôt — partaient avec. Dans
# un worktree dédié, une remise à zéro ne détruit que ce que le pipeline a
# lui-même produit, et l'utilisateur garde sa copie pendant que le pipeline
# tourne.
#
# `.claude/worktrees/` est déjà le domicile des worktrees d'agents de ce dépôt ;
# le pipeline s'y range sous un nom fixe.
WORK_ROOT="${AI_PIPELINE_WORKTREE:-${PROJECT_ROOT}/.claude/worktrees/ai-pipeline}"

# Fichiers NON suivis par git dont l'agent a besoin pour vérifier son travail
# (`npx tsc`, `./gradlew`) : liés depuis la copie principale plutôt que
# réinstallés à chaque tâche. `local.properties` dit à Gradle où est le SDK.
WORKSPACE_SHARED_PATHS=(
    "frontend/Web/node_modules"
    "frontend/Android/local.properties"
)

# Environnement Python du backend v2. Le paquet `mika` y est installé en mode
# éditable et pointe sur `PROJECT_ROOT/backendv2/src` : dans le worktree, il
# faut `PYTHONPATH=src`, sinon pytest et lint-imports vérifient le code de la
# copie principale au lieu de celui que l'agent vient d'écrire.
V2_VENV="${AI_PIPELINE_V2_VENV:-${PROJECT_ROOT}/backendv2/.venv}"

# Construction Android (cf. frontend/Android/README.md).
ANDROID_JAVA_HOME="${AI_PIPELINE_JAVA_HOME:-/usr/lib/jvm/java-25-openjdk}"
ANDROID_SDK="${ANDROID_HOME:-${HOME}/Android/Sdk}"

# Garde-fou mémoire des commandes lourdes (une construction Gradle prend
# ~2 Gio) : plafond sans swap, seule la commande est tuée au-delà. Vide si
# l'outil n'existe pas sur la machine.
MEMORY_GUARD="${AI_PIPELINE_MEMORY_GUARD:-${HOME}/recup-audit-v2-2026-10-01/outils/borne.sh}"
[[ -x "$MEMORY_GUARD" ]] || MEMORY_GUARD=""

# -- Agent IA -----------------------------------------------------------------
# Choix possibles: "claude" ou "codex"
# Surcharge possible au lancement:
#   AI_PIPELINE_AGENT=codex ./scripts/ai_pipeline/run.sh
#   ./scripts/ai_pipeline/run.sh --agent codex
#
# `AI_AGENT` reste accepté, mais c'est un nom trop générique : le CLI Claude
# Code l'exporte lui-même (valeur du type "claude-code_2-1-220_agent"). Lancer
# le pipeline depuis un terminal piloté par un agent le faisait donc échouer au
# démarrage sur « AI_AGENT invalide ». Une valeur héritée qui ne nomme aucun
# agent connu est du bruit, pas une intention : on la signale et on l'ignore.
AI_AGENT="${AI_PIPELINE_AGENT:-${AI_AGENT:-claude}}"
case "$AI_AGENT" in
    claude|codex) ;;
    *)
        echo "[WARN] AI_AGENT='${AI_AGENT}' hérité de l'environnement et inconnu du pipeline - ignoré, on utilise 'claude'." >&2
        echo "       Pour choisir explicitement : --agent claude|codex ou AI_PIPELINE_AGENT=..." >&2
        AI_AGENT="claude"
        ;;
esac
AI_AGENT_TIMEOUT=15600                         # timeout en secondes

# -- Retry sur rate limit ----------------------------------------------------
# Quand l'agent (Claude Code surtout) sort en disant "You've hit your limit",
# on attend puis on relance, plutôt que de notifier un échec immédiat.
AI_RATE_LIMIT_RETRY_DELAY="${AI_RATE_LIMIT_RETRY_DELAY:-1800}"   # 30 min entre tentatives
AI_RATE_LIMIT_MAX_RETRIES="${AI_RATE_LIMIT_MAX_RETRIES:-12}"     # 12 = jusqu'à 6h d'attente cumulée

# Durée pendant laquelle une sonde de disponibilité réussie vaut réponse. La
# sonde est un vrai appel d'agent : elle était refaite avant CHAQUE tâche et
# chaque PR examinée par le rebase, au niveau d'effort des tâches.
AI_PROBE_TTL="${AI_PROBE_TTL:-600}"

# Claude Code
CLAUDE_CMD="${CLAUDE_CMD:-claude}"            # chemin vers claude CLI
CLAUDE_TIMEOUT="${CLAUDE_TIMEOUT:-$AI_AGENT_TIMEOUT}" # compat historique
CLAUDE_MODEL="${CLAUDE_MODEL:-}"              # vide = défaut du CLI

# OpenAI Codex CLI
CODEX_CMD="${CODEX_CMD:-codex}"               # chemin vers codex CLI
CODEX_TIMEOUT="${CODEX_TIMEOUT:-$AI_AGENT_TIMEOUT}"
CODEX_MODEL="${CODEX_MODEL:-}"                # vide = défaut du CLI

# -- Budget de réflexion (extended thinking) ---------------------------------
# Niveau d'effort de raisonnement de l'agent. Vide = on garde le défaut du CLI
# (pour Claude Code : la valeur "effortLevel" de ~/.claude/settings.json).
#
#   Claude Code : low | medium | high | xhigh | max   → flag --effort
#   Codex CLI   : minimal | low | medium | high       → -c model_reasoning_effort
#
# Surcharge au lancement :
#   AI_PIPELINE_EFFORT=medium ./scripts/ai_pipeline/run.sh
#   ./scripts/ai_pipeline/run.sh --effort medium
#
# Un effort élevé = plus de tokens de réflexion par tâche (meilleure qualité
# d'analyse, mais quota consommé plus vite et tâches plus longues).
#
# `CLAUDE_EFFORT` et `CODEX_EFFORT` ne sont PLUS lus depuis l'environnement,
# seulement calculés ici : le CLI Claude Code exporte `CLAUDE_EFFORT` pour son
# propre compte, et sa valeur ("high") est valide pour le pipeline — elle se
# serait donc appliquée à chaque tâche sans erreur et sans que personne le voie.
AI_EFFORT="${AI_PIPELINE_EFFORT:-${AI_EFFORT:-}}"

# Défaut : `high`, le plus haut niveau commun aux deux échelles (celle de
# Codex s'arrête là). `xhigh` ou `max` restent possibles pour Claude sur
# demande (--effort xhigh), au prix d'un quota consommé plus vite.
AI_EFFORT_DEFAULT="high"
CLAUDE_EFFORT="${AI_EFFORT:-$AI_EFFORT_DEFAULT}"
CODEX_EFFORT="${AI_EFFORT:-$AI_EFFORT_DEFAULT}"

if [[ "$AI_AGENT" == "codex" && ( "$CODEX_EFFORT" == "xhigh" || "$CODEX_EFFORT" == "max" ) ]]; then
    echo "[WARN] Effort '${CODEX_EFFORT}' inconnu de Codex (minimal|low|medium|high) - on retombe sur 'high'." >&2
    CODEX_EFFORT="high"
fi

# Plafond dur, en tokens, du budget de réflexion de Claude Code (variable
# d'environnement MAX_THINKING_TOKENS lue par le CLI au moment de l'appel).
# Vide = pas de plafond explicite, c'est --effort/effortLevel qui décide seul.
CLAUDE_MAX_THINKING_TOKENS="${AI_PIPELINE_THINKING_TOKENS:-}"

# -- PR -----------------------------------------------------------------------
# Ce dépôt n'a AUCUN workflow GitHub Actions : rien ne validera la PR après
# coup. Le pipeline ne lance pas la suite complète pour autant — la politique
# injectée dans les prompts (ai_test_policy) autorise une vérification ciblée
# et exige une relecture humaine.
PR_LABEL="ai-suggestion"                     # label GitHub sur la PR
PR_DRAFT=false                               # créer en mode normal (pas draft)
PR_REVIEWERS=""                              # reviewers (comma-separated)

# -- Notifications ------------------------------------------------------------
NOTIFY_SLACK=false
SLACK_WEBHOOK_URL=""                         # webhook Slack incoming

NOTIFY_EMAIL=false
EMAIL_TO=""
EMAIL_FROM="ai-pipeline@vtuber.local"

# -- Modules ciblables --------------------------------------------------------
# Un module = une unité d'audit/correction, traitée par une tâche IA complète.
# Chemins relatifs à la racine du dépôt. Un module n'est retenu que s'il existe
# sur BASE_REF : c'est cet état-là que l'agent lit dans le worktree, et un
# dossier pas encore poussé y serait vide.
#
# La cible est le code VIVANT : backendv2/ et les trois clients (web, Android,
# Unity). Volontairement absents :
#   old/                         → v1 archivée, on ne la modifie plus
#   backendv2/src/mika/contracts,
#   ports, vocab                 → sans logique ; lus comme contexte par les
#                                  passages des facultés qui s'en servent
#   faculties/presence, place,
#   plugins/sensors              → quelques dizaines de lignes, lues avec
#                                  leurs voisins
#   backendv2/src/mika/sim       → l'outil de validation : le « corriger » pour
#                                  qu'un scénario passe est la pente à éviter
#   tests (backendv2/tests, Android app/src/test, Unity Assets/Mika/Tests)
#                                → la politique de tests interdit d'y écrire
#   Unity Runtime/Protocol/Generated
#                                → généré par frontend/Unity/tools/gen_world_protocol.py
#
# Les modules sont rangés en GROUPES : on lance un audit sur un groupe
# (audit-groupe.sh), et ses issues portent le label `groupe:<nom>` pour les
# retrouver sur GitHub. AVAILABLE_MODULES est la mise bout à bout des groupes :
# un module ajouté ou retiré l'est à un seul endroit.
_V="backendv2/src/mika"
_ANDROID_PKG="frontend/Android/app/src/main/java/fr/qwartz/mika"
_UNITY="frontend/Unity/Mika/Assets/Mika"

MODULE_GROUP_ORDER=(
    noyau exploitation relations vie-interieure parole projets monde canaux
    web android unity
)

declare -A MODULE_GROUP_DESCRIPTIONS=(
    [noyau]="journal, faits, gardes, arbitrage, épisodes : tout le reste en dépend"
    [exploitation]="serveur, ligne de commande, sauvegarde, console d'opérateur"
    [relations]="mémoire, identité, liens, ce qu'elle devine des autres"
    [vie-interieure]="humeur, attention, besoins, soi, corps et sommeil"
    [parole]="ce qu'elle dit, quand, à qui, et ce qu'elle envoie"
    [projets]="buts, projets, ateliers et Forge"
    [monde]="son monde 3D côté noyau"
    [canaux]="web, modèles, courrier, flux, caméra, images"
    [web]="client web (Three.js, VRM)"
    [android]="client Android (Kotlin)"
    [unity]="client Unity (C#)"
)

declare -A MODULE_GROUPS=(
    # Noyau et machinerie : un défaut ici touche toutes les facultés.
    [noyau]="$_V/kernel $_V/runtime"
    [exploitation]="$_V/app $_V/inspector"

    # Facultés, une par passage.
    [relations]="$_V/faculties/memory $_V/faculties/identity $_V/faculties/social $_V/faculties/others"
    [vie-interieure]="$_V/faculties/affect $_V/faculties/attention $_V/faculties/needs $_V/faculties/self $_V/faculties/body"
    [parole]="$_V/faculties/expression $_V/faculties/transcript $_V/faculties/agency $_V/faculties/shares"
    [projets]="$_V/faculties/goals $_V/faculties/projects $_V/plugins/forge $_V/adapters/forge $_V/adapters/workshop"
    [monde]="$_V/faculties/world $_V/adapters/world"

    # Adaptateurs et plugins (même forme que les facultés, confiance
    # restreinte) : les gros chacun leur passage, le reste d'adapters/ en un
    # lot.
    [canaux]="$_V/adapters/web $_V/adapters/llm $_V/adapters/mail $_V/plugins/email $_V/plugins/rss $_V/plugins/camera $_V/plugins/imaging $_V/adapters/imaging $_V/adapters"

    # Client web : l'animation pèse ~7 000 lignes à elle seule ; l'UI et
    # l'audio sont deux métiers distincts ; le reste (scène, réseau, types,
    # main.ts) fait un lot cohérent.
    [web]="frontend/Web/src/vtuber/animation frontend/Web/src/vtuber frontend/Web/src/ui frontend/Web/src/audio frontend/Web/src"

    # Client Android (Kotlin, ~11 500 lignes) : le réseau et la conversation
    # sont les deux gros morceaux de `data/` ; « app » couvre le reste (core,
    # share, manifeste, ressources).
    [android]="$_ANDROID_PKG/data/net $_ANDROID_PKG/data/chat $_ANDROID_PKG/data $_ANDROID_PKG/service $_ANDROID_PKG/ui frontend/Android/app"

    # Client Unity (C#, ~22 000 lignes) : les acteurs du monde et l'avatar sont
    # les deux gros morceaux du runtime ; l'éditeur (import, animation, labo)
    # fait un lot.
    [unity]="$_UNITY/Runtime/World/Actors $_UNITY/Runtime/World $_UNITY/Runtime/Avatar $_UNITY/Runtime $_UNITY/Editor"
)

AVAILABLE_MODULES=()
for _g in "${MODULE_GROUP_ORDER[@]}"; do
    read -ra _mods <<< "${MODULE_GROUPS[$_g]}"
    AVAILABLE_MODULES+=("${_mods[@]}")
done
unset _g _mods

# Le label GitHub d'un module est `module:<chemin>`, et GitHub refuse un label
# de plus de 50 caractères : les chemins Android et Unity n'y tiennent pas. Le
# premier préfixe qui correspond est remplacé par son abrégé (`ancien=nouveau`).
MODULE_LABEL_PREFIXES=(
    "frontend/Android/app/src/main/java/fr/qwartz/mika/=android/"
    "frontend/Android/=android/"
    "frontend/Unity/Mika/Assets/Mika/=unity/"
)

# Périmètres à retrancher d'un module, quand un sous-dossier est lui-même un
# module de la liste ci-dessus. Sans ça les deux se recouvrent : un adaptateur
# serait audité une fois pour lui-même et une fois dans le balayage de
# `adapters`, avec deux issues pour un même constat et aucune déduplication
# possible (elle est indexée par label de module).
_UNITY_RT="$_UNITY/Runtime"
declare -A MODULE_SCOPE_EXCLUDES=(
    ["backendv2/src/mika/adapters"]="les sous-dossiers llm/, mail/, web/, forge/, world/, workshop/ et imaging/ de backendv2/src/mika/adapters/"
    ["frontend/Web/src/vtuber"]="frontend/Web/src/vtuber/animation/"
    ["frontend/Web/src"]="frontend/Web/src/vtuber/, frontend/Web/src/ui/ et frontend/Web/src/audio/"
    ["${_ANDROID_PKG}/data"]="${_ANDROID_PKG}/data/net/ et ${_ANDROID_PKG}/data/chat/"
    ["frontend/Android/app"]="${_ANDROID_PKG}/data/, ${_ANDROID_PKG}/service/, ${_ANDROID_PKG}/ui/ et les tests (app/src/test, app/src/androidTest)"
    ["${_UNITY_RT}/World"]="${_UNITY_RT}/World/Actors/"
    ["${_UNITY_RT}"]="${_UNITY_RT}/World/, ${_UNITY_RT}/Avatar/ et ${_UNITY_RT}/Protocol/Generated/ (généré : un défaut s'y corrige dans frontend/Unity/tools/gen_world_protocol.py ou le schéma du noyau)"
)

# -- Profils d'analyse --------------------------------------------------------
PROFILES_DIR="${_CONFIG_DIR}/profiles"
LOGS_DIR="${_CONFIG_DIR}/logs"
LOGS_KEEP="${LOGS_KEEP:-200}"                  # journaux run-*.log conservés

# Profils d'audit dont les issues NE sont PAS taguées Propose_AI_PR, donc jamais
# reprises automatiquement par le worker. « features » en fait partie : une idée
# de fonctionnalité se discute avant d'être codée. Pour en lancer une, ajouter
# le label Propose_AI_PR à la main sur l'issue.
AUDIT_NO_AUTO_PR_PROFILES=(
    "features"
    "amelioration"
)

# Gravité minimale d'un constat d'audit (critical | high | medium | low), pour
# les profils qui signalent des défauts (pas pour features ni amelioration, où
# « severity » est un impact attendu). Un constat en dessous n'est pas créé.
# Pour un passage : SEVERITE=high audit_bugs …
AUDIT_SEVERITE_MIN="${SEVERITE:-${AUDIT_SEVERITE_MIN:-medium}}"
case "$AUDIT_SEVERITE_MIN" in
    critical|high|medium|low) ;;
    *)
        echo "[WARN] SEVERITE='${AUDIT_SEVERITE_MIN}' inconnue (critical|high|medium|low) - on garde 'medium'." >&2
        AUDIT_SEVERITE_MIN="medium"
        ;;
esac

# -- Doublons ------------------------------------------------------------------
# Filet appliqué à chaque issue d'audit avant sa création (lib/dedup.py) :
# ressemblance des titres (0 à 1) et fichiers en commun. Seuils mesurés sur 212
# issues d'audit passées : au-dessus de 0,8 les 4 paires trouvées étaient des
# doublons ; entre 0,6 et 0,8 avec un fichier commun, presque toujours le même
# défaut vu sous un autre profil.
DEDUP_SKIP="${DEDUP_SKIP:-0.8}"    # proche d'une issue ouverte : pas créée
DEDUP_FLAG="${DEDUP_FLAG:-0.6}"    # + un fichier commun : créée, « doublon-possible », sans Propose_AI_PR
# Les issues fermées depuis ce nombre de jours sont montrées à l'agent, avec
# les ouvertes, pour qu'il ne les re-signale pas.
DEDUP_CLOSED_DAYS="${DEDUP_CLOSED_DAYS:-90}"

# -- Sécurité -----------------------------------------------------------------
# Fichiers que l'IA ne doit JAMAIS toucher. Les motifs sont comparés en glob
# (`case`) à des chemins RELATIFS à la racine du dépôt : un motif nu ne matche
# donc que la racine, d'où les `*` en tête. Cette liste est aussi celle que
# lisent les prompts (ai_write_constraints) : une seule source.
FORBIDDEN_PATTERNS=(
    # Secrets
    "*.env"
    ".env*"
    "*credentials.json"
    "*credentials.yml"
    "*credentials.yaml"
    "*.credentials"
    "*secret.json"
    "*secret.yml"
    "*secret.yaml"
    "*.pem"
    "*.key"

    # La v1 est archivée : on ne la modifie plus.
    "old/*"

    # Sa persona est un choix d'auteur, pas du code à corriger.
    "backendv2/persona/*"

    # Dépendances, configuration de test, de lint et contrats d'architecture :
    # tout est dans pyproject.toml (pytest, ruff, import-linter). Desserrer une
    # règle d'import pour faire passer un correctif, c'est retirer le garde-fou.
    "backendv2/pyproject.toml"
    "frontend/Web/package.json"
    "frontend/Web/package-lock.json"
    "frontend/Web/tsconfig*.json"

    # Android : construction, dépendances, minification, signature, et les
    # schémas Room exportés (le compilateur les écrit ; une base qui change de
    # forme demande une migration, pas un schéma retouché).
    "frontend/Android/*.gradle.kts"
    "frontend/Android/gradle.properties"
    "frontend/Android/gradle/*"
    "frontend/Android/gradlew*"
    "frontend/Android/app/proguard-rules.pro"
    "frontend/Android/app/schemas/*"
    "*.jks"
    "*.keystore"

    # Unity : réglages et paquets du projet, types de protocole générés, et
    # tout ce que l'éditeur sérialise. Un `.meta` porte l'identifiant (GUID)
    # par lequel scènes et prefabs référencent un fichier : retouché à la main,
    # les références cassent en silence. Scènes, prefabs, matériaux et clips
    # s'éditent dans Unity, pas en YAML.
    "frontend/Unity/Mika/ProjectSettings/*"
    "frontend/Unity/Mika/Packages/*"
    "*/Protocol/Generated/*"
    "*.meta"
    "*.unity"
    "*.prefab"
    "*.asset"
    "*.mat"
    "*.anim"
    "*.controller"
    "frontend/Unity/Mika/Assets/Mika/Art/*"
    "frontend/Unity/ArtSource/*"

    # Exploitation et outillage : un agent ne réécrit pas les règles qui le
    # surveillent, ni la CI, ni ses propres réglages.
    "backendv2/deploy/*"
    "scripts/ai_pipeline/*"
    ".claude/*"
    ".github/*"

    # Données d'exécution. Pas de `*/data/*` : il interdisait aussi le paquet
    # Kotlin `fr/qwartz/mika/data/`, la moitié de l'application Android.
    "data/*"
    "backendv2/data/*"
    "uploads/*"
    "*.db"
    "*.sqlite3"

    # Binaires / assets
    "*.vrm"
    "*.fbx"
    "*.glb"
    "*.blend"
    "*.png"
    "*.jpg"
    "*.zip"
)
