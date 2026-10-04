#!/usr/bin/env bash
# ============================================================================
# AI Pipeline - Audit par groupe de modules
# ============================================================================
# Un passage d'agent par module du groupe, l'un après l'autre, puis un bilan.
# Les groupes sont définis dans config.sh (MODULE_GROUPS).
#
# Usage:
#   scripts/ai_pipeline/audit-groupe.sh --liste
#   scripts/ai_pipeline/audit-groupe.sh <profil> <groupe>... [--apercu]
#   scripts/ai_pipeline/audit-groupe.sh bugs noyau relations
#   scripts/ai_pipeline/audit-groupe.sh amelioration vie-interieure --apercu
#   scripts/ai_pipeline/audit-groupe.sh bugs tout
#   scripts/ai_pipeline/audit-groupe.sh bugs canaux web --un-passage
#
#   --apercu      affiche les constats sans créer d'issues
#   --un-passage  un seul passage d'agent par groupe, au lieu d'un par module :
#                 plus rapide, attentif à ce qui circule entre les modules,
#                 mais moins profond sur chacun
#
# Variables utiles : SEVERITE=high (seuil de gravité), AI_PIPELINE_EFFORT=high.
# Ctrl+C arrête l'agent en cours ET la suite de la série.
# ============================================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/config.sh"
source "${SCRIPT_DIR}/lib/common.sh"
ORCHESTRATOR="${SCRIPT_DIR}/orchestrator.sh"

# Valeur d'une clé du compte rendu d'un passage (cf. report_set).
report_get() {
    sed -n "s/^$2=//p" "$1" | tail -1
}

usage() {
    sed -n '/^# Usage:/,/^# ====/p' "${BASH_SOURCE[0]}" | sed '$d; s/^# \{0,1\}//'
    exit "${1:-0}"
}

list_groups() {
    git -C "$PROJECT_ROOT" fetch --quiet "$REPO_REMOTE" "$BASE_BRANCH" 2>/dev/null || true
    echo "Groupes (modules présents sur ${BASE_REF} / modules du groupe) :"
    echo ""
    local g m total present
    for g in "${MODULE_GROUP_ORDER[@]}"; do
        total=0; present=0
        for m in ${MODULE_GROUPS[$g]}; do
            total=$((total + 1))
            module_in_base "$m" && present=$((present + 1))
        done
        printf '  %-15s %2d/%-2d  %s\n' "$g" "$present" "$total" "${MODULE_GROUP_DESCRIPTIONS[$g]:-}"
    done
    echo ""
    echo "Profils : $(ls "${PROFILES_DIR}/audit" | sed 's/\.md$//' | tr '\n' ' ')"
}

# -- Arguments ------------------------------------------------------------------
[[ $# -eq 0 ]] && usage 1
case "$1" in
    -h|--help) usage ;;
    --liste|--list) list_groups; exit 0 ;;
esac

PROFILE="$1"; shift
if [[ ! -f "${PROFILES_DIR}/audit/${PROFILE}.md" ]]; then
    err "Profil inconnu : ${PROFILE} (disponibles : $(ls "${PROFILES_DIR}/audit" | sed 's/\.md$//' | tr '\n' ' '))"
    exit 1
fi

APERCU=false
ONE_PASS=false
declare -a GROUPS_ASKED=()
for arg in "$@"; do
    case "$arg" in
        --apercu|--no-create) APERCU=true ;;
        --un-passage) ONE_PASS=true ;;
        tout|all) GROUPS_ASKED+=("${MODULE_GROUP_ORDER[@]}") ;;
        *)
            if [[ -z "${MODULE_GROUPS[$arg]+x}" ]]; then
                err "Groupe inconnu : ${arg} (disponibles : ${MODULE_GROUP_ORDER[*]} tout)"
                exit 1
            fi
            GROUPS_ASKED+=("$arg")
            ;;
    esac
