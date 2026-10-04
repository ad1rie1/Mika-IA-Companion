#!/usr/bin/env bash
# Sauvegarde de la v1 ARCHIVÉE (old/backend) : la base SQLite + le magasin
# vectoriel Chroma (OPS-10).
#
# Le moteur vivant (backendv2) a sa propre sauvegarde, prouvée par rejeu :
#   backendv2/.venv/bin/python -m mika --data <dossier> backup <archives>
# (voir backendv2/deploy/README.md, et l'unité mika-backup.timer).
#
#   scripts/backup.sh [DOSSIER_DESTINATION]      (défaut : data/backups)
#
# Produit <dest>/mika-<horodatage>/{vtuber.db, chromadb.tar.gz, MANIFEST} et
# garde les KEEP (défaut 7) sauvegardes les plus récentes.
#
# Cohérence — ce qu'il faut savoir avant de l'utiliser :
#
# * La base est copiée par l'API de sauvegarde en ligne de SQLite
#   (`Connection.backup`, via Python — pas de dépendance au binaire sqlite3),
#   qui produit un instantané COHÉRENT même sous écriture concurrente, WAL
#   compris : la copie contient tout ce que le journal `-wal` tient. Le `.db`
#   seul n'aurait pas suffi (sous WAL le fichier principal est en retard sur
#   les écritures jusqu'au checkpoint).
#
# * Chroma n'a pas d'API d'instantané : le tar lit des fichiers que le
#   consolidateur (tick 60 s) et l'indexeur épisodique peuvent être en train
#   d'écrire. Il n'existe pas d'endpoint « pause ». Deux façons propres :
#     - moteur ARRÊTÉ : instantané exact, et l'arrêt propre a fait un
#       `wal_checkpoint(TRUNCATE)` (config/asgi.py) ;
#     - moteur EN MARCHE : accepter la fenêtre. SQL est la vérité ; une
#       incohérence entre lignes et vecteurs se resynchronise à la
#       restauration (`python old/backend/manage.py reindexer_vecteurs` puis
#       `backfill_episodic`), jamais l'inverse.
#   Le MANIFEST note si le moteur tournait, pour savoir à la restauration
#   si la resynchronisation est nécessaire ou seulement prudente.
#
# * Le `.env` (clé de chiffrement des secrets du registre) n'est PAS copié
#   ici : sans CONFIG_ENCRYPTION_KEY / DJANGO_SECRET_KEY, les clés de
#   providers de la base restaurée sont indéchiffrables. Sauvegarder `.env` à
#   part, hors du même disque, et le restaurer avec la base.
set -euo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${1:-$RACINE/data/backups}"
KEEP="${KEEP:-7}"
# KEEP=0 faisait `head -n -0`, qui liste TOUT : la rotation effaçait aussi la
# sauvegarde qu'on venait de faire.
[[ "$KEEP" =~ ^[0-9]+$ && "$KEEP" -ge 1 ]] || { echo "KEEP doit être un entier >= 1 (reçu : $KEEP)" >&2; exit 1; }
PYTHON="${PYTHON:-python3}"

DB="${DB:-$RACINE/data/vtuber.db}"
CHROMA="${CHROMA_PERSIST_DIR:-$RACINE/data/chromadb}"
case "$CHROMA" in /*) ;; *) CHROMA="$RACINE/$CHROMA" ;; esac

[ -f "$DB" ] || { echo "base introuvable : $DB" >&2; exit 1; }

HORODATAGE="$(date +%Y%m%d-%H%M%S)"
CIBLE="$DEST/mika-$HORODATAGE"
mkdir -p "$CIBLE"

# Le moteur v1 tourne-t-il ? (indicatif — pour le MANIFEST)
# Ce n'est plus l'unité systemd `mika` qu'il faut interroger : elle lance
# désormais la v2, et son état faisait écrire « resynchronisation nécessaire »
# dans la sauvegarde d'une v1 arrêtée. La v1 n'a plus d'unité ; on cherche son
# processus ASGI.
EN_MARCHE="non"
if pgrep -f "config\.asgi:application" >/dev/null 2>&1; then
    EN_MARCHE="oui"
fi

echo "→ SQLite : $DB"
"$PYTHON" - "$DB" "$CIBLE/vtuber.db" <<'EOF'
import sqlite3, sys
src = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True, timeout=30)
dst = sqlite3.connect(sys.argv[2])
with dst:
    src.backup(dst)
src.close()
dst.execute("PRAGMA journal_mode=DELETE")
n = dst.execute("PRAGMA integrity_check").fetchone()[0]
dst.close()
if n != "ok":
    sys.exit(f"integrity_check de la copie : {n}")
print("  copie cohérente, integrity_check ok")
EOF

if [ -d "$CHROMA" ]; then
    echo "→ Chroma : $CHROMA"
    tar -C "$(dirname "$CHROMA")" -czf "$CIBLE/chromadb.tar.gz" "$(basename "$CHROMA")"
else
    echo "→ Chroma : dossier absent ($CHROMA), ignoré"
fi

{
    echo "moteur=v1 (old/backend, archivé)"
    echo "date=$HORODATAGE"
    echo "service_en_marche=$EN_MARCHE"
    echo "db=$DB"
    echo "chroma=$CHROMA"
    echo "git=$(git -C "$RACINE" rev-parse --short HEAD 2>/dev/null || echo '?')"
    echo "resynchroniser_a_la_restauration=$([ "$EN_MARCHE" = "non" ] && echo 'prudent' || echo 'necessaire')"
} > "$CIBLE/MANIFEST"

echo "→ écrit dans $CIBLE"
du -sh "$CIBLE"

# Rotation : garder les KEEP plus récentes.
ls -1d "$DEST"/mika-* 2>/dev/null | sort | head -n -"$KEEP" | while read -r vieux; do
    echo "→ rotation : suppression de $vieux"
    rm -rf "$vieux"
done
