"""Les domaines de Mika, tels que la couche ``app`` les relie (ADR 0310).

Chaque domaine a son dossier ici et sa fiche (``Domain``, ``domain.py``). ``DOMAINS`` les liste, à la main et dans un
ordre voulu : c'est l'ordre où le cadre les parcourt — celui où ses routes sont essayées, où ``mika --help`` montre
ses commandes. Rien n'est découvert : ni dossier balayé, ni point d'entrée ; ajouter un domaine, c'est écrire son
dossier et l'inscrire ici.

Une fiche n'importe rien : elle nomme les modules de ses parts, que le cadre importe au moment d'assembler
(``domain.part``). Ce module est donc une feuille : tout module d'``app`` peut le lire sans que l'import tourne en
rond.
"""

from __future__ import annotations

from mika.app.domains.agenda import AGENDA
from mika.app.domains.contacts import CONTACTS
from mika.app.domains.domain import Base, ConsolePart, Domain, LivePart, part
from mika.app.domains.forge import FORGE
from mika.app.domains.mail import MAIL
from mika.app.domains.phone import PHONE
from mika.app.domains.senses import SENSES
from mika.app.domains.teams import TEAMS
from mika.app.domains.tools import TOOLS
from mika.app.domains.wakeup import WAKEUP

__all__ = ["DOMAINS", "Base", "ConsolePart", "Domain", "LivePart", "part"]

#: les domaines, dans l'ordre où le cadre les parcourt
DOMAINS: tuple[Domain, ...] = (TOOLS, MAIL, SENSES, TEAMS, PHONE, WAKEUP, CONTACTS, AGENDA, FORGE)
