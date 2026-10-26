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
sudo python3 -m venv .venv                       # Python ≥ 3.12 ; développé et testé en 3.14 — garder la même
                                                 # version que le poste de développement (torch et les pilotes suivent
                                                 # les nouvelles versions de Python avec retard)
sudo .venv/bin/pip install -e ".[llm,memory,documents]"   # documents : lire les PDF ; + mariadb, plus bas
sudo dnf install bubblewrap passt iproute git   # ou apt install bubblewrap passt iproute2 git
```

Ce qui exécute du code (la Forge, les ateliers de ses projets, les serveurs MCP
lancés ici) tourne sous bubblewrap ; leur réseau, quand il est permis (la
recherche web, une commande approuvée d'un atelier), passe par `pasta` (paquet
`passt`) et `ip` ; les ateliers sont des dépôts `git`. **Aucun n'a de repli** :
sans eux, ces fonctions échouent. Bubblewrap doit pouvoir créer des espaces de
noms utilisateur sans être setuid (le cas sur Fedora ; sur Debian/Ubuntu,
vérifier `kernel.unprivileged_userns_clone=1` et, sur Ubuntu 24.04+, le profil
AppArmor de `bwrap`).

`/etc/mika/mika.env` (facultatif, droits 0600) — une affectation `NOM=valeur`
par ligne, les commentaires sur leur propre ligne (systemd ne coupe pas un
commentaire en fin de ligne : il le garderait dans la valeur) :

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
mandataire TLS devant (Caddy, nginx) plutôt que de changer `--host` : un autre
hôte que la boucle locale, `0.0.0.0` ou `::` vide l'adresse du relais MCP, et
les appels de Claude Code échouent.

## Les commandes à la main

Les unités chargent `/etc/mika/mika.env` ; une commande lancée à la main
(`sudo -u mika … python -m mika`) ne le lit pas. Sur MariaDB, elle travaillerait
alors sur des fichiers SQLite neufs ; avec `MIKA_SECRET_KEY`, elle créerait un
nouveau `secret.key`. Lance-les donc sous l'utilisateur `mika`, **avec**
l'environnement du service :

```bash
mika() {
  sudo sh -c 'if [ -r /etc/mika/mika.env ]; then set -a; . /etc/mika/mika.env; set +a; fi
    export HF_HOME=/var/lib/mika/cache/huggingface
    cd /opt/mika/backendv2 && exec runuser -u mika -- .venv/bin/python -m mika --data /var/lib/mika "$@"' sh "$@"
}
mika --help
```

Les commandes qui écrivent les réglages (`account`, `token create`, `llm`,
`mail`…) se lancent serveur arrêté. La suite de ce document suppose cette
fonction.

**Claude Code comme fournisseur** : la CLI `claude` installée pour
l'utilisateur `mika`, puis `mika claude-code login` (le login de la CLI, jamais
un jeton) et `mika claude-code check` (un appel d'essai).

## Ses bases sur MariaDB (ADR 0101)

Sans réglage, ses bases sont des fichiers SQLite dans `/var/lib/mika`. Pour
les ranger dans un serveur MariaDB 11.8 — **sur la même machine, par son
socket** (ses lectures restent synchrones : un serveur distant ajouterait un
aller-retour à chacune) — et **dédié à Mika** (son compte crée les comptes
des apps de la Forge : sous MariaDB, ce droit vaut administration) :

```bash
sudo dnf install mariadb-server            # ou apt install mariadb-server
sudo .venv/bin/pip install -e ".[llm,memory,documents,mariadb]"   # mariadb : le pilote PyMySQL
```

`/etc/my.cnf.d/mika.cnf` (Debian : `/etc/mysql/mariadb.conf.d/90-mika.cnf`) :

```ini
[mariadb]
# l'oubli (ADR 0073) : la place libérée par une suppression est remise à zéro ;
# et ne jamais activer log_bin (le journal binaire garderait ce qui a été effacé)
innodb_immediate_scrub_data_uncompressed = ON
# chaque validation sur le disque (l'équivalent de synchronous=FULL)
innodb_flush_log_at_trx_commit = 1
# de la marge pour un gros instantané ou un long mail
max_allowed_packet = 64M
# une valeur trop longue est refusée, jamais coupée (le défaut, dit ici pour qu'il reste)
sql_mode = STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION
character-set-server = utf8mb4
collation-server = utf8mb4_nopad_bin
# elle passe par le socket : rien n'écoute sur le réseau (le pare-feu d'un poste Fedora
# Workstation ouvre 1025-65535 au réseau local)
bind-address = 127.0.0.1
```

Puis son compte, sans mot de passe (`unix_socket` : c'est l'utilisateur
système `mika` qui se connecte) — tous les droits sur ses bases (`mika_…`),
de quoi y donner les siens à chaque app forgée, et créer leurs comptes :

```bash
sudo systemctl enable --now mariadb
sudo mariadb <<'SQL'
CREATE USER 'mika'@'localhost' IDENTIFIED VIA unix_socket;
GRANT ALL PRIVILEGES ON `mika\_%`.* TO 'mika'@'localhost' WITH GRANT OPTION;
GRANT CREATE USER ON *.* TO 'mika'@'localhost';
SQL
```

Et dans `/etc/mika/mika.env` (le chemin du socket : `/var/lib/mysql/mysql.sock`
sur Fedora, `/run/mysqld/mysqld.sock` sur Debian) :

```ini
MIKA_DATABASE_URL=mariadb+pymysql://mika@localhost/?unix_socket=/var/lib/mysql/mysql.sock
# le début du nom de ses bases (mika_mind, mika_views…)
#MIKA_DATABASE_PREFIX=mika_
```

Au démarrage, ses bases sont créées (`mika_mind`, `mika_views`, `mika_mail`,
`mika_feeds`, `mika_teams`) et passées à leur dernière révision ; chaque app
forgée a la sienne (`mika_forge_<app>`), et un compte du même nom qui n'a de
droits que sur elle. Rien n'est repris des fichiers SQLite d'avant : elle
repart d'une base vide.

## Le modèle de plongements (ADR 0109)

C'est lui qui fait remonter un souvenir quand on lui parle. Par défaut, `paraphrase-multilingual-MiniLM-L12-v2`
sur le processeur : petit, mais faible en français. Un autre se choisit dans `/etc/mika/mika.env` :

```ini
MIKA_EMBEDDINGS_MODEL=google/embeddinggemma-2
# cpu (défaut), cuda (la carte graphique), auto ; une valeur inconnue revient au processeur
MIKA_EMBEDDINGS_DEVICE=cuda
```

Au banc (`tools/banc_plongements`, 40 messages), le modèle par défaut retrouve le bon souvenir en tête 25 fois sur
40. Deux modèles font bien mieux :

- `google/embeddinggemma-2` (34/40, le choix du portable) : la seule partie texte (270M), environ 590 Mo sur une
  carte graphique ou 1,5 Go de RAM sur le processeur. Il lui faut transformers ≥ 5.19, sentence-transformers ≥ 6.1,
  Pillow et torchvision. **torchvision s'installe depuis l'index de torch**, pour que les deux s'accordent :
  `.venv/bin/pip install --no-deps "torchvision==<version>+cu126" pillow --index-url
  https://download.pytorch.org/whl/cu126` (torch 2.14 va avec torchvision 0.29).
