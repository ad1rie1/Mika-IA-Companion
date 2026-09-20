# Interface de gestion

L'interface `/gestion/` utilise les gabarits Django et une amélioration progressive
JavaScript. Les pages, filtres, détails et formulaires restent utilisables sans JS.
Le frontend de conversation est une application distincte.

L’inventaire détaillé des parcours, paginations et limites est dans
[Audit des pages](gestion-audit-pages.md).

## Organisation des pages

| Pages | Présentation et accès aux informations |
|---|---|
| Vue d'ensemble | États essentiels en cartes, alertes actionnables, volumes et boucles ; textes nocturnes dépliables. |
| Émotions, drives, rythme | Jauges et cartes pour l'état courant ; tableaux conservés pour comparer personnes et facteurs. |
| Ruminations, chantiers | Listes filtrées, textes complets dépliables, fiches pour origine, attente, résultat et dates. |
| Historique affectif | Courbe et tableaux datés ; paginations indépendantes. |
| Souvenirs, connaissances | Cartes de lecture, sensibilité, thèmes et entités filtrables ; fiches avec provenance et dates. |
| Messages | Fil de lecture, pièces jointes signalées, état d'attente ; filtre de conversation chronologique et fiche complète. |
| Thèmes, entités | Index comparables ; liens vers souvenirs et faits, y compris pour les entités autres que les personnes. |
| Journaux, rêves | Cartes et paginations indépendantes ; fiches avec souvenirs sources, pensées du coucher et rappel. |
| Récit de soi | Version courante stable et historique séparé, même en changeant de page. |
| Identités, personnes | Fiches à onglets ; mêmes composants de lecture que Mémoire pour les messages, souvenirs et connaissances ; humeurs et handles paginés. |
| Revendications, engagements | Comparaison et actions dans la liste ; preuves, notes et descriptions intégrales dépliables. |
| Politique de confiance | Tables de référence, adaptées à la comparaison des seuils et permissions. |
| Observations, décisions, planification | Liste de suivi et fiche explicative : données source, paroles, outils, conditions et résultat. |
| Projets, accords, journal | Avancement et plan de travail ; tâches, fichiers, logs et traces IA paginés indépendamment ; liens d’accord filtrés par projet. |
| Modules | Catalogue de cartes, état, configuration et panneaux dans chaque espace. |
| Email, RSS | Corps et résumés lisibles ; métadonnées des messages, contacts et flux inspectables. Les emails HTML sont convertis en texte échappé. |
| Forge apps | État et journal avant le code ; source repliable, accès au journal complet. |
| Atelier Forge | Modules, journal filtré, collections et inspection des valeurs JSON paginées. |
| Configuration | Groupes et recherche ; listes éditables paginées par un constructeur commun au cœur, aux modules et aux apps ; contexte conservé après écriture. |
| Santé, routage, quotas, consolidation | Tables de comparaison et indicateurs ; sommaire des grandes pages, valeurs et diagnostics consultables. |
| Journal de configuration | Avant/après intégralement dépliable, avec les protections existantes sur les secrets. |

Les listes distinguent un filtre absent (défaut) du choix vide « Tous ». Les petits
référentiels finis restent visibles ensemble ; les collections croissantes sont
paginées, en base ou à partir de l’instantané disponible.

Les textes longs ne sont plus uniquement limités par une hauteur CSS. Le composant
`long_text.html` propose une ouverture native `<details>`. Les fiches ont une URL
stable `/gestion/fiche/<type>/<id>/` et reviennent à la liste avec ses filtres.
Les filtres sont repliables ; sur mobile, les filtres inactifs se ferment au
chargement pour laisser la place aux résultats.
Aucun modèle arbitraire n'est exposé : les types et champs sont déclarés dans
`GestionSysteme/views/records.py`.

Les gros contenus ont un plafond d'affichage annoncé par la mention « tronqué » :
100 000 caractères pour les textes dépliables, les textes des fiches et un corps de mail, 40 000 pour un résumé RSS, 200 000
pour chaque source ou manifeste forgé et chaque bloc JSON d’une fiche. La conversion d'un mail HTML lit au plus
250 000 caractères de source avant d'appliquer le plafond du corps. Les données
stockées restent intactes. Le filtre Entité recherche en base par nom ou numéro
(`123` ou `#123`), sans charger la liste complète des entités.

## Filtres et suggestions

Les filtres natifs proposent des suggestions sur les grands référentiels (thèmes,
handles de l’historique affectif, apps du journal Forge et personnes commanditaires).
`GET /gestion/api/suggestions/<source>?q=…` accepte seulement ces quatre sources,
cherche en base et renvoie au plus 20 suggestions avec un indicateur `more`.
Ce plafond ne limite pas les valeurs filtrables : préciser la recherche retrouve
les suivantes. Les réponses ne sont pas mises en cache et passent par le même
contrôle d’accès que les pages. Le navigateur remplit une `datalist` sans HTML
injecté ; la saisie manuelle reste utilisable sans JavaScript.

