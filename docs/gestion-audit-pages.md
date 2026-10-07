# Audit des pages de gestion

> **v1 archivée (`old/backend/`).** `/gestion/` était la console Django de l'ancien moteur ; elle n'est
> plus servie. Le moteur vivant est [`backendv2/`](../backendv2/README.md) : il écoute sur le port 8001
> et sa console est `/inspecteur/`.

Cet inventaire accompagne la refonte de `/gestion/`. Il distingue les listes qui
peuvent grandir, les aperçus et les petits référentiels à comparer ensemble.
Le contrat des panneaux est décrit dans [gestion-interface.md](gestion-interface.md).

## Règles communes

- Une liste de données se filtre avant pagination. Les paramètres restent dans
  l’URL, y compris une valeur vide choisie pour « Tous ». L’absence de paramètre
  peut appliquer un défaut ; choisir « Tous » doit réellement le désactiver.
- Chaque liste indépendante d’un même écran possède son paramètre de page.
  Filtrer une liste conserve les autres listes et leurs paramètres répétés.
- Les compteurs d’ensemble ne se calculent pas sur la tranche affichée.
  Le pager annonce les bornes de la sélection. Une page hors limites revient
  à la dernière page existante.
- Les listes ORM d’objets ont un tri départagé par clé primaire. Le helper
  n’ajoute pas de clé aux agrégats : cela changerait les groupes.
- Une fiche ou une modification revient à sa liste avec son contexte, au moyen
  du contrôle partagé `retour_sur`. Aucun retour extérieur n’est accepté pour
  les nouveaux parcours projet/configuration.
- Les textes dépliables et les textes des fiches sont limités à 100 000
  caractères ; les blocs JSON des fiches à 200 000. La mention « tronqué » est
  explicite. Les plafonds spécifiques email, RSS et source Forge restent actifs.

## État, mémoire et conscience

| Page | Question et présentation | Pagination / accès à la suite |
|---|---|---|
| Vue d’ensemble | État courant, volumes et éléments demandant une intervention. Les liens d’alerte reprennent les filtres correspondant au compteur. | Synthèse de catégories fixes ; liens vers les listes. |
| Émotions | Humeur globale, oscillateurs par personne, diagnostic du moteur. | Personnes : 25 par défaut, recherche par identifiant et lien vers la fiche affective ; état courant restaurable. |
| Drives | Quatre cartes de tension, seuil et satisfaction ; horizon et échelle des courbes, cas particulier du repos. | Ensemble fini des pulsions, affiché ensemble. |
| Ruminations | Pensées, origine, émotion et évolution. | Liste filtrée, 25 par défaut ; fiche dédiée. |
| Chantiers | Intention, état, progression, attente et résultat. Derniers mouvements d’abord ; envie recalculée au moment de la lecture. | 25 par défaut, recherche par titre, filtre d’état, fiche complète. |
| Rythme et sommeil | Phase, énergie et réglages effectivement appliqués. | État courant et référentiels fixes, sans pagination. |
| Historique affectif | Frise récente, archives globales, relevés par personne et résumés. Le filtre handle fonctionne aussi quand seuls les résumés subsistent. | `p_global` / `p_instantanes` / `p_resumes`, trois paginations ; 25 par défaut. |
| Souvenirs | Lire un épisode, retrouver thèmes, personnes et connaissances dérivées. | 25 par défaut, filtres ; fiche et connaissances dérivées paginées par 10. |
| Connaissances | Distinguer faits valides et invalidés, confiance et source. | 25 par défaut, filtres et fiche. |
| Thèmes | Index des sujets vers leurs souvenirs et faits. | Index paginé ; suggestions recherchées en base et filtre insensible à la casse, sans couper aux 200 premiers thèmes. |
| Entités | Distinguer personnes, objets, lieux et concepts. | Index paginé, recherche et filtres ; liens de mémoire. |
| Messages | Conversation et contexte de réception, pièces jointes et réponses attendues. | 25 par défaut ; ordre chronologique dans une conversation ; fiche. |
| Journaux et rêves | Cartes de lecture et fiches complètes : moments sources, pensées ouvertes au coucher, rumination source et rappel. | `p_journaux` et `p_reves`, 15 chacun ; souvenirs sources des fiches par 10, références supprimées signalées. |
| Récit de soi | Version actuelle suivie des versions précédentes. | Version actuelle fixe ; historique par 10. |
| Observations | Signal reçu, interprétation et traitement. | 25 par défaut, recherche/catégorie/état et fiche. |
| Décisions | Motif, conduite, paroles, outils et état au moment du cycle. | 25 par défaut, filtre de conduite et fiche. |
| Planification | Agenda des intentions en attente, reports, tentatives et résultats. Tri sur la prochaine tentative, puis priorité ; historique récent quand on quitte « en attente ». | 25 par défaut, recherche et état ; compteurs globaux, fiche. |

