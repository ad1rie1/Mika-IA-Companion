# AI Pipeline

Des agents (Claude Code ou Codex) auditent le dépôt, ouvrent des issues, les
corrigent en PR, et tiennent ces PR à jour. Cible : le moteur vivant
(`backendv2/`) et ses trois clients (`frontend/Web/`, `frontend/Android/`,
`frontend/Unity/Mika/`).

Un **module** est un dossier qu'un agent traite en un passage
(`AVAILABLE_MODULES` dans `config.sh`). Il n'est retenu que s'il existe sur
`origin/main` : c'est cet état que l'agent lit, un dossier pas encore poussé
serait vide pour lui. Son label GitHub est `module:<chemin>`, abrégé pour
Android (`module:android/…`) et Unity (`module:unity/…`).

## Lancer

```bash
scripts/ai_pipeline/run.sh                    # boucle : rebase → worker → audits, puis dort 30 min
scripts/ai_pipeline/run.sh --max-tasks 3      # s'arrête après 3 tâches
scripts/ai_pipeline/run.sh --dry-run          # montre ce qui serait lancé, sans appel d'agent

scripts/ai_pipeline/orchestrator.sh --audit --profile bugs --modules backendv2/src/mika/kernel
scripts/ai_pipeline/orchestrator.sh --worker  # issues Propose_AI_PR → PR
scripts/ai_pipeline/orchestrator.sh --issue 42
scripts/ai_pipeline/orchestrator.sh --rebase  # PR en conflit → rebase ; PR obsolètes → fermées
scripts/ai_pipeline/triggers/manual.sh        # menu interactif

scripts/ai_pipeline/audit-groupe.sh --liste                  # les groupes de modules et les axes de cohérence
scripts/ai_pipeline/audit-groupe.sh bugs noyau relations     # un passage par module, puis un bilan
scripts/ai_pipeline/audit-groupe.sh amelioration vie-interieure --apercu
scripts/ai_pipeline/audit-groupe.sh bugs tout
scripts/ai_pipeline/audit-groupe.sh bugs canaux web --un-passage   # un passage par groupe

scripts/ai_pipeline/audit-groupe.sh coherence tout                 # cohérence : un passage par axe, sur tout le dépôt
scripts/ai_pipeline/audit-groupe.sh coherence protocoles reglages --apercu
scripts/ai_pipeline/orchestrator.sh --axe documentation
```

Par défaut, `audit-groupe.sh` fait **un passage d'agent par module** : c'est le
plus profond. Avec `--un-passage`, il en fait **un par groupe**, sur tous ses
modules à la fois : plus rapide, attentif à ce qui circule entre eux, mais
moins fouillé sur chacun. Une issue issue d'un passage par groupe retrouve son
module d'après ses fichiers (label `module:…`), sinon elle ne porte que le
label du groupe. En direct : `orchestrator.sh --audit --profile bugs --group noyau`.

Les modules sont rangés en **groupes** (`MODULE_GROUPS` dans `config.sh`) :
`noyau`, `exploitation`, `relations`, `vie-interieure`, `parole`, `projets`,
`monde`, `canaux`, `web`, `android`, `unity`. Chaque issue et chaque PR porte
le label `groupe:<nom>`, pour filtrer sur GitHub.

Prérequis : `git`, `gh` authentifié, `jq`, `flock`, `timeout`, et le CLI de
l'agent. Le dépôt GitHub est déduit du remote `origin`.

## Où il travaille

Dans **son propre worktree** (`.claude/worktrees/ai-pipeline`, réglable par
`AI_PIPELINE_WORKTREE`), en tête détachée sur `origin/main`. Il ne fait
jamais de checkout, de pull, de reset ni de clean dans la copie de travail du
dépôt : elle peut rester sale, et on peut y travailler pendant qu'il tourne.
Ce qu'un agent laisse non commité est sauvegardé en patch dans `logs/`
(`leftover-*.patch`) avant chaque remise à zéro.

`frontend/Web/node_modules` et `frontend/Android/local.properties` sont liés
depuis la copie principale. Android se vérifie par `:app:compileDebugKotlin`,
sous le garde-fou mémoire `borne.sh` s'il existe. Unity ne peut pas être
compilé hors de l'éditeur : l'agent ne touche qu'au C# existant et le dit
dans la PR. Le Python est
celui de `backendv2/.venv`, appelé avec `PYTHONPATH=src` : son paquet `mika`
est installé en mode éditable sur la copie principale, et sans cette variable
les tests de l'agent porteraient sur ta copie au lieu de son travail.

Un seul pipeline à la fois : l'orchestrateur prend un verrou
(`.git/ai-pipeline.lock`) ; une seconde instance s'arrête aussitôt (code 75).

## Profils d'audit

| Profil | Cherche | Issues |
|---|---|---|
| `bugs`, `quality`, `security` | des défauts | taguées `Propose_AI_PR` : le worker les corrige |
| `features` | de nouvelles fonctionnalités | `idee`, à arbitrer |
| `amelioration` | comment rendre Mika plus humaine ou plus fonctionnelle, à partir de l'existant | `idee`, à arbitrer |
| `coherence` | deux pièces du dépôt qui ne disent plus la même chose (voir ci-dessous) | `Propose_AI_PR`, sauf `a-trancher` |

