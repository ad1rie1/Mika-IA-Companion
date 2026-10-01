"""La console des gens, par ses intentions.

- les personnes et les adresses ont leur fiche : une adresse reliée renvoie à
  sa personne (clé canonique), la fiche d'une personne réunit ses adresses ;
  la recherche trouve par nom et par adresse ;
- chaque vue et chaque onglet se déclarent, s'ouvrent sur un noyau neuf sans
  lever, et répondent à une clé inconnue par une note, jamais par une erreur ;
- le verdict d'identité s'explique pas à pas, et l'explication suit la
  politique : une opératrice authentifiée et une adresse anonyme n'obtiennent
  ni le même niveau ni la même raison ; une audience publique n'obtient
  jamais rien de privé ;
- les actions d'opérateur (relier, délier, preuve, proximité) journalisent
  les événements de leur faculté comme venant de l'extérieur, avec un audit
  qui nomme l'opérateur ; un formulaire invalide ou une action sans objet
  est refusé champ par champ, en français ; une action sans objet n'est même
  pas offerte ;
- un profil oublié s'affiche comme oublié ;
- le fil montre les messages par pages (curseur), les filtres, et les
  questions restées sans réponse, compte à l'appui.
"""

from __future__ import annotations

from mika.contracts import identity as identity_c
from mika.contracts import presence as presence_c
from mika.contracts import runtime as rt
from mika.contracts import social as social_c
from mika.kernel.events import Content, Origin
from mika.kernel.inspect import (
    ActionSlot,
    Badge,
    Disclosure,
    Fields,
    Found,
    Grid,
    Head,
    Meter,
    Note,
    Prose,
    Ref,
    Row,
    Section,
    Stats,
    Swatch,
    Table,
    Text,
    When,
)
from mika.ports.llm import LLMResponse
from mika.runtime import inspection
from mika.runtime.inspection import Inspection
from mika.runtime.operations import offered, perform
from mika.sim.clock import run_virtual
from mika.vocab.privacy import Sensitivity
from tests.fixtures.mika import befriend, boot, build, connect, said

#: (propriétaire, nom) → (titre, paramètres, destination)
OWN_VIEWS = {
    ("identity", "personnes"): ("Personnes", ("q",), "personnes"),
    ("identity", "annuaire"): ("Adresses", ("q", "confiance"), "identites"),
    ("identity", "revendications"): ("Revendications", (), "identites"),
    ("identity", "politique"): ("Politique", (), "identites"),
    ("identity", "personne"): ("Une adresse (ancienne page)", ("handle",), ""),
    ("social", "liens"): ("Liens", ("q", "proximite", "person"), "personnes"),
    ("presence", "presents"): ("Présents", (), "personnes"),
    ("transcript", "messages"): ("Messages", ("handle", "q", "role"), "fil"),
    ("transcript", "questions"): ("Questions sans réponse", (), "fil"),
}
#: les facultés de ce fichier (les autres ajoutent leurs onglets en parallèle, testés ailleurs)
MINE = frozenset({"identity", "social", "presence", "transcript"})
PERSON_TABS = [("identity", "synthese"), ("identity", "adresses"), ("social", "lien"), ("transcript", "echanges")]
HANDLE_TABS = [("identity", "verdict"), ("identity", "revendication"), ("identity", "preuves"),
               ("identity", "autres"), ("transcript", "fil")]
LEVEL_FR = {Sensitivity.NONE: "rien sur autrui", Sensitivity.ANODYNE: "anodin", Sensitivity.PERSONAL: "personnel",
            Sensitivity.CONFIDENCE: "confidences"}
SUMMARY = "C'est quelqu'un qui adore le café noir et les chats."
ANON = "web_4f2a9c"


def respond(req):
    if req.role in ("extract", "profile", "compact"):
        return LLMResponse("{}")
    return LLMResponse("d'accord [EMOTION:happy:0.5]")


def when(at: int) -> str:
    return f"t{at}"


def show(kernel, owner, name, *, subject: str = "", **params):
    spec = inspection.find(kernel, owner, name)
    assert spec is not None, f"{owner}/{name} n'est pas déclarée"
    return Inspection(kernel).run(spec, params, when, subject=subject)


def plain(cell) -> str:
    if isinstance(cell, Ref | Badge | Text | Meter | Swatch):
        return cell.text
    if isinstance(cell, When):
        return f"@{cell.at}"
    return "—" if cell is None else str(cell)


def flatten(blocks) -> list:
    out = []
    for b in blocks:
        out.append(b)
        if isinstance(b, Section | Grid | Disclosure):
            out += flatten(b.items)
        if isinstance(b, Table):
            out += flatten([x for r in b.rows if isinstance(r, Row) for x in r.detail])
    return out


def row_cells(row) -> tuple:
    return row.cells if isinstance(row, Row) else row


def cells(block):
    if isinstance(block, Table):
        return [c for row in block.rows for c in row_cells(row)] + [block.title, block.empty]
    if isinstance(block, Fields):
        return [c for pair in block.pairs for c in pair] + [block.title]
    if isinstance(block, Stats):
        return [c for s in block.items for c in (s.label, s.value, s.sub)]
    if isinstance(block, Note | Prose):
        return [block.title, block.text]
    return []


