#!/bin/bash
# lancer.sh <scénario> [options] : mesure_noyau.py sur un instantané GELÉ de backendv2 (le dossier de travail peut
# être en cours de modification par une autre tâche), sous la borne mémoire, BLAS sur un seul fil.
#   GEL=<dossier> (défaut : $TMPDIR/jumeau-gel) ; REV=<commit> (défaut : HEAD) ; FILS=<n> (défaut : 1)
set -euo pipefail
ICI="$(cd "$(dirname "$0")" && pwd)"
DEPOT="$(cd "$ICI/../.." && pwd)"
REV="${REV:-$(git -C "$DEPOT" rev-parse HEAD)}"
GEL="${GEL:-${TMPDIR:-/tmp}/jumeau-gel-${REV:0:8}}"
if [ ! -d "$GEL/backendv2/src/mika" ]; then
  mkdir -p "$GEL"
  git -C "$DEPOT" archive "$REV" backendv2/src backendv2/persona | tar -x -C "$GEL"
fi
export PYTHONPATH="$GEL/backendv2/src" OPENBLAS_NUM_THREADS="${FILS:-1}" OMP_NUM_THREADS="${FILS:-1}" MKL_NUM_THREADS="${FILS:-1}"
cd "$DEPOT"
exec ~/recup-audit-v2-2026-10-01/outils/borne.sh "$DEPOT/backendv2/.venv/bin/python" "$ICI/mesure_noyau.py" "$@"
