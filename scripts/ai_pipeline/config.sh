#!/usr/bin/env bash
# ============================================================================
# AI Pipeline - Configuration
# ============================================================================

# -- Projet ------------------------------------------------------------------
# PROJECT_ROOT est DÉDUIT de l'emplacement de ce fichier, jamais écrit en dur :
# le pipeline a déjà été copié d'un projet à l'autre avec un chemin absolu qui
# pointait ailleurs, et comme tous les modes font `cd "$PROJECT_ROOT"` avant de
# travailler, il tournait silencieusement sur le mauvais dépôt.
_CONFIG_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "${_CONFIG_DIR}/../.." && pwd)}"
REPO_REMOTE="origin"
BASE_BRANCH="main"
BRANCH_PREFIX="ai"                          # branches: ai/bugs-20260802-1430

# Dépôt GitHub visé, déduit du remote. `gh` résout sinon le dépôt depuis le
# répertoire courant : run.sh interroge les issues sans faire de `cd`, les modes
# en font un vers PROJECT_ROOT — les deux moitiés de la boucle parlaient donc
# potentiellement de deux dépôts différents. GH_REPO est lu par toutes les
# commandes gh, ce qui lève l'ambiguïté partout d'un coup.
GH_REPO="${GH_REPO:-$(git -C "$PROJECT_ROOT" remote get-url "$REPO_REMOTE" 2>/dev/null \
    | sed -E 's#^(git@|https://|ssh://git@)github\.com[:/]##; s#\.git$##')}"
export GH_REPO

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

# -- Tests --------------------------------------------------------------------
# Ce dépôt n'a AUCUN workflow GitHub Actions : rien ne validera la PR après
# coup. Le pipeline ne lance pas la suite complète pour autant (≈1000 tests
# pytest, trop long et trop coûteux à chaque tâche) — la politique injectée
# dans les prompts (ai_test_policy) autorise une vérification ciblée et exige
# une relecture humaine. Voir README à créer si un CI est ajouté un jour.
RUN_TESTS=false

# -- PR -----------------------------------------------------------------------
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
# Chemins relatifs à PROJECT_ROOT (le pipeline vérifie `-d "$PROJECT_ROOT/$mod"`
# et n'en garde que les existants).
#
# Volontairement absents :
#   backend/config      → settings.py est protégé, le reste (asgi, personality)
#                         tient en trois fichiers : à traiter à la main
#   backend/tests       → la politique de tests interdit d'y écrire
#   backend/staticfiles → généré
AVAILABLE_MODULES=(
    "backend/ai"
    "backend/communication"
    "backend/configs"
    "backend/conscience"
    "backend/drives"
    "backend/emotion"
    "backend/files"
    "backend/GestionSysteme"
    "backend/identity"
    "backend/memory"
    "backend/modules"
    "backend/pipeline"
    "backend/projects"
    "backend/utils"
    "frontend/src"
)

# -- Profils d'analyse --------------------------------------------------------
PROFILES_DIR="${_CONFIG_DIR}/profiles"
LOGS_DIR="${_CONFIG_DIR}/logs"

# Profils d'audit dont les issues NE sont PAS taguées Propose_AI_PR, donc jamais
# reprises automatiquement par le worker. « features » en fait partie : une idée
# de fonctionnalité se discute avant d'être codée. Pour en lancer une, ajouter
# le label Propose_AI_PR à la main sur l'issue.
AUDIT_NO_AUTO_PR_PROFILES=(
    "features"
)

# -- Sécurité -----------------------------------------------------------------
# Fichiers/patterns que l'IA ne doit JAMAIS toucher.
# Les patterns sont comparés en glob (`case`) à des chemins RELATIFS à la racine
# du dépôt : un motif nu comme `settings.py` ne matcherait donc que la racine.
# D'où les `*` en tête.
FORBIDDEN_PATTERNS=(
    # Secrets et configuration d'infrastructure
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
    "*settings.py"
    "*manage.py"

    # Schéma de base : une migration réécrite après coup casse les installs
    "*/migrations/*"

    # Identité de Mika et données d'exécution — pas du code à « corriger »
    "personality.yaml"
    "data/*"
    "uploads/*"
    "*.db"
    "*.sqlite3"

    # Dépendances et configuration de test : ajouter un paquet ou desserrer
    # pytest.ini est une décision humaine, pas un effet de bord de correctif
    "pytest.ini"
    "backend/requirements.txt"
    "frontend/package.json"
    "frontend/package-lock.json"

    # Binaires / assets
    "*.vrm"
    "*.fbx"
    "*.zip"
)
