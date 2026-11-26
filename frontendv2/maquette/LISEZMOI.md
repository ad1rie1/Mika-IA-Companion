# Maquette du frontendv2

Le client web de tous les jours d'une personne connectée : le chat avec Mika (et le mode pro), ses outils, son
courrier, son Teams, son téléphone et ses paramètres. Pas de monde 3D : Mika est au bout de la barre du haut, et en
grand dans le chat. Cette page est la **maquette validée** (le 2026-11-04) : les données sont fictives et rien ne
parle au moteur. Le vrai client est `frontendv2/` (son `README.md`), sur l'API par personne (ADR 0187).
L'écran **Carte** (lieux, itinéraires, voyages, et sa carte dans le chat) s'y est ajouté le même soir, validé lui aussi.
L'écran **Projets** s'y est ajouté le 2026-11-21 (`ecrans/projets2*.js`, d'après
`output/chaines-de-travail/web/MAQUETTE-V2.md`) : un atelier en trois zones sur toute la largeur (la liste, le contenu
en volets, un panneau latéral), où tout se modifie sur place, avec le code, la documentation et son éditeur, le fil
d'activité et le schéma des dépendances. **Validée le même jour**, au troisième tour (« ok mieux ! go là-dessus »,
« sers-toi de la maquette comme référence ») : le vrai écran en reprend la structure, les classes et la feuille de
style (ADR 0291). Sa première maquette, rejetée, est retirée.
**Proposé le 2026-11-21, pas encore validé** : l'effort de réflexion dans le champ du chat (`ecrans/chat.js`,
`chat.css`). Une pastille « Effort · auto » à côté de « Pro » ouvre son menu : Auto, ou forcé à un niveau, pour toute
la conversation et, en mode pro, pour le fil ouvert (un fil en auto suit la conversation ; la conversation en auto suit
le réglage de la console, ADR 0285). Il se règle aussi dans la fenêtre « Le fil » et par `/effort` ; un fil forcé le
dit dans la liste des fils. `?effort=1` ouvre le menu d'emblée.

**Validé le 2026-11-22** (« nikel la maquette ») : l'écran **Contacts** (`ecrans/contacts.js`, `contacts.css`, ADR 0298) — tous ceux que Mika connaît pour toi, vus dans ton Teams, tes boîtes, ton téléphone ou dont tu lui as parlé, et leurs organisations : ce qui les identifie, ce que Mika en sait, où vous vous croisez. Il remplace l'onglet Contacts du courrier.

**Validé le 2026-11-22** (« oui ») (ADR 0300) : les **photos de profil** de Teams à la place des initiales, partout où une personne a un avatar (fil Teams, conversations, participants, Contacts, Mail) — seulement pour qui Teams montre une photo, un proche vu au téléphone garde ses initiales ; et les **réactions** sous un message (déjà dans la maquette validée) : la tienne en couleur, qui a réagi au survol. Les portraits sont dessinés (pas de vraies photos ici). `ecrans/teams-photos.js` et `.css`, chargés avant les écrans ; `?photos=0` pour comparer avec les initiales. Routes : `#teams/discussions/lumen`, `#teams/discussions/marc`, `#contacts/claire`.