Les catégories d’observation, états et tris restent des choix fermés. Les noms de
thèmes et d’apps se filtrent sans sensibilité à la casse ; les handles restent des
identifiants exacts. Le commanditaire accepte uniquement une personne, affichée
comme « Nom (#id) » pour lever l’ambiguïté des homonymes.

## Un seul contrat JSON, version 2

Le schéma JSON Schema est disponible sur `GET /gestion/api/panneaux/schema`, derrière
le même portail que le reste de la gestion. Sa définition est dans `panel_schema.py`.
L'enveloppe obligatoire est :

```json
{"version": 2, "blocks": [{"type": "prose", "title": "Résumé", "text": "Bonjour"}]}
```

Les anciens formats sans enveloppe (`columns/rows`, `tabs`, `fields`) sont supprimés.
Un payload invalide produit un message d'erreur lisible. Aucun adaptateur ancien,
assainisseur de HTML ou calcul de page commençant à zéro n'est conservé.

| Bloc | Propriétés |
|---|---|
| `grid` | `items: [blocs]`, `columns: 1..3` ; une colonne sur petit écran |
| `section` | `title`, `description`, `items: [blocs]` |
| `disclosure` | `title`, `items: [blocs]`, `open: false` |
| `blocks` | `items: [blocs]`, composition verticale |
| `stats` | `items: [{label, value, sub?, tone?, href?}]` |
| `fields` | `items: [{label, value}]` ; value scalaire ou cellule typée |
| `prose`, `code` | `title`, `text` ; texte intégral échappé |
| `note` | `title`, `text`, `tone` |
| `timeline` | `title`, `items: [{title, text?, meta?, tone?, href?}]`, `empty` |
| `table` | `title`, `columns`, `rows`, `pagination?`, `filters?`, `empty` |
| `form` | `action`, `initial: {champ: valeur}`, `title` |

Cellule typée : `{"kind": "badge", "text": "Prêt", "tone": "ok"}`. Types :
`text`, `mono`, `num`, `badge`, `emotion`, `link`, `meter`, `bool`, `muted`.
Un lien porte `href`, une jauge `ratio` (0 à 1), une émotion `emotion`.
Les tons sont `info`, `ok`, `warn`, `danger` ou la chaîne vide.
Les liens autorisés sont HTTP(S), chemins absolus locaux, requêtes `?` et ancres `#`.
Aucun balisage, classe CSS, code JavaScript ou nom de gabarit n'est interprété.

```json
{
  "version": 2,
  "blocks": [{
    "type": "table", "title": "Tâches",
    "columns": [{"key": "titre", "label": "Titre"}, {"key": "etat", "label": "État"}],
    "rows": [{
      "cells": {"titre": "Relire le dossier", "etat": {"kind": "badge", "text": "À faire", "tone": "warn"}},
      "detail": {"type": "form", "action": "modifier", "initial": {"id": "42", "titre": "Relire le dossier"}}
    }],
    "pagination": {"page": 1, "per_page": 25, "total": 1},
    "filters": [{"key": "q", "label": "Recherche", "kind": "search"}]
  }]
}
```

Le handler reçoit les paramètres GET : `page` commence à **1**, `per_page` vaut
25 par défaut et est borné à 200. Il filtre et trie ses données **avant** de les
découper. Il doit borner la page à la dernière page réelle après filtrage.
Le moteur rend les contrôles et conserve les paramètres dans les liens ; il ne
prétend pas filtrer un ensemble dont il ne reçoit qu'une page.
Pour plusieurs tableaux, utiliser des clés de filtre distinctes et
`pagination.param` distinct (par exemple `p_logs`). Déclarer les paramètres de
page sur la vue du manifeste : `page_params: [p_logs, p_notes]`. Comme `page`,
ils arrivent en entiers ≥ 1 ; une valeur absente ou invalide donne 1.
Les autres paramètres GET restent des chaînes. Les contrôles conservent toutes
les valeurs des paramètres répétés qui appartiennent aux autres filtres.

Limites de rendu : 8 niveaux, 200 blocs, 30 colonnes et 200 lignes par tableau.
La taille JSON totale des apps forgées reste soumise à `forge.max_view_payload_kb`.

## Actions et formulaires

Dans un manifeste Forge :

```yaml
views:
  - key: liste
    label: Tâches
    description: Travail à terminer.
    actions:
      - key: modifier
        label: Enregistrer
        fields:
          - {key: id, label: Identifiant, type: hidden, required: true}
          - {key: titre, label: Titre, type: text, required: true, max_length: 200}
```

```python
def action_liste_modifier(api, data):
    # Les champs sont validés et convertis. L'app vérifie sa cible métier.
    if api.storage.get("taches", data["id"]) is None:
        return {"ok": False, "message": "Cette tâche n'existe plus."}
    api.storage.set("taches", data["id"], {"titre": data["titre"]})
    return {"ok": True, "message": "Tâche enregistrée."}
```

Types de champ : `text`, `textarea`, `integer`, `number`, `boolean`, `select`,
`email`, `url`, `hidden`. Options : `required`, `initial`, `help`, `minimum`,
`maximum`, `max_length`, `choices` (chaînes ou `{value, label}`). Un champ
`boolean` est facultatif par défaut : une case décochée transmet `false`.
Déclarer `required: true` pour exiger qu'elle soit cochée. Les autres types
restent obligatoires par défaut.

L'action peut déclarer `description`, `confirm` et `danger`. Un bloc `form`
place une instance dans une fiche ou un détail de ligne. Les actions qui ne sont
pas placées dans le contenu sont présentées en tête du panneau.

Les POST sont protégés par CSRF, les actions inconnues répondent 404, GET répond
405. Une saisie invalide répond 400, conserve les valeurs et affiche les erreurs
sans exécuter le handler. La Forge exécute les actions déclarées dans son bac à
sable avec les mêmes limites de temps que ses autres handlers.
Les messages de résultat et d'erreur sont bornés à 500 caractères avant leur
ajout aux notifications de session.
Les détails contenant un formulaire invalide s'ouvrent automatiquement, même
sans JavaScript, pour rendre la correction visible.

Les plugins Python utilisent les mêmes composants (`panels.Grid`, `Disclosure`,
`Code`, `Timeline`, `ActionForm`) et `PanelAction(fields=(Input(...),))`.
Le handler reçoit `request.panel_data`. Les plugins peuvent toujours livrer un
`Template` Django dans leur code ; ce bloc n'existe pas dans le contrat JSON.