def text(blocks) -> str:
    return "\n".join(plain(c) for b in flatten(blocks) for c in cells(b))


def failed(blocks) -> bool:
    return any(isinstance(b, Note) and (b.tone in ("ko", "danger") or "a échoué" in b.text) for b in flatten(blocks))


def tables(blocks) -> list[Table]:
    return [b for b in flatten(blocks) if isinstance(b, Table)]


def table(blocks, first_column: str) -> Table:
    return next(t for t in tables(blocks) if plain_label(t.columns[0]) == first_column)


def titled(blocks, title: str) -> Table:
    return next(t for t in tables(blocks) if t.title.startswith(title))


def plain_label(column) -> str:
    return getattr(column, "label", column)


def as_dict(t: Table, row) -> dict:
    return {plain_label(k): v for k, v in zip(t.columns, row_cells(row), strict=True)}


def row_of(t: Table, key: str) -> dict:
    for row in t.rows:
        head = row_cells(row)[0]
        if plain(head) == key or (isinstance(head, Ref) and head.key.split("/", 1)[-1] == key):
            return as_dict(t, row)
    raise AssertionError(f"pas de ligne {key!r} dans {t.title or t.columns}")


def form(**values: str) -> dict[str, list[str]]:
    return {"_champs": [k for k in values if not k.startswith("_")], **{k: [v] for k, v in values.items()}}


def events(kernel, name: str) -> list:
    return [kernel.mind.decode(s) for s in kernel.mind.store.read(types={name})]


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
    """Une opératrice authentifiée et proche, et une adresse anonyme qui se
    dit Alice ; quelques messages ; un profil."""
    await connect(kernel, "user_1", "Alice", operator=True)
    await befriend(kernel, "user_1", "close")
    await connect(kernel, ANON, "", authenticated=False)
    await say(kernel, said("user_1", "salut Mika, tu as passé une bonne journée ?"))
    await say(kernel, said(ANON, "moi c'est Alice"))
    await kernel.mind.append([social_c.PROFILE_REVISED.draft(
        person="user_1", summary=Content.of(SUMMARY, level=int(Sensitivity.PERSONAL)), tone="avec douceur",
        interests=("le café",))], emitter="social", correlation="genese:profil", origin=Origin.GENESIS)


def all_tabs(kernel, key_person: str, key_handle: str) -> dict:
    insp = Inspection(kernel)
    out = {}
    for spec in insp.tabs("person"):
        if spec.owner in MINE:
            out[("person", spec.owner, spec.name)] = insp.run(spec, {}, when, subject=key_person)
    for spec in insp.tabs("handle"):
        if spec.owner in MINE:
            out[("handle", spec.owner, spec.name)] = insp.run(spec, {}, when, subject=key_handle)
    return out


# ── Déclaration ───────────────────────────────────────────────────────────


def test_each_view_and_tab_is_declared_in_its_place(tmp_path):
    async def scenario(kernel):
        insp = Inspection(kernel)
        views = {(v.owner, v.name): (v.title, tuple(p.name for p in v.typed), v.section)
                 for v in insp.views() if not v.subject}
        return (views, [(v.owner, v.name) for v in insp.tabs("person")],
                [(v.owner, v.name) for v in insp.tabs("handle")],
                insp.subject("person"), insp.subject("handle"), inspection.find(kernel, "identity", "personne"))

    views, person_tabs, handle_tabs, person, handle, legacy = run(tmp_path, scenario)
    for key, expected in OWN_VIEWS.items():
        assert views.get(key) == expected, key
    assert legacy.hidden
    # les onglets des autres facultés s'intercalent, les nôtres restent dans cet ordre
    assert [t for t in person_tabs if t in PERSON_TABS] == PERSON_TABS
    assert person_tabs[:2] == PERSON_TABS[:2]
    assert handle_tabs == HANDLE_TABS
    assert (person.label, person.plural, person.forgettable) == ("Personne", "Personnes", True)
    assert (handle.label, handle.plural, handle.forgettable) == ("Adresse", "Adresses", False)
    assert person.search is not None and handle.search is not None


# ── Un noyau neuf ─────────────────────────────────────────────────────────


