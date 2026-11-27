"""Comment part un message Teams (ADR 0132, 0134, 0186) : la ligne de ses canaux qui vaut pour une conversation — ce
qui la désigne : son identifiant, son nom, qui écrit —, depuis un compte : le tableau du compte (``teams:<clé>``),
sinon celui de Teams, sinon le minimum vital. Le moteur des canaux et ce que le courrier partage avec lui — qui une
ligne d'un de tes comptes désigne (``designated``) — sont dans ``vocab/canals.py``.
"""

from __future__ import annotations

from mika.vocab.access import TEAMS, Verdict, decide
from mika.vocab.canals import CanalRule, Canals, designated


def teams_verdict(canals: Canals, account: str, *about: str) -> Verdict[CanalRule]:
    """La ligne d'un message Teams et sa place : ``about`` — l'identifiant de la conversation, son nom, qui écrit ;
    le tableau du compte (``teams:<clé>``), sinon celui de Teams, sinon le minimum vital."""
    key = f"{TEAMS}:{account}" if account and f"{TEAMS}:{account}" in canals.tables else TEAMS
    table = canals.table(key)
    return decide(table.lines, table.default, lambda r: designated(r, about, False))


def teams_rule(canals: Canals, account: str, *about: str) -> CanalRule:
    return teams_verdict(canals, account, *about).line
