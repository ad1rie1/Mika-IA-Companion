"""Les vues d'inspection des gens, par leurs intentions.

- chaque vue se déclare, s'ouvre sur un noyau neuf sans lever, et répond à
  un paramètre inconnu par une note, jamais par une erreur ;
- le verdict d'identité s'explique pas à pas, et l'explication suit la
  politique : une opératrice authentifiée et une poignée anonyme n'obtiennent
  ni le même niveau ni la même raison ; une audience publique n'obtient
  jamais rien de privé ;
- un profil oublié s'affiche comme oublié ;
- le fil montre les messages et les questions restées sans réponse, borné.
"""

from __future__ import annotations

from mika.contracts import identity as identity_c
from mika.contracts import presence as presence_c
from mika.contracts import runtime as rt
from mika.contracts import social as social_c
from mika.kernel.events import Content, Origin
from mika.kernel.inspect import Fields, Note, Prose, Ref, Table
from mika.ports.llm import LLMResponse
from mika.runtime import inspection
from mika.sim.clock import run_virtual
from mika.vocab.privacy import Sensitivity
from tests.fixtures.mika import befriend, boot, build, connect, said

OWN_VIEWS = {
    ("identity", "personnes"): ("Personnes", ()),
    ("identity", "personne"): ("Une personne", ("handle",)),
    ("social", "liens"): ("Liens", ("person",)),
    ("presence", "presents"): ("Présents", ()),
    ("transcript", "fil"): ("Fil", ("handle", "q")),
}
LEVEL_FR = {Sensitivity.NONE: "rien sur autrui", Sensitivity.ANODYNE: "anodin", Sensitivity.PERSONAL: "personnel",
            Sensitivity.CONFIDENCE: "confidences"}
SUMMARY = "C'est quelqu'un qui adore le café noir et les chats."
ANON = "web_4f2a9c"


def respond(req):
    if req.role in ("extract", "profile", "compact"):
        return LLMResponse("{}")
    return LLMResponse("d'accord [EMOTION:happy:0.5]")


def show(kernel, owner, name, **params):
    spec = inspection.find(kernel, owner, name)
    assert spec is not None, f"{owner}/{name} n'est pas déclarée"
    return inspection.run_view(kernel, spec, params, when=lambda t: f"t{t}")


def cells(block):
    if isinstance(block, Table):
        return [c for row in block.rows for c in row] + [block.title, block.empty]
    if isinstance(block, Fields):
        return [c for pair in block.pairs for c in pair] + [block.title]
    if isinstance(block, Note | Prose):
        return [block.text]
    return []


def text(blocks) -> str:
    out = []
    for b in blocks:
        for c in cells(b):
            out.append(c.text if isinstance(c, Ref) else str(c))
    return "\n".join(out)


def failed(blocks) -> bool:
    return any(isinstance(b, Note) and (b.tone == "ko" or "a échoué" in b.text) for b in blocks)


def table(blocks, first_column: str) -> Table:
    return next(b for b in blocks if isinstance(b, Table) and b.columns[0] == first_column)


def titled(blocks, title: str) -> Table:
    return next(b for b in blocks if isinstance(b, Table) and b.title.startswith(title))


def row_of(t: Table, key: str) -> dict:
    for row in t.rows:
        head = row[0]
        if (head.text if isinstance(head, Ref) else head) == key or \
                (isinstance(head, Ref) and dict(head.params).get("handle") == key):
            return dict(zip(t.columns, row, strict=True))
    raise AssertionError(f"pas de ligne {key!r} dans {t.title or t.columns}")


def run(tmp_path, scenario, **kw):
    kernel, clock, _llm, _out = build(tmp_path, respond, **kw)

    async def main():
        await boot(kernel)
        try:
            return await scenario(kernel)
        finally:
            await kernel.stop()

    return run_virtual(clock, main)


async def say(kernel, p):
    got = await kernel.perceive(p)
    if got.reply is not None:
        await got.reply
    return got


async def live(kernel):
    """Une opératrice authentifiée et proche, et une poignée anonyme qui se
    dit Alice ; quelques messages ; un profil."""
    await connect(kernel, "user_1", "Alice", operator=True)
    await befriend(kernel, "user_1", "close")
    await connect(kernel, ANON, "", authenticated=False)
    await say(kernel, said("user_1", "salut Mika, tu as passé une bonne journée ?"))
    await say(kernel, said(ANON, "moi c'est Alice"))
    await kernel.mind.append([social_c.PROFILE_REVISED.draft(
        person="user_1", summary=Content.of(SUMMARY, level=int(Sensitivity.PERSONAL)), tone="avec douceur",
        interests=("le café",))], emitter="social", correlation="genese:profil", origin=Origin.GENESIS)