- `Qwen/Qwen3-Embedding-0.6B` (35/40, avec sa consigne de souvenirs) : environ 1,2 Go sur une carte (fp16), ou
  2,4 Go de RAM sur le processeur.

Sans carte et avec peu de RAM, `ibm-granite/granite-embedding-278m-multilingual` (31/40) ou
`intfloat/multilingual-e5-base` (30/40) prennent environ 1,1 Go.

Changer de modèle ne demande qu'un redémarrage : l'index range ses vecteurs par modèle, et la mémoire replonge ce
qui manque au premier passage (quelques minutes pour une longue vie). Le modèle se télécharge dans `HF_HOME`
(`/var/lib/mika/cache/huggingface` avec l'unité fournie). Ce dossier n'entre pas dans les sauvegardes.

**Sur une carte NVIDIA** (Fedora) : le pilote de RPM Fusion, un torch CUDA dans le venv, et la carte rendue au
service.

```bash
sudo dnf install https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm \
                 https://mirrors.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-$(rpm -E %fedora).noarch.rpm
sudo dnf install akmod-nvidia xorg-x11-drv-nvidia-cuda kernel-devel    # kernel-devel du noyau qui démarrera
sudo akmods --force && sudo reboot                                     # puis : nvidia-smi
cd /opt/mika/backendv2 && .venv/bin/pip install "torch==$(.venv/bin/python -c 'import torch; print(torch.__version__.split("+")[0])')+cu126" \
    --index-url https://download.pytorch.org/whl/cu126
```

`PrivateDevices=yes` cache la carte au service. `/etc/systemd/system/mika.service.d/gpu.conf` rend ses seuls
périphériques ; `/dev/nvidia-uvm` naît au premier usage de CUDA, ce que le service ne peut pas faire lui-même :

```ini
[Service]
ExecStartPre=-+/usr/bin/nvidia-modprobe -u -c=0
BindPaths=-/dev/nvidiactl -/dev/nvidia0 -/dev/nvidia-uvm -/dev/nvidia-uvm-tools
DeviceAllow=/dev/nvidiactl rw
DeviceAllow=/dev/nvidia0 rw
DeviceAllow=/dev/nvidia-uvm rw
DeviceAllow=/dev/nvidia-uvm-tools rw
```

Si Secure Boot est actif, le module du pilote doit être signé (une clé à enrôler à l'écran au redémarrage).

## Derrière un mandataire TLS

Trois options de `serve` :

- `--origin https://mika.example` (répétable) : l'origine du frontend servi en
  HTTPS. Elle **remplace** les origines de développement (`localhost:3000`…) :
  sans elle, le navigateur se voit refuser CORS, CSRF et la WebSocket.
- `--behind-proxy` : l'adresse du client est lue dans `X-Forwarded-For` (envoyé
  par un mandataire **local** seulement — 127.0.0.1, ::1) ; l'étranglement des
  connexions vise alors la vraie adresse. Implique `--cookie-secure`. Sans elle,
  derrière un mandataire, l'étranglement verrait tous les clients en 127.0.0.1
  et les cookies partiraient sans `Secure` : la première requête qui porte un
  en-tête de mandataire (`X-Forwarded-For`, `X-Real-IP`, `Forwarded`, `Via`) est
  signalée au journal (« mandataire non déclaré : lance avec --behind-proxy »).
- `--cookie-secure` : cookies de session et CSRF marqués `Secure`.

Pose-les par une surcharge, qu'une nouvelle copie de `mika.service` n'écrasera
pas : `sudo systemctl edit mika`, puis

```ini
[Service]
ExecStart=
ExecStart=/opt/mika/backendv2/.venv/bin/python -m mika --data /var/lib/mika serve --host 127.0.0.1 --port 8001 \
    --origin https://mika.example --behind-proxy
```

Le mandataire **doit** transmettre l'adresse du client (`X-Forwarded-For`) et ne
relayer de `/mcp/` que la console MCP (`/mcp/console/`). Le relais de Claude Code
et les outils prêtés (`/mcp/pret/<nom>`) ne servent que la machine elle-même et
refusent toute requête qui porte un en-tête de mandataire : fermer leur chemin
chez le mandataire est la seconde porte. La console MCP les refuse aussi, tant
qu'une opératrice ne l'ouvre pas au réseau (Outils › Prêter à un agent, ADR 0126) ;
ouverte, elle répond au travers du mandataire, jeton toujours exigé. Sans TLS, ce
jeton passe en clair : ne l'ouvre ainsi que sur un réseau local.

Ce qui le dimensionne, c'est la console, pas les pings des clients (toutes les
20 s) : un corps de requête d'au moins 5 Mo plus la marge du formulaire (un
dépôt de fichier, `kernel/forms.py::UPLOAD_MAX`), et un délai de lecture
au-dessus de son plus long appel synchrone, « Rejouer avec… » un autre
fournisseur, borné à 300 s
(`adapters/llm/gateway.py::DEFAULT_DEADLINES["background"]`). Une de ces bornes
qui change fait changer ces réglages.

