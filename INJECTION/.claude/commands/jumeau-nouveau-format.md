---
description: Écrire un lecteur pour un format d'archive que le jumeau ne reconnaît pas encore
---

Un ou plusieurs fichiers de `brut/` n'ont pas de lecteur (voir `travail/inconnus.txt`, ou le
chemin donné ci-dessous). Écris le lecteur qui manque.

1. **Observe sans divulguer.** Lis le début de quelques fichiers concernés pour comprendre le
   format : structure, encodage, dates et fuseau, auteurs, fils, pièces jointes, indice de qui
   est « elle ». Ne recopie **aucun** contenu réel dans le code, les tests, les commits ni ta
   réponse : décris la structure avec des valeurs inventées.
2. **Écris `src/twin/readers/<format>.py`** sur le modèle des lecteurs existants
   (`whatsapp.py` pour un format ligne à ligne, `sms.py` pour un XML lu en flux, `meta.py` pour
   du JSON). Le lecteur expose `READER` avec :
   - `name`, `label`, `version = 1` ;
   - `detect(path) -> 0..100` : sûr de lui seulement quand le contenu le prouve ;
   - `read(path, ctx)`, qui rend des `Author` (avec `me` et `me_reason` quand la source le
     laisse deviner), des `Conversation`, des `Message` (ou des `Document` pour un texte qui
     n'est pas une conversation).
   
   Les dates passent par `twin.timing.Temps` : `exact` quand la source horodate. Sinon, la
   précision réelle (`day`, `month`, `span`…) et la bonne `Origin`. **Ne jamais inventer
   d'heure.** Inscris le lecteur dans `all_readers()` (`src/twin/readers/__init__.py`).
3. **Teste-le** dans `tests/unit/test_readers.py` sur un échantillon **inventé** qui reprend les
   pièges vus : encodage, multi-lignes, dates ambiguës, messages système. Puis lance
   `.venv/bin/python -m pytest -q` et `.venv/bin/ruff check src tests`.
4. Vérifie avec `.venv/bin/jumeau formats --detail` que les fichiers sont reconnus. Propose
   ensuite `.venv/bin/jumeau ingerer` et `.venv/bin/jumeau dater`, sans les lancer.
5. Ajoute la ligne du format dans le tableau « Déposer les archives » de `README.md`.

Fichiers ou format visés : $ARGUMENTS