Pour une issue `idee` que tu veux faire réaliser, ajoute `Propose_AI_PR` à la
main. Les profils `bugs`, `quality` et `security` ne retiennent que les
constats de gravité `medium` ou plus (`AUDIT_SEVERITE_MIN`, ou `SEVERITE=high`
pour un passage). Chaque audit se termine par les pistes que l'agent a
examinées puis écartées, affichées dans le terminal : un audit vide se juge
sur elles.

## Cohérence

Le profil `coherence` ne cherche pas un défaut dans une pièce, mais un écart
**entre** deux pièces : un champ que le serveur envoie et qu'Android lit sous un
autre nom, une limite de pièce jointe qui diffère entre le web et le serveur,
un README qui décrit une commande retirée, une émotion connue du noyau et pas
d'Unity, un reste de Telegram. Un audit par module ne voit pas ces écarts :
celui-ci s'audite donc par **axe**, chaque passage lisant tout le dépôt vivant
(moteur, trois clients, extension, `INJECTION/` hors données privées, docs,
scripts) :

| Axe | Regarde |
|---|---|
| `protocoles` | ce que le serveur envoie et ce que chaque client lit (chat, monde 3D, Teams) |
| `vocabulaire` | les listes fermées recopiées : émotions, lieux, phases, statuts, libellés, phrases |
| `documentation` | README, ARCHITECTURE, ADR, `CLAUDE.md` et docs face au code |
| `reglages` | limites, délais et seuils recopiés d'une pièce à l'autre |
| `restes` | code mort entre pièces, références à ce qui n'existe plus, fichiers suivis par erreur |
| `conventions` | une pièce qui fait autrement que ses sœurs, au point que ça casse ou trompe |

Les axes sont déclarés dans `profiles/audit/coherence.md` lui-même (marqueurs
`<!-- AXE:nom | description -->`) : un axe s'ajoute en y écrivant une section,
et seul le texte de l'axe demandé est envoyé à l'agent. Lancé sur un module
(`--profile coherence --modules …`), le profil regarde ce module face à ce
avec quoi il échange, selon tous les axes.

Chaque constat cite au moins deux pièces et dit laquelle fait foi. Quand rien
dans le dépôt ne permet de trancher, l'agent écrit `arbitrage: oui` : l'issue
est créée avec `a-trancher` et **sans** `Propose_AI_PR`. Décide du bon côté
dans un commentaire, puis remplace `a-trancher` par `Propose_AI_PR`.

Une issue de cohérence porte `axe:<nom>` et le label de **chaque** module
qu'elle touche (serveur et client), pour que l'audit de chacun la retrouve.
L'agent voit toutes les issues d'audit du dépôt, pas seulement celles de son
axe. `run.sh` ne lance pas ce profil dans sa boucle : un passage lit tout le
dépôt, il se déclenche à la main.

## Doublons

Deux protections avant qu'une issue d'audit soit créée :

1. **L'agent voit ce qui est déjà connu** sur son module : toutes les issues
   d'audit, tous profils confondus, ouvertes et fermées depuis
   `DEDUP_CLOSED_DAYS` jours (90).
2. **Un filet compare chaque constat** au titre et aux fichiers de toutes les
   issues du dépôt (`lib/dedup.py`) :

| Proche de… | Ressemblance des titres | Ce qui se passe |
|---|---|---|
| une issue ouverte | ≥ 0,8 (`DEDUP_SKIP`) | pas créée, « doublon de #N » au journal |
| une issue ouverte, avec un fichier en commun | ≥ 0,6 (`DEDUP_FLAG`) | créée avec `doublon-possible`, **sans** `Propose_AI_PR` : à trancher |
| une issue fermée | ≥ 0,8, ou ≥ 0,6 avec un fichier en commun | créée normalement, avec « déjà signalé dans #N : régression ? » |

Deux constats jumeaux d'un même audit ne passent pas tous les deux. Les seuils
ont été mesurés sur 212 issues d'audit passées. Avec `--no-create`, l'aperçu
affiche le verdict de chaque constat.

## Codes de sortie de l'orchestrateur

| Code | Sens |
|------|------|
| 0 | travail livré (PR, issues, PR rebasées) |
| 1 | échec |
| 10 | rien à faire (aucun module disponible, aucune issue en attente) |
| 11 | passage fait, sans résultat (aucune modification, aucun constat) |
| 75 | une autre instance tient le verrou |

`run.sh` et `triggers/cron_weekly.sh` décident de la suite sur ce code, jamais
sur le texte affiché.

## Fichiers

- `config.sh` — modules ciblés, fichiers protégés (`FORBIDDEN_PATTERNS`, aussi
  recopiés dans les prompts), agent, effort, délais.
- `lib/common.sh` — journal, appel de l'agent (sans serveur MCP, sans
  historique de session), sonde de disponibilité, contexte projet et politique
  de tests injectés dans chaque prompt.
- `lib/git.sh` — worktree, branches de tâche, contrôles de commits et de
  fichiers protégés.
- `lib/github.sh` — PR, issues, labels, déduplication par module.
- `modes/` — audit, fix, worker, rebase.
- `profiles/` — les consignes par profil (`audit/`, `small_fix/`,
  `large_issue/refactor.md` pour le worker et les issues sans profil).
- `triggers/` — cron, menu manuel, webhook (`AI_PIPELINE_WEBHOOK_SECRET`
  exigé hors loopback ; `/webhook/trigger` le demande en en-tête
  `X-Pipeline-Secret`).
