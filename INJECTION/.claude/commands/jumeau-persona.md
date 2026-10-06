---
description: Relire et affiner avec moi sa persona (qui elle est, sa façon de parler, ses goûts) avant l'avance rapide
---

Sa persona décide de comment elle parlera, réagira et se présentera. Relisons-la ensemble. Le serveur MCP « jumeau » est ouvert.

1. Lis `sortie/persona/<nom>.yaml` (l'actuelle) et, s'il y en a, les personas par chapitre (`<nom>-chapitre-N.yaml`).
2. Pour chaque champ (`description`, `tone`, `traits`, `quirks`, `vulnerabilities`, `values`, `interests`, `speech`, `greetings`, `life`, `tastes`, `facts`, `temperament`), **vérifie dans le corpus** (`corpus_chercher`, `seance_lire`, `personne_fiche`) que c'est vrai et que c'est bien elle :
   - **`speech` et `greetings`** : compare avec ses vrais messages. Longueur, ponctuation, émojis, abréviations, tics de langage ;
   - **`facts`** : chaque fait doit être prouvé par les archives (ville, métier, famille, animaux, dates). Un fait sans preuve se retire ;
   - **pas de caricature** : « toujours », « à chaque fois » deviennent des tendances ;
   - **`nature: incarnee`** : rien sur une IA, un avatar ou un serveur ;
   - **le chronotype** vient de ses vraies heures de réveil. Ne le change que si je le demande.
3. Propose tes corrections champ par champ, avec la preuve en une phrase, sans recopier de message privé. **N'édite rien sans mon accord.**
4. Une fois validé, édite le YAML, puis vérifie qu'il est accepté par le moteur :
   `.venv/bin/python -c "import yaml; from mika.contracts.self_ import PersonaDoc; PersonaDoc.model_validate(yaml.safe_load(open('sortie/persona/<nom>.yaml')))"`.
   Pour qu'une correction serve à l'avance rapide, reporte-la aussi dans la table `syntheses` (genre `persona`). Sinon, relance `jumeau synthetiser --etape persona` après avoir supprimé l'entrée concernée.

$ARGUMENTS
