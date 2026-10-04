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
sudo .venv/bin/pip install -e ".[llm,memory,documents]"   # documents : lire les PDF
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
# des dépôts git, mot de passe IMAP). Sans elle, un fichier secret.key est créé
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

## Derrière un mandataire TLS

Trois options de `serve`, à ajouter à `ExecStart` dans `mika.service` :

- `--origin https://mika.example` (répétable) : l'origine du frontend servi en
  HTTPS. Elle **remplace** les origines de développement (`localhost:3000`…) :
  sans elle, le navigateur se voit refuser CORS, CSRF et la WebSocket.
- `--behind-proxy` : l'adresse du client est lue dans `X-Forwarded-For` (envoyé
  par un mandataire **local** seulement — 127.0.0.1, ::1) ; l'étranglement des
  connexions vise alors la vraie adresse. Implique `--cookie-secure`.
- `--cookie-secure` : cookies de session et CSRF marqués `Secure`.

```bash
ExecStart=/opt/mika/backendv2/.venv/bin/python -m mika --data /var/lib/mika serve --host 127.0.0.1 --port 8001 \
    --origin https://mika.example --behind-proxy
```

Le mandataire **doit** transmettre l'adresse du client (`X-Forwarded-For`) et
**ne jamais** relayer `/mcp/` : ces points (le relais de Claude Code, la console
MCP) ne servent que la machine elle-même, et refusent toute requête qui porte
un en-tête de mandataire — fermer le chemin chez le mandataire est la seconde
porte. Caddy transmet l'adresse de lui-même :

```
mika.example {
    @mcp path /mcp/*
    respond @mcp 404
    reverse_proxy 127.0.0.1:8001
}
```

nginx :

```nginx
location /mcp/ { return 404; }
location / {
    proxy_pass http://127.0.0.1:8001;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;          # la WebSocket (/ws)
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 120s;                          # le client garde sa WebSocket par des pings
}
```

Les journaux ne portent aucun secret : un jeton passé en paramètre d'URL et un
`Bearer` sont masqués ; `httpx` ne parle qu'en avertissement.

L'application Android (ADR 0062) est un client natif : elle n'a pas d'origine à
déclarer (`--origin` ne la concerne pas), et passe `Authorization: Bearer …` et
`X-Mika-Presence` à la mise à niveau de `/ws`. Caddy et nginx les transmettent tels
quels (ne les retire pas). En arrière-plan, elle garde sa WebSocket par des pings
toutes les 20 s : `proxy_read_timeout` doit rester au-dessus (120 s ci-dessus).
Les fichiers qu'elle télécharge (`/files/…`) passent par le même mandataire. Ceux que
Mika envoie sont gardés hors du journal, dans `partages/` du dossier de données
(droits 0700/0600) : la sauvegarde les emporte et la restauration les remet.

## Premier démarrage

1. Ouvre la console (`http://localhost:8001/`) ou le frontend : le premier compte créé est opérateur (ou
   `sudo -u mika .venv/bin/python -m mika --data /var/lib/mika account <nom> --operator`, le mot de passe
   demandé sans écho).
2. `http://localhost:8001/inspecteur/reglages/fournisseurs` (la console, **Configuration ›
   Fournisseurs**) : ajoute un fournisseur (sa clé est chiffrée et jamais réaffichée ;
   « Charger la liste » propose ses modèles). Le premier déclaré sert « répondre » d'office.
   Tant qu'aucun modèle n'est branché, `/health` dit `degraded` et elle ne peut
   pas parler.
3. Le reste se règle dans la console, **Réglages** : personnalité et tempérament
   (avec ce que pilote chaque curseur), paramètres internes (lisibles ; une
   surcharge seulement dans le bloc « avancé », bornée et journalisée), canaux
   (dépôts git), sens (courrier, flux, transcription, appareils), comptes. Chaque
   enregistrement laisse une ligne dans **Journal de configuration**.
   On lui écrit par une application dédiée (le frontend web, le client Unity),
   avec un compte : il n'y a pas de robot de messagerie (ADR 0060). Un client
   natif s'authentifie par un jeton de son compte (`mika token create <compte>`).
4. Ses boîtes aux lettres : **Courrier › Comptes** (ou Réglages › Sens ›
   Courrier) — un enregistrement par boîte : serveurs IMAP/SMTP, dossiers
   relevés, et sa voix (en son nom, en assistante, ou à ta place ; ton,
   consignes, signature ; préparer des réponses d'elle-même). « Tester la
   connexion » sur la fiche du compte. En ligne de commande, serveur arrêté :
   `mika mail set --compte perso --address … --imap-host … --user … --password …
   --smtp-host … --voix proprietaire --nom "Ton Nom"` (`mika mail show`,
   `mika mail remove --compte perso`). Rien de ce qu'elle rédige ne part sans
   ton accord (Courrier › Brouillons).

Pour relire la console sans serveur (après une mise à jour, par exemple) :
`.venv/bin/python -m mika console apercu --out /tmp/console` exporte chaque
page, en clair et en sombre, d'une Mika neuve (modèle factice, rien ne sort de
la machine) ; ouvrir `/tmp/console/index.html`.

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
| `ko` | 200 | quelque chose est cassé et rien ne le réparera seul (tranche corrompue, boucle arrêtée) : regarder la console, redémarrer |
| `starting`, `stopping` | 503 | pas prête |

Le détail de chaque contrôle est dans la console, **Système › Santé** ; les
journaux dans `journalctl -u mika`. Les coûts et le taux de cache des appels
de modèle sont dans **Système › Appels de modèle**.

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
projections et vecteurs se reconstruisent depuis le journal. Les dossiers
d'appel de Claude Code (prompts privés, jeton de session du relais) ne sont pas
dans le dossier de données : ils vivent sous `XDG_RUNTIME_DIR` (`/run/mika` avec
l'unité fournie), en `0700`, effacés en fin d'appel et purgés au démarrage —
jamais archivés. Copie les archives ailleurs que sur la machine.

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
cd /opt/mika && sudo git pull && cd backendv2 && sudo .venv/bin/pip install -e ".[llm,memory,documents]"
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
