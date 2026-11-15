"""Où la joindre, et combien lui raconter : deux règles dans les contrats de leur propriétaire, lues par les buts et
par les projets (``contracts.identity.reach_now``, ``contracts.social.retelling``).

Buts et projets ne s'importent pas (ADR 0031) : chacun avait sa recherche d'adresse (« une adresse présente d'abord,
sinon joignable ») et son échelle de récit (propriétaire → tout, proche → l'essentiel, amie → une mention). Les deux
``confidant`` gardent leur liste de candidats et rendent ce qu'ils rendaient.

Dix autres facultés et plugins avaient leur copie de la recherche d'adresse. Les initiatives d'attention, de social,
de memory et d'others lisent la règle telle quelle, avec son repli sur la clé de la personne (une adresse reliée
depuis à quelqu'un d'autre reste trouvée) ; les six autres gardent chacune ce qui leur est propre (la clé de la
personne, la cible de la demande en dernier recours, un filtre d'heures) et rendent ce que rendait l'ancienne forme.

Avec elle, deux règles que les initiatives vers quelqu'un recopiaient : depuis quand la personne ne lui a rien écrit
(``contracts.identity.last_heard``) et la garde qui devance l'initiative si elle écrit entre-temps
(``contracts.identity.heard_since_guard``). Aucune nouvelle copie de ces règles ne naît ailleurs.
"""

from __future__ import annotations

import ast
import itertools
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from mika.contracts import goals as goals_c
from mika.contracts import identity as identity_c
from mika.contracts import others as others_c
from mika.contracts import presence as presence_c
from mika.contracts import projects as projects_c
from mika.contracts import social as social_c
from mika.contracts import transcript as transcript_c
from mika.faculties.goals.faculty import Goal
from mika.faculties.goals.work import confidant as goal_confidant
from mika.faculties.others.faculty import _check_in
from mika.faculties.projects.faculty import Project
from mika.faculties.projects.work import confidant as project_confidant
from mika.kernel.clock import HOUR as ONE_HOUR
from mika.plugins.forge import _address as forge_address
from mika.plugins.forge.calls import _address as call_address
from mika.plugins.imaging.prompt import _address as imaging_address
from mika.plugins.mcp.prompt import _address as mcp_address
from mika.plugins.rss import _address as rss_address
from mika.plugins.wakeup.prompt import address_of as wakeup_address
from mika.vocab.phrasebook import phrase

SRC = Path(__file__).resolve().parents[2] / "src" / "mika"
#: l'heure locale des cadres posés à la main
HOUR = 3

#: ce qu'un fait vaut quand le cadre ne le pose pas
DEFAULTS = {
    identity_c.HANDLES.name: (), identity_c.REACHABLE.name: (), presence_c.PRESENT.name: (),
    identity_c.IS_OWNER.name: False, identity_c.OWNERS.name: (), social_c.CLOSENESS.name: social_c.STRANGER,
    identity_c.PERSON.name: "", others_c.HOURS.name: others_c.HoursReading(days=0, active=(True,) * 24, learned=False),
    transcript_c.LAST_FROM.name: 0, identity_c.IDENTITY.name: NS(name=""),
}


def frame(*, present=(), owners=(), handles=None, reachable=None, closeness=None, persons=None, asleep=(),
          heard=None):
    """Un cadre de faits posés à la main : ``handles``, ``reachable`` et ``closeness`` par personne ; une personne
    de ``owners`` est propriétaire ; ``persons`` relie une adresse à sa personne ; une personne de ``asleep``
    n'écrit pas d'habitude à l'heure du cadre (``HOUR``) ; ``heard`` : quand chaque adresse lui a écrit pour la
    dernière fois."""
    sleeping = tuple(h != HOUR for h in range(24))
    facts = {
        (presence_c.PRESENT.name, None): tuple(present),
        (identity_c.OWNERS.name, None): tuple(owners),
        **{(identity_c.IS_OWNER.name, o): True for o in owners},
        **{(identity_c.HANDLES.name, k): tuple(v) for k, v in (handles or {}).items()},
        **{(identity_c.REACHABLE.name, k): tuple(v) for k, v in (reachable or {}).items()},
        **{(social_c.CLOSENESS.name, k): v for k, v in (closeness or {}).items()},
        **{(identity_c.PERSON.name, k): v for k, v in (persons or {}).items()},
        **{(others_c.HOURS.name, k): others_c.HoursReading(days=3, active=sleeping, learned=True) for k in asleep},
        **{(transcript_c.LAST_FROM.name, k): v for k, v in (heard or {}).items()},
    }
    return NS(get=lambda key: facts.get((key.name, getattr(key, "arg", None)), DEFAULTS[key.name]),
              local=lambda at=None: NS(hour=HOUR))