# ── Déclaration ───────────────────────────────────────────────────────────


def test_each_view_is_declared_with_its_title_and_params(tmp_path):
    async def scenario(kernel):
        return {(v.owner, v.name): (v.title, tuple(p for p, _label in v.params)) for v in inspection.views(kernel)}

    declared = run(tmp_path, scenario)
    for key, expected in OWN_VIEWS.items():
        assert declared.get(key) == expected, key


# ── Un noyau neuf ─────────────────────────────────────────────────────────


def test_every_view_opens_on_a_fresh_kernel(tmp_path):
    async def scenario(kernel):
        got = {key: show(kernel, *key) for key in OWN_VIEWS}
        # des paramètres qui ne désignent rien, ou qui ressemblent à du SQL
        got["personne inconnue"] = show(kernel, "identity", "personne", handle="tg_404")
        got["lien inconnu"] = show(kernel, "social", "liens", person="user_404")
        got["fil inconnu"] = show(kernel, "transcript", "fil", handle="web_404")
        got["recherche piégée"] = show(kernel, "transcript", "fil", q="%' OR 1=1 --_\\")
        return got

    got = run(tmp_path, scenario)
    for key, blocks in got.items():
        assert blocks and not failed(blocks), (key, blocks)
    assert table(got[("identity", "personnes")], "poignée").rows == ()
    assert table(got[("presence", "presents")], "poignée").rows == ()
    assert table(got[("social", "liens")], "personne").rows == ()
    assert "Choisissez une poignée" in text(got[("identity", "personne")])
    assert "Poignée inconnue : « tg_404 »" in text(got["personne inconnue"])
    assert "Aucun lien avec « user_404 »" in text(got["lien inconnu"])
    assert "Aucun message avec « web_404 »" in text(got["fil inconnu"])
    assert table(got["recherche piégée"], "n°").rows == ()


# ── Après un peu de vie ───────────────────────────────────────────────────


def test_the_people_list_says_who_is_who_and_what_each_would_hear(tmp_path):
    async def scenario(kernel):
        await live(kernel)
        frame = kernel.mind.frame()
        facts = {h: (frame.get(identity_c.DISCLOSURE((h, "web", False))),
                     frame.get(identity_c.DISCLOSURE((h, "web", True)))) for h in ("user_1", ANON)}
        return show(kernel, "identity", "personnes"), facts

    blocks, facts = run(tmp_path, scenario)
    assert not failed(blocks)
    people = table(blocks, "poignée")
    alice, anon = row_of(people, "user_1"), row_of(people, ANON)
    assert alice["nom"] == "Alice" and alice["confiance du canal"].startswith("authentifiée")
    assert alice["certitude"] == "1,00 (vérifiée)" and alice["propriétaire"] == "oui"
    assert anon["confiance du canal"].startswith("publique") and anon["certitude"] == "0,00 (inconnue)"
    assert anon["propriétaire"] == "non" and anon["revendique"] == "« Alice »"
    assert anon["parle pour"] == "elle-même"  # une affirmation seule ne lie rien
    # le niveau affiché est celui que la politique applique
    for handle, row in (("user_1", alice), (ANON, anon)):
        private, public = facts[handle]
        assert row["divulgation en privé"].startswith(LEVEL_FR[private.level])
        assert row["divulgation en public"].startswith(LEVEL_FR[public.level])
    assert alice["divulgation en privé"] == "confidences · sa fiche ouverte"
    assert anon["divulgation en privé"] == "anodin · sa fiche fermée"
    # une audience publique n'obtient jamais rien de privé, qui que ce soit
    for row in people.rows:
        public = dict(zip(people.columns, row, strict=True))["divulgation en public"]
        assert public == "anodin · sa fiche fermée"
    link = alice["poignée"]
    assert isinstance(link, Ref) and link.key == "identity/personne" and dict(link.params) == {"handle": "user_1"}
    assert "Alice" in text([b for b in blocks if isinstance(b, Fields)])  # parmi les propriétaires