def test_every_view_and_tab_opens_on_a_fresh_kernel(tmp_path):
    async def scenario(kernel):
        insp = Inspection(kernel)
        got = {key: show(kernel, *key) for key in OWN_VIEWS}
        # des paramètres qui ne désignent rien, ou qui ressemblent à du SQL
        got["personne inconnue"] = show(kernel, "identity", "personne", handle="tg_404")
        got["lien inconnu"] = show(kernel, "social", "liens", person="user_404")
        got["fil inconnu"] = show(kernel, "transcript", "messages", handle="web_404")
        got["recherche piégée"] = show(kernel, "transcript", "messages", q="%' OR 1=1 --_\\")
        got["filtre inconnu"] = show(kernel, "transcript", "messages", role="personne")
        for kind in ("person", "handle"):
            for spec in (s for s in insp.tabs(kind) if s.owner in MINE):
                got[(kind, spec.owner, spec.name, "")] = insp.run(spec, {}, when, subject="")
                got[(kind, spec.owner, spec.name, "?")] = insp.run(spec, {}, when, subject="tg_404")
        heads = {k: insp.head(k, "tg_404", when) for k in ("person", "handle")}
        heads["name"] = insp.head("person", "name:personne", when)
        heads["vide"] = insp.head("person", "", when)
        searches = {k: insp.search(k, "") for k in ("person", "handle")}
        return got, heads, searches

    got, heads, searches = run(tmp_path, scenario)
    for key, blocks in got.items():
        assert blocks and not failed(blocks), (key, blocks)
    assert table(got[("identity", "annuaire")], "adresse").rows == ()
    assert table(got[("identity", "personnes")], "personne").rows == ()
    assert table(got[("presence", "presents")], "personne").rows == ()
    assert table(got[("social", "liens")], "personne").rows == ()
    assert titled(got[("identity", "politique")], "Les canaux").rows
    assert "Choisissez une adresse" in text(got[("identity", "personne")])
    assert "Adresse inconnue : « tg_404 »" in text(got["personne inconnue"])
    assert "Aucun lien avec « user_404 »" in text(got["lien inconnu"])
    assert "Aucun message avec « web_404 »" in text(got["fil inconnu"])
    assert table(got["recherche piégée"], "n°").rows == ()
    assert "« personne » inconnu" in text(got["filtre inconnu"])  # une valeur inconnue est dite, pas une erreur
    assert all(v is None for v in heads.values())
    assert searches == {"person": [], "handle": []}


# ── Les fiches ────────────────────────────────────────────────────────────


def test_a_person_has_a_fiche_that_gathers_her_handles(tmp_path):
    async def scenario(kernel):
        await live(kernel)
        insp = Inspection(kernel)
        before = insp.head("person", ANON, when), insp.head("person", "user_1", when)
        linked = await perform(kernel, "identity.relier", form(person="Alice"), by="user_1", subject=ANON,
                               nonce="r1")
        after = {k: insp.head("person", k, when) for k in (ANON, "user_1")}
        handle = insp.head("handle", ANON, when)
        found = {q: insp.search("person", q) for q in ("ali", "4F2A", "zorro")}
        found_handles = insp.search("handle", "4f2a")
        return before, linked, after, handle, found, found_handles, all_tabs(kernel, "user_1", ANON)

    (anon_before, alice_before), linked, after, handle, found, found_handles, tabs = run(tmp_path, scenario)
    assert isinstance(alice_before, Head) and alice_before.key == "user_1" and alice_before.title == "Alice"
    assert anon_before.key == ANON  # pas encore reliée : elle parle pour elle-même
    assert {b.text for b in alice_before.badges} >= {"propriétaire", "non liée", "en privé : confidences"}
    assert alice_before.subtitle.startswith("Une proche, et sa propriétaire")
    assert len(alice_before.facts) <= 6 and dict(alice_before.facts)["adresses"] == 1
    assert alice_before.aliases == ("user_1",)

    assert linked.ok
    # une adresse reliée renvoie à sa personne (la console y redirige)
    assert after[ANON].key == "user_1" and after["user_1"].key == "user_1"
    assert after["user_1"].aliases == tuple(sorted(("user_1", ANON)))
    assert "liée · 2 adresses" in {b.text for b in after["user_1"].badges}
    assert isinstance(handle, Head) and handle.key == ANON and "Parle pour Alice" in handle.subtitle
    assert {b.text for b in handle.badges} >= {"publique", "liée"}

    assert [f.key for f in found["ali"]] == ["user_1"] and isinstance(found["ali"][0], Found)
    assert [f.key for f in found["4F2A"]] == ["user_1"]  # par une de ses adresses
    assert found["zorro"] == []
    assert [f.key for f in found_handles] == [ANON]

    for key, blocks in tabs.items():
        assert blocks and not failed(blocks), key
    synthese = tabs[("person", "identity", "synthese")]
    handles = titled(tabs[("person", "identity", "adresses")], "Ses adresses")  # la table vit dans son onglet
    assert {row_cells(r)[0].key for r in handles.rows} == {"handle/user_1", f"handle/{ANON}"}
    assert all(isinstance(r, Row) and r.href.kind == "subject" for r in handles.rows)
    pointer = next(b for b in synthese if isinstance(b, Fields) and b.title == "Ses adresses")
    assert pointer.pairs[0][1].params == (("onglet", "adresses"),)  # la synthèse y renvoie, sans la répéter
    assert not any(isinstance(b, Table) and b.title == "Ses adresses" for b in synthese)
    assert row_of(titled(synthese, "Ce que ça ouvre"), "en privé")["sur autrui"] == "confidences"
    others = tabs[("handle", "identity", "autres")]
    assert [row_cells(r)[0].key for r in titled(others, "Les autres adresses").rows] == ["handle/user_1"]


