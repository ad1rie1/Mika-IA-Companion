#!/usr/bin/env bash
# ============================================================================
# AI Pipeline - Orchestrateur
# ============================================================================
# Point d'entrée unique. Parse les arguments et dispatch vers le bon mode.
#
# Usage:
#   ./orchestrator.sh --audit --profile security --modules "Authentication"
#   ./orchestrator.sh --profile bugs --modules "GestionTags"
#   ./orchestrator.sh --worker
#   ./orchestrator.sh --issue 42
#   ./orchestrator.sh --cleanup
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Charger config et libs
source "${SCRIPT_DIR}/config.sh"
source "${SCRIPT_DIR}/lib/common.sh"
source "${SCRIPT_DIR}/lib/git.sh"
source "${SCRIPT_DIR}/lib/github.sh"
source "${SCRIPT_DIR}/modes/audit.sh"
source "${SCRIPT_DIR}/modes/fix.sh"
source "${SCRIPT_DIR}/modes/worker.sh"
source "${SCRIPT_DIR}/modes/rebase.sh"

# ============================================================================
# Trap SIGINT (Ctrl+C) - nettoyage et retour sur main
# ============================================================================
# Kill récursif de l'arbre de processus (agent IA + timeout inclus)
_kill_tree() {
    local pid=$1 sig=${2:-TERM}
    local child
    for child in $(pgrep -P "$pid" 2>/dev/null); do
        _kill_tree "$child" "$sig"
    done
    kill -"$sig" "$pid" 2>/dev/null || true
}

cleanup_on_interrupt() {
    # Éviter réentrance
    trap '' INT TERM

    echo ""
    err "Interruption (Ctrl+C) - nettoyage en cours..."

    # Tuer les processus fils (agent IA, timeout) : SIGTERM puis SIGKILL
    local c
    for c in $(pgrep -P $$ 2>/dev/null); do
        _kill_tree "$c" TERM
    done
    sleep 2
    for c in $(pgrep -P $$ 2>/dev/null); do
        _kill_tree "$c" KILL
    done

    cd "$PROJECT_ROOT"

    # Reset les modifications en cours
    git checkout -- . 2>/dev/null || true
    git clean -fd 2>/dev/null || true

    # Retour sur main
    local current_branch
    current_branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
    if [[ -n "$current_branch" && "$current_branch" != "$BASE_BRANCH" && "$current_branch" == "${BRANCH_PREFIX}/"* ]]; then
        warn "Retour sur ${BASE_BRANCH} (abandon de $current_branch)"
        git checkout "$BASE_BRANCH" 2>/dev/null || true
        git branch -D "$current_branch" 2>/dev/null || true
    fi

    warn "Arrêt propre terminé"
    exit 130
}

trap cleanup_on_interrupt INT TERM

# ============================================================================
# Aide
# ============================================================================
usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

MODES:
  --audit               Analyse en profondeur, crée des issues GitHub
  --worker              Traite les issues taggées Propose_AI_PR, crée des PR
  --rebase              Rebase les PRs en conflit + ferme les PRs/issues obsolètes
  --issue NUMBER        Corrige une issue spécifique, crée une PR
  (défaut)              Corrections rapides par profil, crée des PR

OPTIONS:
  --profile PROFILE     Profil: security, bugs, quality (requis sauf --issue/--worker)
  --modules MODULES     Modules ciblés (virgules) ou "all" (défaut: auto)
  --no-create           Ne rien créer sur GitHub (test local)
  --dry-run             Afficher ce qui serait fait sans rien exécuter
  --branch NAME         Nom de branche custom
  --agent claude|codex  Agent IA à utiliser (défaut: config.sh)
  --cleanup             Supprimer les branches ai/* mergées
  -h, --help            Afficher cette aide

EXEMPLES:
  $(basename "$0") --audit --profile security
  $(basename "$0") --profile bugs --modules "GestionTags"
  $(basename "$0") --worker
  $(basename "$0") --issue 42
  $(basename "$0") --cleanup

EOF
    exit 0
}

# ============================================================================
# Arguments
# ============================================================================
PROFILE=""
MODULES="all"
ISSUE_NUMBER=""
AUDIT_MODE=false
WORKER_MODE=false
REBASE_MODE=false
NO_CREATE=false
DRY_RUN=false
CUSTOM_BRANCH=""
DO_CLEANUP=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --profile)    PROFILE="$2"; shift 2 ;;
        --modules)    MODULES="$2"; shift 2 ;;
        --issue)      ISSUE_NUMBER="$2"; shift 2 ;;
        --audit)      AUDIT_MODE=true; shift ;;
        --worker)     WORKER_MODE=true; shift ;;
        --rebase)     REBASE_MODE=true; shift ;;
        --no-create)  NO_CREATE=true; shift ;;
        --no-pr)      NO_CREATE=true; shift ;;
        --dry-run)    DRY_RUN=true; shift ;;
        --branch)     CUSTOM_BRANCH="$2"; shift 2 ;;
        --agent)      AI_AGENT="$2"; export AI_AGENT; shift 2 ;;
        --cleanup)    DO_CLEANUP=true; shift ;;
        -h|--help)    usage ;;
        *)            err "Option inconnue: $1"; usage ;;
    esac
done

# ============================================================================
# Cleanup (mode indépendant)
# ============================================================================
if [[ "$DO_CLEANUP" == true ]]; then
    cleanup_branches
    exit 0
fi

# ============================================================================
# Mode rebase (indépendant — pas de profil/issue requis)
# ============================================================================
if [[ "$REBASE_MODE" == true ]]; then
    main_rebase
    exit 0
fi

# ============================================================================
# Validation
# ============================================================================
if [[ -z "$PROFILE" && -z "$ISSUE_NUMBER" && "$WORKER_MODE" != true ]]; then
    err "--profile ou --issue ou --worker ou --rebase est requis"
    usage
fi

if [[ -n "$PROFILE" && "$WORKER_MODE" != true ]]; then
    if [[ "$AUDIT_MODE" == true ]]; then
        _check_path="${PROFILES_DIR}/audit/${PROFILE}.md"
        _available_dir="${PROFILES_DIR}/audit"
    else
        _check_path="${PROFILES_DIR}/small_fix/${PROFILE}.md"
        _available_dir="${PROFILES_DIR}/small_fix"
    fi
    if [[ ! -f "$_check_path" ]]; then
        err "Profil inconnu: $PROFILE (mode: $([ "$AUDIT_MODE" == true ] && echo 'audit' || echo 'fix'))"
        err "Disponibles: $(ls "${_available_dir}"/*.md 2>/dev/null | xargs -I{} basename {} .md | tr '\n' ' ')"
        exit 1
    fi
fi

# ============================================================================
# Charger le profil MAINTENANT (avant tout checkout git)
# ============================================================================
PROFILE_CONTENT=""
if [[ -n "$PROFILE" && "$WORKER_MODE" != true ]]; then
    if [[ "$AUDIT_MODE" == true ]]; then
        local_profile="${PROFILES_DIR}/audit/${PROFILE}.md"
    else
        local_profile="${PROFILES_DIR}/small_fix/${PROFILE}.md"
    fi
    PROFILE_CONTENT=$(cat "$local_profile")
    ok "Profil '${PROFILE}' chargé - mode $([ "$AUDIT_MODE" == true ] && echo 'audit' || echo 'fix') (${#PROFILE_CONTENT} chars)"
fi

# ============================================================================
# Dispatch
# ============================================================================
if [[ "$AUDIT_MODE" == true ]]; then
    main_audit
elif [[ "$WORKER_MODE" == true ]]; then
    main_worker
else
    main_fix
fi
