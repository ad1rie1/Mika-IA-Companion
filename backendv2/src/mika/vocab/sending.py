"""Ce qu'elle envoie à ta place, courrier et Teams (ADR 0132) : des règles lues de haut en bas, comme celles d'un
pare-feu, puis une règle par défaut.

Une règle dit un **canal** (le courrier — toutes ses boîtes ou une seule — ou Teams), un **destinataire** (tout le
monde ; pour le courrier, une adresse ou un @domaine ; pour Teams, un morceau du nom d'une conversation, de son
identifiant ou du nom de qui écrit), si elle **prépare** une réponse d'elle-même, et comment elle **envoie** :
brouillon (Teams : posé dans la zone de saisie, c'est toi qui l'envoies), ton accord (une carte, ou la console), ou
seule. Pour un message, la première règle qui correspond au canal et au destinataire décide ; aucune : la règle par
défaut. Le courrier n'a pas de brouillon que tu envoies toi-même : « brouillon » y vaut « ton accord ».

Partagé par le courrier, Teams et la console : une valeur, pas une faculté.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mika.kernel.forms import Knob
from mika.vocab.access import Verdict, decide

MAIL, TEAMS = "courrier", "teams"
#: un canal : tout (la règle par défaut), le courrier (toutes ses boîtes), une boîte (``courrier:<clé>``), Teams
CHANNEL = re.compile(rf"^(?:|{MAIL}|{MAIL}:[a-z0-9_-]{{1,40}}|{TEAMS})$")
#: comment elle envoie
SENDS = (("brouillon", "brouillon — c'est toi qui l'envoies"), ("accord", "ton accord"), ("seule", "seule"))
#: ce que le courrier sait faire (pas de brouillon que tu envoies toi-même)
MAIL_SENDS = ("accord", "seule")
Send = Literal["brouillon", "accord", "seule"]


class SendRule(BaseModel):
    """Une règle d'envoi : canal, destinataire, préparer d'elle-même, comment envoyer."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    canal: Annotated[str, Knob(
        label="Le canal", help="Le courrier (toutes ses boîtes, ou « courrier:<boîte> »), ou Teams ; vide : tout (la "
                            "règle par défaut).")] = Field("", pattern=CHANNEL.pattern)
    dest: Annotated[str, Knob(
        label="Destinataire", help="Vide : tout le monde. Courrier : une adresse ou un @domaine ; Teams : un morceau "
                                   "du nom d'une conversation, de son identifiant ou du nom de qui écrit.")] = \
        Field("", max_length=200)
    prepare: Annotated[bool, Knob(
        label="Préparer d'elle-même", help="Pour un message qui attend une réponse, elle en prépare une sans qu'on "
                                           "le lui demande.")] = False
    send: Annotated[Send, Knob(label="Envoi", choices=SENDS, help="Comment ce qu'elle écrit part.")] = "accord"

    @field_validator("dest")
    @classmethod
    def _dest(cls, dest: str) -> str:
        return dest.strip().lower()

    @model_validator(mode="before")
    @classmethod
    def _mail_has_no_draft(cls, data: object) -> object:
        """Le courrier n'a pas de brouillon que tu envoies toi-même : « brouillon » y vaut « ton accord »."""
        if isinstance(data, dict) and str(data.get("canal", "")).startswith(MAIL) and data.get("send") == "brouillon":
            return {**data, "send": "accord"}
        return data


#: la règle par défaut d'une installation neuve : elle ne prépare rien d'elle-même, et rien ne part sans ton accord
DEFAULT = SendRule()


def mail_send(rule: SendRule) -> str:
    """Comment un courrier part sous cette règle (« brouillon », réservé à Teams, y vaut « ton accord »)."""
    return "accord" if rule.send == "brouillon" else rule.send


def _addressed(dest: str, address: str) -> bool:
    """Un destinataire de courrier : une adresse exacte, ou un @domaine."""
    address = address.strip().lower()
    domain = "@" + address.split("@")[-1] if "@" in address else ""
    return dest == address or (dest.startswith("@") and dest == domain)


