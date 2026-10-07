#!/bin/bash
# Installe le serveur d'images local dans MIKA_IMAGES_HOME (par défaut /mnt/games/mika-images) :
#   1. stable-diffusion.cpp (construction Vulkan épinglée, empreinte vérifiée) dans bin/ ;
#   2. les poids (≈ 16 Go en Q8_0, reprise possible, empreintes de models.sha256) dans models/ ;
#   3. serve.sh, wait-ready.sh et la configuration dans service/ (les unités systemd y pointent : pas d'espace
#      dans le chemin, et le dépôt peut bouger sans casser le service).
# Le dossier local/ du paquet devient un lien vers MIKA_IMAGES_HOME (ignoré par git), s'il n'est pas déjà autre chose.
# Options : --units  écrit aussi les unités systemd utilisateur (sans les activer) ;
#           --enable  les écrit et active la socket (le serveur démarre à la première demande).
# Rien n'est écrit sur le disque système hors ~/.config/systemd/user (avec --units) et ce lien.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=mika-images.conf
source "${MIKA_IMAGES_CONF:-$here/mika-images.conf}"
H="$MIKA_IMAGES_HOME"
mkdir -p "$H"/{bin,models,service,tmp,out}
export TMPDIR="$H/tmp"
# local/ : les poids, le binaire et les images d'essai vus depuis le paquet (essai.sh … local/out/essai.png)
if [ -L "$here/local" ] || [ ! -e "$here/local" ]; then
    ln -sfn "$H" "$here/local"
fi

# ── 1. le binaire ──
if [ ! -x "$H/bin/sd-server" ] || [ "$(cat "$H/bin/.release" 2>/dev/null)" != "$SD_RELEASE" ]; then
    echo "→ stable-diffusion.cpp $SD_RELEASE"
    curl -sSL --fail --retry 5 -o "$H/tmp/sd.zip" \
        "https://github.com/leejet/stable-diffusion.cpp/releases/download/$SD_RELEASE/$SD_ASSET"
    echo "$SD_SHA256  $H/tmp/sd.zip" | sha256sum -c --quiet
    rm -rf "$H/bin" && mkdir -p "$H/bin"
    (cd "$H/bin" && unzip -q "$H/tmp/sd.zip")
    echo "$SD_RELEASE" > "$H/bin/.release"
    rm -f "$H/tmp/sd.zip"
fi
missing=$(LD_LIBRARY_PATH="$H/bin" ldd "$H/bin/sd-server" | grep "not found" || true)
[ -z "$missing" ] || { echo "bibliothèques manquantes :"; echo "$missing"; exit 1; }

# ── 2. les poids ──
get() {  # dépôt, chemin dans le dépôt
    local name; name="$(basename "$2")"
    if grep -q " $name\$" "$here/models.sha256" && [ -f "$H/models/$name" ] \
            && (cd "$H/models" && grep " $name\$" "$here/models.sha256" | sha256sum -c --quiet 2>/dev/null); then
        return 0
    fi
    echo "→ $name"
    curl -sSL --fail -C - --retry 5 -o "$H/models/$name" "https://huggingface.co/$1/resolve/main/$2"
}
get "$VAE_REPO" "$VAE_FILE"
get "$LLM_REPO" "$VISION_FILE"
get "$DIFFUSION_REPO" "$DIFFUSION_FILE"
get "$LLM_REPO" "$LLM_FILE"
echo "→ vérification des poids"
# seulement ceux qu'on utilise : models.sha256 connaît aussi les variantes qu'on n'a pas téléchargées
used=$(printf '%s\n' "$(basename "$DIFFUSION_FILE")" "$(basename "$VAE_FILE")" "$(basename "$LLM_FILE")" \
       "$(basename "$VISION_FILE")")
(cd "$H/models" && awk 'NR == FNR { want[$0] = 1; next } ($2 in want)' <(echo "$used") "$here/models.sha256" \
    | sha256sum -c --quiet)

# ── 3. le service ──
cp "$here/serve.sh" "$here/wait-ready.sh" "$here/mika-images.conf" "$H/service/"
chmod +x "$H/service/serve.sh" "$H/service/wait-ready.sh"

if [ "${1:-}" = "--units" ] || [ "${1:-}" = "--enable" ]; then
    units="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
    mkdir -p "$units"
    for unit in mika-images.socket mika-images.service mika-images-sd.service; do
        sed -e "s|@HOME@|$H|g" -e "s|@PUBLIC_PORT@|$PUBLIC_PORT|g" -e "s|@SD_PORT@|$SD_PORT|g" \
            -e "s|@IDLE_STOP@|$IDLE_STOP|g" -e "s|@MEMORY_MAX@|${MEMORY_MAX:-16G}|g" \
            "$here/systemd/$unit" > "$units/$unit"
    done
    systemctl --user daemon-reload
    if [ "$1" = "--enable" ]; then
        systemctl --user enable --now mika-images.socket
        echo "socket active : http://127.0.0.1:$PUBLIC_PORT/v1 (le serveur démarre à la première demande)"
    else
        echo "unités écrites ; pour activer : systemctl --user enable --now mika-images.socket"
    fi
fi
echo "installé dans $H"