# ── Où la joindre ─────────────────────────────────────────────────────────


def test_a_present_address_comes_before_a_reachable_one():
    f = frame(present=("user_1",), handles={"alice": ("ext_1", "user_1")}, reachable={"alice": ("ext_1",)})
    assert identity_c.reach_now(f, "alice") == "user_1"


def test_the_first_present_is_in_the_order_of_presence():
    f = frame(present=("user_2", "user_1"), handles={"alice": ("user_1", "user_2")})
    assert identity_c.reach_now(f, "alice") == "user_2"
    assert identity_c.present_address(f, ("user_1", "user_2")) == "user_2"
    assert identity_c.present_address(f, iter(("user_1",))) == "user_1"  # un itérable quelconque
    assert identity_c.present_address(f, ("ext_9",)) is None


def test_without_a_present_address_the_first_reachable():
    f = frame(present=("user_9",), handles={"alice": ("ext_1", "ext_2")}, reachable={"alice": ("ext_2", "ext_1")})
    assert identity_c.reach_now(f, "alice") == "ext_2"


def test_nowhere_to_reach_her():
    assert identity_c.reach_now(frame(handles={"alice": ("ext_1",)}), "alice") is None
    assert identity_c.reach_now(frame(), "ext_7") is None


def test_a_person_without_handles_is_found_by_her_own_key():
    assert identity_c.reach_now(frame(present=("ext_9",)), "ext_9") == "ext_9"


def test_given_handles_replace_the_fallback():
    f = frame(present=("user_1", "ext_5"), handles={"alice": ("user_1",)}, reachable={"alice": ("ext_3",)})
    assert identity_c.reach_now(f, "alice") == "user_1"
    assert identity_c.reach_now(f, "alice", handles=("ext_5",)) == "ext_5"
    assert identity_c.reach_now(f, "alice", handles=()) == "ext_3"  # aucune donnée : la joignable


def test_an_address_linked_since_to_someone_else_is_found_by_its_key():
    """ext_4, reliée depuis à alice, a quitté ses propres adresses (``HANDLES(ext_4)`` vide) pour celles d'alice ; ce
    qu'une faculté avait ouvert sous ext_4 y reste. Si elle est là, la règle la trouve par sa clé."""
    f = frame(present=("ext_4",), handles={"alice": ("ext_4", "user_1")}, persons={"ext_4": "alice"})
    assert identity_c.reach_now(f, "ext_4") == "ext_4"
    assert identity_c.reach_now(f, "alice") == "ext_4"


# ── Depuis quand elle ne lui a rien écrit, et la garde d'une initiative ───


def test_she_was_last_heard_on_the_latest_of_her_addresses():
    f = frame(handles={"alice": ("ext_1", "user_1")}, heard={"ext_1": 40, "user_1": 70, "alice": 99})
    assert identity_c.last_heard(f, "alice") == 70  # ses adresses : sa clé n'en est pas une quand elle en a


def test_without_handles_she_is_heard_by_her_own_key():
    assert identity_c.last_heard(frame(heard={"ext_9": 12}), "ext_9") == 12


def test_never_heard_is_zero():
    assert identity_c.last_heard(frame(), "alice") == 0
    assert identity_c.last_heard(frame(handles={"alice": ("ext_1", "user_1")}), "alice") == 0


def test_the_initiative_guard_reads_each_of_her_addresses():
    """Si elle écrit entre-temps, sur n'importe laquelle de ses adresses, l'initiative est devancée."""
    guard = identity_c.heard_since_guard(frame(handles={"alice": ("ext_1", "user_1")}), "alice")
    assert guard.name == "pas de nouvelles"
    assert guard.reads == (transcript_c.LAST_FROM("ext_1"), transcript_c.LAST_FROM("user_1"))
    assert guard.predicate is None and guard.leases == ()
    assert identity_c.heard_since_guard(frame(), "ext_9").reads == (transcript_c.LAST_FROM("ext_9"),)