## Social

| Page | Question et présentation | Pagination / accès à la suite |
|---|---|---|
| Identités | Qui parle, liaison à une entité, verdict de confiance et divulgation. | 25 par défaut après calcul du verdict et filtres. |
| Revendications | Quelles preuves attendent une décision ? | 25 par défaut ; « Tous » donne aussi les preuves déjà tranchées. |
| Personnes | Entrée par personne vers la mémoire qui la concerne. | 25 par défaut, recherche. |
| Engagements | Promesses et suivi. | 25 par défaut, filtres. |
| Politique de confiance | Comparer planchers, plafonds et permissions. | Matrices finies affichées ensemble. |
| Identité / verdict | Expliquer le calcul du verdict et les preuves. | Aperçus de 5 preuves, compte total et liens vers le registre filtré complet. |
| Identité / handles | Comparer les canaux, identifier celui qui détermine le verdict. | 25 ; le handle principal se calcule sur tous les handles et reste en première ligne. |
| Identité / échanges | Lire les messages des seuls handles de cette identité. | 25 par défaut ; filtre borné à l’identité. |
| Identité / preuves | Lire chaque preuve, son poids et son issue ; formulaire de décision dépliable sur place. | 25 par défaut, filtres et retour après action. |
| Identité / actions | Opérations possibles sur cette identité. | Formulaires, pas une collection historique. |
| Personne / synthèse | Fiche mémoire, divulgation, affect courant, identités et projets confiés. | `p_identites` par 25 ; `p_projets` par 10 ; `p_humeurs` par 3. Aperçu de 3 handles par identité, total et lien vers tous les handles. |
| Personne / souvenirs | Épisodes concernant cette personne. | 25 par défaut et fiche. |
| Personne / connaissances | Faits concernant cette personne. | 25 par défaut et fiche. |
| Personne / échanges | Messages résolus par ses handles. | 25 par défaut et fiche. |
| Personne / affect | Affect courant et tendances distinctes par handle. | `p_humeurs` par 12 ; `resumes` par 15 ; `instantanes` par 25. Tendances traduites, jauges cohérentes avec l’émotion. |
| Personne / engagements | Cartes des promesses : engagements en attente par échéance, puis historique récent ; souvenir source accessible. | 25 par défaut, filtres. |

## Projets et administration

