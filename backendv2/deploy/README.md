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

**Le jeton des dépôts git** (console, Connexions › Dépôts Git) sert à pousser, à
récupérer un dépôt privé et — pour un projet qui passe par des pull requests
(ADR 0274) — à ouvrir et relire une pull request sur GitHub. Il ne part que
vers les hôtes qu'il déclare. Les droits qu'il lui faut, sur les seuls dépôts
des projets : avec un jeton GitHub à portée fine, « Contents » et « Pull
requests » en « Read and write » (« Metadata » en lecture vient avec) ; avec un
jeton classique, `repo`. Rien de plus : elle ne fusionne jamais, et la
protection de la branche principale chez GitHub reste la tienne.

**Fusionner une pull request depuis Mika** (ADR 0288) est le geste d'une
personne — le propriétaire du projet, ou qui s'occupe d'elle —, depuis l'écran
Projets ou la console : jamais elle, ni aucun de ses outils. Ce geste part sous
ce même jeton et ne lui demande aucun droit de plus : « Contents » et « Pull
requests » en « Read and write » (un jeton classique : `repo`). La fusion est
une fusion ordinaire (un commit de fusion), et GitHub ne la fait que si le
commit au bout de la branche est encore celui que la personne a lu. Si la
branche principale est protégée, c'est le compte du jeton qui doit avoir le
droit d'y fusionner (une règle qui exige une relecture ou des vérifications
réussies s'applique à lui comme à tout autre) ; un dépôt qui interdit les
commits de fusion refuse — la pull request se fusionne alors chez GitHub. Pour
qu'elle ne puisse jamais fusionner depuis Mika, retire ce droit au jeton chez
GitHub : la demande est refusée, et le dit.

