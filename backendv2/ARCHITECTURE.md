# Architecture de Mika v2

Mika est une psyché à **journal d'événements** : tout ce qui lui arrive (un message, une décision, une pensée, un rêve) s'ajoute au journal, et l'état de chaque faculté s'en déduit par des fonctions pures. On peut rejouer sa vie, l'expliquer et la simuler (une semaine en secondes). Le pourquoi de chaque choix est dans `docs/adr/` ; l'exploitation dans `deploy/README.md`.

## Couches

```
app            composition : serveur, ligne de commande, sauvegarde
inspector sim  racines secondaires
runtime        le Mind générique : ajouts, épisodes, voies, arbitre, ordonnanceur, effets, projections, santé
faculties plugins adapters
contracts      le contrat public de chaque propriétaire (événements publics, faits) — sans logique
ports          interfaces d'entrée/sortie
vocab          types de valeur partagés par au moins trois propriétaires
kernel         machinerie générique, sans mot du domaine
```

Vérifié à chaque test (`lint-imports`) : une couche n'importe que celles d'en dessous ; **une faculté n'importe jamais une autre faculté** ; les adaptateurs n'importent ni facultés ni runtime ; ni le runtime ni l'inspecteur ne nomment une faculté. `ruff` interdit les imports dans les fonctions, le `except Exception` aveugle hors de `runtime/boundary.py` et des adaptateurs, et toute lecture directe de l'heure, du hasard ou d'identifiants : ils sont injectés.

## Le noyau

