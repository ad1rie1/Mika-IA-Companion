"""Le courrier, tel que la couche ``app`` le relie (ADR 0027, 0166, 0173, 0238, 0308, 0310) : sa fiche.

Ce dossier porte ses réglages (``settings.py`` : ses boîtes, la connexion Microsoft de chacune, l'application
Microsoft de l'instance, les expéditeurs dont les images s'affichent), son câblage (``wiring.py`` : son client, le
port ``mail`` ; le courrier en direct), son module de l'API par personne (``api.py`` : ses boîtes et celles qu'on lui
partage, leurs messages, les brouillons qu'elle y prépare ; ce qui attend son geste, pour la barre du haut), les
réglages d'une boîte dans l'espace de chacun (``box_settings.py`` : ses routes, qu'``api.py`` ajoute aux siennes),
ce qu'elle partage (``sharing.py`` : ses boîtes, avec qui), ses boîtes comme comptes de son canal
(``accounts.py`` : à qui, comment la console les montre), sa part du direct (``live.py``), sa part de la console
(``console/`` : ses onglets, les fiches d'une boîte, d'un mail et d'un brouillon, sa rubrique de réglages, leurs
gabarits, leur feuille et leurs scripts), sa commande (``cli.py`` : ``mika mail``) et le courrier fictif de l'aperçu
(``demo.py`` : son port simulé, que l'aperçu du cadre pose).

Restent au cadre, parce qu'ils croisent les domaines : ce qui vaut pour toutes les sortes de partages, comment part ce
qu'elle prépare depuis une boîte (la règle de son canal, réglée dans l'espace de chacun : ``app/me/settings.py``, qui
lit à qui est la boîte dans ``accounts.py``), « qui peut quoi », ses autrices (une par boîte), et la vie fictive de
l'aperçu, où ses mails se mêlent au reste.
"""

from __future__ import annotations

from mika.app.domains.domain import Base, Domain
from mika.inspector.catalog import Destination, MenuLink

MAIL = Domain(
    "mail",
    base=Base("mail", models="mika.adapters.mail.models",
              place="le courrier relevé, avec ses pièces jointes et ses images"),
    settings="mika.app.domains.mail.settings",
    wiring="mika.app.domains.mail.wiring",
    api="mika.app.domains.mail.api",
    live="mika.app.domains.mail.live",
    sharing="mika.app.domains.mail.sharing",
    accounts="mika.app.domains.mail.accounts",
    console="mika.app.domains.mail.console",
    cli="mika.app.domains.mail.cli",
    destination=Destination(
        "courrier", "Courrier", "Lire les messages, répondre et suivre les brouillons de chaque boîte.",
        subjects=("mail", "brouillon", "compte"), context=("compte",), automatic_actions=False,
        # ses paramètres (ses boîtes, son relevé, ce qu'elle en dit) : en haut à droite (ADR 0173)
        builtin=("courrier.parametres",), gear=("parametres",)),
    menu=MenuLink("Courrier", "courrier", hint="Ses boîtes aux lettres"),
    plugins={
        "email": ("Ses boîtes : serveurs, identifiants, sa façon d'y écrire ; son relevé, ses brouillons", ("boites",),
                  ("Courrier", "courrier/reception")),
    },
    labels={
        "faculties": {"email": "Courrier"},
        "sections": {
            "mails": "Ses mails non lus",
            "drafts": "Ses brouillons de mails", "voice": "Sa voix dans cette boîte", "task_mail": "Le mail à traiter",
            "task_ask": "Ce qu'on lui demande pour ce mail",
            "edits": "Ce qu'on change à ses brouillons (retouches, refus)",
            "mail_mention": "Le mail important qu'elle annonce",
        },
        "reasons": {"mail_mention": "Parler d'un mail reçu", "mail_draft": "Préparer une réponse à un mail"},
        "processes": {
            "email.poll": "Relever le courrier",
            "email.keep": "Télécharger l'historique du courrier",
        },
        "events": {
            "email.draft_asked": "Une réponse à un mail demandée", "email.noticed": "Un mail remarqué",
            "email.poll_asked": "Une relève demandée", "email.read": "Un mail lu", "email.sent": "Un mail envoyé",
        },
        "effects": {"email:effect.executed": ("agit", "Un mail parti", "elle apprend qu'il est parti, retouché ou non")},
        "capabilities": {"email.send": "Mail"},
        "enrichers": {"mail": "Son courrier"},
        "signals": {"mail": "un mail", "sent_by_operator": "un mail envoyé à sa place"},
        # ce que fait chaque famille de ses outils, dit à l'opératrice (Réglages › Droits)
        "about": {
            "email": "lister, chercher et lire le courrier des boîtes qu'elle lit, le ranger, préparer une réponse",
        },
    },
)
