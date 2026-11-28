"""Elle › Humeur et corps, chaque onglet dans sa forme (``app/handmade/tabs/life.py``, ADR 0177), à travers le vrai
serveur : ce que chaque page dit, et à sa place — son humeur en grand puis ses balises, une carte par personne, ses
trois besoins côte à côte, sa journée sur 24 heures, elle-même en sous-onglets. Les
calculs du dessin (la chaleur signée, la journée qui passe minuit, la pagination qui revient à son sous-onglet) se
vérifient sans serveur."""

from __future__ import annotations

import html
import re
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace

from markupsafe import Markup

from mika.app.handmade import unit
from mika.app.handmade.tabs import FOLDED, Got, Line, anchored, life
from mika.contracts import body
from mika.contracts import self_ as self_c
from mika.faculties.affect import inspect as affect_view
from mika.faculties.body import inspect as body_view
from mika.faculties.self.params import params as self_params
from mika.inspector import render
from mika.inspector.ui import env
from mika.kernel.inspect import Badge, Fields, Row, Table, When, pct_fr
from mika.vocab import temperament as T
from tests.protocol.test_console_diagnostics import stop
from tests.protocol.test_console_workflows import append
from tests.protocol.test_drawn_pages import drawn
from tests.protocol.test_now_page import chat
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée


def _between(page: str, start: str, end: str) -> str:
    """Le morceau de la page entre deux repères (le premier après ``start``)."""
    return page.split(start, 1)[1].split(end, 1)[0]


