---
paths:
  - "backendv2/src/mika/inspector/**"
  - "backendv2/src/mika/app/handmade/**"
  - "backendv2/src/mika/app/console.py"
  - "backendv2/src/mika/app/console_menu.py"
  - "backendv2/src/mika/app/reglages.py"
  - "backendv2/src/mika/faculties/*/inspect.py"
  - "backendv2/src/mika/plugins/**/console*.py"
  - "backendv2/src/mika/plugins/**/console/**"
  - "backendv2/tests/browser/console.cjs"
  - "backendv2/docs/console-carte.md"
---

# La console : thème et disposition

Ces règles valent pour toute page de la console (`/inspecteur/`), nouvelle ou retouchée. Le pourquoi est dans l'ADR 0176
(`backendv2/docs/decisions.md`). Ce que fait chaque page est dans `backendv2/docs/console-carte.md`, qu'on met à jour
dans le même lot.

## Le thème

- **Fond blanc et filets.** Pas d'aplat gris en thème clair. Les couleurs viennent des jetons `var(--…)` de
  `inspector/static/console.css`, jamais en dur. Chaque page doit marcher aussi en thème sombre.
- **La typographie.** Inter pour le texte, Inter Display (`var(--display)`) pour les titres, pas de serif. La police
  est servie par la console (`static/fonts`), jamais par un CDN.
- **Les formes.** Trois arrondis (`var(--radius)` : 6, 4, 3 px). Pas d'ombre, sauf pour ce qui flotte : menus,
  panneaux, la barre d'enregistrement quand une valeur a changé. Contrôles de 32 px, 44 sur un écran tactile.
  Étiquettes et boutons rectangulaires, compacts.
- **La CSP est stricte.** Ni `style=` ni `<script>` en ligne : seulement des classes et des fichiers sous `static/`.
  Tout changement d'un fichier de `static/` incrémente `ASSET_VERSION` (`inspector/ui.py`).
- **Les mots.** Toute l'interface est en français. On écrit « moyen de communication », jamais « adresse ».

## La disposition

- **La navigation est en haut.** Pas de menu à gauche pour toute la console. Une colonne à gauche n'existe que dans
  le contenu, pour des sous-onglets.
- **Toute la largeur.** Le contenu prend la largeur de l'écran. Seuls les paragraphes gardent une mesure de lecture
  (en `ch`).
- **Un onglet tient dans un écran, autant que possible.** Pas de page qui défile sans fin :
  - une page à plusieurs sujets passe en sous-onglets (`.hm-subtabs[data-subtabs]`, sections `[data-pane][id]`) ;
  - une liste courte passe en colonnes, une longue se pagine ;
  - un long tableau secondaire se replie (`Disclosure`) ;
  - pas de carte dans une carte.
- **Une seule barre d'onglets par destination,** la même sur toutes ses pages. Si la page d'entrée est dessinée à part,
  elle est son premier onglet (`Destination.lead`). Pas de barre à un seul onglet, ni d'onglet qui répète un filtre.
- **Le fil d'Ariane** d'une destination dit sa rubrique puis la destination (« Mika / Humeur et corps », séparés par
  « / »), au-dessus du titre de l'onglet.
- **Un filtre de petits choix** (quatre au plus, toujours posé : une période) est un bouton à choix (`.seg`) au bout de
  la barre d'onglets, appliqué d'un clic, jamais un sélecteur et un bouton « Filtrer ». Les bascules (« Fiches /
  Tableau ») ont le même dessin.
- **Une page est dessinée** (ADR 0121). Son gabarit est sous `templates/handmade/` et sa mise en forme sous
  `app/handmade/`. Elle reprend le vocabulaire commun de `static/handmade/base.css` (`now-card`, `person-entries`,
  `hm-*`), jamais des blocs génériques seuls.

## Les trois gabarits

- **Le client** (le courrier) : ce qu'on lit à gauche, la liste, la liseuse à côté.
- **Le paramétrage.** Une ligne par réglage : son nom et son aide à gauche, sa valeur à droite, deux par rangée quand
  la place le permet. Un texte long, une liste à cocher ou un curseur prennent toute la largeur. Le formulaire d'une
  action qui a sa page suit le même gabarit.
- **La vue d'un objet** : le fil « rubrique / destination / n° », son état en étiquettes à côté de son nom, ses faits
  sur une ligne séparés par des filets ; ses onglets disent leur compte, les plus rares sous « Plus » ; un seul
  bandeau d'alerte, une bande de chiffres qui mènent à leurs onglets, puis des tuiles.

## Les actions

- **Les actions de la page sont dans la barre de titre, à droite.** Deux en vue au plus : la principale (la première
  déclarée) en avant, à droite des autres ; le reste et les dangereuses sous « ⋯ » ; la roue des réglages (`gear`)
  ferme la barre. On les y met ainsi :
  - un panneau, par `page_links` ;
  - un onglet dessiné, par le triplet de `Drawn.render` (`blocks.lift` et `blocks.head`) ;
  - sinon, par les actions de la destination (`head_actions`).
- **Les actions d'un objet** sont sur sa ligne, sa carte ou sa fiche, jamais dans la barre de titre.
- **Enregistrer** : une seule barre par formulaire, collée en bas.

## Vérifier

Après un changement, on vérifie dans cet ordre :

- **Un export** : `mika console apercu --out output/…`, jamais dans `/tmp`.
- **Des captures**, en clair et en sombre, à 1440 et à 390 px de large. On les regarde avant de conclure.
- **Les tests de la console ciblés** (`tests/protocol/test_console_*`, `test_drawn_*`, les pages touchées), puis
  `ruff`, `lint-imports` et `tests/browser/console.cjs` sur l'export. Pas la suite complète : elle concerne très peu
  la console.
