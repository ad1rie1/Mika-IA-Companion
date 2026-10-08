# 0072 — Claude Code : les outils d'un même message en un seul tour

**Contexte.** L'ADR 0026 annonçait des « appels d'outils partis en parallèle, regroupés en un tour ». C'était vrai
avec la fausse CLI des tests, qui lançait tous les appels d'un lot ensemble. C'est faux avec la vraie (2.1.282,
mesuré le 2026-10-08). La CLI ne lance en parallèle qu'un outil MCP marqué `readOnlyHint`
(`isConcurrencySafe() { return annotations?.readOnlyHint ?? false }`). Sans cette marque, elle attend la réponse
d'un outil avant de lancer le suivant, et le relais ne la donnait jamais. Deux appels écrits ensemble arrivaient
donc au relais l'un après l'autre : le backend rendait un lot d'un seul appel, le runtime l'exécutait, et le second
n'arrivait qu'au tour suivant. N appels coûtaient N tours de la boucle du runtime au lieu d'un : chacun prenait une
place de `max_tool_turns` (6 pour certaines politiques) et payait la fenêtre de regroupement. Mesure de bout en bout
(vraie CLI, faux API, vrai relais, vraie boucle) : deux appels donnaient 3 appels de la passerelle au lieu de 2.

Second constat, mesuré avec la marque : la CLI lance un outil **dès que son bloc est écrit**, pendant que le modèle
écrit encore les suivants. Un modèle qui écrit lentement (un second bloc 0,6 s après le premier) aurait coupé le
lot en deux avec la fenêtre fixe de 150 ms.

**Décision.**

1. *Tous les outils du relais sont « lecture seule » pour la CLI* (`claude_code._tool`). La marque ne règle que
   l'envoi : c'est le runtime qui exécute le lot, un appel après l'autre, avec toutes ses gardes. Le sens de la
   marque côté MCP (« n'écrit rien ») ne s'applique pas ici : le relais ne sert que la CLI de Mika.
2. *Un lot est un message du modèle.* Avec `--include-partial-messages`, la CLI encadre chaque message de
   `stream_event` `message_start` … `message_stop`, et chaque bloc `tool_use` sort sur sa propre ligne
   `assistant`. Le lot se ferme quand le message est fini et que les appels arrivés au relais et les blocs
   annoncés se répondent un à un. Un bloc que la CLI a répondu elle-même (sa ligne `tool_result`, sans passer par
   le relais) n'est plus attendu. Un appel arrivé sans bloc lu veut dire que stdout est en retard sur le relais (ce
   sont deux canaux) : on l'attend aussi. Ce qui manque encore est attendu `LATE_CALL_S` (2 s), puis part au tour
   suivant, comme avant. Sans `stream_event` (une CLI qui ne les diffuserait plus), on revient à la fenêtre de
   150 ms.
3. *Le lot part dans l'ordre écrit.* Les appels arrivent au relais dans l'ordre de leurs requêtes HTTP. Chacun est
   rattaché à son bloc (même outil et mêmes arguments, à défaut le même outil) et le lot est trié comme le modèle
   l'a écrit, comme sur l'API.

**Conséquences.** Le runtime commence le lot à la fin du message du modèle, plus au premier bloc : c'est ce que
fait le fournisseur API. Sur la vraie CLI, deux appels donnent maintenant un tour d'outils, puis la réponse,
exécutés dans l'ordre écrit. La fausse CLI des tests (`tests/fixtures/fake_claude.py`) reproduit ce qu'on a mesuré :
en série sans la marque, appel lancé dès son bloc, `stream_event`, réponse de chaque outil dès qu'elle est là.
Sans ça, le défaut était invisible dans les tests. Contrats : `tests/contract/test_claude_code.py` (lot unique
malgré un modèle lent, ordre écrit, appel refusé par la CLI, repli sans flux). L'ancien fournisseur échoue à
chacun, et chaque morceau du correctif est tenu par au moins un test (vérifié par mutation).
