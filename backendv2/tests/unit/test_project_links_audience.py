"""Lire un projet ne change pas qui entend le lecteur (ADR 0262).

- les personnes d'un projet lu — son propriétaire, ses sujets — n'entendent pas plus le projet qui le lit après le
  lien qu'avant : ni son titre, ni son détail, ni ses fichiers ; et aucune autre faculté ne les prend pour des
  personnes que le lecteur concerne ;
- le propriétaire du lecteur entend toujours son projet quand elle prend la parole pour lui, même s'il lit un projet
  plus confidentiel ; une tierce personne n'entend pas ce que le lecteur a repris d'un projet de niveau plus haut ;
- l'oubli d'une personne du projet lu atteint ce que le lecteur écrit après le lien, par tous ses chemins (ses
  outils, la console, une proposition d'effet, un fichier de son atelier qu'elle envoie), et rien de ce qui y était
  avant ;
- chaque événement d'un projet qui garde un texte déclare ces sujets hérités, et chaque endroit qui en émet un les
  passe ;
- tout ce que le lecteur écrit est au niveau hérité : le « pourquoi » et le résumé d'une commande réseau, le résumé
  d'un envoi ; un plan s'écrit au niveau le plus haut parmi le sien et ceux des projets qu'il demande à lire.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

from mika.contracts import identity as identity_c
from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.contracts import shares as shares_c
from mika.contracts import social as social_c
from mika.faculties.projects import faculty, milestones
from mika.faculties.projects.atelier import NetworkArgs, PushArgs, network_proposal, project_push, ws_network
from mika.faculties.projects.faculty import (
    DECIDED,
    INHERITED,
    LINKS_SET,
    NETWORK_QUEUED,
    PLAN_PROPOSED,
    PROJECTS,
    REFRAMED,
    frame_subject,
    subject_of,
    subjects_of,
    written,
)
from mika.faculties.projects.framing_tools import PlanArgs, project_plan
from mika.faculties.projects.prompt import _live_section, _share_section, _texts
from mika.faculties.projects.tools import (
    DecideArgs,
    NoteArgs,
    ObjectiveArgs,
    ReportArgs,
    project_decide,
    project_note,
    project_objective_add,
    report_run,
)
from mika.faculties.shares.tools import may_share
from mika.kernel.events import Content, EventType, Origin
from mika.kernel.frame import Audience, EpisodeRef, Frame
from mika.kernel.prompt import audible
from mika.kernel.state import FrozenDict
from mika.runtime.effects import with_content
from mika.runtime.operations import perform
from mika.vocab import privacy
from mika.vocab.episodes import Kind, project_target
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import ChannelTrust, Sensitivity
from tests.fixtures.atelier import Atelier
from tests.fixtures.mika import connect
from tests.unit import test_shares as shares
from tests.unit.test_projects import create, events, form, live
from tests.unit.test_projects_framing import _asked_project, _ctx

PERSONAL, CONFIDENCE = int(Sensitivity.PERSONAL), int(Sensitivity.CONFIDENCE)
SOURCES = Path(faculty.__file__).parent


def _audience(handle: str, person: str, *, closeness: str = "acquaintance", owner: bool = False) -> Audience:
    """L'audience d'un tête-à-tête, aux niveaux que la vraie règle donne à ce lien (``privacy.decide``) : une
    connaissance entend l'anodin, et le personnel de ce dont elle est témoin ; une amie, le personnel ; qui s'occupe
    d'elle aussi, et la confidence de ce dont il est témoin."""
    d = privacy.decide(1.0, ChannelTrust.AUTHENTICATED, closeness=closeness, owner=owner)
    return Audience(persons=(handle,), channel="web", public=False, level=int(d.level),
                    witness_level=int(d.witness_level), private_ok=d.own_file, trust=ChannelTrust.AUTHENTICATED.value,
                    certainty=1.0, person=person, owner=owner, tied_level=int(d.tied_level),
                    untied_level=int(d.untied_level))


