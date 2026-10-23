#!/usr/bin/env bash
# Borne une commande lourde (suite complète, simulateur, sonde, construction Gradle) : un plafond de mémoire sans
# swap et une durée maximale ; au-delà, seule la commande est tuée, jamais la session. La machine (30 Go) a déjà
# perdu VS Code dans un OOM, quand onze agents tournaient en parallèle (2026-10).
#
#   scripts/borne.sh .venv/bin/python -m pytest -q
#   BORNE_MEM=6G BORNE_TEMPS=40m scripts/borne.sh …
#
# Le code de sortie est celui de la commande (124 : durée dépassée ; 137 : tuée, mémoire comprise).
set -euo pipefail
if [[ $# -eq 0 ]]; then
    echo "usage : $0 commande [arguments…]  (BORNE_MEM, défaut 3G ; BORNE_TEMPS, défaut 25m)" >&2
    exit 2
fi
exec systemd-run --user --scope --quiet \
    -p MemoryMax="${BORNE_MEM:-3G}" -p MemorySwapMax=0 \
    timeout --kill-after=30s "${BORNE_TEMPS:-25m}" "$@"
