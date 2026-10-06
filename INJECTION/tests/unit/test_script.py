"""Le script de l'avance rapide : retenir puis libérer, initiatives, salons, savoir d'archive, chapitres."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from twin.corpus import Corpus, SourceStats
from twin.people import resolve_people
from twin.records import WHATSAPP, Author, Conversation, Message
from twin.replay.script import build_script, steps
from twin.sessions import build_sessions
from twin.timing import Temps, to_us

TZ = ZoneInfo("Europe/Paris")
T = datetime(2019, 3, 12, 10, 0, tzinfo=TZ)


def at(minutes: float) -> Temps:
    return Temps.exact(to_us(T + timedelta(minutes=minutes)))


def corpus(tmp_path: Path, tier: str = "A") -> Corpus:
    c = Corpus(tmp_path / "corpus.db")
    privé = [  # (minutes, qui, texte)
        (0, "Léa", "coucou ça va ?"),  # elle ouvre : initiative
        (0.5, "Léa", "j'ai une news"),  # même rafale
        (3, "Julie", "oui et toi ?"),
        (3.5, "Léa", "trop bien !!"),  # réponse rapide
        (4, "Julie", "raconte"),
        (5, "Julie", "allez !!"),  # rafale de Julie
        (300, "Léa", "désolée j'étais en cours"),  # 5 h après, autre séance : réponse différée, libérée à son heure
        (3 * 24 * 60, "Julie", "tu es là ?"),  # trois jours plus tard…
        (6 * 24 * 60, "Léa", "pardon j'ai vu que maintenant"),  # … au-delà de 2 jours : une initiative
    ]
    items: list[Any] = [Author(WHATSAPP, "Julie", name="Julie Martin", me=False),
                        Author(WHATSAPP, "Léa", name="Léa", me=True),
                        Conversation(WHATSAPP, "Julie", members=("Julie", "Léa"))]
    items += [Message(WHATSAPP, "Julie", who, text, at(m), i) for i, (m, who, text) in enumerate(privé)]
    salon = [(1000, "Paul", "qui vient samedi ?"), (1001, "Léa", "moi !"), (1002, "Paul", "cool Léa"),
             (1003, "Julie", "moi aussi"), (1100, "Paul", "rdv 20h"), (1101, "Léa", "parfait")]
    items += [Author(WHATSAPP, "Paul", name="Paul Durand", me=False),
              Conversation(WHATSAPP, "Les copains", group=True, members=("Paul", "Léa", "Julie"))]
    items += [Message(WHATSAPP, "Les copains", who, text, at(m), 100 + i) for i, (m, who, text) in enumerate(salon)]
    with c.transaction():
        sid = c.begin_source("x", "x", "test", 1, 0, "now")
        c.add_items(sid, items, SourceStats())
    resolve_people(c, tmp_path / "personnes.yaml", TZ)
    build_sessions(c)
    c.db.execute("UPDATE sessions SET tier = ?", (tier,))
    her = [r["id"] for r in c.db.execute(
        "SELECT m.id FROM messages m JOIN participants pa ON pa.id = m.author JOIN persons p ON p.id = pa.person "
        "WHERE p.is_me = 1 ORDER BY m.t_point")]
    c.db.execute("CREATE TABLE IF NOT EXISTS annotations (session INTEGER, version INTEGER, tier TEXT, data TEXT, "
                 "model TEXT)")
    first = c.db.execute("SELECT MIN(id) FROM sessions").fetchone()[0]
    c.db.execute("INSERT INTO annotations VALUES (?, 1, 'A', ?, '')", (first, json.dumps({"emotions": [
        {"id": her[0], "emotion": "excited", "intensite": 0.5}, {"id": her[1], "emotion": "excited", "intensite": 0.9}],
        "souvenirs": [{"texte": "x", "messages": []}]})))
    c.db.commit()
    return c


def all_steps(c: Corpus) -> list[tuple[int, int, str, dict[str, Any]]]:
    return list(steps(c))


def test_retenir_puis_liberer_et_initiatives(tmp_path: Path) -> None:
    c = corpus(tmp_path)
    assert build_script(c, her_names=("Léa",)).steps > 0
    privé = [s for s in all_steps(c) if s[3].get("room") is None and s[2] in ("in", "her")]
    kinds = [(k, d.get("kind", "")) for _, _, k, d in privé]
    assert kinds == [("her", "initiative"), ("in", ""), ("her", "reply"), ("in", ""), ("in", ""), ("her", "reply"),
                     ("in", ""), ("her", "initiative")]
    first = privé[0][3]
    assert first["text"] == "coucou ça va ?\nj'ai une news [EMOTION:excited:0.90]"
    assert first["target"].startswith("ext_julie")
    # la rafale de Julie est retenue jusqu'à sa réponse, cinq heures plus tard
    burst = [privé[3][3], privé[4][3]]
    late = privé[5]
    assert all(b["release_at"] == late[1] for b in burst)
    assert late[3]["reply_to"] == [b["archive"][0] for b in burst]
    # trois jours sans réponse : rien n'est retenu, sa parole suivante est une initiative
    assert privé[6][3]["release_at"] is None and privé[7][3]["kind"] == "initiative"
    assert [s[1] for s in all_steps(c)] == sorted(s[1] for s in all_steps(c))


def test_salon_adresse_et_parole_spontanee(tmp_path: Path) -> None:
    c = corpus(tmp_path)
    build_script(c, her_names=("Léa",))
    salon = [s[3] | {"_k": s[2]} for s in all_steps(c) if s[3].get("room")]
    paul_q, lea_moi, paul_cool, julie, paul_rdv, lea_parfait = salon
    assert not paul_q["addressed"] and lea_moi["kind"] == "room"  # personne ne l'a nommée : parole spontanée
    assert paul_cool["addressed"] and julie["addressed"]  # nommée / juste après elle
    assert not paul_rdv["addressed"]  # 97 min plus tard, sans la nommer
    assert lea_parfait["kind"] == "room" and lea_parfait["target"].startswith("ext_paul")


def test_seance_non_rejouee_absente_mais_son_savoir_reste(tmp_path: Path) -> None:
    c = corpus(tmp_path, tier="C")
    build_script(c)
    kinds = {s[2] for s in all_steps(c)}
    assert kinds == {"knowledge"}


def _script_of(tmp_path: Path, messages: list[tuple[float, str, str]], members: tuple[str, ...] = ("Zoé", "Léa")):
    c = Corpus(tmp_path / "c.db")
    items: list[Any] = [Author(WHATSAPP, "Zoé", name="Zoé Petit", me=False), Author(WHATSAPP, "Léa", name="Léa", me=True),
                        Conversation(WHATSAPP, "Zoé", members=members)]
    items += [Message(WHATSAPP, "Zoé", who, text, at(m), i) for i, (m, who, text) in enumerate(messages)]
    with c.transaction():
        sid = c.begin_source("x", "x", "test", 1, 0, "now")
        c.add_items(sid, items, SourceStats())
    resolve_people(c, tmp_path / "p.yaml", TZ)
    build_sessions(c)
    c.db.execute("UPDATE sessions SET tier = 'R'")
    build_script(c, her_names=("Léa",))
    return [(k, d) for _, _, k, d in steps(c)]


def test_une_relance_apres_deux_jours_repart_de_zero(tmp_path: Path) -> None:
    """Lundi « t'es dispo samedi ? », jeudi « allô ?? », réponse 10 min après : elle répond au « allô ?? »."""
    got = _script_of(tmp_path, [(0, "Zoé", "t'es dispo samedi ?"), (3 * 24 * 60, "Zoé", "allô ??"),
                                (3 * 24 * 60 + 10, "Léa", "pardon ! oui samedi")])
    monday, thursday, her = got
    assert her[1]["kind"] == "reply" and her[1]["reply_to"] == thursday[1]["archive"]
    assert monday[1]["release_at"] is None and thursday[1]["release_at"] is not None


def test_une_relance_en_pleine_conversation_n_est_pas_une_ouverture(tmp_path: Path) -> None:
    got = _script_of(tmp_path, [(0, "Zoé", "trop bien"), (1, "Léa", "hein ?"), (30, "Léa", "au fait tu sais quoi")])
    kinds = [d.get("kind") for k, d in got if k == "her"]
    assert kinds == ["reply", "continue"]


def test_elle_ecrit_a_quelqu_un_qui_n_a_jamais_repondu(tmp_path: Path) -> None:
    """Un SMS d'anniversaire resté sans réponse : le destinataire vient des membres de la conversation."""
    got = _script_of(tmp_path, [(0, "Léa", "joyeux anniversaire !!")])
    assert len(got) == 1 and got[0][1]["kind"] == "initiative" and got[0][1]["target"].startswith("ext_zoe")