| Page | Question et présentation | Pagination / accès à la suite |
|---|---|---|
| Projets | Priorité, état, progression et garde-fou réellement configuré. | 25 par défaut ; actifs au départ, « Tous » accessible. |
| Projet / fiche | Description visible en tête, puis avancement et accord attendu ; états des tâches modifiables directement, résultats et suppression dépliables ; cadre d’exécution séparé. | `p_taches` / `p_journal` / `p_fichiers` par 25 ; filtres de tâche et compteurs sur tout le projet. |
| Projet / diagnostic IA | Demande, contexte transmis, réponse brute, JSON interprété et issue de chaque passage conservé. | `p_prompts` par 10 ; fiche `prompt-projet`, gros champs chargés seulement en ouvrant la fiche. |
| Projet / création et édition | Mandat, périmètre, cadence et budget. | Suggestions de personnes ; nom visible en édition. Nom exact ou #identifiant également acceptés, autres types refusés par le champ et le formulaire. Homonymie levée par le #id. |
| Accords de projets | Revoir la proposition, puis approuver ou rejeter. | 25 par défaut ; recherche de projet par titre/#identifiant, lien préfiltré depuis la fiche. |
| Journal des projets | Comprendre les passages du lanceur. | 25 par défaut ; filtres projet/action, fiche. Aucun projet exclu par un sélecteur limité à 200. |
| Catalogue modules | État, capacités, configuration et accès à l’espace. | `p_modules` par 12, recherche et état ; compteurs globaux. |
| Catalogue outils MCP | Comprendre les outils disponibles, leur source et les paramètres requis/types/défauts. | `p_outils` par 25, recherche indépendante ; contrat des paramètres dépliable. |
| Espace module / état | Disponibilité, cycle de vie et capacités. | Fiche d’un module ; configuration accessible même arrêté. |
| Configuration cœur / module / app | Réglages groupés séparés des listes éditables. | Un seul constructeur `record_lists` ; `p_lignes`, 25 par défaut, recherche, compte total et retour après écriture. |
| Email / boîte | Trier les messages et lire leur contenu et métadonnées. | Liste paginée, filtres, fiche adressable ; HTML converti en texte. |
| Email / contacts | Dernier échange et informations connues. | Liste paginée, recherche et compte. |
| RSS / articles | Lire les articles et leur provenance. | Liste paginée, filtres et fiche adressable. |
| RSS / flux | État de collecte et dernière erreur. | Liste paginée, détail inspectable ; configuration des flux dans son onglet. |
| Caméra / devices | Caméras connectées, boucle et dernière observation ; distinction entre module arrêté, analyse désactivée/suspendue/autorisée. | 25 ; observation complète dépliable, durée de retrait lue dans le réglage effectif. |
| Catalogue Forge apps | État, contexte, cadence et espace de chaque app. | 12 ; recherche et filtre d’état, compteurs globaux. |
| App Forge / état | État, diagnostic, source et manifeste repliables. | Aperçu explicite des 30 derniers logs ; lien vers le journal complet filtré. |
| Atelier Forge / modules | Comparer l’état de toutes les apps. | 25 par défaut, recherche. |
| Atelier Forge / journal | Rechercher erreurs et messages par module. | 50 par défaut ; nom de module libre exact, sans limite cachée de 100 noms. |
| Atelier Forge / stockage | Explorer les collections puis leurs valeurs. | Collections par 50 ; valeurs par 25 par défaut, recherche et JSON inspectable. |
| Panneaux d’une app Forge | Interface décrite par l’app via le contrat v2. | Pagination fournie par son handler, clés indépendantes déclarées dans `page_params`. |
| Santé | Pannes, boucles, cadence, disjoncteurs et abonnements au bus. | `p_sites` par 50 ; `p_bus` par 25 dans l’ordre de diffusion (priorité, nom). Boucles et abonnés en échec tous visibles ; compteurs globaux. Rôles/fournisseurs finis affichés ensemble. |
| Routage IA | Rôle → modèle effectif ; les six fournisseurs déclarés et présence des identifiants. | Modèles par 25 avec recherche ; liens directs vers leurs réglages. Rôles et fournisseurs affichés ensemble. |
| Quotas | Consommation par rôle, cache et budgets projet. | Projets par 25 avec titre et plafond, projet supprimé sans lien cassé. Référentiels de rôles affichés ensemble. |
| Consolidation | Volumes traités lors des passages. | 50 par défaut. |
| Journal de configuration | Changements, auteur, avant et après. | 50 par défaut, filtres de clé/action ; secrets masqués. |

## Limites assumées

La pagination en base s’applique aux QuerySets. Les instantanés du moteur, les
inventaires de modules, les verdicts calculés et `config_service.list_rows`
renvoient des collections en mémoire : leur **rendu** est paginé, leur acquisition
reste complète. La fiche d’une personne calcule la divulgation sur l’ensemble de
ses identités, indépendamment de la page affichée.

L’atelier projet est un aperçu du disque : son inventaire conserve le plafond
`projects.workspace.max_tree_entries` avec une mention de coupe, et le journal
Git montre explicitement les dix derniers enregistrements. La pagination du
journal d’exécution et des traces IA, elle, couvre toutes les lignes conservées.
Les politiques de rétention restent celles des moteurs. Les détails dépliés d’un
tableau prennent la largeur visible de leur conteneur, même si ses colonnes
nécessitent un défilement horizontal.

Le moteur ne peut pas récupérer des lignes qu’un plugin ou une app forgée ne
lui transmet pas. Le contrat permet la pagination, les filtres et le détail,
mais le handler reste responsable du tri, de la requête et du total annoncés.
Les panneaux natifs inclus dans le projet ont été examinés séparément.

## Vérification

