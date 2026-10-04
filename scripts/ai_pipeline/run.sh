#!/usr/bin/env bash
# ============================================================================
# AI Pipeline - Runner principal
# ============================================================================
# Exécute les tâches par priorité :
#   0. Rebase   (PR du pipeline en conflit ou devenues obsolètes)
#   1. Worker   (issues taggées Propose_AI_PR → PR)
#   2. Audit    (analyse en profondeur → issues)
# puis recommence tant qu'il reste des Propose_AI_PR, et se rendort.
#
# Usage:
#   ./run.sh                  # Tout exécuter par priorité
#   ./run.sh --agent codex    # Utiliser Codex CLI au lieu de Claude Code
#   ./run.sh --max-tasks 3    # Limiter à 3 tâches max
#   ./run.sh --dry-run        # Simuler sans rien exécuter
#
# Surcharges par variable d'environnement : AI_PIPELINE_AGENT,
# AI_PIPELINE_EFFORT, AI_PIPELINE_THINKING_TOKENS (et non AI_AGENT /
# CLAUDE_EFFORT, que le CLI Claude Code exporte déjà pour son propre compte),
# RELOOP_SLEEP_SECONDS, TOKEN_WAIT_SECONDS.
#
# Le pipeline travaille dans son propre worktree : la copie de travail du
# dépôt peut rester sale, et on peut continuer à y travailler pendant qu'il
# tourne.
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/config.sh"
source "${SCRIPT_DIR}/lib/common.sh"

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
    echo -e "${RED}[STOP]${NC} Interruption reçue - arrêt du pipeline"
    # L'orchestrateur reçoit TERM en premier : c'est son trap qui arrête
    # l'agent et remet le worktree à zéro. On lui en laisse le temps avant
    # le KILL.
    local c
    for c in $(pgrep -P $$ 2>/dev/null); do
        kill -TERM "$c" 2>/dev/null || true
    done
    sleep 5
    for c in $(pgrep -P $$ 2>/dev/null); do
        _kill_tree "$c" KILL
    done
    rm -f "${REPORT_FILE:-}"
    exit 130
}

trap _on_interrupt INT TERM

ORCHESTRATOR="${SCRIPT_DIR}/orchestrator.sh"
MAX_TASKS=0        # 0 = illimité
DRY_RUN=false
TASKS_DONE=0
REPORT_FILE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --agent)
            case "${2:-}" in
                claude|codex) AI_AGENT="$2" ;;
                *) echo "Agent inconnu: '${2:-}' (attendu: claude ou codex)"; exit 1 ;;
            esac
            shift 2 ;;
        --max-tasks)  MAX_TASKS="$2"; shift 2 ;;
        --effort)     AI_EFFORT="$2"; CLAUDE_EFFORT="$2"; CODEX_EFFORT="$2"; shift 2 ;;
        --thinking-tokens) CLAUDE_MAX_THINKING_TOKENS="$2"; shift 2 ;;
        --dry-run)    DRY_RUN=true; shift ;;
        -h|--help)
            cat <<EOF
Usage: $(basename "$0") [options]

  --agent claude|codex     Agent IA à utiliser (défaut: \$AI_PIPELINE_AGENT ou claude)
  --max-tasks N            Limiter à N tâches (0 = illimité)
  --effort LEVEL           Budget de réflexion de l'agent
                           claude: low|medium|high|xhigh|max  (défaut: high)
                           codex : minimal|low|medium|high    (défaut: high)
  --thinking-tokens N      Plafond dur du thinking Claude (MAX_THINKING_TOKENS)
  --dry-run                Simuler sans rien exécuter
EOF
            exit 0
            ;;
        *)  echo "Option inconnue: $1"; exit 1 ;;
    esac
done
[[ "$MAX_TASKS" =~ ^[0-9]+$ ]] || { echo "--max-tasks attend un entier (reçu: '${MAX_TASKS}')"; exit 1; }

# Une simulation ne paie pas d'appel d'agent, même pour la sonde.
if [[ "$DRY_RUN" == true ]]; then
    check_ai_tokens() { return 0; }
fi

# Transmis à orchestrator.sh (processus fils qui re-source config.sh) sous les
# noms cloisonnés AI_PIPELINE_* : `AI_AGENT` et `CLAUDE_EFFORT` sont exportés
# par le CLI Claude Code lui-même, cf. le commentaire dans config.sh.
AI_PIPELINE_AGENT="$AI_AGENT"
AI_PIPELINE_EFFORT="${AI_EFFORT:-}"
AI_PIPELINE_THINKING_TOKENS="${CLAUDE_MAX_THINKING_TOKENS:-}"
export AI_AGENT AI_PIPELINE_AGENT AI_PIPELINE_EFFORT AI_PIPELINE_THINKING_TOKENS