Caddy transmet l'adresse de lui-même :

```
mika.example {
    @mcp {
        path /mcp /mcp/*
        not path /mcp/console /mcp/console/*
    }
    respond @mcp 404
    reverse_proxy 127.0.0.1:8001
}
```

nginx :

```nginx
location /mcp/console/ {                              # la console MCP, si on l'ouvre au réseau
    proxy_pass http://127.0.0.1:8001;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
location /mcp/ { return 404; }
location / {
    proxy_pass http://127.0.0.1:8001;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;          # la WebSocket (/ws)
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    client_max_body_size 6m;                          # un dépôt de fichier dans la console
    proxy_read_timeout 330s;                          # « Rejouer avec… », 300 s au plus
}
```

L'application Android (ADR 0062) est un client natif : elle n'a pas d'origine à
déclarer (`--origin` ne la concerne pas), et passe `Authorization: Bearer …` et
`X-Mika-Presence` à la mise à niveau de `/ws` ; Caddy et nginx les transmettent
tels quels (ne les retire pas). Les fichiers qu'elle télécharge (`/files/…`)
passent par le même mandataire. Fermée, elle ne garde rien d'ouvert : ses
messages lui arrivent par Firebase (ADR 0077, plus bas).

Les journaux ne portent aucun secret : un jeton passé en paramètre d'URL et un
`Bearer` sont masqués ; `httpx` ne parle qu'en avertissement.