def _facing(kernel, handle: str, audience: Audience, kind: str = Kind.REPLY, **attrs) -> Frame:
    mind = kernel.mind
    return Frame(mind.frame().root, mind.clock.now(), mind.registry, audience,
                 EpisodeRef(f"ep-{handle}-{kind}", kind, target=handle, attrs=FrozenDict(attrs)))


async def _heard(kernel, handle: str, audience: Audience) -> str:
    """Ce qu'elle a sous les yeux de ses projets quand cette personne lui demande « tu travailles sur quoi ? »."""
    frame = _facing(kernel, handle, audience)
    s = frame.state("projects")
    body = _live_section(s, frame, {"projects": await _texts(s, frame, kernel.ports)})
    return str(body.content) if body is not None and audible(body, audience.level, audience.witness_level) else ""


async def _told(kernel, handle: str, audience: Audience, pid: int, oid: int):
    """La section du sujet quand elle prend la parole pour l'objectif ``oid`` du projet ``pid`` devant cette
    personne, et si elle passe la seconde barrière (``audible``)."""
    frame = _facing(kernel, handle, audience, Kind.INITIATIVE, subject=subject_of(pid, oid),
                    args=FrozenDict({"share": social_c.FULL}))
    s = frame.state("projects")
    body = _share_section(s, frame, {"projects": await _texts(s, frame, kernel.ports)})
    return body, audible(body, audience.level, audience.witness_level)


def _run(kernel, name: str, pid: int, oid: int = 0):
    """Un appel d'outil pendant une exécution du projet ``pid`` (qui vise l'objectif ``oid``, s'il est dit)."""
    attrs = {"subject": subject_of(pid, oid)} if oid else {}
    return _ctx(kernel, name, Kind.WORK, project_target(pid), **attrs)


async def _confidence(kernel, pid: int) -> None:
    """Ce projet devient une confidence : plus haut que ce qu'écrit d'ordinaire un projet (« personnel »)."""
    await kernel.mind.append([REFRAMED.draft(project=pid, sensitivity=CONFIDENCE)], emitter="projects",
                             correlation=f"niveau:{pid}", origin=Origin.GENESIS)


async def _reads(kernel, reader: int, target: int, nonce: str) -> int:
    """Adrien fait lire ``target`` par ``reader`` ; rend le numéro de l'événement du lien."""
    got = await perform(kernel, "projects.liens", form(**{f"lit_{target}": "on"}), by="user_1", subject=str(reader),
                        nonce=nonce)
    assert got.ok, got
    return events(kernel, LINKS_SET)[-1].seq


def _objective(kernel, pid: int) -> int:
    return kernel.mind.frame().state("projects").projects[pid].objectives[0].id


def _view(kernel, pid: int) -> c.ProjectView:
    return next(v for v in kernel.mind.frame().get(c.LIVE) if v.id == pid)


# ── Qui entend le lecteur ─────────────────────────────────────────────────


