"""Les canaux et leurs tableaux (ADR 0134) : par où ça arrive, et ce que ce canal laisse passer au plus.

Un canal (``vocab.access.Canal`` : un type — le chat web, l'app Android, Teams, le courrier, Internet, elle seule
— ou une instance) a son tableau, lu de haut en bas puis sa ligne par défaut. Ses colonnes sont des **plafonds** :
répondre (ou écrire), ce qu'elle fait d'un outil qui lit et d'un outil qui agit, piloter un projet, ses fichiers, ce
qu'elle en garde — la ressource qu'une demande touche a son propre tableau, lu ensuite, et la plus stricte gagne.
Sur **tes comptes** (une boîte de courrier, ton compte Teams), elle écrit à ta place : ses colonnes sont alors
« préparer d'elle-même » et comment ça part (brouillon, ton accord, seule) ; qui est en face s'y dit par une
adresse ou un @domaine (le courrier), un morceau du nom d'une conversation ou de qui écrit (Teams), ou tout le
monde. Un canal qu'on n'a pas réglé a son **minimum vital** (``vital``), écrit ici.

Rangés dans les réglages, passés en paramètre à qui en lit (journalisés : sa vie se rejoue) ; une valeur, pas une
faculté.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from mika.kernel.forms import Knob
from mika.vocab.access import (
    ADDRESS,
    ALONE,
    EVERYONE,
    INTERNAL,
    INTERNET,
    KEEPS,
    MAIL,
    MOBILE,
    NO,
    POLICIES,
    REPLIES,
    STEER_EDIT,
    STEER_NO,
    STEER_READ,
    STEERS,
    TEAMS,
    WEB,
    Canal,
    Keep,
    Policy,
    Reply,
    Rule,
    Steer,
    Table,
    Verdict,
    canal_key,
    canal_of,
    decide,
    facing,
)


class CanalRule(Rule):
    """Une ligne d'un tableau de canal : ce que ce canal laisse passer au plus pour qui est en face — répondre (sur
    tes comptes : comment ce qu'elle écrit part), préparer d'elle-même (tes comptes), un outil qui lit, un outil qui
    agit, piloter un projet, ses fichiers, ce qu'elle en garde."""

    reply: Annotated[Reply, Knob(label="Répondre, écrire", choices=REPLIES, advanced=False)] = "non"
    prepare: Annotated[bool, Knob(label="Préparer d'elle-même", advanced=False)] = False
    read: Annotated[Policy, Knob(label="Un outil qui lit, au plus", choices=POLICIES, advanced=False)] = NO
    act: Annotated[Policy, Knob(label="Un outil qui agit, au plus", choices=POLICIES, advanced=False)] = NO
    steer: Annotated[Steer, Knob(label="Piloter un projet, au plus", choices=STEERS, advanced=False)] = STEER_NO
    files: Annotated[bool, Knob(label="Ses fichiers", advanced=False)] = False
    keep: Annotated[Keep, Knob(label="Ce qu'elle en garde, au plus", choices=KEEPS, advanced=False)] = "rien"


#: la ligne par défaut d'un canal : fermée, comme un pare-feu
CLOSED = CanalRule()
#: tout ouvert : ce que laisse un canal qui prouve qui parle (le chat web, l'app Android) et elle seule
WIDE = CanalRule(who=(EVERYONE,), reply="seule", read=ALONE, act=ALONE, steer=STEER_EDIT, files=True, keep="public")


class CanalTable(Table[CanalRule]):
    """Le tableau d'un canal."""

    default: CanalRule = CLOSED


#: le minimum vital de chaque type de canal, tant qu'on ne l'a pas réglé : le chat web et l'app Android laissent
#: tout (les tableaux des ressources décident) ; elle seule, tout ; Internet, répondre, et lire un projet ; tes
#: comptes (le courrier, Teams) : rien ne part sans ton accord, elle ne prépare rien d'elle-même
VITAL: Mapping[str, CanalTable] = {
    WEB: CanalTable(lines=(WIDE,)),
    MOBILE: CanalTable(lines=(WIDE,)),
    INTERNAL: CanalTable(lines=(CanalRule(canal=(INTERNAL,), reply="seule", read=ALONE, act=ALONE,
                                          steer=STEER_EDIT, files=True, keep="public"),)),
    INTERNET: CanalTable(lines=(CanalRule(who=(EVERYONE,), reply="seule", steer=STEER_READ),)),
    MAIL: CanalTable(lines=(CanalRule(who=(EVERYONE,), reply="accord"),)),
    TEAMS: CanalTable(lines=(CanalRule(who=(EVERYONE,), reply="accord"),)),
}