`test_gestion_systeme.py` parcourt les destinations et onglets de la navigation,
les fiches sociales et les formulaires de configuration. `test_gestion_page_logic.py`
ajoute des collections dépassant une page : absence de doublons, indépendance des
listes, filtres sans plafond caché, compteurs globaux, reports de l’agenda,
fournisseurs, retours et diagnostic des projets. Les suites de panneaux/Forge
vérifient le contrat, les formulaires, l’échappement et les contenus bornés.
La vérification visuelle utilise une base temporaire, en thèmes clair/sombre et
aux largeurs 390 et 1440 pixels ; les contrôles ne modifient pas les données réelles.


## Passe approfondie du 20 septembre 2026

Les six onglets d’une personne, les cinq d’une identité, les sept de Mémoire,
les six de Vie intérieure, les panneaux Email/RSS/Caméra et les trois vues de
`veille_hn` ont été parcourus avec des données représentatives. Le contrôle mobile
à 390 px couvre aussi les configurations Email/RSS/Forge et les nouvelles fiches
de journal et de rêve. Les vues de lecture principales ont été inspectées par
captures ; les autres contrôles vérifient le rendu, les bornes et la navigation.

Le jeu isolé comporte notamment 32 handles pour une identité, 34 preuves,
61 souvenirs/faits/engagements et résumés supplémentaires, 18 journaux et rêves,
57 mails et contacts, 32 flux et caméras simulées, ainsi que plusieurs pages
pour chaque collection de l’app forgée. Sont vérifiés : états sans liaison,
texte long, mail HTML sans texte brut, source supprimée, page suivante,
retour à une liste filtrée et conservation des paginations indépendantes.

`veille_hn` est la seule app forgée installée dans ce dépôt de travail. Ses vues
réelles sont exécutées dans la sandbox : filtre de score fermé aux choix proposés,
passages les plus récents d’abord, dates explicites et pagination. Sa version locale
passe à 7 ; son code sous `data/forge_modules/` est ignoré par Git, comme les autres
données d’exécution. Les archives de versions ne sont pas des apps distinctes.

Cette passe vérifie le rendu à partir de données et d’états représentatifs ; elle
ne déclenche ni collecte IMAP/RSS externe, ni capture ou analyse d’une caméra réelle.
Les futures apps forgées doivent encore faire vérifier leurs propres handlers.

La suite ciblant GestionSystème, les panneaux, les apps/handlers Forge, RSS et le
durcissement du runtime passe avec **1 157 tests réussis et 8 ignorés**. La dernière
présentation des pulsions est aussi revérifiée séparément. Les contrôles de rendu
et les modifications de données de démonstration n’altèrent pas la base du projet.


## Reprise après revue des interactions

La reprise conserve les composants partagés et corrige les choix d’usage :

- commanditaire limité aux personnes dès le champ de saisie ; suggestions et nom
  lisible en édition, identifiant conservé pour distinguer les homonymes ;
- catégories d’observation en liste fermée ; suggestions à la demande pour thèmes,
  handles et apps du journal Forge, sans plafond caché sur les valeurs filtrables ;
- description du projet visible en tête et changements d’état des tâches par
  boutons directs ; valeurs des états dérivées du modèle ;
- agenda avec délai relatif fondé sur la prochaine tentative, date exacte et
  échéance initiale en cas de report ; aide `schedule_action` rétablie ;
- états vides distinguant attente normale et recherche sans résultat ; aides
  caméra et installation des greffons accessibles dans des blocs repliables ;
- incidents et boucles tous visibles sur Santé ; liste complète des abonnés
  paginée dans l’ordre de diffusion du bus ;
- conteneur CSS limité aux tableaux de panneaux, vérifié dans un parent flex.
  Les cellules de texte gardent une largeur de lecture minimale et les colonnes
  déclarées compactes ne coupent plus les noms mot par mot.

`test_gestion_interactions.py` ajoute 17 cas couvrant ces parcours. La validation
élargie passe avec **1 174 tests réussis, 8 ignorés**. Les contrôles navigateur
utilisent toujours la base temporaire : suggestion au-delà des vingt premières,
filtrage avec une casse différente, nom du commanditaire en édition, changement
réel d’état d’une tâche avec conservation des deux pages, agenda clair/sombre,
catégories et détails Caméra sur mobile. Aucun compte externe ni matériel réel
n’est sollicité.