def test_a_concern_opened_under_an_address_linked_since_still_reaches_it():
    """L'inquiétude d'``others`` ouverte sous ext_4, reliée depuis à alice : ext_4 est là, la prise de nouvelles part
    vers elle, et sa garde lit ext_4. Sans le repli sur la clé, ext_4 n'était pas trouvée et rien ne partait — alors
    que sa garde et son dernier message se lisaient déjà sous ext_4."""
    f = frame(present=("ext_4",), handles={"alice": ("ext_4", "user_1")}, persons={"ext_4": "alice"},
              closeness={"ext_4": social_c.FRIEND})
    f = NS(get=f.get, local=lambda at=None: NS(hour=14, minute=0), now=2 * ONE_HOUR,
           env=NS(params_of=lambda *_: None), root="")
    [wish] = _check_in(NS(concerns={"ext_4": ("message", 0, ONE_HOUR)}), f)
    assert (wish.target, wish.reason, wish.resources) == ("ext_4", others_c.CHECK_IN, frozenset({"floor:ext_4"}))
    assert [g.reads for g in wish.guards] == [(transcript_c.LAST_FROM("ext_4"),)]
    someone = phrase("others.initiative.someone")
    assert dict(wish.args) == {"brief:others": phrase("others.initiative.check_in",
                                                      who=someone[:1].upper() + someone[1:])}


# ── Combien lui raconter ──────────────────────────────────────────────────


def test_the_retelling_scale():
    f = frame(owners=("adrien",), closeness={"bea": social_c.CLOSE, "chloe": social_c.FRIEND,
                                              "dan": social_c.ACQUAINTANCE, "eve": "inconnu-du-contrat"})
    tell = social_c.retelling
    assert tell(f, "adrien", concerned=False, owner_hears=True) == social_c.FULL == "full"
    assert tell(f, "adrien", concerned=False, owner_hears=False) is None
    assert tell(f, "bea", concerned=True, owner_hears=True) == social_c.SUMMARY == "summary"
    assert tell(f, "chloe", concerned=True, owner_hears=True) == social_c.MENTION == "mention"
    assert tell(f, "dan", concerned=True, owner_hears=True) is None  # une connaissance
    assert tell(f, "eve", concerned=True, owner_hears=True) is None  # un cran inconnu ne vaut rien
    assert tell(f, "zoe", concerned=True, owner_hears=True) is None  # une inconnue
    assert tell(f, "bea", concerned=False, owner_hears=True) is None  # une proche que ça ne regarde pas


# ── Les deux ``confidant`` rendent ce qu'ils rendaient ────────────────────


def _goal(owner=None, about=()):
    return Goal(id=1, kind=goals_c.EXPLORATION, authority=goals_c.USER, title_ref="t", opened_at=0, owner=owner,
                about=tuple(about))


def _project(owner=None, authority=projects_c.USER):
    return Project(id=1, title_ref="t", authority=authority, created_at=0, owner=owner)


PEOPLE = dict(owners=("adrien",), reachable={"adrien": ("user_1",), "bea": ("ext_2",), "chloe": ("ext_3",)},
              closeness={"bea": social_c.CLOSE, "chloe": social_c.FRIEND, "dan": social_c.ACQUAINTANCE})


def test_a_goal_confided_by_a_friend_about_her_alone_is_a_mention_to_her():
    assert goal_confidant(_goal("chloe", ("chloe",)), frame(**PEOPLE)) == ("chloe", "ext_3", social_c.MENTION)


def test_a_goal_about_nobody_tells_everything_to_an_owner():
    assert goal_confidant(_goal(), frame(**PEOPLE)) == ("adrien", "user_1", social_c.FULL)


def test_a_goal_about_others_is_not_told_to_an_owner():
    """Un but qui ne regarde qu'une connaissance : personne ne l'entend (une propriétaire n'y est pas candidate)."""
    assert goal_confidant(_goal(None, ("dan",)), frame(**PEOPLE)) is None
    # … sauf si la propriétaire est concernée : elle entend tout
    assert goal_confidant(_goal("adrien", ("dan",)), frame(**PEOPLE)) == ("adrien", "user_1", social_c.FULL)


def test_a_goal_goes_to_the_next_one_when_the_first_is_out_of_reach():
    f = frame(**{**PEOPLE, "reachable": {"chloe": ("ext_3",)}})
    assert goal_confidant(_goal("bea", ("bea", "chloe")), f) == ("chloe", "ext_3", social_c.MENTION)


def test_a_project_confided_by_a_close_friend_is_the_essential_to_her():
    assert project_confidant(_project("bea"), frame(**PEOPLE)) == ("bea", "ext_2", social_c.SUMMARY)


def test_a_project_of_her_own_tells_everything_to_an_owner():
    assert project_confidant(_project(None, projects_c.SELF), frame(**PEOPLE)) == ("adrien", "user_1", social_c.FULL)