- **Événements** (`kernel/events.py`). Un type appartient à un propriétaire, qui seul l'émet ; les autres ne le réduisent que s'il est `public`. Une charge utile porte des observations, des intentions, des deltas, des tirages enregistrés — **jamais un état recalculé**. Les textes libres sont des `Content`, rangés à part et effaçables ; tout texte gardé déclare qui il concerne (ADR 0024). Évolution par *upcasters*.
- **Tranches et réducteurs.** Une tranche immuable par faculté ; un réducteur est pur et **total** (s'il lève, la tranche est marquée `tainted`). Il lit les faits des autres *d'avant* l'événement (double tampon), les paramètres en vigueur à cet instant (`kernel.params_changed`) et un hasard dérivé de l'événement.
- **Faits** (`kernel/facts.py`) : le seul canal de lecture entre facultés. Un fournisseur par clé ou famille, graphe acyclique, lectures déclarées, forme close quand ça varie avec le temps.
- **Concurrence.** `Mind.append` est le seul point d'écriture : dédoublonnage → validation → **garde** → estampille → une transaction qui va au bout (ADR 0021) → publication. Un épisode écrit sous garde (faits lus inchangés, prédicat, **baux**) ou est `Superseded`. Les effets visibles partent après le commit, par la file de sortie ; ce qui sort de la machine est une **capacité**, proposée puis exécutée tout de suite ou après accord.
- **Ordonnanceur** : chaque processus déclare sa prochaine échéance ; un retard donne une exécution avec `missed`.
- **Arbitrage** : des preuves en log-odds par (type d'épisode, cible), cumulées ; des modulations additives ou des vetos ; un déclenchement de Poisson `λ_max · σ(score)` indépendant de la cadence (ADR 0015).
- **Épisodes** (`runtime/pipeline.py`) : admission → baux → départ gardé → enrichissements → composition → appel (boucle d'outils unique) → analyse → commit gardé → règlement (ADR 0009).
- **Prompt** (`kernel/prompt.py`) : des sections déclarées (zones stable / historique / volatile, ancres, rang de coupe) ; filtrées par la divulgation, budgétées, historique coupé avec hystérésis pour garder le cache. Ce qui vient d'ailleurs est **cité** et coupé en premier (ADR 0022).
- **Autres contributions** : évaluations (ce qu'un événement fait ressentir, ADR 0017), préludes, interprètes (ADR 0014), formes de signal (`shapes=`), outils, projections, **vues d'inspection** (`@f.inspect`, ADR 0024).
- **Passerelle LLM** : routage par rôle, un rôle « voix » exige la persona, créneaux à priorité avec préemption, une trace chiffrée par appel.

## Persistance

`mind.db` : journal, contenus, instantanés, file de sortie, projections T0, comptes, réglages — sa vie, qu'on sauvegarde. `views.db` : projections différées, vecteurs, registre des appels de modèle — jetable. Une projection empoisonnée est mise en quarantaine ; une nouvelle version se construit à côté puis bascule ; une tranche dont la version change est reconstruite par **clôture de lecture** depuis la genèse. Une sauvegarde rejoue sa copie et en garde l'empreinte ; une restauration la revérifie avant de toucher au dossier (ADR 0024).

## Les facultés

| Faculté | Ce qu'elle tient |
|---|---|
| `presence` | les connexions vivantes (volatile) |
| `identity` | poignées, confiance du transport, revendications, preuves, liaisons ; la divulgation (ADR 0012) |
| `transcript` | le fil (id d'un message = son `seq`), les résumés des fils longs |
| `memory` | souvenirs, croyances, promesses, échanges ; consolidation, index, rappel filtré (ADR 0010) |
| `body` | rythme circadien, sommeil à deux processus (ADR 0016) |
| `needs` | besoins de compagnie, de s'exprimer, d'apprendre ; le vide ressenti |
| `attention` | signaux remarqués (habituation, dosage), pensées, attentes, digestion nocturne |
| `affect` | humeur, posture par personne, ancres qui guérissent ; reçoit les évaluations |
| `self` | persona, tempérament, estime, récit de soi, journal, rêves (ADR 0019) |
| `expression` | la balise d'émotion, le style, le murmure, la livraison |
| `social` | rythmes de contact, profils, proximité ; saluer, relancer, se confier (ADR 0013, 0018) |
| `agency` | le budget d'initiatives, la période réfractaire |
| `goals` | rappels, explorations, projets : autorité, pas prouvés, attentes, carnets, atelier (ADR 0020) |

Les **plugins** ont la même forme et une confiance restreinte — des signaux, des preuves, des sections citées, jamais la parole forcée ; leur monde vit hors du journal : `email` (IMAP/SMTP, envoi approuvé), `rss`, `camera`, `forge` (ses apps, hors processus, ADR 0023), `sensors` (`POST /api/perceptions`). Les pièces jointes sont perçues au bord (port `preprocess`).

## Autour du noyau

- **Web** : le protocole du frontend (inchangé), comptes et sessions, CSRF, CORS ; une réponse ne part qu'aux connexions de sa personne. **Telegram** : liste blanche avant toute écriture, salons publics, réponse au salon d'origine.
- **Atelier** et **Forge** : bubblewrap sans repli, environnement reconstruit, réseau coupé sauf capacité approuvée ; délais tenus en tuant le processus.
- **Console** (`/inspecteur/`, opérateurs, ADR 0025) : un back-office que **les facultés déclarent** — vues rangées par destination (`@f.inspect(section=…)`), fiches d'objets auxquelles chacune ajoute ses onglets (personne, poignée, but, mail, app), actions d'opérateur journalisées (`@f.action`, origine extérieure, garde, audit `runtime.operated`), vitaux, badges « à traiter », courbes (`@f.series`, `views.db`). La carte est dans `app/console.py`, les réglages dans `app/reglages.py` : des modèles pydantic annotés (`Knob`) rendus en formulaires, secrets jamais réaffichés. Les paramètres internes disent d'où vient chaque valeur (défaut ← tempérament ← réglage ← surcharge, `runtime/params.py`). Pour « pourquoi a-t-elle dit ça ? » : le prompt exact, les outils et la décision de chaque épisode (`runtime/traces.py`, 14 jours).
- **Santé** (`/health`, public) : noms et états seulement ; 503 tant qu'elle n'est pas prête.
- **Simulateur** (`sim/`) : le vrai noyau sur temps virtuel, des interlocuteurs, un modèle factice qui répète tout secret qu'on lui montre, des pannes, des mesures. Voie rapide S01–S18. On valide par cibles d'intention (ADR 0007) et on casse exprès ce qu'un test garde pour vérifier qu'il n'est pas vide.

## Ajouter une faculté

1. `faculties/<nom>/` : tranche gelée, `Params`, `Faculty(...)`.
2. `contracts/<nom>.py` : ce que d'autres doivent lire.
3. Réducteurs, faits, sections, preuves, processus, outils, vues — par décorateurs.
4. L'inscrire dans `app/composition.py`. Au démarrage, sa tranche se reconstruit depuis le journal et elle apparaît seule dans la console (ses vues, ses onglets de fiche, ses actions, ses paramètres documentés par `Knob`).

## Invariants

- Rejouer le journal redonne l'état vivant ; instantané + queue = rejeu complet ; une archive restaurée rejoue au même état.
- Même graine → même journal, quel que soit `PYTHONHASHSEED`.
- Aucun épisode supplanté n'est livré ; aucun effet ne part avant son commit.
- Tout texte gardé dit qui il concerne : l'oubli l'atteint.

## Glossaire

tranche = *slice* · bail = *lease* · supplanté = *superseded* · divulgation = *disclosure* · posture = *stance* · poignée = *handle* · revendication = *claim* · liaison = *binding* · proximité = *closeness* · salon = *room* · but = *goal* · pas = *step* · atelier = *workshop* · capacité = *capability* · citation = *untrusted section* · pensée = *thought* · souvenir = *episode memory* · croyance = *belief* · murmure = *murmur* · vue = *inspection view*

## Commandes

```bash
.venv/bin/python -m pytest -q && .venv/bin/ruff check src tests && .venv/bin/lint-imports
.venv/bin/python -m mika sim run --report sim-reports      # voie rapide + rapport
.venv/bin/python -m mika --data data/v2 serve --port 8001   # puis l'inspecteur : /inspecteur/
.venv/bin/python -m mika --data data/v2 replay --verify
.venv/bin/python -m mika --data data/v2 backup ARCHIVES --keep 14   # verify ARCHIVE, restore ARCHIVE
.venv/bin/python -m mika --help                            # modèles, comptes, Telegram, sens, forge, oubli
```
