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
- **Ordonnanceur** : chaque processus déclare sa prochaine échéance ; un retard donne une exécution avec `missed`. Un processus qui échoue ou ne produit rien recule (30 s, 1 min… 1 h) ; un ajout entièrement dédoublonné n'est pas un progrès ; au-delà de 120 passages par minute, une **rafale** le retient et la santé le montre (KER-1, ADR 0040).
- **Arbitrage** : des preuves en log-odds par (type d'épisode, cible), cumulées ; des modulations additives ou des vetos ; un déclenchement de Poisson `λ_max · σ(score)` indépendant de la cadence (ADR 0015). Un épisode porte sur un seul **sujet** (`subject` : un but, un objectif de projet) : quand plusieurs candidats d'une ligne en ont un, leurs preuves se cumulent mais seuls les arguments du plus fort passent — les autres reviennent plus tard au lieu de voir leur sujet écrasé.
- **Épisodes** (`runtime/pipeline.py`) : admission → baux → départ gardé → enrichissements → composition → appel (boucle d'outils unique) → analyse → commit gardé → règlement (ADR 0009). Un **tour de conversation** (adresse, salon) reçoit une réponse, à son dernier message — une rafale n'en donne pas trois ; ce qu'elle ne peut pas dire est livré une fois par tour (`reply_failed` / `reply_abstained`). La file de sortie a deux voies (la parole n'attend pas derrière un `git push`), des échéances par gestionnaire et des réessais datés avec recul ; une parole de plus de 10 min ne part plus (ADR 0040). Démarrage en deux temps : `Kernel.boot()` puis `live()`.
- **Prompt** (`kernel/prompt.py`) : des sections déclarées (zones stable / historique / volatile, ancres, rang de coupe) ; filtrées par la divulgation, budgétées (une réserve calculée avant la composition), historique coupé avec hystérésis et une coupe mémorisée par fil pour garder le cache. Le fil porte des **repères de temps** perçus (« [le lendemain, mardi 14h13] ») et, en salon, « Nom : » ; son résumé est épinglé (ADR 0041). Ce qui vient d'ailleurs est **cité** et coupé en premier (ADR 0022).
- **Autres contributions** : évaluations (ce qu'un événement fait ressentir, ADR 0017), préludes, interprètes (ADR 0014), formes de signal (`shapes=`), outils, projections, **vues d'inspection** (`@f.inspect`, ADR 0024).
- **Passerelle LLM** : routage par rôle, un rôle « voix » exige la persona, créneaux à priorité avec préemption (un créneau réservé au premier plan dès deux, priorité héritée par les appels faits pendant un épisode), délais par voie (conversation 120 s, fond 300 s), passerelle collante par `call_id` et `release` en fin de boucle, une trace chiffrée par appel, un repli par fournisseur avec le temps restant (ADR 0038). Fournisseurs : Claude (API), **Claude Code** (la CLI `claude -p` et son propre login, jamais un jeton ; ses appels d'outils passent par un relais MCP local et c'est le runtime qui les exécute — ADR 0026), compatibles OpenAI, Ollama. Les lots d'outils hors du socle d'un épisode sont « à la demande » : le modèle les cherche (recherche d'outils), un catalogue d'une ligne par lot le lui dit.

## Persistance

`mind.db` : journal, contenus, instantanés, file de sortie, projections T0, comptes, réglages — sa vie, qu'on sauvegarde. `views.db` : projections différées, vecteurs, registre des appels de modèle — jetable. Une projection empoisonnée est mise en quarantaine ; une nouvelle version se construit à côté puis bascule ; une tranche dont la version change est reconstruite par **clôture de lecture** depuis la genèse. Une sauvegarde rejoue sa copie et en garde l'empreinte ; une restauration la revérifie avant de toucher au dossier (ADR 0024).

## Les facultés

| Faculté | Ce qu'elle tient |
|---|---|
| `presence` | les connexions vivantes (volatile) |
| `identity` | adresses, confiance du transport, revendications, preuves, liaisons ; la divulgation (ADR 0012). La propriété se juge sur **l'adresse qui parle** (`audience.owner`), jamais en salon public ; une liaison par recoupement demande deux preuves sur deux messages, et le fil des autres adresses (`THREAD`) reste fermé tant qu'un opérateur ne l'a pas confirmée (ADR 0035) ; un nom dont on lui a parlé (`name:alice`) se relie à une personne par un opérateur, jamais deviné (ADR 0048) |
| `transcript` | le fil (id d'un message = son `seq`), les résumés des fils longs |
| `memory` | souvenirs, croyances, promesses, échanges ; consolidation par conversation, index, rappel hybride filtré (ADR 0010). Qui l'a confié (`told_by`) et qui l'a entendu ; le secret explicite ne quitte jamais son confident, la confidence peut s'ouvrir aux proches ; au-dessus de l'audience, elle sait qu'elle sait (« ce n'est pas à moi d'en parler ») ; ce qui se passe dans la vie des autres (`memory.life_events`, situations en cours comprises) ; un secret ne laisse même pas deviner qu'il existe, le privé se tait sans mensonge (ADR 0043) ; tenir une promesse datée à l'heure (`memory.keep_promise`, due) ; ce qu'elle dit d'elle-même (goût, avis, fait) tient un an (ADR 0046) |
| `body` | rythme circadien, sommeil à deux processus (ADR 0016) ; la nuit, seule une amie ou une proche la réveille (`body.woken_by`) : les autres attendent son réveil et reçoivent une réponse par personne (`KernelDeps.reply_wait`, ADR 0036) |
| `needs` | besoins de compagnie, de s'exprimer, d'apprendre ; le vide ressenti ; les retrouvailles après un vide (`needs.reunited`) ; la matière d'une initiative, la personne d'abord, jamais une rêverie (ADR 0047) |
| `others` | ce qu'elle devine des autres : ton habituel et du moment, surprise, événements graves, inquiétude (aussi née de sa propre réponse) et prise de nouvelles, contagion émotionnelle, délais de réponse et heures où l'on répond, appris de l'expérience (ADR 0028, 0035) ; un mot d'encouragement la veille (`others.cheer`), « alors, cet entretien ? » une fois le moment passé (`others.follow_up`), jamais sur la foi d'un tiers ; les heures actives de chacun (`others.hours`) ; un au revoir lu (`closing`) (ADR 0043, 0046) |
| `attention` | signaux remarqués (habituation, dosage), pensées (celles nées d'un signal sont citées : « CE QUE TU AS REMARQUÉ »), attentes par personne (`attention.awaiting`, une conversation close n'attend rien), digestion nocturne ; une pensée née d'un échange naît quand il s'est posé, de son moment le plus marquant (ADR 0043) ; solitude et attente mesurées au rythme de la personne ; « j'ai été dure avec X » (ADR 0046) |
| `affect` | trois échelles : le moment, le fond de la journée, la relation (ancre qui guérit, attachement lent `affect.bond`) ; les impulsions visent depuis le repos ; reçoit les évaluations (ADR 0032) ; une cause d'humeur passée se dit au passé ; des excuses sincères pardonnent, graduées par la proximité (ADR 0047) |
| `self` | persona, tempérament, estime qui a des causes (sociomètre `self.touched`), récit de soi, journal de la journée vécue, rêves posés au réveil (`self.woke_with`) (ADR 0019, 0036) ; une vie d'IA VTuber, des goûts et des faits stables dans la persona (ADR 0047) ; un journal intime et sa version « à raconter », la seule montrée à qui n'en est pas le seul concerné (ADR 0043) |
| `expression` | la balise d'émotion, le style, le murmure (à la personne visée, voix intérieure), la livraison ; « CE QUE TU TE RÉPÈTES » : ouvertures, formules, bonjour redit, monologues (ADR 0043) |
| `social` | rythmes de contact, profils (nourris de ce que la personne a dit elle-même), proximité sur fenêtre glissante avec plancher d'histoire et attachement, réciprocité ; saluer, relancer, se confier (ADR 0013, 0018, 0035) |
| `agency` | le budget d'initiatives, la période réfractaire ; **ne pas harceler** : après une initiative sans réponse, plus rien vers la personne sauf une relance douce ; retenue après sa réponse ; prévenir (`INFORMS`) n'est pas relancer ; se raviser (ADR 0033) ; ce qui est dû (`OWED`) et ce qui prévient, déclarés une fois dans le contrat, passent la rancune (ADR 0044) ; une raison par initiative (ADR 0047) ; pas d'initiative juste après un au revoir (ADR 0048) |
| `goals` | ce qu'elle se propose de faire ensuite : rappels et explorations — autorité, pas prouvés, attentes, carnets (ADR 0020) ; plan de travail, priorité, pilotage par l'opérateur (ADR 0030) ; une rêverie se vit d'un trait, se dissipe sans affect et n'est jamais une nouvelle (ADR 0043, 0047) |
| `projects` | ses projets, des boîtes noires qu'on pilote : objectifs ponctuels ou constants, exécutions (`WORK` dans son mode à elle, `JOB` impersonnel) prouvées par un commit ou un outil qui produit, décisions techniques, atelier et dépôt git (distant compris), outils, plage de travail ; elle en ouvre et en clôt aussi d'elle-même (ADR 0031, 0039) |

Les **plugins** ont la même forme et une confiance restreinte — des signaux, des preuves, des sections citées, jamais la parole forcée ; leur monde vit hors du journal : `email` (plusieurs boîtes IMAP/SMTP et leurs dossiers, sa voix par boîte, des brouillons qu'un opérateur lit et peut retoucher avant de les approuver, ADR 0027 ; en arrière-plan d'une réponse, montré en privé à qui en a les droits, ADR 0037), `rss`, `camera`, `forge` (ses apps, hors processus, ADR 0023 ; une version qui touche des secrets ou une promotion est mise de côté et proposée, ADR 0039), `sensors` (`POST /api/perceptions`). Les pièces jointes sont perçues au bord (port `preprocess`, HTML lu en une passe bornée).

## Autour du noyau

- **Web** : le protocole du frontend (inchangé), comptes et sessions, CSRF, CORS ; une réponse ne part qu'aux connexions de sa personne, un murmure qu'à celles de sa cible, une seule voix entre deux onglets ; une session révoquée ferme ses WebSockets. **Telegram** : **fermé par défaut** — liste blanche, conversation privée des propriétaires, ou ouverture explicite (`open_to_all`) ; salons publics, réponse au salon d'origine (ADR 0038).
- **Atelier** (un dossier par projet, son dépôt git) et **Forge** : bubblewrap sans repli, environnement reconstruit, réseau coupé sauf capacité approuvée (réseau à part par `pasta`, paquet `passt`, sans repli) ; mémoire, CPU, fichiers et sortie bornés, atelier plein = seul le ménage passe ; délais tenus en tuant le processus (ADR 0039). Pousser vers un dépôt distant et en récupérer sont des capacités ; le jeton (Configuration › Canaux › Dépôts git) ne passe que par l'environnement de git.
- **Console** (`/inspecteur/`, opérateurs, ADR 0025, refondue ADR 0029 ; carte : `docs/console-carte.md`) : un back-office que **les facultés déclarent** — vues rangées par destination (`@f.inspect(section=…)`), fiches d'objets auxquelles chacune ajoute ses onglets (personne, adresse, but, mail, app), actions d'opérateur journalisées (`@f.action`, origine extérieure, garde, audit `runtime.operated`), vitaux, badges « à traiter », courbes (`@f.series`, `views.db`). La carte est dans `app/console.py` : des menus qui répondent à des questions, des sous-menus par rubrique pour Configuration et Système ; toute table est paginée (le rendu découpe ce qu'une vue oublie). Les réglages sont dans `app/reglages.py` : des modèles pydantic annotés (`Knob`) découpés en sous-pages d'un seul sujet, un champ ne se montrant que s'il sert (`only`, `only_any`), un choix limité en sélecteur, secrets jamais réaffichés. Les paramètres internes ont une page par faculté et disent d'où vient chaque valeur (défaut ← tempérament ← réglage ← surcharge, `runtime/params.py`). Pour « pourquoi a-t-elle dit ça ? » : `/inspecteur/parole/<seq>` dit la cause en mots, le calcul de l'arbitre, les sections, les souvenirs rappelés, les outils (traces de `runtime/traces.py`, 14 jours) ; « Que ferait-elle ? » en lecture seule. Les libellés vivent dans `app/console.py` ; une faculté qui ajoute une section, une raison, un veto, un processus ou un événement l'y nomme (ADR 0042), et un test d'architecture le vérifie (ADR 0045). Une restauration prend le verrou du dossier ; l'oubli d'un sujet (console comme ligne de commande) emporte ses alias (ADR 0045).
- **Santé** (`/health`, public) : noms et états seulement ; 503 tant qu'elle n'est pas prête.
- **Simulateur** (`sim/`) : le vrai noyau sur temps virtuel, des interlocuteurs, un modèle factice qui répète tout secret qu'on lui montre, des pannes, des mesures. Voie rapide S01–S22. On valide par cibles d'intention (ADR 0007) et on casse exprès ce qu'un test garde pour vérifier qu'il n'est pas vide. **La sonde** (`mika sim sonde`) fait vivre une semaine au vrai modèle configuré : ce que la doublure ne montre pas (ADR 0043, 0048).

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

tranche = *slice* · bail = *lease* · supplanté = *superseded* · divulgation = *disclosure* · posture = *stance* · adresse = *handle* · revendication = *claim* · liaison = *binding* · proximité = *closeness* · salon = *room* · but = *goal* · pas = *step* · projet = *project* · objectif = *objective* · exécution = *run* · atelier = *workshop* · capacité = *capability* · citation = *untrusted section* · pensée = *thought* · souvenir = *episode memory* · croyance = *belief* · murmure = *murmur* · vue = *inspection view*

## Commandes

```bash
.venv/bin/python -m pytest -q && .venv/bin/ruff check src tests && .venv/bin/lint-imports
.venv/bin/python -m mika sim run --report sim-reports      # voie rapide + rapport
.venv/bin/python -m mika --data data/v2 sim sonde --out sonde   # une semaine avec le vrai modèle configuré
.venv/bin/python -m mika --data data/v2 serve --port 8001   # puis l'inspecteur : /inspecteur/
.venv/bin/python -m mika --data data/v2 replay --verify
.venv/bin/python -m mika --data data/v2 backup ARCHIVES --keep 14   # verify ARCHIVE, restore ARCHIVE
.venv/bin/python -m mika --help                            # modèles, comptes, Telegram, sens, forge, oubli
```
