"""Qui est qui : elle reconnue canal par canal, les autres regroupés, la main qui l'emporte."""

from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from twin.corpus import Corpus, SourceStats
from twin.people import name_key, pseudo_key, resolve_people, slugify
from twin.records import MAIL, ME, MSN, SMS, WHATSAPP, Author, Conversation, Message
from twin.timing import Temps

TZ = ZoneInfo("Europe/Paris")


def add(corpus: Corpus, path: str, items: list) -> None:  # type: ignore[type-arg]
    with corpus.transaction():
        sid = corpus.begin_source(path, path, "test", 1, 0, "2026-10-06")
        corpus.add_items(sid, items, SourceStats())


def msg(channel: str, conv: str, author: str, rank: int, kind: str = "message") -> Message:
    return Message(channel, conv, author, f"texte {rank}", Temps.exact(1_600_000_000_000_000 + rank * 60_000_000),
                   rank, kind=kind)


def corpus_de_test(tmp_path: Path) -> Corpus:
    c = Corpus(tmp_path / "corpus.db")
    # WhatsApp : trois discussions à deux ; elle s'appelle « Léa Martin » dans ses exports
    for i, other in enumerate(["Julie Martin", "Paul", "Maman"]):
        add(c, f"wa{i}", [
            Author(WHATSAPP, other, name=other, me=False, me_reason="porte le nom de la discussion"),
            Author(WHATSAPP, "Léa Martin", name="Léa Martin", me=True, me_reason="discussion à deux"),
            Conversation(WHATSAPP, other, members=(other, "Léa Martin")),
            msg(WHATSAPP, other, other, 0), msg(WHATSAPP, other, "Léa Martin", 1)])
    # un groupe où elle apparaît sans indice : son nom suffit
    add(c, "wa-groupe", [
        Conversation(WHATSAPP, "Les copines", group=True, members=("Léa Martin", "Zoé", "Paul")),
        msg(WHATSAPP, "Les copines", "Zoé", 0)])
    # SMS : le numéro de Julie (son nom complet dans le carnet) ; un « Paul » homonyme ailleurs
    add(c, "sms", [
        Author(SMS, ME, me=True, me_reason="envoyé"),
        Author(SMS, "+33611111111", name="Julie Martin", address="+33611111111", me=False),
        Conversation(SMS, "+33611111111", members=(ME, "+33611111111")),
        msg(SMS, "+33611111111", "+33611111111", 0), msg(SMS, "+33611111111", ME, 1)])
    # mails : sans indice « Envoyés » ; elle est dans les trois fils, une newsletter dans un seul
    for i, (who, kind) in enumerate([("paul.durand@example.com", "message"), ("noreply@shop.example", "masse"),
                                     ("julie.martin@example.com", "message")]):
        add(c, f"mail{i}", [
            Author(MAIL, who, name="", address=who), Author(MAIL, "lea@example.org", address="lea@example.org"),
            Conversation(MAIL, f"fil{i}", members=(who, "lea@example.org")),
            msg(MAIL, f"fil{i}", who, 0, kind), msg(MAIL, f"fil{i}", "lea@example.org", 1)])
    # MSN : deux fichiers ; ses pseudos changent mais se recoupent
    add(c, "msn1", [
        Author(MSN, "julie1#Juju", name="Juju", aliases=("Juju", "Juju ☆")),
        Author(MSN, "julie1#Léa ~ zik", name="Léa ~ zik", aliases=("Léa ~ zik", "Léa (absente)")),
        Conversation(MSN, "julie1", members=("julie1#Juju", "julie1#Léa ~ zik")),
        msg(MSN, "julie1", "julie1#Juju", 0), msg(MSN, "julie1", "julie1#Léa ~ zik", 1)])
    add(c, "msn2", [
        Author(MSN, "paul2#Polo", name="Polo", aliases=("Polo",)),
        Author(MSN, "paul2#Léa ~ zik", name="Léa ~ zik", aliases=("Léa ~ zik", "Léa en vacances")),
        Conversation(MSN, "paul2", members=("paul2#Polo", "paul2#Léa ~ zik")),
        msg(MSN, "paul2", "paul2#Polo", 0), msg(MSN, "paul2", "paul2#Léa ~ zik", 1)])
    return c