**Proposé le 2026-11-23, pas encore validé** : l'écran **Agenda** (`ecrans/agenda.js`, `agenda.css`, `agenda-donnees.js`,
d'après `output/agenda/CONCEPTION.md`) — tous tes agendas en un écran, comme Google Agenda ou Outlook : Créer, le
mini-mois et les agendas groupés à gauche (Mes agendas · Partagés avec moi · Abonnements · L'agenda de Mika, chacun sa
couleur, son fournisseur, son menu ⋯) ; Jour · Semaine · Mois · Planning, les chevauchements, la ligne de l'heure ; la fiche
d'un événement dans un volet (récurrence, lieu vers la Carte, visio, participants et leur réponse, rappels, « Mika te le
rappelle », « Ce que Mika en sait », Modifier · Dupliquer · Supprimer · Demander à Mika) ; créer et modifier (et la question
d'un événement récurrent) ; partager un agenda (Lire · Lire et préparer · S'en servir) ; les invitations et la réponse que
Mika prépare ; ce qu'elle propose d'ajouter, hachuré de rose ; son agenda à elle, tiré de sa mémoire, en lecture seule.
Posés par-dessus les écrans validés, sans les retoucher : **Paramètres › Agendas** (`ecrans/agenda-parametres.js` : les
comptes, leur fiche, « Brancher un agenda » par sorte), **Outils › Droits** (`ecrans/agenda-droits.js` : un tableau par
agenda) et le **chat** (`ecrans/agenda-chat.js` : la carte « Ajouter à ton agenda » et un de ses rappels). Pour faire tenir
une dixième rubrique, `agenda.css` replie les libellés de la barre du haut un peu plus tôt, et sur un téléphone la barre
du bas passe à huit entrées : Carte, Outils et Réglages sous « Plus ». L'écran se passe le lundi 23 novembre 2026 à 14:20.

**Validé le 2026-11-26** (« je valide la maquette », ADR 0312) : les **fichiers du chat** (`ecrans/chat-fichiers.js`, `chat-fichiers.css`),
posés par-dessus l'écran Chat validé sans le retoucher. Dans le fil, tes pièces se montrent comme les siennes (une image
en vignette, un document en carte avec sa sorte, son nom et sa taille, « plus disponible » une fois retiré) ; un clic
ouvre la **visionneuse** : une image en grand, un PDF dans le lecteur du navigateur, un texte ou un Markdown (rendu ou
source), un CSV en tableau ; les autres sortes se disent et s'enregistrent ; ← et → parcourent les fichiers, « Dans la
conversation » remonte au message. **Fichiers** (en haut à droite) liste tous les fichiers de la conversation, pas
seulement les messages chargés : chercher par nom, par sorte et par qui l'a envoyé, en liste ou en vignettes, page par
page. `?panneau=1` ouvre Fichiers, `?grille=1` en vignettes, `?voir=<id>` la visionneuse.

## L'ouvrir

- **Avec la VRM** (servie en HTTP, depuis la racine du dépôt) :

  ```bash
  python3 -m http.server 8791 --bind 127.0.0.1
  # puis http://127.0.0.1:8791/frontendv2/maquette/
  ```

- **Sans serveur** : ouvrir `index.html` dans le navigateur. Les modules étant refusés en `file://`, Mika garde son
  portrait pré-rendu, qui cligne des yeux.

Le fond de l'écran Carte (`ecrans/carte-fond.js`) est la France tirée des tuiles Protomaps, puis simplifiée : données © OpenStreetMap (ODbL). Le vrai écran montre la carte vectorielle que le serveur sert (ADR 0193).

La VRM (`frontend/Web/public/models/default.vrm`), les portraits (`frontend/Android/app/src/main/assets/avatar/`) et
la police Inter (`backendv2/src/mika/inspector/static/fonts/`) sont lus là où ils sont : rien n'est copié ici. La VRM et
les portraits sont sous licence et ne sont pas versionnés.

Paramètres d'adresse utiles pour les captures : `?theme=dark|light`, `?vrm=0` (portrait seul), `?pro=1` (chat en
mode pro), `?notes=1` (panneau des notes ouvert), et la route après `#` :