# ============================================================================
# Helpers
# ============================================================================
banner() {
    echo -e "\n${CYAN}══════════════════════════════════════════${NC}"
    echo -e "${CYAN}  $*${NC}"
    echo -e "${CYAN}══════════════════════════════════════════${NC}\n"
}

task_limit_reached() {
    [[ "$MAX_TASKS" -gt 0 && "$TASKS_DONE" -ge "$MAX_TASKS" ]]
}

# Renvoie le nombre d'issues Propose_AI_PR ouvertes, ou sort en échec si la
# requête n'a pas abouti — l'appelant ne doit surtout pas lire ça comme un zéro.
count_pending_propose_ai_pr() {
    gh_query gh issue list --state open --limit 1000 --label "Propose_AI_PR" \
        --json number --jq 'length'
}

# Lance l'orchestrateur et rend son code de sortie (contrat : lib/common.sh).
# En arrière-plan + wait pour que Ctrl+C soit traité tout de suite. Le module
# choisi revient par le compte rendu (AI_PIPELINE_REPORT), et non plus en
# cherchant « Module choisi automatiquement: » dans la sortie.
LAST_MODULE=""
run_orchestrator() {
    LAST_MODULE=""
    if [[ "$DRY_RUN" == true ]]; then
        echo -e "${YELLOW}[DRY-RUN]${NC} $ORCHESTRATOR $*"
        return "$EXIT_NOTHING"
    fi

    REPORT_FILE=$(mktemp)
    local rc=0
    AI_PIPELINE_REPORT="$REPORT_FILE" "$ORCHESTRATOR" "$@" &
    wait $! || rc=$?
    LAST_MODULE=$(sed -n 's/^module=//p' "$REPORT_FILE" | tail -1)
    rm -f "$REPORT_FILE"
    REPORT_FILE=""
    return "$rc"
}

# ============================================================================
# ÉTAPE PRÉLIMINAIRE : Rebase/Cleanup des PRs ouvertes
# ============================================================================
run_rebase() {
    banner "ÉTAPE : Rebase / Cleanup des PRs ouvertes"

    if task_limit_reached; then
        echo -e "${YELLOW}[SKIP]${NC} Limite de tâches atteinte"
        return 1
    fi
    if ! check_ai_tokens; then
        echo -e "${RED}[STOP]${NC} Agent IA indisponible - skip rebase"
        return 1
    fi

    local rc=0
    run_orchestrator --rebase || rc=$?
    case "$rc" in
        "$EXIT_OK"|"$EXIT_NOTHING"|"$EXIT_NO_RESULT")
            echo -e "${GREEN}[OK]${NC} Rebase/Cleanup terminé" ;;
        "$EXIT_BUSY")
            echo -e "${YELLOW}[BUSY]${NC} Une autre instance travaille - rebase sauté" ;;
        *)
            echo -e "${YELLOW}[WARN]${NC} Rebase/Cleanup en échec (exit ${rc}) - on continue" ;;
    esac
    return 0
}

# ============================================================================
# PRIORITÉ 1 : Worker (issues Propose_AI_PR → PR)
# ============================================================================
run_workers() {
    banner "PRIORITÉ 1 : Worker (Propose_AI_PR)"

    local pending
    if ! pending=$(count_pending_propose_ai_pr); then
        echo -e "${RED}[STOP]${NC} Impossible de lister les issues Propose_AI_PR - étape worker sautée"
        return 1
    fi
    if [[ "$pending" -eq 0 ]]; then
        echo -e "${GREEN}[OK]${NC} Aucune issue Propose_AI_PR en attente"
        return 0
    fi
    echo -e "${BLUE}[INFO]${NC} ${pending} issue(s) Propose_AI_PR à traiter"

    if task_limit_reached; then
        echo -e "${YELLOW}[SKIP]${NC} Limite de tâches atteinte ($MAX_TASKS)"
        return 1
    fi
    if ! check_ai_tokens; then
        echo -e "${RED}[STOP]${NC} Agent IA indisponible - arrêt du pipeline"
        return 1
    fi

    local rc=0
    run_orchestrator --worker || rc=$?
    case "$rc" in
        "$EXIT_OK")
            TASKS_DONE=$((TASKS_DONE + 1))
            echo -e "${GREEN}[OK]${NC} Worker terminé (tâche #${TASKS_DONE})" ;;
        "$EXIT_NOTHING"|"$EXIT_NO_RESULT")
            echo -e "${BLUE}[INFO]${NC} Worker terminé sans nouvelle PR" ;;
        "$EXIT_BUSY")
            echo -e "${YELLOW}[BUSY]${NC} Une autre instance travaille - worker sauté" ;;
        *)
            echo -e "${YELLOW}[WARN]${NC} Worker en échec (exit ${rc}) - on continue" ;;
    esac
    return 0
}