def test_the_verdict_is_explained_and_differs_between_an_operator_and_an_anonymous_handle(tmp_path):
    async def scenario(kernel):
        await live(kernel)
        return (show(kernel, "identity", "verdict", subject="user_1"), show(kernel, "identity", "verdict", subject=ANON),
                show(kernel, "identity", "revendication", subject=ANON),
                show(kernel, "identity", "preuves", subject=ANON), show(kernel, "identity", "preuves", subject="user_1"),
                show(kernel, "identity", "personne", handle=ANON))

    alice, anon, claim, ledger_anon, ledger_alice, legacy = run(tmp_path, scenario)
    for blocks in (alice, anon, claim, ledger_anon, ledger_alice, legacy):
        assert not failed(blocks)

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

    # la revendication, sa cible, ce qui manque, et le registre qui la garde
    current = next(b for b in claim if isinstance(b, Fields) and b.title == "Revendication en cours")
    pairs = dict(current.pairs)
    assert pairs["nom revendiqué"] == "« Alice »" and "affirmation" in pairs["preuves déjà comptées"]
    assert isinstance(pairs["personne visée"], Ref) and pairs["personne visée"].key == "person/user_1"
    assert isinstance(pairs["vers la barre"], Meter) and pairs["vers la barre"].ratio < 1
    assert "Pour la confirmer" in text(claim)
    ledger = titled(ledger_anon, "Registre des preuves")
    assert len(ledger.rows) == 1
    entry = as_dict(ledger, ledger.rows[0])
    assert plain(entry["sorte"]) == "revendication" and "vise Alice" in entry["détail"]
    assert isinstance(entry["message"], Ref) and isinstance(entry["quand"], When)
    assert titled(ledger_alice, "Registre des preuves").rows == ()
    # l'ancienne page d'une adresse mène aux fiches
    refs = [c for b in legacy if isinstance(b, Fields) for _k, c in b.pairs if isinstance(c, Ref)]
    assert Ref.subject("handle", ANON, ANON).key in {r.key for r in refs}
    assert any(r.key == f"person/{ANON}" for r in refs)


def test_the_lists_say_who_is_who_and_what_each_would_hear(tmp_path):
    async def scenario(kernel):
        await live(kernel)
        frame = kernel.mind.frame()
        facts = {h: (frame.get(identity_c.DISCLOSURE((h, "web", False))),
                     frame.get(identity_c.DISCLOSURE((h, "web", True)))) for h in ("user_1", ANON)}
        return (show(kernel, "identity", "annuaire"), show(kernel, "identity", "annuaire", confiance="compte"),
                show(kernel, "identity", "personnes"), show(kernel, "identity", "personnes", q="alice"),
                show(kernel, "identity", "politique"), facts)

    directory, accounts, listing, searched, policy, facts = run(tmp_path, scenario)
    for blocks in (directory, accounts, listing, searched, policy):
        assert not failed(blocks)
    handles = table(directory, "adresse")
    alice, anon = row_of(handles, "user_1"), row_of(handles, ANON)
    # le nom et par où, pas la clé : elle reste en détail
    assert plain(alice["adresse"]) == "Alice · compte opérateur" and plain(alice["clé"]) == "user_1"
    assert plain(anon["adresse"]) == "web, sans nom" and plain(anon["clé"]) == ANON
    assert plain(alice["confiance du canal"]).startswith("authentifiée")
    assert alice["certitude"] == "1,00 (vérifiée)" and alice["propriétaire"] == "oui"
    assert plain(anon["confiance du canal"]).startswith("publique") and anon["certitude"] == "0,00 (inconnue)"
    assert anon["propriétaire"] == "non" and anon["revendique"] == "« Alice »"
    assert anon["parle pour"].key == f"person/{ANON}"  # une affirmation seule ne lie rien
    for handle, row in (("user_1", alice), (ANON, anon)):
        private, public = facts[handle]
        assert row["divulgation en privé"].startswith(LEVEL_FR[private.level])
        assert row["divulgation en public"].startswith(LEVEL_FR[public.level])
    assert alice["divulgation en privé"] == "confidences · sa fiche ouverte"
    assert anon["divulgation en privé"] == "anodin · sa fiche fermée"
    for row in handles.rows:  # une audience publique n'obtient jamais rien de privé
        assert as_dict(handles, row)["divulgation en public"] == "anodin · sa fiche fermée"
    assert all(isinstance(r, Row) and r.href.key == f"handle/{plain(as_dict(handles, r)['clé'])}"
               for r in handles.rows)
    assert table(accounts, "adresse").rows == ()  # aucune adresse de compte

    people = table(listing, "personne")
    assert {row_cells(r)[0].key for r in people.rows} == {"person/user_1", f"person/{ANON}"}
    assert plain(row_of(people, "user_1")["proximité"]) == "une proche"
    assert [row_cells(r)[0].key for r in table(searched, "personne").rows] == ["person/user_1"]

    # la politique est lue, pas recopiée
    channels = titled(policy, "Les canaux")
    assert len(channels.rows) == 4 and "Calibration vérifiée" in text(policy)


