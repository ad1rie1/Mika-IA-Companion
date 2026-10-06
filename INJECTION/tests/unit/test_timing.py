"""Le temps incertain : plages, précision, propagation par l'ordre."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from twin.dates import date_from_header, date_from_path, find_date, is_date_line
from twin.timing import DAY, HOUR, Origin, Precision, Temps, from_us, precision_for_width, propagate

TZ = ZoneInfo("Europe/Paris")


def at(y: int, m: int, d: int, hh: int = 12, mm: int = 0) -> Temps:
    return Temps.exact(datetime(y, m, d, hh, mm, tzinfo=TZ))


def local(us: int) -> datetime:
    return from_us(us, TZ)


class TestConstruction:
    def test_un_jour_est_une_journee_locale_avec_un_point_en_pleine_journee(self) -> None:
        t = Temps.day(date(2009, 3, 12), TZ, Origin.HEADER)
        assert local(t.start).hour == 0 and local(t.start).day == 12  # type: ignore[arg-type]
        assert local(t.end).day == 12 and local(t.end).hour == 23  # type: ignore[arg-type]
        assert local(t.point).hour == 14  # type: ignore[arg-type]
        assert t.precision == Precision.DAY

    def test_l_hiver_commence_en_decembre_de_l_annee_precedente(self) -> None:
        t = Temps.season(2010, "hiver", TZ, Origin.CONTENT)
        assert local(t.start).date() == date(2009, 12, 1)  # type: ignore[arg-type]
        assert local(t.end).date() == date(2010, 2, 28)  # type: ignore[arg-type]
        assert t.precision == Precision.SEASON

    def test_une_plage_a_l_envers_est_refusee(self) -> None:
        with pytest.raises(ValueError):
            Temps(10, 5)

    def test_la_precision_suit_la_largeur(self) -> None:
        assert precision_for_width(60 * 1_000_000) == Precision.EXACT
        assert precision_for_width(DAY) == Precision.DAY
        assert precision_for_width(20 * DAY) == Precision.MONTH
        assert precision_for_width(300 * DAY) == Precision.YEAR
        assert precision_for_width(800 * DAY) == Precision.RANGE

    def test_l_intersection_de_deux_estimations_contradictoires_est_none(self) -> None:
        a = Temps.year(2008, TZ, Origin.PATH)
        b = Temps.year(2010, TZ, Origin.CONTENT)
        assert a.intersect(b) is None
        assert Temps.year(2009, TZ, Origin.PATH).intersect(Temps.month(2009, 3, TZ, Origin.HEADER)).precision \
            == Precision.MONTH


class TestPropagation:
    def test_interpolation_entre_deux_messages_dates(self) -> None:
        a, b = at(2009, 3, 12, 10), at(2009, 3, 12, 14)
        out, conflicts = propagate([a, Temps.unknown(), Temps.unknown(), Temps.unknown(), b])
        assert not conflicts
        points = [t.point for t in out]
        assert points == sorted(points)  # type: ignore[type-var]
        mid = out[2]
        assert mid.origin == Origin.INTERPOLATED
        assert local(mid.point).hour == 12  # type: ignore[arg-type]
        assert mid.start == a.start and mid.end == b.end  # la plage reste ce que l'ordre garantit

    def test_l_ordre_resserre_une_plage(self) -> None:
        # une page « 2009 » entre deux pages datées de mars et de mai : elle est entre les deux
        mars = Temps.day(date(2009, 3, 1), TZ, Origin.HEADER)
        annee = Temps.year(2009, TZ, Origin.PATH)
        mai = Temps.day(date(2009, 5, 31), TZ, Origin.HEADER)
        out, _ = propagate([mars, annee, mai])
        assert local(out[1].start).month == 3  # type: ignore[arg-type]
        assert local(out[1].end).month == 5  # type: ignore[arg-type]
        assert out[1].precision == Precision.SEASON  # plus fine qu'« une année », jamais plus large

    def test_une_date_aberrante_est_signalee_seule_sans_contraindre_ses_voisines(self) -> None:
        seq = [at(2009, 3, 12, 23), at(2009, 3, 12, 9), at(2009, 3, 12, 10), Temps.unknown(), at(2009, 3, 12, 11)]
        out, conflicts = propagate(seq)
        assert [c.index for c in conflicts] == [0]
        assert out[0] == seq[0]  # jamais corrigée en silence
        assert local(out[3].point).hour == 10  # type: ignore[arg-type]  # interpolée entre 10 h et 11 h

    def test_une_plage_incompatible_avec_l_ordre_est_un_conflit(self) -> None:
        seq = [Temps.year(2010, TZ, Origin.HEADER), Temps.year(2008, TZ, Origin.PATH),
               Temps.year(2011, TZ, Origin.HEADER)]
        out, conflicts = propagate(seq)
        assert [c.index for c in conflicts] == [1]
        assert out[1] == seq[1]

    def test_sans_voisin_date_un_element_reste_inconnu_mais_garde_une_borne(self) -> None:
        out, _ = propagate([at(2009, 3, 12), Temps.unknown()])
        assert out[1].point is None
        assert out[1].start == out[0].start and out[1].end is None

    def test_une_suite_deja_ordonnee_ne_bouge_pas(self) -> None:
        seq = [at(2009, 1, 1), at(2009, 1, 2), at(2009, 1, 3)]
        assert propagate(seq) == (seq, [])


class TestDatesEcrites:
    @pytest.mark.parametrize(("text", "precision", "check"), [
        ("2009-03-12", Precision.DAY, (2009, 3, 12)),
        ("journal_20090312", Precision.DAY, (2009, 3, 12)),
        ("12/03/2009", Precision.DAY, (2009, 3, 12)),
        ("Le 1er mars 2009", Precision.DAY, (2009, 3, 1)),
        ("Mardi 12 Février 2008", Precision.DAY, (2008, 2, 12)),
        ("March 12, 2009", Precision.DAY, (2009, 3, 12)),
        ("mars 2009", Precision.MONTH, (2009, 3, None)),
        ("2009-03", Precision.MONTH, (2009, 3, None)),
        ("été 2009", Precision.SEASON, (2009, 7, None)),
        ("photos 2009", Precision.YEAR, (2009, None, None)),
    ])
    def test_formes(self, text: str, precision: Precision, check: tuple[int, int | None, int | None]) -> None:
        t = find_date(text, TZ, Origin.PATH)
        assert t is not None and t.precision == precision
        p = local(t.point)  # type: ignore[arg-type]
        y, m, d = check
        assert p.year == y and (m is None or p.month == m) and (d is None or p.day == d)

    def test_le_12_03_se_lit_a_l_americaine_sur_demande(self) -> None:
        t = find_date("3/12/2009", TZ, Origin.HEADER, month_first=True)
        assert t is not None and local(t.point).month == 3  # type: ignore[arg-type]

    def test_pas_de_fausse_date(self) -> None:
        assert find_date("rendez-vous à 14h30, salle 12", TZ, Origin.HEADER) is None
        assert find_date("ticket 3048", TZ, Origin.HEADER) is None

    def test_un_dossier_donne_l_annee_d_un_jour_sans_annee(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        f = tmp_path / "notes" / "2009" / "12 mars.txt"
        t = date_from_path(f, tmp_path, TZ)
        assert t is not None and t.precision == Precision.DAY
        assert local(t.point).date() == date(2009, 3, 12)  # type: ignore[arg-type]

    def test_un_dossier_seul_donne_au_mieux_son_annee(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        t = date_from_path(tmp_path / "2011" / "idées.txt", tmp_path, TZ)
        assert t is not None and t.precision == Precision.YEAR

    def test_en_tete(self) -> None:
        t = date_from_header("Le 12 mars 2009\n\nAujourd'hui j'ai vu Julie.", TZ)
        assert t is not None and t.origin == Origin.HEADER
        assert date_from_header("Une longue phrase qui parle de 2009 et de bien d'autres choses encore, "
                                "beaucoup trop longue pour un en-tête de note.", TZ) is None

    def test_ligne_de_date_de_journal(self) -> None:
        assert is_date_line("Mardi 12 mars 2009 :")
        assert is_date_line("# 2009-03-12")
        assert is_date_line("12 mars")
        assert not is_date_line("Le 12 mars on est allés au ciné avec Julie")


def test_heure_d_ete() -> None:
    # 29 mars 2009 : la nuit perd une heure ; la journée locale dure 23 h
    t = Temps.day(date(2009, 3, 29), TZ, Origin.HEADER)
    assert t.width is not None and t.width < DAY and t.width > DAY - 2 * HOUR