def person_of(c: Corpus, channel: str, key: str) -> tuple[int, str, int]:
    r = c.db.execute("SELECT p.id, p.handle, p.is_me FROM participants pa JOIN persons p ON p.id = pa.person "
                     "WHERE pa.channel = ? AND pa.key = ?", (channel, key)).fetchone()
    return r["id"], r["handle"], r["is_me"]


def test_elle_est_reconnue_dans_chaque_canal(tmp_path: Path) -> None:
    c = corpus_de_test(tmp_path)
    report = resolve_people(c, tmp_path / "personnes.yaml", TZ)
    assert person_of(c, WHATSAPP, "Léa Martin")[2] == 1
    assert person_of(c, SMS, ME)[2] == 1
    assert person_of(c, MAIL, "lea@example.org")[2] == 1  # par sa présence dans tous les fils
    assert person_of(c, MSN, "julie1#Léa ~ zik")[2] == 1  # par ses pseudos qui reviennent
    assert person_of(c, MSN, "paul2#Léa ~ zik")[2] == 1
    assert "mail" in report.me_by_channel and "msn" in report.me_by_channel


def test_les_autres_se_regroupent_sur_ce_qui_ne_trompe_pas(tmp_path: Path) -> None:
    c = corpus_de_test(tmp_path)
    resolve_people(c, tmp_path / "personnes.yaml", TZ)
    julie_wa = person_of(c, WHATSAPP, "Julie Martin")
    julie_sms = person_of(c, SMS, "+33611111111")
    assert julie_wa == julie_sms and julie_wa[1] == "ext_julie-martin"  # même nom complet
    # « Paul » (prénom seul) n'est pas fusionné avec paul.durand@ ni avec « Polo »
    paul = person_of(c, WHATSAPP, "Paul")
    assert paul != person_of(c, MAIL, "paul.durand@example.com")
    assert paul != person_of(c, MSN, "paul2#Polo")
    shop = c.db.execute("SELECT ignored FROM persons WHERE id = ?", (person_of(c, MAIL, "noreply@shop.example")[0],))
    assert shop.fetchone()["ignored"] == 1


def test_la_main_l_emporte_et_n_est_plus_recalculee(tmp_path: Path) -> None:
    c = corpus_de_test(tmp_path)
    review = tmp_path / "personnes.yaml"
    resolve_people(c, review, TZ)
    data = yaml.safe_load(review.read_text(encoding="utf-8"))
    # on fusionne « Paul » (WhatsApp) avec paul.durand@ et « Polo » (MSN), et on nomme la relation
    entries = data["personnes"]
    paul = next(e for e in entries if "whatsapp:Paul" in e["participants"])
    for other_ref in ("mail:paul.durand@example.com", "msn:paul2#Polo"):
        other = next(e for e in entries if other_ref in e["participants"])
        other["participants"].remove(other_ref)
        paul["participants"].append(other_ref)
    paul["nom"], paul["relation"] = "Paul Durand", "ami"
    review.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")

    report = resolve_people(c, review, TZ)
    assert report.manual_applied >= 3
    pid = person_of(c, WHATSAPP, "Paul")[0]
    assert person_of(c, MAIL, "paul.durand@example.com")[0] == pid == person_of(c, MSN, "paul2#Polo")[0]
    row = c.db.execute("SELECT name, relation, manual FROM persons WHERE id = ?", (pid,)).fetchone()
    assert (row["name"], row["relation"], row["manual"]) == ("Paul Durand", "ami", 1)

    # relancer sans rien toucher ne change rien
    again = resolve_people(c, review, TZ)
    assert again.manual_applied == 0
    assert person_of(c, MSN, "paul2#Polo")[0] == pid


def test_retiree_d_elle_a_la_main_ne_lui_revient_pas(tmp_path: Path) -> None:
    c = corpus_de_test(tmp_path)
    review = tmp_path / "personnes.yaml"
    resolve_people(c, review, TZ)
    data = yaml.safe_load(review.read_text(encoding="utf-8"))
    data["elle"]["participants"].remove("mail:lea@example.org")  # ce n'était pas elle
    review.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    resolve_people(c, review, TZ)
    assert person_of(c, MAIL, "lea@example.org")[2] == 0



