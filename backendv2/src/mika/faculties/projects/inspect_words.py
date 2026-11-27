"""Les mots et les tons des projets à la console (ADR 0031) : chaque état dit en mots, et sa couleur.

Le mode d'un projet, son statut ; la sorte d'un objectif et son état ; le verdict d'une exécution ; le statut d'une
décision technique ; le ton d'une priorité ; qui a écrit ; où en est une pull request et ses vérifications ; où en est
son plan ; qui valide le plan d'un ticket, et la publication de ses tickets en issues ; pourquoi ce qu'une personne a
écrit sur une pull request n'est pas parti (``WRITE_WORDS``, sur les raisons de ``merge.py``). Les vues (``inspect.py``,
``inspect_git.py``), le fil d'un projet (``feed.py``), l'API par personne et les pages dessinées de la console les
lisent ici, sans tirer les vues.

Rien d'autre : ce module n'inscrit aucune contribution et n'importe aucun autre module ``inspect_*``. Les mots qui
sont une règle de plus (``window_words``, ``pull_words``) restent dans ``inspect.py``, comme ``PRIORITY_FR``, qui
reprend les choix du formulaire (``actions.PRIORITY_CHOICES``).
"""

from __future__ import annotations

from mika.contracts import projects as c
from mika.faculties.projects import merge
from mika.ports.workshop import (
    CHECKS_FAILED,
    CHECKS_PASSED,
    CHECKS_PENDING,
    PULL_CLOSED,
    PULL_MERGED,
    PULL_OPEN,
)

MODE_FR = {c.PERSONA: "elle-même", c.PLAIN: "impersonnel"}
MODE_TONE = {c.PERSONA: "info", c.PLAIN: "muted"}
STATUS_FR = {c.ACTIVE: "actif", c.PAUSED: "en pause", c.ARCHIVED: "archivé"}
STATUS_TONE = {c.ACTIVE: "ok", c.PAUSED: "warn", c.ARCHIVED: "muted"}
KIND_FR = {c.ONCE: "ponctuel", c.CONSTANT: "constant"}
KIND_TONE = {c.ONCE: "", c.CONSTANT: "info"}
OBJ_FR = {c.OPEN: "ouvert", c.DONE: "fait", c.BLOCKED: "bloqué", c.DROPPED: "retiré"}
OBJ_TONE = {c.OPEN: "", c.DONE: "ok", c.BLOCKED: "danger", c.DROPPED: "muted"}
VERDICT_FR = {c.CONTINUE: "continuer", c.DONE: "fait", c.BLOCKED: "bloqué", c.WAIT: "attendre"}
VERDICT_TONE = {c.CONTINUE: "info", c.DONE: "ok", c.BLOCKED: "danger", c.WAIT: "muted"}
DECISION_FR = {c.IN_FORCE: "en vigueur", c.SUPERSEDED: "remplacée", c.WITHDRAWN: "retirée"}
DECISION_TONE = {c.IN_FORCE: "ok", c.SUPERSEDED: "muted", c.WITHDRAWN: "muted"}
PRIORITY_TONE = {c.LOW: "muted", c.NORMAL: "", c.HIGH: "warn", c.URGENT: "danger"}
AUTHOR_FR = {"operator": "toi", "owner": "qui le lui a confié", "self": "elle"}

PULL_FR = {PULL_OPEN: "ouverte, en attente de fusion", PULL_MERGED: "fusionnée", PULL_CLOSED: "fermée sans fusion"}
#: les vérifications du commit d'une pull request ouverte (ADR 0275) ; un dépôt sans CI n'en dit rien
CHECKS_FR = {CHECKS_PENDING: "ses vérifications tournent encore", CHECKS_PASSED: "ses vérifications sont passées",
             CHECKS_FAILED: "ses vérifications ont échoué (l'objectif est rouvert)"}

PLAN_FR = {c.TO_FRAME: ("à cadrer", "info"), c.PROPOSED: ("plan proposé, il attend une réponse", "warn"),
           c.PLANNED: ("planifié", "ok")}

REVIEW_FR = {c.REVIEW_ALWAYS: "toujours par toi", c.REVIEW_LARGE: "par toi, sauf pour un petit ticket"}
ISSUES_FR = {c.ISSUES_NEVER: "jamais", c.ISSUES_ASK: "sur ton accord, ticket par ticket",
             c.ISSUES_ALWAYS: "toujours (la synchronisation)"}
#: pourquoi ce qu'une personne a écrit sur une pull request n'est pas parti (``PullWriteAnswered.why``)
WRITE_WORDS = {
    merge.STALE: "la pull request avait changé entre-temps",
    merge.NO_HOST: "aucun hôte ne sait l'écrire sur ce dépôt",
    merge.FORGOTTEN: "son texte ne se lit plus",
    merge.REFUSED: "l'hôte a refusé, ou n'a pas répondu",
    merge.CUT: "la demande a été interrompue — relis la pull request chez l'hôte",
}
