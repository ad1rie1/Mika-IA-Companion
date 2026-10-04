# 0049 — Où elle est dans sa chambre

> Repris par l'ADR 0050 : son corps vit dans la faculté `world`, l'outil s'appelle `go_to` (mêmes règles : lieu fermé, même lieu sans écriture, un déplacement par épisode), le coucher est un réducteur de `world`. `place` garde le type `place.moved` et les faits que lisent les écrans.

**Contexte.** Le frontend montre Mika dans sa chambre (bureau, fenêtre, lit, bibliothèque, porte, le tapis au
milieu), mais elle y restait plantée au milieu, debout, y compris pour dormir. Le corps sait maintenant marcher,
contourner les meubles, s'asseoir et s'allonger (`frontend/Web/src/vtuber/locomotion/`) ; restait à dire **qui décide**
où elle va. Ce n'est pas le client : c'est elle, donc le modèle — et ce qu'un modèle pilote doit tenir face à ce
qu'un modèle fait (inventer un lieu, rappeler l'outil, zigzaguer).

**Décision.**
1. *Une faculté `place`* (contrat `contracts/place.py`) : l'état `place` (un vocabulaire fermé `Place` : `center`,
   `window`, `desk`, `bed`, `bookshelf`, `door`) et `since`, l'événement public `place.moved(place, by)`, les faits
   `place.current` et `place.since`. Jamais de coordonnées : le modèle choisit un lieu, le corps fait le chemin.
2. *C'est elle qui y va* : l'outil `move_to(place)` (lot `room`, en main dans les réponses et les initiatives — un
   seul petit outil, et c'est son corps : aller à la fenêtre ne se cherche pas dans un catalogue). Validé par le
   schéma avant tout appel (un lieu inventé revient en erreur, rien n'est écrit) ; y aller quand elle y est déjà
   n'écrit rien ; un déplacement par épisode au plus (`max_calls_per_episode=1`). Pas de balise `[MOVE:…]` : les
   crochets sont réservés à l'expression (`STYLE`, `_voice` les retire) et un outil donne validation, traces et
   dédoublonnage.
3. *Le sommeil la met au lit* : un réducteur de `place` sur `body.fell_asleep` (événement public), donc au rejeu
   aussi — on ne dort pas debout au milieu de la pièce. Au réveil elle reste au lit (assise sur le bord, côté
   frontend) jusqu'à ce qu'elle décide d'en bouger.
4. *Son prompt dit où elle est* : section volatile `place` (« OÙ TU ES »), éveillée seulement.
5. *Vers les écrans, un état* : `inner_state.place` (`adapters/web/protocol.py`) ; `place.moved` pousse un état sans
   parole (comme s'endormir, `Delivery(kind="state")`), et la connexion reçoit désormais son état intérieur tout de
   suite après le visage (`Session.announce`) — sans lui, un écran qui s'ouvrait la montrait au milieu de la pièce
   jusqu'au prochain changement. Le frontend traite le lieu comme un état : un changement se marche, le même lieu
   renvoyé ne fait rien, le premier reçu (ouverture, reconnexion) la pose sans marcher, un lieu demandé pendant
   qu'elle dort attend son réveil (sauf le lit), et elle marche jusqu'au lit les yeux ouverts avant de s'endormir.

**Conséquences.** La séquence d'ouverture d'une connexion devient historique → visage → état intérieur (les tests
de protocole qui la lisaient pas à pas l'attendent). Les épisodes de travail (`STEP`, `WORK`) n'ont pas l'outil :
qu'elle s'asseye à son bureau pour travailler sur un projet est une suite naturelle, laissée à plus tard.
Tests : `tests/unit/test_place.py` (en main et efficace, lieu inventé refusé, même lieu sans écriture, un
déplacement par épisode, le sommeil au lit, le prompt) — non vides par mutation (limite par épisode, réducteur du
coucher).
