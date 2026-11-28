# Maquette de l'app Android, avec ce que fait le client web

L'app Android d'aujourd'hui (la conversation, « Ce qu'elle fait », les paramètres) à laquelle s'ajoutent les écrans du
frontend/Web : Mail, Teams, Carte, Téléphone, Outils, et les paramètres de la personne connectée. Elle sert à décider
de la place des boutons et des écrans **avant** d'écrire du Kotlin. Les données sont fictives et rien ne parle au
moteur. **Validée le 2026-11-17, en variante « Tiroir »** (« en mode tiroir je préfère ») : c'est la navigation de
l'app (ADR 0235). Les écarts de l'app avec elle, et pourquoi, sont dans `frontend/Android/README.md` (l'ADR 0233 l'emporte
sur Téléphone : ni onglet Notifications, ni sélecteur de téléphone). Ses écrans ne se retouchent plus ; son sprite
d'icônes (`index.html`) reste la source de celles de l'app (`tools/icones.py`) : une icône neuve s'y ajoute.

**Proposé le 2026-11-17** (Google Maps à la place de Tripadvisor depuis le 2026-11-20, ADR 0256 ; fait dans l'app,
lot L6 : `frontend/Android/README.md`, « Carte ») : la fiche d'un lieu (la note et les avis de Google Maps — sans
répartition ni sous-notes, chaque avis avec son auteur, son lien et sa date —, infos pratiques d'OpenStreetMap, ce qu'en
dit l'office de tourisme, photos) et un onglet Événements (DATAtourisme), dans `ecrans/carte-avis.js` :
`#carte/manger`, `#carte/fiche/atelier`, `#carte/fiche/reblochon`, `#carte/evenements`, `#carte/evenement/poulenc`.
Les événements sont les vrais, tirés de l'API DATAtourisme le 17 novembre ; les restaurants et leurs avis sont inventés.

**Proposé le 2026-11-21, pas encore validé** : l'effort de réflexion dans le chat, dans `ecrans/chat-effort.js`, posé
par-dessus l'écran Chat sans le retoucher. Le menu ⋮ gagne « Effort de réflexion · auto », qui ouvre une feuille (Auto,
ou forcé à un niveau) : pour toute la conversation, ou, en mode pro, pour le fil ouvert (aussi dans « Régler ce fil »).
Forcé, il se voit dans le champ, à côté de « Pro ». Routes : `#chat/effort`, `#chat/pro/effort`.

**Validé le 2026-11-22** (« je valide ta maquette ») : les Contacts (ADR 0298), l'écran Contacts du web validé le même jour
(`frontend/Web/maquette/ecrans/contacts.js`) adapté au téléphone, dans `ecrans/contacts.js` (ses styles : la section
« Contacts » de `maquette.css`). Il se pose par-dessus sans retoucher les écrans validés :

- une rubrique « Contacts » dans le tiroir, après Téléphone (sous « Plus » dans la variante barre), et la ligne
  « Contacts » de la feuille des boîtes de Mail y mène ;
- la liste : chercher par nom, e-mail ou numéro, Tous · Personnes · Organisations, d'où elle connaît chacun et combien,
  le dernier échange, « Lui présenter quelqu'un » ;
- la fiche en page : Écrire, Teams, Message ; ce qui l'identifie ; ce que Mika en sait, chaque fait oubliable après
  confirmation ; où vous vous croisez (vers Mail, Teams, Téléphone) ; « Oublier ce contact », ou pourquoi on ne le peut
  pas d'ici. Celle d'une organisation montre ses personnes, son domaine, son organisation Teams et ses adresses
  génériques ;
- dans Écrire, À, Cc et Cci proposent tous tes contacts, une ligne par adresse, une adresse générique marquée ; les
  destinataires choisis en puces.

Deux icônes neuves dans le sprite (`contacts`, `user-plus`), que `tools/icones.py` a tirées dans l'app
(`ic_m_contacts`, `ic_m_user_plus`) ; l'app en a fait l'écran (`frontend/Android/README.md`, « Contacts »). Routes : `#contacts`, `#contacts/tiroir` (le tiroir ouvert), `#contacts/claire`,
`#contacts/sophie` (deux adresses), `#contacts/lea`, `#contacts/ines` (seulement racontée), `#contacts/maman` (oubli
refusé), `#contacts/lumen` (une organisation), `#contacts/claire/fait/1` et `#contacts/claire/oublier` (les feuilles
ouvertes), `#mail/ecrire/a/<adresse>`, `#mail/ecrire/suggestions`.

**Proposé le 2026-11-23, pas encore validé** : l'Agenda (`output/agenda/CONCEPTION.md`), l'écran Agenda de la maquette
web (`frontend/Web/maquette/ecrans/agenda*.js`) avec les codes d'un agenda de téléphone (Google Agenda, Samsung Calendar),
sur les mêmes données fictives, lues dans `frontend/Web/maquette/ecrans/agenda-donnees.js`. Il se pose par-dessus sans
retoucher les écrans validés :

- une rubrique « Agenda » dans le tiroir, après Teams, avec ce qui attend ta décision (sous « Plus » dans la variante
  barre) ;
- la barre du haut : le mois en titre, qui déplie le mini-mois ; chercher ; « Aujourd'hui » (l'icône au numéro du jour) ;
  ⋮, qui porte les cinq vues (Planning · Jour · 3 jours · Semaine · Mois), « Agendas à afficher » (une feuille, groupée
  et cochée) et les invitations ; on balaie pour changer de période ; la ligne de l'heure ; le bouton + ;
