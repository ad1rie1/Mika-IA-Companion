# 0067 — Mika en 3D native dans l'application mobile (Filament)

**Contexte.** L'ADR 0065 a mis Mika derrière la conversation sous forme de portraits pré-rendus. Vue sur le
téléphone, l'image ne vivait pas : ni mains, ni tête, ni corps qui bougent. Des boucles pré-rendues (labo dans
Chrome) ont suivi. À 10–15 images/s, elles restaient saccadées ; à 30, elles pesaient 5 à 12 Mo par état, plus de
150 Mo pour les 29 émotions ; et chaque retouche demandait plusieurs minutes de rendu. La propriétaire veut l'effet
de la 3D : rendre le VRM et jouer les animations. Elle a écarté une WebView, mal optimisée pour une app qu'on garde
ouverte longtemps, et demandé le meilleur de deux voies natives, sans craindre le travail.

**Décision.**

1. *Rendu natif avec Filament* (le moteur 3D de Google, 1.77), dans une `TextureView` transparente posée sur la
   lumière de l'humeur. Pas Unity embarqué : un moteur de jeu complet tournerait en continu (200 à 300 Mo de RAM,
   60 à 100 Mo d'APK, une seule instance par processus, celui même du service de connexion). Filament ne dessine
   que quand on le lui demande : une image par battement de l'écran tant que la vue est visible, aucune sinon.
2. *Un VRM préparé pour le téléphone* (`frontend/Android/tools/vrm_mobile.py`), sans perte de qualité. Les textures
   restent en pleine résolution. Le visage passe de 342 morphoses à 167 ; Filament en accepte 256 au plus par
   primitive. Les morphoses sont rangées en accesseurs sparse, et le maillage du visage est découpé par matériau :
   chaque morceau ne porte que ses sommets et les morphoses qui les déplacent (345 au lieu de 835), là où le
   chargement prenait 18 s. Les liens d'expression désignent leur morphose par son nom. Le résultat (30 Mo) n'est
   pas versionné : le modèle est sous licence de l'acheteur.
3. *Les mouvements de l'atelier, une seule source.* Les 49 mouvements nettoyés
   (`frontend/Unity/ArtSource/atelier/motions`), ceux qu'Unity importe déjà, et le manifeste des animations du
   client web sont copiés dans l'APK à chaque construction. Le reciblage est direct : le VRM a pour repos une
   T-pose aux rotations nulles. L'orientation d'un os est donc son changement depuis le repos de l'atelier,
   ramené de Blender au glTF par (x, y, z) → (−x, z, y), vérifié sur les positions de repos à 0,1 mm près.
4. *Le comportement du client web, porté en Kotlin pur et testé sur la JVM.*
   - Le corps : la machine à états (attentes tirées selon l'humeur, jumeaux en miroir, tempo et tenue réglés par
     l'arousal, gestes ponctuels, postures d'émotion, bâillement et étirement autour du sommeil), et la table des
     gestes par émotion avec ses portes, dans le même ordre.
   - Les couches procédurales : souffle, micro-mouvements, port de tête, attention et regard.
   - Le visage : expressions sans symboles manga, physiologie, clignements, micro-expressions.
   Une parole peut déclencher un geste, une humeur qui dérive ne change que la posture : l'humeur mémorisée dit
   d'où elle vient (`Mood.reply`).
5. *Cheveux et vêtements simulés* comme three-vrm le fait (les ressorts du VRM 0.x, 198 articulations). Les
   réglages par famille sont ceux qu'Unity leur a rendus, puisque le modèle les livre sans gravité.

**Conséquences.** Les portraits de l'ADR 0065 deviennent un repli : une app construite sans le VRM préparé les
montre encore, et sans rien du tout il n'y a pas d'avatar. L'APK grossit d'environ 30 Mo (le modèle), plus
quelques Mo de bibliothèques Filament (arm64 et x86_64 seulement) et 5 Mo de mouvements. Une animation ajoutée à
l'atelier arrive dans l'app à la construction suivante ; il n'y a plus rien à rendre. Le rendu est « unlit » pour
commencer, comme le repli glTF des matériaux du VRM. Un shader toon proche de MToon (ombrage, rim, contour) reste
à écrire, et les textures nécessaires sont gardées pour lui.
