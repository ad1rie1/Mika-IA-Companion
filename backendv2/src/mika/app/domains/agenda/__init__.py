"""L'agenda, tel que la couche ``app`` le relie (ADR 0309, 0310) : sa fiche.

Ce dossier porte ce que la console change d'un compte (``store.py`` : le port ``agenda_desk``), « L'agenda de Mika »
(``her.py`` : sa mémoire montrée comme un agenda), ses réglages (``settings.py`` : ses comptes, leurs connexions,
l'application Google du serveur, le partage d'un agenda), son câblage (``wiring.py`` : sa base, le port ``agenda`` ;
ses fournisseurs, le port ``agenda_providers`` ; le guichet de la console), son module de l'API par personne
(``api.py`` : ses agendas et ceux qu'on lui partage, leur tableau de droits ; ce qui attend son geste, pour la barre
du haut), ses comptes (``account_settings.py`` : leurs routes, leurs réglages, un agenda neuf ou réglé — Paramètres
› Agendas) et ce qu'une personne a de ses agendas (``reach.py`` : lesquels elle voit, ce qu'elle peut y faire — ce
que l'API, les partages et le direct lisent), ce qu'il partage (``sharing.py`` : ses agendas, avec qui), sa part du
direct (``live.py`` : ce qui change un agenda, et à qui il est), sa part de la console (``console/`` : ses onglets, la
fiche d'un agenda, l'onglet « Agendas » de la fiche d'une personne, ce qu'ils lisent, sa rubrique de réglages, leurs gabarits et leur script) et sa commande (``cli.py`` : ``mika agenda``). Il lit le courrier : son API dit où en est une connexion dans les mots de celles des boîtes
(``ports.mail.SIGNED_IN``), et Microsoft entre par l'application du courrier (ADR 0238), que sa rubrique de réglages
vérifie et enregistre.

Restent au cadre : le rangement de ses droits (le tableau réglé de chaque agenda est gardé par la porte des
réglages avec ceux des canaux et des outils, lus à chaque épisode — on les lit et on les enregistre par ses
réglages) ; « qui peut quoi » — une page qui croise les domaines, où sa console règle le tableau d'un agenda
(``console/rights.py``).
"""

from __future__ import annotations

from mika.app.domains.domain import Base, Domain
from mika.inspector.catalog import Destination, MenuLink

AGENDA = Domain(
    "agenda",
    needs=("mail",),
    base=Base("agenda", models="mika.adapters.agenda.models",
              place="les agendas : ceux de ce serveur, et la copie de ceux qu'on a branchés"),
    settings="mika.app.domains.agenda.settings",
    wiring="mika.app.domains.agenda.wiring",
    api="mika.app.domains.agenda.api",
    live="mika.app.domains.agenda.live",
    sharing="mika.app.domains.agenda.sharing",
    console="mika.app.domains.agenda.console",
    cli="mika.app.domains.agenda.cli",
    # les agendas de chacun (ADR 0309, lot 5) : tous dans une même vue, par personne ; la fiche d'un agenda vit ici ;
    # ses paramètres (les applications Google et Microsoft, la synchro, les rappels) : en haut à droite
    destination=Destination("agendas", "Agendas", "Tous les agendas du système, par personne : leurs comptes, ce qu'elle en "
                            "fait, et le sien.", subjects=("agenda",), builtin=("agendas.parametres",), gear=("parametres",),
                            order=("tous", "comptes", "fait", "mika")),
    menu=MenuLink("Agendas", "agendas", hint="Tous les agendas du système, par personne"),
    plugins={
        "agenda": ("Les agendas de chacun : les applications Google et Microsoft du serveur, la synchronisation, ses "
                   "rappels par défaut ; chacun branche ses comptes dans son espace", ("agendas",),
                   ("Agendas", "agendas/tous")),
    },
    labels={
        "faculties": {
            "agenda": "Agenda",
        },
        "sections": {
            # ADR 0309
            "agenda_day": "Sa journée dans ses agendas (aujourd'hui et demain, cité)",
            "agenda_writes": "Ce qu'elle a proposé d'écrire dans ses agendas, et ce que c'est devenu",
            "agenda_reminder": "Le rendez-vous qu'elle rappelle (cité)",
            "agenda_invitation": "L'invitation dont elle prépare la réponse, et ce qui tombe en même temps (cité)",
        },
        "reasons": {
            # ADR 0309
            "agenda_remind": "Rappeler un rendez-vous, au délai que son agenda demande",
            "agenda_prepare": "Préparer la réponse à une invitation",
        },
        "processes": {
            "agenda.sync": "Relire les agendas branchés (Google, Outlook, CalDAV, abonnements)",
            "agenda.watch": "Voir venir les rappels et les invitations des agendas, laisser tomber ce qui n'a plus lieu d'être",
        },
        "events": {
            "agenda.written": "Ce qu'elle a proposé d'écrire dans un agenda est fait, ou a raté",
            "agenda.reminder_due": "Un rendez-vous à rappeler", "agenda.reminder_dropped": "Un rappel tombé (le rendez-vous a "
            "bougé, est parti, ou son agenda ne le demande plus)",
            "agenda.invitation_noticed": "Une invitation dont elle prépare la réponse",
            "agenda.invitation_settled": "Une invitation qui n'attend plus (répondue, partie, commencée)",
            "agenda.sync_asked": "« Synchroniser maintenant » demandé pour un agenda branché",
        },
        "effects": {
            "agenda:effect.executed": ("agit", "Une écriture dans un agenda",
                                       "elle apprend ce qu'est devenu ce qu'elle y a ajouté, modifié, supprimé ou répondu"),
        },
        "capabilities": {
            "agenda.write": "Agenda",
        },
        "enrichers": {
            "agenda": "Ses agendas (la journée de la personne, ce qu'elle y a proposé)",
            "agenda_reminder": "Le rendez-vous qu'elle rappelle",
            "agenda_invitation": "L'invitation dont elle prépare la réponse",
        },
        "needs": {
            # le serveur branche toujours la base des rendez-vous (ADR 0309) : seule une composition partielle (un test) ne
            # l'a pas ; sa page de réglages vient avec la console de l'agenda (lot 5), le lien ne paraît qu'une fois là
            "agenda": ("ses calendriers ne sont pas branchés sur ce serveur", "agendas"),
        },
        # ce que fait chaque famille de ses outils, dit à l'opératrice (Réglages › Droits)
        "about": {
            "agenda":
                "lire les agendas de la personne qui lui parle, lui trouver un créneau, y ajouter, modifier ou supprimer "
                "un rendez-vous, répondre à une invitation — selon le tableau de chaque agenda",
        },
    },
)
