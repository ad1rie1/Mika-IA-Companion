#!/bin/bash
# Un essai par l'API native du serveur (une tâche suivie jusqu'à son terme) :
#   essai.sh "<prompt>" [sortie.png] [LARGEURxHAUTEUR]
# Réglages par l'environnement (vides : ceux du serveur) :
#   STEPS=30  CFG=5  SEED=42  NEG="flou, déformé"  CACHE=none|easycache  SCHEDULER=simple  PORT=8190
# Les dimensions sont arrondies au multiple de 32 le plus proche (le modèle l'exige).
# Le premier appel après un arrêt attend que le serveur charge ses poids.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=mika-images.conf
source "${MIKA_IMAGES_CONF:-$here/mika-images.conf}"
prompt="$1"; out="${2:-essai.png}"; size="${3:-1536x864}"; base="http://127.0.0.1:${PORT:-$PUBLIC_PORT}"
start=$(date +%s)
body=$(python3 - "$prompt" "$size" <<'EOF'
import json, os, sys
prompt, size = sys.argv[1], sys.argv[2]
w, h = (max(256, round(int(v) / 32) * 32) for v in size.lower().split("x"))
body = {"prompt": prompt, "negative_prompt": os.environ.get("NEG", ""), "width": w, "height": h,
        "seed": int(os.environ.get("SEED") or -1), "batch_count": 1, "embed_image_metadata": False,
        "output_format": "png"}
sample = {}
if os.environ.get("STEPS"):
    sample["sample_steps"] = int(os.environ["STEPS"])
if os.environ.get("CFG"):
    sample["guidance"] = {"txt_cfg": float(os.environ["CFG"])}
if os.environ.get("SCHEDULER"):
    sample["scheduler"] = os.environ["SCHEDULER"]
if sample:
    body["sample_params"] = sample
if os.environ.get("CACHE"):
    body["cache_mode"] = "disabled" if os.environ["CACHE"] == "none" else os.environ["CACHE"]
print(json.dumps(body))
EOF
)
job=$(curl -sS --fail-with-body --max-time 600 -H "Content-Type: application/json" -d "$body" "$base/sdcpp/v1/img_gen" \
      | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
while true; do
    state=$(curl -sS --max-time 30 "$base/sdcpp/v1/jobs/$job")
    status=$(printf '%s' "$state" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')
    case "$status" in
        completed) break ;;
        failed|cancelled) echo "échec : $state" | head -c 500 >&2; echo >&2; exit 1 ;;
    esac
    sleep 2
done
printf '%s' "$state" | python3 -c 'import base64,json,sys; d=json.load(sys.stdin); open(sys.argv[1],"wb").write(base64.b64decode(d["result"]["images"][0]["b64_json"]))' "$out"
echo "$out ($(( $(date +%s) - start )) s)"
