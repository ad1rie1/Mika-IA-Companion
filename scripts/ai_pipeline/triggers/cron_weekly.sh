#!/usr/bin/env bash
# ============================================================================
# Trigger cron - Analyse périodique automatique
# ============================================================================
# (Le nom est historique : la cadence se règle dans la crontab.)
#
# Installer dans crontab:
#   # Audit toutes les heures (crée des issues)
#   0 * * * * /path/to/cron_weekly.sh audit
#
#   # Worker toutes les 30 min (traite les issues taggées Propose_AI_PR)
#   */30 * * * * /path/to/cron_weekly.sh worker
#
#   # Fix toutes les 4 heures (prend une issue d'audit au hasard)
#   0 */4 * * * /path/to/cron_weekly.sh fix
#
# Deux déclenchements qui se chevauchent ne se marchent plus dessus :
# l'orchestrateur tient un verrou, le second s'arrête aussitôt (« occupé »).
#
# Usage:
#   ./cron_weekly.sh audit    - Mode audit (crée des issues)
#   ./cron_weekly.sh worker   - Mode worker (traite Propose_AI_PR)
#   ./cron_weekly.sh fix      - Mode fix (crée des PR depuis les issues)
#   ./cron_weekly.sh rebase   - Rebase / ferme les PR du pipeline
#   ./cron_weekly.sh          - Défaut: worker
# ============================================================================
set -euo pipefail

# cron démarre avec un PATH minimal : sans ces dossiers, `claude` (installé
# dans ~/.local/bin) et `gh` étaient « introuvables » à chaque déclenchement.
export PATH="${HOME}/.local/bin:${HOME}/bin:/usr/local/bin:${PATH}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORCHESTRATOR="${SCRIPT_DIR}/../orchestrator.sh"
source "${SCRIPT_DIR}/../config.sh"

MODE="${1:-worker}"

# Rotation des profils selon le jour
pick_profile() {
    case $(( $(date +%u) % 3 )) in
        0) echo "security" ;;
        1) echo "bugs" ;;
        2) echo "quality" ;;
    esac
}

echo "[$(date)] === Cron AI Pipeline - mode: ${MODE} ==="

rc=0
case "$MODE" in
    audit)
        PROFILE=$(pick_profile)
        echo "[$(date)] Audit ${PROFILE} - module auto"
        "$ORCHESTRATOR" --audit --profile "$PROFILE" || rc=$?
        ;;
    worker)
        echo "[$(date)] Worker - traitement des issues Propose_AI_PR"
        "$ORCHESTRATOR" --worker || rc=$?
        ;;
    rebase)
        echo "[$(date)] Rebase / nettoyage des PR du pipeline"
        "$ORCHESTRATOR" --rebase || rc=$?
        ;;
    fix)
        PROFILE=$(pick_profile)
        if ! ISSUES=$(gh issue list --state open --limit 1000 \
            --label "ai-audit" \
            --label "ai-${PROFILE}" \
            --json number \
            --jq '.[].number'); then
            echo "[$(date)] Impossible de lister les issues '${PROFILE}'" >&2
            exit 1
        fi
        ISSUE=$(shuf -n 1 <<< "$ISSUES" || true)
        if [[ -z "$ISSUE" ]]; then
            echo "[$(date)] Aucune issue '${PROFILE}' à corriger"
        else
            echo "[$(date)] Fix issue #${ISSUE} (profil: ${PROFILE})"
            "$ORCHESTRATOR" --issue "$ISSUE" --profile "$PROFILE" || rc=$?
        fi
        ;;
    *)
        echo "Mode inconnu: ${MODE} (attendu: audit, worker, fix, rebase)" >&2
        exit 1
        ;;
esac

# 10/11 (rien à faire, rien trouvé) et 75 (une autre instance travaille) ne
# sont pas des échecs : cron enverrait sinon un mail à chaque passage à vide.
case "$rc" in
    0|10|11) ;;
    75) echo "[$(date)] Une autre instance du pipeline travaille - passage sauté" ;;
    *)  echo "[$(date)] === Cron terminé en échec (exit ${rc}) ===" >&2; exit "$rc" ;;
esac

echo "[$(date)] === Cron terminé ==="
