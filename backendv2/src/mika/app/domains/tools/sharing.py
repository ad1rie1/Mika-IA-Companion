"""Ce que ses outils venus d'ailleurs partagent (ADR 0188, 0192, 0310) : ses services — sa part des partages
(``app/me/sharing.py``).

Un service partagé reçoit une ligne d'accès pour la personne (ADR 0192) — lire : ses outils qui lisent ; s'en servir :
aussi ceux qui agissent, sur sa demande à elle ; retirer le partage retire la ligne. Il se règle sur ses lignes
d'accès : la console ne le retire pas d'ailleurs (sa part n'a pas d'écriture à part, ``write``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mika.app.domains.domain import SharingPart
from mika.app.domains.tools import api as mcp_me
from mika.app.domains.tools.settings import ToolsSettings
from mika.app.me.api import Call, Denied, missing
from mika.app.me.sharing import Shared
from mika.vocab.access import PERSON, SHARE_PREPARE, SHARE_USE


def service_shares(spec: Any) -> dict[str, str]:
    """Les partages d'un service, par personne (« personne:<clé> ») : leur niveau, lu par la règle de ``mcp.shared``."""
    return {who: level for who, (level, _line) in mcp_me.shared(spec).items()}


def every(settings: Any, names: Mapping[str, str] | None = None) -> list[Shared]:
    """Ses partages, service par service : les lignes de chaque service qui a un propriétaire."""
    out: list[Shared] = []
    for name, spec in sorted(settings.of(ToolsSettings).mcp().servers.items()):
        if spec.owner:
            out += [Shared("mcp", name, name, spec.owner, who[len(PERSON):], level)
                    for who, level in sorted(service_shares(spec).items())]
    return out


async def share(call: Call, settings: Any, key: str, person: str, level: str) -> None:
    """Son propriétaire partage un de ses services, pour lire ou pour s'en servir : la ligne de la personne, posée
    juste après la sienne ; un niveau vide la retire."""
    who = PERSON + person
    spec_m = mcp_me.mine(call).get(key)
    if spec_m is None:
        other = settings.of(ToolsSettings).mcp().servers.get(key)
        if other is not None and other.owner and PERSON + call.me.person in service_shares(other):
            raise Denied(403, "Seul son propriétaire partage ce service.")  # comme une boîte qu'on te partage
        raise missing()
    if level == SHARE_PREPARE:
        raise Denied(400, "Un service se partage pour lire ou pour s'en servir.")
    def access(spec: Any) -> dict[str, Any]:
        # calculées sur la fiche relue sous ``Settings.writing`` : une ligne retirée ailleurs entre-temps ne
        # revient pas, une ligne ajoutée ailleurs reste
        lines = [a.model_dump() for a in spec.access if tuple(a.who) != (who,)]
        if level:
            line = {"who": [who], "read": "seule", "act": "carte" if level == SHARE_USE else "non",
                    "keep": "prive"}
            lines.insert(1 if lines else 0, line)  # juste après la sienne : la première qui la désigne décide
        return {"access": lines}

    port = call.port("mcp")
    if port is None:
        raise Denied(503, "Les services ne sont pas branchés.")
    await port.settle(key, access)


SHARING = SharingPart("mcp", every=every, share=share, word="service", article="le ")
