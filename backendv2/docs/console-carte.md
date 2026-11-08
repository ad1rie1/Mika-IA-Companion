# La carte de la console

Ce que chaque entrée du menu de `/inspecteur/` montre, et sous quelle forme. Le menu visible vit dans
`app/console_menu.py` ; les destinations (adresses, onglets, libellés) dans `app/console.py` ; les réglages dans
`app/reglages.py` ; les pages dessinées à la main dans `app/handmade/` (gabarits `inspector/templates/handmade/`,
feuilles `inspector/static/handmade/`, la table `app/handmade/pages.py::DRAWN`, les onglets de chaque destination dans
`app/handmade/tabs/`). Les décisions sont dans les ADR 0025, 0029, 0042, 0045, 0103, 0121 à 0124, 0176 et 0177.

Trois règles tiennent toute la console :

1. **Toute information en table est paginée.** Une vue qui oublie de paginer est
   découpée par le rendu (25 lignes, `?pg<n>=`) ; une pagination à curseur
   (le journal) sait revenir aux plus récents et au début.
2. **Une page de configuration ne montre qu'un sujet.** Chaque section de
   réglages est découpée en sous-pages ; chaque champ dit ce qu'il fait, sous son nom
   (jamais seulement au survol — sauf dans la table de mixage du tempérament, où l'aide
   du curseur touché se lit à côté).
3. **Un champ ne se montre que s'il sert.** Un choix limité est un sélecteur
   (modèle, budgets, rôle) ; un champ qui ne vaut que pour un type de fournisseur
   n'apparaît qu'avec lui ; ce que le SDK ou la CLI sait déjà (URL, hôte,
   commande) est rangé dans « Options avancées ».

## Le cadre

