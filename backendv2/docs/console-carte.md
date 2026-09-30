# La carte de la console

Ce que chaque menu de `/inspecteur/` montre, et sous quelle forme. Référence de
la refonte du 30/09/2026 (ADR 0029) ; la carte vit dans `app/console.py`, les
réglages dans `app/reglages.py`.

Trois règles tiennent toute la console :

1. **Toute information en table est paginée.** Une vue qui oublie de paginer est
   découpée par le rendu (25 lignes, `?p-<table>=`) ; une pagination à curseur
   (le journal) sait revenir aux plus récents et au début.
2. **Une page de configuration ne montre qu'un sujet.** Chaque section de
   réglages est découpée en sous-pages rangées dans un sous-menu ; chaque champ
   dit ce qu'il fait, sous lui (jamais seulement au survol).
3. **Un champ ne se montre que s'il sert.** Un choix limité est un sélecteur
   (modèle, repli, rôle) ; un champ qui ne vaut que pour un type de fournisseur
   n'apparaît qu'avec lui ; ce que le SDK ou la CLI sait déjà (URL, hôte,
   commande) est rangé dans « Options avancées ».

## Étape 1 — les informations essentielles, par menu

| Groupe | Menu | La question de l'opérateur | L'essentiel |
|---|---|---|---|
| — | **Tableau de bord** | « Tout va bien ? Que dois-je faire ? » | ce qui attend (accords, brouillons, revendications, questions, apps cassées, processus en échec, modèles absents) · son état en ce moment · sa journée · ses derniers épisodes |
| Elle | **Humeur et corps** | « Comment va-t-elle ? » | humeur, postures envers chacun, besoins, rythme et sommeil, estime et récit |
| Elle | **Pensées et nuits** | « À quoi pense-t-elle ? » | pensées vivantes, ce qu'elle a remarqué, ce qu'elle attend, ses nuits (journal, rêves) |
| Elle | **Mémoire** | « Que retient-elle ? » | souvenirs, croyances, promesses, relecture (consolidation) |
| Ses relations | **Personnes** | « Qui connaît-elle ? » | personnes, liens (rythme, manque), présents |
| Ses relations | **Identités** | « Qui parle derrière chaque poignée ? » | poignées, revendications, politique de confiance |
| Ses relations | **Conversations** | « Qu'a-t-on dit ? » | messages, questions sans réponse |
| Son activité | **Décisions** | « Pourquoi parle-t-elle ou se tait-elle ? » | table de l'arbitre maintenant, ce qui tourne en ce moment, budget d'initiatives, ses choix, épisodes, échéances |
| Son activité | **Buts** | « Qu'a-t-elle entrepris ? » | buts vivants, buts clos |
| Son activité | **Approbations** | « Que veut-elle faire sortir ? » | en attente (décider), historique |
| Ses canaux | **Courrier** | « Ses boîtes aux lettres » | boîte, brouillons, envoyés, contacts, comptes |
| Ses canaux | **Flux et capteurs** | « Ce qu'elle perçoit du monde » | flux RSS, caméra, appareils |
| Ses canaux | **Apps forgées** | « Ses petites apps » | liste, état, cassées |
| Exploitation | **Configuration** | « Que décide l'opérateur ? » | sous-menu : Intelligence, Personnage, Canaux, Sens, Comportement, Accès, Historique |
| Exploitation | **Système** | « La machine tient-elle ? » | sous-menu : Surveillance, Journaux, Anatomie, Outils |

Ce qui a changé de place : *Fil* devient **Conversations** (il partageait
l'icône ✉ avec le Courrier) ; *Sens* devient **Flux et capteurs** (le courrier
est lui aussi un sens) ; *Réglages* devient **Configuration** (les comptes
d'accès y ont leur place, l'historique aussi) ; *Initiatives* passe juste après
la table de l'arbitre.

## Étape 2 — pour chaque menu, ce qui doit se voir et se consulter

### Tableau de bord
- **À traiter** (cadres cliquables) : accords en attente, brouillons à décider,
  revendications, questions sans réponse, apps cassées, processus en échec
  d'affilée, anomalies, *aucun modèle configuré* — chacun mène à sa page.
- **En ce moment** (cadres) : humeur, énergie, sommeil, envie dominante,
  présents, épisodes en cours, file d'attente, heure.
- **Sa journée** (courbes 24 h) : énergie et pression de sommeil, besoins
  (les trois), valence et éveil, estime.
- **Aujourd'hui** (cadres) : épisodes par issue, coût des modèles.
- **Derniers épisodes** (table paginée).

### Humeur et corps · Pensées et nuits · Mémoire · Personnes · Identités · Conversations · Buts · Courrier · Flux et capteurs · Apps forgées
Ces pages sont **déclarées par les facultés** (`@f.inspect`) : leur contenu
reste le leur. La refonte y garantit la pagination de chaque table, remplace
les plafonds silencieux (10, 12, 20, 50, 64, 100, 200…) par des pages, et
corrige les défauts relevés (le compte « dans la boîte », les commits datés de
1970, le filtre d'autorité des buts clos, la 5ᵉ courbe perdue de l'accueil).

