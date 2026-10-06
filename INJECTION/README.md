# INJECTION — le jumeau numérique

Faire **devenir une personne** au moteur de Mika (`backendv2/`). Ses archives (messageries, mails,
notes, journaux) sont lues par Claude Code. Elles sont ensuite **vécues en accéléré** par le vrai
noyau, du premier message à aujourd'hui. À l'arrivée, sa mémoire, ses proches, ses humeurs, ses
journaux et ses rêves sont ceux d'une vie : on ne les a pas collés, elle les a traversés.

Plan complet : `~/.claude/plans/stateful-imagining-turing.md`. Les mesures de l'étape 0, dans
`docs/mesures-etape-0.md`, donnent les plafonds et les pièges. On rejoue environ 100 000 messages par heure de calcul,
et environ 1 million au plus sous la borne de 3 Go. Le reste passe en savoir d'archive.

Côté moteur, la couture est décrite par `backendv2/docs/adr/0070-une-vie-importee.md` :
- une persona peut être `nature: incarnee`, et son nom vient d'elle partout ;
- `mika.app.genesis` permet d'importer des souvenirs à la date du rejeu ;
- le préréglage « avance rapide » coupe sa vie spontanée.

## Ce qui reste privé

`brut/`, `travail/` et `sortie/` ne sont **jamais commités** (voir `.gitignore`). Ils contiennent
la vie d'une personne et celle de ses correspondants. Les tests n'utilisent que des échantillons
inventés.

Les textes sont lus par Claude Code (la CLI `claude -p`, avec son propre login) : ils passent donc
par Anthropic. Avant l'injection, `jumeau oublier <personne>` retire une personne du corpus. Après,
chaque texte injecté déclare qui il concerne, et `mika forget` l'efface.

## Installation

```bash
cd INJECTION
uv venv .venv --python 3.14
uv pip install --python .venv/bin/python -e . pytest pytest-asyncio ruff
# pour les étapes qui parlent au moteur (lecture, avance rapide) :
uv pip install --python .venv/bin/python -e ../backendv2 numpy
```

La commande est `.venv/bin/jumeau` (ou `.venv/bin/python -m twin`).

## Déposer les archives dans `brut/`

Un sous-dossier par source est conseillé (`brut/whatsapp/`, `brut/meta/`, `brut/msn/`…), mais
chaque fichier est reconnu par son contenu.

| Source | Comment l'exporter | Lecteur |
|---|---|---|
| WhatsApp | Discussion → ⋮ → Plus → *Exporter la discussion* → *Sans médias*. Un `.txt` par discussion. Le nom du fichier compte : il nomme l'autre personne. | `whatsapp` |
| Messenger / Instagram | *Espace comptes* → *Vos informations* → *Télécharger* → format **JSON**. Déposer le dossier décompressé tel quel : le profil sert à la reconnaître. | `meta` |
| MSN / Windows Live | Les dossiers `…\Mes fichiers reçus\<compte>\History\*.xml`, ou les journaux Messenger Plus! (`.txt`, `.html`). | `msn` |
| SMS / MMS | L'application *SMS Backup & Restore* (Android) → sauvegarde XML. | `sms` |
| Mails | mbox (Thunderbird, Google Takeout), `.eml`, ou un dossier Maildir. Un dossier « Envoyés » aide à la reconnaître. | `mail` |
| Notes, journaux | `.txt`, `.md`, `.docx`, `.rtf`, Google Keep (Takeout JSON), Evernote (`.enex`). Un journal tenu dans un seul fichier est découpé en entrées datées. | `notes` |
| Signal, autre | Pas encore de lecteur : déposer un échantillon, puis lancer `/jumeau-nouveau-format` dans Claude Code. | — |

Les dates ne sont pas toutes connues, et c'est normal. Chaque élément porte une **plage**, un
**point** estimé, une **précision** (exacte, jour, mois, saison, année, plage, inconnue) et
l'**origine** de l'estimation. Les dossiers aident : `notes/2009/12 mars.txt` est daté du
12 mars 2009.

## Les étapes

