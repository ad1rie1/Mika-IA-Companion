# Mika pour Android

Le client de tous les jours sur un téléphone (ADR 0235) : d'abord la conversation avec Mika — on lui écrit, on lui
envoie des photos et des fichiers, elle répond, et comme dans une vraie messagerie elle peut écrire la première quand
l'application est fermée —, puis, par le tiroir, ce que fait le client web `frontendv2/` : Mail, Teams, Carte,
Téléphone, Outils et Paramètres, pour la personne connectée. On voit aussi ce qu'elle fait : sa ligne d'état sous son
nom, son visage au bout de chaque barre du haut, et l'écran « Ce qu'elle fait ».

Le serveur est `backendv2/` (`python -m mika serve`). La conversation passe par
[`backendv2/docs/protocole-chat.md`](../../backendv2/docs/protocole-chat.md), le reste par l'API par personne
[`backendv2/docs/protocole-moi.md`](../../backendv2/docs/protocole-moi.md) ; les décisions : ADR 0062, puis 0235. La
maquette validée des écrans est dans [`maquette/`](maquette/) (son `LISEZMOI.md`) : on navigue par le tiroir.

## Ce que fait l'application

- **Connexion** avec le compte que tu utilises sur la page web de Mika (nom d'utilisateur et mot de passe). Le
  mot de passe sert une fois : le serveur rend un jeton propre à ce téléphone, gardé chiffré par le Keystore
  Android. La session dure jusqu'à ce que tu te déconnectes, ou qu'un opérateur révoque le téléphone.
- **La conversation** : bulles, heures, séparateurs de date, état de chaque message (en attente, envoyé, lu,
  refusé + « Réessayer »), gras et code mis en forme, « Mika écrit… ». Un message tapé hors ligne part tout seul
  au retour du réseau, même si l'application a été tuée entre-temps. Sous une réponse qui n'est pas venue
  (`no_reply`, `too_late`), « Le lui redemander » renvoie le même texte et les mêmes fichiers comme un nouveau
  message ; la bulle d'origine reste. La barre du haut : ☰ (le tiroir — ailleurs que dans le chat, un point rose sur ☰
  et sur « Chat » dit qu'un accord y attend ou qu'elle a écrit depuis ton dernier lu), son visage et sa ligne d'état
  (« Ce qu'elle fait »), la loupe (« Rechercher », plus bas : la conversation d'abord) et ⋮ (Ce qu'elle fait, « Fichiers échangés »,
  Paramètres ; en mode pro d'abord Fils de travail, Régler ce fil, Archiver ce fil).
- **Ses notes de carte** (ADR 0196, `protocole-chat.md` § 4) : quand elle a cherché des lieux ou calculé un trajet
  (`look`), montré une carte (`map`), créé ou changé un voyage (`trip`), sa réponse emporte une note, gardée avec le
  message (base : la colonne `notes`, avec ce qu'elle ouvre, `ref`) ; sous sa dernière bulle, chacune devient une
  carte miniature — celle de la Carte (`MapNoteCard`) : d'abord le plan, puis la vraie carte non interactive, quatre à
  la fois au plus, lue une fois pour la session avec l'écran Carte — qui attend que sa dernière bulle soit dite, et
  qu'un toucher ouvre dans la Carte (le voyage, Itinéraire sur un trajet, Explorer sur des lieux). Une sorte inconnue
  s'ignore ; une note vidée (un regard oublié, un voyage supprimé) ne montre rien ; six au plus par message. Un
  voyage dont la note dit un changement plus récent que ce qu'on en a lu se relit. La bulle 📍 ne change pas.
- **Le mode pro** (ADR 0116), pour une opératrice : la pastille « Pro » dans le champ (retenue sur le téléphone)
  envoie le message en mode pro (`chat.mode`). Pendant qu'elle travaille, une carte montre ses outils en direct
  (trames `tool` : en cours, ✓ ou ✗, durée ; dépliables en texte brut), jamais gardée en base ; elle se replie au-dessus
  de la réponse, une seule bulle en Markdown (tableaux compris) que sa voix ne lit pas. L'historique montre la ligne
  de ses outils. Pastille allumée, le travail prend tout l'écran : Mika quitte le fond (sa 3D ne tourne plus, son
  visage reste dans la barre), le fil n'a plus de bande sous son visage, ses réponses et ses cartes prennent toute la
  largeur, en texte plus serré. Une réponse depuis une notification part toujours en message ordinaire. Deux accords
  ou plus au-dessus du champ : « Tout accepter » (voir les cartes d'accord).
- **Les fils de travail** (ADR 0164) : pastille allumée, la conversation devient un client à plusieurs fils, chacun son
  contexte — Mika n'y relit que les messages du fil, sous son titre et sa petite description. Le fil avec elle est
  caché ; pastille éteinte, il revient seul (aucun message d'un fil de travail). Une barre au-dessus du fil dit le fil
  ouvert (toucher son nom le règle : titre, description, archivé) ; « Fils » ouvre la liste (titre, sinon le début du
  premier message ; archivés repliés à part), « Nouveau » un fil neuf. Le fil ouvert est retenu sur le téléphone. Dans
  le champ : `/clear` (ou `/nouveau`) ouvre un fil neuf sans rien effacer, `/renommer <titre>`, `/description <texte>`,
  `/archiver`, `/desarchiver`, `/aide` ; `//` en tête envoie le message avec un seul `/`. Chaque message garde son fil
  (`chat.strand`, base version 5) ; un fil ouvert ici dont le serveur a plus de messages les demande
  (`strand_history`). Code : `data/chat/Strands.kt` (pur), `ui/chat/StrandParts.kt`.
- **Les cartes d'accord** (ADR 0064, 0235 point 4) : ce qui attend ta décision se replie au-dessus de la barre de
  saisie sur **une seule ligne rose** — « 1 accord · 2 brouillons à relire » et le compte à rebours de l'accord le plus
  proche (« 4 min », en ambre sous cinq minutes) —, Mika restant visible. Repliée par défaut, elle se déplie toute
  seule quand un accord arrive pour la première fois (une liste redite à la reconnexion ne la rouvre pas) ; plus rien
  n'attend, elle repart repliée. Dépliée (bornée à la moitié de la place, ce qui est sous la ligne défile) : les cartes
  d'accord telles qu'avant — ce qu'elle veut faire, **exactement ce qui partira** (en texte brut, à chasse fixe,
  jamais interprété), le compte à rebours (« expire dans 4 min ») et deux boutons, « Accepter » et « Refuser ». Seul
  le bouton décide : un « oui » tapé dans la conversation ne vaut jamais accord. « Accepter » s'éteint quand la carte
  est bloquée (la raison est dite), expirée, incomplète, hors ligne, ou quand une décision est déjà partie ; hors
  ligne, rien n'est mis en file. Le sort de la décision s'affiche un instant (« Refusé : rien ne partira. »). Puis
  **ses brouillons à relire**, en liens vers l'écran où ils se décident (ADR 0191) : une carte d'un mail de sa boîte
  qui nomme son brouillon (`capability` `email.send`, `draft`) mène au brouillon dans Mail (`Route.MailDraft`), une
  réponse Teams (`teams.send`) à sa discussion (`Route.TeamsThread`, où sa carte rose se décide ; sans discussion
  connue, « Ses brouillons ») — jamais leurs boutons ici. Les brouillons comptés sont ceux des pastilles
  (`counts.mail`, `counts.teams` de `GET /api/moi`) et des cartes, sans compter deux fois le même : la ligne relit
  ses brouillons (`mail/drafts`, `teams/replies`) quand les pastilles ou les cartes changent et quand on la déplie,
  pour les nommer (« Mail · Re: Présentation → Claire Dubois ») ; au-delà de quatre par écran, ou si la lecture
  échoue, un lien vers la liste dit combien. **« Tout accepter »** (ADR 0170), en mode pro pour une opératrice, au-dessus
  de deux accords ou plus : chaque accord montré que « Accepter » permettrait, un à la fois (chacun attend sa réponse,
  ou la liste qui suit, avant le suivant), avec l'empreinte de la carte montrée ; une carte qui a changé entre-temps,
  bloquée, expirée ou hors ligne reste à la personne, et un brouillon ne part jamais ainsi. Trames : `approvals` (la
  liste entière, qui remplace la précédente ; chaque connexion repart d'une liste vide, le serveur n'envoie la liste à
  l'ouverture que si elle n'est pas vide ; une carte dit aussi `capability` et `draft`), `approval_result` (le sort),
  et côté app `approval` (`id`, `decision`, l'empreinte `digest` de la carte montrée).
- **Rechercher** (`Route.Search`, le Ctrl K du frontendv2 devenu un écran) : la loupe du chat, ou « Rechercher
  partout » du tiroir. Un champ en haut, des puces (Tout, Conversation — celle de la loupe —, Mail, Teams, Écrans), les
  résultats groupés : **dans la conversation**, les messages gardés sur ce téléphone (sans accents ni casse, dans tout
  leur texte, le passage trouvé surligné, le plus récent d'abord, dix au plus) ; pour une opératrice, **ses fils de
  travail** (par leur titre, leur description, leur premier message) et leurs messages ; **Mail**
  (`mail/messages?q=`) et **Teams** (`teams/conversations?q=`, le nom d'une discussion) au serveur, à partir de deux
  lettres et après une pause de frappe (0,45 s), une recherche dépassée abandonnée ; **les écrans** et pages de l'app
  (Mail › Ses brouillons, Paramètres › Boîtes mail…), classés — le titre qui commence par ce qu'on cherche, puis un de
  ses mots, puis le reste. Toucher un message ramène au chat (son fil de travail en mode pro), le fil s'y porte et le
  surligne un instant ; parti entre-temps, une note le dit. Un mail, une discussion, une page s'ouvrent par-dessus la
  recherche ; une rubrique, à sa place.
- **Fichiers échangés** (`Route.Files`, ADR 0215) : ⋮ du chat. Ce qu'elle t'a envoyé et ce que tu lui as envoyé, dans
  les messages gardés sur ce téléphone (fils de travail compris), tant que le serveur le garde ; puces Tout · Les
  siens · Les tiens ; les images en grille (bord rose : les siennes ; touchée, elle s'ouvre en grand ; un appui long :
  ses gestes), les documents en liste (taille, de qui, quand ; ⋮). Chacun : « Enregistrer » (Téléchargements/Mika),
  « Ouvrir avec… », « Voir dans la conversation ». Tes pièces se reprennent par `/files/<id>` comme les siennes : le
  fil relu leur donne de quoi (`id`, `url`, `available`), et une pièce envoyée d'ici l'apprend en gardant son fichier
  sur le téléphone (sa vignette) ; d'ici là, « sur ce téléphone seulement ». Une pièce retirée dit « plus disponible ».
- **Envoyer des fichiers** : Photos, Appareil photo, Fichier (images, audio, texte, CSV, Markdown, JSON, PDF),
  jusqu'à 5 fichiers de 5 Mo par message (11 Mo au total). Les photos trop lourdes sont réduites en JPEG (côté
  long ≤ 2 048 px), ce qui retire aussi l'EXIF et la position GPS. Le brouillon (texte et fichiers) survit à la
  fermeture de l'application.
- **« Partager vers Mika »** depuis la galerie, le navigateur ou n'importe quelle application : le texte et les
  fichiers arrivent dans la barre de saisie. Partagé sans être connectée, tout attend la connexion.
- **Ses fichiers à elle** : vignette pour une image (touchée, elle s'agrandit), puce avec nom et taille sinon ;
  « Enregistrer » (dans Téléchargements/Mika) ou « Ouvrir avec… ».
- **« Ce qu'elle fait »** : humeur, corps (sommeil, énergie, où elle est, moment de la journée), estime de soi,
  ce à quoi elle repense, le rêve de la nuit, son dernier journal, qui elle est devenue, ce qu'elle sait de toi
  (sous quel nom elle te reconnaît et, si ta fiche t'est ouverte, où vous en êtes, son ton, tes intérêts, ce à
  quoi elle fait attention), ce qu'elle t'a promis, ses besoins, et ses projets en cours si tu es propriétaire.
  Une carte sans données n'apparaît pas.
- **Mika en fond** : derrière la conversation, Mika en 3D native, dans une lumière qui suit son humeur. Elle vit
  (souffle, gestes, regard, clignements, cheveux), te salue à la mesure de ton absence (un hochement après un
  moment, un coucou après sa nuit, jamais joyeux si elle est fâchée) et s'endort la nuit (lumière
  bleue, étoiles en thème sombre). Désactivable (Paramètres › Apparence). Voir
  [Mika en fond](#mika-en-fond-3d-native).
- **« Lui dire où je suis »** (ADR 0119, coupé par défaut) : application ouverte, la position du téléphone part à
  Mika — les coordonnées exactes et le nom du lieu trouvé par le téléphone (`Geocoder`). Voir
  [Sa position](#sa-position).
- **« Lui montrer mes messages »** (ADR 0120, coupé par défaut) : les messages WhatsApp et SMS que le téléphone affiche
  partent à Mika, qui s'en souvient ; elle peut proposer une réponse, qu'une notification te demande d'autoriser. Voir
  [Ses messages](#ses-messages).
- **Mail** (ADR 0235, l'API par personne : [`protocole-moi.md`](../../backendv2/docs/protocole-moi.md) § 3), une
  rubrique du tiroir. Tes boîtes et celles qu'on te partage, à leur niveau (lire, préparer, s'en servir). Le titre est la
  vue et ouvre une feuille : toutes les réceptions (sans les boîtes qu'on ne te partage qu'en lecture, qui s'ouvrent en
  les nommant, ADR 0200), chaque boîte, les dossiers de la boîte choisie et leurs non-lus, « Ses brouillons », « Régler
  les boîtes ». Des puces filtrent (Réponse attendue et son compte, Non lus, Suivis, Où Mika est passée), la loupe
  cherche. Les lignes sont groupées par jour ; ton non-lu (le point indigo) reste à part de ce qu'elle en a fait (en
  rose : réponse attendue, son brouillon, « lu par Mika ») et, en gris discret, d'où en est son tri (le champ
  `triage` : « lu par son tri », « en attente de son tri » jusqu'au relevé suivant, « tri deviné » quand le modèle
  n'a pas pu le lire ; rien pour un envoi en masse). La page suivante se lit en fin de liste : jusqu'à cent
  lignes, la liste se relit d'un coup depuis le début, une page de plus, et au-delà la page qui contient la première
  ligne pas encore lue — un mail rangé entre-temps ne fait rien sauter, et une page qui arrive ne défait pas un
  rangement fait pendant sa lecture. Tirer relit, et la liste se relit chaque minute. Un appui long sélectionne (archiver, lu ou non lu, suivre, corbeille, déplacer) ;
  glisser une ligne vers la gauche ou vers la droite la met à la corbeille (le même geste `trash`, là où la sélection
  la rangerait : ni dans une boîte qu'on te partage sans t'en servir, ni dans la Corbeille elle-même, ni sur « Envoyés »), elle
  reste écartée le temps que le serveur réponde, revient s'il refuse, et « Annuler » la remet dans son dossier (`move`) ;
  « Relever maintenant » est dans le menu.
  - **La liseuse** montre l'objet et ses marques, l'expéditeur et les destinataires, « Ce qu'elle en sait » (son
    résumé ; son titre dit où en est son tri à la place de « remarqué », et le cadre paraît aussi pour un mail que son
    tri n'a pas encore lu, ou dont il n'a pu que deviner l'importance ; il dit aussi ce que tes consignes de tri en ont
    fait, `her.alert` et `her.filed` : te prévenir, le ranger dans un dossier, ADR 0243), le texte du mail (citations en retrait, liens), ses pièces (Enregistrer dans Téléchargements/Mika, ou
    Ouvrir avec…) et le lien vers son brouillon. Le mail devient lu à l'ouverture selon `read_on_open`. En haut :
    archiver, corbeille, non lu, et dans ⋮ suivre, déplacer, répondre à tous. En bas : Répondre, Transférer et
    « Préremplir avec Mika » (sa réponse demandée se guette sur place). Un mail HTML se montre dans sa mise en page
    (`/mail/frame`, ADR 0242) : une WebView sans script ni réseau, à la hauteur de son contenu, qui ne navigue jamais
    (un lien touché s'ouvre dehors). Ses images distantes restent masquées sous un bandeau (cette fois, ou toujours pour
    cet expéditeur si tu es propriétaire) ; un cadre qui ne se charge pas rend son texte.
  - **Ses brouillons** se rangent en trois : à décider, partis, refusés. Un brouillon montre exactement ce qui partira,
    pourquoi elle l'a écrit, sa voix, le passage « [À COMPLÉTER » surligné qui bloque l'envoi, et le mail d'origine.
    Les gestes : Refuser (une note facultative), Lui demander une autre version, Retoucher, Envoyer (tel qu'il a été lu, par
    son `digest`). Dans une boîte qu'on te partage, il attend son propriétaire.
  - **Écrire** sert au mail nouveau, à la réponse (à tous), au transfert et à la retouche de son brouillon. On y choisit
    la boîte d'envoi, les destinataires (À, Cc, Cci, ses correspondants proposés), l'objet, le texte et la citation.
    Les pièces viennent du sélecteur de documents (25 Mo par pièce, dix pièces, 50 Mo en tout) et partent en
    `multipart`. « Préremplir avec Mika » est offert en réponse. Ta réponse repartie de son brouillon passe par lui
    s'il attend encore ; refusé ou plus là, elle part comme une réponse ordinaire ; parti, approuvé ou en échec
    entre-temps (envoyé d'ailleurs, ou une réponse du serveur perdue puis ta retouche), rien de plus ne part et l'écran
    le dit ; ses brouillons illisibles (le réseau), rien ne part non plus. Chaque geste a sa clé d'envoi : un double
    appui ne part qu'une fois. Quitter un mail commencé demande confirmation, sauf pendant son envoi : « Abandonner »
    ne s'offre plus, on sort, l'envoi va au bout. Son sort se dit en toast où qu'on soit (« Ton mail n'est pas parti :
    … », le motif du serveur), et le refus reste aussi sous le formulaire si l'écran est encore là. Une notification
    touchée ou un partage vers Mika remplacent les écrans sans rien demander : le mail commencé attend alors, en
    mémoire le temps de la session, et revient tel quel quand on rouvre la même écriture (même mode, même mail, même
    brouillon) ; quitté en plein envoi, il n'attend que si l'envoi est refusé. Il s'efface à l'envoi, à l'abandon
    confirmé et à la déconnexion. Une écriture quittée avant d'avoir fini de charger (ou « Préremplir » qui répond
    tard) ne pose rien dans celle ouverte ensuite, et un ordre de retour (parti, archivé, décidé) ne referme que
    l'écran où son geste a commencé, jamais le même mail ou le même brouillon rouvert plus tard. Le texte tapé dans le champ d'une discussion Teams ou d'une conversation
    du téléphone survit de même (par discussion, le temps que l'app reste ouverte).
- **Teams** (ADR 0235, l'API par personne : [`protocole-moi.md`](../../backendv2/docs/protocole-moi.md) § 4), une
  rubrique du tiroir. Tes comptes Teams et ceux qu'on te partage, à leur niveau : le compte est en sous-titre (le tien,
  qui y est connecté ; partagé, son niveau et son propriétaire), et le titre ouvre une feuille pour choisir un compte
  ou tous, « Ses brouillons », « Régler les comptes Teams ». La loupe cherche. « Ses brouillons » paraît en bandeau rose
  quand l'une de ses réponses attend ta décision. Les discussions (un tête-à-tête au nom de l'autre personne, un
  groupe à son nom) disent leur dernier message, leur heure, une mention de toi, et en rose une réponse d'elle en
  chemin ; tirer relit, la liste se relit chaque minute. Pas de « nouvelle discussion » : l'extension « Mika · Teams »
  ne sait que répondre. Ni non-lus, ni réactions, ni pièces d'un message : l'API ne les dit pas.
  - **Un fil** : les autres à gauche (leur nom dans un groupe), toi à droite — « Toi » seulement sur un compte à toi ;
    sur un compte qu'on te partage, les messages de son propriétaire sont à gauche, à son nom —, tes mentions marquées,
    « Messages plus anciens » en haut, tes messages en attente avec leur état (en file, posé, pas parti : « Le
    réécrire »), « rédigé avec Mika » sous ce qui est parti d'elle. Ses réponses sont en carte rose au-dessus du champ :
    qui attend ton accord se refuse (une note facultative), se retouche ou s'envoie telle qu'elle a été lue (son
    `digest`), et ⋮ lui demande de la reprendre ; posée dans Teams ou en file, la carte le dit ; à une réponse que tu as
    donnée toi-même, la sienne n'a plus lieu (ADR 0199). Le champ : ✦ « Préremplir avec Mika » à gauche (sur le dernier
    message de quelqu'un d'autre ; ce que répond le serveur, « déjà demandée » ou « une réponse en chemin », est dit tel
    quel, puis sa réponse se guette toutes les dix secondes, une demi-heure au plus), envoyer à droite (une clé d'envoi
    par geste), et dessous « part par l'extension, sous le nom de … ». Sur un compte qu'on te partage, tes messages en
    file et ses réponses en file disent aussi qu'ils partent sous le nom de la personne du compte, et sa réponse qui
    attend « attend l'accord de son propriétaire ». Une extension muette depuis deux heures, Teams
    coupé ou le compte décoché se disent au-dessus du champ. Un compte qu'on ne te partage qu'en lecture n'a pas de
    champ (en lecture et préparation, « Préremplir » seul). Le fil se relit toutes les vingt secondes. ⋮ : « Comment ça
    part » (Outils).
  - **Ses brouillons** : une carte par réponse (sa discussion, son texte, son état, comment ça part, demandée ou
    d'elle-même, son heure, la note d'un refus). Toucher une carte ouvre sa discussion ; celle qui attend ta décision
    se décide aussi d'ici ; sur un compte qu'on te partage, elle attend l'accord de son propriétaire, et la carte dit
    qui décide.
- **Carte** (ADR 0193 à 0196, 0235 ; l'API par personne : [`protocole-moi.md`](../../backendv2/docs/protocole-moi.md)
  § 10), une rubrique du tiroir, trois onglets sous la barre du haut (Explorer · Itinéraire · Voyages) qui se remplacent
  sans s'empiler. La carte est celle que sert ce serveur, et lui seul (voir [La carte](#la-carte-maplibre)) ; sans fond
  prêt, hors de sa zone, ou quand elle ne se dessine pas ici, un plan dessiné de ce qu'elle montre la remplace, sa note
  dit pourquoi.
  - **Explorer** : la carte prend l'écran, la recherche flotte dessus — « Autour de moi » au bout du champ (ta dernière
    position, celle de ton téléphone ; éteint, « Dans cette zone » : ce que la carte montre au-dessus de la feuille,
    recherché de nouveau quand on la déplace), les catégories du serveur en puces. Les lieux se cherchent dans l'index
    du serveur (rien ne sort) ; une adresse (Géoplateforme, relayée : seul le texte part) seulement si le texte en a
    l'air (un chiffre, ou cinq caractères quand l'index n'a rien trouvé), après 0,7 s sans frappe, une fois par texte.
    Les résultats montent du bas, dans une feuille à un peu moins de la moitié de l'écran ; autour de toi, la carte se
    cadre sur eux, et la légende dit jusqu'où l'index est allé (« autour de ta position », ou au-delà de 20 km « les plus
    proches que l'index connaisse · jusqu'à … km »). Un lieu touché, dans la liste ou sur la carte, ouvre sa fiche à la
    place de la liste (« retour » rend la liste) : son nom, sa sorte, sa ville, sa distance ; **Itinéraire** (jusqu'ici),
    **Au voyage**, **En parler** (à Mika : une phrase dans le champ du chat, à compléter, puis le chat s'ouvre). Sans
    index, sans adresses (503) ou trop d'adresses d'affilée (429), l'endroit qui en a besoin dit le message du serveur,
    le reste marche.
    **Au voyage** ouvre la feuille « Ajouter au voyage » : tes voyages (huit au plus), leurs dates en court (« 3–7
    avr. ») ; un toucher l'ajoute à la fin de son dernier jour (« Ajouté au voyage « … », jour 3. », ou « Déjà
    ajouté » pour la même clé), « Nouveau voyage… » ouvre la fenêtre avec le lieu pour premier arrêt.
  - **Ce que Mika a cherché ou montré** (un regard, `Route.Carte(tab, look = "<seq>")`, qu'ouvrent les miniatures du
    chat) : dans Explorer, ses lieux en rose (« Mika te l'a proposé ») à la place des résultats, son tracé tel
    qu'elle l'a gardé, « Ouvrir dans Itinéraire » pour un trajet, « Ouvrir le voyage » s'il en montrait un ; chercher
    autre chose le quitte. Oublié, ou pour quelqu'un d'autre (404) : « Ce que Mika avait cherché n'est plus là », et la
    carte revient au fond ; une autre panne se réessaie.
  - **Itinéraire** : la carte prend l'écran, ses points et son résultat montent du bas. Ses points (A, les étapes, B ; 20
    au plus) : un lieu de l'index, une adresse (si le texte en a l'air, après 0,7 s sans frappe, une fois par texte —
    les mêmes qu'Explorer), « Ma position » (la dernière de ton téléphone ; un itinéraire vide part d'elle) ; ajouter
    une étape, la retirer, inverser. Voiture, vélo ou à pied ; « Sans péage », « Sans autoroute », « Sans ferry » en
    voiture seulement. Le trajet se calcule quand tous ses points sont choisis, et pas deux fois le même (20 trajets par
    minute et par compte, 429 au-delà) : la durée en grand, la distance, ce qu'il traverse et l'heure d'arrivée si tu
    pars maintenant, le tracé sur la carte, les consignes repliées, d'où il vient. **En faire un voyage** (le voyage et
    ses arrêts au jour 1, une clé par intention : redit après une panne, le même voyage ; fini avec l'onglet à l'écran,
    le voyage s'ouvre ; fini pendant qu'on est ailleurs, un toast « Voyage créé » avec **Ouvrir**, et rien n'emmène tout
    seul), le **GPX** fait sur le téléphone
    (ses points et son tracé, dans Téléchargements/Mika), **À Mika** (« Regarde ce trajet : … » dans le champ du chat,
    puis le chat). Un point retapé rend le trajet montré passé : il pâlit, ni tracé, ni consignes, ni voyage, ni GPX
    avant de le choisir dans ses propositions. Le trajet que Mika a calculé (un regard) se pose tel qu'elle l'a gardé —
    ses points, son mode, ce qu'il évitait, son tracé en rose, « Ce que Mika a calculé » — et ne se recalcule qu'au
    premier changement (ou « Recalculer ») ; son mode et ses cases se montrent sans devenir les tiens : un trajet que tu
    commences (« Itinéraire jusqu'ici ») reprend les tiens.
  - **Voyages** : tes voyages en cartes, le plus récemment changé d'abord — leur miniature (ses arrêts reliés ; la vraie
    carte non interactive, quatre à la fois au plus, sinon son plan), leurs dates, leurs jours et arrêts, « préparé avec
    Mika », « passé » ; **Nouveau voyage** en bouton flottant (un titre, une date de départ facultative, le mode, ce qu'il
    évite en voiture).
  - **Un voyage** (`Route.Trip`) : la carte en haut — ses arrêts numérotés, les siens en rose, le trajet de ses tronçons
    quand il se calcule (relu 1,5 s après le dernier geste ; d'ici là, ses arrêts reliés en pointillés, jamais le trajet
    d'avant) —, puis l'éditeur jour par jour : les tronçons (« 2 h 15 · 207 km »), chaque arrêt (« ajouté par Mika » en
    rose, sa note à part), sa **poignée** (la glisser d'un jour à l'autre ; la toucher : « Monter d'une place »,
    « Descendre d'une place », aussi en actions d'accessibilité, et le lecteur d'écran dit où il est arrivé), **Noter**
    (le champ en place ; vidée, la note s'efface), **Retirer**, **Ajouter un arrêt** (un lieu près de ce jour, une
    adresse, ta position, une note), **Ajouter un jour**. **Sur la route** (le bouton sous la carte, ou ⋮) : les
    catégories du serveur, les lieux à moins de 10 km du trajet, « jour N » en tête de leur ligne, ajoutés au bon jour
    (avant l'arrêt qu'on atteint après eux), en épingles secondaires sur la carte (en toucher une ramène sa ligne) ; il
    ne se recherche que si le trajet a changé, et jamais pour un panneau fermé ; quitter le voyage le referme (une
    rotation le garde). Dans la barre, une fois le voyage lu : ✦ **Demander à Mika** (une phrase dans le champ du chat),
    ⋮ **Optimiser l'ordre** (chaque jour de trois arrêts ou plus ; départ et nuit ne bougent pas), **GPX du voyage**
    (celui du serveur, dans Téléchargements/Mika, demandé après les gestes en cours : il a l'ordre que l'écran montre),
    **Le voyage…** (titre, date, mode, ce qu'il évite : seulement ce qui a changé), **Sur la route**, **Supprimer le
    voyage** (confirmé). Les gestes se font l'un après l'autre et se montrent avant que le serveur les dise ; glisser
    retrouve la ligne sous le doigt par sa clé, dans la liste du moment (des tronçons arrivés, « Sur la route » ouvert,
    un autre ordre n'y changent rien) ; un arrêt lâché à sa place n'envoie rien ; chaque ajout a sa clé d'envoi (un
    double appui, un réessai ne l'ajoutent qu'une fois) ; un geste refusé — « La situation a changé » (409) compris — se
    dit, annule ceux qui attendaient derrière lui, et le voyage relu montre où il en est. Le voyage se relit après le
    dernier geste fini — une lecture partie avant lui (celle d'un geste d'avant, du retour sur l'écran) est suivie
    d'une autre, comme le web ; une relecture qui échoue après des gestes tous aboutis garde ce qu'ils ont posé (le
    serveur l'a écrit), le dit, et le voyage se relit au retour sur l'écran ; après un refus, le dernier lu fait foi.
    Supprimé, ou pas à toi (404) : « Ce voyage n'existe pas ».
  - Pas fait, ou autrement que la maquette : le bouton « Distance » de la liste (l'index classe déjà, en mêlant
    pertinence et distance), les boutons de zoom du web (on pince) ; la note d'un arrêt de Mika se lit à part, sans
    guillemets (la règle du web : « ajouté par Mika » n'est qu'une marque, tu as pu écrire ou corriger la note) ; la
    carte d'un voyage de la liste dit ses jours et ses arrêts, pas ses kilomètres (la liste n'a pas son trajet) ;
    « Sur la route » est un panneau en tête de l'éditeur plutôt qu'une feuille (ses épingles restent visibles) ; la
    date d'un voyage est un départ (le serveur ne garde que lui), pas un intervalle.
- **Téléphone** (ADR 0235, l'API par personne : [`protocole-moi.md`](../../backendv2/docs/protocole-moi.md) § 5), une
  rubrique du tiroir, deux onglets (Messages, Position). Sous le titre, l'état de tes téléphones — « Ce téléphone ·
  samsung SM-S931B », « 2 téléphones · dont celui-ci », et s'il en est un qui ne reçoit pas les notifications — : un
  état, pas un sélecteur (ADR 0233), qui mène à Paramètres › Téléphones. Pas d'onglet Notifications tant que
  l'application ne lit que les messageries (ADR 0233).
  - **Messages** : ce que l'application a lu dans WhatsApp et Messages (de tous tes téléphones : le serveur ne dit pas
    encore lequel a reçu quoi), la plus récente d'abord — le groupe ou qui écrit, la pastille de l'appli, le dernier
    message, l'heure, et en rose sa réponse en chemin (partie, copiée, ou en échec en rouge). « Mika propose une
    réponse » en bandeau rose quand l'une attend ton geste (`counts.phone`), avec son texte et son échéance si ce
    téléphone l'a reçue. Tirer relit, la liste se relit chaque minute. Vide, l'écran dit pourquoi : un compte qui n'est
    pas une de ses propriétaires (et le lien vers Position), « Lui montrer mes messages » coupé ici (et le lien vers
    Paramètres › Ses messages), ou rien encore.
    Pas de compteur de non-lus : l'API ne les dit pas.
  - **Un fil** : les autres à gauche (leur nom dans un groupe), toi à droite ; ses propositions en carte rose à leur
    place dans le fil, avec leur sort ; « Messages plus anciens » lit jusqu'aux 100 que rend le serveur. **Répondre
    d'ici**, ce que le web ne peut pas : sur une proposition que ce téléphone a reçue, Ignorer · Écrire autre chose
    (elle passe dans le champ, ta version part à sa place) · Envoyer ; et ton propre texte dans le champ « Répondre par
    WhatsApp ». Tout part par l'action « Répondre » de la notification de l'appli gardée en mémoire (le geste vaut
    accord, ADR 0120 ; voir [Ses messages](#ses-messages)) ; sans elle, le texte est copié et l'appli s'ouvre pour le
    coller — la ligne sous le champ dit lequel des deux, et à qui : « part par la notification de WhatsApp, à Léa ».
    L'action gardée retient le nom que sa notification donnait à la conversation ; s'il n'est pas celui du fil montré
    (deux téléphones du compte peuvent donner la même clé à deux conversations, que le serveur range dans un seul fil),
    rien ne part d'ici : la ligne le dit en rouge, le texte est copié et l'appli s'ouvre — tu y choisis la conversation.
    Une proposition reçue par un autre téléphone, ou déjà réglée, ne se décide pas d'ici. Une fois sa proposition réglée
    (envoyée, laissée, partie depuis sa notification), le champ ne la garde pas : inchangée, elle s'en va ; retouchée,
    elle reste et l'écran dit qu'elle partira comme ton message. Si elle n'attend plus quand tu envoies ta version, rien
    ne part tout seul. Un geste parti va au bout (son règlement sur le téléphone, son sort au serveur) même si l'écran
    se ferme ; son sort ne se dit que sur l'écran où il a commencé (jamais rejoué sur un autre fil, ni l'appli rouverte).
    Ce que tu as décidé se montre tout de suite, et son sort part aussitôt au serveur. Le fil se relit toutes les vingt
    secondes. Pas de ✦ « Préremplir » : le serveur n'a pas cette route pour le téléphone ; ⋮ : « Lui en parler dans le
    chat ».
  - **Position** : ta dernière position sur la vraie carte quand le serveur en sert une qui la couvre — centrée sur ton
    point, au zoom qui montre le cercle de sa précision ; dans la page qui défile, le doigt reste à la carte —, sinon sur
    un plan dessiné (le point et le cercle, à l'échelle, 300 m au moins, sa barre d'échelle ; aucune rue inventée ; sa
    note dit pourquoi pas la carte) ; le lieu, « ±12 m · mesurée à 14:10 », les coordonnées, et si Mika l'a regardée
    (d'après ses bulles 📍 du chat). L'interrupteur « Lui dire où je suis », le même que dans Paramètres › Position, et
    « Ouvrir dans Carte ».
- **Outils** (ADR 0235, 0208, 0209 ; l'API par personne : [`protocole-moi.md`](../../backendv2/docs/protocole-moi.md)
  § 6 et 8), une rubrique du tiroir, trois onglets (Droits, Services, Accords) qui se remplacent sans s'empiler. Rien n'y
  est recalculé : chaque case est la décision même du moteur, pour toi. Ouvert depuis un autre écran (« Comment ça part »
  de Teams, la règle d'envoi de Paramètres), la flèche y ramène.
  - **Droits** : « Par où » choisit le canal dont la colonne se lit (une feuille : l'app Android d'abord, puis le chat
    web en privé, un salon, Teams, le courrier, elle seule) ; le choix vaut pour la session. Puis une carte repliable par
    ressource, groupées comme la matrice — ses propres outils, tes comptes, les services, les apps de la Forge —, chacune
    avec son résumé pour ce canal (combien d'outils seule, avec ton accord, non). Un outil se nomme pour toi (son
    libellé, sinon la première proposition de sa description pour un outil venu d'ailleurs), un cadenas s'il est sous
    une condition, et ses deux pastilles : quand tu lui parles (`reply`), d'elle-même (`initiative`) ; une seule pour
    elle seule (`work`). Seule, Demande (une carte dans ton chat), Accord, Non, ou « — » s'il ne sert pas à ce moment.
    Les outils qui ne servent à aucun moment se replient sous une phrase. Toucher un outil ouvre « Ce qui décide » :
    pour chaque moment du canal, pourquoi (`why`, sa condition comprise), ce qu'elle garde (`keep`), et pour une
    opératrice la ligne même (`line`) ; où elle s'en sert par les autres canaux ; son nom de code en petit ; « Voir
    dans la console » (une opératrice : `href`, ouvert dans le navigateur sur le serveur de la session, seulement une
    page `/admin/…`) et « Lui demander » (la question posée dans le champ du chat, à relire). Un compte (une boîte,
    un compte Teams à toi) ne recopie pas les outils de sa famille — une phrase et « Voir ses outils » y mènent —, il
    dit la règle d'envoi qui vaut pour lui (`rules` : qui, préparer d'elle-même, comment ça part, lue de haut en bas, et
    d'où elle vient) et mène à sa page de Paramètres. Tirer relit ; la matrice se relit à chaque retour sur l'écran.
  - **Services** : ceux qui lui sont ouverts pour toi — le web, les tiens, ceux de l'opératrice, ceux qu'on te partage
    (`received`), même quand aucune case ne t'en ouvre encore —, à qui ils sont, leur but, leurs outils pour toi (et
    les tiens à regarder), leur état. Un des tiens ou qu'on te partage mène à sa page de Paramètres ; un service de
    Mika ou une app, à sa carte dans Droits. En bas, le lien vers Paramètres › Services MCP.
  - **Accords** : ses accords se décident dans le chat (une carte au-dessus du champ, avec exactement ce qui partira ;
    combien attendent en ce moment — ni expirés, ni déjà décidés : ceux de la pastille du chat —, quand la conversation
    en tient), « Ouvrir le chat », et où se relit ce qu'elle
    prépare : ses brouillons de mail, ses réponses dans Teams, avec leurs pastilles. Pas de liste : aucune route ne rend
    encore l'historique des décisions.
  - Pas fait : la recherche d'un outil et le menu des ressources du web (avec ses chiffres), les onze colonnes d'un
    grand écran (une seule se lit ici, ADR 0209). Autrement que la maquette : la Position reste parmi ses propres
    outils, là où la matrice la range (pas de groupe « Ce téléphone ») ; un compte ne liste pas les outils de sa
    famille (ADR 0209) ; le nom de code d'un outil n'est que dans sa feuille (ADR 0208).
- **Paramètres** (ADR 0235, l'API par personne : [`protocole-moi.md`](../../backendv2/docs/protocole-moi.md) § 5, 7, 8,
  9), une rubrique du tiroir : une page racine en groupes, une ligne par page, chaque ligne disant où en est ce qu'elle
  règle (relu à chaque retour). Les formulaires ont une seule barre « Enregistrer », qui paraît dès qu'une valeur
  change (« Annuler » remet celles d'avant ; ce qui n'est pas enregistré se perd en quittant la page) ; un refus du
  serveur se dit sous son champ (`fields`), son message en toast ; une création (une boîte, un compte Teams, un
  service) porte une clé d'envoi : redite après une coupure, elle ne fait pas de doublon. Un enregistrement fige en
  partant tout ce qu'il envoie (la boîte, le compte ou le service, ses changements, le corps de sa règle) : quitté
  avant la réponse pour une autre page de la même sorte, il va au bout pour la sienne, son sort se dit en toast avec
  son nom (« « Pro » : … »), et rien ne se pose sur la page ouverte (ni refus, ni relecture, ni « Tester » qui
  attendait) ; une lecture d'avant ne la remplit pas non plus. La règle d'envoi changée ailleurs entre-temps (409) se
  relit, sa version comprise, le reste du formulaire gardé : refaire ses choix, puis enregistrer.
  - **Ton compte** — **Compte** : ton nom (celui sous lequel elle te connaît), ton identifiant et le serveur, ton rôle,
    « Lui demander » (le chat s'ouvre, « Qu'est-ce que tu sais de moi ? » posé dans le champ, à relire), le mot de
    passe (l'actuel puis le nouveau deux fois ; changé, le serveur ferme toutes tes sessions et révoque tes téléphones :
    celui-ci se déconnecte comme d'habitude, en rendant quand même son jeton — un jeton de débogage, lui, n'est pas
    tombé —, et l'écran de connexion dit pourquoi).
  - **Ce que Mika touche pour toi** — **Boîtes mail** : les tiennes (état, relève, non-lus, ses brouillons, l'erreur),
    celles qu'on te partage (leur niveau, leur propriétaire) ; une boîte : la boîte, la connexion de lecture (mot de passe
    ou compte Microsoft), l'envoi, ce qu'elle en relève (ses dossiers, « Tout garder en local » (ADR 0249), la fenêtre de
    relève, ses « Consignes de tri », ADR 0243), comment elle y écrit, « Comment part ce que Mika y prépare » (pour chaque ligne de la
    règle de son canal et pour le défaut, préparer d'elle-même et comment ça part, ADR 0207 ; qui écrit et l'ordre des
    lignes restent à la console), avec qui elle est partagée, Tester, Relever maintenant, Retirer. Un secret laissé vide
    reste gardé ; une connexion qui change le redemande, dit sous son champ avant l'envoi. Une boîte Microsoft montre
    son code d'appareil et l'adresse où l'entrer, relue toutes les trois secondes jusqu'à la connexion. « Ajouter »
    (bouton flottant) : Microsoft, Exchange pro (pour une opératrice seulement : DavMail vit sur la machine de Mika),
    Gmail ou une autre ; créée, une boîte Microsoft demande son code, une autre se teste, puis sa page s'ouvre.
    Quand le serveur a son application Microsoft (`microsoft_app`, ADR 0238), une boîte Microsoft ne demande que
    son adresse et son nom : l'application et l'annuaire sont sous « Avancé ».
    **Comptes Teams** : les tiens (leur extension, ses réponses à relire), ceux qu'on te partage ; un compte : ses
    réglages, sa règle d'envoi, la clé de son extension (« Nouvelle clé » la montre **une seule fois**, à copier — marquée
    sensible pour le presse-papiers —, jamais gardée sur le téléphone ; « Retirer la clé »), l'adresse de Mika à coller
    dans l'extension, Retirer. La clé neuve est celle de son compte, nommé dans sa fenêtre : quitté avant la réponse,
    elle t'attend sur la page de ce compte (en mémoire, le temps de la session) jusqu'à « J'ai collé », jamais sur celle
    d'un autre. **Téléphones** : les tiens, celui-ci d'abord — reconnu par l'identifiant de son jeton, que la connexion
    rend et que la session garde ; une session ouverte avant cette version le reconnaît à son nom et ne propose pas
    « Révoquer » sur un autre téléphone du même nom, qui pourrait être lui (« peut-être celui-ci » : se reconnecter
    pour le savoir) —, s'ils reçoivent les notifications application fermée, quand ils ont servi ; en révoquer un autre
    (confirmation) ; révoquer celui-ci, c'est se déconnecter, et la confirmation le dit. **Partages** : ce que tu partages (le changer, le retirer), ce
    qu'on te partage (il s'ouvre dans Mail, Teams ou sur la page du service) ; « Partager » : quoi, avec qui (jamais une
    de ses propriétaires pour ce qui est « à toi »), ce que la personne pourra, dit en une phrase. Une boîte, un compte ou
    un service se partage aussi depuis sa page (⋮ › « Partager… »). « Retirer » vise le partage touché (sa sorte, sa
    clé, sa personne), même si la liste se relit pendant la confirmation. **Services MCP** : les tiens (état, outils servis,
    ceux à regarder, avec qui ils sont partagés), ceux qu'on te partage, en lecture ; un service : à quoi il sert,
    quand y penser, son adresse https, ses en-têtes (gardés, jamais réaffichés ; une adresse qui mène à un autre
    serveur — hôte, schéma ou port — les redemande, dit sous leur champ avant l'envoi, ADR 0236 ; « Retirer ses
    en-têtes » les efface), actif, chacun de ses outils (coupé, il
    lit, il agit ; un outil nouveau ou changé n'a pas de choix tant qu'on ne l'a pas fait), ses lignes d'accès en
    lecture, Tester, Retirer ; « Brancher » : son nom, son but, son adresse, ses en-têtes, puis il se teste.
  - **Ce téléphone** — une page par réglage, ceux d'avant, sans rien changer de ce qu'ils font : **Notifications** (les
    messages de Mika et l'autorisation, « Application fermée » et Firebase, « Lui dire quand j'ai lu »), **Position**
    (« Lui dire où je suis », voir [Sa position](#sa-position)), **Ses messages** (« Lui montrer mes messages », voir
    [Ses messages](#ses-messages)), **Apparence** (thème système / clair / sombre, « Mika en fond » si l'app a ses
    portraits, couleurs dynamiques), **Données** (« Effacer les messages de ce téléphone »).
  - En bas : « Se déconnecter », avec sa confirmation.
  - Pas fait : « Lu à l'ouverture » d'une boîte (un réglage commun à toutes, que l'API par personne ne règle pas), la
    liste des sessions du web et « Tout fermer » (aucune route), le téléchargement de l'application (le web le fait),
    une notification « Ses brouillons à relire » (le serveur n'envoie rien par Firebase quand un brouillon de mail ou de
    Teams attend : application fermée, rien ne pourrait la poser).

Hors périmètre : la voix (ni messages vocaux, ni lecture à voix haute) et le monde 3D (la chambre, les déplacements :
c'est le client Unity).

## Construire

Outils attendus sur cette machine : le JDK 25 (`/usr/lib/jvm/java-25-openjdk`) et le SDK Android dans
`~/Android/Sdk` (le fichier `local.properties`, non commité, pointe dessus).

```bash
cd frontend/Android
export JAVA_HOME=/usr/lib/jvm/java-25-openjdk
export ANDROID_HOME=~/Android/Sdk
./gradlew assembleDebug
```

Pour les notifications application fermée, pose d'abord le `google-services.json` du projet Firebase dans `app/`
(jamais versionné ; voir [Les notifications et la batterie](#les-notifications-et-la-batterie)). Sans lui, l'app se
construit et marche, sans notifications application fermée — la construction le dit.

L'APK de débogage est dans `app/build/outputs/apk/debug/app-debug.apk` ; il s'installe à côté d'une version
« release » (identifiant `fr.qwartz.mika.debug`, nom « Mika (dev) »). `./gradlew assembleRelease` produit une
version minifiée, signée avec la clé de débogage (rien n'est publié sur un magasin).

> La machine est partagée : une construction complète prend ~2 Gio de mémoire. Lance-la seule, sans démon
> (`--no-daemon`), et de préférence à travers `~/recup-audit-v2-2026-10-01/outils/borne.sh`.

## Mika en fond (3D native)

Derrière la conversation, Mika est rendue **en 3D native avec Filament** (le moteur 3D de Google), dans la lumière
de son humeur. Elle respire et bouge, joue les mouvements de l'atelier, fait des gestes quand elle répond, cligne des
yeux, te regarde, pose son regard sur toi quand tu écris et regarde ailleurs quand elle compose sa réponse. Ses
cheveux et ses vêtements suivent ses mouvements, et elle bâille quand elle est fatiguée, puis s'endort la nuit.
Le comportement est celui du client web, porté en Kotlin pur et testé sur la JVM (`avatar3d/`). Décision : ADR 0067.

Elle vit la conversation (ADR 0067, point 6) :
- les derniers messages tiennent dans une bande en bas et s'effacent avant son visage ;
- remonter dans l'historique la met en retrait ;
- chaque bulle de sa réponse arrive entière, comme un SMS, quand sa bouche commence à la dire ; la suivante attend
  qu'elle l'ait dite, ses trois points à sa place, sur une seule horloge (`avatar3d/Utterance`), et toucher la bulle
  la fait taire ;
- un message qu'on envoie, elle le lit, puis hoche la tête.

Ces signaux viennent de `ui/chat/ConversationCues.kt` (`ConversationCues`, `SpeechTrack`).

- **Le modèle** n'est pas versionné : il est sous licence de l'acheteur. On le prépare pour le téléphone depuis le
  VRM du client web, sans perte de qualité : textures en pleine résolution, morphoses inutilisées retirées (Filament
  en accepte 256 au plus), maillage du visage découpé par matériau pour un chargement rapide. Il fait ~30 Mo :

  ```bash
  python3 frontend/Android/tools/vrm_mobile.py   # → app/src/main/assets/avatar3d/mika.glb (ignoré par git)
  ```

  `vrm_mobile.py` ne lit qu'un VRM 0.x (`default.vrm`). Le modèle libre du dépôt (`mika-libre.vrm`, ADR 0252) est en
  1.0 : il n'arrive pas encore sur le téléphone.

- **Les animations** sont les mouvements de l'atelier (`frontend/Unity/ArtSource/atelier/motions`, ceux qu'Unity
  importe) et le manifeste du client web (`frontend/Web/public/animations/manifest.json`). Ils sont copiés dans
  l'APK à chaque construction : il n'y a qu'une seule source.
- **Repli.** Sans le modèle préparé, l'app montre les portraits pré-rendus de l'ADR 0065
  (`frontend/Web/assets-src/blender/portraits.py`, ignorés par git eux aussi). Sans portraits non plus, pas d'avatar,
  et l'interrupteur « Mika en fond » (Paramètres › Apparence) n'apparaît pas.
- **Batterie.** Elle n'est dessinée que quand l'écran est visible, à 60 images/s au plus, même sur un écran à 120 Hz.

En version de débogage, **le studio 3D** montre Mika sans serveur ni compte. On y règle chaque émotion « dite »
(geste permis) ou « en dérive » (posture seulement), le sommeil et la fatigue :

```bash
adb shell am start -n fr.qwartz.mika.debug/fr.qwartz.mika.studio.Avatar3DStudioActivity [--ez dark true]
```

## La carte (MapLibre)

Toutes les cartes de l'app (Carte, Téléphone › Position, les miniatures) dessinent le fond que sert ce
serveur, et lui seul (ADR 0193, 0229) : `GET /api/moi/carte/fond` dit s'il est prêt, sa sorte (vectorielle au schéma
Protomaps, ou en images), ses zooms, sa zone, sa mention, et les chemins de ses tuiles, polices et icônes. Il se lit à la
première carte montrée et se relit au plus toutes les cinq minutes tant qu'une carte est à l'écran (`ui/map/MapBase`).

- **La dépendance** : MapLibre Native pour Android, `org.maplibre.gl:android-sdk-opengl` 13.7.1 (le 2026-10-15),
  la seule ajoutée pour la carte. C'est la version OpenGL ES : depuis la 13, `android-sdk` est la version Vulkan, et
  OpenGL ES se dessine sur tous les téléphones d'Android 10 et sur l'émulateur, en surface comme en texture (la Position
  défile). Elle pèse surtout sa bibliothèque native, `libmaplibre.so` : 11,0 Mo en `arm64-v8a`, 11,4 Mo en `x86_64`,
  rangées sans compression comme les autres (`.so` alignées, lues en place) — l'APK de débogage passe à 120 Mo, dont
  22,5 Mo pour elle, que l'APK installé garde aussi (un APK par architecture n'en porterait que 11). Son code Java (le
  SDK, `android-sdk-geojson`, `maplibre-android-gestures`, `android-sdk-turf`, Timber, `androidx.fragment`) pèse environ
  1,4 Mo avant R8. Elle ajoute au manifeste `ACCESS_WIFI_STATE` (une permission normale, sans demande ; l'app avait déjà
  les autres).
- **Rien ne part ailleurs** : ni clé, ni télémétrie (MapLibre n'en a pas), ni tuiles par défaut — l'app ne lui donne que
  son propre style, en JSON, jamais une adresse de style. Ses requêtes passent par le client de la carte
  (`data/moi/carte/MapHttp`), posé une fois pour le processus (`HttpRequestUtil.setOkHttpClient`) : le jeton du téléphone
  vers le serveur de la session seulement (`BearerInterceptor`), et toute autre adresse refusée sur place, sans un octet
  sur le réseau (`SameServerOnly`). Aucune redirection ne se suit : ce filtre ne voit que la première adresse, et OkHttp
  suivrait la 30x après lui (un mandataire qui passe en HTTPS, une interception en clair) ; la redirection arrive à
  MapLibre telle quelle, une tuile en échec. Le logo, la boussole et le bouton des mentions (qui ouvrirait des liens)
  sont coupés : l'app écrit elle-même la mention du serveur au coin de la carte.
- **Le cache des tuiles** : MapLibre garde tuiles, polices et planches lues dans son cache ambiant (`mbgl-offline.db`,
  dans le stockage privé de l'app, 50 Mo par défaut), jusqu'à ce qu'il les remplace par de plus récentes ; le
  `private, max-age=86400` du serveur ne règle que leur fraîcheur. Ce cache n'est pas vidé à la déconnexion, et c'est
  voulu : ce fond est le même pour tous les comptes du serveur, il ne porte ni jeton ni donnée personnelle (le jeton
  part dans l'en-tête, jamais dans l'adresse gardée). La seule trace qu'il laisse est l'ensemble des zones regardées,
  qu'un autre compte du même téléphone ne verrait qu'en parcourant la carte hors ligne.
- **Le style** ne s'écrit pas à la main : `tools/carte_style.mjs` importe `frontendv2/src/map/mapstyle.ts` lui-même (Node
  24 lit le TypeScript) et `@protomaps/basemaps` depuis `frontendv2/node_modules`, et écrit les calques clairs et sombres
  — les couleurs et les noms en français de Protomaps, sans les points d'intérêt qui n'apprennent rien (`QUIET_POIS`) —
  dans `app/src/main/assets/carte/style-clair.json` et `style-sombre.json`, versionnés comme les icônes. Au moment de
  charger, `data/moi/carte/CarteStyle` y pose ce qui vient du serveur (ses tuiles, ses polices, sa planche `light` ou
  `dark` collées sur l'adresse de la session, ses zooms, sa zone, sa mention) et retire, comme le web, les noms sans
  polices et les icônes sans planche ; une carte en images reçoit un style raster simple. Cette moitié-là est réécrite
  en Kotlin : l'outil écrit aussi le style **complet** que le web compose pour cinq cartes servies types (avec tout,
  sans polices sous un préfixe, sans planche, sans les deux, en images) dans
  `app/src/test/resources/carte/styles-web.json`, et `CarteStyleTest` vérifie que `CarteStyle` compose le même pour les
  mêmes entrées — la source, `sprite`, `glyphs`, le style raster, ce qui retire texte et icônes, toute clé racine.
  **Lancer `--check` après chaque mise à jour de `@protomaps/basemaps` (un `npm install` dans `frontendv2/`) ou retouche
  de `frontendv2/src/map/mapstyle.ts`** : rien ne le lance d'office (ni test ni CI). S'il échoue, réécrire, puis lancer
  les tests JVM : un style du web qui a changé ailleurs que dans ses calques y fait échouer `CarteStyleTest` tant que
  `CarteStyle.kt` ne le suit pas.

  ```bash
  node frontend/Android/tools/carte_style.mjs           # réécrit les deux styles et leurs références
  node frontend/Android/tools/carte_style.mjs --check   # échoue si l'un d'eux a vieilli
  ```
- **Ce qu'elle montre** (`ui/map/SceneMap`, porté de `frontendv2/src/map/`) : une scène — des épingles numérotées,
  roses pour ce que Mika a fait, des secondaires plus petites (dessinées en images : leurs numéros n'ont pas besoin des
  polices du serveur), des tracés (polylines à six décimales, `decodePolyline6`), ta position et le cercle de sa
  précision —, cadrée sur ce qu'elle montre (jusqu'au zoom 17, ce que la recherche et la feuille couvrent évité). Le
  nord reste en haut : ni rotation ni inclinaison. Le thème clair ou sombre suit l'app.
- **Les miniatures** (`ui/map/MiniMaps`, porté de `frontendv2/src/map/minis.ts`) : la liste des voyages et le fil du
  chat (`ui/carte/CarteMinis.MapNoteCard`) montrent d'abord le plan de ce qu'elles portent ; ce qu'elles
  montrent se lit une fois pour la session (un voyage changé dans la Carte se relit quand sa miniature reparaît, et une
  liste qui le dit changé depuis la fait relire), puis une vraie carte non interactive (une vue de texture, le doigt
  laissé à la liste) prend sa place — quatre à la fois au plus (`MiniSlots`) : au-delà, le plan reste, et une miniature
  qui sort de la vue rend sa place. Comme le web (`minis.ts`), elle ne devient une vraie carte que si le fond couvre
  **tous** ses points (ses épingles, le début et la fin de ses tracés : un voyage qui sort de la zone garde son plan) ;
  une miniature restée au plan (hors zone, fond pas prêt, refusée, rien à montrer) ne prend pas de place. Les
  miniatures que la liste prépare hors de l'écran peuvent encore en prendre une.
- **Le plan revient** quand le fond n'est pas prêt (sa raison), qu'il ne couvre pas ce que la scène montre, que quatre
  tuiles d'affilée échouent, que MapLibre ne se charge pas sur ce téléphone ou que son style ne se lit pas. Un tel
  échec reste à la carte où il s'est produit (`LiveRefusal`, comme le web : `live.ts` par écran, `minis.ts` par
  miniature) : l'écran garde son plan sans réessayer tant qu'il est là, et réessaie rouvert ou quand le fond servi
  change ; une miniature garde le sien tant que sa liste vit ; les autres cartes de la session n'en savent rien (un
  service redémarré pendant qu'on regarde la Carte n'éteint plus les miniatures du chat ni la Position).
- **La batterie** : la carte suit le cycle de vie de l'écran (`onStart`, `onResume`, `onPause`, `onStop`, `onDestroy` du
  `MapView`) ; quitter l'écran la rend, l'app en arrière-plan ne dessine rien et ne relit pas le fond.

## Installer

Téléphone en mode développeur avec le débogage USB activé (ou émulateur démarré) :

```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

## Se connecter au serveur

L'adresse du serveur se saisit à l'écran de connexion (`http://` est ajouté si tu l'omets).

| Situation | Côté serveur | Adresse dans l'app |
|---|---|---|
| Émulateur sur cette machine | `python -m mika serve` | `http://10.0.2.2:8001` |
| Téléphone en USB | `python -m mika serve` puis `adb reverse tcp:8001 tcp:8001` | `http://localhost:8001` |
| Téléphone sur le Wi-Fi de la maison | `python -m mika serve --host 0.0.0.0` | `http://192.168.x.y:8001` |
| Tailscale | `--host 0.0.0.0` (ou l'adresse Tailscale) | `http://machine.xxx.ts.net:8001` |
| Hors de chez toi | un mandataire TLS devant (voir `backendv2/deploy/README.md`) | `https://mika.example.org` |

En `http://` hors de Tailscale, l'écran de connexion prévient : le mot de passe et les messages passent en clair
sur le réseau. Préfère `https://` dès que tu sors de chez toi. Derrière un mandataire, il doit laisser passer les
en-têtes `Authorization` et `X-Mika-Presence` à la mise à niveau WebSocket et ne pas couper une connexion
silencieuse avant 120 s.

Si le serveur répond « ce serveur ne propose pas encore la connexion par jeton », il est trop ancien pour l'app :
mets Mika à jour. En version de débogage, le lien « Utiliser un jeton (dev) » accepte un jeton créé à la main
(serveur arrêté) : `python -m mika token create <compte> --client mobile --label android`.

## Les notifications et la batterie

- **L'application ne se connecte qu'ouverte** (ADR 0077). Fermée, elle ne garde aucune connexion : ni service en
  arrière-plan, ni démarrage avec le téléphone. C'est ce qui ménage la batterie — une connexion gardée ouverte se
  réveillait toutes les 10 à 20 s, et réessayait sans fin quand le serveur de la maison était hors de portée (en 4G).
  Au premier plan, l'app annonce ta présence (`presence here`) ; quand tu la quittes, ton absence (le serveur
  attend 20 s : prendre une photo et revenir ne compte pas), et la connexion se ferme 30 s plus tard.
- **Application fermée, ses messages arrivent par Firebase** (Firebase Cloud Messaging), **chiffrés pour ce
  téléphone seul** : l'app tire une clé AES à la connexion, gardée par le Keystore, et la donne au serveur avec son
  jeton Firebase (`POST /auth/push`) ; le serveur scelle chaque message avec elle, Google ne transporte qu'un chiffré.
  L'app le déchiffre et l'affiche dans la notification de conversation habituelle. Il faut, une fois : un projet
  Firebase où l'application est déclarée, son `google-services.json` dans `app/` à la construction, et la clé d'un
  compte de service **côté serveur** — `firebase-service-account.json` dans son dossier de données, ou collée dans
  sa console ; jamais dans l'app (pas à pas : `backendv2/deploy/README.md`, « Notifications du téléphone »). L'app le redit au serveur à chaque ouverture chez toi (au plus tous les quarts d'heure). Paramètres ›
  Notifications › « Application fermée » dit où elle en est (active, en attente, serveur sans clé, version sans
  Firebase) avec « Réessayer ».
- **Hors de chez toi**, la notification arrive (elle passe par Google) mais l'app ne joint pas le serveur : le
  message n'entre dans le fil qu'à la prochaine connexion. D'ici là, la notification le garde, même app ouverte.
  Une réponse écrite dans la notification attend dans la file d'envoi et part à la prochaine ouverture chez toi.
- **Notifications** : l'autorisation est demandée une fois, à la première ouverture de la conversation, avec une
  explication. Une notification par conversation, avec « Répondre » (directement depuis la notification) et
  « Marquer comme lu ». Un rattrapage après une coupure donne une seule notification groupée. Rien n'est notifié
  quand la conversation est à l'écran (l'app ouverte sur le chat : « Ce qu'elle fait », une image, la recherche
  par-dessus n'en sont pas), ni pour ses pensées à voix haute, ni pour les réponses à une question posée depuis un
  autre appareil, ni pour l'historique reçu à la toute première connexion. L'app ouverte dans Mail, Teams ou une autre
  rubrique, sa parole se notifie, et un point rose sur ☰ et sur « Chat » dans le tiroir dit qu'un accord attend dans
  le chat (ni expiré, ni déjà décidé) ou qu'elle a écrit depuis ton dernier lu. Ouvrir la conversation efface la
  notification.
- **« Lui dire quand j'ai lu »** (Notifications, activé par défaut) : l'app dit au serveur jusqu'à quel message
  tu as lu (la conversation à l'écran, ou « Marquer comme lu »), trame `read` — une seule valeur, ni l'heure où tu
  es en ligne, ni le temps passé à l'écran. Mika sait alors si ce qu'elle t'a écrit a été vu : un téléphone qui
  dort ne la fait pas se sentir ignorée. Coupé, rien ne part.
- Une réponse depuis une notification démarre un service le temps de son envoi (60 s au plus, notification « Envoi
  de ta réponse à Mika »). Sans Firebase, l'app ne reçoit rien une fois fermée : ce que Mika a dit t'attend à la
  prochaine ouverture.

## Sa position

« Lui dire où je suis » : décision dans l'ADR 0119. Le réglage est dans Paramètres › Position et dans Téléphone ›
Position (le même réglage, la même demande d'autorisation : `ui/settings/WhereSwitch`), **coupé par défaut**.

- **L'autorisation** de localisation est demandée en l'activant : précise ou approximative (Android 12 et plus laisse
  choisir), l'une ou l'autre suffit. Refusée, le réglage reste coupé et le dit, avec un lien vers les réglages du
  téléphone. Retirée plus tard dans les réglages du téléphone, rien ne part (le réglage le dit) et la position s'efface
  chez Mika ; le rallumer redemande l'autorisation.
- **Seulement application au premier plan** (ADR 0077) : l'app écoute la localisation tant qu'elle est à l'écran (une
  mesure par minute au plus, pas moins de 30 s ni de 50 m entre deux), et plus du tout dès qu'elle passe en
  arrière-plan — même si la connexion reste ouverte 30 s, ou s'ouvre le temps d'une réponse depuis une notification.
  Ni `ACCESS_BACKGROUND_LOCATION`, ni service, ni notification permanente.
- **Ce qui part** : la trame `where` (`lat`, `lon`, la précision en mètres, le nom du lieu, l'âge de la mesure), redite
  à chaque ouverture de la connexion — l'âge est compté au moment où elle part. Le serveur ignore une mesure de plus de
  24 h et ne réécrit pas une position qui n'a pas bougé.
- **Couper le réglage** envoie `where` `off` : sa dernière position s'efface chez Mika. **Se déconnecter** l'efface
  aussi, et remet le réglage à zéro : un autre compte n'en hérite jamais.
- **Sur la carte** : Téléphone › Position la montre sur le fond que sert ton serveur (voir
  [La carte](#la-carte-maplibre)) ; les tuiles autour d'elle ne se demandent qu'à lui.
- **Elle ne la regarde que quand vous vous parlez**, en tête-à-tête, par un outil — jamais d'elle-même, jamais en
  salon. Chaque fois, une **petite bulle** le montre juste avant sa réponse : « 📍 Mika a regardé où tu es · Rue de la
  République, Lyon · position de 14:10 » (l'heure seulement si la position avait plus de 2 min, le jour si elle date
  d'un autre jour ; sans lieu une fois la position oubliée). Elle vient du champ `notes` de sa réponse (`speech`,
  `history`), gardé en base avec elle.

## Ses messages

« Lui montrer mes messages » : décision dans l'ADR 0120. Le réglage est dans Paramètres › Ses messages, **coupé par
défaut**.

- **L'accès aux notifications** s'accorde dans les réglages d'Android (« Accès aux notifications ») : le bouton y mène,
  et l'interrupteur s'allume au retour s'il a été accordé. Retiré plus tard, rien ne part (le réglage le dit).
- **Ce qui est lu** : seulement les applis cochées — WhatsApp (et WhatsApp Business), Messages (Google et Samsung) —,
  jamais une liste d'exclusions : ni la banque, ni les codes. Les groupes seulement si « Les groupes aussi » est coché.
  Le lecteur (`service/PhoneListenerService`) lit le `MessagingStyle` de chaque notification : la conversation, qui
  écrit, le texte, l'heure, et si c'est toi qui as écrit. Le tri est pur et testé (`data/phone/PhoneReading`).
- **Ce qui part** : `POST /api/phone/inbox`, par lots de 200, sous le jeton de l'app. La conversation et l'expéditeur
  ne partent qu'en clés opaques (`sha256` de l'appli et de l'identifiant que donne la notification, 32 caractères) ; le
  nom affiché et le texte partent en clair.
- **En 4G**, le serveur de la maison ne répond pas : les messages attendent dans une file sur le téléphone (500 au plus,
  les plus anciens tombent), et repartent au retour du réseau, à l'ouverture de l'app, ou au message suivant — pas
  avant 10 min après un échec. Aucune connexion ne reste ouverte (ADR 0077). Paramètres › Ses messages dit combien
  attendent, ou si le serveur refuse (seule sa propriétaire peut lui montrer ses messages).
- **Ses réponses proposées** arrivent par Firebase, scellées comme ses paroles (`{"t": "phone_draft", …}`) : une
  notification « Répondre à Léa (WhatsApp) ? », le texte entier, avec **Envoyer**, **Écrire autre chose** et
  **Ignorer** (balayer la notification compte comme « Ignorer »). Le geste vaut accord, et marche aussi en 4G.
  « Envoyer » passe par l'action « Répondre » de la notification de WhatsApp ou de Messages, gardée en mémoire
  seulement ; si elle n'existe plus (notification balayée, appli redémarrée), le texte est copié et la notification
  ouvre l'appli pour le coller. Le sort repart au serveur (`POST /api/phone/settled`) par la même file. Sans geste, la
  proposition expire (2 h) et la notification disparaît.
- **Depuis l'écran Téléphone**, les mêmes gestes, le même accord (`PhoneDraftNotifier.sendHere`, `ignoreHere`) : la
  proposition se reconnaît à son identifiant, le même chez le serveur (`offers[].id`) et dans la proposition reçue
  par Firebase, et sa conversation à sa clé (`<appli>|<fil>` : le fil est la clé sous laquelle l'action « Répondre »
  est gardée). Ton propre message part par la même action (`replyHere`), sans passer par le serveur : le téléphone le
  lira ensuite comme les autres. Sans action, le texte est copié et l'écran ouvre l'appli (pas de notification
  « Copié »). L'action gardée retient le nom que sa notification donnait à la conversation (`ReplyRegistry`) : depuis
  l'écran, elle ne sert que si c'est celui du fil montré (`PhoneHere.canDeliver`) — une clé de conversation est
  calculée sur chaque téléphone, et un identifiant local (celui qu'une appli de SMS donne à ses conversations) peut
  donner la même à deux conversations de deux téléphones du compte. Le geste depuis la notification d'une proposition
  ne change pas : sa notification nomme déjà à qui elle répond.
- **Couper** le réglage vide la file et oublie les actions gardées ; Android cesse alors d'appeler le lecteur.
  **Se déconnecter** fait de même et remet le réglage à zéro : un autre compte n'en hérite jamais.

## Se déconnecter, révoquer un téléphone

- **Se déconnecter** (Paramètres) rend le jeton au serveur et efface du téléphone les messages, les fichiers, les
  vignettes et les notifications. L'adresse et le nom d'utilisateur restent pré-remplis.
- **Révoquer un téléphone perdu** : depuis un autre de tes téléphones (Paramètres › Téléphones) ou le web
  (Paramètres › Téléphones), ou dans la console, **Comptes**, révoque son jeton (il porte le nom
  « Android · fabricant modèle »), ou `python -m mika token revoke <id>`. Le téléphone est déconnecté à sa
  prochaine connexion (« Ta session a expiré ou a été révoquée — reconnecte-toi. ») et efface ce qu'il gardait.
  Changer le mot de passe du compte (Paramètres › Compte, ici ou sur le web) révoque aussi les jetons obtenus avec
  l'ancien : changé depuis ce téléphone, il se déconnecte aussitôt (en rendant quand même son jeton), et l'écran de
  connexion dit pourquoi. Une déconnexion commencée va au bout, même si l'écran qui l'a déclenchée se ferme.
- **Révoquer ne défait pas ce que le téléphone a fait** : depuis l'ADR 0235, il écrit comme une session du web. Une
  clé d'extension Teams qu'il a créée, un partage qu'il a donné, un service qu'il a branché, un réglage qu'il a changé
  restent. Après une perte, revois-les dans Paramètres (Comptes Teams, Partages, Services MCP, Boîtes mail).

## Tests

```bash
./gradlew testDebugUnitTest          # le cœur, sur la JVM (protocole, fil, socket, notifications, fichiers…)
./gradlew lintDebug
./gradlew assembleDebugAndroidTest   # compile les tests instrumentés
node tools/carte_style.mjs --check   # le style de la carte et ses références, tirés du web, sont à jour
                                     # (après une mise à jour de @protomaps/basemaps ou de mapstyle.ts)
python3 tools/icones.py --check      # les icônes, tirées de la maquette, sont à jour
./gradlew connectedDebugAndroidTest  # les exécute sur un émulateur ou un téléphone branché
```

Les tests JVM n'ont besoin d'aucun émulateur : le moteur (protocole, fusion du fil, socket, décisions de
notification, réduction des images, partage, navigation, cartes de « Ce qu'elle fait », choix du portrait, cartes
d'accord, ce qui part de sa position et sa petite bulle, le chat — ses notes de carte (`MapNotesTest` : les trois
sortes, une note vidée, sous sa dernière bulle), la ligne au-dessus du champ (`ChatTrayTest` : ce qui se décide ici ou
ailleurs, combien de brouillons sans compter deux fois, le compte à rebours, quand elle se déplie, ce que « Tout
accepter » prend et laisse), la recherche (`SearchRulesTest` : sans accents, le passage trouvé, ses fils, le classement
des écrans, quand le serveur est demandé), les fichiers échangés (`ExchangedFilesTest`), tes pièces qui apprennent de
quoi les reprendre (`ChatSyncTest`) —, la conversation à l'écran ou non (`AppForegroundTest`, `BackStackTest`) et la
pastille hors du chat (`ChatCueTest`), la fermeture d'une session qui va au bout et rend le jeton
(`AuthRepositoryTest`), qui est connecté sans retour de la session d'avant (`MeRepositoryTest`), le mail commencé
gardé pour la même écriture (`UnsentMailTest`), les « où aller après » d'une page de Paramètres (`PageMovesTest`), les
écrans de Mail contre une fausse API qui répond quand le test le veut (`MailComposeModelTest` : une écriture quittée qui
finit de charger, « Préremplir » tardif, sa réponse repartie de son brouillon, l'envoi quitté, son refus en toast ;
`MailReaderModelTest` : un geste tardif sur la liseuse ou la page d'un brouillon ; `MailReaderFrameTest` : la mise en page d'un mail HTML, ses images, un cadre tardif ou refusé ; `MailFramePageTest` : sa politique posée en tête, les liens qui s'ouvrent dehors ; `MailListModelTest` : la page
suivante après un rangement, une ligne glissée à la corbeille, son refus, « Annuler » ; `VisitOrdersTest` : un ordre ne suit que l'écran de sa visite), les pages de Paramètres
contre une fausse API (`FakeSettingsApi` ; `BoxModelTest` : une boîte enregistrée puis quittée pour une autre, une
lecture tardive, une règle changée ailleurs ; `TeamsAccountModelTest` : la clé neuve liée à son compte ;
`ServiceModelTest` : ses outils pour lui, ses en-têtes redemandés quand l'adresse mène ailleurs ; `SharesModelTest` :
« Retirer » vise le partage touché), un fil du Téléphone (`PhoneThreadModelTest` : le champ et sa proposition réglée,
le sort d'un geste sur l'écran de sa visite, un geste qui va au bout l'écran parti, l'action gardée qui vise le fil
montré), ce téléphone reconnu par son jeton (`AuthRepositoryTest`, `SettingsRulesTest`, `PhoneRulesTest`), ouverture d'un message Firebase — `PushPayloadTest` en ouvre un scellé par le serveur —, inscription aux
notifications, tri des notifications de WhatsApp et de Messages, leurs clés opaques, leur file et son envoi, les
réponses proposées, Mail — ses règles, ses dates, `MailApi` contre un faux serveur —, Teams — ses règles,
`TeamsApi` contre un faux serveur —, Téléphone — ses règles, ce qui se décide d'ici, `PhoneMoiApi` contre un faux
serveur —, Outils — ses règles (`ToolsRulesTest` : les mots d'une case, le canal lu et ses moments, le nom d'un outil,
les ressources et leurs groupes, le résumé d'une carte, ce qu'une opératrice voit de plus, les lignes de « Services »),
`ToolsApi` contre un faux serveur —, Carte — le tracé (`PolylineTest`), la scène et son cadrage (`SceneTest`), les mots
(`MapWordsTest`), quand une adresse se demande et les adresses gardées, la légende, la vraie carte ou le plan (et pour
une miniature), les tuiles en échec (`CarteRulesTest`), le style tiré du web et ce que l'app y pose — le même que celui
que compose le web pour les cartes servies de référence (`CarteStyleTest`) —, `CarteApi` et le client de MapLibre contre
un faux serveur, une redirection ailleurs comprise (`CarteApiTest`), ce que la carte pose en GeoJSON (`MapGeoJsonTest`),
ce qui ne s'est pas dessiné, carte par carte, les places des miniatures et l'encre des numéros (`MapFailuresTest`), un voyage
(`TripRulesTest` : l'ordre des arrêts et où un geste les met, un geste qui ne change rien, ce dont son trajet dépend,
« Sur la route » et le jour d'un lieu croisé, ce que la fenêtre d'un voyage envoie, ses miniatures et celles d'un
regard), Itinéraire (`RouteRulesTest` : ses points, ce qui le fait, tes choix face à ceux de Mika, ce qu'on en dit, son
GPX), ce qui sort du serveur (`TripRequestsTest` : le trajet d'un voyage relu après le dernier geste, les gestes l'un
après l'autre, ce qu'un refus fait de la clé), les itinéraires, les regards et les voyages contre un faux serveur
(`TripsApiTest`), un voyage ouvert contre une fausse API (`FakeTripsApi` ; `TripModelTest` : la relecture d'un geste
qui suit celle partie avant lui, une relecture en panne qui garde ce que les gestes ont posé, « Sur la route » fermé
ou quitté, le GPX après les gestes ; `TripReadsTest` : une relecture forcée suit celle en cours ; `TripEditorRowsTest` :
où tombe un arrêt glissé, par la clé de sa ligne), « En faire un voyage » fini hors de l'onglet (`ShownOrdersTest`) —
et Paramètres — ses règles (`SettingsRulesTest` : niveaux et partages, ce qu'un formulaire envoie, les secrets
à redonner, les refus par champ, la règle d'envoi et sa version, les outils d'un service, les lignes de la page
racine), `SettingsApi` contre un faux serveur) est du Kotlin pur. Les tests instrumentés (`app/src/androidTest`) éprouvent Room
en mémoire (`ChatStoreTest`) et les écrans Compose (`ChatScreenTest`, `LoginScreenTest`, `MindScreenTest`).

## Organisation du code

| Paquet | Contenu |
|---|---|
| `core` | `AppGraph` (le graphe de l'app, à la main), horloges, premier plan et conversation à l'écran (`AppForeground`), réseau, localisation |
| `data/net` | protocole, trames, `MikaSocket` (reconnexion, battement, file d'envoi), adresse du serveur |
| `data/db` | Room : messages, file d'envoi, petites valeurs |
| `data/chat` | `ChatSync` (fusion du fil, portage du client web), `ChatEngine`, `ChatRepository` |
| `data/mind` | l'état de Mika, ses libellés, la ligne d'état |
| `data/approvals` | les cartes d'accord : leurs règles (`Approvals`, testées) et la liste en cours |
| `avatar3d` | Mika en 3D native : VRM, squelette, mouvements, machine à états, couches du corps, visage, ressorts, rendu Filament |
| `data/avatar` | ses portraits (repli) : le manifeste, le choix du portrait, le rythme des clignements |
| `data/auth` | jeton chiffré (Keystore), connexion, erreurs en français |
| `data/files` | pièces jointes (préparation, réduction), brouillon, partages reçus, fichiers de Mika |
| `data/location` | « Lui dire où je suis » : ce qui part (`WhereShare`, selon le réglage et le premier plan), le nom du lieu (`PlaceLabel`) ; la localisation elle-même est dans `core/LocationMonitor` |
| `service` | connexion voulue, notifications, réponse depuis une notification (et son service de 60 s) ; le lecteur des notifications du téléphone (`PhoneListenerService`) et les réponses proposées (`PhoneDraftNotifier`, ses gestes depuis la notification ou l'écran Téléphone) |
| `data/phone` | « Lui montrer mes messages » (ADR 0120) : les applis lues, le tri des notifications (`PhoneReading`), les clés opaques, la file et son envoi (`PhoneOutbox`), les réponses proposées (`PhoneDrafts`), les actions « Répondre » gardées en mémoire, le sort d'un geste fait depuis l'écran (`PhoneHere`) |
| `data/push` | les notifications par Firebase : ouvrir un message scellé (`PushPayload`), dire au serveur où notifier (`PushRegistrar`) |
| `push` | Firebase lui-même : le jeton (`FirebasePush`) et la réception (`MikaMessagingService`) |
| `share` | « Partager vers Mika », raccourci de conversation |
| `data/moi` | l'API par personne (`/api/moi`, ADR 0235) : `MoiApi` (lire, écrire en JSON ou en `multipart`, clé d'envoi, refus en mots), `MeRepository` (qui est connecté, les pastilles du tiroir), les règles que les domaines partagent (`MoiRules` : niveaux, `SendKey`, « [À COMPLÉTER », refus en mots ; `MoiText` : instants, initiales) ; un sous-paquet par domaine, `mail/` pour Mail (ses formes, `MailApi`, ses règles pures), `teams/` pour Teams (ses formes, `TeamsApi`, `TeamsRules`), `phone/` pour Téléphone (ses formes, `PhoneMoiApi`, `PhoneRules` : sorts de ses propositions et ce qui se décide d'ici, le fil, l'état de tes téléphones et « ce téléphone », la position et son plan), `settings/` pour Paramètres (ses formes, `SettingsApi` — § 5, 7, 8, 9 —, `SettingsRules` : niveaux et partages, état d'une boîte ou d'un service, ce qu'un formulaire envoie, secrets à redonner, refus par champ, règle d'envoi et sa version, outils d'un service, lignes de la page racine), `tools/` pour Outils (les formes de la matrice, `ToolsApi` — § 6 et, par `SettingsApi`, § 8 —, `ToolsRules` : les mots d'une case et de ce qu'elle garde, le canal lu, le nom d'un outil, ressources, groupes et résumés, ce qu'une opératrice voit de plus, les lignes de « Services »), `carte/` pour la Carte (ses formes et le fond servi, `CarteApi` — § 10 —, `MapGeo` et `Polyline` : zone, cercle, zoom, distance, le tracé ; `Scene` : ce qu'une carte montre et son cadrage ; `MapWords` : distances, durées, dates d'un voyage ; `CarteStyle` : le style tiré du web et ce que l'app y pose ; `MapHttp` : le client de MapLibre, ce serveur seul ; `CarteRules` : les adresses et leurs bornes, la légende, ce qu'Explorer montre, la vraie carte ou le plan, les tuiles en échec ; `TripModels` et `TripsApi` : les formes et les appels des itinéraires, des regards et des voyages ; `TripRules` : l'ordre des arrêts et où un geste les met, ce dont le trajet d'un voyage dépend, « Sur la route », ce que la fenêtre d'un voyage envoie ; `RouteRules` : les points d'un itinéraire, tes choix face à ceux de Mika, son GPX ; `TripRequests` : le trajet d'un voyage relu après le dernier geste, les gestes l'un après l'autre, ce qu'un refus fait de la clé ; `MapMinis` : la miniature d'un voyage ou d'un regard et ce qu'elle ouvre, les places des cartes vivantes ; `GpxDownloads` : le GPX d'un itinéraire, dans Téléchargements/Mika) |
| `ui` | écrans Compose : connexion, conversation, « Ce qu'elle fait », visionneuse |
| `ui/chat` | la conversation : `ChatScreen` et `ChatViewModel` (le fil, la saisie, la ligne au-dessus du champ et « Tout accepter », le message à montrer), `ChatParts` (la barre, le fil, ses bulles, ses miniatures, le surlignage), `ChatItems` (ce que le fil dessine), `MapNotes` (ses notes de carte, validées), `ApprovalCards` (la ligne repliée, les cartes d'accord, les liens vers ses brouillons) et `ChatTray` (ses règles pures), `StrandParts` (les fils de travail), `SearchScreen` et `SearchRules` (« Rechercher » : les puces, les groupes, le classement, Mail et Teams au serveur), `FilesScreen` et `ExchangedFiles` (« Fichiers échangés ») |
| `ui/shell` | le cadre des rubriques : `Shell` et `LocalShell` (aller, revenir, le tiroir, les toasts), la barre du haut, le tiroir, la pastille du chat (`ChatCue`), `Load` et `LoadBox`, les icônes de la maquette (`MIcon`) ; `Parts.kt`, les petites formes que Mail et Teams partagent (rond d'initiales, marque, ligne rose, note, ⋮, recherche, ligne de feuille, fenêtre à un champ) |
| `ui/mail` | Mail : la liste et la feuille des boîtes, la liseuse, ses brouillons, écrire (et `UnsentMail` : le mail commencé, gardé pour la session) ; un ViewModel par sorte d'écran, pour la session, qui prend ce qu'il lui faut par `MailDeps` (l'API, les mails commencés, `MailNotices` : le sort d'un envoi dit en toast par le cadre) ; `VisitOrders` : ses ordres à l'écran de la visite qui les a donnés |
| `ui/teams` | Teams : les discussions et la feuille des comptes, un fil (ses cartes, le champ), ses brouillons ; un ViewModel par écran |
| `ui/phone` | Téléphone : la barre (l'état de tes téléphones) et ses onglets, Messages, un fil (ses propositions, répondre d'ici), Position sur la vraie carte (`PositionMap`) et son plan dessiné de repli (`PositionPlan`) ; un ViewModel par écran (celui d'un fil prend `PhoneThreadDeps` — l'API, les gestes d'ici par `PhoneHereGestures`, la portée de l'application — et se teste sur la JVM) |
| `ui/map` | ce qui sert à toute carte : MapLibre réglé une fois (`MapKit`), les calques du style lus dans les assets, le fond de la session (`MapFondViewModel`), ce qui ne s'est pas dessiné, carte par carte (`LiveRefusal`), la poignée d'un écran sur sa carte (`MapControl`) ; `SceneMap` (la vraie carte ou le plan), `LiveMap` (le `MapView`, son cycle de vie, ce qu'elle pose par-dessus le fond, ses cadrages, ses échecs), `ScenePlan` (le plan dessiné d'une scène), `PinImages` (les épingles en images), `MiniMaps` (ce que montrent les miniatures, lu une fois pour la session — `MiniStore` —, leurs quatre places et leurs refus — `MiniSlots` —, une miniature — `MiniMap`) |
| `ui/carte` | Carte : `CarteScreen` (la barre et ses trois onglets, « Nouveau voyage » flottant, `CarteLinks` : ce qu'un onglet demande à un autre, au chat, à un voyage ; ce que la route ouvre : un regard, « Itinéraire jusqu'ici »), `CarteStore` (ce que la Carte partage pour la session : ce qui est branché, ta position, les adresses trouvées, ses regards, tes voyages, chaque voyage lu — `TripReads`, où une relecture forcée suit celle en cours —, les miniatures), `ExplorerViewModel` et `ExplorerTab` (la recherche, les adresses, le lieu choisi, un regard de Mika en rose), `ItineraryViewModel` et `ItineraryTab` (les points et leurs propositions, le calcul, le regard de Mika, tes choix, le GPX, « En faire un voyage »), `TripsTab` (la liste en cartes), `TripViewModel` (sur `TripDeps`) et `TripScreen` (un voyage : ses gestes l'un après l'autre et montrés d'abord, le voyage et son trajet relus après le dernier, la poignée, la note en place, « Sur la route »), `TripEditorRows` (les lignes de l'éditeur et où tombe un arrêt glissé, sans Compose), `TripDialogs` (« Nouveau voyage », « Le voyage », « Ajouter au voyage », « Ajouter un arrêt »), `CarteMinis` (une miniature et ce qu'elle ouvre ; `MapNoteCard`, pour le chat) |
| `ui/tools` | Outils : `ToolsScreen` (la barre et ses onglets, `ToolsViewModel` : la matrice, tes services, le canal lu et les cartes dépliées, un par session), `RightsTab` (Droits : le canal, les cartes, les pastilles, la règle d'un compte), `ToolSheets` (la feuille des canaux, « Ce qui décide »), `ServicesTab` (Services, Accords) |
| `ui/settings` | Paramètres : la page racine et l'aiguillage des pages (`SettingsScreen` : `SettingsPages`), les pièces communes (`SettingsParts` : groupes, lignes, champ et son refus, choix, barre « Enregistrer », `SettingsModel`), Compte, Boîtes mail (la liste, une boîte, sa connexion Microsoft, une boîte nouvelle), la règle d'envoi (`RulesEditor`), Comptes Teams (la clé montrée une fois), Téléphones, Partages (et la fenêtre « Partager »), Services MCP (brancher, ses outils) ; « Ce téléphone » (`ThisPhonePages` : notifications, position, ses messages, apparence, données ; `WhereSwitch`, partagé avec Téléphone › Position) ; un ViewModel par sorte de page, rouvert pour chaque page qu'il sert : il prend `SettingsDeps` (l'API, ses textes, les pastilles), un geste fige ce qu'il envoie et ne pose rien sur une autre page (`stillOn`, `sayFor`, `refusedFor`) ; ceux d'une boîte, d'un compte Teams, d'un service et des partages se testent sur la JVM (`FakeSettingsApi`) |
| `ui/avatar` | Mika en fond : chargement des portraits, l'aura, le souffle, les clignements, le sommeil, son visage dans la barre |
