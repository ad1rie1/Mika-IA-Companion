# 0060 — Telegram retiré, les identités inconnues gardées

**Contexte.** Le 2026-10-04, la propriétaire a décidé qu'on écrirait désormais à Mika **par une application dédiée**
(le frontend web, le client Unity, plus tard une application mobile), toujours avec un compte : plus de robot
Telegram. Le robot (ADR 0038, 0057) occupait l'adaptateur `adapters/telegram/`, un routeur de livraison, une section
de réglages et une page de console, une commande `mika telegram`, un état dans `/health`, l'appairage par code et une
dépendance facultative. Il avait aussi été, dans le domaine, le seul canal à porter quatre notions : un **compte qui
ne prouve pas qui le tient** (confiance « compte »), une **messagerie** où l'on lit quand on y pense, la possibilité
d'**écrire à quelqu'un d'absent** (`identity.REACHABLE`), et les **salons publics**. Ces notions sont au cœur de la
gestion des identités inconnues (revendications, recoupements, divulgation graduée, refus de recopier un message
privé devant un salon), et la propriétaire tient à les garder : si Mika navigue un jour sur Internet d'elle-même, elle
y créera des identités et échangera sur des canaux non sécurisés.

**Décision.**

1. *Le transport disparaît entièrement.* `adapters/telegram/` (canal, relève `python-telegram-bot`), le routeur
   `app/delivery.py` (le web, seul transport, est désormais le port de livraison), `Live.start/stop/pair_telegram`
   et leur relance, la santé des canaux (`health_extra` de l'application web, qui n'avait que lui), la section
   « Telegram » de Configuration › Canaux (qui garde « Dépôts git » ; l'ancienne adresse `reglages/canaux` y mène),
   la commande `mika telegram`, l'appairage (`Settings.telegram*`, codes, constantes), le masquage des jetons
   `/bot<jeton>` dans les journaux, et l'extra `telegram` de `pyproject.toml`. Les réglages Telegram d'une
   installation existante sont **effacés à l'ouverture** (`settings.RETIRED_KEYS`) : un jeton scellé que plus rien
   ne lit ne reste ni dans `mind.db` ni dans ses sauvegardes. Les propriétaires sans compte opérateur restent un
   paramètre de l'identité (`identity.owners`), réglable par surcharge ; plus aucun réglage ne le fournit.
2. *Ce qu'il avait fait naître reste, sans nom de produit.* Le vocabulaire déclare le canal générique d'un **compte
   extérieur** — `privacy.EXTERNAL` (« external »), adresses `ext_…` (`people.EXTERNAL_PREFIX`, réservé : un
   navigateur ne peut pas s'en réclamer) — au côté des canaux de compte déjà listés (`discord`, `signal`, `email`).
   `privacy.is_messaging(canal)` dit ce que les facultés testaient en écrivant `canal == "telegram"` : le délai
   « messagerie » de l'attention et sa tolérance aux réponses tardives, la classe « messagerie » des délais appris
   (`others`), l'adresse joignable hors ligne (`identity`, conversation privée). `privacy.channel_of(adresse)`
   remplace la déduction `tg_…` → Telegram pour une adresse reliée d'avance par un opérateur. Aucune règle de
   confiance, de certitude ni de divulgation ne change.
3. *Les épreuves gardent leur sens.* Les scénarios du simulateur (S19, la sonde, la vie des autres) et les tests du
   domaine écrivent `ext_…` sur le canal `external` là où ils écrivaient `tg_…` sur Telegram : un inconnu qui se
   dit Alice, un salon qui demande de recopier un message privé, une amie qu'elle peut joindre absente, deux comptes
   homonymes. Le web reste un écran : on y répond en minutes, et seulement si on est là.

**Conséquences.** Aucun événement ne change de forme ; un journal qui contiendrait des perceptions Telegram se rejoue
(un canal que plus rien ne décrit est traité comme public, le pire de ce que personne n'a décrit) — celui de
l'installation de la propriétaire n'en contient aucune. Contrats : `Live` perd `router`, `telegram*`, `make_poller`,
`channel_health` ; `create_app` perd `health_extra` ; `InspectorDeps` perd `restart_telegram` ; `Settings` perd
`telegram`, `save_telegram`, `telegram_pairing`, `new_telegram_pairing`, `clear_telegram_pairing` et gagne
`RETIRED_KEYS` ; `vocab.privacy` gagne `WEB`, `EXTERNAL`, `channel_of`, `is_messaging` ; `vocab.people` gagne
`EXTERNAL_PREFIX` (« tg_ » n'est plus réservé). Aucun paramètre (`Knob`) retiré : le délai « messagerie » vaut pour
tout compte extérieur. Tests : `tests/unit/test_no_telegram.py` (purge du réglage retiré, aucun import ni nom du
canal dans le code — vérifié sur l'arbre syntaxique, pas sur le texte —, le compte extérieur non prouvé) ;
`tests/protocol/test_telegram.py` et les tests du robot (relance, appairage, page de console, santé) sont supprimés.

**Reste.** Sans robot, elle ne peut plus écrire d'elle-même à quelqu'un qui n'est devant aucun écran : aucune adresse
d'aujourd'hui n'est une messagerie (un compte web est un écran ; une réponse à une personne absente l'attend dans son
fil). Quand l'application dédiée saura recevoir hors ligne (une notification), son canal pourra se déclarer
messagerie dans `vocab.privacy` et redonner vie à `identity.REACHABLE`. Les ADR précédentes qui décrivent le robot
(0038, 0057…) restent telles qu'elles ont été écrites.