| Écran | Routes |
|---|---|
| Chat | `#chat` (le bouton Pro du champ passe en mode pro), `#chat/fichiers` (tes pièces et les siennes ; `?voir=f-devis`, `f-tableau`, `f-notes`, `f-comp`, `f-budget`, `f-vacances`) |
| Projets | `#projets/a-faire` (et `/a-faire/3/ticket-4`, `/3/pr-11`…), `#projets/projets`, puis la fiche `#projets/projets/3` et ses onglets : `/objectifs/o2` (et `/rendus`, `/modifier`), `/objectifs/m1`, `/objectifs/diagramme/avancement` et `/objectifs/diagramme/temps` (et `/o2`, `/o2/3` pour un jalon), `/tickets/4` (et `/description`, `/plan`, `/fil`, `/historique`, `/modifier`), `/code/fichiers/<branche>/<chemin>`, `/code/commits/<empreinte>`, `/code/pulls/11` (et `/commits`, `/fichiers`, `/echanges`, `/modifier`), `/code/branches/<branche>`, `/code/issues/9` (et `/echanges`), `/code/ci/57` (et `/journal`), `/documentation/pages/<page>` (et `/modifier/<page>`, `/historique/<page>`, `/images/<image>`, `/decisions/3`, `/decisions/3/options`, `/decisions/3/modifier`), `/activite` (le fil ; et `/executions/61`, `/carnet`), `/dependances/lit-7` (le schéma ; et `/demandes/d3`), `/reglages/general` (« Modifier le projet » ; et `/rythme`, `/accords`, `/depot`, `/outils`) ; `#projets/projets/5/listes/entreprises` (un projet qui a des listes) |
| Outils | `#outils/droits` (la matrice des droits, ressource par ressource), `#outils/services`, `#outils/accords` |
| Mail | `#mail/messages`, `#mail/messages/m-claire`, `#mail/messages/d-lefevre` |
| Teams | `#teams/discussions/lumen`, `#teams/discussions/claire`, `#teams/brouillons` |
| Téléphone | `#telephone/messages/julien`, `#telephone/notifications`, `#telephone/position` (le sélecteur en haut passe d'un téléphone à l'autre) |
| Contacts | `#contacts/claire` (une collègue vue dans Teams et au courrier), `#contacts/lea` (qui parle aussi à Mika), `#contacts/ines` (dont tu lui as seulement parlé), `#contacts/lumen` (une organisation) |
| Agenda | `#agenda` (Semaine ; Planning sur un téléphone), `#agenda/jour`, `#agenda/semaine`, `#agenda/mois`, `#agenda/planning`, `#agenda/evenement/<id>` (`revue-budget`, `point-lumen@2026-11-23` une occurrence, `inv-afterwork` une invitation, `prop-diner` ce que Mika propose, `dentiste` ajouté par Mika, `mika-relire` son agenda, `lea-diner` partagé avec toi), `#agenda/nouveau`, `#agenda/modifier/<id>` (`escalade@2026-11-26` pose la question du récurrent), `#agenda/partager/<agenda>` (`famille`, `perso`, `lea`), `#agenda/invitations` ; et `#chat/agenda` |
| Carte | `#carte/explorer`, `#carte/itineraire`, `#carte/voyages`, `#carte/voyages/alpes` (et sa carte dans le chat, en bas de `#chat`) |
| Paramètres | `#parametres/compte`, `#parametres/comptes-mail/pro`, `#parametres/teams`, `#parametres/telephones`, `#parametres/partages`, `#parametres/mcp/factures` ; `#parametres/agendas`, `#parametres/agendas/<compte>` (`systeme`, `lumen`, `google`, `outlook` en erreur, `feries`), `#parametres/agendas/brancher` et `/systeme`, `/google` (`/google/sans-appli` : l'application Google n'est pas réglée), `/microsoft`, `/caldav`, `/ical` |
| Outils › Droits d'un agenda | `#outils/droits/ag-<agenda>` (`mon`, `travail`, `perso`, `famille`, `feries`, `lea`) |

## Les notes

Le bouton **Notes**, en haut, ouvre pour chaque écran la liste de ce que le moteur sait déjà faire (« Existe »), de
ce qui est en chantier (« En cours ») et de ce qui manque ou reste à décider, avec les fichiers du moteur. C'est là,
et pas dans l'interface, que la maquette dit ce qui n'existe pas encore.

## Le thème

