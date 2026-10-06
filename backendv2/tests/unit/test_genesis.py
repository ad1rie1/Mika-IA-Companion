"""Une vie importée (ADR 0070), par ses intentions.

- ce qu'un pilote lui donne de ses archives devient sa mémoire comme le reste :
  gardé, retrouvé par le rappel, effacé avec la personne qu'il concerne — et
  marqué comme venu de la genèse, jamais de sa voix ;
- une clé de personne mal formée est refusée : l'oubli ne l'atteindrait pas ;
- l'avance rapide coupe sa vie spontanée le temps du rejeu, et la levée lui
  rend ses valeurs naturelles.
"""

from __future__ import annotations

import asyncio

import pytest

from mika.app import composition, genesis
from mika.contracts import agency as agency_c
from mika.contracts import memory as memory_c
from mika.contracts import runtime as rt
from mika.contracts import social as social_c
from mika.faculties.agency import restraint
from mika.kernel import forms
from mika.kernel.clock import HOUR, US
from mika.kernel.events import Origin
from mika.ports.llm import LLMResponse
from mika.runtime import params
from mika.runtime.effects import with_content
from mika.sim.clock import run_virtual
from tests.fixtures.memory import Script, chat, kept, section
from tests.fixtures.mika import DOC, at_paris, befriend, boot, build, connect, said

REVIENT = "CE QUI TE REVIENT"


def _origin(kernel, seq: int) -> str:
    return kernel.mind.store.get_events([seq])[0].origin


# ── La couture : ce que ses archives disent d'elle ────────────────────────


def test_an_archived_memory_is_kept_recalled_and_forgotten_with_the_person(tmp_path):
    """Un souvenir de ses archives est un souvenir : dans ``memory_items``, avec qui il concerne et qui l'a
    confié ; il revient quand Alice en reparle ; une même clé n'en fait pas deux ; et oublier Alice l'efface —
    la ligne, et le texte lui-même."""
    script = Script()
    kernel, clock, _, _out = build(tmp_path, script)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_2", "Alice")
        seq = await genesis.remember(kernel, "Alice m'a appris à faire du vélo au bord du canal à Lyon (CANARI-G1)",
                                     ("user_2",), told_by=("user_2",), importance=0.7, emotion="nostalgic",
                                     dedupe_key="archive-1")
        again = await genesis.remember(kernel, "Alice m'a appris à faire du vélo au bord du canal à Lyon (CANARI-G1)",
                                       ("user_2",), told_by=("user_2",), dedupe_key="archive-1")
        rows = kept(kernel)
        await asyncio.sleep(60)  # l'index des vecteurs passe
        await chat(kernel, "user_2", ["tu te souviens du vélo au bord du canal à Lyon ?"])
        await kernel.mind.forget("user_2")
        left = [r for r in kept(kernel) if "CANARI-G1" in r["text"]]
        text = kernel.mind.store.content([f"{seq}.text"])
        origin = _origin(kernel, seq)
        await kernel.stop()
        return seq, again, rows, left, text, origin

    seq, again, rows, left, text, origin = run_virtual(clock, main)
    mine = [r for r in rows if "CANARI-G1" in r["text"]]
    assert again == seq and len(mine) == 1, "une même clé de dédoublonnage n'en fait qu'un"
    row = mine[0]
    assert row["id"] == seq and row["kind"] == memory_c.SOUVENIR and row["status"] == "active"
    assert row["about"] == ["user_2"] and row["told_by"] == ["user_2"] and row["heard_by"] == ["user_2"]
    assert row["sensitivity"] == 2, "une personne en jeu : personnel par défaut, comme à la consolidation"
    assert origin == Origin.GENESIS.value, "venu de ses archives, pas de sa voix ni d'un processus"
    assert "CANARI-G1" in section(script.replies("user_2")[-1], REVIENT), "le rappel le retrouve"
    assert left == [] and not text.get(f"{seq}.text"), "oublier Alice efface la ligne et le texte"


