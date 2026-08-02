#!/usr/bin/env bash
# ============================================================================
# Trigger manuel - Lancement interactif du pipeline
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORCHESTRATOR="${SCRIPT_DIR}/../orchestrator.sh"

echo "=== AI Pipeline - Lancement manuel ==="
echo ""

# Choix du mode
echo "Mode:"
echo "  1) audit  - Analyser et créer des issues"
echo "  2) fix    - Corriger et créer une PR"
echo "  3) issue  - Corriger une issue spécifique"
echo ""
read -rp "Choix [1-3]: " mode_choice

case "$mode_choice" in
    1) MODE="audit" ;;
    2) MODE="fix" ;;
    3)
        read -rp "Numéro d'issue GitHub: " issue_num
        read -rp "Profil à appliquer (security/bugs/quality, vide=auto): " issue_profile
        exec "$ORCHESTRATOR" --issue "$issue_num" ${issue_profile:+--profile "$issue_profile"}
        ;;
    *) echo "Choix invalide"; exit 1 ;;
esac

# Choix du profil
echo ""
echo "Profils disponibles:"
echo "  1) security  - Audit de sécurité"
echo "  2) bugs      - Détection de bugs"
echo "  3) quality   - Qualité de code"
echo ""
read -rp "Choix [1-3]: " choice

case "$choice" in
    1) PROFILE="security" ;;
    2) PROFILE="bugs" ;;
    3) PROFILE="quality" ;;
    *) echo "Choix invalide"; exit 1 ;;
esac

# Choix des modules
echo ""
echo "Modules disponibles:"
source "${SCRIPT_DIR}/../config.sh"
for i in "${!AVAILABLE_MODULES[@]}"; do
    printf "  %2d) %s\n" $((i+1)) "${AVAILABLE_MODULES[$i]}"
done
echo "   0) Auto (choix intelligent)"
echo ""
read -rp "Modules (numéros séparés par virgule, ou 0 pour auto): " mod_choice

if [[ "$mod_choice" == "0" ]]; then
    MODULES="all"
else
    MODULES=""
    IFS=',' read -ra nums <<< "$mod_choice"
    for num in "${nums[@]}"; do
        num=$(echo "$num" | xargs)
        idx=$((num - 1))
        if [[ $idx -ge 0 && $idx -lt ${#AVAILABLE_MODULES[@]} ]]; then
            [[ -n "$MODULES" ]] && MODULES="${MODULES},"
            MODULES="${MODULES}${AVAILABLE_MODULES[$idx]}"
        fi
    done
fi

AUDIT_FLAG=""
[[ "$MODE" == "audit" ]] && AUDIT_FLAG="--audit"

echo ""
echo "Récapitulatif:"
echo "  Mode:    $MODE"
echo "  Profil:  $PROFILE"
echo "  Modules: $MODULES"
echo ""
read -rp "Lancer ? [o/N]: " confirm

if [[ "$confirm" =~ ^[oOyY]$ ]]; then
    exec "$ORCHESTRATOR" $AUDIT_FLAG --profile "$PROFILE" --modules "$MODULES"
else
    echo "Annulé."
fi