def test_the_people_of_a_project_read_hear_no_more_of_the_reader_than_before(tmp_path):
    """Adrien a « La veille », Bea — une simple connaissance qui a un compte — a « Le carnet de Bea ». Adrien fait
    lire le carnet par sa veille. Bea demande « tu travailles sur quoi ? » : de la veille d'Adrien, elle n'entend
    rien de plus qu'avant le lien — c'est-à-dire rien."""

    async def scenario(kernel, llm):
        await connect(kernel, "user_2", "Bea")
        bea = kernel.mind.frame().get(identity_c.PERSON("user_2"))
        adrien = kernel.mind.frame().get(identity_c.PERSON("user_1"))
        theirs = await create(kernel, "p1", title="Le carnet de Bea", objectives="Tenir le carnet", owner="user_2")
        mine = await create(kernel, "p2", title="La veille d'Adrien", objectives="Surveiller les prix")
        oid = _objective(kernel, mine)
        await report_run(ReportArgs(verdict=c.CONTINUE, summary="Les prix ont monté.",
                                    needs_you="il me faut la clé de l'API"), _run(kernel, "report_run", mine, oid))
        acquaintance = _audience("user_2", bea)
        out = {"before": await _heard(kernel, "user_2", acquaintance),
               "files_before": may_share(_view(kernel, mine), bea, acquaintance, _facing(kernel, "user_2", acquaintance))}
        await _reads(kernel, mine, theirs, "l1")
        # elle y retravaille : un compte rendu, un besoin, puis l'objectif bloque — un événement que lisent
        # l'attention, l'estime et ses envies
        await report_run(ReportArgs(verdict=c.CONTINUE, summary="Lu le carnet de Bea : rien de neuf.",
                                    needs_you="il me faut le mot de passe du carnet"),
                         _run(kernel, "report_run", mine, oid))
        out["after"] = await _heard(kernel, "user_2", acquaintance)
        out["files_after"] = may_share(_view(kernel, mine), bea, acquaintance, _facing(kernel, "user_2", acquaintance))
        out["told"] = await _told(kernel, "user_2", acquaintance, mine, oid)
        await report_run(ReportArgs(verdict=c.BLOCKED, summary="Le carnet est fermé."),
                         _run(kernel, "report_run", mine, oid))
        frame = kernel.mind.frame()
        return bea, adrien, out, frame.state("projects").projects[mine], _view(kernel, mine), \
            events(kernel, c.OBJECTIVE_CLOSED)[-1], frame.state("attention").pending[-1]

    bea, adrien, out, reader, shown, closed, thought = live(tmp_path, scenario)
    # son propre projet, elle l'entend ; celui d'Adrien, non — ni avant le lien, ni après
    assert "Le carnet de Bea" in out["before"] and "La veille d'Adrien" not in out["before"]
    assert out["after"] == out["before"]
    for hidden in ("La veille d'Adrien", "Les prix ont monté", "Lu le carnet", "clé de l'API", "mot de passe"):
        assert hidden not in out["after"], hidden
    assert not out["files_before"] and not out["files_after"]  # ni ses fichiers
    body, _ = out["told"]  # ni par une prise de parole
    assert body.content == phrase("projects.share.something")
    # de qui parle le lecteur n'a pas bougé : Bea n'y figure que pour l'oubli
    assert reader.about == (adrien,) == shown.about and bea in reader.read_about and bea in shown.read_about
    # ce que lisent les autres facultés d'un objectif clos du lecteur ne nomme pas Bea parmi les concernés
    assert closed.data.about == (adrien,) and bea in closed.data.read_about
    assert thought.about == (adrien,)  # la pensée « je bloque sur… » de l'attention


