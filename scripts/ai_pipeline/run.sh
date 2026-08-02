#!/usr/bin/env bash
# ============================================================================
# AI Pipeline - Runner principal
# ============================================================================
# Exécute les tâches par priorité :
#   1. Worker   (issues taggées Propose_AI_PR → PR)
#   2. Fix      (corrections rapides → PR)
#   3. Audit    (analyse en profondeur → issues)
#
# Vérifie la disponibilité de l'agent IA entre chaque étape.
#
# Usage:
#   ./run.sh                  # Tout exécuter par priorité
#   ./run.sh --agent codex    # Utiliser Codex CLI au lieu de Claude Code
#   ./run.sh --max-tasks 3    # Limiter à 3 tâches max
#   ./run.sh --dry-run        # Simuler sans rien exécuter
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/config.sh"
source "${SCRIPT_DIR}/lib/common.sh"

# Couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# ============================================================================
# Arrêt propre : kill récursif de l'arbre de processus (agent IA inclus)
# Les traps bash sont gelés pendant qu'une commande foreground tourne ; on
# utilise `wait` sur l'orchestrateur en background pour que Ctrl+C soit
# immédiat, puis on tue tous les descendants en SIGTERM puis SIGKILL.
# ============================================================================
_kill_tree() {
    local pid=$1 sig=${2:-TERM}
    local child
    for child in $(pgrep -P "$pid" 2>/dev/null); do
        _kill_tree "$child" "$sig"
    done
    kill -"$sig" "$pid" 2>/dev/null || true
}

_on_interrupt() {
    # Éviter réentrance si TERM arrive pendant qu'on traite INT
    trap '' INT TERM
    echo ""
    echo -e "${RED}[STOP]${NC} Ctrl+C reçu - arrêt du pipeline"
    local c
    for c in $(pgrep -P $$ 2>/dev/null); do
        _kill_tree "$c" TERM
    done
    sleep 2
    for c in $(pgrep -P $$ 2>/dev/null); do
        _kill_tree "$c" KILL
    done
    exit 130
}

trap _on_interrupt INT TERM

ORCHESTRATOR="${SCRIPT_DIR}/orchestrator.sh"
# Choix possible ici: "claude" ou "codex" (surchargeable par --agent ou env AI_AGENT)
AI_AGENT="${AI_AGENT:-claude}"
MAX_TASKS=0        # 0 = illimité
DRY_RUN=false
TASKS_DONE=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --agent)      AI_AGENT="$2"; shift 2 ;;
        --max-tasks)  MAX_TASKS="$2"; shift 2 ;;
        --effort)     AI_EFFORT="$2"; CLAUDE_EFFORT="$2"; CODEX_EFFORT="$2"; shift 2 ;;
        --thinking-tokens) CLAUDE_MAX_THINKING_TOKENS="$2"; shift 2 ;;
        --dry-run)    DRY_RUN=true; shift ;;
        -h|--help)
            cat <<EOF
Usage: $(basename "$0") [options]

  --agent claude|codex     Agent IA à utiliser (défaut: \$AI_AGENT ou claude)
  --max-tasks N            Limiter à N tâches (0 = illimité)
  --effort LEVEL           Budget de réflexion de l'agent
                           claude: low|medium|high|xhigh|max
                           codex : minimal|low|medium|high
                           (vide = défaut du CLI / ~/.claude/settings.json)
  --thinking-tokens N      Plafond dur du thinking Claude (MAX_THINKING_TOKENS)
  --dry-run                Simuler sans rien exécuter
EOF
            exit 0
            ;;
        *)  echo "Option inconnue: $1"; exit 1 ;;
    esac
done
export AI_AGENT
# Transmis à orchestrator.sh (processus fils qui re-source config.sh)
export AI_EFFORT CLAUDE_EFFORT CODEX_EFFORT CLAUDE_MAX_THINKING_TOKENS

# ============================================================================
# Helpers
# ============================================================================
task_limit_reached() {
    if [[ "$MAX_TASKS" -gt 0 && "$TASKS_DONE" -ge "$MAX_TASKS" ]]; then
        return 0
    fi
    return 1
}

count_pending_propose_ai_pr() {
    local pending
    pending=$(gh issue list --state open --limit 1000 --label "Propose_AI_PR" \
        --json number --template '{{range .}}{{.number}}{{"\n"}}{{end}}' \
        2>/dev/null || echo "")
    if [[ -z "$pending" ]]; then
        echo 0
    else
        echo "$pending" | grep -c . || echo 0
    fi
}

