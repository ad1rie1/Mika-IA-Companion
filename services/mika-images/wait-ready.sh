#!/bin/bash
# Attend que sd-server réponde (il charge ses poids avant d'écouter) : le relais ne lui passe une connexion
# qu'une fois prêt. Échoue après WAIT_READY_S secondes.
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=mika-images.conf
source "${MIKA_IMAGES_CONF:-$here/mika-images.conf}"
deadline=$(( $(date +%s) + ${WAIT_READY_S:-300} ))
until curl -sf -o /dev/null "http://127.0.0.1:$SD_PORT/v1/models"; do
    [ "$(date +%s)" -lt "$deadline" ] || { echo "sd-server n'a pas répondu à temps" >&2; exit 1; }
    sleep 0.5
done
