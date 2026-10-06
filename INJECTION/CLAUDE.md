# INJECTION — consignes pour Claude Code

Ce dossier fabrique un **jumeau numérique**. Les archives d'une personne (messageries, mails, notes,
journaux) sont lues, remises en forme, puis vécues en accéléré par le moteur `../backendv2`. Le plan
est dans `~/.claude/plans/stateful-imagining-turing.md`, le mode d'emploi dans `README.md`.

## Règles absolues

1. **Les données sont privées.** `brut/`, `travail/` et `sortie/` ne sont jamais commités, ni
   copiés dans un test, un doc, un commit, un message ou un prompt versionné. Les tests n'utilisent
   que des échantillons **inventés**. Avant tout commit : `git status`, et rien sous ces trois
   dossiers.
2. **Claude Code s'appelle par sa CLI et son login** (`claude -p`). Jamais `claude setup-token`,
   jamais `CLAUDE_CODE_OAUTH_TOKEN` : le moteur les retire de l'environnement de ses
   sous-processus. Modèle des lectures : **Sonnet**.
3. **Une date ne s'invente pas.** Chaque élément porte un `Temps` (plage, point, précision,
   origine : `src/twin/timing.py`). Une estimation dit d'où elle vient. Un conflit est signalé,
   jamais tranché en silence.
4. **Mémoire de la machine** : les traitements lourds (avance rapide, grosses ingestions, suites
   complètes du moteur) passent par `~/recup-audit-v2-2026-10-01/outils/borne.sh`, une seule
   exécution lourde à la fois. Regarder `free -m` avant.

## Conventions

- Identifiants de code en anglais ; textes, prompts, docs et messages en français.
- Paquet `twin` dans `src/twin/` ; CLI `jumeau` (`src/twin/cli.py`).
- Un lecteur = un module de `src/twin/readers/` qui expose `READER` (`name`, `label`,
  `version`, `detect(path) -> 0..100`, `read(path, ctx) -> Iterator[Item]`), inscrit dans
  `all_readers()`. Il dit ce que la source dit et ce qu'elle laisse deviner (`Author.me`,
  avec sa raison). Il ne décide rien d'autre. Changer la façon de lire un format = augmenter
  `version` (les sources déjà lues seront relues).
- Tests : `.venv/bin/python -m pytest -q`, puis `.venv/bin/ruff check src tests`.
- Ce qui parle au moteur importe le paquet `mika` (`uv pip install -e ../backendv2`). On
  respecte ses contrats : on ne contourne pas ses facultés, on leur sert des réponses.
