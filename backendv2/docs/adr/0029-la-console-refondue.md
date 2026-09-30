# 0029 — La console refondue : des menus qui répondent à des questions, des pages qui ne montrent qu'un sujet

**Contexte.** La console de l'ADR 0025 montrait tout ce que les facultés déclarent, mais se lisait mal : un
accueil fait de trois courbes presque vides (et d'une cinquième série perdue), des menus rangés par propriétaire
(*Fil* et *Courrier* sous la même icône, *Sens* à côté du courrier qui en est un, *Réglages* mêlant comptes,
paramètres internes et journal, *Système* en huit onglets à plat), des tables plafonnées sans le dire (10, 12,
20, 50, 64, 100, 200 lignes), des paginations à curseur sans retour, et une configuration « tout sur une page » :
les rôles, les fournisseurs et le contexte en un formulaire ; le personnage entier en une colonne ; ≈ 40
paramètres physiques en une table suivie d'un second formulaire qui les répétait tous. Le repli d'un fournisseur
se tapait à la main, l'URL et l'hôte s'affichaient même quand le SDK ou la CLI les savent, la clé d'API de Claude
Code sur l'abonnement aussi. Des informations manquaient : la file de sortie (des livraisons perdues sans trace),
l'état vivant de la passerelle, les anomalies qui n'allaient qu'au journal Python, les épisodes en cours, le
stockage, l'historique des révisions de la persona. La carte détaillée est dans `docs/console-carte.md`.

**Décision.**
1. *La carte répond à des questions.* Tableau de bord (que dois-je faire ?) ; Elle (comment va-t-elle ?) ; Ses
   relations (qui connaît-elle ?) ; Son activité (que fait-elle, pourquoi ?) ; Ses canaux (par où perçoit-elle et
   agit-elle ?) ; Exploitation (que décide-t-on, la machine tient-elle ?). *Fil* devient Conversations, *Sens*
   Flux et capteurs, *Réglages* Configuration. Une destination peut ordonner ses onglets (`order`) et dire quelles
   fiches d'objets elle abrite (`subjects` : le menu s'allume sur une fiche, le fil d'Ariane y ramène).
2. *Les destinations riches ont un sous-menu.* `layout="menu"` rend une colonne rangée par rubrique
   (`Builtin.group`) ; au-delà de 18 entrées, les rubriques qui ne portent pas la page se replient. Une destination
   `dynamic` prend tous les onglets de son préfixe, connus seulement au démarrage (une page par faculté).
3. *Toute information en table est paginée.* Le rendu découpe toute table ou chronologie sans pagination au-delà
   de 25 lignes (`?pg<n>=`) ; une pagination à curseur garde son chemin (`pile`, une par clé de curseur) et sait
   revenir aux plus récents et au début. Les plafonds silencieux des vues sont remplacés par des pages ; la
   recherche, l'historique des approbations, les appels de modèle (`calls.recent(offset=)`, `count()`) aussi.
4. *Une page de configuration ne montre qu'un sujet.* Une section de réglages se découpe en `SettingsPage`
   (Intelligence : fournisseurs, qui sert quoi, contexte ; Personnage : identité, ton et parole, caractère,
   tempérament, import / export ; Canaux ; Sens) ; chaque entrée d'une liste (un fournisseur, une boîte) a sa page ;
   un envoi sur la page d'une autre section est refusé. Les paramètres internes ont une page par faculté, rangée
   par famille (déclarée par la composition, `PARAM_FAMILIES`, pour que la console n'en nomme aucune), et un groupe
   à la fois au-delà de 12 paramètres ; chaque paramètre dit son sens en entier, sa valeur, sa provenance, ses bornes,
   ce qui le pilote, et se remet au tempérament d'un bouton. Les comptes deviennent une page déclarée (liste
   paginée, créer, modifier), **auditée** — elle ne l'était pas.
5. *Un champ ne se montre que s'il sert, un choix limité est un sélecteur.* `Knob.only_any` ajoute le « ou » aux
   conditions d'affichage (la clé d'un service hébergé, ou de Claude Code sur une clé), toutes rendues au
   navigateur (seule la première l'était) et appliquées dès le rendu serveur ; ce que le SDK ou la CLI savent
   (adresse, hôte, commande, dossier) va dans « Options avancées » ; le repli se choisit parmi les autres
   fournisseurs (`choices_from` dans une entrée), le fuseau parmi les fuseaux IANA (`SettingsSection.choices`), et
   la liste des modèles se charge d'elle-même sur la page d'un fournisseur existant. Chaque champ a une aide,
   affichée sous lui.
6. *Ce qui manquait se voit.* Décisions › En cours (épisodes ouverts, files, baux, questions en attente) ;
   Approbations › Historique (avec la capacité) ; Système › Processus (et les échecs gardés au journal),
   Anomalies (`mind.anomalies`, `mind.traces`, arbitre, tranches corrompues), Sorties (la file de sortie : en
   attente, échoué, orphelin), Modèles en service (créneaux, repli, quota d'abonnement, qui sert vraiment chaque
   rôle — `Gateway.status()`, `resolution()`), Coûts par modèle, Stockage ; Configuration › Qui sert quoi (la
   résolution réelle après replis), Import / export (l'historique des révisions de la persona). Le tableau de bord
   liste ce qui attend onglet par onglet, son état en cadres, toutes les courbes (quatre séries par courbe au plus,
   jamais une de perdue), la journée et les derniers épisodes.

**Conséquences.** Les anciennes adresses redirigent (`reglages/modeles` → `fournisseurs`, `personnalite` →
`identite`, `parametres?faculte=x` → `comportement-x`…) et les anciens envois de formulaire sont aiguillés vers la
page qui montre le champ. Tests : chaque page de chaque sous-menu s'ouvre ; une page de réglages ne montre pas les
champs d'une autre ; la clé d'API ne s'affiche que pour les types qui s'en servent ; le repli est un sélecteur qui
ne se propose pas lui-même ; le fuseau est un sélecteur ; un paramètre surchargé se remet au tempérament ; un
réel montré arrondi et renvoyé tel quel ne crée pas de surcharge (`params.shown`, comparaison à l'affichage près) ;
les canaris ne paraissent dans aucune page d'aucun sous-menu. Défauts trouvés en chemin : la pagination filtrée des
épisodes sautait jusqu'à 350 épisodes (curseur pris sur le 400ᵉ lu) ; `fond_min` et `esteem_min` s'affichaient en
minutes (le suffixe `_min` d'un réel n'est plus une unité) ; l'accueil perdait la cinquième série de courbes ; la
recherche plafonnait à 50 (100 au noyau) ; le « Journal » de l'accueil montrait un numéro de séquence brut.

**Complément.** Les vues des facultés restantes (attention, soi, lien, fil, ce qu'elle devine) n'ont plus de
plafond silencieux ; la synthèse d'une personne renvoie à l'onglet Poignées au lieu de répéter sa table. Un
fournisseur neuf se choisit dans la liste de ses modèles **avant** d'être enregistré : « Charger la liste »
interroge le fournisseur avec ce qui vient d'être tapé, et la clé tapée n'est jamais renvoyée dans la page — elle
est gardée côté serveur, sous un jeton, le temps de finir (15 min au plus). `mika backup` et `mika verify` notent
leur résultat dans le dossier de données (`sauvegardes.json`, hors des archives) : Système › Stockage montre la
dernière sauvegarde, ce qui s'est écrit depuis, la dernière vérification et les archives gardées, et le tableau de
bord signale une sauvegarde absente, ancienne (plus de deux jours) ou dont la vérification a échoué. Chaque relevé
d'un flux se note (tentative, succès, erreur en mots — jamais l'adresse, qui peut porter un jeton —, articles lus,
nouveaux, échecs d'affilée) : Flux et capteurs › Flux dit quel flux ne répond plus, et pourquoi.