def test_une_note_du_mcp_n_est_pas_ecrasee_par_la_revue_restee_en_l_etat(tmp_path: Path) -> None:
    """Claude Code note « Maman » → « Hélène Martin, mère » ; la revue, écrite avant, n'a pas bougé."""
    from twin.mcp.server import JumeauTools

    c = corpus_de_test(tmp_path)
    review = tmp_path / "personnes.yaml"
    resolve_people(c, review, TZ)
    pid = person_of(c, WHATSAPP, "Maman")[0]
    JumeauTools(c, TZ, write=True).note_person({"personne": f"p{pid}", "nom": "Hélène Martin", "relation": "mère"})
    resolve_people(c, review, TZ)
    row = c.db.execute("SELECT name, relation FROM persons WHERE id = ?", (pid,)).fetchone()
    assert (row["name"], row["relation"]) == ("Hélène Martin", "mère")
    data = yaml.safe_load(review.read_text(encoding="utf-8"))  # et la revue réécrite le montre
    assert any(e["nom"] == "Hélène Martin" for e in data["personnes"])


def test_une_date_decidee_survit_a_la_relecture_de_sa_source(tmp_path: Path) -> None:
    from twin.dating import apply_manual, date_corpus
    from twin.records import NOTES, Document

    c = Corpus(tmp_path / "corpus.db")
    doc = Document(NOTES, "carnet.txt", "note", "Idées", "des idées", Temps.unknown(), 0, path="carnet.txt")
    add(c, "carnet.txt", [Author(NOTES, ME, me=True), doc])
    dates = tmp_path / "dates.yaml"
    dates.write_text("a_dater:\n- document: carnet.txt\n  date: mars 2009\n", encoding="utf-8")
    date_corpus(c, dates, TZ)
    c.db.execute("DELETE FROM documents")  # la source est relue : sa date redevient celle de la source
    c.db.execute("DELETE FROM sources")
    add(c, "carnet.txt", [Author(NOTES, ME, me=True), doc])
    dates.write_text("a_dater: []\n", encoding="utf-8")
    assert apply_manual(c, dates, TZ) == 1
    row = c.db.execute("SELECT t_precision, t_origin FROM documents").fetchone()
    assert (row["t_precision"], row["t_origin"]) == ("mois", "manuel")
    assert apply_manual(c, dates, TZ) == 0  # déjà appliquée : rien ne bouge

def test_cles() -> None:
    assert name_key("Julie  MARTIN") == name_key("julie martin") == "julie martin"
    assert name_key("Julie") == ""
    assert pseudo_key("~Juju☆ (en cours)") == "juju en cours"
    assert slugify("Hélène D'Arcy") == "helene-d-arcy"


def msn_file(c: Corpus, conv: str, contact: tuple[str, ...], her: tuple[str, ...], hint: bool | None = None) -> None:
    """Un fichier MSN : le côté du contact et le sien, chacun avec ses pseudos."""
    a, b = f"{conv}#{contact[0]}", f"{conv}#{her[0]}"
    add(c, conv, [Author(MSN, a, name=contact[0], aliases=contact), Author(MSN, b, name=her[0], aliases=her, me=hint),
                  Conversation(MSN, conv, members=(a, b)), msg(MSN, conv, a, 0), msg(MSN, conv, b, 1)])


def test_msn_ses_pseudos_changent_avec_les_annees(tmp_path: Path) -> None:
    """« Léa ~ zik » revient partout ; « Léa ♥ Tom » apparaît plus tard : rattaché par le fichier de transition.
    Un contact qui s'appelle « Coeur » à côté d'elle ne fait pas de « Coeur » un de ses pseudos."""
    c = Corpus(tmp_path / "corpus.db")
    friends = ["Alice", "Bea", "Chloe", "Dora", "Emma", "Coeur", "Fanny"]
    hers = [("Léa ~ zik",)] * 4 + [("Léa ~ zik", "Léa ♥ Tom"), ("Léa ♥ Tom",), ("Léa ♥ Tom", "Coeur")]
    for i, (friend, her) in enumerate(zip(friends, hers, strict=True)):
        msn_file(c, f"f{i}", (friend,), her)
    resolve_people(c, tmp_path / "personnes.yaml", TZ)
    assert all(person_of(c, MSN, f"f{i}#{her[0]}")[2] for i, her in enumerate(hers))
    assert not any(person_of(c, MSN, f"f{i}#{friend}")[2] for i, friend in enumerate(friends))