def test_the_claims_badge_counts_pending_claims(tmp_path):
    async def scenario(kernel):
        insp = Inspection(kernel)
        spec = inspection.find(kernel, "identity", "revendications")
        counts = [insp.badge(spec)]
        await live(kernel)
        counts.append(insp.badge(spec))
        await connect(kernel, "web_b0b", "", authenticated=False)
        await say(kernel, said("web_b0b", "moi c'est Alice"))
        counts.append(insp.badge(spec))
        await perform(kernel, "identity.preuve", form(kind=identity_c.DENIED, name="Alice"), by="user_1",
                      subject="web_b0b", nonce="d1")
        counts.append(insp.badge(spec))
        return counts, show(kernel, "identity", "revendications")

    counts, blocks = run(tmp_path, scenario)
    assert counts == [None, (1, ""), (2, ""), (1, "")]
    claims = table(blocks, "adresse")
    assert len(claims.rows) == 1 and row_cells(claims.rows[0])[0].key == f"handle/{ANON}"
    assert claims.rows[0].href.params == (("onglet", "revendication"),)


# ── Les actions d'opérateur ───────────────────────────────────────────────


def test_linking_and_unlinking_a_handle_is_journaled_and_audited(tmp_path):
    async def scenario(kernel):
        await live(kernel)
        registry = kernel.registry
        out = {"offered before": {k: offered(kernel, registry.actions[k], ANON)
                                  for k in ("identity.relier", "identity.delier", "identity.preuve")}}
        out["empty"] = await perform(kernel, "identity.relier", form(person=""), by="user_1", subject=ANON, nonce="a")
        out["unknown"] = await perform(kernel, "identity.relier", form(person="Zorro"), by="user_1", subject=ANON,
                                       nonce="b")
        out["self"] = await perform(kernel, "identity.relier", form(person=ANON), by="user_1", subject=ANON,
                                    nonce="c")
        out["ok"] = await perform(kernel, "identity.relier", form(person="Alice"), by="user_1", subject=ANON,
                                  nonce="d")
        out["again"] = await perform(kernel, "identity.relier", form(person="user_1"), by="user_1", subject=ANON,
                                     nonce="e")
        out["view linked"] = kernel.mind.frame().get(identity_c.IDENTITY(ANON))
        out["offered after"] = offered(kernel, registry.actions["identity.delier"], ANON)
        out["unlink"] = await perform(kernel, "identity.delier", form(), by="user_1", subject=ANON, nonce="f")
        out["view unlinked"] = kernel.mind.frame().get(identity_c.IDENTITY(ANON))
        out["unlink again"] = await perform(kernel, "identity.delier", form(), by="user_1", subject=ANON, nonce="g")
        out["linked"] = events(kernel, identity_c.LINKED.name)
        out["audit"] = events(kernel, rt.OPERATED.name)
        out["ledger"] = show(kernel, "identity", "preuves", subject=ANON)
        return out

    out = run(tmp_path, scenario)
    assert out["offered before"] == {"identity.relier": True, "identity.delier": False, "identity.preuve": True}
    assert not out["empty"].ok and "trop court" in out["empty"].errors["person"]
    assert not out["unknown"].ok and "Aucune personne connue sous « Zorro »" in out["unknown"].errors["person"]
    assert not out["self"].ok and "elle-même" in out["self"].errors["person"]
    assert out["ok"].ok and "parle désormais pour Alice" in out["ok"].message
    assert not out["again"].ok and "déjà" in out["again"].errors["person"]
    assert out["view linked"].bound and out["view linked"].person == "user_1"
    assert out["offered after"]
    assert out["unlink"].ok and not out["view unlinked"].bound
    assert not out["unlink again"].ok  # plus rien à délier : l'action n'est plus offerte
    linked = out["linked"]
    assert [(e.data.handle, e.data.person) for e in linked] == [(ANON, "user_1"), (ANON, None)]
    assert all(e.origin is Origin.EXTERNAL and e.data.by == "operator" for e in linked)
    audit = [(e.data.action, e.data.outcome, e.data.by, e.data.subject) for e in out["audit"]]
    assert ("identity.relier", "done", "user_1", ANON) in audit
    assert ("identity.relier", "refused", "user_1", ANON) in audit
    assert ("identity.delier", "done", "user_1", ANON) in audit
    done = next(e for e in out["audit"] if e.data.action == "identity.relier" and e.data.outcome == "done")
    assert done.data.seqs == (linked[0].seq,)
    # le registre de l'adresse nomme l'opératrice
    ledger = titled(out["ledger"], "Registre des preuves")
    by = [as_dict(ledger, r)["par"] for r in ledger.rows if plain(as_dict(ledger, r)["sorte"]) == "liaison"]
    assert by == ["un opérateur (user_1)", "un opérateur (user_1)"]