def test_the_verdict_is_explained_and_differs_between_an_operator_and_an_anonymous_handle(tmp_path):
    async def scenario(kernel):
        await live(kernel)
        return show(kernel, "identity", "personne", handle="user_1"), show(kernel, "identity", "personne", handle=ANON)

    alice, anon = run(tmp_path, scenario)
    assert not failed(alice) and not failed(anon)

    steps = row_of(titled(alice, "Le verdict"), "certitude enregistrée")
    assert "session authentifiée" in steps["pourquoi"]
    assert row_of(titled(alice, "Le verdict"), "barre de divulgation")["pourquoi"] == "atteinte"
    opened = row_of(titled(alice, "Ce que ça ouvre"), "en privé")
    assert opened["sur autrui"] == "confidences" and "jusqu'aux confidences" in opened["pourquoi"]
    assert opened["sa propre fiche"].startswith("ouverte")

    steps = row_of(titled(anon, "Le verdict"), "certitude enregistrée")
    assert "rien ne prouve" in steps["pourquoi"]
    assert row_of(titled(anon, "Le verdict"), "certitude effective")["valeur"] == "0,00 (inconnue)"
    assert row_of(titled(anon, "Le verdict"), "barre de divulgation")["pourquoi"].startswith("pas atteinte")
    closed = row_of(titled(anon, "Ce que ça ouvre"), "en privé")
    assert closed["sur autrui"] == "anodin" and "canal public" in closed["pourquoi"]
    assert closed["sa propre fiche"].startswith("fermée")
    assert opened["pourquoi"] != closed["pourquoi"]

    # en public, même l'opératrice n'obtient rien de privé
    public = row_of(titled(alice, "Ce que ça ouvre"), "en public")
    assert public["sur autrui"] == "anodin" and public["si elle ou il est concerné"] == "anodin"
    assert "audience publique" in public["pourquoi"] and public["sa propre fiche"].startswith("fermée")

    # la revendication, sa cible, et le registre qui la garde
    assert "« Alice »" in text(anon) and "affirmation" in text(anon)
    claim = next(b for b in anon if isinstance(b, Fields) and b.title == "Revendication en cours")
    target = dict(claim.pairs)["personne visée"]
    assert isinstance(target, Ref) and dict(target.params) == {"handle": "user_1"}
    ledger = titled(anon, "Registre des preuves")
    assert len(ledger.rows) == 1 and ledger.rows[0][2] == "revendication"
    assert "vise Alice" in ledger.rows[0][3] and isinstance(ledger.rows[0][-1], Ref)
    assert titled(alice, "Registre des preuves").rows == ()
    # vers ses liens et son fil
    refs = [c for b in alice if isinstance(b, Fields) for _k, c in b.pairs if isinstance(c, Ref)]
    assert any(r.key == "social/liens" and dict(r.params) == {"person": "user_1"} for r in refs)
    assert any(r.key == "transcript/fil" and dict(r.params) == {"handle": "user_1"} for r in refs)


def test_links_show_closeness_rhythm_and_profile_and_a_forgotten_profile_shows_as_forgotten(tmp_path):
    async def scenario(kernel):
        await live(kernel)
        before = show(kernel, "social", "liens"), show(kernel, "social", "liens", person="user_1")
        await kernel.forget("user_1")
        after = show(kernel, "social", "liens"), show(kernel, "social", "liens", person="user_1")
        return before, after

    (listing, detail), (listing_after, detail_after) = run(tmp_path, scenario)
    for blocks in (listing, detail, listing_after, detail_after):
        assert not failed(blocks)
    alice = row_of(table(listing, "personne"), "user_1")
    assert alice["proximité"] == "une proche (déclarée)"
    assert "repli selon la proximité" in alice["rythme"]  # une seule journée : pas encore de rythme mesuré
    assert alice["dernier message reçu"].startswith("t")
    assert SUMMARY in alice["ce qu'elle en sait"]
    who = alice["personne"]
    assert isinstance(who, Ref) and who.key == "identity/personne" and dict(who.params) == {"handle": "user_1"}
    assert who.text == "Alice"
    anon = row_of(table(listing, "personne"), ANON)
    assert anon["ce qu'elle en sait"] == "pas encore de profil"
    assert "avec douceur" in text(detail) and SUMMARY in text(detail)

    assert row_of(table(listing_after, "personne"), "user_1")["ce qu'elle en sait"] == "(oublié)"
    assert "Ce qu'elle en sait : (oublié)" in text(detail_after)
    assert SUMMARY not in text(listing_after) + text(detail_after)