- Fond blanc et filets, sans aplat gris en clair ; sombre complet. Inter, Inter Display pour les titres.
- La navigation est en haut ; sur un téléphone, elle passe en barre du bas, comme sur Android (huit entrées depuis
  l'écran Projets ; Paramètres s'y dit « Réglages »).
- Chaque écran a une barre de titre : son nom, ses onglets, puis ses actions à droite.
- Un écran tient dans la fenêtre ; chaque liste défile dans son cadre.
- Deux couleurs portent un sens : **l'indigo** de l'app Android pour ce que tu fais, **le rose** de Mika pour ce
  qu'elle fait (ce qu'elle a lu, ce qu'elle propose, ce qu'elle a rédigé).
- Mika a une place fixe, qui ne couvre rien, et qu'on ne déplace pas : son visage (sa VRM, sinon les portraits
  d'Android) au bout de la barre du haut, sur chaque écran et en mode pro, avec son nom et ce qu'elle fait ; dans le
  chat ordinaire, en grand, dans une colonne à droite (son humeur, ce à quoi elle repense, ce qu'elle a promis). Un
  clic sur son visage ou sur son nom ouvre « Ce qu'elle fait ».
- Ctrl K cherche partout : un mail, une personne, une discussion, un outil, un réglage.

## Les fichiers

| Fichier | Rôle |
|---|---|
| `index.html` | le cadre : la barre du haut (son visage au bout), les icônes, la palette |
| `maquette.css` | les jetons (clair, sombre) et les composants communs |
| `maquette.js` | le moteur : routes, barre de titre, la place de Mika (la barre, la colonne du chat), palette, menus, fenêtres, toasts |
| `donnees.js` | qui est connecté, les personnes, l'état de Mika et le fil rouge entre les écrans |
| `mika-vrm.js` | sa VRM (module, HTTP seulement) : son visage dans la barre, son buste dans le chat |
| `ecrans/<écran>.js` et `.css` | un écran chacun : chat, outils, mail, teams, telephone, carte, parametres (et `carte-fond.js`, le fond de France, généré) |
| `ecrans/agenda.js`, `agenda.css`, `agenda-donnees.js` | l'écran Agenda (proposé le 2026-11-23) et ses données d'exemple ; `agenda-parametres.js`, `agenda-droits.js`, `agenda-chat.js` le posent sur Paramètres, Outils › Droits et le chat |
| `ecrans/projets2.js`, `-travail.js`, `-diagramme.js`, `-code.js`, `-doc.js`, `-suite.js` | l'écran Projets, seconde maquette : le socle (les trois zones, les formulaires, le panneau qui s'ouvre), « À faire », la grille et la Vue d'ensemble ; Objectifs, Tickets et « Modifier le projet » ; le diagramme des objectifs (leur avancement, ou leur place dans le temps) ; Code ; Documentation (Pages, Images, Décisions, et le petit rendu Markdown de la lecture) ; Activité, Dépendances, Listes |
| `ecrans/projets2.css`, `projets2-zones.css` | ses styles : le cadre et les morceaux partagés ; les trois zones, les formulaires et les vues refaites (l'éditeur à nos couleurs, le graphique, le schéma) |
| `ecrans/projets2-donnees.js` | ses données d'exemple, inventées : un projet « Outils réseau » complet (dépôt, commits et diffs, pull requests, tickets, espace de documentation, décisions…) ; les gestes les modifient en mémoire |
| `vendor/milkdown-crepe.js`, `.css` | l'éditeur de la documentation : Milkdown, son éditeur Crepe (`@milkdown/crepe`, MIT), en un seul paquet pour navigateur (il expose `window.MikaEditeur`). Fabriqué hors du dépôt : `output/chaines-de-travail/web/v2/editeur/` (`sh empaqueter.sh`). Rien n'est ajouté au `package.json` de `frontendv2/` : la dépendance du vrai client se décidera au moment du code |

L'API d'un écran est décrite en tête de `maquette.js`.