Pour un projet dont les tickets se reflètent en issues et dont les pull
requests attendent leur CI (ADR 0275), le même jeton demande en plus, à portée
fine : « Issues » en « Read and write » (lire les issues et leurs commentaires,
en ouvrir une, la fermer, la rouvrir, y publier une note), et, en lecture
seule, « Checks » et « Commit statuses » (l'état des vérifications d'un
commit ; l'un des deux suffit si la CI n'écrit que l'un) et « Actions » (la fin
du journal d'un échec). Un jeton classique `repo` les couvre. Le journal d'un
échec se télécharge à une adresse signée, hors de l'API de GitHub : elle est
lue sans le jeton. Sans ces droits, rien ne casse : les issues ne se lisent
pas, et des vérifications illisibles ne bloquent aucune pull request.

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
    client_max_body_size 52m;                         # un dépôt de fichier, un mail et ses pièces (50 Mo, ADR 0214)
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

## Servir frontendv2, le client de tous les jours

`frontendv2` (ADR 0187, son `README.md`) se construit en fichiers statiques, que le
mandataire sert à côté du serveur, sur la même adresse. Construit avec
`VITE_BACKEND_ORIGIN` vide, il parle à l'adresse de sa page. Il faut Node.js et
npm (`sudo dnf install nodejs npm`, ou `apt`) ; le dépôt est à root, comme à
l'installation :

```bash
cd /opt/mika/frontendv2
sudo npm ci
sudo env VITE_BACKEND_ORIGIN= npm run build         # → frontendv2/dist/ ; à refaire à chaque mise à jour (plus bas)
```

`sudo env` pose la variable vide après `sudo`, qui vide l'environnement : posée
devant `sudo`, elle se perdrait, et le client parlerait à `localhost:8001`.

`vite build` n'embarque ni ses polices, ni ses portraits, ni sa VRM : le mandataire
sert ces trois chemins à côté de `dist/`, depuis le dépôt (`frontendv2/README.md`,
« Ce qui est lu ailleurs ») — `/ext/fonts/`, `/ext/avatar/` et `/ext/models/`. Les
portraits et la VRM sont sous licence, hors du dépôt : copie-les dans
`frontend/Android/app/src/main/assets/avatar/` et `frontend/Web/public/models/`
(sans eux, ses ronds restent à leur couleur et son portrait remplace sa VRM). Le
reste va au serveur. Avec Caddy, un site à lui (ici un second port de la même
machine ; un autre nom marche aussi) :

```
mika.example:8443 {
    handle_path /ext/fonts/* {
        root * /opt/mika/backendv2/src/mika/inspector/static/fonts
        file_server
    }
    handle_path /ext/avatar/* {
        root * /opt/mika/frontend/Android/app/src/main/assets/avatar
        file_server
    }
    handle_path /ext/models/* {
        root * /opt/mika/frontend/Web/public/models
        file_server
    }
    @server path /api/* /auth/* /ws /ws/* /files/* /admin /admin/* /inspecteur /inspecteur/* /health
    handle @server {
        reverse_proxy 127.0.0.1:8001
    }
    handle {
        root * /opt/mika/frontendv2/dist
        file_server
    }
}
```

Seuls les chemins de `@server` vont au serveur : `/mcp/` n'y passe pas, et
`/admin/` y est relayé pour une opératrice, que le client mène à la console
(« Pourquoi a-t-elle dit ça ? »). Son adresse s'ajoute aux origines admises :
`--origin https://mika.example:8443`, à côté des autres (l'option se répète). Le
client 3D (`frontend/Web/`, son `README.md`) se construit et se sert de même, sur
son propre site.

## Premier démarrage

1. Ouvre la console (`http://localhost:8001/`) ou le frontend : le premier compte créé est opérateur (ou
   `mika account <nom> --operator`, serveur arrêté, le mot de passe demandé sans écho). Depuis une autre machine
   que le serveur (derrière Caddy, avec `--behind-proxy`), la page demande le **code de premier démarrage** :
   `journalctl -u mika | grep "code de premier démarrage"` — tiré à chaque démarrage tant qu'aucun compte
   n'existe, pour que le premier arrivé sur le réseau ne devienne pas opérateur.
2. **Réglages › Modèles de texte** (`/admin/reglages/fournisseurs`) : ajoute un fournisseur (sa clé est
   chiffrée et jamais réaffichée ; « Charger la liste » propose ses modèles ; à l'enregistrement, la fenêtre du
   modèle est lue chez le fournisseur et borne le contexte, ADR 0136). Le premier déclaré sert « répondre »
   d'office, et les autres rôles y retombent — sauf la seconde passe (`polish`, l'autrice qui récrit ses messages),
   qui ne se fait que si un fournisseur lui est confié dans « Qui sert quoi ». La même table règle l'effort de
   réflexion de chaque rôle (vide : celui de la fiche ; `mika llm effort low polish triage caption` fait de même).
   Tant qu'aucun modèle ne sert « répondre », `/health` dit `degraded` et elle ne peut pas parler.
3. Le reste se règle dans **Réglages** (« Tous les réglages » les liste) : sa personnalité (identité, parole,
   caractère, tempérament avec ce que pilote chaque curseur, ses autrices), la configuration des plugins (courrier,
   flux, Teams, réveils…), la transcription, les comptes opérateurs, et les **paramètres avancés** : une page par
   faculté, qui dit d'où vient chaque valeur, où une surcharge se pose, bornée et journalisée. Chaque
   enregistrement laisse une ligne dans **Réglages › Historique des réglages**. On lui écrit par une application
   dédiée (`frontendv2`, le client de tous les jours ; le client 3D de `frontend/Web` ; le client Unity ;
   l'application Android), avec un compte : il n'y a pas de robot de messagerie (ADR 0060). Un client natif
   s'authentifie par un jeton de son compte (`mika token create <compte>`).
4. Ses boîtes aux lettres : **Courrier › Paramètres**, le bouton en haut à droite du courrier
   (`/admin/courrier/parametres`) — un
   enregistrement par boîte : serveurs IMAP/SMTP, dossiers relevés, et sa voix (en son nom, en assistante, ou à ta
   place ; ton, consignes, signature ; préparer des réponses d'elle-même). « Tester la connexion » sur la fiche de
   la boîte. Une fois la boîte enregistrée, « Charger la liste », sous « Dossiers relevés », lit ses dossiers sur
   le serveur : coche ceux où elle remarque ce qui arrive. « Synchroniser tous les dossiers » tient les autres à
   jour dans la console à chaque relève, sans qu'elle les remarque (ADR 0171). En ligne de commande, serveur arrêté : `mika mail set --compte perso --address … --imap-host …
   --user … --password … --smtp-host … --voix proprietaire --nom "Ton Nom"` (`mika mail show`,
   `mika mail remove --compte perso`). Rien de ce qu'elle rédige ne part sans ton accord (À valider › Courriers à
   envoyer).
   Une boîte **Hotmail ou Outlook.com** refuse les mots de passe : elle entre par ton compte Microsoft (ADR 0166).
   Mika livre l'application Microsoft par laquelle elle entre (ADR 0238) : rien à inscrire. Pour la remplacer par
   celle de ton instance (inscrite dans Microsoft Entra : comptes Microsoft personnels acceptés, aucune URI de
   redirection, « Autoriser les flux de clients publics »), donne son identifiant (client ID) dans la console,
   Courrier › Paramètres › Compte Microsoft, ou par `mika mail application <client ID>` (`mika mail application`
   la montre, `--defaut` revient à celle livrée). Ajouter une boîte ne demande que son adresse et son nom (frontendv2,
   l'application Android) ; dans la console : Connexion « par un compte Microsoft », serveur IMAP
   `outlook.office365.com` (993, SSL), SMTP `smtp-mail.outlook.com` (587, STARTTLS), utilisateur = l'adresse,
   l'application laissée vide. Enfin, sur la fiche de la boîte, « Se connecter à Microsoft » : un code à
   entrer sur la page de Microsoft qu'elle indique. En ligne de commande : `mika mail set --compte hotmail --auth
   microsoft --imap-host outlook.office365.com --smtp-host smtp-mail.outlook.com …`, puis la connexion depuis la
   console. Une boîte peut encore déclarer sa propre application (`--client-id`), qui passe devant.

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
   - ou le coller tel quel dans la console de Mika, **Réglages › Tous les réglages › Carte et téléphone ›
     Notifications du téléphone** : chiffré (`secret.key` ou `MIKA_SECRET_KEY`), jamais réaffiché. Collé, il passe
     devant le fichier.

   La page dit d'où vient la clé, le projet, combien de téléphones sont notifiables, ce
   qui est parti et le dernier échec. Ne laisse jamais ce fichier dans le dépôt.
4. Ouvre l'application une fois **chez toi** (le serveur doit être joignable) : elle
   dit au serveur où la notifier. Paramètres › Notifications › « Application fermée »
   dit où elle en est.

Le serveur doit pouvoir joindre `oauth2.googleapis.com` et `fcm.googleapis.com` en
HTTPS sortant. Hors de chez toi, la notification arrive (elle passe par Google), mais
répondre demande que le serveur soit joignable : une réponse écrite hors de portée
attend dans la file d'envoi et part à la prochaine ouverture chez toi.

## L'application du téléphone (ADR 0190)

`frontendv2` propose l'application Android au téléchargement (Paramètres › Téléphones), à qui est connecté (sa
session, ou un jeton de son compte, celui de son téléphone par exemple), jamais par un lien public : elle est servie depuis le dossier de données.
Construite (`frontend/Android/`, son `README.md`), on la dépose sous ce nom :

```bash
sudo install -d -o mika -g mika -m 700 /var/lib/mika/telephone
sudo install -o mika -g mika -m 640 app-release.apk /var/lib/mika/telephone/mika.apk
```

Sans ce fichier, la page dit qu'elle n'est pas encore déposée (`GET /api/moi/phone/apk` : 404).

L'extension de Teams, elle, ne se dépose pas (ADR 0246) : le serveur la zippe à la demande depuis
`/opt/mika/frontend/Extension`, le dossier du dépôt à côté de lui, que l'utilisateur `mika` doit pouvoir lire. Elle
suit donc chaque mise à jour du code ; Paramètres › Teams › L'extension la propose (`GET /api/moi/teams/extension`).

## La carte de sa position (ADR 0193)

Téléphone › Position montre une vraie carte, dont les tuiles passent toujours par ce serveur : le navigateur ne joint
aucune adresse du dehors. Sans réglage, la position garde son plan dessiné. Pour une carte servie depuis la machine
(rien ne sort de la maison), on extrait une zone de la carte Protomaps de la planète (OpenStreetMap, refaite chaque
jour) — seule la zone se télécharge, puis ses polices et icônes :

```bash
df -h /var/lib/mika                                # la France jusqu'au zoom 15 : quelques Go
mika carte extraire --zone france --zoom 15        # → cartes/france.pmtiles
mika carte polices                                  # → cartes/assets (fonts/, sprites/v4/)
```

Serveur en marche, sans risque : l'archive neuve ne remplace l'ancienne qu'entière, et le serveur la rouvre de
lui-même. Une autre zone : `--zone ouest,sud,est,nord` (en degrés) et `--sortie cartes/<nom>.pmtiles` ; chaque zoom de
moins divise la taille par quatre environ. Puis, dans la console, Réglages › Carte et téléphone › Carte de sa
position : « Un fichier PMTiles sur ce serveur », `cartes/france.pmtiles` ; la page dit sa taille, ses zooms et sa
zone. Pour la mettre à jour, relancer `mika carte extraire` de temps en temps. `cartes/` n'entre dans aucune sauvegarde,
sauf ses compteurs (`cartes/quotas.db`, ci-dessous).

Un serveur de carte à part (un `pmtiles serve`, une archive sur un stockage, un serveur `{z}/{x}/{y}` au schéma
Protomaps ou d'images) se règle au même endroit : ce serveur le joint seul, sans rien de la personne, et en relaie
les tuiles. Il doit servir l'archive par plages (`Range`) ; s'il ne répond pas, ou si l'archive change à la même
adresse, la carte le voit en une minute au plus (elle se rouvre, ou garde son plan dessiné).

### Les lieux, les adresses et les itinéraires de l'écran Carte (ADR 0194, 0244)

Les lieux (restaurants, campings, sommets, musées, villes et lieux-dits) se cherchent dans un index de la machine —
rien ne sort. Il se tire de l'extrait OpenStreetMap de Geofabrik, qui garde ce qu'en dit une fiche (cuisine, horaires,
téléphone, site, terrasse, végétarien, vegan, accessibilité, à emporter, étoiles…) : les filtres de l'écran et la
fiche d'un lieu en viennent. Le télécharger et construire l'index **sur le PC** (pyosmium, l'extra `cartes`), puis
copier l'index seul sur le portable :

```bash
# sur le PC, dans backendv2 : un dossier de données à part, pour la carte seulement
.venv/bin/pip install -e ".[cartes]"                         # pyosmium
mkdir -p data/carte/cartes
curl -L -o data/carte/cartes/france-latest.osm.pbf \
  https://download.geofabrik.de/europe/france-latest.osm.pbf  # la métropole, ~4,8 Go, refait chaque nuit
../scripts/borne.sh .venv/bin/python -m mika --data data/carte carte lieux --depuis cartes/france-latest.osm.pbf
# puis sur le portable : à côté de l'ancien, qu'il remplace d'un seul coup
rsync -a data/carte/cartes/lieux.db mika-portable:lieux.db.neuf
ssh -t mika-portable 'sudo install -o mika -g mika -m 0644 lieux.db.neuf /var/lib/mika/cartes/lieux.db.neuf \
  && sudo mv /var/lib/mika/cartes/lieux.db.neuf /var/lib/mika/cartes/lieux.db && rm lieux.db.neuf'
```

Serveur en marche, sans risque : l'index neuf ne remplace l'ancien qu'entier, et le serveur le lit à la recherche
suivante (celles en cours finissent sur l'ancien). Le refaire de temps en temps, sur un extrait du jour. Sans
`--depuis`, la commande prend `cartes/france-latest.osm.pbf` s'il est là, sinon `cartes/france.pmtiles` ; une autre
région de Geofabrik se construit de même (`--depuis cartes/<nom>.osm.pbf`, `--sortie cartes/<nom>.db`). La mémoire ne
dépend presque pas de la taille de l'extrait : seule la position des nœuds utiles se garde, par tranches
d'identifiants. Mesuré le 2026-11-17 sur le PC, sur l'extrait Nord-Pas-de-Calais (241 Mo, 24,5 millions de nœuds) :
35 725 lieux en 13 s, 1,05 Go de mémoire au plus (dont 280 Mo pour charger la commande), un index de 12 Mo, 98,8 % des
horaires compris. La France (vingt fois plus de données) n'est pas encore mesurée : compter quelques minutes, la même
mémoire, un index de quelques centaines de Mo. La fin de la sortie dit combien de lieux par catégorie, combien sans
nom, sans position (hors de l'extrait) ou comptés deux fois.

Sans extrait, l'index se tire encore des tuiles de l'archive (`mika carte lieux --depuis cartes/france.pmtiles`, à
refaire après chaque `mika carte extraire`) : sans détails — ni horaires, ni filtres, ni fiche. Mesuré sur la France
(2026-11-05, 1,84 million de tuiles au zoom 15) : 2 978 370 lieux en 2 min 10 s, 467 Mo de mémoire au plus, un index
de 522 Mo. Un tel index reste lisible jusqu'à ce qu'on le refasse depuis l'extrait.

Puis, dans la console, Réglages › Carte et téléphone :

- **Lieux et adresses** : l'index (`cartes/lieux.db` par défaut) et les adresses — « La Géoplateforme de l'IGN »
  (la Base Adresse Nationale) : ce serveur ne lui envoie que le texte cherché, jamais la position de la personne.
- **Itinéraires** : « Le Valhalla public de FOSSGIS » (celui d'openstreetmap.org : ses conditions demandent au plus
  une demande par seconde, pour tout ce serveur, et il ne garantit pas de répondre ; chaque trajet est gardé un
  jour), ou « Un Valhalla à toi » (ci-dessous). Vers lui ne partent que les points du trajet.

Par défaut, ni adresses ni itinéraires : rien ne sort sans ce choix. Sans index ou sans itinéraires, l'écran Carte
le dit.

### Les données touristiques et les événements (DATAtourisme, ADR 0245)

Les fiches des offices de tourisme (musées, sites, restaurants, hébergements) et leurs événements à venir (concerts,
spectacles, expositions, marchés…) viennent de l'API de DATAtourisme, gardées dans `cartes/tourisme.db` : un cache
**par cases** (une dizaine de kilomètres), où l'écran Carte cherche sans que rien ne sorte. Seule une case part vers
DATAtourisme, jamais la position d'une personne. Il faut une clé personnelle de leur API (www.datatourisme.fr,
« Utiliser les données »). Elle se colle dans la console, **Réglages › Carte et téléphone › Données touristiques
(DATAtourisme)** : chiffrée, jamais réaffichée, jamais écrite au journal. À défaut, le serveur prend la variable
`MIKA_DATATOURISME_API_KEY` de son environnement (`/etc/mika/mika.env`) ; la page dit laquelle sert, jamais sa
valeur. On y règle aussi les bornes des demandes (900 par heure et 8 par seconde par défaut ; leur API en permet 1 000
et une dizaine), la réserve gardée à ce qu'une personne ouvre (20 %), la taille d'une case, combien de temps on garde
ses lieux (7 jours) et ses événements (1 jour), et jusqu'où voir les événements.

Avec une clé, rien d'autre à faire :

- **Chaque soir** (22:00 par défaut, **Réglages › Carte et téléphone › Réchauffage des caches**), le serveur relit les
  cases autour de la dernière position que le téléphone de chacun a donnée (s'il l'a permis) et des points fixes qu'on y
  ajoute (« Lille », « 45.90, 6.13 ») : les événements d'abord, puis les lieux, les cases les plus vieilles d'abord, sur
  ce qui reste du quota — la réserve gardée. « Réchauffer maintenant » lance un passage. La page dit le dernier, les
  cases rafraîchies, le budget consommé et restant, le prochain.
- **En direct** : une case jamais vue qu'une personne ouvre (les événements autour d'elle, la fiche d'un lieu) se lit
  tout de suite, quelques pages, si le quota le permet ; sinon l'écran montre ce qu'on a, et dit pourquoi.

Les compteurs des demandes sont dans `cartes/quotas.db` : un redémarrage ne les oublie pas.

**En option**, des départements copiés en entier (le réglage « Départements tenus en entier » ; « France » : tous),
une fois par semaine et ce qui y change chaque nuit. Toute la France, c'est environ 6 000 demandes, **plus de six
heures** au rythme permis : la première se fait mieux **sur le PC**, puis la base se copie (une synchronisation à la
fois : un verrou, `cartes/tourisme.lock`) :

```bash
# sur le PC, dans backendv2 : le dossier de la carte (il n'a pas besoin d'être celui d'un Mika)
read -rs MIKA_DATATOURISME_API_KEY && export MIKA_DATATOURISME_API_KEY   # tapée, jamais sur la ligne de commande
BORNE_TEMPS=9h ../scripts/borne.sh .venv/bin/python -m mika --data data/carte carte tourisme --zones 59,62 \
  > tourisme.log 2>&1
tail -1 tourisme.log      # {"ok": true, "lieux": …, "événements": …, "demandes": …}
# interrompue (Ctrl-C, une erreur, la borne) : la même commande reprend là où elle s'est arrêtée
# puis sur le portable, serveur arrêté le temps de la copie
rsync -a data/carte/cartes/tourisme.db mika-portable:tourisme.db.neuf
ssh -t mika-portable 'sudo systemctl stop mika \
  && sudo install -o mika -g mika -m 0644 tourisme.db.neuf /var/lib/mika/cartes/tourisme.db \
  && sudo rm -f /var/lib/mika/cartes/tourisme.db-journal && rm tourisme.db.neuf && sudo systemctl start mika'
```

Puis, dans la console, les mêmes départements dans « Départements tenus en entier » : le serveur prend la suite
(chaque nuit, et une complète par semaine). Si `data/carte/cartes/lieux.db` est là, la commande rapproche aussi chaque
fiche de son lieu d'OpenStreetMap ; sinon, le portable le fait de lui-même, avec son index. `--complete` pour tout
refaire, `--horizon 60` pour les événements des 60 prochains jours. `cartes/tourisme.db` n'entre dans aucune
sauvegarde : la base se relit.

### Les avis (Google Places, ADR 0256)

Les notes, le nombre d'avis, le prix, les horaires, les avis en français, le résumé et les photos des restaurants, de
ce qui est à voir et des hébergements viennent de l'**API officielle Places (New)** de Google — rien d'autre n'est lu
de Google —, gardés dans `cartes/avis.db` : un cache **par cases** (3 km par défaut), où l'écran Carte lit sans que
rien ne sorte. Vers Google ne part que le cercle qui couvre une case (son centre et son rayon), jamais la position
d'une personne. Ses conditions ne permettent de garder que l'identifiant d'un lieu (et ses coordonnées trente jours) :
l'opérateur a choisi de garder ce cache sept jours et de le faire lire par Mika, sous sa responsabilité (ADR 0256) ; la
mention « Google Maps », le lien vers la page du lieu, le nom et le lien de l'auteur de chaque avis et de chaque photo
restent toujours avec.

**La clé.** Dans [Google Cloud](https://console.cloud.google.com/) : un projet, **un compte de facturation** lié (Google
le demande, même pour ne rien payer), l'API **Places API (New)** activée, puis une clé (« API et services ›
Identifiants »). **Restreins-la** : « Restrictions relatives aux API » → *Places API (New)* seule ; et, si l'adresse
du portable est fixe, « Restrictions relatives aux applications » → *Adresses IP* (son IPv6). Elle se pose :

- **sur le portable** : dans la console, **Réglages › Carte et téléphone › Avis (Google)** (chiffrée, jamais
  réaffichée, jamais écrite au journal), ou dans `/etc/mika/mika.env` (`MIKA_GOOGLE_PLACES_API_KEY=…`, droits 0600,
  puis `sudo systemctl restart mika`) — la console passe en premier, et sa page dit laquelle sert, jamais sa valeur ;
- **en local** : dans `backendv2/.env` (`MIKA_GOOGLE_PLACES_API_KEY=…`, droits 0600, ignoré par git) : la commande
  `mika` lit le `.env` du dossier où on la lance, sans jamais écraser une variable déjà posée (`MIKA_ENV_FILE` en
  nomme un autre ; vide, aucun). Ne le copie pas dans `/opt/mika/backendv2` : il y serait lu aussi. **Une clé à
  part**, d'un autre projet Google (ou, à défaut, des plafonds bas dans la console de chaque dossier local, 50 par
  SKU) : les plafonds ci-dessous comptent par dossier de données (`cartes/quotas.db`), et Google par compte de
  facturation — la même clé dans `backendv2/.env` et sur le portable, c'est un seul quota offert chez Google, que
  chaque dossier local (`data/v2`, la démo, une sonde) croit avoir à lui seul.

**Ce que ça coûte.** Google facture **chaque appel**, au niveau des champs qu'il demande (prix et quotas vérifiés le
2026-11-20) :

| Appel | SKU | Offerts chaque mois | Puis |
|---|---|---|---|
| une recherche pour une liste (vingt lieux au plus) | Nearby Search Enterprise | 1 000 | 35 $ les 1 000 |
| la fiche d'un lieu, avec ses avis | Place Details Enterprise + Atmosphere | 1 000 | 25 $ les 1 000 |
| une photo, la première fois qu'on la montre | Place Details Photos | 1 000 | 7 $ les 1 000 |

Une case coûte, par sorte, une recherche (un cercle qui la couvre), ou cinq quand elle est dense (ce cercle rend vingt
lieux : ses quatre quarts sont redemandés) ; un réchauffage autour d'une personne (neuf cases, trois sortes), de 27 à
135 recherches, une fois par semaine. La fiche d'un lieu jamais vu coûte une recherche (le chercher tout près de lui)
et une fiche ; relue, une fiche. Le mois de Google commence le 1er à minuit, **heure du Pacifique** (9 h à Paris).
D'où, réglés sur la même page et relus à chaque appel :

- **un plafond par mois et par SKU**, par défaut **le quota offert** (1 000 recherches, 1 000 fiches, 1 000 photos) :
  sans rien toucher, rien n'est facturé **tant que cette clé ne sert qu'à ce serveur** (ces comptes sont ceux de son
  dossier de données) ; chaque appel compte dès qu'il part, même en erreur ;
- 5 appels par seconde, 500 sur 24 heures glissantes (tous niveaux : un garde-fou) ;
- la réserve gardée au direct (20 %) : le réchauffage et le préchargement ne prennent que le reste ;
- la durée du cache (7 jours) : d'ici là, rien ne repart ; la taille d'une case et son découpage.

Avec une clé, rien d'autre à faire : **chaque soir** (Réchauffage des caches), les restaurants autour de la dernière
position de chacun et des points fixes, puis ce qui est à voir, puis les hébergements, les cases les plus vieilles
d'abord, puis la fiche des lieux ouverts depuis un mois ; **en direct**, la fiche d'un lieu lit ce qui lui manque, et
« Actualiser » la relit (vingt qui partent par 24 heures pour tout le serveur ; un refus qui ne fait rien partir, le
mois de Google atteint, ne compte pas). Les compteurs sont dans `cartes/quotas.db` (un redémarrage ne les oublie pas) :
seul fichier de `cartes/` que prend la sauvegarde ; restaurés là où il n'y en a pas (une machine neuve), ceux du
dossier restent sur une restauration sur place. La page dit les appels du mois de chaque SKU, ce qui serait facturé
au-delà des quotas offerts, ce que tient le cache, la dernière erreur.

### Un Valhalla à toi, sur le portable

Le serveur de FOSSGIS suffit pour un usage personnel ; un Valhalla à soi n'a ni sa limite ni ses pannes. Ses tuiles
se construisent **sur le PC** (pour la France, plusieurs Go de mémoire et une heure ou plus), puis se copient : le
portable ne fait que les servir. Avec Podman et l'image officielle (`ghcr.io/valhalla/valhalla-scripted`), sur le
fichier France de Geofabrik :

```bash
# sur le PC : construire (le fichier .osm.pbf se télécharge dans le dossier, ~4,5 Go)
mkdir -p ~/valhalla/custom_files
podman run --rm --name valhalla-construit --memory 12g \
  -v ~/valhalla/custom_files:/custom_files:Z,U \
  -e tile_urls=https://download.geofabrik.de/europe/france-latest.osm.pbf \
  -e serve_tiles=False -e build_elevation=False -e server_threads=4 \
  ghcr.io/valhalla/valhalla-scripted:latest
ls -lah ~/valhalla/custom_files     # valhalla_tiles.tar, valhalla.json, .file_hashes.txt, les bases admin et fuseaux
# puis copier sur le portable, sans le .pbf
rsync -a --exclude '*.pbf' ~/valhalla/custom_files/ mika-portable:valhalla-tuiles/
# « :U » donne le dossier à l'utilisateur du conteneur : pour l'effacer, podman unshare rm -rf ~/valhalla
```

Sur le portable, le dossier en place, puis le service (une unité Quadlet de Podman,
`/etc/containers/systemd/valhalla.container`), qui sert sur la seule boucle locale :

```bash
sudo install -d -m 0755 /var/lib/valhalla
sudo rsync -a ~/valhalla-tuiles/ /var/lib/valhalla/custom_files/
sudo podman pull ghcr.io/valhalla/valhalla-scripted:latest
```

```ini
[Unit]
Description=Valhalla, les itinéraires de l'écran Carte (ADR 0194)
After=network-online.target

[Container]
Image=ghcr.io/valhalla/valhalla-scripted:latest
ContainerName=valhalla
PublishPort=127.0.0.1:8002:8002
Volume=/var/lib/valhalla/custom_files:/custom_files:Z,U
# les tuiles construites sur le PC, sans rien reconstruire ici
Environment=use_tiles_ignore_pbf=True
Environment=force_rebuild=False
Environment=serve_tiles=True
Environment=server_threads=2

[Service]
Restart=on-failure
# le portable a peu de mémoire libre : les tuiles sont lues dans le fichier, au besoin
MemoryMax=2G

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl start valhalla
curl -s http://127.0.0.1:8002/status                # sa version : il répond
```

Puis, dans la console, Réglages › Carte et téléphone › Itinéraires : « Un Valhalla à toi », `http://127.0.0.1:8002`,
et son débit (10 demandes par seconde par défaut). Pour le mettre à jour : reconstruire sur le PC de temps en temps, recopier,
`sudo systemctl restart valhalla`.

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
qu'elle déchiffre (clés d'API, mot de passe IMAP, connexion Microsoft d'une boîte, jeton git). Donc :

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
cd /opt/mika/frontendv2 && sudo npm ci && sudo env VITE_BACKEND_ORIGIN= npm run build   # si tu sers frontendv2
sudo systemctl restart mika
```

La ligne de `frontendv2` reconstruit les fichiers que le mandataire sert (« Servir
frontendv2 », plus haut) : sans elle, la page d'avant parle au moteur d'après. Le
client 3D, s'il est servi, se reconstruit de même dans `/opt/mika/frontend/Web`.

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