def test_a_belief_about_herself_and_a_moment_of_someone_s_life(tmp_path):
    """Ce qui la définit (un goût de toujours) se garde longtemps et ne concerne qu'elle ; un moment de la vie
    d'Alice est noté avec sa date, et sa mémoire le lit comme les autres (``memory.life_events``)."""
    kernel, clock, _, _out = build(tmp_path, Script())
    when = at_paris(2026, 10, 2, 18, 0)

    async def main():
        await boot(kernel)
        taste = await genesis.believe(kernel, "Mon plat préféré, c'est le gratin dauphinois de ma grand-mère",
                                      (), about_self=True, durable=True, origin=memory_c.OBSERVED,
                                      dedupe_key="gout-gratin")
        fact = await genesis.believe(kernel, "Alice adore la city pop", ("user_2",), source="user_2",
                                     told_by=("user_2",), sensitivity=1, dedupe_key="alice-citypop")
        event = await genesis.note_event(kernel, "son entretien chez Ubisoft", ("user_2",), when,
                                         told_by=("user_2",), importance=0.8, dedupe_key="alice-ubisoft")
        life = kernel.mind.frame().get(memory_c.LIFE_EVENTS("user_2"))
        rows = {r["id"]: r for r in kept(kernel)}
        await kernel.stop()
        return taste, fact, event, life, rows

    taste, fact, event, life, rows = run_virtual(clock, main)
    assert rows[taste]["about_self"] == 2 and rows[taste]["about"] == [] and rows[taste]["sensitivity"] == 1
    assert rows[fact]["kind"] == memory_c.BELIEF and rows[fact]["informants"] == ["user_2"]
    assert rows[event]["kind"] == memory_c.EVENT and rows[event]["due"] == when
    assert [e.id for e in life] == [event] and life[0].importance == 0.8


@pytest.mark.parametrize("key", ["Alice", "name:Alice", "name:alice  martin", "name:", " user_2", "anon_3f2a", "user_007",
                                 "conscience_mika", "__global__", "module_email", "", "user 2", "user_x",
                                 "web_6f3e22ccb0ae"])
def test_a_badly_formed_person_key_is_refused(key):
    """Un prénom nu, un nom pas replié, sa tuyauterie, une connexion jetable, une adresse jamais vue : refusés."""
    with pytest.raises(genesis.NotAPerson):
        genesis.person_key(key)


def test_canonical_keys_are_accepted():
    assert genesis.named("Alice  Martin") == "name:alice martin"
    for key in ("user_2", "ext_5", "ext_tg_123", genesis.named("Chloé"), "name:chloe"):
        assert genesis.person_key(key) == key
    # une adresse de navigateur se choisit côté client : acceptée une fois qu'elle a été vue
    assert genesis.person_key("web_6f3e22ccb0ae", lambda h: h == "web_6f3e22ccb0ae") == "web_6f3e22ccb0ae"


def test_nothing_is_written_when_a_key_is_refused(tmp_path):
    """Refusée avant l'ajout : rien n'entre dans le journal — pas même le texte, qu'aucun oubli n'atteindrait."""
    kernel, clock, _, _out = build(tmp_path, Script())

    async def main():
        await boot(kernel)
        head = kernel.mind.head
        refused = []
        for call in (lambda: genesis.remember(kernel, "Un souvenir de Bob", ("Bob",)),
                     lambda: genesis.believe(kernel, "Bob aime le jazz", ("user_3",), told_by=("bob",)),
                     lambda: genesis.believe(kernel, "J'aime le jazz", ("user_3",), about_self=True),
                     lambda: genesis.note_event(kernel, "son départ", (), at_paris(2026, 10, 3, 9))):
            try:
                await call()
            except ValueError as exc:
                refused.append(type(exc).__name__)
        after = kernel.mind.head
        await kernel.stop()
        return head, after, refused

    head, after, refused = run_virtual(clock, main)
    assert refused == ["NotAPerson", "NotAPerson", "ValueError", "NotAPerson"] and after == head


# ── L'avance rapide ───────────────────────────────────────────────────────


