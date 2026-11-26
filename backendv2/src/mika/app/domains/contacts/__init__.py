"""L'annuaire, tel que la couche ``app`` le relie (ADR 0298, 0310) : sa fiche.

Ce dossier porte son câblage (``wiring.py`` : sa base, le port ``contacts``), son module de l'API par personne
(``api.py``), sa part du direct (``live.py``), sa part de la console (``console/`` : Personnes › Annuaire, la fiche
dessinée d'un contact, ses rapprochements dans la file « À valider », ses deux onglets de la fiche d'une personne) et
ce qu'il ajoute à l'aperçu (``preview.py``). Il lit le courrier, Teams et le téléphone : un contact se voit là où on
le croise.
"""

from __future__ import annotations

from mika.app.domains.domain import Base, Domain

CONTACTS = Domain(
    "contacts",
    needs=("mail", "phone", "teams"),
    base=Base("contacts", models="mika.adapters.contacts.models",
              place="l'annuaire : les personnes et les organisations qu'elle connaît, et où elle les voit"),
    wiring="mika.app.domains.contacts.wiring",
    api="mika.app.domains.contacts.api",
    live="mika.app.domains.contacts.live",
    console="mika.app.domains.contacts.console",
    preview="mika.app.domains.contacts.preview",
    labels={
        "faculties": {"contacts": "Annuaire"},
        "processes": {
            "contacts.ingest": "Ranger dans l'annuaire qui elle lit dans Teams et le courrier",
            "contacts.portrait": "Se faire une idée de qui échange avec un compte, à partir de ses derniers messages",
            "contacts.match": "Réunir les fiches de l'annuaire qui sont la même personne (le juge des rapprochements)",
        },
        # ce que fait chaque famille de ses outils, dit à l'opératrice (Réglages › Droits)
        "about": {
            "contacts":
                "retrouver ce qu'elle sait d'un contact qu'elle lit pour la personne (où elle le voit, ce qu'elle a "
                "compris de ses derniers messages), seulement ce que les comptes de cette personne en montrent",
        },
    },
)
