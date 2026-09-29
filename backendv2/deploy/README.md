# Mika v2 en service

Ce qu'il faut pour la faire tourner sur une machine, la surveiller, la
sauvegarder et la restaurer. Les commandes supposent le dépôt dans
`/opt/mika`, les données dans `/var/lib/mika` et les archives dans
`/var/backups/mika` ; ajuste les unités si tu choisis d'autres chemins.

## Installer

```bash
sudo useradd --system --home /var/lib/mika --shell /usr/sbin/nologin mika
sudo install -d -o mika -g mika -m 0700 /var/lib/mika /var/backups/mika
sudo git clone <dépôt> /opt/mika
cd /opt/mika/backendv2
sudo python3 -m venv .venv
sudo .venv/bin/pip install -e ".[llm,memory]"
sudo dnf install bubblewrap        # ou apt install bubblewrap : la Forge et les ateliers en ont besoin
```

Bubblewrap doit pouvoir créer des espaces de noms utilisateur sans être
setuid (le cas sur Fedora ; sur Debian/Ubuntu, vérifier
`kernel.unprivileged_userns_clone=1` et, sur Ubuntu 24.04+, le profil
AppArmor de `bwrap`). Sans bubblewrap, rien de ce qui exécute du code ne
tourne — il n'y a pas de repli.

`/etc/mika/mika.env` (facultatif, droits 0600) :

```ini
# La clé qui chiffre les secrets rangés dans mind.db (clés d'API, jeton
# Telegram, mot de passe IMAP). Sans elle, un fichier secret.key est créé
# dans /var/lib/mika au premier démarrage — et il est sauvegardé avec le reste.
# Si tu la mets ici, sauvegarde-la à part : sans elle, les secrets sont perdus.
#MIKA_SECRET_KEY=...
```

Puis :

```bash
sudo cp deploy/mika.service deploy/mika-backup.service deploy/mika-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mika.service mika-backup.timer
```

Le serveur écoute sur `127.0.0.1:8001`. Pour l'ouvrir au réseau, place un
mandataire TLS devant (Caddy, nginx) plutôt que de changer `--host`.

## Premier démarrage

1. Ouvre le frontend : le premier compte créé est opérateur (ou
   `sudo -u mika .venv/bin/python -m mika --data /var/lib/mika account <nom> <mot de passe> --operator`).
2. `http://localhost:8001/inspecteur/modeles` : déclare un fournisseur (sa clé
   est chiffrée et jamais réaffichée) et associe les rôles. Tant qu'aucun
   modèle n'est branché, `/health` dit `degraded` et elle ne peut pas parler.
3. Le reste se règle dans l'inspecteur : persona, tempérament, canaux
   (Telegram), sens (courrier, flux, transcription, appareils), comptes.

## Surveiller

`GET /health` est public et ne dit que des noms et des états :

```json
{"status": "ok", "ready": true, "checks": {"journal": "ok", "slices": "ok", "loops": "ok",
 "projections": "ok", "processes": "ok", "outbox": "ok", "llm": "ok", "lanes": "ok"}}
```

| `status` | code | sens |
|---|---|---|
| `ok` | 200 | tout va bien |
| `degraded` | 200 | elle répond, moins bien (pas de modèle, projection en retard, processus qui échoue, file de sortie bloquée) |
| `ko` | 200 | quelque chose est cassé et rien ne le réparera seul (tranche corrompue, boucle arrêtée) : regarder l'inspecteur, redémarrer |
| `starting`, `stopping` | 503 | pas prête |

Le détail de chaque contrôle est dans l'inspecteur, page **Santé** ; les
journaux dans `journalctl -u mika`. Les coûts et le taux de cache des appels
de modèle sont dans la page **Appels de modèle**.

## Sauvegarder

Le minuteur fait une archive chaque nuit à 3 h 30 et garde les 14 dernières.
À la main (sans risque serveur en marche) :

```bash
sudo -u mika /opt/mika/backendv2/.venv/bin/python -m mika --data /var/lib/mika backup /var/backups/mika
sudo -u mika /opt/mika/backendv2/.venv/bin/python -m mika verify /var/backups/mika/mika-AAAAMMJJ-HHMMSS.tar.gz
```

Une archive contient `mind.db` (sa vie : le journal, les contenus, les
comptes, les réglages), les caches du courrier et des flux, ses apps forgées,
ses ateliers et `secret.key`, avec un manifeste (sommes SHA-256, tête du
journal, empreinte de l'état rejoué depuis la copie). `views.db` n'y est pas :
projections et vecteurs se reconstruisent depuis le journal. Copie les
archives ailleurs que sur la machine.

## Restaurer

```bash
sudo systemctl stop mika
sudo -u mika /opt/mika/backendv2/.venv/bin/python -m mika --data /var/lib/mika restore \
    /var/backups/mika/mika-AAAAMMJJ-HHMMSS.tar.gz --force
sudo -u mika /opt/mika/backendv2/.venv/bin/python -m mika --data /var/lib/mika replay --verify
sudo systemctl start mika
curl -s localhost:8001/health
```

La restauration vérifie les sommes et rejoue la copie **avant** de toucher au
dossier ; l'ancien dossier est mis de côté (`/var/lib/mika.avant-restauration-…`),
jamais effacé. Au démarrage, les vues se reconstruisent (le rappel est moins
bon quelques minutes, le temps de réindexer les souvenirs).

## Mettre à jour

```bash
sudo -u mika /opt/mika/backendv2/.venv/bin/python -m mika --data /var/lib/mika backup /var/backups/mika
cd /opt/mika && sudo git pull && cd backendv2 && sudo .venv/bin/pip install -e ".[llm,memory]"
sudo systemctl restart mika
```

Une faculté dont la tranche change de version est reconstruite depuis le
journal au démarrage ; une projection qui change de version est reconstruite
à côté puis basculée. Rien à migrer à la main.

## Oublier quelqu'un

```bash
sudo systemctl stop mika
sudo -u mika /opt/mika/backendv2/.venv/bin/python -m mika --data /var/lib/mika forget user_12
sudo systemctl start mika
```

Ses contenus sont effacés de `mind.db`, des vues et des journaux WAL ; les
**archives** plus anciennes les contiennent encore, jusqu'à leur rotation.
