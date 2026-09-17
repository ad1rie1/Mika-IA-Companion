#!/usr/bin/env bash
# Sauvegarde de Mika : la base SQLite + le magasin vectoriel Chroma (OPS-10).
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
#     - service ARRÊTÉ (`systemctl --user stop mika`) : instantané exact, et
#       l'arrêt propre a fait un `wal_checkpoint(TRUNCATE)` (config/asgi.py) ;
#     - service EN MARCHE : accepter la fenêtre. SQL est la vérité ; une
#       incohérence entre lignes et vecteurs se resynchronise à la
#       restauration (voir deploy/README.md : `reindexer_vecteurs` +
#       `backfill_episodic`), jamais l'inverse.
#   Le MANIFEST note si le service tournait, pour savoir à la restauration
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
PYTHON="${PYTHON:-python3}"

DB="$RACINE/data/vtuber.db"
CHROMA="${CHROMA_PERSIST_DIR:-$RACINE/data/chromadb}"
case "$CHROMA" in /*) ;; *) CHROMA="$RACINE/$CHROMA" ;; esac

[ -f "$DB" ] || { echo "base introuvable : $DB" >&2; exit 1; }

HORODATAGE="$(date +%Y%m%d-%H%M%S)"
CIBLE="$DEST/mika-$HORODATAGE"
mkdir -p "$CIBLE"

# Le service tourne-t-il ? (indicatif — pour le MANIFEST)
EN_MARCHE="inconnu"
if command -v systemctl >/dev/null 2>&1; then
    if systemctl --user is-active --quiet mika 2>/dev/null || systemctl is-active --quiet mika 2>/dev/null; then
        EN_MARCHE="oui"
    else
        EN_MARCHE="non"
    fi
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
