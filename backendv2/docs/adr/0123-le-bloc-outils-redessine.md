# 0123 — Le bloc Outils, redessiné

**Contexte.** Le 2026-10-21, le jour même de l'ADR 0122, le propriétaire ouvre la console et tranche : « toute la
partie Outils est à revoir, on y comprend rien ». Le bloc avait sept entrées :

- trois pages montraient les mêmes données (outils × situations), chacune avec ses mots : le catalogue (« famille »,
  « disponible pour »), « Qui reçoit quoi » (« lot »), « Régler ses outils » (« situation », « comme le code ») ;
- le vocabulaire venait du code : « porte d'offre du pipeline », « audiences types », « un fournisseur qui ne sait pas
  différer », « un pas qui choisit ses lots », et des identifiants bruts en guise de noms (`workshop`, `mcp.web`,
  `forge_apps.veille_hn`) ;
- la notion qui portait toute la légende, « en main / à la demande », ne changeait rien sur un fournisseur qui ne
  diffère pas, et la page le disait en petit ;
- « Outils de ses apps » disait qu'aucune app ne déclarait d'outil, alors que le catalogue montrait l'outil qui lit
  les pages d'une app ;
- « Régler ses outils » alignait 53 menus déroulants et un seul bouton tout en bas ;
- « Ce qu'elle expose » s'ouvrait sur le relais du moteur Claude Code, où il n'y a rien à régler.

Parmi trois structures (quatre pages et le réglage sur place ; lire et régler séparés ; garder les sept et
réécrire), il choisit la première.

**Décision.**

1. *Quatre entrées* : « Ce qu'elle peut faire », « Venus d'ailleurs », « Prêter à un agent », puis « Apps forgées ».
   Les anciennes adresses redirigent : `outils/qui` et `outils/texte` vers `outils/tous`, `outils/outils_apps` vers
   `outils/serveurs`.
2. *« Ce qu'elle peut faire »* (`outils/tous`, `inspector/pages/tools.py::can_do`, gabarit `handmade/outils/peut.html`)
   est une seule grille. Ses familles d'outils sont en lignes, et chaque famille s'ouvre sur ses outils. Les
   situations sont en colonnes, rangées par ce qui se passe : « Elle répond à… » sa propriétaire, un compte, une
   inconnue, un salon ; « D'elle-même », à sa propriétaire ; « Elle travaille seule sur… » un but, un projet, un
   brouillon.
   - Une famille dit, situation par situation, si elle a tous ses outils (✓), une partie (2/5), si un opérateur les
     lui a retirés (✕) ou si rien n'est prévu (—).
   - Un outil a une case à cocher là où le code l'offre. La décocher le lui retire dans cette situation, la recocher
     le lui rend. Un tiret dit, au survol, pourquoi ce n'est pas prévu. Un outil qui clôt sa boucle est coché, sans
     case. « À chercher » ne se montre que si un fournisseur diffère vraiment.
   - Le formulaire porte les outils qu'il montrait (`vu`) : une grille filtrée par une recherche ne touche pas aux
     autres.
   - Dessous, replié, le texte exact que son prompt porte sur ses outils, situation par situation.
   - Ses blocs (la même liste en tableau) ne servent qu'à la console en MCP : sur la page, la grille est le panneau
     (`app/handmade/tools.py::Catalogue`).
3. *La fiche d'un outil* dit où elle peut s'en servir, avec un réglage par situation : « comme prévu », « retiré » et,
   quand le fournisseur diffère, « toujours sous la main » ou « à chercher ». La place fine (`hand`, `ask`) se règle
   là, et seulement là. Le reste (ses derniers appels, ses arguments, sa provenance) suit.
4. *Un seul enregistrement* : `POST /inspecteur/outils/regler` reçoit la grille (ses cases), la fiche (`outil`,
   `r.<situation>`) ou « Tout remettre comme prévu » (toutes les situations). L'audit reste `console.outils.regler`, un
   par situation changée. Le message dit ce qui a changé, outil par outil.
5. *Les familles portent un nom* : `Labels.bundles` (`app/console.py::BUNDLE_LABELS`, `Names.bundle`). Un lot qui
   ne se nomme pas comme sa faculté y a son nom (« L'atelier d'un projet », « Qui lui parle »). Une source qui ajoute
   des lots les nomme par un motif (« mcp.* » : « Service « {} » », « forge_apps.* » : « Son app « {} » »).
6. *« Venus d'ailleurs »* est l'onglet du plugin MCP (`serveurs`, ses services branchés, son badge « à revoir »).
   La composition y dessine dessous la vue de la Forge qui liste les outils de ses apps
   (`app/handmade/tools.py::Elsewhere`). Cette vue n'a plus d'onglet (`hidden`). Elle compte aussi l'outil qui lit
   les pages d'une app.
7. *« Prêter à un agent »* (ex-« Ce qu'elle expose ») commence par ce qui se décide : la console en lecture (son
   jeton, puis, replié, ce qu'elle montre : d'office, et en plus), puis les points de prêt. Le relais du moteur Claude
   Code est replié en bas.

**Conséquences.**

- Rien ne change à ce que la porte décide (ADR 0122) : la grille et la fiche lisent les mêmes règles par les mêmes
  fonctions (`offered_in`, `why_not`, `deferred`), et un test vérifie toujours que le récit « pourquoi pas » dit ce
  que fait la porte.
- La console en MCP ne sert plus « Qui reçoit quoi » (`SERVABLE`) : la liste de « Ce qu'elle peut faire » dit, outil
  par outil, où elle peut s'en servir. Une sélection enregistrée qui la nommait l'ignore.
- La place fine (« sous la main », « à chercher ») n'est plus dans la grille : sur un fournisseur qui ne diffère pas,
  elle ne voulait rien dire. Elle reste sur la fiche, là où elle compte.