def test_the_owner_still_hears_his_reader_and_a_third_person_not_what_it_took_from_higher(tmp_path):
    """La veille d'Adrien lit un carnet de Bea qui est une confidence. Quand elle vient dire à Adrien ce qu'il lui
    faut, il entend toujours son projet ; Carla, une amie qui entendait le détail de la veille avant le lien,
    n'entend plus ce que la veille écrit depuis qu'elle lit plus confidentiel qu'elle."""

    async def scenario(kernel, llm):
        await connect(kernel, "user_2", "Bea")
        await connect(kernel, "user_3", "Carla")
        frame = kernel.mind.frame()
        adrien, carla = (frame.get(identity_c.PERSON(h)) for h in ("user_1", "user_3"))
        theirs = await create(kernel, "p1", title="Le carnet de Bea", objectives="Tenir le carnet", owner="user_2")
        await _confidence(kernel, theirs)
        mine = await create(kernel, "p2", title="La veille d'Adrien", objectives="Surveiller les prix")
        oid = _objective(kernel, mine)
        owner = _audience("user_1", adrien, closeness="close", owner=True)
        friend = _audience("user_3", carla, closeness="friend")
        await report_run(ReportArgs(verdict=c.CONTINUE, summary="Les prix ont monté.",
                                    needs_you="il me faut la clé de l'API"), _run(kernel, "report_run", mine, oid))
        out = {"owner_before": await _told(kernel, "user_1", owner, mine, oid),
               "friend_before": await _heard(kernel, "user_3", friend)}
        await _reads(kernel, mine, theirs, "l1")
        await report_run(ReportArgs(verdict=c.CONTINUE, summary="Lu le carnet de Bea.",
                                    needs_you="il me faut le mot de passe du carnet"),
                         _run(kernel, "report_run", mine, oid))
        out["owner_after"] = await _told(kernel, "user_1", owner, mine, oid)
        out["owner_talk"] = await _heard(kernel, "user_1", owner)
        out["friend_after"] = await _heard(kernel, "user_3", friend)
        out["friend_told"] = await _told(kernel, "user_3", friend, mine, oid)
        return owner, out, kernel.mind.frame().state("projects").projects[mine]

    owner, out, reader = live(tmp_path, scenario)
    assert written(reader) == CONFIDENCE > owner.level  # ce qu'il écrit dépasse ce qu'Adrien entend d'autrui
    # Adrien, pour son propre projet : dit avant le lien, dit après, sans rien perdre
    before, passed_before = out["owner_before"]
    after, passed_after = out["owner_after"]
    assert passed_before and "La veille d'Adrien" in before.content and "clé de l'API" in before.content
    assert passed_after and "La veille d'Adrien" in after.content and "mot de passe du carnet" in after.content
    assert after.level == before.level == 0  # son projet à lui : rien qui se mesure comme la vie d'un autre
    assert "mot de passe du carnet" in out["owner_talk"]  # et en conversation aussi
    # Carla : elle entendait le détail de la veille ; elle n'entend plus ce qu'elle écrit depuis le lien
    assert "La veille d'Adrien" in out["friend_before"] and "clé de l'API" in out["friend_before"]
    assert "mot de passe du carnet" not in out["friend_after"] and "Lu le carnet" not in out["friend_after"]
    told, _ = out["friend_told"]
    assert told.content == phrase("projects.share.something")


# ── L'oubli atteint ce que le lecteur écrit ensuite ───────────────────────


def _text_refs(kernel, pid: int, after: int) -> dict[str, str]:
    """Les textes gardés par les événements du projet ``pid`` écrits après l'événement ``after`` — les siens, et les
    propositions d'effet faites pour lui : référence → « type.champ »."""
    mind = kernel.mind
    out = {}
    for stored in mind.store.read():
        e = with_content(mind, mind.decode(stored))
        own = getattr(e.data, "project", None) == pid or (e.type.name == c.PROJECT_CREATED.name and e.seq == pid)
        proposed = e.type.name == rt.EFFECT_PROPOSED.name and e.data.context == project_target(pid)
        if e.seq <= after or not (own or proposed):
            continue
        for name in e.type.content_fields:
            value = getattr(e.data, name, None)
            if isinstance(value, Content) and value.ref:
                out[value.ref] = f"{e.type.name}.{name}"
    return out