def test_the_fast_forward_preset_names_real_parameters():
    """Chaque surcharge du préréglage est un vrai paramètre : un nom qui n'existe plus serait refusé — et sa vie
    spontanée tournerait en silence pendant le rejeu (contre-épreuve : un nom inventé l'est)."""
    faculties = composition.faculties()
    planned = params.plan(faculties, DOC.temperament, genesis.fast_forward_overrides())
    assert {o: dict(p.refused) for o, p in planned.items() if p.refused} == {}
    for owner, layer in genesis.FAST_FORWARD.items():
        assert set(layer) <= set(forms.flatten(planned[owner].value)), owner
    wrong = params.plan(faculties, DOC.temperament, {"agency": {"plafond_du_jour": 0}})
    assert wrong["agency"].refused


class _Talkative:
    """Elle répond, et écrit d'elle-même quand l'arbitre l'y pousse."""

    def __call__(self, req):
        if req.role in ("extract", "profile", "compact"):
            return LLMResponse("{}")
        if req.role in ("narrative", "journal", "dream", "murmur"):
            return LLMResponse("Une journée.")
        if req.role == "initiative":
            return LLMResponse("coucou, ça va ? [EMOTION:happy:0.5]")
        return LLMResponse("haha d'accord [EMOTION:happy:0.5]")


def _ordinary_initiatives(kernel) -> list:
    """Ses initiatives dites, hors salutations (à l'arrivée de quelqu'un : pas de paramètre pour les couper, et un
    rejeu d'archive n'en fait pas — voir ``genesis``). Les rappels et les promesses tenues, pourtant dus, sont
    comptés : le préréglage les coupe aussi."""
    mind = kernel.mind
    events = [with_content(mind, mind.decode(e))
              for e in mind.store.read(types=(rt.EPISODE_STARTED.name, rt.UTTERANCE.name))]
    reasons = {e.correlation: e.data.reason for e in events if e.type.name == rt.EPISODE_STARTED.name}
    owed = {social_c.GREETING}
    return [e for e in events if e.type.name == rt.UTTERANCE.name and e.data.kind == "INITIATIVE"
            and not owed & set(reasons.get(e.correlation, "").split(","))]


def _a_day_with_a_friend(tmp_path, *, fast: bool):
    """Une journée avec une amie qui répond à chaque mot d'elle (le contre-exemple de « ne pas harceler » : elle
    lui écrit d'elle-même plusieurs fois)."""
    kernel, clock, _, _out = build(tmp_path, _Talkative(), start=at_paris(2026, 9, 28, 9, 0))

    async def main():
        await boot(kernel)
        natural = kernel.mind.registry.params_of("agency", kernel.mind.root)
        if fast:
            await genesis.begin_fast_forward(kernel, overrides=None)
        posed = kernel.mind.registry.params_of("agency", kernel.mind.root)
        await befriend(kernel, "user_1", social_c.FRIEND)
        await connect(kernel, "user_1", "Adrien")
        seen = 0
        for _ in range(24 * 6):
            await asyncio.sleep(10 * 60)
            sent = _ordinary_initiatives(kernel)
            if len(sent) > seen:
                seen = len(sent)
                await asyncio.sleep(5 * 60)
                p = await kernel.perceive(said("user_1", "oui ça va, et toi ?"))
                await p.reply
        sent = _ordinary_initiatives(kernel)
        lifted = None
        if fast:
            await genesis.end_fast_forward(kernel, overrides=None)
            lifted = {o: kernel.mind.registry.params_of(o, kernel.mind.root) for o in genesis.FAST_FORWARD}
        expected = {o: params.planned(kernel.registry.faculties[o], DOC.temperament).value
                    for o in genesis.FAST_FORWARD}
        await kernel.stop()
        return natural, posed, sent, lifted, expected

    return run_virtual(clock, main)


