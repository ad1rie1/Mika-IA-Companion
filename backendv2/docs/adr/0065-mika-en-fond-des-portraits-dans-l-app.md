# 0065 — Mika en fond : des portraits pré-rendus dans l'application mobile

> Remplacée par l'ADR 0067 (Mika en 3D native) : les portraits ne restent qu'un repli.

**Contexte.** L'application Android (ADR 0062) est une messagerie : l'avatar 3D y était hors périmètre, laissé au
client web et au client Unity. Elle reçoit pourtant déjà tout ce qu'il faut pour montrer Mika vivante : l'émotion
de chaque parole (`speech`), la dérive de son humeur entre deux tours (`emotion_update`, envoyée seulement à un écran
regardé) et son état (`inner_state_update` : sommeil, énergie). La propriétaire a demandé (2026-10-04) que l'app
affiche l'avatar en fond, avec ses émotions faciales et une gestuelle statique. Le VRM pèse 101 Mo (80 000
triangles, 1 759 cibles de morphose) : l'embarquer, l'analyser et le faire tourner en continu sur un téléphone
coûterait mémoire et batterie à un écran dont le sujet reste la conversation.

**Décision.**

1. *Des images, pas de moteur 3D.* L'app montre des **portraits pré-rendus** : un par émotion (les 29), plus
   « coucou », « fatiguée » et « endormie ». Chacun porte ses yeux fermés, découpés au plus juste et fondus sur les
   bords, posés le temps d'un clignement. Environ 4 Mo en WebP pour 32 portraits en 1080×1440.
2. *Un seul personnage, deux rendus.* Le script Blender (`frontend/Web/assets-src/blender/portraits.py`) recopie le
   visage du client web à l'identique : les recettes d'expressions (`EmotionController`) jouées sans les symboles
   manga (`faceRig`), la physiologie à l'équilibre (`FacePhysiology` : rougeur, pupilles, yeux humides sans larme),
   le port de tête (`HeadEmotionOverlay`). Le corps est une image choisie des mouvements de l'atelier (déjà posés au
   sol et nettoyés), la tête et les yeux tournés vers l'objectif comme le font `HeadAttentionOverlay` et
   `GazeController` ; les mèches longues retombent (le modèle livre ses ressorts sans gravité, et rien ne les simule
   sur une image figée).
3. *Pas versionnés.* Le modèle est sous licence de l'acheteur : comme la scène de l'atelier et ses rendus, les
   portraits ne sont pas dans le dépôt. Ils s'écrivent dans les assets de l'app (dossier ignoré). Une app construite
   sans eux n'a pas d'avatar et ne propose pas l'interrupteur.
4. *Le choix est une fonction pure de ce que l'app sait déjà* (`AvatarDirector`) : endormie d'abord (rien ne la
   réveille à l'écran), puis le salut quand on la retrouve après 20 minutes, puis la réflexion pendant « Mika
   écrit… », puis son émotion si elle est assez marquée (intensité ≥ 0,25 ; une humeur légère cède à la fatigue sous
   0,3 d'énergie), le visage au repos sinon. Aucune trame ni aucun champ nouveau côté serveur.
5. *Vivante sans changer d'image* : un souffle (le haut du corps monte d'un ou deux pixels), des clignements
   irréguliers et parfois doubles, un fondu et un petit élan à chaque changement de pose, une lumière qui suit la
   famille de l'émotion, et la nuit (ombre bleue, étoiles en thème sombre, « z » qui montent). Tout s'arrête quand
   Android supprime les animations. Le portrait est un décor : un lecteur d'écran ne le lit pas, la ligne d'état dit
   déjà comment elle va.

**Conséquences.** Le serveur ne change pas. Une émotion nouvelle côté serveur s'affiche sur le visage au repos
tant qu'elle n'a pas son portrait. Changer une pose ou une expression, c'est relancer le script (environ une
minute et demie) puis reconstruire l'app ; le studio de débogage (`AvatarStudioActivity`) montre la conversation
sur chaque portrait sans serveur. Les portraits figent l'expression à pleine intensité : l'app ne montre pas les
nuances d'intensité ni le mélange de deux émotions, que le client web garde.
