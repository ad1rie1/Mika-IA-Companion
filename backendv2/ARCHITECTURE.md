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

**Concurrence.** Le Mind est le seul point d'écriture (`Mind.append`) : dédoublonnage → validation → **garde** → estampille → application → une transaction (qui va au bout même si l'appelant est annulé, ADR 0021) → publication → notifications. Un épisode lit une racine épinglée, travaille (un appel de modèle peut durer une minute), puis écrit sous **garde** : faits lus inchangés depuis sa base de décision, prédicat vrai, **baux** tenus (`floor:<personne>`, `workshop:<but>`). Sinon `Superseded`, rien n'est ajouté ; le Mind revérifie les gardes en vol à chaque ajout et annule tôt les épisodes devancés. Les effets visibles partent après le commit, par la file de sortie (au moins une fois, idempotents) ; un effet peut journaliser ce qu'il a produit. Ce qui sort de la machine est une **capacité** déclarée par une faculté (`@faculty.capability`) : proposée (`effect.proposed`), exécutée par le runtime tout de suite ou après accord (`effect.resolved`).

**Ordonnanceur** (`runtime/scheduler.py`). Chaque processus déclare sa prochaine échéance ; la boucle dort jusque-là ou jusqu'à un réveil. Après un arrêt ou un saut d'horloge, une échéance en retard donne **une** exécution avec `missed=(de, à)`.

