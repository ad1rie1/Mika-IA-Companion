# INJECTION — le jumeau numérique

Faire **devenir une personne** au moteur de Mika (`backendv2/`). Ses archives (messageries, mails,
notes, journaux) sont lues par Claude Code. Elles sont ensuite **vécues en accéléré** par le vrai
noyau, du premier message à aujourd'hui. À l'arrivée, sa mémoire, ses proches, ses humeurs, ses
journaux et ses rêves sont ceux d'une vie : on ne les a pas collés, elle les a traversés.

Plan complet : `~/.claude/plans/stateful-imagining-turing.md`. Mesures de l'étape 0 :
`docs/mesures-etape-0.md`.

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
uv pip install --python .venv/bin/python -e ../backendv2
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
| 1 bis | `jumeau dater [--claude]` | Resserre les dates par l'ordre des sources, interpole, signale les conflits. Écrit la revue `travail/dates.yaml`. Avec `--claude`, Claude Code date d'abord par recoupement avec le corpus daté (serveur MCP). | ✅ |
| 2 | `jumeau personnes` | Regroupe les participants en personnes et la détecte dans chaque canal. Revue : `travail/personnes.yaml` (la main l'emporte). | ✅ |
| 3 | `jumeau planifier` | Découpe en séances, calcule la signifiance, répartit en paliers A, B, R, C, D et estime le budget (jetons, appels, heures). Curseurs : `travail/plan.yaml`. | ✅ |
| 4 | `jumeau lire [--essai]` | Annotation par Claude Code (Sonnet) : émotions de chacun de ses messages, souvenirs, croyances, promesses, événements, rêves racontés. Reprenable, quota surveillé. | ✅ |
| 5 | `jumeau synthetiser` | Personnes, chapitres, persona, journaux, rêves, récits, savoir d'archive. | à venir |
| 6 | `jumeau avancer` | L'avance rapide dans le vrai noyau, sur horloge virtuelle. | à venir |
| 7 | — | `mika replay --verify`, puis `mika serve --data INJECTION/sortie/vie` | à venir |

Les paliers :
- **A** : rejouée et lue à fond ;
- **B** : rejouée, lecture légère (émotions et résumé) ;
- **R** : rejouée sans lecture (ses mots, sans balise d'émotion) ;
- **C** : non rejouée, résumée en savoir d'archive ;
- **D** : ignorée.

Ses notes et son journal sont toujours en A.

Utile à tout moment : `jumeau etat` (ce que contient le corpus) et `jumeau formats --detail`
(quel lecteur prendrait quel fichier, sans rien écrire).

## Avec Claude Code

Ouvrir Claude Code dans `INJECTION/` : `CLAUDE.md` lui donne les règles, et les commandes
préparées (`.claude/commands/`) pilotent les étapes :

- `/jumeau-etat` : où en est-on, que faire ensuite ;
- `/jumeau-nouveau-format` : écrire un lecteur pour un format inconnu, à partir d'un échantillon ;
- `/jumeau-personnes` : revoir qui est qui (fusions, « elle », relations). Les propositions sont validées une par une ;
- `/jumeau-relire` : juger un échantillon d'annotations avant de tout lancer, et améliorer la consigne.

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
