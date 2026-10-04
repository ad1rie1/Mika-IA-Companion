#!/usr/bin/env bash
# ============================================================================
# AI Pipeline - Orchestrateur
# ============================================================================
# Point d'entrée unique. Parse les arguments et dispatch vers le bon mode.
#
# Usage:
#   ./orchestrator.sh --audit --profile security --modules backendv2/src/mika/faculties/memory
#   ./orchestrator.sh --profile bugs --modules backendv2/src/mika/kernel
#   ./orchestrator.sh --worker
#   ./orchestrator.sh --issue 42
#   ./orchestrator.sh --cleanup
#
# Codes de sortie (contrat lu par run.sh, cf. lib/common.sh) :
#   0 travail livré · 1 échec · 10 rien à faire · 11 passage sans résultat
#   75 une autre instance travaille déjà
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
# Trap SIGINT/SIGTERM - arrêt de l'agent et remise à zéro du WORKTREE
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
    err "Interruption - arrêt de l'agent et nettoyage du worktree..."

    # Tuer les processus fils (agent IA, timeout) : SIGTERM puis SIGKILL
    local c
    for c in $(pgrep -P $$ 2>/dev/null); do
        _kill_tree "$c" TERM
    done
    sleep 2
    for c in $(pgrep -P $$ 2>/dev/null); do
        _kill_tree "$c" KILL
    done

    # Ce nettoyage faisait `git checkout -- .` puis `git clean -fd` dans la
    # copie de travail de l'utilisateur : un Ctrl+C effaçait ses modifications
    # non commitées. Il n'agit plus que dans le worktree du pipeline, et
    # seulement si l'orchestrateur s'y trouve.
    if [[ -d "$WORK_ROOT" && "$(pwd -P)" == "$(cd "$WORK_ROOT" && pwd -P)" ]]; then
        local current_branch
        current_branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
        if [[ "$current_branch" == "${BRANCH_PREFIX}/"* ]]; then
            warn "Abandon de ${current_branch}"
            finish_task_branch "$current_branch" || true
        else
            workspace_reset "interruption" || true
        fi
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
  --profile PROFILE     Profil (requis sauf --issue/--worker/--rebase)
                        audit : $(ls "${PROFILES_DIR}/audit" | sed 's/\.md$//' | tr '\n' ' ')
                        fix   : $(ls "${PROFILES_DIR}/small_fix" | sed 's/\.md$//' | tr '\n' ' ')
  --modules MODULES     Modules ciblés (virgules) ou "all" (défaut: auto)
  --no-create           Ne rien créer sur GitHub (test local)
  --dry-run             Afficher ce qui serait fait sans rien exécuter
  --branch NAME         Nom de branche custom
  --agent claude|codex  Agent IA à utiliser (défaut: config.sh)
  --cleanup             Supprimer les branches ${BRANCH_PREFIX}/* mergées
  -h, --help            Afficher cette aide

Le pipeline travaille dans son worktree (${WORK_ROOT}),
jamais dans la copie de travail du dépôt.

EXEMPLES:
  $(basename "$0") --audit --profile security
  $(basename "$0") --profile bugs --modules backendv2/src/mika/kernel
  $(basename "$0") --worker
  $(basename "$0") --issue 42
  $(basename "$0") --cleanup

EOF
    exit "${1:-0}"
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

_need_value() {
    [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || { err "L'option $1 attend une valeur"; usage "$EXIT_FAIL"; }
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --profile)    _need_value "$@"; PROFILE="$2"; shift 2 ;;
        --modules)    _need_value "$@"; MODULES="$2"; shift 2 ;;
        --issue)      _need_value "$@"; ISSUE_NUMBER="$2"; shift 2 ;;
        --audit)      AUDIT_MODE=true; shift ;;
        --worker)     WORKER_MODE=true; shift ;;
        --rebase)     REBASE_MODE=true; shift ;;
        --no-create)  NO_CREATE=true; shift ;;
        --no-pr)      NO_CREATE=true; shift ;;
        --dry-run)    DRY_RUN=true; shift ;;
        --branch)     _need_value "$@"; CUSTOM_BRANCH="$2"; shift 2 ;;
        --agent)
            _need_value "$@"
            case "$2" in
                claude|codex) AI_AGENT="$2"; export AI_AGENT ;;
                *) err "Agent inconnu: '$2' (attendu: claude ou codex)"; exit "$EXIT_FAIL" ;;
            esac
            shift 2 ;;
        --cleanup)    DO_CLEANUP=true; shift ;;
        -h|--help)    usage ;;
        *)            err "Option inconnue: $1"; usage "$EXIT_FAIL" ;;
    esac
done

if [[ -n "$ISSUE_NUMBER" && ! "$ISSUE_NUMBER" =~ ^[0-9]+$ ]]; then
    err "--issue attend un numéro (reçu: '${ISSUE_NUMBER}')"
    exit "$EXIT_FAIL"
fi
if [[ -n "$CUSTOM_BRANCH" && "$CUSTOM_BRANCH" != "${BRANCH_PREFIX}/"* ]]; then
    # Le nettoyage d'interruption ne referme que les branches du pipeline.
    err "--branch doit commencer par ${BRANCH_PREFIX}/ (reçu: '${CUSTOM_BRANCH}')"
    exit "$EXIT_FAIL"
fi

prune_logs

# Un seul pipeline à la fois dans le worktree. Le dry-run ne le touche pas.
[[ "$DRY_RUN" != true ]] && acquire_pipeline_lock

# ============================================================================
# Modes indépendants (pas de profil requis)
# ============================================================================
if [[ "$DO_CLEANUP" == true ]]; then
    cleanup_branches
    exit "$EXIT_OK"
fi

if [[ "$REBASE_MODE" == true ]]; then
    main_rebase
fi

# ============================================================================
# Validation et chargement du profil (avant tout travail git)
# ============================================================================
if [[ -z "$PROFILE" && -z "$ISSUE_NUMBER" && "$WORKER_MODE" != true ]]; then
    err "--profile ou --issue ou --worker ou --rebase est requis"
    usage "$EXIT_FAIL"
fi

PROFILE_CONTENT=""
if [[ "$WORKER_MODE" != true ]]; then
    if [[ -n "$PROFILE" ]]; then
        _mode_dir="small_fix"
        [[ "$AUDIT_MODE" == true ]] && _mode_dir="audit"
        _profile_path="${PROFILES_DIR}/${_mode_dir}/${PROFILE}.md"
        # Le nom de profil vient aussi du webhook : on refuse tout ce qui
        # sortirait du dossier des profils.
        if [[ ! "$PROFILE" =~ ^[a-z_]+$ || ! -f "$_profile_path" ]]; then
            err "Profil inconnu: $PROFILE (mode: ${_mode_dir})"
            err "Disponibles: $(ls "${PROFILES_DIR}/${_mode_dir}" | sed 's/\.md$//' | tr '\n' ' ')"
            exit "$EXIT_FAIL"
        fi
    elif [[ -n "$ISSUE_NUMBER" ]]; then
        # Une issue sans profil partait avec un prompt sans consigne de rôle.
        _profile_path="${PROFILES_DIR}/large_issue/refactor.md"
    fi
    PROFILE_CONTENT=$(cat "$_profile_path")
    ok "Profil '${PROFILE:-refactor}' chargé - mode $([[ "$AUDIT_MODE" == true ]] && echo 'audit' || echo 'fix') (${#PROFILE_CONTENT} chars)"
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