# ============================================================================
# Balayage des modules pour un profil (fix ou audit)
# ============================================================================
# Tourne tant que l'orchestrateur trouve un module non couvert. Un module déjà
# passé dans cette session est retiré du tirage (AI_PIPELINE_SKIP_MODULES) :
# sans PR ni issue créée, rien d'autre ne le marquerait comme couvert.
#   sweep_modules fix|audit <profil>
sweep_modules() {
    local mode="$1" profile="$2"
    local -a session_skipped=()
    local -a mode_args=(--profile "$profile")
    [[ "$mode" == "audit" ]] && mode_args=(--audit --profile "$profile")

    echo -e "\n${BLUE}[INFO]${NC} ${mode} profil: ${profile} - parcours des modules"

    while true; do
        if task_limit_reached; then
            echo -e "${YELLOW}[SKIP]${NC} Limite de tâches atteinte"
            return 1
        fi
        if ! check_ai_tokens; then
            echo -e "${RED}[STOP]${NC} Agent IA indisponible - arrêt"
            return 1
        fi

        local rc=0
        AI_PIPELINE_SKIP_MODULES="$(IFS=,; echo "${session_skipped[*]}")" \
            run_orchestrator "${mode_args[@]}" || rc=$?
        local picked="${LAST_MODULE:-?}"

        case "$rc" in
            "$EXIT_OK")
                TASKS_DONE=$((TASKS_DONE + 1))
                echo -e "${GREEN}[OK]${NC} ${mode} ${profile}/${picked} terminé (tâche #${TASKS_DONE})"
                ;;
            "$EXIT_NO_RESULT")
                echo -e "${BLUE}[INFO]${NC} ${mode} ${profile}/${picked}: rien à signaler, module suivant"
                ;;
            "$EXIT_NOTHING")
                echo -e "${GREEN}[OK]${NC} Tous les modules couverts pour '${profile}'"
                return 0
                ;;
            "$EXIT_BUSY")
                echo -e "${YELLOW}[BUSY]${NC} Une autre instance travaille - profil '${profile}' sauté"
                return 0
                ;;
            *)
                echo -e "${YELLOW}[WARN]${NC} ${mode} ${profile}/${picked} en échec (exit ${rc}), on passe au profil suivant"
                return 0
                ;;
        esac

        # Sans module connu, on ne peut pas l'exclure : on s'arrête plutôt que
        # de reboucler sur le même tirage.
        if [[ "$picked" == "?" ]]; then
            echo -e "${YELLOW}[WARN]${NC} Module traité inconnu - fin du balayage '${profile}'"
            return 0
        fi
        session_skipped+=("$picked")
    done
}

# PRIORITÉ 2 (hors boucle par défaut) : corrections rapides → PR. Les profils
# bugs/security/quality de small_fix restent lançables par l'orchestrateur ou
# le cron ; pour les remettre dans la boucle, appeler run_fixes dans
# run_pipeline_loop.
run_fixes() {
    banner "PRIORITÉ 2 : Fix (tous les modules)"
    # bugs seul : security et quality ont été retirés de la boucle de fix.
    local -a profiles=("bugs")
    local profile
    for profile in "${profiles[@]}"; do
        sweep_modules fix "$profile" || return 1
    done
}

# PRIORITÉ 3 : Audit (analyse profonde → issues, tous les modules)
run_audits() {
    banner "PRIORITÉ 3 : Audit (tous les modules)"
    # "features" produit des propositions de fonctionnalités. Ses issues ne sont
    # PAS taguées Propose_AI_PR (cf. AUDIT_NO_AUTO_PR_PROFILES) : elles ne
    # partent donc jamais toutes seules en PR, elles attendent un arbitrage.
    local profile
    for profile in "bugs" "quality" "security" "features"; do
        sweep_modules audit "$profile" || return 1
    done
}

# ============================================================================
# BOUCLE PIPELINE : Worker ↔ Audit jusqu'à stabilité, puis réveil périodique
# ============================================================================
# - Boucle interne : alterne run_workers (traite les Propose_AI_PR) et
#   run_audits (crée de nouvelles issues Propose_AI_PR). On itère tant qu'il
#   reste des issues Propose_AI_PR ouvertes après le passage de l'audit.
# - Une fois stable, on dort RELOOP_SLEEP_SECONDS (30 min par défaut) puis on
#   relance un cycle complet pour voir si les PRs ont été mergées / si de
#   nouveaux problèmes apparaissent.
# - MAX_TASKS et indisponibilité de l'agent IA coupent proprement la boucle.
RELOOP_SLEEP_SECONDS="${RELOOP_SLEEP_SECONDS:-1800}"
TOKEN_WAIT_SECONDS="${TOKEN_WAIT_SECONDS:-1800}"

