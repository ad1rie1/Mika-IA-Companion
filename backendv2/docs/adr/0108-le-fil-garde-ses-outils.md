# 0108 — Le fil garde la trace de ses outils

**Contexte.** Le 2026-10-13, première conversation de la propriétaire avec Mika sur le portable (Claude Code,
Haiku). Elle demande la température de demain à Paris. Mika appelle `mcp_web_search`, lit les extraits et répond
juste, en disant que deux sources ne sont pas d'accord. Au message suivant (« c'est la première fois qu'on parle
:) »), Mika répond : « Je dois te corriger : mon message précédent était inventé. Je n'avais rien regardé… ». Elle
refait la recherche, lit Météo-France, et ne répond pas à ce qu'on vient de lui dire.

Les traces de l'épisode montrent la cause. L'historique montré au modèle ne garde que le **texte** de ses messages :
ni l'appel d'outil, ni ce qu'il a rendu. Au second tour, le modèle relit « j'ai regardé les prévisions » sans aucune
trace de recherche. Or sa persona lui dit que ce qui se passe hors de sa chambre, elle ne le sait que par ses outils.
Il en conclut qu'il a inventé, et s'en accuse.

Pire, il pose `[MENSONGE: J'ai regardé les prévisions…]`, une phrase de son message **précédent**. `expression.lied`
cherche le passage faux dans la réponse **en cours** et retombe sur toute la réponse quand rien ne correspond. Le
mensonge est donc retenu sur la réponse qui donnait les vraies prévisions : un souvenir `lie` envers la propriétaire,
et la gêne qui va avec (`attention`, origine `LIE`).

**Décision.**

1. *Le fil dit de quels outils vient un de ses messages.* `rt.Utterance.tools` (le nom de chaque outil appelé dans
   l'épisode et s'il a réussi) existait déjà. La table du fil le garde dans une colonne `tools`, en JSON
   (`[[nom, réussi], …]`). La projection passe en version 6 et se reconstruit depuis le journal. `thread_turns`
   l'ajoute au repère de son message : « [pour écrire ce message, tu t'es servie de mcp_web_search : ce que tu y dis
   en vient] », puis « tu as essayé …, sans succès » pour ceux qui ont échoué. Le repère passe avant son tour, comme
   les repères de temps : son propre texte garde sa forme, sinon le modèle imiterait la note. Le repère ne dépend
   que de la ligne, donc le préfixe en cache ne bouge pas.
2. *Les noms seulement.* Ce qu'elle a demandé à l'outil (une requête qui nomme quelqu'un) et ce qu'il a rendu ne sont
   pas gardés. Ces textes n'ont pas de sujets déclarés, et l'oubli ne les atteindrait pas (ADR 0024). Savoir qu'elle
   a cherché suffit à ne pas se croire prise à inventer. Si on lui redemande sa source, elle peut chercher de nouveau.
3. *Une marque de mensonge désigne une phrase de cette réponse, ou rien.* `lied` ne désigne la phrase la plus proche
   de la marque que si elle porte au moins la moitié de ses mots. Une marque sans phrase (« [mensonge] ») désigne
   toujours toute la réponse. Une marque qui cite une phrase absente de la réponse ne pose aucune annotation, donc
   aucun souvenir `lie` et aucune gêne.

**Conséquences.**
- Un mensonge marqué en le paraphrasant trop librement n'est plus retenu. La consigne demande déjà la phrase « telle
  que tu l'as dite ».
- Les phrases sont dans `persona/voix.yaml` (`transcript.thread.used_tools`, `transcript.thread.tools_failed`).
- Tests : `test_thread_time.py` (le repère, de bout en bout avec `memory_search`), `test_lies.py` (le cas du
  2026-10-13 et ses contre-exemples).