def _words(part: str) -> str:
    """Ce qu'un morceau de page donne à lire : sans ses balises, ses entités rendues, ses espaces resserrés."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", part)).split())


def test_her_mood_in_big_then_the_figures_then_her_tags_with_what_she_said(world):  # noqa: F811
    client, _, _ = world
    bootstrap(client)
    chat(client, "salut ! je reviens d'un concert")
    page = drawn(client, "/admin/vie/humeur")
    hero = _between(page, 'class="now-hero', "</section>")
    # son humeur en mots, ce que son prompt lui en dit, le plan plaisir × éveil et sa trace sur la période
    assert 'class="now-word"' in hero and "ce que son prompt lui en dit" in hero and 'class="plane-now"' in hero
    assert "sa trace sur 24 h" in hero
    band = _words(_between(page, "vie-band", "</section>"))
    assert band.index("Envie d'en parler") < band.index("Son fond") < band.index("Son visage") \
        < band.index("Dernière balise")
    # chaque tuile dit ce qu'elle mesure, sans les mots du moteur
    assert "elle écrit d'elle-même au-delà de" in band and "ce que montre son avatar" in band
    assert "lecture absolue" not in band and "pousse à parler" not in band and "déborde" not in band
    # sa balise déclarée en lui répondant (la doublure écrit « contente »), et ce qu'elle a dit
    tags = _between(page, 'class="vie-tags"', "</ol>")
    assert "sw-happy" in tags and "J'ai bien lu" in tags and "en répondant" in tags
    assert page.index("Sa valence") < page.index("Ses dernières balises") < page.index("Les chiffres bruts")
    # la période est celle du filtre de la console
    assert "sa trace sur 7 jours" in drawn(client, "/admin/vie/humeur?periode=7j")


def test_one_card_per_person_with_what_she_tells_herself(world):  # noqa: F811
    client, _, _ = world
    bootstrap(client)
    chat(client)
    page = drawn(client, "/admin/vie/postures")
    cards = _between(page, 'class="vie-stances"', "</section>")
    assert 'href="/admin/fiche/person/user_1?onglet=affect"' in cards  # sa fiche, sur ce qu'elle ressent
    assert 'class="vie-said"' in cards  # ce qu'elle se dit envers elle
    assert cards.index("Chaleur") < cards.index("Hostilité") < cards.index("Attachement")
    assert "Le détail" in cards and "Elle en veut à" not in page


def test_a_grudge_is_the_one_banner_and_warmth_leans_to_its_side():
    cold = life._signed({"t": "meter", "ratio": 0.4, "text": "−0,40", "tone": "danger"})
    assert (cold["x1"], cold["x2"], cold["side"]) == (30.0, 50, "cold")
    warm = life._signed({"t": "meter", "ratio": 0.2, "text": "+0,20", "tone": "ok"})
    assert (warm["x1"], warm["x2"], warm["side"]) == (50, 60.0, "warm")
    line = Line({"personne": {"t": "link", "text": "Bea", "href": "/admin/fiche/person/bea"},
                 "chaleur (−1…1)": {"t": "meter", "ratio": 0.4, "text": "−0,40", "tone": "danger"},
                 "hostilité": {"t": "meter", "ratio": 0.5, "text": "50\u202f%", "tone": ""}},
                {}, "", "", [{"t": "note", "text": "Tu lui en veux encore.", "title": "ce qu'elle se dit"}], False, {})
    bea = life._stance(line)
    # la rancune se lit à la part de la jauge (le seuil de la vue), pas à son ton
    assert bea["grudge"] and bea["says"] == "Tu lui en veux encore." and bea["initial"] == "B"
    below = affect_view.GRUDGE_FROM - 0.01
    calm = Line({"hostilité": {"t": "meter", "ratio": below, "text": pct_fr(below), "tone": "danger"}},
                {}, "", "", [], False, {})
    assert not life._stance(calm)["grudge"]
    page = str(Markup(env.get_template("handmade/vie/postures.html").render(
        t={"id": "pg1", "count": 1, "empty": ""}, people=[bea], lede="", grudges=[bea["who"]], forms={},
        tables="table")))
    assert page.count('class="person-tab-note danger"') == 1 and page.index("Elle en veut à") < page.index("vie-stances")
    assert 'class="vie-stance grudge"' in page and 'class="vie-signed cold' in page


def test_the_anchor_of_a_stance_is_in_the_card_detail_not_on_the_card():
    """Ses chiffres bruts, dont l'ancre (une colonne repliée de la faculté), sont dans le détail de la carte ; la
    carte ne garde que sa dernière balise."""
    folded = {"t": "fields", "title": FOLDED, "pairs": [
        {"label": "ancre", "value": {"t": "text", "text": "amoureuse 2 %"}},
        {"label": "dernière balise", "value": {"t": "text", "text": "contente 40 %"}}]}
    facts = {"t": "fields", "title": "", "pairs": [{"label": "installée", "value": {"t": "text", "text": "non"}}]}
    line = Line({"personne": {"t": "text", "text": "Bea"}}, {p["label"]: p["value"] for p in folded["pairs"]},
                "", "", [{"t": "note", "text": "Rien de particulier.", "title": "ce qu'elle se dit"}, facts, folded],
                False, {})
    bea = life._stance(line)
    shown = [p["label"] for d in bea["facts"] for p in d.get("pairs", [])]
    assert "ancre" in shown and "installée" in shown and "dernière balise" not in shown
    page = str(Markup(env.get_template("handmade/vie/postures.html").render(
        t={"id": "pg1", "count": 1, "empty": ""}, people=[bea], lede="", grudges=[], forms={}, tables="table")))
    meta = _words(_between(page, 'class="vie-meta"', "</p>"))
    assert "dernière balise" in meta and "contente" in meta and "ancre" not in meta
    assert "amoureuse 2 %" in _words(_between(page, "<summary>Le détail</summary>", "</details>"))


def test_the_installed_postures_are_counted_in_words():
    """Le chapeau de « Envers chacun » compte les postures que leurs échanges ont installées, accordé (C2-09) ; il
    les reconnaît à la clé de leur étiquette, jamais à ses mots."""
    def lede(*installed: bool | Badge) -> str:
        rows = tuple(Row((f"P{i}", "—", "—", "—", "—", "—", "—", "—"), detail=(Fields((
            ("installée", x if isinstance(x, Badge) else affect_view.INSTALLED if x else affect_view.NOT_INSTALLED),
        )),)) for i, x in enumerate(installed))
        got = Got(SimpleNamespace(env=lambda: render.Env(when=str, now=0)),
                  [Table(affect_view.POSTURE_COLUMNS, rows, title="Postures envers chacun")], {}, {})
        return _words(_between(str(life.postures(got)), 'id="vie-stances-title"', "</header>"))

    assert "1 posture installée (plusieurs échanges concordants)" in lede(True, False)
    assert "2 postures installées (plusieurs échanges concordants)" in lede(True, True)
    assert "installée" not in lede(False)
    renamed = replace(affect_view.INSTALLED, text="bien installée")
    assert "1 posture installée" in lede(renamed)
    assert "installée" not in lede(Badge("oui, ou presque", "muted", key=affect_view.NOT_INSTALLED.key))


def test_her_three_needs_side_by_side_then_their_curve_and_what_happens(world):  # noqa: F811
    client, _, _ = world
    bootstrap(client)
    chat(client)
    page = drawn(client, "/admin/vie/needs")
    needs = _between(page, 'class="vie-needs"', "</ul>")
    assert needs.index("Compagnie") < needs.index("S'exprimer") < needs.index("Apprendre")
    assert "n-social" in needs and "n-expression" in needs and "n-curiosity" in needs  # chacun sa couleur
    assert "ce qui le comble" in needs
    assert 'class="hm-calm"' in page  # rien de pressant : rien ne se dit dans son prompt
    assert page.index("Ses besoins dans le temps") < page.index('id="vie-needs-now"') < page.index("Ses règles")
    assert 'href="?vue_pg1=table"' in page  # la bascule « Tableau » de la faculté


def test_the_page_says_its_rubric_and_its_period_is_a_choice_not_a_form(world):  # noqa: F811
    """La maquette (ADR 0176) : « Mika / Humeur et corps » en fil d'Ariane, la destination en lien ; la période, de
    petits choix, en bouton à choix au bout de la barre d'onglets, appliquée d'un clic — ni formulaire, ni
    « Filtrer »."""
    client, live, _ = world
    bootstrap(client)
    page = drawn(client, "/admin/vie/needs")
    crumbs = page.split('<nav class="crumbs"', 1)[1].split("</nav>", 1)[0]
    her = self_c.name_of(live.kernel.mind.frame().get(self_c.PERSONA))
    assert f"<span>{her}</span>" in crumbs and '<span aria-hidden="true">/</span>' in crumbs
    assert '<a href="/admin/vie">Humeur et corps</a>' in crumbs and "<h1>Besoins</h1>" in page
    assert 'class="eyebrow"' not in page
    row = page.split('class="tabs-row"', 1)[1].split('class="tabs-tail"', 1)
    assert 'aria-current="page">Besoins' in row[0]  # les onglets, puis au bout la période
    period = row[1].split("</nav>", 1)[0]
    assert '<nav class="seg" aria-label="Période">' in period
    assert 'href="?periode=24h" aria-current="true">24 h<' in period and 'href="?periode=7j">7 jours<' in period
    assert '<form class="filters"' not in page and ">Filtrer<" not in page
    week = drawn(client, "/admin/vie/needs?periode=7j")
    assert 'href="?periode=7j" aria-current="true">7 jours<' in week


def test_her_day_on_24_hours_then_her_nights(world):  # noqa: F811
    client, _, _ = world
    bootstrap(client)
    page = drawn(client, "/admin/vie/rythme")
    day = _between(page, 'class="vie-day"', "</figure>")
    for phase in ("matin", "après-midi", "soir", "nuit"):
        assert f">{phase}</text>" in day, phase
    assert "sa nuit" in day and 'class="vie-now"' in day and "ce que son prompt lui dit de l'heure" in page
    assert page.index("Sa journée") < page.index("Ses dernières 24 heures") < page.index("Ses dernières nuits") \
        < page.index("Dernières transitions") < page.index("En détail")


def test_the_messages_waiting_for_her_waking_are_counted_in_words(world):  # noqa: F811
    """L'étiquette du rythme accorde le verbe et le nom au compte que la faculté donne (C2-09)."""
    client, live, _ = world
    bootstrap(client)
    stop(client, live.kernel)  # une vie à l'arrêt : rien ne répond aux messages pendant la lecture
    append(client, live.kernel, [body.WAITED.draft(message=901, handle="user_1", person="user_1")], "body")
    flags = _words(_between(drawn(client, "/admin/vie/rythme"), 'class="now-chips vie-flags"', "</ul>"))
    assert "1 message attend son réveil" in flags and "message(s)" not in flags
    append(client, live.kernel, [body.WAITED.draft(message=902, handle="user_1", person="user_1")], "body")
    flags = _words(_between(drawn(client, "/admin/vie/rythme"), 'class="now-chips vie-flags"', "</ul>"))
    assert "2 messages attendent son réveil" in flags