# Attend que l'agent IA ait de nouveau des tokens, en revérifiant toutes les
# TOKEN_WAIT_SECONDS.
wait_for_ai_tokens() {
    local attempt=0
    while ! check_ai_tokens; do
        attempt=$((attempt + 1))
        local next_try
        next_try=$(date -d "+${TOKEN_WAIT_SECONDS} seconds" '+%Y-%m-%d %H:%M' 2>/dev/null || echo "+${TOKEN_WAIT_SECONDS}s")
        echo -e "\n${YELLOW}[WAIT]${NC} Agent IA indisponible (tokens/quota) - tentative ${attempt}"
        echo -e "${YELLOW}       Nouvelle vérification dans $((TOKEN_WAIT_SECONDS / 60)) min (${next_try})${NC}"
        pause_for "$TOKEN_WAIT_SECONDS"
    done
    [[ $attempt -gt 0 ]] && echo -e "${GREEN}[OK]${NC} Tokens à nouveau disponibles après ${attempt} attente(s)"
    return 0
}

run_pipeline_loop() {
    while true; do
        banner "Cycle pipeline démarré : $(date '+%Y-%m-%d %H:%M')"

        local iteration=0
        while true; do
            iteration=$((iteration + 1))
            echo -e "\n${BLUE}[ITER]${NC} Itération ${iteration} du cycle courant"

            wait_for_ai_tokens

            # Étape 0 : Rebase auto des PRs en conflit + fermeture des PRs obsolètes
            run_rebase || true
            task_limit_reached && { echo -e "${YELLOW}[STOP]${NC} Limite de tâches atteinte"; return 0; }

            # Étape 1 : Worker traite toutes les issues Propose_AI_PR existantes
            run_workers || true
            task_limit_reached && { echo -e "${YELLOW}[STOP]${NC} Limite de tâches atteinte"; return 0; }

            # Étape 2 : Audit produit éventuellement de nouvelles issues
            # (déjà taggées Propose_AI_PR → reprises au tour suivant par le worker)
            run_audits || true
            task_limit_reached && { echo -e "${YELLOW}[STOP]${NC} Limite de tâches atteinte"; return 0; }

            if [[ "$DRY_RUN" == true ]]; then
                echo -e "${YELLOW}[DRY-RUN]${NC} Un cycle simulé - arrêt"
                return 0
            fi

            # Étape 3 : on est stable si plus aucune issue Propose_AI_PR n'est ouverte
            local pending
            if ! pending=$(count_pending_propose_ai_pr); then
                echo -e "${RED}[STOP]${NC} Décompte des issues impossible - on ne conclut PAS à la stabilité"
                break
            fi
            if [[ "$pending" -eq 0 ]]; then
                echo -e "${GREEN}[STABLE]${NC} Aucune issue Propose_AI_PR en attente et tous les audits clean"
                break
            fi
            echo -e "${BLUE}[INFO]${NC} ${pending} issue(s) Propose_AI_PR encore ouverte(s) - on relance worker+audit"
        done

        local next_run
        next_run=$(date -d "+${RELOOP_SLEEP_SECONDS} seconds" '+%Y-%m-%d %H:%M' 2>/dev/null || echo "+${RELOOP_SLEEP_SECONDS}s")
        banner "Pipeline stable - prochain cycle : ${next_run}"
        pause_for "$RELOOP_SLEEP_SECONDS"
    done
}

# ============================================================================
# MAIN
# ============================================================================
echo -e "\n${CYAN}══════════════════════════════════════════${NC}"
echo -e "${CYAN}  AI Pipeline - Runner$([[ "$DRY_RUN" == true ]] && echo ' (DRY-RUN)')${NC}"
echo -e "${CYAN}  $(date '+%Y-%m-%d %H:%M')${NC}"
echo -e "${CYAN}  Agent IA: $(ai_agent_label)${NC}"
if [[ "$AI_AGENT" == "claude" ]]; then
    echo -e "${CYAN}  Effort/réflexion: ${CLAUDE_EFFORT}${CLAUDE_MAX_THINKING_TOKENS:+ (max ${CLAUDE_MAX_THINKING_TOKENS} tokens)}${NC}"
else
    echo -e "${CYAN}  Effort/réflexion: ${CODEX_EFFORT:-défaut CLI}${NC}"
fi
echo -e "${CYAN}  Worktree: ${WORK_ROOT}${NC}"
[[ "$MAX_TASKS" -gt 0 ]] && echo -e "${CYAN}  Max tâches: ${MAX_TASKS}${NC}"
echo -e "${CYAN}══════════════════════════════════════════${NC}\n"

# Check initial de l'agent IA (attente si tokens épuisés au démarrage)
wait_for_ai_tokens

# Boucle continue worker↔audit (avec réveil périodique) jusqu'à interruption
# ou atteinte de MAX_TASKS.
run_pipeline_loop || true

banner "Terminé - ${TASKS_DONE} tâche(s) exécutée(s)"
