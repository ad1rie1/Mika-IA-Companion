"""L'API par personne (ADR 0187) : ce que ``frontendv2`` montre à qui est connecté, et seulement à elle.

Chaque route lit la session du navigateur, ou le jeton d'un client natif présenté **sans** ``Origin`` (la règle de
``/auth/whoami``). Une route qui écrit exige en plus, d'un navigateur, le jeton CSRF (cookie ``csrftoken``, en-tête
``X-CSRFToken``) ; d'un client natif, que son jeton soit celui d'un téléphone (client ``mobile``, ADR 0235) : un
téléphone écrit, un écran (``screen``) ne fait que lire. Qui est connecté est une **personne** (``Me``) : son compte,
la clé de sa personne (``identity.person``), et si elle est une de ses propriétaires — les boîtes « à toi » (sans
propriétaire nommé, ADR 0185) sont alors les siennes.

Rien ici ne recopie une règle. Une ressource est à quelqu'un selon ses paramètres journalisés (``owners``) ; ce qu'on y
fait passe par les actions que la console déclare (``runtime.operations.perform``), au nom de la personne (``by``) :
journalisées et dédoublonnées comme dans la console, auditées depuis son espace (``moi.<action>``, ``via=SPACE``). Ce
qui se règle (son compte, ses boîtes, ses comptes Teams, ses services, ses partages) s'écrit dans les réglages du
serveur et s'audite (``moi.<geste>``) ; une création redite avec la même clé d'envoi ne refait rien (``Call.once``).
Une ressource qui n'est pas à elle n'existe pas : le même 404 qu'une ressource inconnue. Le contrat, route par route :
``docs/protocole-moi.md``.

Ce paquet porte le cadre et les modules qui n'ont pas encore rejoint leur domaine (``mail``…) ;
celui d'un domaine qui a sa fiche vit dans son dossier (``app/domains/<nom>/api.py``, ADR 0310). Le cadre qu'ils
emploient tous (``Me``, ``Call``, ``Denied``, la déclaration d'une route) est dans ``api.py`` ; leurs petites aides
dans ``common.py`` ; la règle de partage est dans ``vocab.ownership``, que ``common.py`` lit. ``assembly.py`` réunit
les routes (``MeApi``) : c'est lui qui lit les fiches, jamais ce fichier — un module d'un domaine importe ce paquet,
et ce paquet n'importe donc aucun domaine.
"""

from __future__ import annotations

from mika.app.me.api import OUTBOUND, PROBES, ROUTES_BUSY, Call, Denied, form, missing, spend

__all__ = ["OUTBOUND", "PROBES", "ROUTES_BUSY", "Call", "Denied", "form", "missing", "spend"]