def mail_verdict(rules: Sequence[SendRule], default: SendRule, account: str, address: str) -> Verdict[SendRule]:
    """La règle d'un courrier de (ou vers) cette adresse, depuis cette boîte, et sa place : le moteur commun
    (``vocab.access.decide``), son destinataire pour sélecteur."""
    return decide(rules, default, lambda r: r.canal in (MAIL, f"{MAIL}:{account}")
                  and (not r.dest or _addressed(r.dest, address)))


def mail_rule(rules: Sequence[SendRule], default: SendRule, account: str, address: str) -> SendRule:
    """La règle d'un courrier de (ou vers) cette adresse, depuis cette boîte : la première qui correspond."""
    return mail_verdict(rules, default, account, address).line


def mail_rule_for_all(rules: Sequence[SendRule], default: SendRule, account: str,
                      addresses: Iterable[str]) -> SendRule:
    """La règle la plus serrée d'un envoi à plusieurs destinataires : il ne part seul que si chacun le permet."""
    found = [mail_rule(rules, default, account, a) for a in addresses] or [mail_rule(rules, default, account, "")]
    return next((r for r in found if mail_send(r) != "seule"), found[0])


def teams_verdict(rules: Sequence[SendRule], default: SendRule, *about: str) -> Verdict[SendRule]:
    """La règle d'un message Teams et sa place : ``about`` — l'identifiant de la conversation, son nom, qui écrit ; la
    première règle de Teams dont le destinataire en est un morceau (ou vide)."""
    hay = "\n".join(a.lower() for a in about if a)
    return decide(rules, default, lambda r: r.canal == TEAMS and (not r.dest or r.dest in hay))


def teams_rule(rules: Sequence[SendRule], default: SendRule, *about: str) -> SendRule:
    """La règle d'un message Teams : la première de Teams dont le destinataire correspond (``teams_verdict``)."""
    return teams_verdict(rules, default, *about).line


class Sending(BaseModel):
    """Ses règles d'envoi, dans leur ordre, et la règle par défaut."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rules: Annotated[tuple[SendRule, ...], Knob(
        label="Règles", help="Lues de haut en bas : pour un message, la première qui correspond au canal et au "
                             "destinataire décide.")] = ()
    default: Annotated[SendRule, Knob(label="Par défaut", help="Quand aucune règle ne correspond.")] = DEFAULT


#: ce que Teams envoyait selon son mode d'avant l'ADR 0132
_TEAMS_MODES = {"brouillon": "brouillon", "validation": "accord", "autonome": "seule"}


def from_before(accounts: Mapping[str, Mapping[str, object]], approval: bool,
                teams: Mapping[str, object] | None) -> Sending:
    """Les réglages d'avant l'ADR 0132 en règles qui font la même chose : pour chaque boîte, ses « jamais pour »
    puis « préparer d'elle-même » ; pour Teams, ses « jamais pour » puis son mode. ``approval`` : un envoi de
    courrier attendait un accord ; ``teams`` : ses réglages (``None`` : jamais réglés, ses défauts d'alors)."""
    mail_send: Send = "accord" if approval else "seule"
    rules: list[SendRule] = []
    for key, raw in sorted(accounts.items()):
        canal = f"{MAIL}:{key}"
        prepare = bool(raw.get("autodraft"))
        if prepare:
            rules += [SendRule(canal=canal, dest=s, prepare=False, send=mail_send)
                      for s in raw.get("autodraft_skip") or () if str(s).strip()]
        if (prepare, mail_send) != (DEFAULT.prepare, DEFAULT.send):
            rules.append(SendRule(canal=canal, prepare=prepare, send=mail_send))
    t = {"mode": "brouillon", "autodraft": True, "skip": (), **(teams or {})}
    teams_send = _TEAMS_MODES.get(str(t["mode"]), "brouillon")
    prepare = bool(t["autodraft"])
    if prepare:
        rules += [SendRule(canal=TEAMS, dest=s, prepare=False, send=teams_send)
                  for s in t["skip"] or () if str(s).strip()]
    if (prepare, teams_send) != (DEFAULT.prepare, DEFAULT.send):
        rules.append(SendRule(canal=TEAMS, prepare=prepare, send=teams_send))
    return Sending(rules=tuple(rules))