- « À décider » en tête des vues : la proposition de Mika (Refuser · Modifier · Ajouter) et les deux invitations, avec
  la réponse qu'elle a préparée ;
- la fiche d'un événement en page ; le formulaire en plein écran (la date dans un calendrier, l'heure dans une liste) ;
  la question d'un événement récurrent ; partager un agenda (une feuille) ; la page des invitations ; la notification
  d'un rappel ou d'une invitation, dans le volet du téléphone dessiné ;
- Paramètres › Agendas (une ligne après Comptes Teams) : les comptes, la page d'un compte et d'un agenda, « Brancher un
  agenda » par sorte (système, Google et l'adresse à coller, Microsoft et son code, CalDAV, iCal) ; Outils › Droits :
  un groupe « Tes agendas », et le tableau de chacun en cartes ; dans le chat, la carte « Ajouter à ton agenda » et un
  rappel d'elle.

Fichiers : `ecrans/agenda.js` (l'écran, ses vues, ses feuilles, la fiche, le volet), `agenda-edition.js` (le formulaire),
`agenda-parametres.js`, `agenda-droits.js`, `agenda-chat.js`, `agenda.css` ; et `agenda-crochet.js`, chargé juste après
`maquette.js`, qui garde la vue d'origine de chaque écran (`A.vue(id)`) pour que l'Agenda ajoute ses routes à
Paramètres, Outils et au chat. Onze icônes neuves dans le sprite : `agenda` (celle du web), `today` (le numéro du jour
s'écrit par-dessus), `repeat`, `video`, `server`, `eye-off` (celles du web), et les cinq vues `view-list`, `view-day`,
`view-3`, `view-week`, `view-month` ; `tools/icones.py` ne les a pas encore tirées dans l'app. Routes : `#agenda`,
`#agenda/jour`, `/3jours`, `/semaine`, `/mois`, `/mois-deplie`, `/agendas`, `/agendas/<agenda>`, `/tiroir`,
`/chercher/<mot>`, `/invitations`, `/evenement/<id>` (et `/mot`, `/rappel`, `/supprimer`), `/nouveau`,
`/modifier/<id>` (et `/question`), `/dupliquer/<id>`, `/partager/<agenda>`, `/notification` ; `#parametres/agendas`
(`/<compte>`, `/<compte>/<agenda>`, `/brancher`, `/brancher/<sorte>`, `/brancher/google/coller`,
`/brancher/google/sans-appli`, `/brancher/microsoft/code`, `/brancher/caldav/trouves`…) ; `#outils/droits/<agenda>` ;
`#chat/agenda`. Captures : `output/agenda/maquette-android/` (refaites par `captures.cjs`).

## L'ouvrir

```bash
python3 -m http.server 8792 --bind 127.0.0.1     # depuis la racine du dépôt
# puis http://127.0.0.1:8792/frontend/Android/maquette/
```

Sur un ordinateur, le téléphone (un S25, 384 × 832 dp) est à droite et le panneau à gauche :

- **Variantes à comparer** : la navigation par barre du bas (Chat · Mail · Teams · Carte · Plus) ou par tiroir (le
  chat en plein écran, comme aujourd'hui) ; le thème.
- **Cet écran** : ce qu'il montre et ce qu'il reste **à trancher** (les questions de placement).
- **Tous les écrans** : un lien par écran.

Ouverte sur une fenêtre de 760 px ou moins, la maquette prend tout l'écran, sans le cadre ni le panneau.

Paramètres d'adresse : `?theme=dark|light`, `?nav=barre|tiroir`, puis la route après `#` (`#chat`, `#chat/accord`,
`#chat/pro`, `#mail`, `#mail/lire/m-claire`, `#mail/brouillon/d-lefevre`, `#teams/d/claire`, `#carte`,
`#carte/voyage/alpes`, `#telephone/c/rando`, `#outils`, `#plus`, `#parametres`, `#mika`, `#contacts`…).

## Ce qu'elle lit ailleurs, sans le copier

- les personnes, l'état de Mika et ses portraits : `frontend/Web/maquette/donnees.js` ;
- le fond de carte (la France simplifiée, © OpenStreetMap) : `frontend/Web/maquette/ecrans/carte-fond.js` ;
- les agendas, leurs comptes et leurs événements (proposé) : `frontend/Web/maquette/ecrans/agenda-donnees.js` ;
- les portraits pré-rendus : `app/src/main/assets/avatar/` (sous licence, non versionnés ; sans eux, un rond coloré) ;
- la police Inter de la console, si Roboto manque.

## Les fichiers

| Fichier | Rôle |
|---|---|
| `index.html` | le panneau, le cadre du téléphone, les icônes |
| `maquette.css` | les jetons (clair, sombre) et les composants Material 3 |
| `maquette.js` | le moteur : routes, barre du haut, barre du bas ou tiroir, feuilles, menus, fenêtres, son visage, le panneau |
| `ecrans/<écran>.js` | un écran chacun : chat (avec la recherche, les fichiers et « Ce qu'elle fait »), mail, teams, carte, telephone, outils, plus (avec Paramètres) |
| `ecrans/chat-effort.js`, `ecrans/carte-avis.js`, `ecrans/contacts.js` | des propositions posées par-dessus les écrans validés, sans les retoucher |
| `ecrans/agenda*.js`, `ecrans/agenda.css` | l'Agenda (proposé), posé de même ; `agenda-crochet.js` garde les vues d'origine |