run_task() {
    local description="$1"
    shift

    if task_limit_reached; then
        echo -e "${YELLOW}[SKIP]${NC} Limite de tâches atteinte ($MAX_TASKS)"
        return 1
    fi

    if ! check_ai_tokens; then
        echo -e "${RED}[STOP]${NC} Agent IA indisponible - arrêt du pipeline"
        return 1
    fi

    echo -e "\n${CYAN}──────────────────────────────────────────${NC}"
    echo -e "${CYAN}  Tâche $((TASKS_DONE + 1)): ${description}${NC}"
    echo -e "${CYAN}──────────────────────────────────────────${NC}\n"

    if [[ "$DRY_RUN" == true ]]; then
        echo -e "${YELLOW}[DRY-RUN]${NC} $ORCHESTRATOR $*"
        TASKS_DONE=$((TASKS_DONE + 1))
        return 0
    fi

    if "$ORCHESTRATOR" "$@"; then
        TASKS_DONE=$((TASKS_DONE + 1))
        echo -e "${GREEN}[OK]${NC} ${description} terminé"
    else
        echo -e "${YELLOW}[WARN]${NC} ${description} échoué (on continue)"
    fi
    return 0
}

# ============================================================================
# ÉTAPE PRÉLIMINAIRE : Rebase/Cleanup des PRs ouvertes
# ============================================================================
# - Rebase automatique des PRs en conflit avec main
# - Fermeture des PRs (et issues liées) devenues non pertinentes
run_rebase() {
    echo -e "\n${CYAN}══════════════════════════════════════════${NC}"
    echo -e "${CYAN}  ÉTAPE : Rebase / Cleanup des PRs ouvertes${NC}"
    echo -e "${CYAN}══════════════════════════════════════════${NC}\n"

    if task_limit_reached; then
        echo -e "${YELLOW}[SKIP]${NC} Limite de tâches atteinte"
        return 1
    fi

    if ! check_ai_tokens; then
        echo -e "${RED}[STOP]${NC} Agent IA indisponible - skip rebase"
        return 1
    fi

    if [[ "$DRY_RUN" == true ]]; then
        echo -e "${YELLOW}[DRY-RUN]${NC} $ORCHESTRATOR --rebase"
        return 0
    fi

    local tmpout
    tmpout=$(mktemp)
    "$ORCHESTRATOR" --rebase 2>&1 | tee "$tmpout" &
    local pipe_pid=$!
    wait "$pipe_pid" || true
    rm -f "$tmpout"

    echo -e "${GREEN}[OK]${NC} Rebase/Cleanup terminé"
    return 0
}

# ============================================================================
# PRIORITÉ 1 : Worker (issues Propose_AI_PR → PR)
# ============================================================================
run_workers() {
    echo -e "\n${CYAN}══════════════════════════════════════════${NC}"
    echo -e "${CYAN}  PRIORITÉ 1 : Worker (Propose_AI_PR)${NC}"
    echo -e "${CYAN}══════════════════════════════════════════${NC}\n"

    local pending
    pending=$(gh issue list --state open --limit 1000 --label "Propose_AI_PR" \
        --json number --template '{{range .}}{{.number}}{{"\n"}}{{end}}' \
        2>/dev/null || echo "")

    if [[ -z "$pending" ]]; then
        echo -e "${GREEN}[OK]${NC} Aucune issue Propose_AI_PR en attente"
        return 0
    fi

    local count
    count=$(echo "$pending" | wc -l)
    echo -e "${BLUE}[INFO]${NC} ${count} issue(s) Propose_AI_PR à traiter"

    run_task "Worker - traitement des issues Propose_AI_PR" --worker || return 1
    return 0
}