def test_the_rhythm_reads_the_keys_of_its_facts_not_their_words(world, monkeypatch):  # noqa: F811
    """Le rythme lit l'état de son corps à la clé de ses étiquettes (``Badge.key``), jamais à leurs mots : un « non »
    qui dirait « oui » ne la dit pas réveillée par un message ; libres sous d'autres mots, ses initiatives ne se
    signalent pas ; retenues sous d'autres mots, elles se signalent, de leur ton."""
    monkeypatch.setattr(body_view, "NO", Badge("oui", "muted", key=body_view.NO.key))
    monkeypatch.setattr(body_view, "_gate_badge", lambda s, frame: Badge("libres comme l'air", "ok",
                                                                         key=body_view.FREE))
    client, live, _ = world
    bootstrap(client)
    stop(client, live.kernel)
    page = drawn(client, "/admin/vie/rythme")
    assert 'class="now-chips vie-flags"' not in page  # rien à signaler
    monkeypatch.setattr(body_view, "_gate_badge", lambda s, frame: Badge("tenues : elle dort", "warn",
                                                                         key=body_view.VETOED))
    flags = _between(drawn(client, "/admin/vie/rythme"), 'class="now-chips vie-flags"', "</ul>")
    assert '<li class="warn">initiatives et travail tenues : elle dort</li>' in flags
    assert "réveillée par un message" not in flags