## Premier démarrage

1. Ouvre la console (`http://localhost:8001/`) ou le frontend : le premier compte créé est opérateur (ou
   `mika account <nom> --operator`, serveur arrêté, le mot de passe demandé sans écho). Depuis une autre machine
   que le serveur (derrière Caddy, avec `--behind-proxy`), la page demande le **code de premier démarrage** :
   `journalctl -u mika | grep "code de premier démarrage"` — tiré à chaque démarrage tant qu'aucun compte
   n'existe, pour que le premier arrivé sur le réseau ne devienne pas opérateur.
2. **Réglages › Modèles de texte** (`/inspecteur/reglages/fournisseurs`) : ajoute un fournisseur (sa clé est
   chiffrée et jamais réaffichée ; « Charger la liste » propose ses modèles ; à l'enregistrement, la fenêtre du
   modèle est lue chez le fournisseur et borne le contexte, ADR 0136). Le premier déclaré sert « répondre »
   d'office, et les autres rôles y retombent — sauf la seconde passe (`polish`, l'autrice qui récrit ses messages),
   qui ne se fait que si un fournisseur lui est confié dans « Qui sert quoi ». Tant qu'aucun modèle ne sert
   « répondre », `/health` dit `degraded` et elle ne peut pas parler.
3. Le reste se règle dans **Réglages** (« Tous les réglages » les liste) : sa personnalité (identité, parole,
   caractère, tempérament avec ce que pilote chaque curseur, ses autrices), la configuration des plugins (courrier,
   flux, Teams, réveils…), la transcription, les comptes opérateurs, et les **paramètres avancés** : une page par
   faculté, qui dit d'où vient chaque valeur, où une surcharge se pose, bornée et journalisée. Chaque
   enregistrement laisse une ligne dans **Réglages › Historique des réglages**. On lui écrit par une application
   dédiée (le frontend web, le client Unity, l'application Android), avec un compte : il n'y a pas de robot de
   messagerie (ADR 0060). Un client natif s'authentifie par un jeton de son compte (`mika token create <compte>`).
4. Ses boîtes aux lettres : **Réglages › Plugins › Boîtes aux lettres** (`/inspecteur/reglages/boites`) — un
   enregistrement par boîte : serveurs IMAP/SMTP, dossiers relevés, et sa voix (en son nom, en assistante, ou à ta
   place ; ton, consignes, signature ; préparer des réponses d'elle-même). « Tester la connexion » sur la fiche de
   la boîte. En ligne de commande, serveur arrêté : `mika mail set --compte perso --address … --imap-host …
   --user … --password … --smtp-host … --voix proprietaire --nom "Ton Nom"` (`mika mail show`,
   `mika mail remove --compte perso`). Rien de ce qu'elle rédige ne part sans ton accord (À valider › Brouillons
   de courrier).

Les pièces jointes qu'on lui envoie prennent au plus 2 Gio par personne par défaut (Réglages › Paramètres avancés,
page des pièces reçues, « Place par personne »).

## Notifications du téléphone (Firebase)

