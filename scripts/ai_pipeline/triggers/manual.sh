#!/usr/bin/env bash
# ============================================================================
# Trigger manuel - Lancement interactif du pipeline
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORCHESTRATOR="${SCRIPT_DIR}/../orchestrator.sh"
source "${SCRIPT_DIR}/../config.sh"

# Propose les profils réellement présents dans le dossier du mode, plutôt
# qu'une liste écrite à la main (« features » n'y figurait pas).
choose_profile() {
    local dir="$1"
    local -a profiles=()
    mapfile -t profiles < <(ls "$dir" | sed 's/\.md$//')

    echo "" >&2
    echo "Profils disponibles:" >&2
    local i
    for i in "${!profiles[@]}"; do
        printf "  %d) %s\n" $((i + 1)) "${profiles[$i]}" >&2
    done
    echo "" >&2

    local choice
    read -rp "Choix [1-${#profiles[@]}]: " choice
    if [[ ! "$choice" =~ ^[0-9]+$ ]] || (( choice < 1 || choice > ${#profiles[@]} )); then
        echo "Choix invalide" >&2
        exit 1
    fi
    echo "${profiles[$((choice - 1))]}"
}

echo "=== AI Pipeline - Lancement manuel ==="
echo ""
echo "Mode:"
echo "  1) audit  - Analyser et créer des issues"
echo "  2) fix    - Corriger et créer une PR"
echo "  3) issue  - Corriger une issue spécifique"
echo "  4) rebase - Rebase / fermer les PR du pipeline"
echo ""
read -rp "Choix [1-4]: " mode_choice

case "$mode_choice" in
    1) MODE="audit" ;;
    2) MODE="fix" ;;
    3)
        read -rp "Numéro d'issue GitHub: " issue_num
        [[ "$issue_num" =~ ^[0-9]+$ ]] || { echo "Numéro invalide"; exit 1; }
        read -rp "Profil à appliquer (security/bugs/quality, vide=auto): " issue_profile
        exec "$ORCHESTRATOR" --issue "$issue_num" ${issue_profile:+--profile "$issue_profile"}
        ;;
    4) exec "$ORCHESTRATOR" --rebase ;;
    *) echo "Choix invalide"; exit 1 ;;
esac

if [[ "$MODE" == "audit" ]]; then
    PROFILE=$(choose_profile "${PROFILES_DIR}/audit")
else
    PROFILE=$(choose_profile "${PROFILES_DIR}/small_fix")
fi

# Choix des modules
echo ""
echo "Modules disponibles:"
for i in "${!AVAILABLE_MODULES[@]}"; do
    printf "  %2d) %s\n" $((i+1)) "${AVAILABLE_MODULES[$i]}"
done
echo "   0) Auto (un module non encore couvert, au hasard)"
echo ""
read -rp "Modules (numéros séparés par virgule, ou 0 pour auto): " mod_choice

if [[ "$mod_choice" == "0" ]]; then
    MODULES="all"
else
    MODULES=""
    IFS=',' read -ra nums <<< "$mod_choice"
    for num in "${nums[@]}"; do
        num=$(echo "$num" | xargs)
        [[ "$num" =~ ^[0-9]+$ ]] || continue
        idx=$((num - 1))
        if [[ $idx -ge 0 && $idx -lt ${#AVAILABLE_MODULES[@]} ]]; then
            [[ -n "$MODULES" ]] && MODULES="${MODULES},"
            MODULES="${MODULES}${AVAILABLE_MODULES[$idx]}"
        fi
    done
    [[ -n "$MODULES" ]] || { echo "Aucun module valide choisi"; exit 1; }
fi

AUDIT_FLAG=()
[[ "$MODE" == "audit" ]] && AUDIT_FLAG=(--audit)

echo ""
echo "Récapitulatif:"
echo "  Mode:    $MODE"
echo "  Profil:  $PROFILE"
echo "  Modules: $MODULES"
echo ""
read -rp "Lancer ? [o/N]: " confirm

if [[ "$confirm" =~ ^[oOyY]$ ]]; then
    exec "$ORCHESTRATOR" "${AUDIT_FLAG[@]}" --profile "$PROFILE" --modules "$MODULES"
else
    echo "Annulé."
fi
