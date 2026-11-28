"""Les règles pures de l'annuaire (ADR 0298), dans ``ports/contacts.py`` : qui voit les contacts de quel compte, à qui
est un compte, ce qu'est une organisation et une adresse générique, comment un identifiant se range.

- **ce qu'elle a lu ne se dit qu'à qui la source appartient** : un compte à son nom, un compte « à toi » pour une des
  propriétaires, un compte qu'on lui partage (au moins en lecture) ; un compte à elle, à tout le monde ; un compte
  d'une autre, à personne d'autre ;
- **à qui relier un compte** : sa personne quand elle est une seule ;
- **une organisation** : le domaine d'une adresse, sans ses sous-domaines, jamais un webmail public ;
- **une adresse générique** : celle d'une organisation (``noreply``, ``support``, ``facturation+42``…), jamais d'une
  personne.
"""

from __future__ import annotations

import pytest

from mika.ports.contacts import (
    DOMAIN,
    EMAIL,
    MAIL,
    PHONE,
    TEAMS,
    TEAMS_ID,
    account_person,
    generic_address,
    mail_domain,
    normalized,
    org_domain,
    visible_sources,
)

ACCOUNTS = {
    (TEAMS, "adrien"): "personne:adrien",
    (TEAMS, "commun"): "",
    (TEAMS, "sien"): "elle",
    (MAIL, "bea"): "personne:bea",
    (MAIL, "perso"): "",
}


def test_a_person_sees_her_accounts_the_shared_ones_and_those_of_nobody():
    owners = ("adrien",)
    assert visible_sources("adrien", owners=owners, accounts=ACCOUNTS) == {
        (TEAMS, "adrien"), (TEAMS, "commun"), (TEAMS, "sien"), (MAIL, "perso")}
    # Bea n'est pas une propriétaire : ses comptes, et ceux de personne
    assert visible_sources("bea", owners=owners, accounts=ACCOUNTS) == {(MAIL, "bea"), (TEAMS, "sien")}
    # un partage en lecture ouvre la boîte de Bea à Adrien ; un niveau inconnu, rien
    shares = {(MAIL, "bea"): {"personne:adrien": "lire"}, (TEAMS, "adrien"): {"personne:bea": "inconnu"}}
    assert (MAIL, "bea") in visible_sources("adrien", owners=owners, accounts=ACCOUNTS, shares=shares)
    assert (TEAMS, "adrien") not in visible_sources("bea", owners=owners, accounts=ACCOUNTS, shares=shares)
    # personne (une page sans personne connue) : seulement ce qui n'est à personne
    assert visible_sources("", owners=owners, accounts=ACCOUNTS) == {(TEAMS, "sien")}


def test_an_account_is_linked_to_its_person_only_when_she_is_one():
    assert account_person("personne:bea", ("adrien",)) == "bea"
    assert account_person("", ("adrien",)) == "adrien"
    assert account_person("", ("adrien", "bea")) == ""
    assert account_person("", ()) == ""
    assert account_person("elle", ("adrien",)) == ""


@pytest.mark.parametrize(("domain", "org"), [
    ("nordis.fr", "nordis.fr"), ("news.nordis.fr", "nordis.fr"), ("e.mail.fnac.com", "fnac.com"),
    ("impots.gouv.fr", "impots.gouv.fr"), ("www.bbc.co.uk", "bbc.co.uk"), ("x.y.gouv.qc.ca", "y.gouv.qc.ca"),
    ("gmail.com", ""), ("hotmail.fr", ""), ("mail.yahoo.fr", ""), ("localhost", ""), ("", ""),
])
def test_an_organisation_is_the_domain_without_its_subdomains_never_a_webmail(domain, org):
    assert org_domain(domain) == org


@pytest.mark.parametrize(("address", "generic"), [
    ("noreply@edf.fr", True), ("no-reply@edf.fr", True), ("no_reply@edf.fr", True), ("ne.pas.repondre@x.fr", True),
    ("Support@x.fr", True), ("facturation+42@x.fr", True), ("notifications-abc@github.com", True),
    ("newsletter@x.fr", True), ("bonjour@x.fr", True), ("gilles.rousseau@x.fr", False), ("contactez-moi@x.fr", False),
    ("infos@x.fr", True), ("", False), ("pas-une-adresse", False),
])
def test_a_generic_address_is_told_by_its_local_part(address, generic):
    assert generic_address(address) is generic


def test_an_identifier_is_kept_in_one_form():
    assert normalized(TEAMS_ID, " 8:orgid:ABC ") == "8:orgid:abc"
    assert normalized(EMAIL, " Gilles@Nordis.FR ") == "gilles@nordis.fr"
    assert normalized(EMAIL, "pas une adresse") == "" and normalized(EMAIL, "@") == ""
    assert normalized(DOMAIN, "Nordis.fr.") == "nordis.fr" and normalized(DOMAIN, "nordis") == ""
    assert normalized(PHONE, "+33 6 12-34-56-78") == "+33612345678" and normalized(PHONE, "aucun") == ""
    assert mail_domain("Gilles@News.Nordis.fr") == "news.nordis.fr" and mail_domain("sans") == ""


def test_a_tenant_default_domain_or_a_guest_login_never_makes_an_organisation():
    """Relecture I10 : deux petites entreprises sans domaine à elles (``jean@lumen.onmicrosoft.com``,
    ``marie@autre.onmicrosoft.com``) et un invité (``x_gmail.com#ext#@hote.onmicrosoft.com``) rejoignaient tous
    l'organisation « onmicrosoft.com », que le premier profil nommait : tout le monde paraissait « chez Lumen
    Conseil ». Un domaine d'hébergement partagé ne fait pas d'organisation ; un nom de connexion d'invité n'est pas une
    adresse."""
    for domain in ("lumen.onmicrosoft.com", "autre.onmicrosoft.com", "onmicrosoft.com", "lumen.mail.onmicrosoft.com",
                   "lumen.sharepoint.com", "x.onmicrosoft.de"):
        assert org_domain(domain) == "", domain
    assert org_domain("lumen-onmicrosoft.com") == "lumen-onmicrosoft.com"  # un vrai domaine qui lui ressemble
    assert normalized(EMAIL, "x_gmail.com#EXT#@hote.onmicrosoft.com") == ""
    assert normalized(EMAIL, "jean@lumen.onmicrosoft.com") == "jean@lumen.onmicrosoft.com"  # une adresse, sans org