def vital(canal: str) -> CanalTable:
    """Le minimum vital d'un canal (son type décide)."""
    return VITAL.get(canal_key(canal)[0], CanalTable())


class Canals(BaseModel):
    """Les tableaux réglés, par canal (un type, ou une instance ``type:clé``) ; un canal absent a son minimum vital."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tables: Annotated[dict[str, CanalTable], Knob(
        label="Canaux", advanced=False,
        help="Le tableau de chaque canal réglé (un type, ou une instance « type:clé ») ; un canal absent a son minimum "
             "vital. Réglés dans Réglages › Canaux.")] = Field(default_factory=dict)

    def table_of(self, canal: Canal) -> tuple[CanalTable, str]:
        """Le tableau qui vaut par ce canal, et sa clé : son instance si elle est réglée, sinon son type, sinon le
        minimum vital."""
        for key in (canal.key, canal.type):
            if key in self.tables:
                return self.tables[key], key
        return vital(canal.type), canal.type

    def table(self, key: str) -> CanalTable:
        """Le tableau d'une clé de canal, réglé ou vital."""
        return self.tables.get(key) or vital(key)


def canal_verdict(canals: Canals, audience: Any, kind: str, *, close: Any = None) -> tuple[Verdict[CanalRule], str] | None:
    """La ligne du canal par où cette audience arrive, sa place, et la clé du tableau ; ``None`` hors de toute
    situation."""
    from_ = canal_of(audience, kind)
    matches = facing(audience, kind, close=close)
    if from_ is None or matches is None:
        return None
    table, key = canals.table_of(from_)
    return decide(table.lines, table.default, matches), key


# ── tes comptes : le courrier, Teams ───────────────────────────────────────


def addressed(motif: str, address: str) -> bool:
    """Un destinataire de courrier : une adresse exacte, ou un @domaine."""
    address, motif = address.strip().lower(), motif.strip().lower()
    domain = "@" + address.split("@")[-1] if "@" in address else ""
    return motif == address or (motif.startswith("@") and motif == domain)


def _designated(line: CanalRule, hay: Iterable[str], by_address: bool) -> bool:
    """Une ligne d'un de tes comptes désigne-t-elle ce correspondant ? Tout le monde, ou une de ses adresses (le
    courrier : exacte ou @domaine ; Teams : un morceau de la conversation ou de qui écrit)."""
    if not line.who or EVERYONE in line.who:
        return True
    text = "\n".join(h.lower() for h in hay if h)
    for w in line.who:
        if not w.startswith(ADDRESS):
            continue
        motif = w[len(ADDRESS):]
        if (addressed(motif, text) if by_address else motif.lower() in text):
            return True
    return False


def mail_verdict(canals: Canals, account: str, address: str) -> Verdict[CanalRule]:
    """La ligne d'un courrier de (ou vers) cette adresse, depuis cette boîte, et sa place : le tableau de la boîte
    (``courrier:<clé>``), sinon celui du courrier, sinon le minimum vital."""
    table = canals.table(f"{MAIL}:{account}") if f"{MAIL}:{account}" in canals.tables else canals.table(MAIL)
    return decide(table.lines, table.default, lambda r: _designated(r, (address,), True))


def mail_rule(canals: Canals, account: str, address: str) -> CanalRule:
    return mail_verdict(canals, account, address).line


def mail_rule_for_all(canals: Canals, account: str, addresses: Iterable[str]) -> CanalRule:
    """La ligne la plus serrée d'un envoi à plusieurs destinataires : il ne part seul que si chacun le permet."""
    found = [mail_rule(canals, account, a) for a in addresses] or [mail_rule(canals, account, "")]
    return next((r for r in found if mail_send(r) != "seule"), found[0])


def mail_send(rule: CanalRule) -> str:
    """Comment un courrier part sous cette ligne : pas de brouillon que tu envoies toi-même (il vaut ton accord)."""
    return "accord" if rule.reply == "brouillon" else rule.reply


def teams_verdict(canals: Canals, account: str, *about: str) -> Verdict[CanalRule]:
    """La ligne d'un message Teams et sa place : ``about`` — l'identifiant de la conversation, son nom, qui écrit ;
    le tableau du compte (``teams:<clé>``), sinon celui de Teams, sinon le minimum vital."""
    key = f"{TEAMS}:{account}" if account and f"{TEAMS}:{account}" in canals.tables else TEAMS
    table = canals.table(key)
    return decide(table.lines, table.default, lambda r: _designated(r, about, False))


def teams_rule(canals: Canals, account: str, *about: str) -> CanalRule:
    return teams_verdict(canals, account, *about).line