def test_a_project_confided_by_an_acquaintance_goes_to_an_owner():
    assert project_confidant(_project("dan"), frame(**PEOPLE)) == ("adrien", "user_1", social_c.FULL)
    assert project_confidant(_project("dan"), frame(**{**PEOPLE, "owners": ()})) is None


# ── Les six autres copies gardent chacune ce qui leur est propre ──────────
# Ce que faisait chaque copie avant de lire ``reach_now`` (le corps d'avant, mot pour mot). Celles d'attention, de
# social, de memory et d'others (« sans repli » : ``HANDLES`` seules) ne sont plus : elles lisent ``reach_now``.


def _was(f, handles, person, last=None):
    present = [h for h in f.get(presence_c.PRESENT) if h in handles]
    if present:
        return present[0]
    reachable = f.get(identity_c.REACHABLE(person))
    return reachable[0] if reachable else last


def _was_keyed(f, person):  # forge, wakeup
    return _was(f, f.get(identity_c.HANDLES(person)) or (person,), person)


def _was_asked(f, r):  # forge/calls, mcp
    person = f.get(identity_c.PERSON(r.target)) or r.target
    return _was(f, f.get(identity_c.HANDLES(person)) or (r.target,), person, r.target)


def _was_drawn(f, j):  # imaging
    return _was(f, f.get(identity_c.HANDLES(j.person)) or (j.target,), j.person, j.target)


def _was_hours(f, person):  # rss
    handles = f.get(identity_c.HANDLES(person)) or (person,)
    present = [h for h in f.get(presence_c.PRESENT) if h in handles]
    if present:
        return present[0]
    if not f.get(others_c.HOURS(person)).active[f.local().hour]:
        return None
    reachable = f.get(identity_c.REACHABLE(person))
    return reachable[0] if reachable else None


#: chaque copie, ce qu'elle faisait, et ce qu'on lui donne (une personne, une demande ou un dessin)
COPIES = {
    "forge": (forge_address, _was_keyed, "person"), "wakeup": (wakeup_address, _was_keyed, "person"),
    "forge.calls": (call_address, _was_asked, "request"), "mcp": (mcp_address, _was_asked, "request"),
    "imaging": (imaging_address, _was_drawn, "job"), "rss": (rss_address, _was_hours, "person"),
}

SUBJECTS = {
    "person": ("alice", "ext_9", "ext_4"),
    "request": tuple(NS(target=t) for t in ("ext_4", "ext_9", "user_1")),
    "job": tuple(NS(person=p, target=t) for p, t in (("alice", "ext_4"), ("ext_9", "ext_9"), ("", "ext_4"))),
}


def _frames():
    """Toutes les combinaisons d'un petit monde : alice (deux adresses), ext_9 (une clé sans adresse connue), ext_4
    (une adresse reliée ou non à alice), présentes ou non, joignables ou non, éveillées ou non."""
    presents = ((), ("user_1",), ("ext_9",), ("user_2", "user_1"), ("ext_4",), ("ext_9", "user_1"), ("ext_4", "user_2"))
    for present, handles, reach_a, reach_9, linked, asleep in itertools.product(
            presents, (None, ("user_1", "user_2")), (None, ("ext_3",)), (None, ("ext_8",)), (False, True),
            ((), ("alice", "ext_9", "ext_4"))):
        yield frame(present=present, handles={"alice": handles} if handles else None,
                    reachable={k: v for k, v in (("alice", reach_a), ("ext_9", reach_9)) if v},
                    persons={"ext_4": "alice"} if linked else None, asleep=asleep)


@pytest.mark.parametrize("name", list(COPIES))
def test_each_copy_answers_what_it_answered(name):
    now, was, kind = COPIES[name]
    for f in _frames():
        for subject in SUBJECTS[kind]:
            assert now(f, subject) == was(f, subject), (name, subject)


def test_each_copy_keeps_its_own_fallback():
    """ext_9 n'a pas d'adresse connue et sa clé est là : la règle la trouve par sa clé (les initiatives d'attention,
    de social, de memory et d'others la lisent telle quelle), comme les copies qui se replient sur sa clé."""
    f = frame(present=("ext_9",))
    assert identity_c.reach_now(f, "ext_9") == "ext_9"
    assert [a(f, "ext_9") for a in (forge_address, wakeup_address, rss_address)] == ["ext_9"] * 3
    # une demande ou un dessin : rien de joignable, d'où venait la demande
    assert call_address(frame(), NS(target="ext_4")) == mcp_address(frame(), NS(target="ext_4")) == "ext_4"
    assert imaging_address(frame(), NS(person="alice", target="web_1")) == "web_1"
    # rss : la présente passe avant ses heures, la joignable attend qu'elle soit réveillée
    asleep = frame(present=("ext_3",), reachable={"alice": ("ext_3", "ext_5")}, handles={"alice": ("ext_3",)},
                   asleep=("alice",))
    assert rss_address(asleep, "alice") == "ext_3"
    assert rss_address(frame(reachable={"alice": ("ext_5",)}, asleep=("alice",)), "alice") is None
    assert rss_address(frame(reachable={"alice": ("ext_5",)}), "alice") == "ext_5"


