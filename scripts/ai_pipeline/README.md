# AI Pipeline

Des agents (Claude Code ou Codex) auditent le dépôt, ouvrent des issues, les
corrigent en PR, et tiennent ces PR à jour. Cible : le moteur vivant
(`backendv2/`) et le client web (`frontend/Web/`) ; la v1 archivée (`old/`)
n'est jamais touchée.

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
```

Prérequis : `git`, `gh` authentifié, `jq`, `flock`, `timeout`, et le CLI de
l'agent. Le dépôt GitHub est déduit du remote `origin`.

## Où il travaille

Dans **son propre worktree** (`.claude/worktrees/ai-pipeline`, réglable par
`AI_PIPELINE_WORKTREE`), en tête détachée sur `origin/main`. Il ne fait
jamais de checkout, de pull, de reset ni de clean dans la copie de travail du
dépôt : elle peut rester sale, et on peut y travailler pendant qu'il tourne.
Ce qu'un agent laisse non commité est sauvegardé en patch dans `logs/`
(`leftover-*.patch`) avant chaque remise à zéro.

`frontend/Web/node_modules` est lié depuis la copie principale. Le Python est
celui de `backendv2/.venv`, appelé avec `PYTHONPATH=src` : son paquet `mika`
est installé en mode éditable sur la copie principale, et sans cette variable
les tests de l'agent porteraient sur ta copie au lieu de son travail.

Un seul pipeline à la fois : l'orchestrateur prend un verrou
(`.git/ai-pipeline.lock`) ; une seconde instance s'arrête aussitôt (code 75).

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
