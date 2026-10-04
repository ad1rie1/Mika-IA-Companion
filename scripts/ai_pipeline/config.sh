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

# Dépendances NON suivies par git dont l'agent a besoin pour vérifier son
# travail (`npx tsc`) : liées depuis la copie principale plutôt que
# réinstallées à chaque tâche.
WORKSPACE_SHARED_PATHS=(
    "frontend/Web/node_modules"
)

# Environnement Python du backend v2. Le paquet `mika` y est installé en mode
# éditable et pointe sur `PROJECT_ROOT/backendv2/src` : dans le worktree, il
# faut `PYTHONPATH=src`, sinon pytest et lint-imports vérifient le code de la
# copie principale au lieu de celui que l'agent vient d'écrire.
V2_VENV="${AI_PIPELINE_V2_VENV:-${PROJECT_ROOT}/backendv2/.venv}"

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
# chaque PR examinée par le rebase, au niveau d'effort des tâches (xhigh).
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

# Défaut par agent, et pas un défaut commun : `xhigh` n'existe pas côté Codex,
# dont l'échelle s'arrête à `high`. Claude tourne donc en xhigh sauf demande
# explicite, Codex garde le défaut de son CLI.
CLAUDE_EFFORT="${AI_EFFORT:-xhigh}"
CODEX_EFFORT="$AI_EFFORT"

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
# Chemins relatifs à la racine du dépôt (le pipeline n'en garde que les
# existants). Le label GitHub d'un module est `module:<chemin>` : GitHub limite
# un label à 50 caractères, un chemin ne doit donc pas dépasser 43.
#
# La cible est le moteur VIVANT : backendv2/ et le client web. Volontairement
# absents :
#   old/                         → v1 archivée, on ne la modifie plus
#   backendv2/src/mika/contracts,
#   ports, vocab                 → sans logique ; lus comme contexte par les
#                                  passages des facultés qui s'en servent
#   faculties/presence, place    → quelques dizaines de lignes, lues avec
#                                  world et identity
#   backendv2/src/mika/sim       → l'outil de validation : le « corriger » pour
#                                  qu'un scénario passe est la pente à éviter
#   backendv2/tests              → la politique de tests interdit d'y écrire
#   frontend/Unity               → aucun correctif vérifiable hors de l'éditeur
AVAILABLE_MODULES=(
    # Noyau et machinerie : un défaut ici touche toutes les facultés.
    "backendv2/src/mika/kernel"
    "backendv2/src/mika/runtime"
    "backendv2/src/mika/app"
    "backendv2/src/mika/inspector"

    # Facultés, une par passage.
    "backendv2/src/mika/faculties/projects"
    "backendv2/src/mika/faculties/memory"
    "backendv2/src/mika/faculties/goals"
    "backendv2/src/mika/faculties/identity"
    "backendv2/src/mika/faculties/self"
    "backendv2/src/mika/faculties/attention"
    "backendv2/src/mika/faculties/social"
    "backendv2/src/mika/faculties/affect"
    "backendv2/src/mika/faculties/others"
    "backendv2/src/mika/faculties/world"
    "backendv2/src/mika/faculties/body"
    "backendv2/src/mika/faculties/transcript"
    "backendv2/src/mika/faculties/needs"
    "backendv2/src/mika/faculties/agency"
    "backendv2/src/mika/faculties/expression"

    # Plugins : même forme que les facultés, confiance restreinte.
    "backendv2/src/mika/plugins/email"
    "backendv2/src/mika/plugins/forge"
    "backendv2/src/mika/plugins/rss"
    "backendv2/src/mika/plugins/camera"

    # Adaptateurs : les gros chacun leur passage, le reste en un lot.
    "backendv2/src/mika/adapters/llm"
    "backendv2/src/mika/adapters/mail"
    "backendv2/src/mika/adapters/web"
    "backendv2/src/mika/adapters/forge"
    "backendv2/src/mika/adapters/world"
    "backendv2/src/mika/adapters/workshop"
    "backendv2/src/mika/adapters/telegram"
    "backendv2/src/mika/adapters"

    # Client web : l'animation pèse ~7 000 lignes à elle seule ; l'UI et
    # l'audio sont deux métiers distincts ; le reste (scène, réseau, types,
    # main.ts) fait un lot cohérent.
    "frontend/Web/src/vtuber/animation"
    "frontend/Web/src/vtuber"
    "frontend/Web/src/ui"
    "frontend/Web/src/audio"
    "frontend/Web/src"
)

# Périmètres à retrancher d'un module, quand un sous-dossier est lui-même un
# module de la liste ci-dessus. Sans ça les deux se recouvrent : un adaptateur
# serait audité une fois pour lui-même et une fois dans le balayage de
# `adapters`, avec deux issues pour un même constat et aucune déduplication
# possible (elle est indexée par label de module).
declare -A MODULE_SCOPE_EXCLUDES=(
    ["backendv2/src/mika/adapters"]="les sous-dossiers llm/, mail/, web/, forge/, world/, workshop/ et telegram/ de backendv2/src/mika/adapters/"
    ["frontend/Web/src/vtuber"]="frontend/Web/src/vtuber/animation/"
    ["frontend/Web/src"]="frontend/Web/src/vtuber/, frontend/Web/src/ui/ et frontend/Web/src/audio/"
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
)

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

    # Exploitation et outillage : un agent ne réécrit pas les règles qui le
    # surveillent, ni la CI, ni ses propres réglages.
    "backendv2/deploy/*"
    "scripts/ai_pipeline/*"
    ".claude/*"
    ".github/*"

    # Données d'exécution
    "data/*"
    "*/data/*"
    "uploads/*"
    "*.db"
    "*.sqlite3"

    # Binaires / assets
    "*.vrm"
    "*.fbx"
    "*.glb"
    "*.blend"
    "*.zip"
)