def test_presence_lists_live_connections_with_their_audience(tmp_path):
    async def scenario(kernel):
        await live(kernel)
        await kernel.mind.append([presence_c.CONNECTED.draft(
            handle="tg_77", channel="telegram", connection="tg-group", room="tg:-100", public=True,
            display_name="Bob")], emitter="presence", correlation="ws:tg", origin=Origin.EXTERNAL)
        return show(kernel, "presence", "presents")

    blocks = run(tmp_path, scenario)
    assert not failed(blocks)
    rows = table(blocks, "poignée")
    assert len(rows.rows) == 3
    assert row_of(rows, "user_1")["audience"] == "privée"
    assert row_of(rows, ANON)["audience"] == "publique (rien ne prouve qui écrit)"
    assert row_of(rows, "tg_77")["audience"] == "publique (salon « tg:-100 »)"
    assert row_of(rows, "user_1")["présente depuis"].startswith("t")
    assert row_of(rows, "user_1")["nom"] == "Alice"


def test_the_thread_shows_messages_filters_and_unanswered_questions(tmp_path):
    async def scenario(kernel):
        await live(kernel)
        # une question journalisée dont la réponse n'est pas encore partie
        await kernel.mind.append([rt.PERCEPTION_RECEIVED.draft(
            handle=ANON, channel="web", text=Content.of("tu es là ? " + "x" * 400))], emitter="runtime",
            correlation="perception:attente", origin=Origin.EXTERNAL)
        return (show(kernel, "transcript", "fil"), show(kernel, "transcript", "fil", handle=ANON),
                show(kernel, "transcript", "fil", q="Alice"))

    everything, anon, search = run(tmp_path, scenario)
    for blocks in (everything, anon, search):
        assert not failed(blocks)
    messages = table(everything, "n°")
    said_texts = [dict(zip(messages.columns, r, strict=True)) for r in messages.rows]
    assert any(r["texte"] == "salut Mika, tu as passé une bonne journée ?" and r["qui parle"] == "la personne"
               for r in said_texts)
    assert any(r["qui parle"] == "elle" and r["texte"] == "d'accord" for r in said_texts)  # la prosodie est retirée
    assert all(r["interne"] == "non" for r in said_texts)
    assert all(len(r["texte"]) <= 301 for r in said_texts)
    ids = [int(r["n°"].key) for r in said_texts]
    assert ids == sorted(ids, reverse=True)  # du plus récent au plus ancien
    waiting = titled(everything, "Questions sans réponse")
    assert len(waiting.rows) == 1 and waiting.rows[0][3].startswith("tu es là ?")
    assert any(r["réponse"] == "en attente" for r in said_texts)
    assert "questions sans réponse" in text(everything)

    only_anon = table(anon, "n°")
    handles = {dict(r[3].params)["handle"] for r in only_anon.rows}
    assert handles == {ANON}
    found = table(search, "n°")
    assert [r[5] for r in found.rows] == ["moi c'est Alice"]


def test_views_stay_bounded_in_a_crowd(tmp_path):
    crowd = [f"web_{i:04d}" for i in range(210)]

    async def scenario(kernel):
        await kernel.mind.append([presence_c.CONNECTED.draft(handle=h, channel="web", connection=f"c-{h}")
                                  for h in crowd], emitter="presence", correlation="ws:foule",
                                 origin=Origin.EXTERNAL)
        await kernel.mind.append([rt.PERCEPTION_RECEIVED.draft(handle=h, channel="web", text=Content.of(f"coucou {h}"))
                                  for h in crowd], emitter="runtime", correlation="perception:foule",
                                 origin=Origin.EXTERNAL)
        return {key: show(kernel, *key) for key in OWN_VIEWS}

    got = run(tmp_path, scenario)
    for blocks in got.values():
        assert not failed(blocks)
        assert all(len(b.rows) <= 200 for b in blocks if isinstance(b, Table))
    assert len(table(got[("identity", "personnes")], "poignée").rows) == 200
    assert "sur 210" in text(got[("identity", "personnes")])
    assert len(table(got[("presence", "presents")], "poignée").rows) == 200
    assert len(table(got[("social", "liens")], "personne").rows) == 200
    fil = got[("transcript", "fil")]
    assert len(table(fil, "n°").rows) == 100
    assert len(titled(fil, "Questions sans réponse").rows) == 100
    assert dict(next(b for b in fil if isinstance(b, Fields)).pairs)["questions sans réponse"] == 210