def test_fast_forward_silences_her_ordinary_initiatives_and_lifting_it_brings_her_back(tmp_path):
    """Le préréglage posé, une journée entière avec une amie qui répond : aucune initiative ordinaire (le
    plafond du jour à zéro) ; levé, chaque faculté retrouve ses valeurs naturelles. Contre-épreuve : la même
    journée sans préréglage la voit écrire d'elle-même."""
    natural, posed, sent, lifted, expected = _a_day_with_a_friend(tmp_path / "rapide", fast=True)
    assert natural.daily_cap > 0 and posed.daily_cap == 0
    assert sent == [], [e.data.text.text for e in sent]
    assert lifted == expected, "la levée ramène les valeurs naturelles (tempérament, réglages)"
    _n, _p, free, _l, _e = _a_day_with_a_friend(tmp_path / "libre", fast=False)
    assert free, "contre-épreuve : sans préréglage, elle écrit d'elle-même dans la journée"


def test_the_preset_is_journaled_like_any_configuration(tmp_path):
    """Posé, le préréglage est un ``kernel.params_changed`` (le rejeu le relit tel quel) ; levé, un autre."""
    kernel, clock, _, _out = build(tmp_path, Script())

    async def main():
        await boot(kernel)
        before = kernel.mind.head
        posed = await genesis.begin_fast_forward(kernel, overrides=None)
        middle = kernel.mind.head
        again = await genesis.begin_fast_forward(kernel, overrides=None)
        lifted = await genesis.end_fast_forward(kernel, overrides=None)
        names = [e.type for e in kernel.mind.store.read() if e.seq > before]
        values = kernel.mind.registry.params_of("goals", kernel.mind.root)
        await kernel.stop()
        return posed, middle > before, again, lifted, names, values

    posed, wrote, again, lifted, names, values = run_virtual(clock, main)
    assert posed and wrote and not again, "posé une fois : le reposer ne journalise rien"
    assert lifted and set(names) == {"kernel.params_changed"}
    assert values.live_self_max > 0 and values.musings_per_day > 0


def test_fast_forward_vetoes_every_ordinary_initiative(tmp_path):
    """Sous le préréglage, toute initiative ordinaire est refusée par le plafond du jour ; levé, plus rien ne la
    refuse à ce titre."""
    kernel, clock, _, _out = build(tmp_path, Script(), start=at_paris(2026, 9, 28, 9, 0))

    async def main():
        await boot(kernel)
        await genesis.begin_fast_forward(kernel, overrides=None)
        await asyncio.sleep(HOUR / US)
        veto = restraint(kernel.mind.frame(), None, ("needs.talk",)).veto
        await genesis.end_fast_forward(kernel, overrides=None)
        lifted = restraint(kernel.mind.frame(), None, ("needs.talk",)).veto
        await kernel.stop()
        return veto, lifted

    veto, lifted = run_virtual(clock, main)
    assert veto == agency_c.DAILY_CAP and lifted != agency_c.DAILY_CAP


# ── Ce que la relecture du lot a trouvé ───────────────────────────────────


def test_a_secret_from_her_own_notes_never_comes_out():
    """Un secret sans personne (ses propres notes importées) : la règle « personne d'identifié » ne regardait que la
    sensibilité, et un secret anodin sortait dans un salon public."""
    from mika.faculties.memory.salience import admissible  # noqa: PLC0415 — la règle seule
    from mika.kernel.frame import Audience  # noqa: PLC0415

    public = Audience(persons=("ext_42",), room="salon", public=True, level=1)
    assert not admissible((), 1, "ext_42", public, secret=True).ok
    assert admissible((), 1, "ext_42", public, secret=False).ok, "contre-épreuve : anodin et pas secret, ça se dit"