def test_operator_evidence_is_weighed_like_any_other(tmp_path):
    async def scenario(kernel):
        await live(kernel)
        out = {"offered alice": offered(kernel, kernel.registry.actions["identity.preuve"], "user_1")}
        out["unknown kind"] = await perform(kernel, "identity.preuve", form(kind="authenticated"), by="user_1",
                                            subject=ANON, nonce="a")
        out["long note"] = await perform(kernel, "identity.preuve", form(kind=identity_c.VOUCHED, note="x" * 300),
                                         by="user_1", subject=ANON, nonce="b")
        out["vouch"] = await perform(kernel, "identity.preuve", form(kind=identity_c.VOUCHED, note="je la connais"),
                                     by="user_1", subject=ANON, nonce="c")
        out["view"] = kernel.mind.frame().get(identity_c.IDENTITY(ANON))
        out["vouch again"] = await perform(kernel, "identity.preuve", form(kind=identity_c.VOUCHED), by="user_1",
                                           subject=ANON, nonce="d")
        out["deny other"] = await perform(kernel, "identity.preuve", form(kind=identity_c.DENIED, name="Bob"),
                                          by="user_1", subject=ANON, nonce="e")
        out["deny nameless"] = await perform(kernel, "identity.preuve", form(kind=identity_c.DENIED), by="user_1",
                                             subject=ANON, nonce="f")
        out["deny"] = await perform(kernel, "identity.preuve", form(kind=identity_c.DENIED, name="alice"),
                                    by="user_1", subject=ANON, nonce="g")
        out["denied view"] = kernel.mind.frame().get(identity_c.IDENTITY(ANON))
        # sur un compte (Telegram), affirmation + garantie atteignent la barre : l'adresse est reliée
        await say(kernel, said("tg_5", "moi c'est Alice", channel="telegram"))
        out["tg vouch"] = await perform(kernel, "identity.preuve", form(kind=identity_c.VOUCHED), by="user_1",
                                        subject="tg_5", nonce="h")
        out["tg view"] = kernel.mind.frame().get(identity_c.IDENTITY("tg_5"))
        out["evidence"] = events(kernel, identity_c.EVIDENCE.name)
        return out

    out = run(tmp_path, scenario)
    assert not out["offered alice"]  # une session authentifiée : aucune preuve n'y change rien
    assert not out["unknown kind"].ok and "choix inconnu" in out["unknown kind"].errors["kind"]
    assert not out["long note"].ok and "200" in out["long note"].errors["note"]
    assert out["vouch"].ok and "certitude de la revendication : 0,20" in out["vouch"].message
    # une garantie pèse ce que dit la politique : en public, elle ne franchit pas la barre seule
    assert not out["view"].bound and 0.5 < out["view"].claim_certainty < 0.7
    assert not out["vouch again"].ok and "qu'une fois" in out["vouch again"].errors["kind"]
    assert not out["deny other"].ok and "ne connaît pas cette adresse sous ce nom" in out["deny other"].errors["name"]
    assert not out["deny nameless"].ok and out["deny nameless"].errors["name"] == "Indique le nom démenti."
    assert out["deny"].ok and not out["denied view"].claim
    assert out["tg vouch"].ok and "confirmée : elle parle désormais pour Alice" in out["tg vouch"].message
    assert out["tg view"].bound and out["tg view"].person == "user_1" and 0.7 <= out["tg view"].certainty < 0.85
    ops = [e for e in out["evidence"] if e.data.by == "operator"]
    assert [(e.data.kind, e.data.note) for e in ops] == [(identity_c.VOUCHED, "je la connais"),
                                                         (identity_c.DENIED, ""), (identity_c.VOUCHED, "")]
    assert all(e.origin is Origin.EXTERNAL for e in ops)


def test_the_operator_sets_closeness_from_the_person_fiche(tmp_path):
    async def scenario(kernel):
        await live(kernel)
        out = {"tab": show(kernel, "social", "lien", subject="user_1")}
        spec = kernel.registry.actions["social.proximite"]
        out["offered"] = {k: offered(kernel, spec, k) for k in ("user_1", ANON, "anon_1", "name:bob")}
        out["bad"] = await perform(kernel, "social.proximite", form(closeness="meilleure amie"), by="user_1",
                                   subject="user_1", nonce="a")
        out["same"] = await perform(kernel, "social.proximite", form(closeness="close"), by="user_1",
                                    subject="user_1", nonce="b")
        out["friend"] = await perform(kernel, "social.proximite", form(closeness="friend"), by="user_1",
                                      subject="user_1", nonce="c")
        out["level"] = kernel.mind.frame().get(social_c.CLOSENESS("user_1"))
        out["auto"] = await perform(kernel, "social.proximite", form(closeness="auto"), by="user_1",
                                    subject="user_1", nonce="d")
        out["lived"] = kernel.mind.frame().get(social_c.CLOSENESS("user_1"))
        await perform(kernel, "identity.relier", form(person="user_1"), by="user_1", subject=ANON, nonce="e")
        out["offered bound"] = offered(kernel, spec, ANON)  # une adresse reliée n'est plus une personne à part
        out["set"] = events(kernel, social_c.CLOSENESS_SET.name)
        out["audit"] = events(kernel, rt.OPERATED.name)
        return out

    out = run(tmp_path, scenario)
    assert not failed(out["tab"])
    slot = next(b for b in out["tab"] if isinstance(b, ActionSlot))
    assert slot.action == "social.proximite" and slot.initial == (("closeness", "close"),)
    assert out["offered"] == {"user_1": True, ANON: True, "anon_1": False, "name:bob": False}
    assert not out["bad"].ok and "choix inconnu" in out["bad"].errors["closeness"]
    assert not out["same"].ok and "déjà déclarée" in out["same"].errors["closeness"]
    assert out["friend"].ok and out["level"] == social_c.FRIEND
    assert out["auto"].ok and out["lived"] == social_c.STRANGER  # une seule journée : leur histoire commence
    assert out["offered bound"] is False
    operator_set = [e for e in out["set"] if e.origin is Origin.EXTERNAL]
    assert [(e.data.person, e.data.closeness, e.data.by) for e in operator_set] == [
        ("user_1", social_c.FRIEND, "user_1"), ("user_1", "", "user_1")]
    audit = [(e.data.action, e.data.outcome, e.data.subject_kind) for e in out["audit"]
             if e.data.action == "social.proximite"]
    assert audit == [("social.proximite", "refused", "person"), ("social.proximite", "done", "person"),
                     ("social.proximite", "done", "person")]