done
[[ ${#GROUPS_ASKED[@]} -eq 0 ]] && { err "Aucun groupe demandé"; usage 1; }

# Ce qu'on audite, sans doublon, dans l'ordre des groupes demandés : des
# modules, ou des groupes entiers (« groupe:<nom> ») en --un-passage.
declare -a MODULES_TODO=()
declare -A SEEN=()
for g in "${GROUPS_ASKED[@]}"; do
    if [[ "$ONE_PASS" == true ]]; then
        [[ -n "${SEEN[groupe:$g]:-}" ]] && continue
        SEEN[groupe:$g]=1
        MODULES_TODO+=("groupe:$g")
        continue
    fi
    for m in ${MODULE_GROUPS[$g]}; do
        [[ -n "${SEEN[$m]:-}" ]] && continue
        SEEN[$m]=1
        MODULES_TODO+=("$m")
    done
done

git -C "$PROJECT_ROOT" fetch --quiet "$REPO_REMOTE" "$BASE_BRANCH" 2>/dev/null \
    || warn "git fetch impossible - présence des modules jugée sur l'état connu de ${BASE_REF}"

if [[ "$ONE_PASS" == true ]]; then
    header "Audit ${PROFILE} : ${#MODULES_TODO[@]} groupe(s), un passage chacun$([[ "$APERCU" == true ]] && echo ' - APERÇU')"
else
    header "Audit ${PROFILE} : ${GROUPS_ASKED[*]} (${#MODULES_TODO[@]} module(s))$([[ "$APERCU" == true ]] && echo ' - APERÇU')"
fi

# -- Boucle -----------------------------------------------------------------------
# L'orchestrateur reçoit lui aussi le Ctrl+C et nettoie le worktree ; ici, on
# retient seulement qu'il faut s'arrêter après lui.
INTERRUPTED=false
trap 'INTERRUPTED=true' INT

declare -a ROWS=()
total_issues=0 total_dup=0 total_flag=0 total_below=0
i=0
for m in "${MODULES_TODO[@]}"; do
    i=$((i + 1))

    if [[ "$m" == groupe:* ]]; then
        # Un passage pour tout le groupe : on compte ses modules présents.
        group="${m#groupe:}"
        present=0 total=0
        for gm in ${MODULE_GROUPS[$group]}; do
            total=$((total + 1))
            module_in_base "$gm" && present=$((present + 1))
        done
        what="${present}/${total} module(s) en un passage"
        if (( present == 0 )); then
            ROWS+=("${group}|${what}|pas encore sur ${BASE_REF}|||")
            warn "[${i}/${#MODULES_TODO[@]}] groupe ${group} : aucun module sur ${BASE_REF} (pas encore poussé ?), sauté"
            continue
        fi
        log "[${i}/${#MODULES_TODO[@]}] groupe ${group} : ${what}"
        args=(--audit --profile "$PROFILE" --group "$group")
    else
        group=$(module_group "$m")
        what=$(module_label "$m" | sed 's/^module://')
        if ! module_in_base "$m"; then
            ROWS+=("${group}|${what}|pas encore sur ${BASE_REF}|||")
            warn "[${i}/${#MODULES_TODO[@]}] ${m} : absent de ${BASE_REF} (pas encore poussé ?), sauté"
            continue
        fi
        log "[${i}/${#MODULES_TODO[@]}] ${group} : ${m}"
        args=(--audit --profile "$PROFILE" --modules "$m")
    fi

    report=$(mktemp)
    rc=0
    [[ "$APERCU" == true ]] && args+=(--no-create)
    AI_PIPELINE_REPORT="$report" "$ORCHESTRATOR" "${args[@]}" || rc=$?

    issues=$(report_get "$report" issues)
    dup=$(report_get "$report" doublons)
    flag=$(report_get "$report" a_trancher)
    below=$(report_get "$report" sous_le_seuil)
    rm -f "$report"

    case "$rc" in
        "$EXIT_OK")        result=$([[ "$APERCU" == true ]] && echo "constats (aperçu)" || echo "issues créées") ;;
        "$EXIT_NOTHING")   result="rien à faire" ;;
        "$EXIT_NO_RESULT") result="rien de nouveau" ;;
        "$EXIT_BUSY")      result="occupé (autre instance)" ;;
        130)               result="interrompu" ;;
        *)                 result="échec (code ${rc})" ;;
    esac
    ROWS+=("${group}|${what}|${result}|${issues}|${dup}|${flag}|${below}")
    total_issues=$((total_issues + ${issues:-0}))
    total_dup=$((total_dup + ${dup:-0}))
    total_flag=$((total_flag + ${flag:-0}))
    total_below=$((total_below + ${below:-0}))

    if [[ "$INTERRUPTED" == true || "$rc" -eq 130 ]]; then
        warn "Interruption : la série s'arrête là"
        break
    fi
    if [[ "$rc" -eq "$EXIT_BUSY" ]]; then
        warn "Une autre instance du pipeline travaille : la série s'arrête là"
        break
    fi
done

# -- Bilan ------------------------------------------------------------------------
header "Bilan - audit ${PROFILE}"
printf '%-15s %-50s %-28s %6s %8s %10s %6s\n' "groupe" "module" "résultat" "issues" "doublons" "à trancher" "seuil"
for row in "${ROWS[@]}"; do
    IFS='|' read -r g m r n d f b <<< "$row"
    printf '%-15s %-50s %-28s %6s %8s %10s %6s\n' "$g" "$m" "$r" "${n:--}" "${d:--}" "${f:--}" "${b:--}"
done | tee -a "$LOG_FILE"
echo ""
log "Total : ${total_issues} issue(s) créée(s), ${total_dup} doublon(s) écarté(s), ${total_flag} à trancher, ${total_below} sous le seuil"
[[ "$APERCU" == true ]] && log "Aperçu : rien n'a été créé. Les constats sont dans les journaux de ${LOGS_DIR}."