def test_forgetting_someone_of_a_project_read_reaches_what_the_reader_wrote_since(tmp_path):
    async def scenario(kernel, llm):
        await connect(kernel, "user_2", "Bea")
        bea = kernel.mind.frame().get(identity_c.PERSON("user_2"))
        theirs = await create(kernel, "p1", title="Le carnet de Bea", objectives="Tenir le carnet", owner="user_2")
        mine = await create(kernel, "p2", title="La veille d'Adrien", objectives="Surveiller les prix",
                            approval="on")
        oid = _objective(kernel, mine)
        await project_note(NoteArgs(text="avant le lien"), _run(kernel, "project_note", mine, oid))
        linked = await _reads(kernel, mine, theirs, "l1")
        # par ses outils, pendant une exécution
        await project_note(NoteArgs(text="le carnet avance"), _run(kernel, "project_note", mine, oid))
        await project_decide(DecideArgs(title="Le format", choice="Comme le carnet", reason="pour s'y retrouver"),
                             _run(kernel, "project_decide", mine, oid))
        await project_objective_add(ObjectiveArgs(text="Recouper avec le carnet"),
                                    _run(kernel, "project_objective_add", mine, oid))
        await ws_network(NetworkArgs(argv=["curl", "https://exemple.test"], why="vérifier ce que dit le carnet"),
                         _run(kernel, "ws_network", mine, oid))
        await report_run(ReportArgs(verdict=c.CONTINUE, summary="Lu le carnet.", needs_you="un accès au carnet"),
                         _run(kernel, "report_run", mine, oid))
        # par la console : une consigne, un objectif, une décision
        for action, fields in (("consigne", {"instruction": "Cite le carnet"}),
                               ("objectif_ajouter", {"text": "Résumer le carnet", "kind": "once",
                                                     "cadence_hours": "0"}),
                               ("decision_ajouter", {"title": "La source", "choice": "Le carnet", "replaces": "0"})):
            got = await perform(kernel, f"projects.{action}", form(**fields), by="user_1", subject=str(mine),
                                nonce=action)
            assert got.ok, (action, got)
        store = kernel.ports["store"]
        mine_before = _text_refs(kernel, mine, 0)
        since = _text_refs(kernel, mine, linked)
        kept = dict(store.content(list(mine_before)))
        await kernel.forget(bea)
        return mine_before, since, kept, dict(store.content(list(mine_before)))

    everything, since, kept, left = live(tmp_path, scenario)
    assert set(kept) == set(everything)  # tout se lisait avant l'oubli
    written_since = set(since.values())
    for wanted in ("projects.noted.text", "projects.decided.title", "projects.decided.choice",
                   "projects.decided.reason", "projects.objective_added.text", "effect.proposed.summary",
                   "projects.run_reported.summary", "projects.run_reported.need", "projects.amended.instruction"):
        assert wanted in written_since, wanted
    # ce que le lecteur a écrit depuis le lien : effacé, quel que soit le chemin
    assert not set(since) & set(left), sorted(since[r] for r in set(since) & set(left))
    # ce qui y était avant : intact — son titre, son premier objectif, sa note d'avant
    before = set(everything) - set(since)
    assert before and before <= set(left) and "avant le lien" in left.values()
    assert "La veille d'Adrien" in left.values()


def test_a_file_shared_from_the_reader_is_judged_on_its_own_people_and_forgotten_with_those_it_reads(tmp_path):
    """Un fichier de l'atelier du lecteur peut reprendre ce qu'il a lu : envoyé, il porte les personnes du projet lu
    parmi ses sujets, pour l'oubli. Qui peut le recevoir se juge sur le lecteur seul : Béa, dont le projet est lu,
    n'y a pas droit pour autant."""
    atelier = Atelier()

    async def scenario(kernel, store, llm, deliveries):
        bea = kernel.mind.frame().get(identity_c.PERSON("user_2"))
        theirs = await shares._project(kernel, "p1", title="Le carnet de Béa", owner="user_2")
        mine = await shares._project(kernel, "p2", title="La veille")
        await atelier.write(mine, "notes.md", "ce que dit le carnet")
        await _reads(kernel, mine, theirs, "l1")
        out = {"owner": await shares.call(kernel, "share_project_file", "user_1", project=mine, path="notes.md"),
               "read": await shares.call(kernel, "share_project_file", "user_2", project=mine, path="notes.md")}
        sent = shares.journal(kernel, shares_c.SHARED)
        kept = store.files()
        await kernel.forget(bea)
        return bea, out, sent, kept, store.files()

    bea, out, sent, kept, left = shares.live(tmp_path, scenario, atelier=atelier)
    assert out["owner"].ok and not out["read"].ok
    assert out["read"].content == phrase("shares.tools.project_files.not_shared")
    [shared] = sent
    assert shared.data.target == "user_1" and bea in shared.data.about  # un sujet de plus, pour l'oubli
    assert kept == [shared.data.file] and left == []  # ses octets partent avec l'oubli de Béa


# ── Chaque événement qui garde un texte porte les sujets hérités ──────────


def _event_types() -> dict[str, EventType]:
    """Les types d'événements des projets, par le nom sous lequel le code les écrit (``NOTED``, ``RUN_REPORTED``) :
    ceux de ``faculty.py``, du contrat, et des sous-sujets qui en sont sortis (les jalons, ADR 0313)."""
    found = {}
    for module in (faculty, c, milestones):
        for name, value in vars(module).items():
            if isinstance(value, EventType) and value.owner == PROJECTS.name:
                found[name] = value
    return found


