"""Ce qu'on lit d'une fiche de DATAtourisme (ADR 0245), sur des réponses réelles du 17/11/2026 : son nom, sa position
et son adresse, son texte sans Markdown, ses tarifs et s'il est gratuit, ses contacts (jamais le nom d'une personne),
son auteur et sa mise à jour, ses labels, ses photos (crédit, licence, fin des droits) ; pour un événement, ses
occurrences et ses thèmes. Une fiche illisible est laissée, jamais une erreur."""

from __future__ import annotations

from datetime import date

import pytest

from mika.adapters.maps.datatourisme import EVENT, PLACE, Fiche, name_key, plain, read_fiche, themes_of
from tests.fixtures import tourism as tf


def by_uuid(rows: list[dict]) -> dict[str, Fiche]:
    out = {}
    for raw in rows:
        fiche = read_fiche(raw)
        assert fiche is not None, raw.get("uuid")
        out[fiche.uuid] = fiche
    return out


def test_every_real_fiche_reads_with_its_place_author_and_update():
    for rows in (tf.events(), tf.restaurants(), tf.markets()):
        for fiche in by_uuid(rows).values():
            assert fiche.name and fiche.author and len(fiche.updated) == 10
            assert fiche.lat is not None and fiche.lon is not None and fiche.department
            assert fiche.town


def test_an_event_reads_its_dates_its_price_and_its_place():
    clerc = by_uuid(tf.events())[tf.JULIEN_CLERC]
    assert clerc.kind == EVENT and clerc.category == "" and clerc.sort_fr == "Événement"
    assert clerc.street and clerc.postcode.startswith("59") and clerc.town == "Roubaix" and clerc.department == "59"
    assert [(o.first, o.opens, o.closes) for o in clerc.occurrences] == [(date(2026, 11, 22), "17:00", "19:00")]
    assert clerc.prices == "De 65€ à 45€" and clerc.free is False
    assert clerc.themes == ("concerts", "spectacles")


def test_a_restaurant_reads_its_sort_its_labels_and_its_photo_with_credit_and_licence():
    rows = by_uuid(tf.restaurants())
    resort = rows[tf.RESORT]
    assert resort.kind == PLACE and resort.category == "manger" and resort.sort == "restaurant"
    assert ("Accueil Vélo", "2028-06-15") in resort.labels and ("5 étoiles", "") in resort.labels
    [photo] = resort.photos
    assert photo.url == "https://aisne.media.tourinsoft.eu/upload/resort-barriere-lille--2--3.jpg"
    assert photo.credit == "Patrick Messina" and photo.licence == "By-NC-ND 4.0" and photo.rights_end == "2032-06-03"
    assert resort.uri.startswith("https://data.datatourisme.fr/")


def test_contacts_keep_phones_sites_and_never_a_persons_name():
    resort = by_uuid(tf.restaurants())[tf.RESORT]
    assert ("Téléphone", "+33 3 28 14 45 00") in resort.contacts
    assert ("Site", "https://www.hotelsbarriere.com/fr/lille/hotel-barriere.html") in resort.contacts
    said = repr(resort)
    assert "Jeanne" not in said and "EXEMPLE" not in said and "Madame" not in said


def test_a_market_reads_its_period_and_its_weekdays():
    markets = by_uuid(tf.markets())
    vallon = markets["1982b799-b64b-3345-ad22-b2b1395ad066"]
    [o] = vallon.occurrences
    assert (o.first, o.last, o.opens, o.closes) == (date(2026, 1, 1), date(2026, 12, 31), "08:00", "12:00")
    assert o.days == 1 << 6  # le dimanche
    assert vallon.themes == ("marches",) and vallon.department == "74"


def test_markdown_turns_into_clean_paragraphs():
    text = plain({"@fr": "**Fiat lux !**  \nUne _quête_ de [lumière](https://exemple.fr/x)\n\n\n\n# Titre\n\\_fin\\_"})
    assert text == "Fiat lux !\nUne quête de lumière\n\nTitre\n_fin_"
    assert plain({"@fr": "a" * 7000}).endswith("…")


@pytest.mark.parametrize(("name", "types", "summary", "themes"), [
    ("Quatuor Poulenc", ["Concert", "Congress", "BusinessEvent"], "", ("concerts",)),
    ("Ça capte !", ["FairOrShow", "SaleEvent"], "L'exposition « Ça capte ! »", ("expositions",)),
    ("Marché de Wazemmes", ["Market", "SaleEvent"], "", ("marches",)),
    # des classes en trop : seules celles que le résumé confirme
    ("Mercredi tout est permis", ["Festival", "ShowEvent", "Carnival", "Parade", "Visit", "Traineeship"],
     "Un spectacle pour les enfants", ("spectacles", "enfants")),
    ("Atelier", ["Product"], "", ()),
])
def test_themes_come_from_the_name_then_from_the_classes(name, types, summary, themes):
    assert themes_of(types, name, summary) == themes


@pytest.mark.parametrize(("info", "low", "high", "prices", "free"), [
    ("Entrée libre", None, None, "Entrée libre", True),
    ("Gratuit pour tous, sur réservation", None, None, "Gratuit pour tous, sur réservation", True),
    ("12/8€ - Gratuit moins de 18 ans", None, None, "12/8€ - Gratuit moins de 18 ans", False),
    ("Gratuit pour les moins de 12 ans", None, None, "Gratuit pour les moins de 12 ans", None),
    (None, [6], [12], "de 6 € à 12 €", False),
    (None, [0], [0], "gratuit", True),
    (None, None, None, "", None),
])
def test_free_is_guessed_from_the_price_and_never_invented(info, low, high, prices, free):
    spec = {"priceCurrency": "EUR"}
    if info:
        spec["additionalInformation"] = {"@fr": info}
    if low is not None:
        spec["minPrice"], spec["maxPrice"] = low, high
    raw = {"uuid": tf.POULENC, "label": {"@fr": "Essai"}, "type": ["Event", "EntertainmentAndEvent"],
           "offers": [{"priceSpecification": [spec]}]}
    fiche = read_fiche(raw)
    assert (fiche.prices, fiche.free) == (prices, free)


@pytest.mark.parametrize("raw", [
    None, [], {"uuid": "pas-un-uuid", "label": {"@fr": "x"}}, {"uuid": tf.POULENC, "label": {"@fr": ""}},
    {"uuid": tf.POULENC, "label": {"@fr": "x"}, "isLocatedAt": "cassé", "takesPlaceAt": [{"startDate": 3}],
     "hasMainRepresentation": [{"hasRelatedResource": [{"locator": ["javascript:alert(1)"]}]}]},
])
def test_an_unreadable_fiche_is_left_aside_without_raising(raw):
    fiche = read_fiche(raw)
    assert fiche is None or (fiche.photos == () and fiche.lat is None and fiche.occurrences == ())


def test_names_compare_without_accents_articles_or_their_sort():
    assert name_key("Hôtel Barrière Lille") == "barriere lille"
    assert name_key("Le Café des Remparts") == "remparts"
    assert name_key("Restaurant") == "restaurant"
