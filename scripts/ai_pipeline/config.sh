#!/usr/bin/env bash
# ============================================================================
# AI Pipeline - Configuration
# ============================================================================

# -- Projet ------------------------------------------------------------------
PROJECT_ROOT="/home/Qwartz/Bureau/IntelligentNetwork-automatic"
REPO_REMOTE="origin"
BASE_BRANCH="main"
BRANCH_PREFIX="ai"                          # branches: ai/security-20260406-1430

# -- Agent IA -----------------------------------------------------------------
# Choix possibles: "claude" ou "codex"
# Surcharge possible au lancement:
#   AI_AGENT=codex ./scripts/ai_pipeline/run.sh
AI_AGENT="${AI_AGENT:-claude}"
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
#   AI_EFFORT=medium ./scripts/ai_pipeline/run.sh
#   ./scripts/ai_pipeline/run.sh --effort medium
#
# Un effort élevé = plus de tokens de réflexion par tâche (meilleure qualité
# d'analyse, mais quota consommé plus vite et tâches plus longues).
AI_EFFORT="${AI_EFFORT:-}"
CLAUDE_EFFORT="${CLAUDE_EFFORT:-$AI_EFFORT}"
CODEX_EFFORT="${CODEX_EFFORT:-$AI_EFFORT}"

# Plafond dur, en tokens, du budget de réflexion de Claude Code (variable
# d'environnement MAX_THINKING_TOKENS lue par le CLI). Vide = pas de plafond
# explicite, c'est --effort/effortLevel qui décide seul.
CLAUDE_MAX_THINKING_TOKENS="${CLAUDE_MAX_THINKING_TOKENS:-}"

# -- Tests --------------------------------------------------------------------
# Les tests sont délégués au CI/CD GitHub (workflow ci-cd.yml)
# Le pipeline ne lance PAS de tests localement
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
EMAIL_FROM="ai-pipeline@intelligentnetwork.local"

# -- Modules ciblables --------------------------------------------------------
# Liste des modules Django analysables (un par ligne)
AVAILABLE_MODULES=(
    "Authentication"
    "CollecteursData"
    "Configuration"
    "DashBoard"
    "ExportModule"
    "GestionAuditNetworks"
    "GestionIA"
    "GestionRemoteAccess"
    "GestionReseau"
    "GestionSociete"
    "GestionSondes"
    "GestionTags"
    "HauteDisponibilite"
    "Installer"
    "IntelligentNetwork"
    "MultiTenant"
    "Planification"
    "Supervision"
    "Systeme"
    "UpdateSystem"
    "PROJET_SONDE_EXTERNE"
    "proxy_service"
)

# -- Profils d'analyse --------------------------------------------------------
PROFILES_DIR="${PROJECT_ROOT}/scripts/ai_pipeline/profiles"
LOGS_DIR="${PROJECT_ROOT}/scripts/ai_pipeline/logs"

# -- Sécurité -----------------------------------------------------------------
# Fichiers/patterns que l'IA ne doit JAMAIS toucher
# Note : on cible des fichiers de DONNÉES/CONFIG (json, yml, pem, key…), pas du code source.
# Les modèles Django nommés credentials.py / model_credentials.py sont du code légitime.
FORBIDDEN_PATTERNS=(
    "*.env"
    "*credentials.json"
    "*credentials.yml"
    "*credentials.yaml"
    "*.credentials"
    "*secret.json"
    "*secret.yml"
    "*secret.yaml"
    "*.pem"
    "*.key"
    "settings.py"
    "settings_local.py"
    "mysql-client.cnf"
    "manage.py"
)