L'application Android fermée ne garde aucune connexion (la batterie) : ce que Mika
écrit à la personne lui arrive par Firebase Cloud Messaging, **chiffré pour son seul
téléphone** (Google ne transporte qu'un chiffré, ADR 0077). Sans cette mise en place,
tout marche, mais l'application ne reçoit que ce qu'elle trouve en s'ouvrant.

1. Dans la [console Firebase](https://console.firebase.google.com/), crée un projet
   (Google Analytics inutile), puis ajoute-lui une application **Android** par paquet
   que tu installes : `fr.qwartz.mika` (version « release ») et `fr.qwartz.mika.debug`
   (version de débogage). Pas besoin d'empreinte SHA.
2. Télécharge `google-services.json` (il décrit les deux applications) et pose-le dans
   `frontend/Android/app/` — il n'est jamais versionné. Reconstruis et réinstalle
   l'application : sans lui, la construction le dit (« Firebase : pas d'identifiants… »).
3. Paramètres du projet › **Comptes de service** › « Générer une nouvelle clé
   privée » : un fichier JSON. Deux façons de le donner au serveur :
   - le poser dans le dossier de données, à côté de `secret.key`, sous le nom
     `firebase-service-account.json` :
     `sudo install -o mika -g mika -m 600 <fichier>.json /var/lib/mika/firebase-service-account.json`.
     Il est relu à chaque envoi (pas de redémarrage) et la sauvegarde l'emporte ;
   - ou le coller tel quel dans la console de Mika, **Réglages › Tous les réglages › Canaux › Notifications du
     téléphone** : chiffré (`secret.key` ou `MIKA_SECRET_KEY`), jamais réaffiché. Collé, il passe devant le fichier.

   La page dit d'où vient la clé, le projet, combien de téléphones sont notifiables, ce
   qui est parti et le dernier échec. Ne laisse jamais ce fichier dans le dépôt.
4. Ouvre l'application une fois **chez toi** (le serveur doit être joignable) : elle
   dit au serveur où la notifier. Paramètres › Notifications › « Application fermée »
   dit où elle en est.

Le serveur doit pouvoir joindre `oauth2.googleapis.com` et `fcm.googleapis.com` en
HTTPS sortant. Hors de chez toi, la notification arrive (elle passe par Google), mais
répondre demande que le serveur soit joignable : une réponse écrite hors de portée
attend dans la file d'envoi et part à la prochaine ouverture chez toi.

## Surveiller

`GET /health` est public et ne dit que des noms et des états :

```json
{"status": "ok", "ready": true, "checks": {"journal": "ok", "slices": "ok", "loops": "ok",
 "projections": "ok", "processes": "ok", "outbox": "ok", "llm": "ok", "lanes": "ok", "config": "ok",
 "ports": "ok"}}
```

| `status` | code | sens |
|---|---|---|
| `ok` | 200 | tout va bien |
| `degraded` | 200 | elle répond moins bien, ou plus du tout : aucun modèle ne sert « répondre », son fournisseur échoue, ses appels de fond sont retenus par le quota de l'abonnement (ADR 0127), une projection est en retard, un processus échoue, la file de sortie est bloquée… |
| `ko` | 200 | quelque chose est cassé et rien ne le réparera seul (tranche corrompue, boucle arrêtée) : regarder la console, redémarrer |
| `starting`, `stopping`, `stopped` | 503 | pas prête |

Le détail de chaque contrôle est dans la console, **Système › Santé générale** ;
les journaux dans `journalctl -u mika`. Les coûts et le taux de cache des appels
de modèle sont dans **Système › Appels et coûts**.

## Sauvegarder

Le minuteur fait une archive chaque nuit à 3 h 30 et garde les 14 dernières.
À la main (sans risque serveur en marche) :

```bash
sudo systemctl start mika-backup.service           # la même sauvegarde, avec l'environnement du service
mika verify /var/backups/mika/mika-AAAAMMJJ-HHMMSS.tar.gz   # noté pour la console (« dernière vérification »)
```

Une archive contient `mind.db` (sa vie : le journal, les contenus, les
comptes, les réglages), les caches du courrier, des flux et de Teams, ses apps
forgées, ses ateliers, les fichiers qu'elle a envoyés (`partages/`) et les
pièces jointes qu'on lui a envoyées (`pieces/`), `secret.key` quand la clé vient
de ce fichier et `firebase-service-account.json` s'il est posé, avec un
manifeste (sommes SHA-256, tête du journal, empreinte de l'état rejoué depuis la
copie). `views.db` n'y est pas : projections et vecteurs se reconstruisent
depuis le journal. Sur MariaDB, le dossier y est, et à côté une copie SQL de
chaque base (`bases/` : `mind`, `mail`, `feeds`, `teams`, et celle de chaque app
forgée) faite par `mariadb-dump` en un instantané cohérent ; la vérification
recharge `mind` dans une base de travail et l'y rejoue. Les dossiers d'appel de
Claude Code (prompts privés, jeton de session du relais) ne sont pas dans le
dossier de données : ils vivent sous `XDG_RUNTIME_DIR` (`/run/mika` avec l'unité
fournie), en `0700`, effacés en fin d'appel et purgés au démarrage — jamais
archivés.

**Hors de la machine, et chiffrées.** Un disque qui meurt emporte Mika et ses
quatorze archives ; une archive qui fuit contient `secret.key` à côté des secrets
qu'elle déchiffre (clés d'API, mot de passe IMAP, jeton git). Donc :

