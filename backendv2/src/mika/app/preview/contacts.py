"""L'annuaire de l'aperçu (ADR 0298) : des personnes connues de loin et des organisations, vues dans le compte Teams
« Équipe » (à adrien, partagé à Béa) et dans les boîtes de l'aperçu (« Atelier », à toi ; « Personnel », à elle) —
rangées comme la collecte les rangerait, profils Teams compris —, ce que le téléphone d'adrien lui montre (« Maman »
sur WhatsApp, en tête-à-tête et dans le groupe « Famille » ; un SMS du numéro de Gilles) et ce qu'adrien lui a raconté
(« Léa », « Maman »), une fiche reliée à Béa, et des rapprochements à valider. Les noms, adresses et numéros sont
inventés."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from mika.inspector.render import PREFIX
from mika.kernel.clock import DAY, HOUR
from mika.plugins.contacts.ingest import CURSOR_TOLD_RULE, TOLD_RULE
from mika.ports.contacts import (
    COMPANY,
    EMAIL,
    MAIL,
    PHONE,
    PHONE_APP,
    PHONE_SOURCE,
    TEAMS,
    TEAMS_ID,
    TENANT,
    TOLD,
    TOLD_NAME,
    Note,
    Observation,
    Portrait,
)

GILLES = "8:orgid:7c2e41d0-5b8a-4f0e-9d21-3a6e0c1f91ab"
DOMINIQUE = "8:orgid:51aa09e2-3c44-4d1b-8f02-77e1c0d4a6b1"
SOPHIE = "8:orgid:0e9f6c3b-28d4-4a5e-b1c7-9d3a2f6e8c40"
ADRIEN = "8:orgid:3e51ce13-6eb8-463b-a75a-a40b2ab67602"
#: le téléphone d'adrien : « Maman » sur WhatsApp, un SMS du numéro de Gilles ; deux conversations
MAMAN, SMS_GILLES = "whatsapp:a1b2c3d4e5f6", "messages:0f1e2d3c4b5a"
DUO, FAMILY, TEXTED = "0a1b2c3d4e5f6a7b", "1b2c3d4e5f6a7b8c", "2c3d4e5f6a7b8c9d"
#: ce qu'adrien lui a raconté (des clés de sa mémoire)
TOLD_LEA, TOLD_MAMAN = "name:9f8e7d6c5b4a3921:lea", "name:9f8e7d6c5b4a3921:maman"


def _seen(kind: str, value: str, source: str, account: str, name: str, count: int, first: int, last: int,
          **more: Any) -> Observation:
    return Observation(kind, value, source, account, name, count, first, last, **more)


def directory(live: Any, now: int, adrien: str, bea: str) -> list[str]:
    """L'annuaire rempli ; rend les adresses de ses fiches et de ses onglets à exporter."""
    store = live.kernel.ports.get("contacts")
    if store is None:
        return []
    t = now
    team, box, hers = (TEAMS, "equipe"), (MAIL, "atelier"), (MAIL, "perso")
    profile = {"count": 0, "first": t - 30 * DAY, "last": t - 30 * DAY}
    seen = [
        # adrien, la personne du compte Teams : le compte le désigne d'office
        _seen(TEAMS_ID, ADRIEN, *team, "Adrien Moreau", 0, t - 40 * DAY, t - 40 * DAY, own=True),
        # Gilles, de Nordis : ses messages Teams, ses courriers, son profil (e-mail, numéro, entreprise)
        _seen(TEAMS_ID, GILLES, *team, "Gilles ROUSSEAU", 48, t - 41 * DAY, t - 2 * HOUR, title="Responsable réseau",
              department="Infrastructures"),
        _seen(EMAIL, "gilles.rousseau@nordis.fr", *box, "Gilles Rousseau", 12, t - 39 * DAY, t - 1 * DAY),
        _seen(EMAIL, "gilles.rousseau@nordis.fr", *team, "Gilles ROUSSEAU", joins=(TEAMS_ID, GILLES), proof=True,
              **profile),
        _seen(PHONE, "+33612345678", *team, "Gilles ROUSSEAU", joins=(TEAMS_ID, GILLES), **profile),
        _seen(COMPANY, "Nordis", *team, "Nordis", joins=(TEAMS_ID, GILLES), **profile),
        _seen(TENANT, "Nordis", *team, "Nordis", joins=(TEAMS_ID, GILLES), **profile),
        _seen(TEAMS_ID, DOMINIQUE, *team, "Dominique ORTEGA", 31, t - 20 * DAY, t - 5 * HOUR,
              title="Tests des mises à jour"),
        _seen(EMAIL, "d.ortega@nordis.fr", *team, "Dominique ORTEGA", joins=(TEAMS_ID, DOMINIQUE), proof=True,
              **profile),
        # une adresse sans personne derrière : rangée à l'organisation
        _seen(EMAIL, "support@nordis.fr", *box, "Support Nordis", 9, t - 35 * DAY, t - 3 * DAY),
        # Sophie, collègue : ses courriers et Teams
        _seen(EMAIL, "sophie.lambert@calix.fr", *box, "Sophie Lambert", 7, t - 25 * DAY, t - 2 * DAY),
        _seen(TEAMS_ID, SOPHIE, *team, "Sophie LAMBERT", 3, t - 22 * DAY, t - 6 * DAY, department="Réseau"),
        _seen(EMAIL, "sophie.lambert@calix.fr", *team, "Sophie LAMBERT", joins=(TEAMS_ID, SOPHIE), proof=True,
              **profile),
        _seen(COMPANY, "Calix Énergie", *team, "Calix Énergie", joins=(TEAMS_ID, SOPHIE), **profile),
        # Léa, qui écrit à l'atelier (ses courriers sont dans la boîte de l'aperçu)
        _seen(EMAIL, "lea@example.net", *box, "Léa Martin", 2, t - 3 * HOUR, t - 37 * 60 * 1_000_000),
        # dans sa boîte à elle : à tout le monde ; « G. Rousseau » rappelle Gilles (un rapprochement)
        _seen(EMAIL, "g.rousseau@gmail.com", *hers, "G. Rousseau", 3, t - 9 * DAY, t - 4 * DAY),
        _seen(EMAIL, "k.haddad@ondes.fr", *hers, "Karim Haddad", 4, t - 12 * DAY, t - 4 * DAY),
        # Béa, qui lui parle aussi : sa fiche de l'annuaire lui est reliée
        _seen(EMAIL, "bea.martin@calix.fr", *box, "Bea Martin", 5, t - 15 * DAY, t - 3 * HOUR),
    ]
    if adrien:
        phone, told = (PHONE_SOURCE, adrien), (TOLD, adrien)
        seen += [
            _seen(PHONE_APP, MAMAN, *phone, "Maman", 49, t - 30 * DAY, t - 1 * DAY, thread=DUO),
            _seen(PHONE_APP, MAMAN, *phone, "Maman", 7, t - 20 * DAY, t - 2 * DAY, thread=FAMILY,
                  thread_title="Famille", group=True),
            # un SMS d'un numéro hors du carnet : celui du profil de Gilles, sa fiche le reçoit
            _seen(PHONE, "06 12 34 56 78", *phone, "", 0, t - 6 * DAY, t - 6 * DAY, same=((PHONE_APP, SMS_GILLES),)),
            _seen(PHONE_APP, SMS_GILLES, *phone, "", 2, t - 6 * DAY, t - 6 * DAY, joins=(PHONE, "+33612345678"),
                  proof=True, thread=TEXTED),
            _seen(TOLD_NAME, TOLD_LEA, *told, "Léa", 3, t - 5 * DAY, t - 3 * DAY),
            _seen(TOLD_NAME, TOLD_MAMAN, *told, "Maman", 4, t - 20 * DAY, t - 2 * DAY),
        ]
    store.observe_now(seen)
    # ce qu'adrien lui a raconté est rangé ici, pas tiré de sa mémoire : la collecte ne le relit pas sous sa règle
    store.set_cursor(CURSOR_TOLD_RULE, TOLD_RULE)
    for kind, value, person in ((TEAMS_ID, ADRIEN, adrien), (EMAIL, "bea.martin@calix.fr", bea)):
        found = store.contact_of(kind, value)
        if found is not None and person:
            store.link(found, person)
    gilles = store.contact_of(TEAMS_ID, GILLES)
    if gilles is not None:  # ce qu'elle a compris de ses derniers messages (lot 6)
        store.portrayed(Portrait(gilles, TEAMS, "equipe", t - HOUR, t - 2 * HOUR, 24, call_id="apercu#1"), [
            Note(0, gilles, TEAMS, "equipe", text, kind, confidence, "", place, t - ago, t - HOUR, "apercu#1")
            for text, kind, confidence, place, ago in (
                ("Il est responsable réseau chez Nordis.", "role", 0.85, "dans le groupe « Déploiement PDV »", 9 * DAY),
                ("Il suit pour adrien la migration des centrales vers le VPN.", "topic", 0.8, "en tête-à-tête",
                 2 * HOUR),
                ("Pour une urgence, il préfère qu'on l'appelle.", "expectation", 0.6, "en tête-à-tête", DAY))])
    urls = [f"{PREFIX}/personnes/personnes?qui=loin", f"{PREFIX}/personnes/personnes?qui=organisations",
            f"{PREFIX}/personnes/personnes?qui=lui_parlent", f"{PREFIX}/personnes/personnes?affichage=tableau",
            f"{PREFIX}/personnes/personnes?q=nordis", f"{PREFIX}/personnes/personnes?de=tous",
            f"{PREFIX}/approbations/rapprochements"]
    if adrien:
        urls.append(f"{PREFIX}/personnes/personnes?de={quote(adrien, safe='')}")
    tabs = [v.name for v in live.kernel.registry.inspectors if v.subject == "contact"]
    for c in store.page(size=100).items:
        base = f"{PREFIX}/fiche/contact/{quote(f'contact:{c.id}', safe='')}"
        urls += [base, *(f"{base}?onglet={name}" for name in tabs)]
    return urls


__all__ = ["directory"]