def test_every_project_event_that_keeps_a_text_declares_the_inherited_subjects():
    """Sauf sa création : un projet naît avant tout lien."""
    kept = [t for t in PROJECTS.events.values() if t.content_fields and t is not c.PROJECT_CREATED]
    assert len(kept) >= 13 and DECIDED in kept and c.RUN_REPORTED in kept
    for t in kept:
        assert INHERITED in t.subject_fields and INHERITED in t.payload.model_fields, t.name
        assert "about" in t.subject_fields, t.name
    # et c'est tout ce que l'oubli en lit : un sujet hérité n'est jamais dans ``about``
    assert INHERITED == "read_about" != "about"


#: où un événement qui garde un texte s'écrit sans sujets hérités, et pourquoi
BORN_BEFORE_ANY_LINK = {"objectives_of": "les objectifs d'un projet qui vient de naître : il ne lit encore rien"}


def test_every_place_that_writes_such_an_event_passes_the_inherited_subjects():
    """Par l'AST (pas par le texte du source) : chaque ``X.draft(…)`` d'un événement qui déclare ``read_about`` le
    passe, en clair ou par un dictionnaire déplié (``**who``)."""
    types = _event_types()
    missing, seen = [], 0
    for path in sorted(SOURCES.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef) or fn.name in BORN_BEFORE_ANY_LINK:
                continue
            for node in ast.walk(fn):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) \
                        or node.func.attr != "draft":
                    continue
                target = node.func.value
                name = target.id if isinstance(target, ast.Name) else \
                    target.attr if isinstance(target, ast.Attribute) else ""
                t = types.get(name)
                if t is None or INHERITED not in t.subject_fields:
                    continue
                seen += 1
                keywords = {k.arg for k in node.keywords}
                if INHERITED not in keywords and None not in keywords:
                    missing.append(f"{path.name}:{node.lineno} {name}.draft dans {fn.name}")
    assert seen >= 25 and not missing, missing
    assert importlib.import_module("mika.faculties.projects.faculty").objectives_of  # l'exception existe encore


def test_what_is_kept_outside_its_own_events_takes_them_for_forgetting_only():
    """Le résumé d'une proposition d'effet et ce que ses lecteurs héritent : tous ceux que l'oubli doit atteindre,
    chacun une fois, qui le demande d'abord."""
    reader = faculty.Project(id=2, title_ref="t", authority=c.USER, created_at=0, owner="adrien", about=("adrien",),
                             read_about=("bea", "carla"))
    assert subjects_of(reader) == ("adrien", "bea", "carla")
    assert subjects_of(reader, "dan", None, "bea") == ("dan", "bea", "adrien", "carla")
    assert faculty.view(reader).about == ("adrien",)  # ce que lisent les autres facultés et le partage de fichiers


# ── Tout ce que le lecteur écrit est au niveau hérité ─────────────────────


