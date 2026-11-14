"""Les interfaces du cœur avec ce qui l'entoure, sans le connaître. Trois sortes :

1. ce que le cœur demande au dehors, que les adaptateurs implémentent : le magasin (``store``), les modèles
   (``llm``), le courrier, Teams, la Forge, l'atelier, les images, les vecteurs… ;
2. les portes que le transport web appelle et qu'``app`` implémente : Teams (``TeamsGate``, ``TeamsKeys``), le
   téléphone (``PhoneGate``), les réveils (``WakeDesk``, et la porte ``WakeGate``, un appelable) et les réglages de la
   Forge (``ForgeSettings``), avec leurs issues dans ``gate`` (ADR 0213). Elles vivent ici plutôt que dans
   ``contracts`` parce qu'elles parlent la langue du transport (des lots, des clés, des issues HTTP), pas celle des
   contrats, à la différence du port d'entrée (``contracts/entry.py::MindPort``) ;
3. les bases et entités SQL (``sql``, ``journal``, ``store``), et les aides pures que ces interfaces partagent
   (``drafts``, ``paging``, ``preprocess``, ``errors``, ``llm_budget``), dont le langage des arguments des apps de la
   Forge (``forge_args``, ADR 0105).

Chaque Protocol déclare ce qu'on lui demande, avec ses paramètres ; un membre facultatif le dit dans sa docstring et
se lit par ``getattr`` sous son nom déclaré. ``tests/architecture/test_ports_declared.py`` confronte chaque Protocol à
ses implémentations (ADR 0222).

Les crochets que le runtime cherche sur chaque port
---------------------------------------------------

Le runtime parcourt la table des ports (``KernelDeps.ports``, runtime/bootstrap.py) et prend sur chacun, par
``getattr``, quatre crochets facultatifs. Un port qui n'en a pas l'usage ne les définit pas ; le runtime ne nomme
jamais un port :

- ``async open() -> None`` : se préparer avant la première perception (un index, un cache, des tables). Le
  démarrage l'attend sur chaque port, avant que rien ne vive (``Kernel.boot``) ;
- ``shutdown() -> None`` : arrêter les processus qu'il tient (la Forge, les serveurs d'outils extérieurs). L'arrêt du
  noyau l'appelle, une panne contenue (``Kernel._shutdown_ports``) ;
- ``async forget(subject: str) -> int`` : effacer ce qu'il garde de dérivé sur ce sujet (vecteurs, courrier, Teams,
  partages) et rendre combien. L'oubli d'un sujet l'attend après celui du Mind (``Kernel.forget``), et son nombre
  s'ajoute au compte rendu sous le nom du port ;
- ``failing() -> list[str]`` : les noms de ce qui est en panne chez lui (un serveur d'outils coupé par son
  disjoncteur) ; vide : tout répond. La santé le lit (``_ports``, runtime/health.py) et en fait un contrôle dégradé.

La passerelle LLM n'est pas dans cette table (``KernelDeps.gateway``) : son ``failing(role, now, window_us)``
(``LLMGateway``, ports/llm.py) est un autre membre, qui dit si le fournisseur d'un rôle ne répond plus.
"""