def test_a_night_stayed_up_late_is_read_by_its_key():
    """Ses dernières nuits : « veillé tard » se lit à la clé de l'étiquette de la vue, pas à son mot."""
    def late(cell: Badge) -> bool:
        table = Table(("endormie", "réveillée", "dormi", "tirée du sommeil", "veillé tard", "ce qu'elle en sait"),
                      ((When(1), When(2), "7 h", "—", cell, ""),), title="Ses dernières nuits")
        look = SimpleNamespace(frame=SimpleNamespace(local=lambda at: datetime(2026, 11, 15, 23)), hm=lambda at: "23:00")
        return life._nights(SimpleNamespace(raw_table=lambda title: table), look)[0]["late"]

    assert late(body_view.LATE) and late(replace(body_view.LATE, text="jusqu'à pas d'heure"))
    assert not late(body_view.NO) and not late(Badge("oui", "muted", key=body_view.NO.key))


def _phase(name: str, start: str, tint: str) -> Line:
    return Line({"phase": {"t": "text", "text": name}, "début": {"t": "text", "text": start},
                 "teinte": {"t": "swatch", "key": tint, "text": tint}}, {}, "", "", [], False, {})


def test_the_night_phase_crosses_midnight_and_says_its_longer_piece():
    phases = [_phase("matin", "06:00", "hopeful"), _phase("après-midi", "12:00", "playful"),
              _phase("soir", "18:00", "relieved"), _phase("nuit", "23:00", "dreamy")]
    day = life._day(phases, "de 23:00 à 06:00", 60)
    night = day["phases"][-1]
    assert [(r["x"], r["w"]) for r in night["rects"]] == [(life._pct(23 * 60), life._pct(60)), (0.0, 25.0)]
    assert night["mid"] == 12.5  # son nom au milieu de 0 h – 6 h, pas sur la dernière heure
    assert len(day["sleep"]) == 2 and day["now_label"] == "01:00" and day["now_anchor"] == "start"


