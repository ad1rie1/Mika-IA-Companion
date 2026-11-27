"""Comment part un courrier (ADR 0132, 0134) : la ligne de ses canaux qui vaut pour une adresse, depuis une boîte — le
tableau de la boîte (``courrier:<clé>``), sinon celui du courrier, sinon le minimum vital —, la plus serrée d'un envoi
à plusieurs destinataires, et comment il part sous elle. Le moteur des canaux et ce que Teams partage avec lui — qui
une ligne d'un de tes comptes désigne (``designated``, ``addressed``) — sont dans ``vocab/canals.py``.
"""

from __future__ import annotations

from collections.abc import Iterable

from mika.vocab.access import MAIL, Verdict, decide
from mika.vocab.canals import CanalRule, Canals, designated


def mail_verdict(canals: Canals, account: str, address: str) -> Verdict[CanalRule]:
    """La ligne d'un courrier de (ou vers) cette adresse, depuis cette boîte, et sa place : le tableau de la boîte
    (``courrier:<clé>``), sinon celui du courrier, sinon le minimum vital."""
    table = canals.table(f"{MAIL}:{account}") if f"{MAIL}:{account}" in canals.tables else canals.table(MAIL)
    return decide(table.lines, table.default, lambda r: designated(r, (address,), True))


def mail_rule(canals: Canals, account: str, address: str) -> CanalRule:
    return mail_verdict(canals, account, address).line


def mail_rule_for_all(canals: Canals, account: str, addresses: Iterable[str]) -> CanalRule:
    """La ligne la plus serrée d'un envoi à plusieurs destinataires : il ne part seul que si chacun le permet."""
    found = [mail_rule(canals, account, a) for a in addresses] or [mail_rule(canals, account, "")]
    return next((r for r in found if mail_send(r) != "seule"), found[0])


def mail_send(rule: CanalRule) -> str:
    """Comment un courrier part sous cette ligne : pas de brouillon que tu envoies toi-même (il vaut ton accord)."""
    return "accord" if rule.reply == "brouillon" else rule.reply