# ── Liens, présence, fil ──────────────────────────────────────────────────


def test_links_show_closeness_rhythm_and_profile_and_a_forgotten_profile_shows_as_forgotten(tmp_path):
    async def scenario(kernel):
        await live(kernel)
        before = show(kernel, "social", "liens"), show(kernel, "social", "lien", subject="user_1")
        legacy = show(kernel, "social", "liens", person="user_1")
        await kernel.forget("user_1")
        after = show(kernel, "social", "liens"), show(kernel, "social", "lien", subject="user_1")
        return before, legacy, after

    (listing, detail), legacy, (listing_after, detail_after) = run(tmp_path, scenario)
    for blocks in (listing, detail, legacy, listing_after, detail_after):
        assert not failed(blocks)
    links = table(listing, "personne")
    alice = row_of(links, "user_1")
    assert plain(alice["proximité"]) == "une proche (déclarée)"
    assert "repli selon la proximité" in alice["rythme"]  # une seule journée : pas encore de rythme mesuré
    assert isinstance(alice["dernier message reçu"], When)
    assert isinstance(alice["silence ÷ rythme"], Meter)
    assert SUMMARY in plain(alice["ce qu'elle en sait"])
    who = alice["personne"]
    assert isinstance(who, Ref) and who.key == "person/user_1" and who.text == "Alice"
    href = next(r.href for r in links.rows if r.cells[0] == who)
    assert href.key == "person/user_1" and href.params == (("onglet", "lien"),)
    assert plain(row_of(links, ANON)["ce qu'elle en sait"]) == "pas encore de profil"
    assert "avec douceur" in text(detail) and SUMMARY in text(detail)
    assert "Ce lien vit désormais sur la fiche" in text(legacy) and SUMMARY in text(legacy)

    assert plain(row_of(table(listing_after, "personne"), "user_1")["ce qu'elle en sait"]) == "(oublié)"
    summary = next(b for b in detail_after if isinstance(b, Prose) and b.title == "Ce qu'elle en sait")
    assert summary.text == "(oublié)"
    assert SUMMARY not in text(listing_after) + text(detail_after)


def test_presence_lists_live_connections_with_their_audience_and_a_vital(tmp_path):
    async def scenario(kernel):
        insp = Inspection(kernel)
        empty = dict((s.key, v) for s, v in insp.vitals())["presence.presents"]
        await live(kernel)
        await kernel.mind.append([presence_c.CONNECTED.draft(
            handle="tg_77", channel="telegram", connection="tg-group", room="tg:-100", public=True,
            display_name="Bob")], emitter="presence", correlation="ws:tg", origin=Origin.EXTERNAL)
        vital = dict((s.key, v) for s, v in insp.vitals())["presence.presents"]
        return show(kernel, "presence", "presents"), empty, vital

    blocks, empty, vital = run(tmp_path, scenario)
    assert not failed(blocks)
    rows = table(blocks, "personne")
    assert len(rows.rows) == 3
    by_handle = {plain(row_cells(r)[1]): as_dict(rows, r) for r in rows.rows}
    assert plain(by_handle["user_1"]["audience"]) == "privée"
    assert plain(by_handle[ANON]["audience"]) == "publique (rien ne prouve qui écrit)"
    assert plain(by_handle["tg_77"]["audience"]) == "publique (salon « tg:-100 »)"
    assert isinstance(by_handle["user_1"]["présente depuis"], When)
    assert by_handle["user_1"]["nom"] == "Alice" and by_handle["user_1"]["personne"].key == "person/user_1"
    assert all(r.href.kind == "subject" and r.href.key.startswith("person/") for r in rows.rows)
    assert (empty.text, empty.tone) == ("0", "")
    assert (vital.text, vital.tone) == ("3", "info") and "Alice" in vital.hint and "Bob" in vital.hint


