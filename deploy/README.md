# Exploitation — service, arrêt, sauvegarde, restauration

## Le service (`deploy/mika.service`)

Unit systemd utilisateur ; les étapes d'installation sont en tête du fichier.
Deux valeurs sont couplées au code :

- `TimeoutStopSec=60` doit rester **au-dessus** de `BUDGET_ARRET_TOTAL_S`
  (`backend/config/asgi.py`, 45 s) : l'arrêt du lifespan est une suite
  d'étapes bornées, et le SIGKILL de systemd ne doit tomber dans aucune.
  `test_arret_supervise.py` lit l'unit et compare.
- `RestartPreventExitStatus=3` : code de sortie de `run.py` quand la mémoire
  longue a été refusée (`MEMORY_REQUIRE_VECTOR_STORE=1` et Chroma/encodeur en
  panne). Redémarrer en boucle ne répare pas un dossier corrompu.

## Démarrage et `/health`

Le port s'ouvre **avant** le chargement de ChromaDB et du modèle
d'embedding (plusieurs secondes de CPU, en thread). Pendant ce temps :

```
GET /health  →  503  {"status": "starting", "ready": false, "checks": {...}}
```

puis `200 {"status": "ok"}` — ou `200 {"status": "degraded"}` si un rôle
`conversation` n'est pas mappé, une boucle de fond est arrêtée ou en retard,
ou la mémoire longue tourne en repli explicite (`MEMORY_REQUIRE_VECTOR_STORE=0`).
`degraded` reste un 200 : le processus répond, il ne fait que moins bien ;
une sonde qui le redémarrerait pour cela ne réparerait rien. `503
{"status": "failed"}` = mémoire longue refusée, le processus s'arrête.
`503 {"status": "stopping"}` pendant l'arrêt.

Un tour reçu pendant `starting` est traité sans rappel mémoire (la question
est persistée, la réponse ne cite aucun souvenir) — pas d'erreur.

## Sauvegarde (`scripts/backup.sh`)

```
scripts/backup.sh                 # → data/backups/mika-<date>/
scripts/backup.sh /mnt/nas/mika   # destination explicite ; KEEP=14 pour la rotation
```

Produit `vtuber.db` (instantané cohérent par l'API de sauvegarde SQLite, WAL
compris), `chromadb.tar.gz` et un `MANIFEST`. Le script fonctionne service
en marche, avec une réserve : Chroma n'a pas d'instantané, le tar peut
attraper une écriture du consolidateur. **SQL est la vérité** — une
désynchronisation lignes ↔ vecteurs se répare toujours dans ce sens, à la
restauration (ci-dessous). Pour un instantané exact, arrêter le service
avant : l'arrêt propre finit par un `wal_checkpoint(TRUNCATE)`.

**Sauvegarder `.env` à part** : sans `CONFIG_ENCRYPTION_KEY` (ou, à défaut,
`DJANGO_SECRET_KEY`), les clés de providers de la base restaurée sont
indéchiffrables.

Cron utilisateur, chaque nuit à 4 h 30 (après la réorganisation nocturne) :

```
30 4 * * * cd "$HOME/Bureau/PROJET IA/vtuber" && scripts/backup.sh >> data/backups/backup.log 2>&1
```

## Restauration

1. Arrêter le service : `systemctl --user stop mika`.
2. Mettre de côté l'état courant : `mv data/vtuber.db data/vtuber.db.avant`
   (et `-wal` / `-shm` s'ils existent), `mv data/chromadb data/chromadb.avant`.
3. Remettre la base : `cp <backup>/vtuber.db data/vtuber.db`.
4. Remettre Chroma : `tar -C data -xzf <backup>/chromadb.tar.gz`.
   (Ou ne rien remettre : l'étape 6 reconstruit les collections depuis SQL,
   c'est plus long — un encodage par ligne — mais toujours exact.)
5. Restaurer `.env` de la même époque si la clé de chiffrement a changé.
6. **Resynchroniser les vecteurs sur SQL** (nécessaire si le MANIFEST dit
   `service_en_marche=oui`, prudent sinon) :

   ```
   cd backend
   python manage.py migrate                 # si le code a avancé depuis la sauvegarde
   python manage.py reindexer_vecteurs      # souvenirs + connaissances → Chroma, depuis l'ORM
   python manage.py backfill_episodic       # échanges bruts → collection `echanges`
   ```

   `reindexer_vecteurs` ré-upserte chaque `Souvenir` et chaque `Connaissance`
   (idempotent par id, métadonnées recomposées depuis la ligne — importance,
   émotion, thèmes) et retire de Chroma les ids que SQL ne connaît plus ;
   `backfill_episodic` refait les chunks d'échanges. Les deux sont
   ré-exécutables sans risque.
7. `systemctl --user start mika`, puis `curl -s localhost:8000/health` jusqu'à
   `"status": "ok"`. Le consolidateur reprend à son dernier `ConsolidationLog`
   (celui de la sauvegarde) : les messages arrivés après sont ré-extraits
   normalement.

## Ce que l'arrêt fait, dans l'ordre (`config/asgi.py::_shutdown`)

Telegram → file de tours vidée (10 s) puis arrêtée → conscience, modules,
project runner, sleep cycle, emotion sync → passe finale mémoire
(consolidateur : 5 s de grâce au tick en cours, puis annulation ; checkpoint
écrit **par tranche**, donc jamais plus d'une tranche à ré-extraire) → état
émotionnel sauvegardé → diffusions différées → `wal_checkpoint(TRUNCATE)`.
Chaque étape sous `wait_for` ; un dépassement est compté dans le registre de
dégradations (`arret: <étape> hors budget`, visible sur
`/gestion/systeme/sante/`) et l'étape suivante s'exécute quand même.

## Dépôt

`.git` porte encore un blob de 448 Mo (le zip PerulaVRM, désormais supprimé
de la racine et ignoré). À faire par le propriétaire, une fois, quand aucun
autre agent ne travaille dans le checkout :

```
git gc --prune=now --aggressive
```
