# 0004 — Sans Django

**Contexte.** La v1 reposait sur l'ORM Django depuis une boucle asyncio : 335 ponts `sync_to_async` et des lectures ORM partout.

**Décision.** Noyau sans framework ; Starlette/uvicorn pour HTTP/WebSocket ; `sqlite3` avec un seul écrivain ; Pydantic aux frontières.

**Conséquences.** La propriété des données devient structurelle (chaque projection appartient à sa faculté). Il faut réécrire l'authentification, les sessions et l'inspecteur — plus petits que l'administration v1.