| # | Commande | Ce qu'elle fait | État |
|---|---|---|---|
| 1 | `jumeau ingerer` | Lit `brut/` dans `travail/corpus.db`. On peut relancer sans risque : un fichier inchangé est sauté, des exports qui se chevauchent ne font pas de doublons. | ✅ |
| 1 bis | `jumeau dater [--claude]` | Resserre les dates par l'ordre des sources, interpole, signale les conflits. Écrit la revue `travail/dates.yaml`. Une date décidée (à la main, ou par Claude Code) est gardée : elle revient même après la relecture de sa source. Avec `--claude`, Claude Code date d'abord, par recoupement avec le corpus daté (serveur MCP), ce que l'ordre n'a pas su dater. Il travaille sur les séances : le lancer **après** `jumeau planifier`, puis relancer `jumeau planifier --garder-seances`. | ✅ |
| 2 | `jumeau personnes` | Regroupe les participants en personnes et la détecte dans chaque canal. Revue : `travail/personnes.yaml` (la main l'emporte ; une note prise par Claude Code via le MCP n'est pas écrasée par une revue restée en l'état). Un pseudo MSN commun ou deux numéros réunis par un même nom ne sont que **proposés**. | ✅ |
| 3 | `jumeau planifier` | Découpe en séances, calcule la signifiance, répartit en paliers A, B, R, C, D et estime le budget (jetons, appels, heures). Curseurs : `travail/plan.yaml`. | ✅ |
| 4 | `jumeau lire [--essai]` | Annotation par Claude Code (Sonnet) : émotions de chacun de ses messages, souvenirs, croyances, promesses, événements, rêves racontés. Reprenable, quota surveillé : un refus pour quota attend la réinitialisation sans compter comme un essai ; un échec repart de plus en plus tard ; un lot qui échoue sans cesse est coupé en deux. `--reprendre-echecs` remet en file ce qui a échoué (aussi pour `dater --claude` et `synthetiser`). | ✅ |
| 5 | `jumeau synthetiser [--etape X]` | Claude Code (Sonnet) écrit, dans l'ordre : ses mois (et son récit de soi), les chapitres de sa vie, sa persona (`sortie/persona/`, une par chapitre et l'actuelle, nature « incarnée », chronotype calculé sur ses vrais réveils), les profils de ses proches par trimestre, le journal de ses jours forts et deux rêves possibles par nuit. Ses vrais journaux et ses vrais rêves priment. | ✅ |
| 6 | `jumeau avancer [--preparer] [--jusqu-a D]` | L'avance rapide dans le vrai noyau, sur horloge virtuelle. Le moteur est gelé et la mémoire bornée ; on peut reprendre. Les messages auxquels elle a répondu sont retenus puis libérés à l'heure de sa réponse. Le rejoueur sert à ses facultés ce que Claude Code a lu. Rapport : `sortie/rapport/`. | ✅ |
| 7 | — | `mika replay --verify`, puis `mika serve --data INJECTION/sortie/vie --port 8001` | à faire sur les vraies données |
| — | `jumeau oublier <personne>` | Retire quelqu'un du corpus avant l'injection : ses messages, leurs tête-à-tête, ce que les annotations et les synthèses disent d'elle ; ses séances repartent en lecture sans elle. L'oubli est gardé : une source relue ne la fait pas revenir. Ses textes à elle qui la nomment sont listés, pas modifiés. Après l'injection, c'est `mika forget`. | ✅ |

Les paliers :
- **A** : rejouée et lue à fond ;
- **B** : rejouée, lecture légère (émotions et résumé) ;
- **R** : rejouée sans lecture (ses mots, sans balise d'émotion) ;
- **C** : non rejouée, résumée en savoir d'archive ;
- **D** : ignorée.

Ses notes et son journal sont toujours en A.

## Sa voix

Tout ce que le moteur lui fait lire ou dire sans modèle (consignes, sections du prompt, mots des humeurs, ses
bonjours de secours…) est dans **un seul fichier** : `backendv2/persona/voix.yaml` (documenté en tête). Pour lui
donner une voix à elle sans toucher au moteur : copier ce fichier en `sortie/voix.yaml` et le retoucher. `jumeau
avancer` le passe au moteur (`MIKA_VOIX`), et rappelle à l'arrivée de servir sa vie avec la même voix. Le moteur gelé
copie aussi `backendv2/persona/` : changer la voix du moteur fait un nouveau moteur gelé.

Utile à tout moment : `jumeau etat` (ce que contient le corpus) et `jumeau formats --detail`
(quel lecteur prendrait quel fichier, sans rien écrire).

## Avec Claude Code

Ouvrir Claude Code dans `INJECTION/` : `CLAUDE.md` lui donne les règles, et les commandes
préparées (`.claude/commands/`) pilotent les étapes :

- `/jumeau-etat` : où en est-on, que faire ensuite ;
- `/jumeau-nouveau-format` : écrire un lecteur pour un format inconnu, à partir d'un échantillon ;
- `/jumeau-personnes` : revoir qui est qui (fusions, « elle », relations). Les propositions sont validées une par une ;
- `/jumeau-relire` : juger un échantillon d'annotations avant de tout lancer, et améliorer la consigne ;
- `/jumeau-persona` : relire sa persona champ par champ, preuves à l'appui ;
- `/jumeau-avancer` : préparer, essayer sur un mois, lancer, puis vérifier l'avance rapide.

Le serveur MCP « jumeau » (`.mcp.json`) donne à Claude Code des outils sur le corpus : recherche plein texte, lecture d'une séance, fiche d'une personne, annotation, dates à revoir. En session, il peut aussi consigner une date retrouvée ou la relation d'une personne. La datation par lots (`jumeau dater --claude`) l'ouvre en lecture seule.

Ordre conseillé avant une grosse dépense :
1. `jumeau lire --essai` ;
2. `jumeau lire --max-lots 3` ;
3. `/jumeau-relire` ;
4. ajuster la consigne ;
5. lancer `jumeau lire` pour de bon.

## Développer

```bash
.venv/bin/python -m pytest -q && .venv/bin/ruff check src tests
```

`tests/integration/` fait vivre de petites archives au vrai noyau :
- `test_fast_forward.py` vérifie retenir puis libérer, la reprise après arrêt et la mémoire assemblée ;
- `test_pipeline_cli.py` fait toute la chaîne de `brut/` à une vie vécue, avec un faux `claude`, puis
  `mika replay --verify`.

La dépendance `numpy` vient du moteur. Une avance réelle passe toujours par `jumeau avancer`, qui gèle le moteur et
borne la mémoire.