def test_what_the_reader_writes_to_leave_the_machine_is_at_the_inherited_level(tmp_path):
    async def scenario(kernel, llm):
        await connect(kernel, "user_2", "Bea")
        bea = kernel.mind.frame().get(identity_c.PERSON("user_2"))
        theirs = await create(kernel, "p1", title="Le carnet de Bea", objectives="Tenir le carnet", owner="user_2")
        await _confidence(kernel, theirs)
        # sans relecture indépendante : depuis l'ADR 0276, un envoi qui part d'elle attend le verdict de son commit,
        # et ce test garde le niveau de ce qui part, pas la relecture (``test_project_reviews.py``)
        asks = await create(kernel, "p2", title="La veille", objectives="Surveiller les prix", approval="on",
                            remote="https://github.com/adrien/veille.git", reread="never")
        alone = await create(kernel, "p3", title="Le bilan", objectives="Faire le bilan")  # sans accord requis
        for n, reader in enumerate((asks, alone)):
            await _reads(kernel, reader, theirs, f"l{n}")
        atelier = kernel.ports["workshop"]
        await atelier.write(asks, "notes.md", "ce que dit le carnet\n")
        assert await atelier.commit(asks, "des notes")
        why = "comparer avec ce que dit le carnet"
        await ws_network(NetworkArgs(argv=["curl", "https://exemple.test"], why=why), _run(kernel, "ws_network", asks))
        await project_push(PushArgs(why="envoyer mes notes sur le carnet"), _run(kernel, "project_push", asks))
        await ws_network(NetworkArgs(argv=["curl", "https://exemple.test"], why=why), _run(kernel, "ws_network", alone))
        s = kernel.mind.frame().state("projects")
        return bea, s.projects[asks], s.projects[alone], events(kernel, rt.EFFECT_PROPOSED), \
            events(kernel, NETWORK_QUEUED)

    bea, asks, alone, proposed, queued = live(tmp_path, scenario)
    assert asks.sensitivity == alone.sensitivity == PERSONAL and written(asks) == written(alone) == CONFIDENCE
    network, push = proposed
    # une commande réseau qui attend un accord, et un envoi au dépôt distant : son résumé porte ses mots
    assert "comparer avec ce que dit le carnet" in network.data.summary.text
    assert network.data.summary.level == CONFIDENCE and bea in network.data.about
    assert "envoyer mes notes sur le carnet" in push.data.summary.text
    assert push.data.summary.level == CONFIDENCE and bea in push.data.about
    # sans accord requis : son « pourquoi » attend la fin de l'exécution, puis part dans un résumé — au même niveau
    [waiting] = queued
    assert waiting.data.why.level == CONFIDENCE and bea in waiting.data.read_about and bea not in waiting.data.about
    later = network_proposal(alone, waiting.seq, waiting.data.argv, waiting.data.why.text)
    assert later.data.summary.level == CONFIDENCE and bea in later.data.about


PLAN = {"aim": "Suivre ce que dit le carnet de Bea.", "deliverables": "Un point par semaine.",
        "approach": "Je lis le carnet, puis j'écris.",
        "steps": [{"text": "Écrire le point de la semaine", "kind": "constant", "cadence_hours": 168}]}


def test_a_plan_is_written_at_the_highest_level_among_its_project_and_those_it_asks_to_read(tmp_path):
    """Une séance de cadrage voit le titre des projets qu'elle peut demander à lire, et son plan les nomme — avant
    tout lien, donc avant que le projet n'hérite de leur niveau."""

    async def scenario(kernel, llm):
        await connect(kernel, "user_2", "Bea")
        bea = kernel.mind.frame().get(identity_c.PERSON("user_2"))
        theirs = await create(kernel, "p1", title="Le carnet de Bea", objectives="Tenir le carnet", owner="user_2")
        await _confidence(kernel, theirs)
        plain = await create(kernel, "p2", title="Le site", objectives="Le mettre en ligne")
        pid = await _asked_project(kernel)  # un projet à elle, demandé par Adrien : il naît à cadrer
        framing = _ctx(kernel, "project_plan", Kind.WORK, project_target(pid), subject=frame_subject(pid))
        before = kernel.mind.frame().state("projects").projects[pid]
        got = await project_plan(PlanArgs.model_validate({**PLAN, "reads": [plain, theirs]}), framing)
        assert got.ends, got
        return bea, before, events(kernel, PLAN_PROPOSED)[-1], \
            [e for e in events(kernel, faculty.OBJECTIVE_ADDED) if e.data.project == pid][-1]

    bea, before, plan, step = live(tmp_path, scenario)
    assert written(before) == PERSONAL and before.reads == () and before.read_level == 0  # aucun lien encore
    assert plan.data.reads and plan.data.plan.level == CONFIDENCE  # le plus haut : celui du carnet
    assert step.data.text.level == CONFIDENCE  # ses étapes aussi : elles nomment ce qu'il lira
    # et l'oubli de Bea atteindra ce plan, qui nomme son carnet
    assert bea in plan.data.read_about and bea in step.data.read_about and bea not in plan.data.about