Toute page a la même barre du haut (`inspector/templates/base.html`, ADR 0176) : les rubriques du menu, chacune un menu
déroulant (sa question en tête, puis ses pages, chacune avec une ligne d'explication, `MenuLink.hint`, ou celle de sa
colonne) ; « Aller à… »
(Ctrl K ou `/`), qui propose à la frappe les pages de la console, puis « Chercher partout » (la recherche globale ; sans
script, le formulaire y mène) ; son état en pastille — son humeur en un mot et son énergie nommée (« curieuse ·
énergie 53 % » : l'intensité de l'émotion reste dans le panneau), le nombre d'alertes ; jusqu'à 1 440 px de large sans
son nom, déjà en tête de la barre, et sous 1 361 px son nom sans le résumé ; c'est elle qui cède quand la barre manque
de largeur, jamais les rubriques —, qui se déplie sur tous ses vitaux, relus toutes les 10 s (`/_vitals`) ; le menu du
compte (« Mon compte », sa fiche dans Réglages › Comptes ; le thème ; la déconnexion). Un seul menu s'ouvre à la fois ;
un clic ailleurs ou Échap le ferme. Sur un écran étroit, les rubriques passent dans un panneau, ouvert par le bouton Menu
(sans script : une case à cocher). Sous la barre, chaque page a sa barre de titre : son fil
d'Ariane (plus bas), le titre et, sur une fiche, son état en étiquettes à côté, ses faits sur une ligne séparés par des filets,
et ses actions à droite (deux en vue, la principale à droite des autres, le reste et les dangereuses sous « ⋯ »), la roue qui ouvre ses réglages
(`gear`, ADR 0173, 0206 : les réglages d'un plugin vivent dans sa destination) au bout. Une action est à côté de ce qu'elle touche : celles de la page dans la barre de titre —
Courrier (Nouveau message, Actualiser), Venus d'ailleurs (Brancher un service), Comptes (Ajouter un
utilisateur, un opérateur) ; un onglet dessiné les y remonte (`Drawn.render` rend un triplet ; `blocks.lift` et
`blocks.head` dans `app/handmade/blocks.py`), un panneau les y nomme (`page_links`) —, celles d'un objet sur sa ligne,
sa carte ou sa fiche, Enregistrer dans la barre d'enregistrement. Des filtres qui ne sont que de petits choix
(quatre au plus, une valeur toujours posée : la période d'Humeur et de Besoins) deviennent des boutons à choix au bout
de la barre d'onglets, appliqués d'un clic (`render.quick_filters`, `.seg`) ; les autres gardent leur formulaire et son
bouton « Filtrer ». Le contenu prend toute la largeur de l'écran, comme la barre du haut ; seuls les paragraphes gardent une mesure de lecture. Le style : fond blanc et filets, Inter servie par la console (`static/fonts`, `font-src 'self'`),
trois arrondis, une ombre seulement pour ce qui flotte (menus, panneaux, la barre d'enregistrement quand une valeur a
changé).

**Le fil d'Ariane part du menu** (ADR 0202). Un seul constructeur, `Pages.trail` (`inspector/pages/routes.py`) : il part
toujours de la rubrique du lien de menu qui mène à la page (`catalog.menu_place` : le plus précis ; à précision égale,
celui de la rubrique où vit sa destination), puis dit sa destination, sous le nom de ce lien ; la page n'y ajoute que
ses niveaux à elle. Chaque niveau mène à sa page, sauf la page même. Ainsi :

- une destination : « Mika / Humeur et corps » au-dessus de « Besoins » (la destination en lien quand le titre est
  celui de l'onglet) ; En ce moment dit « Mika », la page d'entrée de Personnes « Échanges / Personnes » ;
- Réglages et Système : la rubrique, puis le lien du menu qui couvre la page — « Réglages / Personnage » au-dessus de
  « Tempérament », « Personnage » menant à sa première page —, ou sa colonne (« Système / Journaux » au-dessus de
  « Gestes audités ») ; une page de faculté, « Réglages / Paramètres avancés / Émotions », « Paramètres avancés » menant
  à la vue d'ensemble et « Émotions » à sa famille (l'ancre `famille-` suivie de son nom en minuscules) ; une page de réglages qu'un lien d'une autre rubrique couvre suit cette rubrique (« Connexions /
  Dépôts Git ») ; une page qu'aucun lien ne couvre garde son groupe, en repli ; les réglages d'un plugin, derrière
  la roue de leur destination (ADR 0206), disent la destination : « Échanges / Teams » au-dessus de « Paramètres » ;
- une fiche : sa rubrique, sa destination et l'objet par son numéro, « Activité / Projets / n° 257 » ; un objet qui
  n'a pour nom que sa clé (son titre est sa clé) la dit à la place, comme un outil : un serveur extérieur, « Outils /
  Ses outils / web », un réveil ; un objet que son titre nomme autrement (une personne, un moyen de communication, un
  mail) s'arrête à sa destination, « Échanges / Personnes » : sa clé, interne (`user_1`), ne se dit pas
  (`Subjects.trail`, `inspector/pages/subjects.py`) ; de même un événement (« Système / Journaux / Journal
  d'événements / n° 93 »), une parole (« Échanges / Conversations / n° 58 »), un épisode (« Activité / Décisions /
  Épisodes »), un outil (« Outils / Ses outils / email_read »), un compte (« Réglages / Comptes / Béa Martin ») ;
- un retour ne remplace jamais le chemin : celui qu'une faculté déclare (`Head.back`) devient le lien de la
  destination quand il y mène (la liste filtrée d'où vient un mail, la liste des outils filtrée), et se dit à part,
  au bout du fil, sinon (« ← Ses pièces ») ; la liste d'où l'on vient (`?retour=`) aussi, « ← Retour à la liste » ;
  une page d'action dit « ← Retour » quand on n'y vient pas de sa destination.

## Le menu

| Rubrique | Entrées | La question de l'opératrice |
|---|---|---|
| **Accueil** | — | « Tout va bien ? Que dois-je faire ? » |
| **À valider** | Tout ce qui attend · Courriers à envoyer · Réponses Teams · Identités à confirmer · Noms à relier · Historique des autorisations | « Qu'est-ce qui attend ma décision ? » |
| **Sa rubrique**, à son nom | En ce moment · **Humeur et corps** (Humeur · Postures · Besoins · Sommeil et rythme · Monde et corps · Estime et récit · Qui elle devient) · **Pensées et nuits** (Pensées · Ce qu'elle remarque · Attentes · Journal et rêves) · **Mémoire** (Souvenirs · Croyances · Pièces reçues · Fichiers envoyés · Promesses · La vie des autres · Voir venir · Consolidation) · Constellation | « Comment va-t-elle, à quoi pense-t-elle, que retient-elle ? » |
| **Relations & échanges** | **Personnes** · **Conversations** · **Courrier** · **Teams** · **Identités**, chacune avec ses onglets | « Qui connaît-elle, qu'a-t-on dit ? » |
| **Activité** | **Projets** (Ses projets · Exécutions · Décisions techniques) · **Buts et rappels** (Buts vivants · Clos) · **Décisions** (Table de l'arbitre · Que ferait-elle ? · En cours · Initiatives · Ses choix · Épisodes · Échéances) | « Que fait-elle, pourquoi parle-t-elle ou se tait-elle ? » |
| **Outils** | **Ses outils** (Ce qu'elle peut faire · Venus d'ailleurs · Prêter à un agent) · Apps forgées | « Que peut-elle faire, et pour qui ? » |
| **Connexions extérieures** | **Ses sens** (Flux RSS · Caméra · Dessins · Appareils · Localisation · Messages du téléphone) · Réveils par API · Dépôts Git | « Que perçoit-elle du dehors, qui la fait agir ? » |
| **Réglages** | Tous les réglages · Modèles de texte · Modèles d'image · Personnage · Configuration des plugins · Carte et téléphone · Paramètres avancés · Comptes · Droits · Canaux · Historique des réglages | « Que décide l'opératrice ? » |
| **Système** | **Surveiller** (Santé générale · Processus · Anomalies · File de sortie · Moteur des modèles · Écrans du monde · Appels et coûts · Stockage et sauvegardes) · **Journaux** (Journal d'événements · Gestes audités · Historique des réglages · Historique des autorisations) · **Anatomie** (Diagnostic avancé · Contributions · Toutes les vues · Simulations) | « La machine tient-elle ? » |

En gras, les groupes de pages : une destination et ses onglets, ou une colonne de Système et ses pages. Dans la barre,
« Relations & échanges » s'appelle « Échanges » et « Connexions extérieures » « Connexions » (`MenuGroup.short`). Le
menu regroupe les destinations de `app/console.py` sans changer leurs adresses : liens, fiches, vues des facultés et
formulaires gardent les leurs (`InspectorDeps.menu` transmet la présentation à l'inspecteur). **Le menu fait foi**
(ADR 0202) : une destination porte le nom de son lien (`Destination.label` : « Ses sens », « Buts et rappels », « Ses
outils »), son fil d'Ariane le reprend, et le titre de chaque page reprend le nom que le menu lui donne — ou son fil
le nom du lien qui la couvre (`test_console_navigation.py` le vérifie lien par lien). Le menu d'une rubrique montre
ses groupes de pages (ADR 0178) : un lien vers une destination à onglets y est une colonne, son nom et sa ligne
d'explication, puis ses onglets, lus dans sa barre d'onglets même (`UI.tab_bar` : sans ce qui est rangé derrière sa
roue, sa page dessinée à part en premier) ; les pages seules qui se suivent partagent une colonne. Une rubrique qui
n'est qu'une destination (À valider, Système) nomme ses pages une à une, dans l'ordre et sous le nom de leurs onglets
(`tests/protocol/test_console_navigation.py`). Système les range en trois colonnes, comme des groupes de pages
(`MenuLink.column`, son nom et sa ligne d'explication dans `MenuGroup.columns`, ADR 0202) : Surveiller, Journaux,
Anatomie ; Journaux mène aussi à l'historique des réglages et à celui des autorisations, qui restent dans leur rubrique
(ouverts, c'est elle que le menu allume, et leur fil en part). Réglages fait exception : des raccourcis nommés par la
tâche, et les pages d'un même sujet derrière un lien (`also`) forment la barre d'onglets de chacune, dans l'ordre du
lien (Personnage : Identité, Portrait, Sa parole, Tempérament, Autrices, Import / export ; Carte et téléphone :
Carte de sa position, Lieux et adresses, Itinéraires, Notifications du téléphone) ; chaque page de réglages
appartient à un seul lien. Les réglages d'un plugin n'y sont pas : ils vivent dans sa destination, derrière sa roue
(ADR 0173, 0206), et Réglages n'y mène que par Configuration des plugins, leur vue d'ensemble, et l'annuaire ; aucun
lien ne les prend par `also`, la page de la roue allume le lien de sa destination, sans onglet. Sous 1320 px de large, les colonnes passent trois par rangée ; dans le panneau d'un écran
étroit, l'une sous l'autre, les onglets deux par rangée. « Aller à… » trouve aussi chaque onglet, sous le nom de sa
page. Sa rubrique porte son nom, lu dans sa persona au rendu (`MenuGroup.her`, ADR 0070). La page la plus précise
allume le bon lien, et dans un groupe son onglet : une fiche ouverte depuis une liste allume l'entrée de cette liste
(un brouillon : « Échanges › Courrier »), sans allumer d'onglet quand on n'y vient pas d'une liste ; un événement
allume Système › Journaux. Les compteurs restent sur les sous-pages et les onglets ; une rubrique affiche un point
d'attention, sans additionner des listes qui peuvent contenir la même demande ; la rubrique de la page courante est
soulignée dans la barre.

La recherche globale (`/recherche`, `inspector/pages/subjects.py`) trouve, sans tenir compte des accents, les pages de
la console (chacune avec son chemin, celui de son fil d'Ariane), les réglages (les entrées de l'annuaire, trouvées
comme il les trouve, par le nom et l'aide de leurs champs : « Trouvé dans : Fuseau horaire », `settings_directory.find`),
les vues où chercher dans les textes, un événement par son numéro, puis les objets de chaque sorte, leurs dates écrites
comme dans le reste de la console (`Inspection.search(when=…)`) et un compte sans sa clé interne. Les vues brutes des
facultés n'y sont plus une sorte de résultat : elles doublaient les pages sous des titres techniques ; quand l'une
porte le mot cherché dans son titre, un lien « Chercher dans les vues techniques » mène à Système › Toutes les vues
(ADR 0202).

Toute la console est dessinée (ADR 0121) : chaque onglet d'une destination a sa forme à lui (ADR 0177), sur les
données de sa faculté — un module par destination (`app/handmade/tabs/`) lit les blocs qu'elle déclare, rendus et
numérotés comme la console les rend (`Got` : leur pagination, la bascule « Tableau », les jetons de leurs formulaires
restent ceux de la console), et en fait sa page (gabarit `handmade/<destination>/<onglet>.html`, racine
`data-tab="<destination>/<onglet>"`) ; un onglet qui ne reconnaît plus ses blocs rend la main à la console ; les fiches, les épisodes, « pourquoi a-t-elle dit ça ? » et les
panneaux (réglages, comptes, demandes en attente) dans le même vocabulaire. Seules les vues de la Forge gardent le
rendu de la console : ses apps déclarent leur interface par un contrat. Les fiches d'un but, d'un réveil, d'une
conversation et d'une réponse Teams, d'une boîte aux lettres, d'un mail et d'un brouillon ont leur en-tête et leur
onglet principal dessinés (`app/handmade/fiches.py`, gabarits `handmade/fiches/`) : ce qui compte d'abord (où en est
le but et son plan, ce qu'un réveil fait faire et sa clé, le fil en bulles, ce qui partira en face du message), les
formulaires que la console a préparés à leur place, leurs autres onglets bloc par bloc. Les pages de détail ont
chacune leur gabarit (`inspector/templates/handmade/`, inclus comme un panneau, leurs blocs au repli ou quand une
liste est demandée en tableau) : un épisode et ses sept onglets (`episode/`), un événement (`evenement/`), « pourquoi
a-t-elle dit ça ? » et « pourquoi n'a-t-elle pas répondu ? » (`parole/`), la recherche (`recherche/` : « Tout », une carte par sorte avec ses premiers liens, puis une section par sorte, en sous-onglets).

## Page par page

### Accueil

Dessiné à la main (`app/handmade/home.py`), il répond à trois questions et se relit seul (le fragment
`/inspecteur/_accueil`, `handmade/live.js`) :

- **Ce qui t'attend** : une ligne par page où décider (chaque onglet qui demande une action : accords en attente,
  brouillons, revendications…), puis les réponses en échec, *aucun modèle configuré*, les processus en échec
  d'affilée, les anomalies, la sauvegarde à faire et les contrôles de santé qui ne passent pas ; chacune mène à sa
  page et dit pourquoi. Un contrôle de santé mène à la page où regarder (« Système › File de sortie », la table
  `DESTINATIONS` de `inspector/pages/diagnostics.py` ; la santé générale s'il n'en a pas) : avec le badge de cette
  page, la même panne ne fait qu'une ligne (la plus grave, à gravité égale la plus précise), et la santé générale, qui
  compte ces contrôles, ne la répète pas. Le total de la file dit ce qu'il compte (« courriers à envoyer : 3 · autres
  demandes : 2 »).
- **Comment elle va** : son humeur en mots, son corps (son état — éveillée ou endormie, depuis quand —, son énergie,
  où elle est, ce qu'elle fait), ses besoins (sous leur titre, avec ce que mesure leur pourcentage : leur tension),
  qui est là (les lectures d'« En ce moment »).
- **Sa journée** : la journée en chiffres et ses huit derniers épisodes. Les courbes des 24 heures sont sur
  « En ce moment ».

### Sa rubrique

- **En ce moment** (`/inspecteur/maintenant`, `app/handmade/now.py`) répond à « comment va-t-elle, et pourquoi ? »
  en croisant ses facultés au même instant que son prompt : son humeur en mots et sur le plan plaisir × éveil, ses
  24 dernières heures sur un seul axe (humeur, énergie, sommeil, besoins, paroles et pensées), son corps, ses
  besoins, ses pensées, les gens, le fil de sa journée, ce qu'elle entreprend et la journée en chiffres. Elle se
  relit toutes les 20 s ; une lecture qui échoue tait sa carte.
- **Humeur, Postures, Besoins, Sommeil et rythme, Monde et corps, Estime et récit, Qui elle devient**
  (`app/handmade/tabs/life.py`, ADR 0177) : des vues d'elle — un bandeau au plus, une bande de chiffres, puis des
  tuiles. Humeur : son humeur en grand (le mot, le mélange, ce que son prompt lui en dit, le plan plaisir × éveil et
  sa trace sur la période), puis sa valence à côté de ses dernières balises, chacune avec ce qu'elle a dit.
  Postures : une carte par personne (ce qu'elle ressent, la chaleur de part et d'autre du milieu, l'hostilité,
  l'attachement, ce qu'elle s'en dit), un bandeau si elle en veut à quelqu'un. Besoins : ses trois besoins côte à
  côte, leur courbe, ce qui se passe ; ses règles repliées. Sommeil et rythme : sa journée sur 24 heures (ses
  phases et leur teinte, sa nuit, maintenant) à côté de l'énergie et de la pression de sommeil, ses nuits et ses
  transitions. Monde et corps : ce qui est en route pas à pas, les choses rangées par où elles sont, ce qu'elle a
  remarqué des éditions. Estime et récit et Qui elle devient passent en sous-onglets (son estime sur son échelle,
  son récit, sa persona, son tempérament par famille ; ce qu'elle sait d'elle, ce qui la passionne, ce qui la
  définit, ses changements d'avis) ; persona et tempérament se règlent dans Réglages.
- **Pensées, Ce qu'elle remarque, Attentes, Journal et rêves** (`app/handmade/tabs/thoughts.py`, `nights.py`) : une
  bande de chiffres, puis des sous-onglets — maintenant, l'historique (une page plus ancienne ouvre son sous-onglet),
  les règles. Pensées : ce qui lui trotte dans la tête, la plus forte d'abord, chacune de la couleur de son émotion,
  ce qu'il en reste et d'où elle est née. Ce qu'elle remarque : ce qui attend d'être remarqué, puis chaque signal, la
  pertinence annoncée et celle retenue sur une même barre (l'habituation se voit). Attentes : de qui, le temps qui
  court vers l'échéance en jauge, puis les attentes closes en fil. Le journal et les récits de ses nuits se lisent
  comme des documents.
- **Mémoire** (`app/handmade/tabs/memory.py`) : Souvenirs, Croyances, Promesses, La vie des autres, Voir venir,
  Consolidation, Pièces reçues, Fichiers envoyés. Les éléments retenus se lisent en listes à filets, deux colonnes
  sur un grand écran, leur détail replié ; chacun met en avant ce qui le distingue : la confiance et l'origine d'une
  croyance ; l'échéance d'une promesse (en retard : dit ; tenues et abandonnées côte à côte) ; la date d'un moment,
  en agenda (en ce moment, à venir, passés et comment ça a tourné — lu dans l'archive de la faculté, même pour un
  moment passé depuis longtemps). Pièces reçues (ADR 0182) : la place en chiffres, puis
  en sous-onglets les pièces (sa sorte, ce qu'elle y a lu, ce qui s'y relie, la télécharger, la retirer) et leur
  place, une jauge par personne ; l'ancienne adresse de la place (`memoire/place`) y mène. Fichiers envoyés (ADR 0205,
  vue `envoyes` de `shares`, à côté) : ce qu'elle a envoyé à tout le monde, du plus récent — sa sorte, pour qui, son
  origine, le message qui l'a emporté (« pas parti » sinon), son état ; le télécharger, le retirer. « Retirer »
  (`shares.retirer`, `attachments.retirer` : confirmé, audité ; aussi sous « ⋯ » sur la fiche du fichier ou de la
  pièce) efface ses octets ; sa ligne reste, estompée, « retiré(e) par un opérateur », et ce qu'elle en a lu reste.
  Voir venir : ses attentes sur une échelle de « toujours juste » à « pile ou face », et qui tient ce qu'il annonce.
  La consolidation dit où en est la relecture en une phrase et une bande de chiffres, puis en sous-onglets les
  passages à reprendre (leur reprise sur leur ligne), ses relectures, les tris de la nuit et l'état détaillé.
- **Constellation** (`/inspecteur/constellation`, `app/constellation.py`, ADR 0103) : sa mémoire en une boule de
  points, chacun près de ses voisins de sens, et ce qui la parcourt en direct (une parole et sa provenance, un
  élément qui naît, la nuit, un rêve et ses sources).

### Relations & échanges

- **Personnes** (`/inspecteur/personnes`, `app/handmade/people.py`) : une carte par personne — ce qu'elle est pour
  elle, ce qu'elle ressent, ce qui se passe entre elles, ce qu'elle en sait —, qui est là, qui lui manque, une
  recherche et des filtres (proximité, en ligne). Ses onglets, les mêmes sur ses quatre pages : Vue d'ensemble
  (cette page), Annuaire, Liens, Présents — la destination déclare ce premier onglet dessiné à part
  (`Destination.lead`), ses autres onglets y ramènent. Ses onglets (`app/handmade/tabs/people.py`) disent une
  personne comme la vue d'ensemble : **Annuaire**, une entrée par personne — ses moyens de communication (le
  principal d'abord, ce que chaque canal prouve), la certitude, depuis quand, son dernier message, leurs échanges et
  leur lien ; **Liens**, un bandeau si quelqu'un lui manque, la bande de chiffres, puis les liens par proximité
  (proches, amitiés, connaissances, pas encore de lien) — l'échelon déclaré ou vécu, le rythme, le silence sur une
  jauge (à sa moitié, elle lui manque), ce qu'elle en sait ; **Présents**, une entrée par personne présente et, sous
  elle, chacune de ses connexions (par où, le moyen de communication, l'audience).
- **La fiche d'une personne** s'ouvre sur sa **vue d'ensemble** (`app/handmade/person/`) : ce qu'elle ressent
  envers elle, leur histoire, ce qu'elle sait d'elle, ce qui reste en suspens, leurs derniers mots. Les onglets des
  facultés suivent, dessinés sur leurs données (Échanges en conversation, Mémoire en cartes, les listes en
  cartes) ; ce que la vue d'ensemble résume (Synthèse, Lien, Ce qu'elle devine, Affect, Pensées) est rangé au bout
  de la barre, sous « Le détail ». L'onglet **Fichiers** (`app/handmade/person/files.py`, ADR 0179) réunit en
  deux sous-onglets ce que la personne lui a envoyé (sa place, chaque pièce et ce qu'elle y a lu, ADR 0106) et ce
  qu'elle lui a envoyé (ADR 0062), une page par fichier, téléchargement opérateur, et « Retirer » sur chaque fichier
  encore là (ADR 0205 : confirmé, audité ; ses octets s'effacent, sa ligne reste et dit « retiré par un opérateur »,
  ce qu'elle en a lu reste) ; l'ancienne adresse des pièces reçues (`?onglet=pieces`) y mène (`Overview.joined`). **Son téléphone** et **Sa position** n'apparaissent que si
  elle en a (`@f.inspect(..., shown=)`) ; **Comptes** non plus (ADR 0185, 0186) : en sous-onglets, les boîtes aux
  lettres qui sont à elle (ses propriétaires : celles sans propriétaire nommé), chacune avec son état, sa voix, ses
  non-lus, « Ouvrir la boîte » (le Courrier, réduit à ses boîtes), puis ses comptes Teams (leur état, le dernier
  envoi de l'extension, leurs conversations) — réunis (`joined`) —, les services qu'elle a branchés depuis son espace
  (ADR 0192 : à quoi chacun sert, actif ou non, avec qui il est partagé, sa fiche) et ses partages (ADR 0188 : ce
  qu'elle partage, ce qu'on lui partage — la ressource, la personne, le niveau), lus dans les réglages, en lecture
  seule ; sans boîte, Teams est un onglet à lui, et la fiche ne montre ni ses services ni ses partages. **Voyages**
  n'apparaît aussi que si elle en a (`app/handmade/person/voyages.py`, ADR 0204) : chacun de ses voyages, du plus
  récemment changé — son titre, comment on s'y déplace, s'il a été préparé avec elle, son départ, ce qu'il évite, ses
  jours et ses arrêts, sa création au journal —, ses arrêts jour par jour, repliés (sorte, note, coordonnées,
  « ajouté par » elle sous son nom), son GPX (servi par la console aux opérateurs, `/inspecteur/voyages/<id>/gpx` ;
  son tracé compte dans la borne des trajets de l'écran Carte, sur le compte de l'opérateur : 20 par minute, puis
  un 429 qui le dit) et « Supprimer » (`trips.supprimer`, confirmé, audité ; le dernier supprimé, la fiche revient sur
  sa vue d'ensemble) ; rien ne s'y modifie : un voyage se prépare à deux. Quand un de ses moyens de communication est un
  compte, l'en-tête le dit (« compte utilisateur » ou « compte opérateur ») et mène à sa page (« Modifier le
  compte », Réglages › Comptes).
- **Conversations** (ADR 0181) s'ouvre sur **Par personne** (`app/handmade/tabs/threads.py`), comme une messagerie :
  une ligne par personne, tous ses moyens de communication réunis, la plus récente d'abord, vingt-cinq par page — son
  avatar à la couleur de ce qu'elle ressent envers elle et sa présence, ce qu'elle est pour elle, l'heure, le dernier
  message (« elle : » s'il est d'elle), les questions qui attendent sa réponse, combien de messages et par où ; un
  filtre par nom ou moyen de communication, et un par mot dit (là où mène la recherche : les conversations où il a
  été dit, chacune avec ce message-là) ; la ligne mène à l'onglet Échanges de sa fiche (au fil du moyen de
  communication pour une inconnue de passage), où leur conversation se lit les plus récents en premier. Puis
  **Questions sans réponse**, chacune dans sa bulle avec depuis combien de temps elle attend (une heure : dit ; un
  jour : en alerte), le message source et leur conversation sur sa ligne ; **Ses réponses jugées**, les avis de
  l'opératrice (ADR 0113). L'ancien fil de tous les messages n'est plus une page : son adresse (`fil/messages`) mène
  à Par personne, son filtre gardé.
- **Courrier** : Réception et Envoyés en boîte aux lettres (une ligne par message, douze par page, une case pour la
  cocher ; le message ouvert dans une liseuse, `?lire=`, à côté de la liste dès que la place le permet, dessous
  sinon, avec le précédent et le suivant — j, k, Échap — et, en tête, ce qu'elle en sait), Brouillons (« À décider »
  en enveloppes : à qui, depuis quelle boîte et dans quelle voix, en réponse à quoi, d'où il vient ; « Déjà décidés »
  en lignes), Contacts (une ligne par adresse, « Ses échanges » et « Écrire »), tous dans le même espace : à côté, ce
  qu'on lit (Réception, À traiter, Suivis, ses brouillons, Envoyés, Contacts — à la place des onglets, que la page
  tait), à qui sont les boîtes montrées (« Les boîtes de » : tout le monde, toi, elle par son nom, chaque personne
  qui a une boîte — `?qui=`, ADR 0185), les comptes et leurs dossiers ; au-dessus, écrire, actualiser et chercher. La
  barre de la liste range ce
  qu'on a coché, sur le serveur (lu, non lu, archiver, suivre, corbeille) ; « Charger des messages plus anciens » est
  au bout de la liste. « Non lu » est le tien (le drapeau du serveur) ; ce qu'elle a lu ou rangé se dit à part
  (« lu par elle »), ADR 0175. Les fiches dessinent aussi leurs onglets secondaires : la boîte › Sa voix (les trois voix, l'expéditeur
  tel qu'il partira, la signature, le texte qu'elle lit), le mail › Fil (en bulles, reçus à gauche, partis à droite)
  et Ce qu'elle en sait, le brouillon › Pourquoi (le mail auquel il répond, les consignes) et Historique (le parcours,
  les deux versions) ; un brouillon disparu de la boîte garde une fiche qui dit ce qu'elle en sait. Le compte, le dossier et les filtres se
  gardent dans la pagination et au retour d'un message ; consulter n'envoie rien et ne marque rien comme lu, sauf
  si le réglage « Ouvrir un mail le marque lu » le demande (le script de la console envoie « Marquer comme lu »). Un
  mail HTML se lit tel qu'il a été écrit, avec ses styles, dans un cadre isolé (ADR 0169) : ni script, ni
  formulaire, ni image distante (son texte de remplacement à sa place), sauf si on les affiche pour ce mail ou
  « Toujours pour cet expéditeur » (ADR 0175) ; ses images intégrées (`cid:`) s'y montrent (ADR 0172) ; ses liens web et `mailto:` s'ouvrent dans un nouvel onglet ; sa version texte reste accessible ; un
  message long se lit en parties de 50 000 caractères au plus. Ses pièces jointes se téléchargent depuis le cache,
  sans le serveur ; un mail relevé avant qu'elles soient gardées le dit, et « Récupérer ses pièces » le relit. Les brouillons
  qu'elle propose sont distingués de ceux du serveur. **Paramètres**, le bouton en haut à droite (pas un onglet,
  ADR 0173), une section à la fois (une colonne de sous-onglets à gauche, des ancres ; ce qui est masqué part quand même
  avec le formulaire, et la section ouverte se retrouve après l'enregistrement, ADR 0176) : ses boîtes en cartes (où chacune en est, comment elle lit et envoie, sa voix, son dernier relevé), une
  boîte sur sa page (la boîte, la connexion, lire, envoyer, sa voix, chacun à côté de ce qu'il règle ; ce qui ne sert
  pas au choix fait ne paraît pas, et une adresse courante propose ses serveurs, ADR 0174), puis les paramètres
  généraux du courrier (relevé, ce qu'elle en dit, ses brouillons, la lecture). L'ancienne adresse, Réglages › Plugins › Boîtes
  aux lettres, y mène.
- **Teams** (ADR 0069, `app/handmade/tabs/teams.py`) : Conversations, comme une messagerie (le dernier message,
  l'heure, une question sans réponse, une réponse en chemin ; sans extension, comment la brancher) ; Réponses, celles
  qui attendent ton accord d'abord, chacune en face du message auquel elle répond (« Examiner et décider »), puis ce
  que les autres sont devenues ; Extension, où elle en est, ses chiffres (chacun mène à son onglet), ton compte
  Teams, la brancher pas à pas. Un compte par personne (ADR 0186) : chaque onglet commence par « Les comptes de »
  (tout le monde, toi, elle par son nom, chaque personne qui a un compte Teams, `?qui=`), puis « Comptes » s'il y en a
  plusieurs (`?compte=`) ; les conversations disent leur compte quand plusieurs sont mêlés. Extension : un compte par
  ligne (à qui, clé, dernier envoi), ou le compte choisi — ses chiffres, sa clé (Nouvelle clé, Retirer la clé), le
  pas-à-pas, comment ses réponses partent : le tableau de ce compte (Réglages › Canaux, `?canal=teams:<clé>`), et sa
  voix et sa signature, « Modifier ce compte » (ses réglages, qui ramènent à son extension : son compte et sa clé côte
  à côte). La fiche d'une conversation d'un autre compte est `conversation_teams/<compte>~<id>`. **Paramètres**, le
  bouton en haut à droite (pas un onglet, comme le Courrier, ADR 0206) : « Actif », puis ses comptes en cartes (ADR
  0186) — à qui, actif ou non (décoché : son extension est refusée), son nom, son ton, sa signature ; la clé de chacun
  se crée dans l'onglet Extension (un fait de la page y mène, un autre au tableau de Teams dans Réglages › Canaux) ;
  supprimer un compte efface ce que son extension avait apporté. L'ancienne adresse, Réglages › Plugins › Teams, y
  mène.
- **Identités et moyens de communication** (`app/handmade/tabs/identities.py`) : Moyens de communication (un
  bandeau quand une revendication attend, qui mène à la file « À valider », la bande de chiffres, une ligne par moyen
  en colonnes : par où, ce que le canal prouve, pour qui il parle, ce qu'il ouvre en privé et en public) ; Règles de
  divulgation, une page de règles : les barres en chiffres, ce que chaque canal peut prouver sur une même échelle de
  certitude, le poids des preuves pour et contre, les rangs de proximité, les propriétaires. Les identités à
  confirmer et les noms à relier n'ont pas d'onglet ici : ils ne se décident que dans la file (ADR 0180), et leurs
  anciennes adresses y mènent.
- Dans la console, une *adresse* (une identité qui parle pour une personne : un compte, un téléphone, un compte
  extérieur) se dit **moyen de communication** ; les clés techniques restent (l'onglet `adresses`, le paramètre
  `handle`). La fiche d'un moyen de communication (`fiche/handle/<clé>`) s'ouvre sur **En bref**
  (`app/handmade/handles.py`) : quatre tuiles (par où, ce que le canal prouve, si elle peut lui écrire d'elle-même,
  son dernier message), *Le canal*, *Qui écrit d'ici* (pour qui il parle, ses droits de propriétaire, ses autres
  moyens), *Ce que ça ouvre* (une ligne par sorte de chose, en privé et en public, et pourquoi), le verdict pas à pas
  replié. Son *Fil* est en bulles ; *Verdict* et *Ses autres moyens de communication* passent sous « Le détail » ;
  *Revendication* ne se montre pas pour un compte authentifié.

### Activité

**Projets** (ADR 0031, 0133) : un projet est une boîte noire qu'on pilote, distincte d'un but.

Ses onglets sont dans `app/handmade/tabs/projects.py` (ADR 0177).

- **Ses projets** : ses chiffres (ce qui attend ton accord en tête quand il y en a), puis une liste, une rangée par
  projet sous des colonnes nommées : son nom et où il en est (une ligne), mode (Mika ou impersonnel) et état,
  objectifs en jauge, prochaine et dernière exécution, pour qui ; priorité, plage de travail, agenda, outils, dépôt
  distant et ce qui sort se déplient sous la rangée (la flèche à son bout). Sur un écran étroit, la rangée s'empile
  et nomme ses valeurs. « Créer un projet » est dans la barre de titre et a sa page : le projet, ses objectifs (un
  par ligne, ponctuels et constants), son mode et ses outils, son rythme et sa plage, sa liberté, son dépôt distant.
- **Exécutions** : ce qui tourne en ce moment, puis le fil jour par jour (filtrable par projet et par verdict) :
  projet et objectif visé, verdict et preuve, compte rendu, commit ; chacune mène à son épisode (prompt, outils,
  appels, décision).
- **Décisions techniques** : rangées par projet (filtrables par projet et par statut), chacune avec sa question, ce
  qui est choisi, pourquoi, qui l'a posée et quand ; une décision remplacée s'estompe.
- **La fiche** gouverne, onglet par onglet ; ses onglets disent leur compte (objectifs, exécutions, décisions), Accès
  et Carnet sont rangés sous « Plus » ; en tête, la principale (« Lancer maintenant », ou « Reprendre » en pause) et
  « Donner une consigne », le reste sous « ⋯ ». *Vue d'ensemble* (dessinée, `app/handmade/projects.py`, ADR 0177 : la
  vue d'un objet de la maquette — un seul bandeau : ce qui attend ton accord, « Les décider » ouvrant la file des
  validations, sinon sa pause ou ce qui le retient ; une bande de chiffres « Où il en est », ses dernières exécutions
  en barres ; son plan et sa réponse ; puis des tuiles qui mènent à leurs onglets : ses objectifs, ses dernières
  exécutions, ses décisions en vigueur, son cadre, sa prochaine exécution, son dépôt) · *Objectifs* (dessiné,
  `app/handmade/projects.py` : ses chiffres, puis une entrée par objectif — son numéro, ce qu'il vise, sa sorte et son
  état, son rythme et qui l'a posé, son dernier compte rendu en citation (long, quatre lignes que « lire la suite »
  déplie) et ce qu'elle en a tiré ; ses boutons sur sa ligne, deux en vue (le lancer, le premier statut), « Modifier
  l'objectif » en panneau, le reste sous « ⋯ » ; un constant ne se coche pas ; « Ajouter un objectif » en colonne à
  côté de la liste sur un grand écran) · *Exécutions* (issue, verdict, preuve, commit,
  durée) · *Décisions* (dessiné, comme *Objectifs* et sur les mêmes pièces, `handmade/projets/_fiche.html` : une entrée par
  décision — la question tranchée et son statut, ce qui est choisi, pourquoi en citation, le contexte et les options
  envisagées repliés, qui l'a posée, quand, ce qu'elle remplace ; sur sa ligne, la retirer ou la remettre en vigueur
  et « Remplacer cette décision » en panneau ; remplacée ou retirée, elle s'estompe ; « Consigner une décision » en
  colonne à côté) · *Fichiers* (dossiers à parcourir, lire,
  télécharger, déposer) · *Dépôt git* (dessiné, `app/handmade/project_git.py`, ADR 0183 : un seul bandeau — un
  envoi qui attend ton accord, GitHub qui ne répond pas, ou les deux histoires qui ont divergé ; l'atelier et son
  dépôt distant face à face, l'atelier avec sa branche, son dernier commit et ce qui n'est pas enregistré, le distant
  avec son hôte, le bout de sa branche, ses issues et pull requests et quand il a été lu ; entre eux l'écart (à
  pousser, à récupérer) et « Pousser maintenant », « Récupérer », « Relire », le geste qui comble l'écart en avant ;
  puis des sous-onglets : l'historique paginé, ceux qui restent à pousser marqués, un commit ouvert en diff coloré
  au-dessus ; ce qui n'est pas enregistré ; l'histoire du distant, ceux à récupérer marqués ; ses issues et ses pull
  requests ouvertes, qui s'ouvrent sur GitHub ; les échanges passés et ce que git a répondu ; les réglages du
  distant) · *Comportement et outils* (modifier le projet, ce que veut dire son
  mode, son rythme, ses outils et leurs noms) · *Accès* (dessiné, ADR 0133, `app/handmade/projects.py` : un tableau
  de lignes lues de haut en bas — qui et par où (les mêmes cases qu'un service), quand, voir, piloter projet (lecture seule, accord du propriétaire, modification, aucun pilotage), fichiers, ce qu'elle fait d'un outil de ses apps qui lit et d'un
  outil qui agit, à quels outils —, « + Ajouter un accès » (une ligne fermée), chaque ligne montée, descendue ou
  retirée, la dernière, obligatoire, le comportement par défaut ; jamais réglé, il le dit) · *Carnet* (consignes,
  ses notes, ce qu'on en a fait, ce qui sort de la machine). En tête : lancer maintenant, pause, reprendre, consigne, archiver, restaurer — les formulaires
  d'onglet (`inline`) et les actions de ligne n'y sont jamais.

**Buts et rappels** (`app/handmade/tabs/goals.py`) : les buts vivants, leurs chiffres, puis côte à côte ses
explorations (séances sur leur plafond, envie qui s'use) et ses rappels (chacun à sa date, le plus proche d'abord) ;
les buts clos, leur issue en marque et ce qu'ils ont donné, en deux colonnes. La fiche d'un but : Résumé, Cadre
et réglages, Séances, Carnet, Décisions, Épisodes et prompts ; elle pilote (ADR 0030) : modifier le cadre,
avancer maintenant, rouvrir, priorité, plan de travail. Sa prochaine séance (quand, ou ce qui la retient : la nuit,
le plafond de l'heure, une séance en cours ; rien pour un rappel, un but clos ou en pause) se dit d'une seule règle
(`goals.inspect.next_session`), la même dans l'en-tête, la liste et la fiche ; la fiche dessinée la lit dans
l'en-tête de la faculté.

**Décisions** (`app/handmade/tabs/decisions.py`) : une ligne de l'arbitre se lit partout de la même façon — ce qui
pousse face à ce qui retient sur une barre, l'équilibre au milieu, le score ; ce qui l'en empêche ; combien de fois
par heure elle agirait ; le calcul pas à pas, replié. Les barres se tirent de la vue seule (ni l'arbitre ni le
journal relus à côté) : chaque ligne porte son calcul pas à pas (chaque preuve, modulation, seuil et veto, avec son
apport) et, repliés, sa sorte, sa cible et le rythme maximal de la sorte ; un taux s'écrit à trois chiffres
significatifs, pour qu'un taux faible ne se lise pas zéro.

- **Table de l'arbitre** : une phrase (elle agirait en moyenne dans…, ou rien et pourquoi), ses lignes de la plus
  probable à la plus bloquée ; « Comment elle décide » (le seuil et le rythme maximal de chaque sorte), replié.
- **Que ferait-elle ?** : sans personne, les personnes dont une ligne existe, en puces ; pour une personne, son
  verdict en grand, ses lignes, ce qui vise n'importe qui de présent (replié) ; la fiche d'une personne y mène.
- **En cours** (`app/handmade/running.py`) : une phrase sur ce qu'elle fait (« elle répond à Adrien depuis 12 s »,
  ou rien et son dernier épisode), ce qui tourne en arrière-plan ; ce qui attend (chaque voie, ses places occupées
  et sa file, les questions sans réponse, les actions à autoriser, les ressources réservées) ; ses huit derniers
  épisodes, chacun vers sa page. Le relevé est daté, avec un lien pour l'actualiser.
- **Initiatives** : son budget du jour en cases, sa période de recul, les initiatives restées sans réponse, ce qui
  retient ses initiatives ordinaires ; ce qu'elle a dit d'elle-même, répondu ou non ; ses règles et les initiatives
  comptées sur 24 h.
- **Ses choix** : chaque initiative décidée, le tirage, la roue des lignes en lice (la part de chacune, la choisie
  en couleur). **Épisodes** (filtres sorte, issue, cible) : ses 24 h par issue et ses 14 jours en barres, puis le
  fil jour par jour. **Échéances** : ce qui échoue d'affilée en tête, puis par horizon (dans l'heure, aujourd'hui,
  plus tard) ; « rien de prévu » replié.

**Un épisode** a sa page, en onglets, chacun dessiné : Résumé (son issue en grand, le message déclencheur en bulle,
ses dernières paroles, ses chiffres en tuiles — durée, paroles, événements, appels et leur coût, outils —, lu dans le
journal sans rien lancer, par la même lecture que ses blocs, `episode_overview.summary`), Déroulé (ses événements sur un fil, à la seconde), Ce qu'elle a dit (ses paroles en
bulles, leur voix, leurs outils, leurs sections), Prompt (ce qui l'a décidé, ses sections dépliables sur leur texte,
le contexte complet, ses outils en main, sa réponse pas à pas jusqu'à l'autrice), Outils (un appel par carte, ses
arguments à côté de son résultat), Appels de modèle (leurs totaux, puis leur tableau), Décision.

**Un événement** (`/inspecteur/evenement/<n>`) : ses repères, ses textes (en bulle pour une parole ou un message), son
parcours dans la machine (qui le réduit, ce qu'il réveille, qui le projette), qui il concerne, les épisodes qu'il a
déclenchés et leur issue, ses données brutes repliées.

**Pourquoi a-t-elle dit ça ?** (ADR 0042) : une page par parole (`/inspecteur/parole/<seq>`), liée depuis le fil,
l'onglet « Échanges » d'une personne, chaque épisode et chaque événement de parole. Elle est dessinée
(`handmade/parole/parole.html`, ADR 0121 ; ses blocs au repli) : ce qu'elle a dit, en grand, avec ce qu'elle
ressentait en le disant (sa balise) et ce qu'elle lisait chez l'autre ; ce qui l'a fait parler (le message, ou la
ligne exacte de l'arbitre pas à pas) ; sa réponse pas à pas — le texte brut du modèle principal, la relecture,
l'autrice (son contexte, sa réponse, retenue ou écartée et pourquoi), ce qui est parti ; son humeur à ce moment-là
(les sections affectives de son prompt, telles qu'envoyées) ; ses outils en main et ceux qu'elle a appelés, avec
leurs résultats ; ce dont elle s'est souvenue, avec le texte ; les sections de son prompt, nommées, chacune
dépliable sur son texte, et le contexte complet tel qu'envoyé ; l'avis de l'opératrice (« Ton avis »). Les clés
techniques sont dans « Détails techniques ».

- « Rejouer avec… », sur cette page et dans l'onglet « Prompt » d'un épisode : le prompt gardé (la trace, 14 jours)
  renvoyé tel quel à un fournisseur déclaré, par `Gateway.try_on` — un seul appel, derrière tout le fond, sous le
  rôle à part `trial` (Système › Appels et coûts ne le mêle pas à « répondre »). La page montre côte à côte ce
  qu'elle a vraiment dit et ce que l'autre modèle répond, avec durée, jetons et coût ; un appel d'outil est
  affiché, jamais exécuté, et la CLI de Claude Code reçoit le prompt sans ses outils (elle le dit). Rien n'est
  livré, rien n'entre au fil ni dans sa mémoire, rien n'est gardé au-delà de la page : seule une ligne
  `runtime.operated` (`console.rejouer`, sujet : l'épisode) entre au journal, avant l'envoi. Une trace tronquée ou
  expirée désactive les boutons ; un prompt servi en local qui partirait vers un service hébergé est signalé avant
  l'envoi (il mêle les personnes).
- La même adresse, avec le numéro d'un message reçu resté sans réponse, répond à « Pourquoi n'a-t-elle pas
  répondu ? » : la fin d'épisode qui l'a réglé et sa cause en mots (un silence choisi, ce qui l'a fait taire, trop
  tard, une panne), puis ce qu'elle avait sous les yeux et ses outils, ou l'appel de modèle en échec.

### Outils (ADR 0064, 0122, 0123, 0128, 0129, 0130, 0131, 0133)

- **Ce qu'elle peut faire** (`outils/tous`, `?q=`, `?lot=`, `inspector/pages/families.py`, ADR 0134) : ses outils
  internes, une famille (un lot) par sous-onglet, son nombre d'outils dans la colonne (ADR 0176) ; filtrée (`?q=`,
  `?lot=`), les familles qui répondent l'une sous l'autre. Chaque outil avec sa description (lit ou agit, le lien de sa
  fiche), puis le tableau de la famille (`handmade/droits/tableau.html`), ouvert dans son sous-onglet (filtrée :
  « Régler les droits » l'ouvre) — qui,
  par où, quand, un outil qui lit, un outil qui agit, ce qu'elle en garde, ses outils —, né du minimum vital que le
  code déclare (`owner_only` : à toi et elle seule ; sinon à tout le monde et elle seule), modifiable ; « Revenir au
  minimum vital » ; un avertissement quand un tableau descend en dessous. Une case grisée (🔒) dit ce que l'outil ne
  sait pas faire (attendre un accord) ou ce qui n'a pas de sens pour lui (garder ce qui est déjà à elle). `?famille=`
  ouvre un tableau ; chaque bouton envoie tout le tableau (`/outils/familles/regler`). Dans un dernier sous-onglet
  (filtrée : dessous, replié), le texte exact que son prompt porte sur ses outils, situation par situation. `?outil=<nom>` ouvre sa fiche : où elle peut s'en
  servir, par ses droits (le tableau de sa famille, ou de son service ou de son app), ses arguments, ses derniers
  appels. Ce qui vient d'ailleurs (un service, une app) a ses tableaux sur sa propre fiche.
- **Venus d'ailleurs** (`outils/serveurs`, l'onglet du plugin MCP) : les services branchés (à qui — elle, ou la
  personne qui l'a branché sous son compte, vers sa fiche, ADR 0192 —, état, outils servis / proposés, à revoir, avec
  qui et ses accès — badge et vitale), « À qui » en bouton à choix quand plusieurs en ont branché (tout le monde, elle,
  chaque personne, `?qui=`), puis les outils que ses apps lui donnent (la vue de la Forge, dessous). Brancher un service : à quoi il lui sert, comment le joindre ; il est fermé tant qu'aucune ligne
  d'accès ne l'ouvre. Un service d'une personne porte « à <son nom> » à côté du sien. La fiche d'un serveur a trois
  onglets : *En bref* (son état, ses outils servis, à revoir, ses
  appels ; ses lignes d'accès d'un regard ; ce qu'elle en lit ; *qui peut quoi* — ses outils servis devant toi, toi
  quand elle te parle d'elle-même, chaque personne que nomme une ligne, un proche, un autre compte, quand elle
  travaille seule, et ce qu'elle en garde, par la règle du moteur ; pour qui et quand ; le côté technique replié), *Accès aux
  outils* (dessiné, ADR 0131 : un tableau de lignes lues de haut en bas comme les règles d'un pare-feu — qui (des
  sources à cocher : toi, tes proches, tout le monde, elle par son nom, puis chaque personne qui a un compte, ADR
  0133, 0184), par où (des canaux à cocher : tous, un type, une instance ; « elle seule » pour elle, cochée seule,
  ADR 0134, 0184), quand
  (toujours, ou des moments à cocher), politique de lecture, d'action, de mémorisation, ses outils —, « + Ajouter un accès aux outils » en haut à droite,
  chaque ligne montée, descendue ou retirée ; dernière ligne, obligatoire, le comportement par défaut), *Ses outils*
  (dessiné : « À regarder », un choix par outil nouveau ou changé — coupé, lecture, action —, puis ce qui lit et ce
  qui agit, chacun avec ce qu'il fait devant qui d'après ses lignes ; une ligne se déplie sur son réglage — servi, lit
  ou agit, ce qu'elle lit de lui ; `?outil=` l'ouvre ; un outil changé est suspendu) ; sous « Le détail », *État* (ce
  qui a été déclaré, ce qu'il répond, ce qu'il dit de lui-même — jamais lu par elle —, « Tester la connexion ») et
  *Appels* (pour qui, seule ou sur accord, l'issue, qui a décidé). La connexion se règle par « Modifier la
  connexion ». Une alerte dit un service qui ne sert à personne.
- **Paramètres des services**, la roue en haut à droite de Ses outils (ADR 0206 ; plus de bouton « Leurs réglages »
  à côté de « Brancher un service ») : chaque serveur a sa page — **à quoi il sert, pour elle** (obligatoire), quand
  s'en servir, actif ; à une adresse (URL, jeton scellé, autorité) ou sur cette machine (commande, arguments,
  variables, variables secrètes scellées, réseau, dossiers partagés) ; en main ; bornes (qui peut quoi : sur sa
  fiche, « Accès aux outils »). Nom fixe (il entre dans le nom de ses outils). ADR 0064, 0128, 0131.
- **Prêter à un agent** (`outils/expose`) : la console en lecture — créer, renouveler ou fermer son jeton (montré
  une seule fois, avec sa ligne `claude mcp add`), l'ouvrir au réseau ou l'y fermer (ADR 0126 : sa ligne prend alors
  l'adresse par laquelle on lit la console), choisir ce qu'elle montre (ses pages d'office et d'autres, ses
  vues, ses fiches, « pourquoi ») ; ses outils prêtés — des points `/mcp/pret/<nom>` à déclarer (`?nouveau`), régler
  (`?pret=<nom>` : lecture seule ou non, ses outils), renouveler et retirer, avec ce que chacun sert et ses derniers
  appels ; replié en bas, le relais MCP du moteur Claude Code (lu).
- Les anciennes pages mènent ici : `outils/qui`, `outils/texte` → `outils/tous` ; `outils/outils_apps` →
  `outils/serveurs` ; `reglages/serveurs-mcp` (Réglages › Plugins › Outils extérieurs) → `outils/parametres`.
- **Apps forgées** : le catalogue en tuiles (`app/handmade/tabs/apps.py`), comme un lanceur — titre vers la fiche,
  nom, version et agenda, état (une app cassée : un trait rouge et sa raison), promue ; recherche par nom ou titre,
  bascule « Tableau » ; la fiche d'une app : État, Vues, Réglages, Code,
  Base, Journal, Vécu. Les commandes de maintenance sont sur État et Code ; Vues garde les actions de l'app,
  Réglages sa configuration.

### Connexions extérieures

- **Flux RSS** (`sens/flux`, `app/handmade/tabs/senses.py`) : la phrase d'état du relevé, un flux en panne en
  bandeau, la bande de chiffres ; en sous-onglets les derniers articles (pertinence, résumé), ses flux (état, dernier
  relevé replié), ce qu'elle a remarqué (courbe des jours), ce qui lui a fait penser à ses amies, les mots qui la
  touchent. Recherche dans les titres et résumés.
- **Caméra** : ce qu'elle voit, appareil par appareil, à côté de ses appareils (en direct ou silencieux, dernière
  image — jamais l'image), puis ses regards au journal.
- **Dessins** : la bande de chiffres, puis un dessin par entrée — où il en est, pour qui (son nom), ce qu'elle a
  demandé, ce qu'elle y voit ou pourquoi il a raté.
- **Appareils** (le jeton des appareils) : ses appareils à gauche (chacun filtre la page), ce qu'ils lui ont signalé
  à droite.
- **Les réglages de Ses sens** sont derrière sa roue, en haut à droite de chacun de ses onglets (ADR 0206) : un menu
  « Réglages » qui mène à **Flux suivis** (les adresses des flux RSS ou Atom), **Accès des appareils** (le jeton des
  appareils ; « Nouveau jeton » est l'action de la barre de titre, confirmée, le jeton montré une fois) et
  **Transcription vocale** (service, modèle, clé) — la page de la roue allumée, les onglets de Ses sens à côté. Plus
  de « Configurer le plugin » dans la barre de titre de Flux RSS et d'Appareils : leur état vide dit où regarder. Les
  liens d'un onglet vers d'autres réglages ou une tâche restent dans sa barre de titre, avant la roue : les
  paramètres avancés de la caméra et « Connecter une caméra » (vers l'accès des appareils), les fournisseurs
  d'images et les paramètres avancés des dessins. Les anciennes adresses, Réglages › Plugins › Flux RSS, Appareils
  connectés et Transcription, y mènent.
- **Messages du téléphone** (`sens/messages`, `app/handmade/senses.py`, ADR 0120) : le téléphone de chaque personne,
  puis ses conversations (un contact, un groupe), repliées, qui s'ouvrent en bulles jour par jour ; huit
  conversations par personne quand on regarde tout le monde, toutes quand on en choisit une (`?personne=`, des
  puces) ; puis les réponses qu'elle a proposées et leur sort.
- **Localisation** (`sens/positions`, ADR 0119) : une ligne par personne, ses téléphones réunis (ses autres moyens de
  communication dépliés), puis ce que les téléphones lui ont dit, par pages (`?avant=`) ; le même filtre par
  personne.
- **Réveils par API** (ADR 0068, 0117, `app/handmade/tabs/wakeups.py`) : ses réveils en tuiles (actif, clé, en
  attente, dernier appel), puis leurs derniers appels en fil — ce qu'ils apportaient, pourquoi ils attendent, leur
  compte rendu, le reste replié ; « Déclarer un réveil » dans la barre de titre ; la fiche d'un réveil : État (sa clé,
  générée ici et montrée une fois ; comment l'appeler), Appels. **Paramètres**, la roue en haut à droite (ADR 0206) :
  chaque réveil a sa page — **à quoi il sert** (obligatoire), actif, consignes (elles priment sur le texte d'un
  appel, cité), projet, impersonnel, outils (lots), ignorer son rythme, à qui rendre compte, bornes ; nom fixe (la
  fin de son URL) ; « Modifier ses réglages », sur sa fiche, ouvre sa page et ramène à la fiche une fois
  enregistré. L'ancienne adresse, Réglages › Plugins › Réveils par API, y mène.
- **Dépôts Git** : le jeton avec lequel ses projets poussent vers leur dépôt distant (jamais réaffiché, jamais dans
  le journal).

### À valider

Une seule file pour tout ce qui attend une décision (ADR 0177), une seule page : ses onglets — **Tout ce qui
attend**, **Courriers à envoyer**, **Réponses Teams**, **Identités à confirmer**, **Noms à relier** — en sont des
filtres, puis **Historique des autorisations**. « Tout » et l'historique sont ceux de la console
(`inspector/pages/approvals.py`) ; les autres onglets et ce qui n'est pas une demande d'envoi (une identité à
confirmer, un nom à relier, lus dans les vues de la faculté d'identité) viennent de la composition
(`app/handmade/waiting.py`, `InspectorDeps.queue`). Ces deux vues sont hors de la navigation : la file est le seul
endroit où l'on en décide (ADR 0180). Courrier › Brouillons et Teams › Réponses restent dans leur destination pour
retoucher un texte ; l'accueil ne compte la file qu'une fois (son total, qui dit ce qu'il compte, onglet par
onglet), pas ses onglets ni ces vues (`UI.attention_items(distinct=True)`). Ce qu'une demande concerne (une personne, « projet n° 61 », « service
« agenda » », une app, un canal — « Teams », « courrier », « téléphone », jamais une personne) a un seul lecteur,
côté composition (`approval_sources.about`, que l'inspecteur reçoit par `queue.about`) : la file, la demande ouverte,
sa source et l'historique le disent pareil, et l'inspecteur ne nomme aucun plugin.

- **La file** : comme un courrier — la file à gauche, une
  ligne par élément (sa sorte en nom court — `CAPABILITY_LABELS`, `app/console.py`, sa phrase entière au survol et
  dans l'en-tête de la demande ouverte —, ce qu'elle veut faire, ce qu'elle concerne, depuis quand), qui défile
  dans son cadre, cinquante par page ; des puces par sorte quand il y en a plusieurs — sur « Tout », pas celles
  qu'un onglet garde déjà (les courriers, Teams : l'onglet y mène) ; « Toutes » sans compte (l'onglet le dit), la
  file comptée seulement quand une puce filtre ; la demande ouverte à droite (`?demande=`) : sa place dans la file
  et ses voisines, sa source en liens (le brouillon et la boîte d'un mail, la conversation et la réponse préparée
  d'une réponse Teams, le service, le projet, l'app, la fiche de la personne — « d'Adrien », élidé — et leur
  conversation : `app/handmade/approval_sources.py`, par `InspectorDeps.approval_sources`), ce qui partira
  exactement, avant les boutons — son aperçu quand la capacité en déclare un (un mail, une réponse Teams, un appel
  de service, une commande réseau ; un envoi au dépôt distant : le dépôt, la branche, le commit épinglé et les
  enregistrements que le distant n'a pas ; une récupération : ce qui arrivera), sinon ses arguments un par ligne
  (« nom : valeur ») —, la clé de la capacité et le JSON exact repliés sous « Détails techniques », une note
  facultative, approuver ou refuser ; dessous, son historique — l'épisode qui l'a proposée, les dernières décisions
  du même genre (accordées ou refusées, par qui, leur note, comment elles ont tourné) et le lien vers tout
  l'historique de ce genre (`?sorte=`). Après une décision, la suivante s'ouvre (la même quand elle doit être
  relue). Une demande bloquée dit pourquoi et désactive l'approbation ; l'accord porte sur l'empreinte du contenu
  vu ; seule la demande ouverte calcule son aperçu.
- **Une identité à confirmer, un nom à relier** (`?element=<sorte>:<clé>`) : leurs faits (qui se présente comme
  qui, où en est la revendication ; qui a parlé du nom, qui le porte), leur source en liens, un homonyme en bandeau,
  leurs actions déjà orientées sur leur page (s'en porter garant, la démentir, le nom revendiqué posé ; relier, la
  personne visée posée ; « C'est elle », le formulaire pré-rempli sur la fiche) ou en boutons (« Ce n'est pas elle » —
  jamais deviné, ADR 0048) — chacune ramène à la file, la suivante ouverte.
- **Historique des autorisations** (`app/handmade/tabs/approvals.py`) : une entrée par demande tranchée — ce
  qu'elle voulait faire (relu au journal), la capacité (son nom court, sa clé au survol), ce qu'elle concerne, puis
  la décision
  (qui, la note) et son exécution (réussie ou non) dans l'ordre ; un trait dit l'issue. Trente demandes par page,
  prises par leur décision, chacune avec son exécution relue (elles ne se séparent jamais d'une page à l'autre) ;
  dans la page, celle dont la dernière nouvelle est la plus récente d'abord. Des puces filtrent par sorte
  (`?sorte=<capacité>`), un bouton à choix au bout de la barre d'onglets par issue
  (`?issue=tout|approuve|refuse|echec`) ; un filtre qui écarte beaucoup lit le journal par lots et dit que la
  recherche continue (« Plus anciens »). Vide, un bandeau, comme les autres onglets de la file.

### Réglages

Aucune page n'a de sélecteur de pages en tête : le menu Réglages de la barre du haut, les onglets et **Tous les
réglages** y mènent. Un formulaire de réglages range un champ par ligne : son nom et son aide à gauche, sa valeur à
droite, deux par rangée quand la place le permet (un texte long, une liste à cocher, un curseur gardent la largeur).
Tous les réglages est l'annuaire, construit à partir des pages déclarées sans charger leurs valeurs
(`inspector/pages/settings_directory.py`, ADR 0197) : une carte par rubrique — Intelligence, Personnage, Carte et
téléphone, Plugins, Connexions extérieures, puis les pages de la console (Comptes, Droits, Historique des
réglages) —, les pages qui vivent ailleurs comprises, dans leur rubrique et sous le nom de leur destination (Courrier ›
Paramètres, Teams › Paramètres, Ses sens › Flux suivis…, sous Plugins, ADR 0206) ; chaque
page s'y dit en une phrase entière (la description de sa section quand elle est seule, sinon la première phrase de
son introduction), jamais coupée. La recherche, par plusieurs mots sans tenir compte des accents, lit le titre,
l'introduction, la rubrique et l'adresse de chaque page, et le nom et l'aide de chacun de ses champs (ceux des
facultés compris) ; une page trouvée par un champ le dit (« Trouvé dans : Fuseau horaire »). La même recherche,
`settings_directory.find`, sert à qui la reprend. Les paramètres internes y sont repliés à part, ouverts quand une
recherche les trouve. Les commandes d'une page (« Nouveau jeton », « Revenir au fichier ») sont ses actions, dans la
barre de titre : deux en vue au plus, les dangereuses sous « ⋯ », chacune confirmée. Les faits d'une page qui
renvoient ailleurs sont des liens, chacun dit une fois. Une entrée de liste a pour titre l'entrée elle-même
(« Fournisseur « apercu » », « Fournisseur à ajouter »). Une correspondance (rôle → fournisseur, flux → autrice) garde
son « — » à chaque ligne : laissée vide, la clé est absente et retombe sur son repli ; décrite ligne à ligne
(`SettingsSection.describe`), elle est une table — sa liste dans une colonne, ce qu'elle donne à côté — et la page n'a
qu'un formulaire. Une liste d'entrées (des fournisseurs, des boîtes…) se lit
en fiches (`handmade/reglages/enregistrements.html`) avec leurs valeurs non secrètes, la modification et le retrait
confirmé, et peut se décrire en mots (`SettingsSection.describe`) : un fournisseur dit son type, s'il la fait
parler, sa clé, son modèle, les rôles qui le désignent, ses bornes en mots et ses appels des dernières 24 h ; son
bouton « Détail » déplie sa consommation et ses temps de réponse sur 24 h et sur 7 jours (appels, échecs, temps
moyen, médian, les plus lents, attente d'un créneau, jetons lus et écrits, part lue depuis le cache, coût), puis
rôle par rôle (`CallLog.profile`).

| Rubrique | Sous-page | Contenu |
|---|---|---|
| Intelligence | Fournisseurs (menu : Modèles de texte) | chaque fournisseur a sa page : type, modèle (**sélecteur** chargé chez le fournisseur, même pour un fournisseur pas encore enregistré), connexion, clé ; options avancées repliées (URL, hôte, commande, créneaux, température…) ; ses budgets (contexte, sortie, caractères par jeton) ; un échec est journalisé, sans basculement |
| | Qui sert quoi | une seule table, une ligne par rôle : sa famille (voix, mémoire, compréhension, sens, travail), son fournisseur (une liste, « — » : son repli), ce qui le sert **vraiment** après replis (le fournisseur, son type et son modèle), et comment (déclaré, la chaîne de ses replis, ou « chaque appel échoue ») — sauf `polish` (rendre naturel), qui n'a pas de repli ; un seul Enregistrer |
| | Fournisseurs d'images, Qui dessine quoi (menu : Modèles d'image) | les fournisseurs d'images et leurs rôles (`draw`, `edit`, `own`), ADR 0061 ; Qui dessine quoi est la même table : ce qui sert chaque rôle, son type et son modèle, où il tourne, ce qu'il sait aussi faire, comment |
| Personnage | Identité | nom, nature, description (une phrase), langue, fuseau |
| | Portrait | son portrait en prose — le seul texte qui la décrit, lu partout (ADR 0138) —, ce qui est vrai d'elle, ses centres d'intérêt |
| | Sa parole | ses exemples de voix en chat, ses salutations (seuls leurs premiers mots lui sont montrés), son fil de référence pour l'autrice |
| | Tempérament | une **table de mixage** (ADR 0176, `SettingsSection.aside`) : à gauche, tous ses curseurs d'un coup, famille par famille en colonnes, le milieu (0,5) marqué, ceux qui s'en écartent nettement en couleur ; l'aide du curseur qu'on survole, atteint au clavier ou déplace se lit à droite (« Ce qu'il règle »). À droite aussi, **son caractère, écrit** par le modèle d'après ses curseurs (ADR 0139) : le texte, le modèle, quand — ou « en cours d'écriture » ; après « Enregistrer », une modale suit l'écriture (`/inspecteur/reglages/temperament/etat`, JSON) et montre le texte quand il est là. Puis **la forme de son caractère** : une figure de tous ses curseurs (les 28 du caractère et son chronotype), rangés par famille ; la forme proposée pleine, celle d'aujourd'hui en pointillé, la valeur de chaque sommet dans une bulle au survol, au clavier ou au toucher ; ses traits les plus marqués en mots. Puis **partir d'un profil** : changer le sélecteur dessine la différence sur la figure sans rien remplir (`static/handmade/temperament.js`) ; « Pré-remplir » (`?profil=<clé>`) ouvre le formulaire sur ses valeurs, rien n'est enregistré avant « Enregistrer » ; ses 18 profils repliés, chacun avec sa silhouette. Puis ses curseurs, l'humeur de fond, sa réaction, sa défense, ses précisions (celles qui sont écrites ; les autres repliées sous « Écrire d'autres précisions »), ce que pilote chaque curseur (replié) ; **Voir l'effet** (`app/handmade/temperament.py`, `SettingsSection.prefill`) |
| | Autrices | en faits, combien de flux ont une autrice et le modèle qui les fait écrire ; en tête, un seul bandeau quand aucun modèle ne sert le rôle « rendre naturel ». Puis **ses autrices** en cartes, sous leur nom (où elles écrivent, leurs codes en bref, les premiers mots de leur exemple ; ajouter, modifier, retirer), et **où elles écrivent**, le formulaire de la page : flux par flux (le chat, chaque boîte mail, Teams, le téléphone), sa liste dans la colonne « Autrice » (« — » : le premier jet part), ce qu'elle récrit et ce qui l'en empêcherait (Teams désactivé) (`app/authors.py`, `app/handmade/authors.py`, ADR 0124). Les codes portent toute la forme du flux — longueur, registre, émojis, mise en forme (ADR 0140) : lus par l'autrice, ou par le premier jet quand aucune seconde passe ne suit |
| | Import / export | le document YAML, l'historique des révisions ; « Revenir au fichier » est une action de la barre de titre, sous « ⋯ », confirmée |
| Carte et téléphone (ADR 0197 ; menu : Carte et téléphone, ses quatre pages en une barre d'onglets) | Notifications du téléphone | la clé Firebase (collée ici ou posée en fichier), d'où elle vient, les téléphones notifiables, ce qui est parti, le dernier échec (ADR 0077) |
| | Carte de sa position | d'où viennent les tuiles de Téléphone › Position (aucune, un fichier PMTiles de `cartes/`, un serveur de carte relayé), la taille, les zooms et la zone du fichier, ses polices et icônes, la dernière erreur (ADR 0193) |
| | Lieux et adresses | l'index des lieux de l'écran Carte (un fichier SQLite de `cartes/`, refait par `mika carte lieux`) : combien de lieux, tirés de quelle archive, quand, sa zone et sa taille — ou comment le construire ; les adresses (aucune, par défaut, ou la Géoplateforme de l'IGN : seul le texte cherché part), ce qui en est parti depuis le démarrage, la dernière erreur (ADR 0194) |
| | Itinéraires | qui les calcule (aucun, par défaut ; le Valhalla public de FOSSGIS, au plus une demande par seconde pour tout ce serveur, sans garantie ; un Valhalla à toi, son adresse et son débit) ; les trajets demandés depuis le démarrage, ceux repris du cache, la dernière erreur (ADR 0194) |
| Plugins (menu : Configuration des plugins) | Vue d'ensemble des plugins | dessinée (`handmade/reglages/plugins.html`, ADR 0197) : une ligne par plugin composé — son nom et ce qui s'y règle, ses pages de réglages (nommées par leur destination quand elles y vivent : « Teams › Paramètres », « Ses sens › Flux suivis », ADR 0206), ses paramètres avancés (si sa faculté en a), où s'en servir —, tirée d'`app/reglages.py` (`PLUGINS`, une entrée par paquet de `plugins/`, `tests/protocol/test_settings_pages.py` les compare) ; puis ce qui se branche sans être un plugin (Transcription vocale, Notifications du téléphone) ; sans pagination ; les réglages d'une app restent sur sa fiche, dans la Forge |
| | Courrier | ses boîtes et ses paramètres généraux vivent dans Courrier › Paramètres, en haut à droite du courrier (ADR 0173) ; ce qu'elle prépare d'elle-même : le tableau de chaque boîte, Réglages › Canaux |
| | Teams | vivent dans Teams › Paramètres, en haut à droite de Teams (ADR 0206) : « Actif », puis ses comptes en cartes (ADR 0186) — voir Relations & échanges ; la clé de chacun se crée dans Teams › Extension |
| | Outils extérieurs (MCP) | vivent dans Ses outils › Paramètres des services, en haut à droite de Ses outils (ADR 0206) : chaque serveur a sa page — voir Outils |
| | Flux | vivent dans Ses sens › Flux suivis (ADR 0206) : les adresses suivies |
| | Transcription | vit dans Ses sens › Transcription vocale (ADR 0206) : service, modèle, clé |
| | Appareils | vit dans Ses sens › Accès des appareils (ADR 0206) : le jeton des appareils ; « Nouveau jeton » est l'action de la barre de titre (confirmée, le jeton montré une fois) |
| | Réveils par API | vivent dans Réveils par API › Paramètres (ADR 0206) : chaque réveil a sa page — voir Connexions extérieures ; sa clé se génère sur sa fiche, montrée une fois. ADR 0068 |
| Connexions extérieures (ADR 0197) | Dépôts Git | le jeton de ses dépôts distants, l'adresse de chaque dépôt sur la fiche de son projet (en lien) ; le menu y mène par Connexions extérieures › Dépôts Git |
| Paramètres avancés | Vue d'ensemble | la bande de chiffres, d'où vient une valeur (les quatre sources en étiquettes) ; en sous-onglets les facultés rangées par famille (dérivés du tempérament, surcharges, réglés ailleurs, refus), et ce que pilote chaque curseur du tempérament (`app/handmade/tabs/settings.py`) |
| | une page par faculté | son fil, « Réglages / Paramètres avancés / sa famille », « Paramètres avancés » menant à la vue d'ensemble, sa famille à la sienne sur cette vue (une ancre) ; ses chiffres en bande (ce que le tempérament dérive mène au tempérament), d'où vient une valeur, ses groupes en colonne à gauche, ses paramètres **rangés par groupe** (un groupe = une page, une ligne par paramètre : son nom et son aide, d'où il vient et ses bornes, sa valeur), chacun avec sa valeur, sa provenance, ses bornes et son sens — valeur et bornes en notation décimale française (« 0,00000556 », « 0,00000001 – 0,0005 »), six chiffres dans le champ, renvoyés tels quels sans rien changer ; une surcharge se pose en changeant la valeur ; **Voir l'effet** : avant d'enregistrer, les lignes de l'arbitre et les faits partagés qui changeraient maintenant avec les valeurs tapées (avant → après) — rien n'est écrit ni journalisé, ce qui s'est accumulé n'est pas rejoué |
| Comptes | Comptes | qui se connecte (son espace, le téléphone, un écran) et qui pilote la console : un compte par entrée (nom, identifiant, rôle, désactivé, sa dernière connexion — l'ouverture de sa session web la plus récente encore gardée ou le dernier usage d'une de ses applications, `Accounts.last_seen` —, sa fiche, ses droits exacts), paginée, bascule « Tableau » ; deux boutons dans la barre de titre, « Ajouter un utilisateur » (le chat, sans la console) et « Ajouter un opérateur » (la console aussi), chaque compte une personne dès l'ajout. La page d'un compte est la vue d'un objet : le fil « Réglages / Comptes / son nom », son nom affiché avec ses étiquettes (opérateur ou utilisateur, actif ou désactivé), ce qu'il ouvre, ses faits (son identifiant, sa fiche, l'onglet Comptes de sa fiche s'il en a un, ses droits exacts — Réglages › Droits, `?qui=` et le chat web en privé —, sa dernière connexion) ; modifier (nom affiché, opérateur, actif, mot de passe) — audité ; ses connexions web (combien de sessions ouvertes, la plus récente) et « Fermer ses sessions » (confirmé, audité ; ses applications restent) ; ses applications connectées (téléphone, moteur : sorte, origine, dernier usage, jamais le secret), douze par page, « révoquer » — audité (ADR 0062) — et « Nouveau jeton » (un nom, ce qu'il ouvre : un écran ou un moteur, ou le téléphone), donné par la console : il ne tombe pas avec le mot de passe, il est audité et montré une seule fois, à l'opératrice qui l'a créé |
| Droits | Droits | dessiné (`reglages/droits`, ADR 0133, 0134, `app/handmade/rights.py`) : ce qu'elle a, ressource par ressource, une sorte par sous-onglet (ADR 0176) — *Vie interne* (ses familles d'outils), *Apps de la Forge*, *Services MCP*, *Projets*, *Canaux*, *Partages*, *Ce que le code fixe* —, chaque ressource sur sa ligne, avec sa description (celle d'une famille écrite pour l'opératrice, à la troisième personne, `FAMILY_ABOUT` : jamais la phrase de sa voix, qui parle au modèle) et le nombre de ses outils, ses outils décrits en la dépliant (lit ou agit, le lien de sa fiche), et « détail des accès » (`?detail=<ressource>`) : son tableau de règles lu tel qu'il est écrit, ses planchers, « Modifier » vers la page qui le règle, « ← Retour » vers sa ligne. Qui et par quel canal se choisissent sur une ligne, en tête. Les droits exacts, outil par outil, seulement quand on a choisi qui (`?qui=` : toi quand elle te répond ou te parle d'elle-même, chaque personne qui a un compte, un autre compte, une inconnue, elle seule) et par quel canal (`?canal=` : le chat web en privé ou en salon, l'app Android, Internet, elle seule) : une étiquette par outil vient alors sur la ligne de sa ressource et dit s'il est ouvert, une colonne « Droits exacts » dit ce qu'elle en fait et les lignes qui en décident (la ressource ; le canal ou le plafond s'ils ont serré), et ce que le canal laisse au plus. Une lecture, sauf *Partages* (ADR 0210) : une ligne par partage (la ressource et sa sorte — boîte, compte Teams, service —, son propriétaire, qui le reçoit et le lien de sa fiche, le niveau en mots), « Retirer » sur chaque boîte et chaque compte Teams (confirmé, audité, `POST /reglages/droits/partages`, la même écriture que son propriétaire : la personne ne le voit plus dans son espace), « ses lignes d'accès » sur un service (sa fiche, où il se retire). Rien ne s'y crée : donner reste au propriétaire |
| Droits | Canaux | dessiné (`reglages/canaux`, `inspector/pages/canals.py`, ADR 0134) : par où ça lui arrive — un sous-onglet par type (le chat web, l'app Android, Teams, le courrier, Internet, elle seule, ADR 0176), et dedans ses instances, repliées (le chat web en privé ou en salon, chaque boîte, chaque compte Teams, un réseau), chacun avec son tableau (`handmade/droits/tableau.html`) : ce qu'il laisse passer au plus (répondre, outils qui lisent et qui agissent, projets, fichiers, garde) ; sur tes comptes, préparer d'elle-même et comment ça part (l'ADR 0132 s'y fond : qui écrit, c'est tout le monde ou une adresse). Un canal qu'on n'a pas réglé montre son minimum vital ; « Revenir au minimum vital ». `?canal=` ouvre un tableau et son sous-onglet ; chaque bouton envoie tout le tableau (`/reglages/canaux/regler`) et rejournalise le courrier et Teams |
| Historique des réglages | Journal des modifications | jour par jour, chaque réglage enregistré (qui, quoi, sur quoi) et chaque journalisation des paramètres — celles d'un même moment et d'une même origine (le démarrage) réunies en une ligne |

### Système

Le menu Système a trois colonnes (ADR 0202, `MenuLink.column`), les groupes de ses onglets (`group`, dans
`inspector/pages/system.py`) : le fil d'Ariane et la recherche les disent (« Système / Journaux »). Journaux mène
aussi à Réglages › Historique des réglages et à À valider › Historique des autorisations, qui restent dans leur
rubrique.

| Colonne | Page | Contenu |
|---|---|---|
| Surveiller | Santé générale | le verdict ; les dix contrôles en tuiles, ceux en panne d'abord, chacun avec son constat, son détail et un lien vers son diagnostic ; **ses projections** : une jauge en demi-cercle (combien sont à jour), une ligne par projection (son nom en clair, sa faculté, son niveau, une barre : où elle en est du journal), la quarantaine, les vues lentes en barres (la pire fois, un trait pour la dernière) (`app/handmade/system.py::projections`) |
| | Processus | ceux qui échouent d'abord : passages, échecs, dernière erreur, en cours |
| | Anomalies | (`app/handmade/tabs/system.py`, ADR 0177) un bandeau (tranches corrompues, anomalies, ou rien depuis le démarrage), les chiffres ; côte à côte ce qui a échoué dans ses facultés et à l'arbitre — la faculté, l'événement, l'erreur en clair et telle quelle ; les traces du journal (supplanté, oubli…) jour par jour, en mots, celles qui disent un problème marquées |
| | File de sortie | (`app/handmade/system.py::outbox`) à quoi elle sert et le chemin de ce qui part (écrit au journal → en route → parti, et ce qui est à traiter) ; **À traiter** (le filtre d'état le suit, 8 par page, Relancer / Marquer comme vu, l'erreur, ce qu'il faut vérifier) ; **ce qui part, par sorte**, en mots (ses messages, ce que montrent ses écrans, ce qu'elle fait au dehors — l'action nommée —, le ménage), une barre empilée parti / en route / à traiter / vu ; **les derniers départs**, filtrés par état, avec leur heure et leur événement |
| | Moteur des modèles | un bandeau (un rôle sans fournisseur, des appels qui attendent un créneau) ; chaque fournisseur : ses créneaux en cases, son quota en jauges, ses 24 dernières heures (appels, échecs, médiane) ; qui sert quoi, en vrai : les rôles par fournisseur, ceux que personne ne sert d'abord |
| | Écrans du monde | un bandeau (ce qui manque à un hôte connecté) ; côte à côte les clients de `/ws/world` (client, moteur, qui, rôles, qui tient le bail d'hôte et qui l'attend) et, par hôte, la révision chargée et ce qui lui manque (ancres, assets en puces, révision dépassée). ADR 0051 |
| | Appels et coûts | un bandeau des échecs (les rôles qui échouent surtout) ; ses quatorze jours en barres (le coût, les appels, leurs échecs en rouge) ; en sous-onglets où va le coût (par rôle, **modèle**, fournisseur : une barre de coût et une d'appels chacun), tous les appels paginés, le détail jour par jour |
| | Stockage et sauvegardes | un bandeau si les sauvegardes manquent ou échouent ; taille des bases, dernier instantané ; ses bases et ses dossiers, une ligne chacun (`app/backup.place`, mesuré hors de la boucle d'événements) : sa place, ce qu'il garde, ce que la sauvegarde en fait — sauvegardé, jetable (`views.db` se reconstruit), réextrait (la carte), retéléchargé (le modèle de plongements), mis de côté par une restauration ; sous MariaDB, ses bases sont « sur le serveur MariaDB » ; ce que garde `mind`, une barre par table ; la dernière sauvegarde (ce qui s'est écrit depuis), la dernière vérification, les archives gardées |
| Journaux | Journal d'événements | jour par jour, une ligne par événement (l'heure, ce qui s'est passé, son type, son numéro, ses données repliées), deux colonnes sur un écran large ; les événements d'un même épisode se suivent et ne disent son lien qu'une fois ; les familles de la page en puces qui filtrent ; filtrable, quarante par page, paginé dans les deux sens |
| | Gestes audités | ce que les opérateurs ont fait dans la console, et chacun depuis son espace (`runtime.operated`) : jour par jour, l'heure, qui, le geste sous son titre (jamais sa clé), d'où (la console, son espace, la ligne de commande : le début de sa clé, `operations.origin` ; une action déclarée sous sa clé nue vient de la console si un opérateur l'a faite), sur quoi (le lien de sa fiche si elle s'ouvre, sinon sa clé en texte : un objet retiré depuis, un partage), l'issue, sa clé et ses événements ; en tête, qui et quelles issues sur la page ; « depuis » en bouton à choix (`?depuis=`) |
| Anatomie | Diagnostic avancé | en sous-onglets : l'ensemble de ses tranches (la plus récemment modifiée d'abord), puis une faculté par sous-onglet — ses faits lus maintenant (les familles en une ligne), sa tranche en JSON, repliée |
| | Contributions | en sous-onglets : l'ensemble (une ligne par faculté, ce qu'elle apporte en nombres), puis une faculté par sous-onglet — ce qu'elle publie, écoute, fournit (et qui le lit), ses sections, preuves, processus, outils, capacités, vues, fiches, actions |
| | Toutes les vues | en sous-onglets : par destination, sur les fiches, par faculté, cachées ; chaque groupe en colonnes |
| | Simulations | les rapports à gauche, celui qu'on lit à droite ; sans dossier, comment en faire |

## Les formes

- **Cadres** (`Stats`) : un nombre, un état, en une bande de cases jointes ;
  toujours en tête de page, jamais plus de six.
- **Tables** : une ligne entière mène à sa fiche ; le détail se déplie sous la
  ligne par un chevron ; le compte total s'affiche au-dessus ; 25 lignes par
  page par défaut. Une collection en fiches ou en fil passe en tableau sobre par
  « Tableau » (`vue_pg<n>=table`), qui garde les filtres et la pagination, même sans
  JavaScript.
- **Courbes** : une échelle par courbe, la table des valeurs repliée dessous. Un
  graphe a une hauteur fixe et s'étire en largeur seulement (`inspector/svg.py`).
- **Fiches** (`Fields`) : libellé à gauche, valeur à droite, deux colonnes au
  plus en largeur. Une fiche de collection ou de réglage mène à sa page sur toute
  sa surface.
- **Listes** : une liste sans long texte (des lignes serrées) passe en colonnes sur un
  écran large ; une entrée dont on ouvre le détail prend toute la largeur. Une suite de
  replis se range sur trois colonnes.
- **Sous-onglets** : une page à plusieurs sujets les met dans une colonne à gauche, un
  seul ouvert à droite (`.hm-subtabs`, `data-subtabs`, `data-pane`, `handmade/base.css`
  et `console.js`) ; l'adresse garde la section ouverte (son ancre), Précédent y revient,
  un enregistrement la retrouve ; sans script, les sections se suivent.
- **Formulaires** : un groupe = un cadre titré avec sa phrase d'explication ;
  l'aide de chaque champ sous son nom, sa valeur à droite (un texte long, une liste
  à cocher ou un curseur sur toute la largeur) — les réglages comme le formulaire
  d'une action qui a sa page (créer un projet : ses groupes deux par deux sur un
  écran large ; l'adresse peut la poser déjà orientée, `?valeur.<champ>=` — un choix offert, un texte, un objet,
  jamais une case « Je confirme », un secret ni un champ caché) ; les options rarement utiles repliées sous
  « Options avancées » ; un champ qui ne sert pas au choix fait ne paraît pas, et
  paraît dès qu'il sert (à la frappe comme au choix) ; une liste qui ne peut
  rester vide n'offre pas de « — » ; une seule barre « Enregistrer » par page, collée en bas,
  qui passe au premier plan dès qu'une valeur change. Une saisie non enregistrée se
  signale et la sortie est protégée ; les erreurs ont un résumé navigable au clavier.
- **Actions d'en-tête** : une barre de boutons, à droite de la barre de titre (celles
  de la page, voir « Le cadre ») ; le formulaire s'ouvre en panneau sous l'en-tête, un
  seul à la fois.

## Composants communs et langage de la Forge

- `kernel/inspect.py` décrit les blocs natifs ; `kernel/envelope.py` valide
  et documente leur représentation JSON pour les apps (version 2 conservée).
- `inspector/render.py` prépare les cellules, liens, filtres, tableaux,
  graphiques et paginations ; les valeurs des graphiques utilisent le même
  composant de table que les autres vues.
- `_cells.html`, `_forms.html` et `_navigation.html` fournissent les primitives
  réutilisables ; `_blocks.html` les compose en sections, grilles, détails,
  statistiques et formulaires. Chaque occurrence d'un formulaire reçoit son
  propre identifiant, même si la même action apparaît plusieurs fois.
- `Workspace` compose une navigation latérale et un contenu ; `Toolbar`
  regroupe des actions ; `ActionSlot.presentation="button"` ouvre le formulaire
  à la demande ; `Text.secondary` ajoute un aperçu et `Prose.reading` un
  document lisible. Ces primitives sont aussi disponibles dans le langage
  JSON de la Forge ; le HTML brut reste réservé au lecteur natif nettoyé.
- `Table.layout` et `Column.role` présentent une table en fiches ou en fil ;
  l'enveloppe Forge accepte ces champs facultatifs.
- `Column.detail=True` range une information secondaire dans le détail de
  chaque ligne, sans perdre sa valeur, son lien ou la pagination. Dans une app
  Forge : `{"label": "Identifiant", "detail": true}`.
- `Head.action_tabs` limite les commandes globales d'une fiche aux onglets où
  elles servent. Une app conserve ses propres actions dans ses blocs de vue.
- Les filtres d'une app sont déclarés dans `manifest.yaml` (`params`) et
  rendus par l'hôte : recherche, entier, liste ou booléen. Le formulaire garde
  l'app et la vue sélectionnées et repart de la première page après filtrage.
- Sans pagination explicite, chaque table reçoit une page de 25 lignes et un
  compteur, même vide. Un historique à curseur annonce que son total est
  inconnu. La navigation reste disponible sur sa dernière page.
- Les téléchargements natifs sont déclarés par le propriétaire de la fiche
  (`Faculty.download`) et servis par une route commune authentifiée. Le nom du
  fichier est nettoyé et la réponse force le téléchargement sans mise en cache.
  Ce mécanisme n'ajoute pas de HTML arbitraire au langage des apps Forge.

Pour une vue Forge avec plusieurs grandes collections, utiliser un nom par
pagination (facultatif, `page` reste accepté) :

```json
{"type": "table", "title": "Articles", "columns": ["Titre"],
 "rows": [["Un article"]],
 "pagination": {"param": "page_articles", "page": 1, "total": 51, "per_page": 25}}
```

L'app lit `params.get("page_articles", 1)`, borne le numéro selon son total,
puis découpe ses données. Une deuxième table utilise par exemple
`page_alertes`. Ces paramètres sont des entiers bornés par l'hôte, conservés
dans les liens entre vues et réservés à la pagination. Sections, grilles,
statistiques, courbes, détails de ligne et formulaires se combinent dans la
même enveloppe, sans HTML ni JavaScript fournis par l'app.

## Vérifier la console

Les contrôles HTTP sont dans `tests/fixtures/console_html.py` (structure de chaque document : un seul titre
principal, identifiants uniques, aucun lien ni formulaire imbriqué, en-têtes associés aux colonnes, pagination),
`tests/protocol/test_console_apercu.py`, `test_console_workflows.py`, `test_console_settings.py`,
`test_console_navigation.py` et `test_inspector_pages.py` (sous `tests/protocol/`), `tests/unit/test_forge_console.py`,
`tests/unit/test_console_pagination.py` et `tests/contract/test_mail_feeds.py`.

`tests/browser/console.cjs` les complète avec un vrai navigateur (les fichiers de `static/` servis depuis les sources :
feuilles des pages dessinées, scripts, polices) : la barre du haut (menus des rubriques, panneau mobile au clavier,
« Aller à… »), mode sans JavaScript,
recherche des rubriques, champs conditionnels, filtres, état des formulaires, panneaux imbriqués, expiration de
session, contrastes et largeur de chaque page exportée à 390 et 1440 px. Depuis `backendv2`, avec Playwright
disponible pour Node (ou son dossier dans `NODE_PATH`) et Chrome installé :

```bash
.venv/bin/python -m mika console apercu --out /tmp/mika-console-apercu
MIKA_CONSOLE_PREVIEW=/tmp/mika-console-apercu node --test tests/browser/console.cjs
```

`mika console apercu` exporte chaque page, en clair et en sombre, d'une Mika neuve sur des données fictives
(modèle factice, port de courrier simulé, rien ne sort de la machine, POST refusés) ; le cadre d'un mail HTML
(ADR 0169) s'exporte à part, sous `cadres/`.
`PLAYWRIGHT_CHROMIUM_EXECUTABLE` permet de préciser un autre exécutable Chromium. Le navigateur emploie un profil
temporaire ; les pages et ressources sont servies par interception depuis l'export et les fichiers source, et les
requêtes vers un autre hôte sont bloquées. Aucun compte de l'installation n'est utilisé.