def test_imported_secrets_and_ties_keep_the_consolidation_s_rules(tmp_path):
    """Un secret importé est une confidence ; « entre vous » se tient de première main, au moins personnel, et
    compte ; la source d'une croyance est un sujet d'oubli ; son propre nom n'est pas une tierce personne."""
    kernel, clock, _, _out = build(tmp_path, Script())

    async def main():
        await boot(kernel)
        await connect(kernel, "user_2", "Alice")
        await connect(kernel, "user_3", "Bob")
        await genesis.remember(kernel, "J'ai raté mon bac de philo, personne ne le sait", (), secret=True,
                               dedupe_key="s1")
        await genesis.believe(kernel, "Alice m'appelle « Mimi »", ("user_2",), told_by=("user_2",), between_us=True,
                              sensitivity=1, importance=0.2, dedupe_key="b1")
        await genesis.believe(kernel, "Alice adore le jazz", ("user_2",), source="user_3", dedupe_key="b2")
        refused = []
        for call in (lambda: genesis.believe(kernel, "un surnom", (), between_us=True),
                     lambda: genesis.believe(kernel, "un surnom", ("user_2",), told_by=("user_3",), between_us=True),
                     lambda: genesis.remember(kernel, "moi, à la plage", (genesis.named(DOC.name),)),
                     lambda: genesis.believe(kernel, "j'aime le jazz", (), about_self=True, source="user_3")):
            try:
                await call()
            except ValueError as exc:
                refused.append(type(exc).__name__)
        rows = {r["text"]: r for r in kept(kernel)}
        await kernel.stop()
        return rows, refused

    rows, refused = run_virtual(clock, main)
    secret = rows["J'ai raté mon bac de philo, personne ne le sait"]
    assert secret["secret"] and secret["sensitivity"] == 3
    tie = rows["Alice m'appelle « Mimi »"]
    assert tie["sensitivity"] >= 2
    assert rows["Alice adore le jazz"]["told_by"] == ["user_3"]
    assert refused == ["ValueError", "ValueError", "NotAPerson", "ValueError"]


def test_lifting_keeps_the_operator_s_own_overrides(tmp_path):
    """La levée rejournalise la configuration qu'on lui donne : une surcharge de l'opératrice revient."""
    kernel, clock, _, _out = build(tmp_path, Script())
    mine = {"agency": {"daily_cap": 3}}

    async def main():
        await boot(kernel)
        await genesis.begin_fast_forward(kernel, overrides=mine)
        posed = kernel.mind.registry.params_of("agency", kernel.mind.root).daily_cap
        await genesis.end_fast_forward(kernel, overrides=mine)
        lifted = kernel.mind.registry.params_of("agency", kernel.mind.root).daily_cap
        await kernel.stop()
        return posed, lifted

    assert run_virtual(clock, main) == (0, 3)


def test_a_preset_path_that_no_longer_exists_refuses_to_start(tmp_path, monkeypatch):
    """Un paramètre du préréglage disparu : la pose lève, plutôt que de laisser sa vie spontanée tourner."""
    kernel, clock, _, _out = build(tmp_path, Script())
    monkeypatch.setattr(genesis, "FAST_FORWARD", {**genesis.FAST_FORWARD, "agency": {"plafond_du_jour": 0}})

    async def main():
        await boot(kernel)
        try:
            await genesis.begin_fast_forward(kernel, overrides=None)
        except ValueError as exc:
            return str(exc)
        finally:
            await kernel.stop()
        return ""

    assert "refusé" in run_virtual(clock, main)


def test_release_held_does_nothing_before_the_kernel_lives(tmp_path):
    """Appelé avant ``live`` (ou après ``stop``), ``release_held`` ne fait rien : la reprise au démarrage retiendra."""
    kernel, _clock, _, _out = build(tmp_path, Script())
    kernel.release_held()  # ni exception, ni tâche lancée hors boucle


def test_her_first_name_alone_is_her_unless_someone_else_bears_it():
    """« Léa » dans une extraction : elle, si personne de connu ne s'appelle ainsi ; sinon, cette personne."""
    from mika.faculties.memory.extraction import People, Speaker  # noqa: PLC0415

    alone = People.of((Speaker("P1", "user_2", "Alice"),), {}, her="Léa Morel")
    assert alone.one("Léa") is None and alone.one("Léa Morel") is None and alone.one("moi") is None
    friend = People.of((Speaker("P1", "user_2", "Léa Dupont"),), {}, her="Léa Morel")
    assert friend.one("Léa") == "user_2", "une amie qui porte son prénom n'est pas elle"
    mika = People.of((), {}, her="Mika")
    assert mika.one("Mika") is None
