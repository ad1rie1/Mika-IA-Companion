#!/usr/bin/env bash
# ============================================================================
# Trigger cron - Analyse périodique automatique
# ============================================================================
# Installer dans crontab:
#   # Audit toutes les heures (crée des issues)
#   0 * * * * /path/to/cron_weekly.sh audit
#
#   # Worker toutes les 30 min (traite les issues taggées Propose_AI_PR)
#   */30 * * * * /path/to/cron_weekly.sh worker
#
#   # Fix toutes les 4 heures (prend une issue au hasard)
#   0 */4 * * * /path/to/cron_weekly.sh fix
#
# Usage:
#   ./cron_weekly.sh audit    - Mode audit (crée des issues)
#   ./cron_weekly.sh worker   - Mode worker (traite Propose_AI_PR)
#   ./cron_weekly.sh fix      - Mode fix (crée des PR depuis les issues)
#   ./cron_weekly.sh          - Défaut: worker
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORCHESTRATOR="${SCRIPT_DIR}/../orchestrator.sh"
source "${SCRIPT_DIR}/../config.sh"

MODE="${1:-worker}"

echo "[$(date)] === Cron AI Pipeline - mode: ${MODE} ==="

if [[ "$MODE" == "audit" ]]; then
    # Rotation des profils selon le jour
    DAY_OF_WEEK=$(date +%u)
    case $((DAY_OF_WEEK % 3)) in
        0) PROFILE="security" ;;
        1) PROFILE="bugs" ;;
        2) PROFILE="quality" ;;
    esac
    echo "[$(date)] Audit ${PROFILE} - module auto"
    "$ORCHESTRATOR" --audit --profile "$PROFILE"

elif [[ "$MODE" == "worker" ]]; then
    # Worker : traite les issues taggées Propose_AI_PR
    echo "[$(date)] Worker - traitement des issues Propose_AI_PR"
    "$ORCHESTRATOR" --worker

elif [[ "$MODE" == "fix" ]]; then
    # Fix : prendre une issue ouverte au hasard et la corriger
    DAY_OF_WEEK=$(date +%u)
    case $((DAY_OF_WEEK % 3)) in
        0) PROFILE="security" ;;
        1) PROFILE="bugs" ;;
        2) PROFILE="quality" ;;
    esac
    ISSUE=$(gh issue list --state open \
        --label "ai-audit" \
        --label "ai-${PROFILE}" \
        --json number \
        --template '{{range .}}{{.number}}{{"\n"}}{{end}}' 2>/dev/null | shuf -n 1 || echo "")

    if [[ -z "$ISSUE" ]]; then
        echo "[$(date)] Aucune issue '${PROFILE}' à corriger"
    else
        echo "[$(date)] Fix issue #${ISSUE} (profil: ${PROFILE})"
        "$ORCHESTRATOR" --issue "$ISSUE" --profile "$PROFILE"
    fi
fi

echo "[$(date)] === Cron terminé ==="