def test_msn_un_pseudo_commun_est_propose_pas_fusionne(tmp_path: Path) -> None:
    c = Corpus(tmp_path / "corpus.db")
    msn_file(c, "julie1", ("Juju",), ("Léa ~ zik",))
    msn_file(c, "julie2", ("Juju",), ("Léa ~ zik",))
    resolve_people(c, tmp_path / "personnes.yaml", TZ)
    a, b = person_of(c, MSN, "julie1#Juju"), person_of(c, MSN, "julie2#Juju")
    assert a[0] != b[0]
    reviews = [r["review"] for r in c.db.execute("SELECT review FROM persons WHERE id IN (?, ?)", (a[0], b[0]))]
    assert all("pseudo MSN « juju »" in r for r in reviews)


def test_msn_un_journal_plus_n_empeche_pas_de_la_reconnaitre_dans_les_xml(tmp_path: Path) -> None:
    c = Corpus(tmp_path / "corpus.db")
    add(c, "plus", [Author(MSN, "Léa ~ zik", name="Léa ~ zik", me=True, me_reason="titulaire"),
                    Author(MSN, "Julie", name="Julie", address="julie@hotmail.com", me=False),
                    Conversation(MSN, "plus", members=("Léa ~ zik", "Julie")),
                    msg(MSN, "plus", "Julie", 0), msg(MSN, "plus", "Léa ~ zik", 1)])
    msn_file(c, "paul2", ("Polo",), ("Léa ~ zik", "Léa en vacances"))
    resolve_people(c, tmp_path / "personnes.yaml", TZ)
    assert person_of(c, MSN, "paul2#Léa ~ zik")[2] == 1
    assert person_of(c, MSN, "paul2#Polo")[2] == 0


def test_deux_numeros_reunis_par_le_seul_nom_sont_signales(tmp_path: Path) -> None:
    c = Corpus(tmp_path / "corpus.db")
    for number in ("+33611111111", "+33622222222"):
        add(c, f"sms{number}", [Author(SMS, ME, me=True, me_reason="envoyé"),
                                Author(SMS, number, name="Julie Martin", address=number, me=False),
                                Conversation(SMS, number, members=(ME, number)), msg(SMS, number, number, 0)])
    resolve_people(c, tmp_path / "personnes.yaml", TZ)
    person = person_of(c, SMS, "+33611111111")[0]
    assert person == person_of(c, SMS, "+33622222222")[0]
    review = c.db.execute("SELECT review FROM persons WHERE id = ?", (person,)).fetchone()[0]
    assert "réunis par le seul nom « julie martin »" in review


def test_son_nom_vient_d_un_vrai_nom_pas_d_un_pseudo(tmp_path: Path) -> None:
    from twin.render import her_name

    c = Corpus(tmp_path / "corpus.db")
    for i, friend in enumerate(["Alice", "Bea", "Chloe"]):
        msn_file(c, f"f{i}", (friend,), ("Léa ~ zik",))
    add(c, "wa", [Author(WHATSAPP, "Julie", name="Julie", me=False),
                  Author(WHATSAPP, "Léa Martin", name="Léa Martin", me=True, me_reason="discussion à deux"),
                  Conversation(WHATSAPP, "Julie", members=("Julie", "Léa Martin")),
                  msg(WHATSAPP, "Julie", "Léa Martin", 0)])
    review = tmp_path / "personnes.yaml"
    resolve_people(c, review, TZ)
    assert her_name(c) == "Léa Martin"  # trois fichiers MSN contre un message : le pseudo ne gagne pas
    data = yaml.safe_load(review.read_text(encoding="utf-8"))
    data["elle"]["nom"] = "Léa Moreau"  # son vrai nom, dit à la main
    review.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    resolve_people(c, review, TZ)
    assert her_name(c) == "Léa Moreau"
