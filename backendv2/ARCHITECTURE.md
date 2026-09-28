# Architecture de Mika v2

Mika est une psyché à **journal d'événements**. Tout ce qui lui arrive — un message, une décision, une pensée, un rêve — est un événement ajouté à un journal. L'état de chacune de ses facultés se déduit du journal par des fonctions pures. On peut donc rejouer sa vie, l'expliquer (chaîne des causes) et la simuler (une semaine en quelques secondes).

## Couches

```
app            composition : serveur, ligne de commande
inspector sim  racines secondaires
runtime        le Mind générique (ajouts, épisodes, voies, arbitre, ordonnanceur, effets, projections)
faculties plugins adapters
contracts      contrat public de chaque propriétaire (événements publics, clés de faits) — sans logique
ports          interfaces d'entrée/sortie
vocab          types de valeur partagés par au moins trois propriétaires
kernel         machinerie générique, sans mot du domaine
```

Règles vérifiées à chaque test (`lint-imports`) : une couche n'importe que les couches sous elle ; **une faculté n'importe jamais une autre faculté** ; les adaptateurs n'importent ni facultés ni runtime ; le runtime ne nomme aucune faculté. `ruff` interdit en plus les imports dans les fonctions, le `except Exception` aveugle hors de `runtime/boundary.py` et des adaptateurs, et toute lecture directe de l'heure, du hasard ou d'identifiants (`time.time`, `datetime.now`, `random`, `uuid4`…) : ils sont injectés.

## Les contrats du noyau

**Événements** (`kernel/events.py`). Un type d'événement appartient à un propriétaire (préfixe du nom) ; lui seul l'émet ; les autres ne peuvent le réduire que s'il est `public`. Une charge utile porte des observations, des intentions, des deltas et des tirages enregistrés (texte d'un modèle, hasard), **jamais un état recalculé**. Les textes libres sont des `Content` : rangés hors de l'enveloppe à l'ajout, ils ne sont jamais visibles des réducteurs et peuvent être effacés (oubli). Les schémas évoluent par *upcasters* (JSON brut, version n → n+1).

**Tranches et réducteurs** (`kernel/faculty.py`, `runtime/mind.py`). Chaque faculté possède une tranche d'état immuable. Un réducteur est pur et **total** : il ne lève pas ; s'il lève quand même, la tranche est marquée `tainted` et l'événement sauté pour lui. Un réducteur voit sa propre tranche et les faits des autres **d'avant l'événement** (double tampon) : l'ordre des réducteurs n'a pas d'importance. Il reçoit les paramètres en vigueur à l'instant de l'événement (journalisés par `kernel.params_changed`) et un hasard dérivé de l'identifiant de l'événement.