**Arbitrage** (`kernel/arbitration.py`, `runtime/arbiter.py`). Les facultés apportent des preuves en log-odds pour « tel type d'épisode vers telle cible », avec une raison et une plage déclarées. Les preuves se **cumulent** par (type, cible) ; `ANY` soutient toutes les cibles ; les modulations sont des décalages additifs ou des vetos (commutatifs). Le déclenchement est un processus de Poisson d'intensité `λ_max · σ(score)`, tiré par amincissement contre une borne locale (le double de l'intensité actuelle, réévaluée à chaque événement et toutes les 5 min, ADR 0015) : le comportement ne dépend pas de la cadence d'évaluation. Un modulateur voit la preuve cumulée et la plus forte raison prise seule (la barre de réveil compare celle-ci).

**Évaluations** (`@faculty.appraisal`, `@affect.feels`). Ce qu'un événement fait ressentir est déclaré par son propriétaire et reçu par un seul receveur, dans la même application (ADR 0017). **Préludes** (`@faculty.prelude`) : un épisode court avant un autre (le murmure avant une initiative).

**Signaux** (`@faculty.reducer(shapes=[attention.Signal])`). Tout événement public dont la charge utile dérive d'une forme est réduit par qui s'y abonne : chaque plugin déclare son propre événement de signal, l'attention les remarque tous (habituation, dosage) sans en connaître aucun (ADR 0022). **Sections citées** (`untrusted=True`) : zone volatile, coupées en premier, rendues en citation.

**Interprètes** (`@faculty.interpret`). Ce qu'une faculté tire d'un message à son arrivée (« moi c'est Alice »), sans modèle : journalisé juste après la perception, avant que la réponse soit demandée (ADR 0014).

**Épisodes** (`kernel/episode.py`, `runtime/pipeline.py`). Pipeline fixe : admission → baux → départ gardé → enrichissements en parallèle → composition → appel (boucle d'outils unique) → analyse → commit gardé → règlement. Issues : `done`, `abstained`, `superseded`, `timeout`, `failed`, `preempted`, `interrupted`, `cancelled` ; seules une réponse ou un renoncement dit règlent une question (ADR 0009). Un épisode porte son objet (`subject`, p. ex. `goal:12`) ; un candidat peut restreindre les lots d'outils offerts (`bundles`) ; un outil voit les appels déjà faits dans l'épisode et rend `ToolResult(ok=…)`.

**Prompt** (`kernel/prompt.py`). Chaque faculté déclare des sections (zone stable / historique / volatile, ancres avant/après, rang de coupe, plancher, étiquettes). Le composeur filtre (type d'épisode, étiquettes coupées, sensibilité au-dessus du niveau de l'audience), ordonne, budgète, et coupe l'historique avec hystérésis pour que le préfixe mis en cache ne bouge pas.

**Passerelle LLM** (`ports/llm.py`, `adapters/llm/`). Routage par rôle avec repli ; un rôle « voix » **exige une persona** ; créneaux à priorité par fournisseur (le premier plan préempte le fond sur un modèle local à un créneau) ; une trace par appel.

## Persistance

Deux fichiers SQLite : `mind.db` (journal, contenus, dédoublonnage, instantanés, file de sortie, projections T0, comptes, réglages — sa vie, qu'on sauvegarde) et `views.db` (projections différées — jetable). T0 dans la transaction d'ajout ; T1 différées avec point de contrôle transactionnel ; T2 préparées dans un **processus** séparé ; un événement empoisonné est mis en quarantaine ; une nouvelle version se construit à côté puis bascule. Une tranche dont la version change est reconstruite par **clôture de lecture** depuis la genèse.

## Les facultés (M1–M6) et les plugins (M7)

| Faculté | Tient | Fournit |
|---|---|---|
| `presence` (volatile) | les connexions vivantes | `PRESENT`, `SINCE(poignée)` |
| `identity` | poignées, confiance du transport, revendications, preuves, démentis, liaisons (ADR 0012) | `PERSON`, `IDENTITY`, `DISCLOSURE(poignée, canal, public)`, `HANDLES`, `REACHABLE`, `IS_OWNER` ; interprète des messages ; section « qui tu as en face » ; l'audience d'un épisode ; outils `identity_whoami_with`, `identity_doubt`, `identity_forget_binding` |
| `transcript` | le fil (T0 `thread`, id d'un message = son `seq`), les résumés des fils longs | `LAST_FROM`, `LAST_TO`, `HEAD` ; l'historique du prompt (le fil privé de la personne, ou celui du salon) |
| `memory` | souvenirs, croyances, promesses (T0 `memory_items`), échanges (T0 `memory_chunks`), à qui elle a répété quoi (T0 `memory_told`) ; consolidation, indexation ; la nuit : souvenirs de réflexion, fusion des doublons du jour | `CHECKPOINT`, `PROMISES_TO` ; rappel filtré par la divulgation (un sujet délicat rend confidentiel) ; outils `memory_search`, `memory_promise_done` (ADR 0010) |
| `body` | le rythme circadien (chronotype), le sommeil à deux processus (ADR 0016) | `RHYTHM`, `PHASE`, `ENERGY`, `SLEEP`, `AWAKE_SINCE` ; veto en dormant, inertie du réveil, fatigue ; sections « ton rythme », « état cognitif » |
| `needs` | besoins de compagnie, de s'exprimer, d'apprendre ; le vide ressenti | `NEEDS` ; preuves vers quiconque est là ; section « tes envies » |
| `attention` | pensées (échange marquant, croyance révisée, manque), attentes (réponse, retour), digestion nocturne | `THOUGHTS`, `IGNORED` ; preuve « une inquiétude qui insiste » ; section « ce qui te trotte dans la tête » |
| `affect` | humeur générale, posture par personne, ancres qui guérissent, balise récente ; receveur des évaluations | `MOOD`, `STANCE`, `WARMTH`, `REGARD`, `HOSTILITY` (la rancune), `FACE` ; sections humeur et posture ; preuve « débordement » ; ce que vit une relation déborde selon la proximité |
| `self` | la persona (un document), le tempérament, l'estime, le récit de soi, le journal, les rêves (ADR 0019) | `PERSONA`, `ESTEEM`, `YESTERDAY`, `DREAM_RESIDUE` ; le fournisseur de persona des voix ; sections « qui tu es devenue » (stable), « comment tu te sens avec toi-même », « ton fil d'hier » (masqué), « ce que tu as rêvé cette nuit » |
| `expression` | la balise `[EMOTION:nom:intensité]`, le style, le murmure | analyse des réponses ; livraison (file de sortie → port `delivery`) ; prélude « murmure » |
| `social` | contacts par personne (jours, messages, relances sans réponse), profils, proximité déclarée (ADR 0013, 0018) | `CLOSENESS` (vécue), `CONTACT` (rythme propre, silence), `MISSED`, `SENSITIVE`, `GREETED` ; preuves saluer, envie de discuter, reprendre contact, chercher du réconfort ; retenue (rancune, jamais deux messages sans réponse) ; sections « ce que tu sais de cette personne », « ce que tu perçois de son état » ; relecture des profils |
| `agency` | le budget d'initiatives | plafond quotidien, période réfractaire à gigue enregistrée, allongée par les initiatives ignorées ; la consigne d'une initiative |
| `goals` | buts (rappels, explorations, projets) avec autorité, pas, verdicts prouvés, attentes nominatives, carnets, effets proposés (ADR 0020) | `LIVE`, `STATUS(but)` ; preuves avancer (`STEP`), rappeler, raconter (gradué par le lien) ; ouverture d'elle-même (inquiétude, curiosité) ; sections « ce à quoi tu travailles », « le rappel », « ce que tu as mené à bout », « ce que tu as en train » ; outils `report_step`, `goal_note`, `goal_drop`, `goal_remind`, `create_project`, `ws_*` (atelier) ; capacité `goals.networked` |

Les **plugins** ont la forme d'une faculté, une confiance restreinte (ils ne forcent jamais la parole : des signaux, des preuves, des sections citées) et leur monde hors du journal :

| Plugin | Tient | Apporte |
|---|---|---|
| `email` | les mails remarqués (lus ou non), port `mail` (IMAP/SMTP, cache à part) | signal par mail (tri par le rôle `triage`, heuristique sinon) ; le dire à sa propriétaire (une fois) ; section « tes mails » (propriétaires) ; outils `email_list`, `email_read`, `email_send` (capacité approuvée) |
| `rss` | les titres remarqués, port `feeds` | signal pour ce qui touche ses centres d'intérêt (sans modèle) ; section « dans tes flux » ; outils `rss_list`, `rss_read` (par identifiant) |
| `camera` | ce qu'elle a vu, port `camera` (images en mémoire, route `/ws/camera`) | signal quand l'image change (rôle `caption`) ; section « ce que tu vois » (propriétaires) ; outil `camera_look` |
| `forge` | ses apps : versions, activation, échecs, disjoncteur, ce qui les attend ; port `forge` (hôte hors processus) | signaux d'apps (espacés), « mon app ne marche plus » ; `on_event` (signaux anodins seulement) ; section « tes apps » ; outils `forge_*`, `forge_call` (promus ou au travail) (ADR 0023) |
| `sensors` | rien (il porte l'événement) | les signaux d'appareils reçus par `POST /api/perceptions` |

Les pièces jointes sont perçues au bord (port `preprocess` : documents, images, messages vocaux), sur le web comme sur Telegram.

L'affect est exact à tout instant : oscillateurs en forme close, repos constant par morceaux (débuts de phase, instants déterministes), ancre qui guérit exponentiellement (`propagate_toward`).

## Autour du noyau

- **Web** (`adapters/web/`) : le protocole que lit le frontend ; comptes et sessions dans `mind.db` (scrypt), CSRF à double soumission, CORS avec identifiants, 4401 après `accept()`. Une réponse ne part qu'aux connexions de sa personne ; une réponse ratée est dite, sans voix. Une propriétaire voit ses projets et les actions en attente ; un opérateur approuve ou refuse (`/api/projects/pending/<id>/…`), puis chacun reçoit son état à jour.
- **Atelier** (`adapters/workshop/`) : un dossier par but, bubblewrap sans repli, environnement reconstruit, réseau coupé sauf capacité approuvée, git par pas.
- **Monde** (`adapters/mail`, `feeds`, `camera`, `preprocess`, `forge`) : IMAP/SMTP et flux avec leurs caches, tampon de caméra, prétraitement des pièces jointes, hôte de la Forge (un processus bubblewrap par app).
- **Telegram** (`adapters/telegram/`) : liste blanche avant toute écriture, limite par compte, groupes = salons publics (elle entend tout, répond à ce qui lui parle), réponse dans le salon d'origine, conversations privées = adresses où lui écrire. Livraison routée par canal (`app/delivery.py`).
- **Vecteurs** (`adapters/vectors/`) : un cache (SQLite + numpy), plongement sentence-transformers local ou par hachage (simulateur) ; reconstructible à l'octet.
- **Modèles** (`adapters/llm/`) : Claude, OpenAI-compatible, Ollama / Ollama Cloud ; passerelle rechargeable à chaud ; clés chiffrées (Fernet) dans `settings`.
- **Inspecteur** (`/inspecteur/`, opérateurs) : vue d'ensemble, chronologie, chaîne d'un épisode, décisions de l'arbitre, état, modèles.
- **Simulateur** (`sim/`) : le vrai noyau sur temps virtuel, des interlocuteurs, un modèle factice « persona » (qui répète tout secret qu'on lui montre), des pannes (magasin scellé), des mesures, un rapport. Voie rapide : S01, S03, S13 réduit, S15 (mémoire), S02 (troll), S04 (confidentialité), S05 (amie absente), S12 (imposteur), S06 (journée vide), S07 (semaine type), S08 (la nuit), S09 (exploration), S10 (but bloqué), S11 (rappels la nuit), S16 (projet), S17 (courrier et flux), S18 (ses apps). On valide par cibles d'intention (ADR 0007), et on vérifie qu'un test n'est pas vide en cassant exprès ce qu'il garde.

## Ajouter une faculté

1. Créer `faculties/<nom>/` : tranche (dataclass gelée), `Params` si besoin, `Faculty(...)`.
2. Publier dans `contracts/<nom>.py` ce que d'autres doivent lire : événements publics, clés de faits.
3. Écrire réducteurs, faits, sections, preuves, processus, outils — par décorateurs.
4. L'inscrire dans `app/composition.py`.
5. Au démarrage, sa tranche se reconstruit depuis le journal ; le registre valide ses références. La persona et les paramètres sont journalisés avant que les processus tournent (`Kernel.start(configure=…)`).

## Invariants

- Rejouer le journal redonne l'état vivant ; instantané + queue = rejeu complet.
- Même graine → même journal, quel que soit `PYTHONHASHSEED`.
- Aucun épisode supplanté n'est livré ; aucun effet ne part avant son commit.
- Aucune lecture de l'heure, du hasard ou d'identifiants hors des adaptateurs.
- Une faculté n'importe jamais une autre faculté.

## Glossaire

tranche = *slice* · bail = *lease* · supplanté = *superseded* · divulgation = *disclosure* · posture = *stance* · poignée = *handle* · revendication = *claim* · liaison = *binding* · recoupement = *corroboration* · proximité = *closeness* · regard = *regard* · salon = *room* · chantier = *exploration* · but = *goal* · pas = *step* · atelier = *workshop* · capacité = *capability* · signal = *signal* · citation = *untrusted section* · rumination = *thought* · souvenir = *episode memory* · connaissance = *belief* · murmure = *murmur*

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

# Telegram (jeton chiffré) ; ce qu'un opérateur sait mieux qu'elle (serveur arrêté)
.venv/bin/python -m mika --data data/v2 telegram token 123456:ABC…
.venv/bin/python -m mika --data data/v2 telegram allow 123456789        # n'écouter que ces conversations
.venv/bin/python -m mika --data data/v2 telegram owner 123456789        # vos comptes Telegram
.venv/bin/python -m mika --data data/v2 identity link tg_123456789 user_1
.venv/bin/python -m mika --data data/v2 social closeness user_1 close

# ce qu'elle perçoit du monde (secrets chiffrés), et les apps promues
.venv/bin/python -m mika --data data/v2 mail set --address mika@… --imap-host … --user … --password … --smtp-host …
.venv/bin/python -m mika --data data/v2 rss add https://exemple.fr/flux.xml
.venv/bin/python -m mika --data data/v2 stt set https://api.openai.com/v1 sk-…      # messages vocaux
.venv/bin/python -m mika --data data/v2 forge promote cafe
.venv/bin/python -m mika --data data/v2 sensors token      # puis POST /api/perceptions, Authorization: Bearer …
```