def test_the_thread_shows_messages_filters_pages_and_unanswered_questions(tmp_path):
    async def scenario(kernel):
        await live(kernel)
        for i in range(60):
            await kernel.mind.append([rt.PERCEPTION_RECEIVED.draft(
                handle="user_1", channel="web", text=Content.of(f"bavardage {i}"), addressed=False)],
                emitter="runtime", correlation=f"perception:bavard{i}", origin=Origin.EXTERNAL)
        # une question journalisée dont la réponse n'est pas encore partie
        await kernel.mind.append([rt.PERCEPTION_RECEIVED.draft(
            handle=ANON, channel="web", text=Content.of("tu es là ? " + "x" * 400))], emitter="runtime",
            correlation="perception:attente", origin=Origin.EXTERNAL)
        insp = Inspection(kernel)
        first = show(kernel, "transcript", "messages")
        cursor = dict(table(first, "n°").pager.older)
        return {"first": first, "second": show(kernel, "transcript", "messages", **cursor),
                "anon": show(kernel, "transcript", "messages", handle=ANON),
                "search": show(kernel, "transcript", "messages", q="Alice"),
                "mine": show(kernel, "transcript", "messages", role="assistant"),
                "questions": show(kernel, "transcript", "questions"),
                "badge": insp.badge(inspection.find(kernel, "transcript", "questions")),
                "exchanges": show(kernel, "transcript", "echanges", subject="user_1"),
                "handle": show(kernel, "transcript", "fil", subject=ANON)}

    got = run(tmp_path, scenario)
    for key, blocks in got.items():
        if key != "badge":
            assert not failed(blocks), key
    first, second = table(got["first"], "n°"), table(got["second"], "n°")
    assert len(first.rows) == 50 and first.pager is not None and second.rows
    ids = [int(r.cells[0].key) for r in first.rows] + [int(r.cells[0].key) for r in second.rows]
    assert ids == sorted(ids, reverse=True) and len(set(ids)) == len(ids)  # du plus récent au plus ancien, sans doublon

    messages = [as_dict(first, r) for r in first.rows] + [as_dict(second, r) for r in second.rows]
    greeting = next(r for r in messages if plain(r["texte"]) == "salut Mika, tu as passé une bonne journée ?")
    assert plain(greeting["qui parle"]) == "la personne" and greeting["avec"].key == "person/user_1"
    replies = [r for r in messages if plain(r["qui parle"]) == "elle"]
    assert replies and all(plain(r["texte"]) == "d'accord" for r in replies)  # la prosodie est retirée
    assert all(isinstance(r["émotion"], Swatch) for r in replies)
    assert all(isinstance(r["épisode"], Ref) and r["épisode"].kind == "episode" for r in replies)
    long_one = next(r for r in messages if plain(r["texte"]).startswith("tu es là ?"))
    assert long_one["texte"].clamp == 300 and plain(long_one["réponse"]) == "en attente"

    only_anon = table(got["anon"], "n°")
    assert {r.cells[3].text for r in only_anon.rows} == {ANON}
    assert [plain(r.cells[5]) for r in table(got["search"], "n°").rows] == ["moi c'est Alice"]
    assert {plain(r.cells[2]) for r in table(got["mine"], "n°").rows} == {"elle"}

    waiting = table(got["questions"], "n°")
    assert len(waiting.rows) == 1 and plain(waiting.rows[0].cells[3]).startswith("tu es là ?")
    assert got["badge"] == (1, "")
    exchanges = table(got["exchanges"], "n°")
    assert {r.cells[3].key for r in exchanges.rows} == {"person/user_1"} and exchanges.pager is not None
    assert {r.cells[3].text for r in table(got["handle"], "n°").rows} == {ANON}


def test_views_stay_bounded_in_a_crowd(tmp_path):
    crowd = [f"web_{i:04d}" for i in range(210)]

    async def scenario(kernel):
        await kernel.mind.append([presence_c.CONNECTED.draft(handle=h, channel="web", connection=f"c-{h}")
                                  for h in crowd], emitter="presence", correlation="ws:foule",
                                 origin=Origin.EXTERNAL)
        await kernel.mind.append([rt.PERCEPTION_RECEIVED.draft(handle=h, channel="web", text=Content.of(f"coucou {h}"))
                                  for h in crowd], emitter="runtime", correlation="perception:foule",
                                 origin=Origin.EXTERNAL)
        got = {key: show(kernel, *key) for key in OWN_VIEWS}
        got["page 5"] = show(kernel, "identity", "annuaire", page="5")
        got["badge"] = Inspection(kernel).badge(inspection.find(kernel, "transcript", "questions"))
        got["found"] = Inspection(kernel).search("person", "web_", 20)
        return got

    got = run(tmp_path, scenario)
    for key in OWN_VIEWS:
        blocks = got[key]
        assert not failed(blocks), key
        assert all(len(t.rows) <= 50 for t in tables(blocks)), key
    for key, first in ((("identity", "annuaire"), "adresse"), (("identity", "personnes"), "personne"),
                       (("presence", "presents"), "personne"), (("social", "liens"), "personne")):
        t = table(got[key], first)
        assert len(t.rows) == 50 and t.pager is not None and t.pager.total == 210, key
    assert len(table(got["page 5"], "adresse").rows) == 10
    fil = table(got[("transcript", "messages")], "n°")
    assert len(fil.rows) == 50 and fil.pager is not None and fil.pager.older
    assert len(table(got[("transcript", "questions")], "n°").rows) == 50
    assert got["badge"] == (210, "")
    assert len(got["found"]) == 20