def test_herself_in_four_subtabs_her_temperament_by_family(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    page = drawn(client, "/admin/vie/soi")
    nav = _between(page, 'class="hm-subnav"', "</nav>")
    assert nav.index("Son estime") < nav.index("Son récit") < nav.index("Sa persona") < nav.index("Son tempérament")
    for pane in ("soi-estime", "soi-recit", "soi-persona", "soi-temperament"):
        assert f'id="{pane}" data-pane' in page, pane
    assert 'href="#soi-recit"' in _between(page, "vie-band", "</section>")  # la bande mène à son sous-onglet
    assert 'class="vie-scale-now' in page  # son estime sur son échelle
    # ses seuils et ses bornes lus dans ses paramètres, dits en % comme son estime (C2-03), plus relus dans un texte
    frame = live.kernel.mind.frame()
    p = self_params(frame.env.params_of("self", frame.root))
    scale = _between(page, 'class="vie-scale"', "</figure>")
    assert f'class="vie-scale-track" x="{unit(p.esteem_min)}%"' in scale
    assert f'class="vie-scale-sure" x="{unit(p.assured_above)}%"' in scale
    assert f"elle doute · sous {pct_fr(p.doubt_below)}" in scale and "sur une échelle de 0 à 100 %" in scale
    assert f'<text class="vie-scale-value" x="{unit(p.esteem_rest)}%" y="11" text-anchor="middle">' \
           f"{pct_fr(p.esteem_rest)}</text>" in scale  # jamais bousculée : à son repos
    persona = frame.get(self_c.PERSONA)
    temperament = page.split('id="soi-temperament"', 1)[1]  # le dernier sous-onglet
    assert T.PROFILES[T.profile_of(persona.temperament)].label in temperament
    assert temperament.index(T.FEEL) < temperament.index(T.OTHERS)  # ses curseurs, famille par famille
    assert "imperturbable" in temperament and "à fleur de peau" in temperament  # les deux bouts d'un curseur
    lists = _between(page, 'id="soi-persona"', 'id="soi-temperament"')
    assert all(f"<li>{x}</li>" in lists for x in persona.interests)  # ses centres d'intérêt, un par ligne


def test_who_she_becomes_in_subtabs(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    page = drawn(client, "/admin/vie/devenir")
    nav = _between(page, 'class="hm-subnav"', "</nav>")
    assert nav.index("Ce qu'elle sait d'elle") < nav.index("Ce qui la passionne") < nav.index("Ce qui la définit") \
        < nav.index("Ses changements d'avis")
    knowing = _between(page, 'id="devenir-sait"', "</section>")
    assert knowing.index("Tenir parole") < knowing.index("Mener au bout") < knowing.index("Voir venir")
    passions = _between(page, 'id="devenir-passions"', "</section>")
    interests = live.kernel.mind.frame().get(self_c.PERSONA).interests
    assert passions.count('class="vie-passion-head"') == len(interests) and "jamais nourrie" in passions


def test_a_list_in_a_subtab_pages_back_to_it():
    """Ses liens de pagination reviennent au sous-onglet ; « first » d'une pagination numérotée est un rang (« 51–100
    sur 158 »), il ne prend pas d'ancre."""
    table = {"pager": {"prev": "", "next": "?pg3=2", "first": 51, "links": [{"n": 1, "href": "?pg3=1"}, {"gap": True}]}}
    anchored(table, "devenir-avis")
    assert table["pager"]["next"] == "?pg3=2#devenir-avis" and table["pager"]["prev"] == ""
    assert table["pager"]["links"][0]["href"] == "?pg3=1#devenir-avis" and table["pager"]["first"] == 51
    cursor = {"pager": {"cursor": True, "older": "?avant=9", "newer": "", "first": "?"}}
    anchored(cursor, "devenir-avis")
    assert cursor["pager"]["older"] == "?avant=9#devenir-avis" and cursor["pager"]["first"] == "?#devenir-avis"