### Décisions
- **Maintenant** : la table de l'arbitre (preuves → score → taux), la politique.
- **En cours** *(nouveau)* : épisodes ouverts (sorte, cible, depuis), files
  d'attente par voie, baux tenus.
- **Initiatives** : budget du jour, période réfractaire, ignorées.
- **Ses choix**, **Épisodes** (filtres sorte/issue/cible, pagination juste),
  **Échéances**.

### Approbations
- **En attente** : une carte par demande (ce qui partira, contexte, arguments),
  approuver / refuser.
- **Historique** : décisions et exécutions, avec la capacité (pas seulement un
  numéro), paginé.

### Configuration (sous-menu)
| Rubrique | Sous-page | Contenu |
|---|---|---|
| Intelligence | Fournisseurs | liste paginée ; chaque fournisseur a sa page : type, modèle (**sélecteur** chargé chez le fournisseur, même pour un fournisseur pas encore enregistré), connexion, clé ; options avancées repliées (URL, hôte, commande, créneaux, température…) ; repli = **sélecteur** parmi les autres fournisseurs |
| | Rôles | un sélecteur par rôle, rangés par famille (voix, compréhension, sens, travail), et ce qui sert **vraiment** chaque rôle après replis |
| | Contexte | la fenêtre que le prompt peut remplir |
| Personnage | Identité | nom, description, langue, fuseau |
| | Ton et parole | ton, façons de parler, salutations |
| | Caractère | traits, manies, fragilités, valeurs, centres d'intérêt |
| | Tempérament | les huit curseurs, l'humeur de fond, ce que pilote chaque curseur |
| | Import / export | le document YAML, revenir au fichier, l'historique des révisions |
| Canaux | Telegram | robot, conversations autorisées, propriétaires |
| Sens | Boîtes aux lettres | liste ; chaque boîte a sa page (lire, envoyer, sa voix, initiative) |
| | Flux RSS | adresses suivies |
| | Transcription | service, modèle, clé |
| | Appareils | jeton des appareils |
| Comportement | Vue d'ensemble | provenance des paramètres, ce que pilote chaque curseur |
| | une page par faculté | ses paramètres **rangés par groupe** (un groupe = une page), chacun avec sa valeur, sa provenance, ses bornes et son sens ; une surcharge se pose en changeant la valeur |
| Accès | Comptes | liste paginée, créer, modifier (opérateur, actif, mot de passe) — audité |
| Historique | Journal des modifications | chaque réglage enregistré, chaque rejournalisation des paramètres |

### Système (sous-menu)
| Rubrique | Sous-page | Contenu |
|---|---|---|
| Surveillance | Santé | contrôles, projections, quarantaine, vues lentes |
| | Processus | passages, échecs, dernière erreur, en cours |
| | Anomalies *(nouveau)* | échecs d'évaluation, traces du journal (supplanté, oubli…), échecs de processus gardés au journal |
| | Sorties *(nouveau)* | la file de sortie : en attente, échouées, orphelines, essais, dernière erreur |
| | Modèles en service *(nouveau)* | par fournisseur : créneaux occupés / total, repli ; par rôle : qui sert vraiment |
| | Coûts et appels | par jour, rôle, fournisseur, **modèle** ; derniers appels paginés |
| | Stockage *(nouveau)* | taille des bases, dernier instantané ; la dernière sauvegarde (ce qui s'est écrit depuis), la dernière vérification, les archives gardées |
| Journaux | Chronologie | le journal, filtrable, paginé dans les deux sens |
| | Opérations | ce que les opérateurs ont fait |
| Anatomie | État et faits · Contributions · Toutes les vues | le mécanisme |
| Outils | Simulations | les rapports |

## Étape 3 — les formes

- **Cadres** (`Stats`) : un nombre, un état ; toujours en tête de page, jamais
  plus de six.
- **Tables** : une ligne entière mène à sa fiche ; le détail se déplie sous la
  ligne par un chevron ; le compte total s'affiche au-dessus ; 25 lignes par
  page par défaut.
- **Courbes** : une échelle par courbe, la table des valeurs repliée dessous.
- **Fiches** (`Fields`) : libellé à gauche, valeur à droite, deux colonnes au
  plus en largeur.
- **Formulaires** : un groupe = un cadre titré avec sa phrase d'explication ;
  l'aide de chaque champ sous lui ; les options rarement utiles repliées sous
  « Options avancées » ; une seule barre « Enregistrer » par page.
- **Actions d'en-tête** : une barre de boutons ; le formulaire s'ouvre en
  panneau sous l'en-tête, un seul à la fois.
- **Sous-menus** : les destinations riches (Configuration, Système) ont une
  colonne de navigation à gauche, rangée par rubrique ; les autres gardent des
  onglets.