def _copies_of_the_rule(tree: ast.Module):
    """Les compréhensions qui filtrent ``presence.PRESENT`` par des adresses (``[h for h in f.get(…PRESENT) if h in
    …]``) : la recherche d'une adresse présente, recopiée."""
    for node in ast.walk(tree):
        if not isinstance(node, (ast.ListComp, ast.GeneratorExp, ast.SetComp)):
            continue
        for gen in node.generators:
            reads_present = (isinstance(gen.iter, ast.Call) and isinstance(gen.iter.func, ast.Attribute)
                             and gen.iter.func.attr == "get" and len(gen.iter.args) == 1
                             and isinstance(gen.iter.args[0], ast.Attribute) and gen.iter.args[0].attr == "PRESENT")
            if reads_present and any(isinstance(c, ast.Compare) and any(isinstance(o, ast.In) for o in c.ops)
                                     for c in gen.ifs):
                yield node.lineno


def test_the_present_address_is_looked_up_in_one_place():
    """La règle vit dans ``contracts/identity.py::present_address`` ; une copie ailleurs diverge un jour."""
    found = {f"{p.relative_to(SRC)}:{line}" for p in SRC.rglob("*.py")
             for line in _copies_of_the_rule(ast.parse(p.read_text(encoding="utf-8")))}
    assert {f.split(":")[0] for f in found} == {"contracts/identity.py"}, sorted(found)


def _named(func: ast.expr, name: str) -> bool:
    return isinstance(func, ast.Name) and func.id == name or isinstance(func, ast.Attribute) and func.attr == name


def _over_last_from(node: ast.AST):
    """Les compréhensions sur le dernier message de chaque adresse (``… ….LAST_FROM(h) … for h in …``)."""
    for n in ast.walk(node):
        if isinstance(n, (ast.GeneratorExp, ast.ListComp, ast.SetComp)) and any(
                isinstance(c, ast.Call) and _named(c.func, "LAST_FROM") for c in ast.walk(n.elt)):
            yield n


def _copies_of_the_guard(tree: ast.Module):
    """Les gardes posées sur le dernier message de chacune de ses adresses (``Guard(…, reads=tuple(….LAST_FROM(h) for
    h in …))``) : la garde « pas de nouvelles », recopiée."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _named(node.func, "Guard") and any(
                kw.arg == "reads" and next(_over_last_from(kw.value), None) is not None for kw in node.keywords):
            yield node.lineno


def _copies_of_last_heard(tree: ast.Module):
    """Le plus récent des derniers messages de ses adresses (``max(….LAST_FROM(h) … for h in …)``), recopié."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _named(node.func, "max") and node.args \
                and next(_over_last_from(node.args[0]), None) is not None:
            yield node.lineno


def _found(copies) -> set[str]:
    return {f"{p.relative_to(SRC)}:{line}" for p in SRC.rglob("*.py")
            for line in copies(ast.parse(p.read_text(encoding="utf-8")))}


def test_the_initiative_guard_is_written_in_one_place():
    """La garde « pas de nouvelles » vit dans ``contracts/identity.py::heard_since_guard`` : huit copies, sous deux
    noms (« pas de nouvelles » et « silence »), l'ont précédée."""
    found = _found(_copies_of_the_guard)
    assert {f.split(":")[0] for f in found} == {"contracts/identity.py"}, sorted(found)


def test_her_last_message_is_looked_up_in_one_place():
    """« Depuis quand elle ne lui a rien écrit » vit dans ``contracts/identity.py::last_heard``. Seules deux vues de
    la console lisent le plus récent sur une liste d'adresses qu'on leur donne (``everyone_of``), pas une personne."""
    found = _found(_copies_of_last_heard)
    assert {f.split(":")[0] for f in found} == {"contracts/identity.py", "faculties/identity/inspect.py",
                                                "app/handmade/tabs/people.py"}, sorted(found)