- copier chaque archive ailleurs (un second disque, un stockage distant) en la
  chiffrant — par exemple `restic` (chiffre, déduplique, vérifie) ou `age` :
  `age -r <clé publique> -o mika-….tar.gz.age mika-….tar.gz` ; un minuteur
  systemd après `mika-backup.service` suffit ;
- en service, préférer `MIKA_SECRET_KEY` dans `/etc/mika/mika.env` (droits 0600)
  à un `secret.key` dans le dossier : la clé n'est alors dans aucune archive, et
  on la garde à part (un gestionnaire de mots de passe) ; sans elle, les secrets
  d'une archive restaurée sont perdus, le reste de sa vie non.

## Restaurer

```bash
sudo systemctl stop mika
mika restore /var/backups/mika/mika-AAAAMMJJ-HHMMSS.tar.gz --force
mika replay --verify
sudo systemctl start mika
curl -s localhost:8001/health
```

La restauration vérifie les sommes et rejoue la copie **avant** de toucher au
dossier. Elle travaille dans le dossier même (l'utilisateur `mika` n'écrit pas
dans `/var/lib`) : l'ancien contenu est mis de côté dans
`/var/lib/mika/.avant-restauration-…`, jamais effacé, et n'entre dans aucune
archive suivante — supprime-le à la main quand tu n'en as plus besoin. Le modèle
de plongements (`cache/`) reste en place. Sur MariaDB, ses bases en service sont
d'abord copiées dans `bases/` de ce dossier mis de côté, puis chaque copie de l'archive est rechargée
à sa place ; `mika_views` est vidée. Une archive faite sur fichiers ne se
restaure pas sur un serveur, ni l'inverse. Au démarrage, les vues se
reconstruisent (le rappel est moins bon quelques minutes, le temps de réindexer
les souvenirs).

## Mettre à jour

```bash
sudo systemctl start mika-backup.service
cd /opt/mika && sudo git pull && cd backendv2 && sudo .venv/bin/pip install -e ".[llm,memory,documents]"   # les extras de l'installation (+ mariadb)
sudo systemctl restart mika
```

Une faculté dont la tranche change de version est reconstruite depuis le
journal au démarrage ; une projection qui change de version est reconstruite
à côté puis basculée. Rien à migrer à la main.

Pour relire la console sans serveur après une mise à jour :
`.venv/bin/python -m mika console apercu --out /tmp/console` exporte chaque
page, en clair et en sombre, d'une Mika neuve (modèle factice, rien ne sort de
la machine) ; ouvrir `/tmp/console/index.html`.

## Oublier quelqu'un

```bash
sudo systemctl stop mika
mika forget user_12
sudo systemctl start mika
```

Ses contenus sont effacés de `mind.db`, des vues et des journaux WAL ; les
**archives** plus anciennes les contiennent encore, jusqu'à leur rotation, comme
les dossiers `.avant-restauration-…` qu'une restauration a laissés. Sur
MariaDB, ils disparaissent des tables tout de suite (la place est remise à zéro :
`innodb_immediate_scrub_data_uncompressed`), et des journaux de reprise et
d'annulation d'InnoDB à leur rotation, sous peu.
