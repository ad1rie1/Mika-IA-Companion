#!/bin/bash
# Lance sd-server (stable-diffusion.cpp) avec Qwen-Image 2.1 : l'API OpenAI (/v1/images/generations,
# /v1/images/edits, /v1/models) et l'API native asynchrone (/sdcpp/v1/*), sur 127.0.0.1 seulement.
# Les réglages viennent de mika-images.conf (à côté de ce script, ou MIKA_IMAGES_CONF).
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=mika-images.conf
source "${MIKA_IMAGES_CONF:-$here/mika-images.conf}"
models="$MIKA_IMAGES_HOME/models"
for f in "$(basename "$DIFFUSION_FILE")" "$(basename "$VAE_FILE")" "$(basename "$LLM_FILE")"; do
    [ -f "$models/$f" ] || { echo "poids absent : $models/$f (lancer install.sh)" >&2; exit 2; }
done
vision=()
[ -f "$models/$(basename "$VISION_FILE")" ] && vision=(--llm_vision "$models/$(basename "$VISION_FILE")")
export LD_LIBRARY_PATH="$MIKA_IMAGES_HOME/bin${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
if [ -z "$GGML_VK_VISIBLE_DEVICES" ]; then
    # « Vulkan1<TAB>NVIDIA GeForce RTX 3060 » : le numéro de ggml du premier périphérique dont le nom correspond
    GGML_VK_VISIBLE_DEVICES=$("$MIKA_IMAGES_HOME/bin/sd-server" --list-devices 2>/dev/null \
        | awk -F'\t' -v m="$GPU_MATCH" '$1 ~ /^Vulkan[0-9]+$/ && index($2, m) { sub("Vulkan", "", $1); print $1; exit }')
    [ -n "$GGML_VK_VISIBLE_DEVICES" ] || { echo "aucun GPU Vulkan ne correspond à « $GPU_MATCH »" >&2; exit 3; }
fi
export GGML_VK_VISIBLE_DEVICES
cache=()
[ -n "$CACHE_MODE" ] && cache=(--cache-mode "$CACHE_MODE")
# shellcheck disable=SC2086 — SD_EXTRA est une liste d'options
exec "$MIKA_IMAGES_HOME/bin/sd-server" \
    --listen-ip 127.0.0.1 --listen-port "$SD_PORT" \
    --diffusion-model "$models/$(basename "$DIFFUSION_FILE")" \
    --vae "$models/$(basename "$VAE_FILE")" \
    --llm "$models/$(basename "$LLM_FILE")" "${vision[@]}" \
    --cfg-scale "$CFG" --sampling-method "$SAMPLER" --scheduler "$SCHEDULER" --steps "$STEPS" "${cache[@]}" \
    --fa --mmap $SD_EXTRA
