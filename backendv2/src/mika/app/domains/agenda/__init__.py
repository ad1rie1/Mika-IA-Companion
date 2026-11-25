"""L'agenda, tel que la couche ``app`` le relie (ADR 0309, 0310) : sa fiche.

Ce dossier porte ce que la console change d'un compte (``desk.py`` : le port ``agenda_desk``), « L'agenda de Mika »
(``her.py`` : sa mémoire montrée comme un agenda), ses réglages (``settings.py`` : l'application Google du serveur),
son câblage (``wiring.py`` : sa base, le port ``agenda`` ; ses fournisseurs, le port ``agenda_providers`` ; le
guichet de la console), son module de l'API par personne (``api.py`` : ses agendas et ceux qu'on lui partage, ses
comptes, leurs réglages, leur tableau de droits ; ce qui attend son geste, pour la barre du haut) et sa part de la
console (``console/`` : ses onglets, la fiche d'un agenda, ce qu'ils lisent, leurs gabarits et leur script). Il lit
le courrier : son API dit où en est une connexion dans les mots de celles des boîtes (``ports.mail.SIGNED_IN``), et
Microsoft entre par l'application du courrier (ADR 0238).

Restent au cadre : ses comptes, leurs connexions et le partage d'un agenda dans les réglages du serveur
(``Settings.agenda``…, sous le verrou des connexions Microsoft du courrier) et ses droits (``agenda_tables``, lus à
chaque épisode) ; l'onglet « Agendas » de la fiche d'une personne, « qui peut quoi », les partages, ce que concerne
un accord — des pages qui croisent les domaines.
"""

from __future__ import annotations

from mika.app.domains.domain import Base, Domain

AGENDA = Domain(
    "agenda",
    needs=("mail",),
    base=Base("agenda", models="mika.adapters.agenda.models",
              place="les agendas : ceux de ce serveur, et la copie de ceux qu'on a branchés"),
    settings="mika.app.domains.agenda.settings",
    wiring="mika.app.domains.agenda.wiring",
    api="mika.app.domains.agenda.api",
)