**Faits** (`kernel/facts.py`). Le seul canal de lecture entre facultés. Une clé (`FactKey`) ou une famille (`FactFamily`, p. ex. `STANCE(personne)`) a un seul fournisseur ; le graphe des faits est acyclique ; une lecture non déclarée lève. Un fait qui varie avec le temps se calcule en forme close (`kernel/dynamics.py` : propagateur exact de l'oscillateur amorti). Admission : au moins deux consommateurs, une petite valeur, pas de prose.

**Concurrence.** Le Mind est le seul point d'écriture (`Mind.append`) : dédoublonnage → validation → **garde** → estampille → application → une transaction → publication → notifications. Un épisode lit une racine épinglée, travaille (un appel de modèle peut durer une minute), puis écrit sous **garde** : faits lus inchangés depuis sa base de décision, prédicat vrai, **baux** tenus (`floor:<personne>`, `workshop:<but>`). Sinon `Superseded`, rien n'est ajouté ; le Mind revérifie les gardes en vol à chaque ajout et annule tôt les épisodes devancés. Les effets visibles partent après le commit, par la file de sortie (au moins une fois, idempotents).

**Ordonnanceur** (`runtime/scheduler.py`). Chaque processus déclare sa prochaine échéance ; la boucle dort jusque-là ou jusqu'à un réveil. Après un arrêt ou un saut d'horloge, une échéance en retard donne **une** exécution avec `missed=(de, à)`.

**Arbitrage** (`kernel/arbitration.py`, `runtime/arbiter.py`). Les facultés apportent des preuves en log-odds pour « tel type d'épisode vers telle cible », avec une raison et une plage déclarées. Les preuves se **cumulent** par (type, cible) ; `ANY` soutient toutes les cibles ; les modulations sont des décalages additifs ou des vetos (commutatifs). Le déclenchement est un processus de Poisson d'intensité `λ_max · σ(score)`, tiré par amincissement : le comportement ne dépend pas de la cadence d'évaluation.

**Épisodes** (`kernel/episode.py`, `runtime/pipeline.py`). Pipeline fixe : admission → baux → départ gardé → enrichissements en parallèle → composition → appel (boucle d'outils unique) → analyse → commit gardé → règlement. Issues : `done`, `abstained`, `superseded`, `timeout`, `failed`, `preempted`, `interrupted`, `cancelled` ; seules une réponse ou un renoncement dit règlent une question (ADR 0009).

**Prompt** (`kernel/prompt.py`). Chaque faculté déclare des sections (zone stable / historique / volatile, ancres avant/après, rang de coupe, plancher, étiquettes). Le composeur filtre (type d'épisode, étiquettes coupées, sensibilité au-dessus du niveau de l'audience), ordonne, budgète, et coupe l'historique avec hystérésis pour que le préfixe mis en cache ne bouge pas.

**Passerelle LLM** (`ports/llm.py`, `adapters/llm/`). Routage par rôle avec repli ; un rôle « voix » **exige une persona** ; créneaux à priorité par fournisseur (le premier plan préempte le fond sur un modèle local à un créneau) ; une trace par appel.

## Persistance

Deux fichiers SQLite : `mind.db` (journal, contenus, dédoublonnage, instantanés, file de sortie, projections T0, comptes, réglages — sa vie, qu'on sauvegarde) et `views.db` (projections différées — jetable). T0 dans la transaction d'ajout ; T1 différées avec point de contrôle transactionnel ; T2 préparées dans un **processus** séparé ; un événement empoisonné est mis en quarantaine ; une nouvelle version se construit à côté puis bascule. Une tranche dont la version change est reconstruite par **clôture de lecture** depuis la genèse.

## Les facultés de M1

| Faculté | Tient | Fournit |
|---|---|---|
| `presence` (volatile) | les connexions vivantes | `PRESENT`, `SINCE(poignée)` |
| `identity` | poignées, confiance du canal, certitude, liaison d'un compte | `PERSON`, `IDENTITY`, `DISCLOSURE(poignée, canal, public)` ; section « qui tu as en face » ; l'audience d'un épisode |
| `transcript` | le fil (projection T0 `thread`, id d'un message = son `seq`) | `LAST_FROM`, `LAST_TO`, `HEAD` ; l'historique du prompt (le fil **avec** l'interlocuteur) |
| `body` | le rythme circadien (décalé par le chronotype) | `RHYTHM`, `PHASE`, `ENERGY`, `SLEEP` ; section « ton rythme » |
| `affect` | humeur générale, posture par personne, ancres qui guérissent, balise récente | `MOOD`, `STANCE`, `WARMTH`, `FACE` ; sections humeur et posture ; preuve « débordement » |
| `self` | la persona (un document), le tempérament | `PERSONA` ; le fournisseur de persona des voix |
| `expression` | la balise `[EMOTION:nom:intensité]`, le style | analyse des réponses ; livraison (file de sortie → port `delivery`) |
| `social` | les salutations | preuve « saluer qui arrive », modulation pendant un échange |
| `agency` | le budget d'initiatives | plafond quotidien, période réfractaire ; la consigne d'une initiative |

L'affect est exact à tout instant : oscillateurs en forme close, repos constant par morceaux (débuts de phase, instants déterministes), ancre qui guérit exponentiellement (`propagate_toward`).

## Autour du noyau

- **Web** (`adapters/web/`) : le protocole que lit le frontend ; comptes et sessions dans `mind.db` (scrypt), CSRF à double soumission, CORS avec identifiants, 4401 après `accept()`. Une réponse ne part qu'aux connexions de sa personne ; une réponse ratée est dite, sans voix.
- **Modèles** (`adapters/llm/`) : Claude, OpenAI-compatible, Ollama / Ollama Cloud ; passerelle rechargeable à chaud ; clés chiffrées (Fernet) dans `settings`.
- **Inspecteur** (`/inspecteur/`, opérateurs) : vue d'ensemble, chronologie, chaîne d'un épisode, décisions de l'arbitre, état, modèles.
- **Simulateur** (`sim/`) : le vrai noyau sur temps virtuel, des interlocuteurs, un modèle factice « persona » (qui répète tout secret qu'on lui montre), des pannes (magasin scellé), des mesures, un rapport. Voie rapide : S01, S03, S13 réduit. On valide par cibles d'intention (ADR 0007).

## Ajouter une faculté

1. Créer `faculties/<nom>/` : tranche (dataclass gelée), `Params` si besoin, `Faculty(...)`.
2. Publier dans `contracts/<nom>.py` ce que d'autres doivent lire : événements publics, clés de faits.
3. Écrire réducteurs, faits, sections, preuves, processus, outils — par décorateurs.
4. L'inscrire dans `app/composition.py`.
5. Au démarrage, sa tranche se reconstruit depuis le journal ; le registre valide ses références.

## Invariants

- Rejouer le journal redonne l'état vivant ; instantané + queue = rejeu complet.
- Même graine → même journal, quel que soit `PYTHONHASHSEED`.
- Aucun épisode supplanté n'est livré ; aucun effet ne part avant son commit.
- Aucune lecture de l'heure, du hasard ou d'identifiants hors des adaptateurs.
- Une faculté n'importe jamais une autre faculté.

## Glossaire

tranche = *slice* · bail = *lease* · supplanté = *superseded* · divulgation = *disclosure* · posture = *stance* · chantier = *exploration* · rumination = *thought* · souvenir = *episode memory* · connaissance = *belief* · murmure = *murmur*

## Commandes

```bash
.venv/bin/python -m pytest -q          # tous les tests (ajouter -m "not slow" pour les rapides)
.venv/bin/ruff check src tests && .venv/bin/lint-imports
.venv/bin/python -m mika sim selftest  # déterminisme, sentinelle d'horloge, blocage
.venv/bin/python -m mika sim run --report sim-reports   # voie rapide + rapport markdown
.venv/bin/python -m mika --data data/v2 replay --verify

# un modèle, puis le serveur (le frontend inchangé parle au port 8001)
.venv/bin/python -m mika --data data/v2 llm backend claude --kind claude --model claude-sonnet-5 --api-key sk-ant-…
.venv/bin/python -m mika --data data/v2 llm route claude reply initiative step murmur journal dream narrative
.venv/bin/python -m mika --data data/v2 serve --port 8001   # puis frontend/ : npm run dev
```