# ============================================================================
# PRIORITÉ 2 : Fix (corrections rapides → PR, tous les modules)
# ============================================================================
run_fixes() {
    echo -e "\n${CYAN}══════════════════════════════════════════${NC}"
    echo -e "${CYAN}  PRIORITÉ 2 : Fix (tous les modules)${NC}"
    echo -e "${CYAN}══════════════════════════════════════════${NC}\n"

    # Profils actifs pour le fix (bugs et security désactivés)
    local profiles=("bugs")
    #    local profiles=("bugs" "security" "quality")
    for profile in "${profiles[@]}"; do
        echo -e "\n${BLUE}[INFO]${NC} Profil: ${profile} - parcours des modules"

        # Modules déjà traités dans cette session pour ce profil
        # (évite de repasser sur un module qui n'a rien à corriger tant qu'aucune
        # PR n'a été créée, puisque sans PR le module n'est pas marqué comme "couvert")
        local -a session_skipped=()

        # Boucle tant que pick_available_module trouve des modules non couverts
        while true; do
            if task_limit_reached; then
                echo -e "${YELLOW}[SKIP]${NC} Limite de tâches atteinte"
                unset AI_PIPELINE_SKIP_MODULES
                return 1
            fi

            if ! check_ai_tokens; then
                echo -e "${RED}[STOP]${NC} Agent IA indisponible - arrêt"
                unset AI_PIPELINE_SKIP_MODULES
                return 1
            fi

            # Exporter la liste (CSV) pour pick_available_module via orchestrator.sh
            if [[ ${#session_skipped[@]} -gt 0 ]]; then
                export AI_PIPELINE_SKIP_MODULES="$(IFS=,; echo "${session_skipped[*]}")"
            else
                export AI_PIPELINE_SKIP_MODULES=""
            fi

            # Lancer l'orchestrateur avec sortie visible + capturée dans un fichier temp
            # Background + wait pour que Ctrl+C soit interceptable immédiatement par le trap
            local tmpout
            tmpout=$(mktemp)

            "$ORCHESTRATOR" --profile "$profile" 2>&1 | tee "$tmpout" &
            local pipe_pid=$!
            wait "$pipe_pid" || true

            local output
            output=$(cat "$tmpout")
            rm -f "$tmpout"

            # Extraire le module choisi depuis les logs
            local picked_module
            picked_module=$(echo "$output" | grep -oP '(?<=Module choisi automatiquement: )\S+' || echo "?")

            if echo "$output" | grep -q "Rien à faire"; then
                echo -e "${GREEN}[OK]${NC} Tous les modules couverts pour '${profile}'"
                break
            fi

            if echo "$output" | grep -q "Pipeline terminé avec succès"; then
                TASKS_DONE=$((TASKS_DONE + 1))
                echo -e "${GREEN}[OK]${NC} Fix ${profile}/${picked_module} terminé (tâche #${TASKS_DONE})"
                [[ "$picked_module" != "?" ]] && session_skipped+=("$picked_module")
            elif echo "$output" | grep -q "Aucune modification nécessaire"; then
                echo -e "${BLUE}[INFO]${NC} Fix ${profile}/${picked_module}: rien à corriger, module suivant"
                [[ "$picked_module" != "?" ]] && session_skipped+=("$picked_module")
            else
                echo -e "${YELLOW}[WARN]${NC} Fix ${profile}/${picked_module} échoué, on passe au profil suivant"
                break
            fi
        done
        unset AI_PIPELINE_SKIP_MODULES
    done
    return 0
}

# ============================================================================
# PRIORITÉ 3 : Audit (analyse profonde → issues, tous les modules)
# ============================================================================
run_audits() {
    echo -e "\n${CYAN}══════════════════════════════════════════${NC}"
    echo -e "${CYAN}  PRIORITÉ 3 : Audit (tous les modules)${NC}"
    echo -e "${CYAN}══════════════════════════════════════════${NC}\n"
    #local profiles=("bugs")
    local profiles=("bugs" "quality" "security")
    #local profiles=("security" "bugs" "quality")
    for profile in "${profiles[@]}"; do
        echo -e "\n${BLUE}[INFO]${NC} Audit profil: ${profile} - parcours des modules"

        # Modules déjà traités dans cette session pour ce profil
        # (évite de repasser sur un module sans problème détecté tant qu'aucune
        # issue n'a été créée, puisque sans issue le module n'est pas "couvert")
        local -a session_skipped=()

        while true; do
            if task_limit_reached; then
                echo -e "${YELLOW}[SKIP]${NC} Limite de tâches atteinte"
                unset AI_PIPELINE_SKIP_MODULES
                return 1
            fi

            if ! check_ai_tokens; then
                echo -e "${RED}[STOP]${NC} Agent IA indisponible - arrêt"
                unset AI_PIPELINE_SKIP_MODULES
                return 1
            fi

            # Exporter la liste (CSV) pour pick_audit_available_module via orchestrator.sh
            if [[ ${#session_skipped[@]} -gt 0 ]]; then
                export AI_PIPELINE_SKIP_MODULES="$(IFS=,; echo "${session_skipped[*]}")"
            else
                export AI_PIPELINE_SKIP_MODULES=""
            fi

            # Lancer l'orchestrateur avec sortie visible + capturée dans un fichier temp
            # Background + wait pour que Ctrl+C soit interceptable immédiatement par le trap
            local tmpout
            tmpout=$(mktemp)

            "$ORCHESTRATOR" --audit --profile "$profile" 2>&1 | tee "$tmpout" &
            local pipe_pid=$!
            wait "$pipe_pid" || true

            local output
            output=$(cat "$tmpout")
            rm -f "$tmpout"

            # Extraire le module choisi depuis les logs
            local picked_module
            picked_module=$(echo "$output" | grep -oP '(?<=Module choisi automatiquement: )\S+' || echo "?")

            if echo "$output" | grep -q "Rien à faire"; then
                echo -e "${GREEN}[OK]${NC} Tous les modules audités pour '${profile}'"
                break
            fi

            if echo "$output" | grep -q "Audit terminé avec succès"; then
                TASKS_DONE=$((TASKS_DONE + 1))
                echo -e "${GREEN}[OK]${NC} Audit ${profile}/${picked_module} terminé (tâche #${TASKS_DONE})"
                [[ "$picked_module" != "?" ]] && session_skipped+=("$picked_module")
            elif echo "$output" | grep -q "Aucun problème détecté"; then
                echo -e "${BLUE}[INFO]${NC} Audit ${profile}/${picked_module}: aucun problème détecté, module suivant"
                [[ "$picked_module" != "?" ]] && session_skipped+=("$picked_module")
            else
                echo -e "${YELLOW}[WARN]${NC} Audit ${profile}/${picked_module} - problème, on passe au profil suivant"
                echo "$output" | tail -5
                break
            fi
        done
        unset AI_PIPELINE_SKIP_MODULES
    done
    return 0
}

# ============================================================================
# BOUCLE PIPELINE : Worker ↔ Audit jusqu'à stabilité, puis réveil périodique
# ============================================================================
# Fonctionnement :
#   - Boucle interne : alterne run_workers (traite les Propose_AI_PR) et
#     run_audits (crée de nouvelles issues Propose_AI_PR). On itère tant qu'il
#     reste des issues Propose_AI_PR ouvertes après le passage de l'audit.
#   - Une fois stable (0 issue Propose_AI_PR ET aucun nouvel audit positif),
#     on sleep RELOOP_SLEEP_SECONDS (30 min par défaut) puis on relance un
#     cycle complet pour voir si les PRs ont été mergées / si de nouveaux
#     problèmes apparaissent.
#   - MAX_TASKS et indisponibilité de l'agent IA coupent proprement la boucle.
# ============================================================================
RELOOP_SLEEP_SECONDS="${RELOOP_SLEEP_SECONDS:-1800}"
TOKEN_WAIT_SECONDS="${TOKEN_WAIT_SECONDS:-1800}"

# Boucle bloquante tant que l'agent IA n'a pas de tokens disponibles.
# On retente toutes les TOKEN_WAIT_SECONDS (30 min par défaut, surchargeable).
# Ctrl+C interrompt le sleep via le trap principal.
wait_for_ai_tokens() {
    local attempt=0
    while ! check_ai_tokens; do
        attempt=$((attempt + 1))
        local next_try
        next_try=$(date -d "+${TOKEN_WAIT_SECONDS} seconds" '+%Y-%m-%d %H:%M' 2>/dev/null || echo "+${TOKEN_WAIT_SECONDS}s")
        echo -e "\n${YELLOW}[WAIT]${NC} Agent IA indisponible (tokens/quota) - tentative ${attempt}"
        echo -e "${YELLOW}       Nouvelle vérification dans $((TOKEN_WAIT_SECONDS / 60)) min (${next_try})${NC}"
        sleep "$TOKEN_WAIT_SECONDS"
    done
    [[ $attempt -gt 0 ]] && echo -e "${GREEN}[OK]${NC} Tokens à nouveau disponibles après ${attempt} attente(s)"
    return 0
}

run_pipeline_loop() {
    while true; do
        echo -e "\n${CYAN}══════════════════════════════════════════${NC}"
        echo -e "${CYAN}  Cycle pipeline démarré : $(date '+%Y-%m-%d %H:%M')${NC}"
        echo -e "${CYAN}══════════════════════════════════════════${NC}\n"

        local iteration=0
        while true; do
            iteration=$((iteration + 1))
            echo -e "\n${BLUE}[ITER]${NC} Itération ${iteration} du cycle courant"

            # Boucle d'attente tokens : on ne sort plus, on patiente jusqu'à dispo
            wait_for_ai_tokens

            # Étape 0 : Rebase auto des PRs en conflit + fermeture des PRs obsolètes
            #run_rebase || true

            if task_limit_reached; then
                echo -e "${YELLOW}[STOP]${NC} Limite de tâches atteinte"
                return 0
            fi

            # Étape 1 : Worker traite toutes les issues Propose_AI_PR existantes
            run_workers || true

            if task_limit_reached; then
                echo -e "${YELLOW}[STOP]${NC} Limite de tâches atteinte"
                return 0
            fi

            # Étape 2 : Audit produit éventuellement de nouvelles issues
            # (déjà taggées Propose_AI_PR → reprises au tour suivant par le worker)
            run_audits || true

            if task_limit_reached; then
                echo -e "${YELLOW}[STOP]${NC} Limite de tâches atteinte"
                return 0
            fi

            # Étape 3 : on est stable si plus aucune issue Propose_AI_PR n'est ouverte
            local pending
            pending=$(count_pending_propose_ai_pr)

            if [[ "$pending" -eq 0 ]]; then
                echo -e "${GREEN}[STABLE]${NC} Aucune issue Propose_AI_PR en attente et tous les audits clean"
                break
            fi

            echo -e "${BLUE}[INFO]${NC} ${pending} issue(s) Propose_AI_PR encore ouverte(s) - on relance worker+audit"
        done

        local next_run
        next_run=$(date -d "+${RELOOP_SLEEP_SECONDS} seconds" '+%Y-%m-%d %H:%M' 2>/dev/null || echo "+${RELOOP_SLEEP_SECONDS}s")
        echo -e "\n${CYAN}══════════════════════════════════════════${NC}"
        echo -e "${YELLOW}[SLEEP]${NC} Pipeline stable - réveil dans $((RELOOP_SLEEP_SECONDS / 60)) min pour re-checker"
        echo -e "${CYAN}  Prochain cycle : ${next_run}${NC}"
        echo -e "${CYAN}══════════════════════════════════════════${NC}\n"
        sleep "$RELOOP_SLEEP_SECONDS"
    done
}

# ============================================================================
# MAIN
# ============================================================================
echo -e "\n${CYAN}══════════════════════════════════════════${NC}"
echo -e "${CYAN}  AI Pipeline - Runner$([ "$DRY_RUN" == true ] && echo ' (DRY-RUN)')${NC}"
echo -e "${CYAN}  $(date '+%Y-%m-%d %H:%M')${NC}"
echo -e "${CYAN}  Agent IA: $(ai_agent_label)${NC}"
if [[ "$AI_AGENT" == "claude" ]]; then
    echo -e "${CYAN}  Effort/réflexion: ${CLAUDE_EFFORT:-défaut settings.json}${CLAUDE_MAX_THINKING_TOKENS:+ (max ${CLAUDE_MAX_THINKING_TOKENS} tokens)}${NC}"
else
    echo -e "${CYAN}  Effort/réflexion: ${CODEX_EFFORT:-défaut CLI}${NC}"
fi
[[ "$MAX_TASKS" -gt 0 ]] && echo -e "${CYAN}  Max tâches: ${MAX_TASKS}${NC}"
echo -e "${CYAN}══════════════════════════════════════════${NC}\n"

# Check initial de l'agent IA (attente si tokens épuisés au démarrage)
wait_for_ai_tokens

# Boucle continue worker↔audit (avec réveil périodique) jusqu'à interruption
# ou atteinte de MAX_TASKS.
run_pipeline_loop || true

# Résumé
echo -e "\n${CYAN}══════════════════════════════════════════${NC}"
echo -e "${CYAN}  Terminé - ${TASKS_DONE} tâche(s) exécutée(s)${NC}"
echo -e "${CYAN}══════════════════════════════════════════${NC}\n"
