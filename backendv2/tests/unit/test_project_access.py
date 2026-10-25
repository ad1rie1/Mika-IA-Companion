"""Qui peut quoi sur un projet (ADR 0133), par ses intentions.

- un projet dont on n'a jamais réglé les accès fait ce qu'il faisait : toi, tout ; les autres l'entendent selon sa
  confidentialité, sans le piloter ;
- un opérateur règle ses lignes d'un coup (``projects.acces``), journalisées ; la première qui désigne qui est en face
  décide — le voir, le piloter ; une ligne ajoutée est fermée ; une ligne illisible est refusée ;
- piloter « seule » écrit le geste aussitôt, au nom de qui l'a demandé ; « ton accord » le garde et le propose :
  accepté, il s'écrit ; refusé, rien ;
- sans « voir », elle n'en parle pas ; jamais dans un salon ni avec une inconnue.
"""

from __future__ import annotations

import asyncio
import itertools

from mika.app.mindport import KernelPort
from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.faculties.projects.access import line_for, sees, steering
from mika.faculties.projects.faculty import ACCESS_SET, AMENDED, PAUSED
from mika.faculties.projects.prompt import _live_section
from mika.faculties.projects.tools import SteerArgs, may_steer, project_steer
from mika.kernel.frame import Audience, EpisodeRef, Frame
from mika.runtime.operations import perform
from mika.runtime.tools import ToolContext, offer
from mika.vocab.episodes import Kind
from mika.vocab.privacy import ChannelTrust
from tests.fixtures.mika import connect
from tests.unit.test_projects import create, events, live

FIELDS = ["qui", "toujours", "moments", "voir", "piloter", "lecture", "action", "tous", "prend", "defaut_voir",
          "defaut_piloter", "defaut_lecture", "defaut_action", "faire"]


def access_form(*rows: dict, faire: str = "", **default: str) -> dict[str, list[str]]:
    """Le tableau tel que la page l'envoie : ``rows`` (qui, quand, voir, piloter, lecture, action, outils)."""
    data: dict[str, list[str]] = {"_champs": FIELDS, "faire": [faire]}
    for n, r in enumerate(rows, start=1):
        data[f"qui.{n}"] = [r["who"]]
        for m in r.get("when", ()):
            data[f"moments.{n}|{m}"] = ["on"]
        if not r.get("when"):
            data[f"toujours.{n}"] = ["on"]
        if r.get("see"):
            data[f"voir.{n}"] = ["on"]
        data[f"piloter.{n}"] = [r.get("steer", "non")]
        data[f"lecture.{n}"] = [r.get("read", "non")]
        data[f"action.{n}"] = [r.get("act", "non")]
        for t in r.get("tools", ()):
            data[f"prend.{n}|{t}"] = ["on"]
        if not r.get("tools"):
            data[f"tous.{n}"] = ["on"]
    for k, v in {"piloter": "non", "lecture": "non", "action": "non", **default}.items():
        data[f"defaut_{k}"] = [v]  # la page les envoie toujours (une case décochée, elle, n'arrive pas)
    return data


def facing(person: str, *, owner: bool = False, room: str | None = None, trust: str = ChannelTrust.AUTHENTICATED.value):
    return Audience(persons=(person,), channel="web", public=bool(room), room=room, trust=trust, owner=owner,
                    person=person, level=3, witness_level=3, private_ok=True)


_CALLS = itertools.count(1)


def talking(kernel, handle: str, audience: Audience, tool: str = "project_steer") -> ToolContext:
    """Le contexte d'un outil pendant une réponse à ``handle`` (un épisode, un appel : chaque fois les siens)."""
    mind, n = kernel.mind, next(_CALLS)
    episode = EpisodeRef(f"ep-{handle}-{n}", Kind.REPLY, target=handle)
    frame = Frame(mind.frame().root, mind.clock.now(), mind.registry, audience, episode)
    return ToolContext(mind, mind.registry.tools[tool], f"appel-{n}", f"ep-{handle}-{n}", frame, ports=kernel.ports)


async def set_access(kernel, pid: int, *rows: dict, nonce: str, faire: str = "", **default: str):
    got = await perform(kernel, "projects.acces", access_form(*rows, faire=faire, **default), by="user_1",
                        subject=str(pid), nonce=nonce)
    return got


def test_a_project_never_set_does_what_it_did_and_an_operator_sets_its_rows_at_once(tmp_path):
    async def scenario(kernel, llm):
        pid = await create(kernel, "p1", title="Le site", objectives="Écrire la page d'accueil")
        out = {"before": kernel.mind.frame().get(c.LIVE)[0]}
        out["added"] = await set_access(kernel, pid, faire="ajouter", nonce="a0", voir="on")
        out["closed"] = kernel.mind.frame().get(c.LIVE)[0]
        out["saved"] = await set_access(kernel, pid, {"who": "personne:user_2", "see": True, "steer": "seule"},
                                        {"who": "comptes", "when": ["conversation"], "see": True}, nonce="a1")
        out["refused"] = await set_access(kernel, pid, {"who": "personne: user 2"}, nonce="a2")
        out["no_moment"] = await set_access(kernel, pid, {"who": "toi", "when": ["jamais"]}, nonce="a3")
        out["after"] = kernel.mind.frame().get(c.LIVE)[0]
        return pid, out

    pid, out = live(tmp_path, scenario)
    before = out["before"]
    assert (before.access, before.default_access) == (c.BEFORE_0133, c.BEFORE_0133_DEFAULT)
    owner, friend = facing("user_1", owner=True), facing("user_2")
    assert steering(before, owner, Kind.REPLY) == "seule" and steering(before, friend, Kind.REPLY) == "non"
    assert sees(before, friend, Kind.REPLY)  # comme avant : sa confidentialité décide
    # ajouter : une ligne fermée, enregistrée aussitôt
    assert out["added"].ok and "fermée" in out["added"].message
    assert out["closed"].access == (c.ProjectAccess(who="toi"),) and out["closed"].default_access.see
    assert steering(out["closed"], owner, Kind.REPLY) == "non"
    # deux lignes, de haut en bas ; la ligne par défaut fermée
    after = out["after"]
    assert out["saved"].ok and [a.who for a in after.access] == ["personne:user_2", "comptes"]
    assert steering(after, friend, Kind.REPLY) == "seule"
    assert steering(after, facing("user_3"), Kind.REPLY) == "non" and sees(after, facing("user_3"), Kind.REPLY)
    assert not sees(after, facing("user_3"), Kind.INITIATIVE)  # « quand elle répond » seulement
    assert not sees(after, owner, Kind.REPLY)  # toi n'a plus de ligne : la ligne par défaut, fermée
    # jamais dans un salon ni avec une inconnue, quelles que soient les lignes
    assert line_for(after, facing("user_2", room="salon"), Kind.REPLY) is None
    assert line_for(after, facing("web_x", trust=ChannelTrust.ACCOUNT.value), Kind.REPLY) is None
    # une ligne illisible : refusée, rien n'est écrit
    assert not out["refused"].ok and "Ligne 1 : choisis qui." in out["refused"].message
    assert not out["no_moment"].ok and "coche au moins un moment" in out["no_moment"].message


def test_steering_alone_writes_at_once_and_on_your_approval_waits_for_it(tmp_path):
    async def scenario(kernel, llm):
        await connect(kernel, "user_2", "Camille")
        pid = await create(kernel, "p1", title="Le site", objectives="Écrire la page d'accueil")
        camille = facing("user_2")
        out = {"before": may_steer(camille, Kind.REPLY, kernel.mind.frame())}
        await set_access(kernel, pid, {"who": "personne:user_2", "see": True, "steer": "seule"},
                         {"who": "toi", "see": True, "steer": "seule"}, nonce="a1")
        frame = kernel.mind.frame()
        policy = kernel.runner.policies[Kind.REPLY]
        out["offered"] = "project_steer" in offer(kernel.mind.registry.tools, policy, Kind.REPLY, camille,
                                                  frame=frame)
        out["not_offered"] = "project_steer" in offer(kernel.mind.registry.tools, policy, Kind.REPLY,
                                                      facing("user_3"), frame=frame)
        out["alone"] = await project_steer(_args(pid, what="pause"), talking(kernel, "user_2", camille))
        out["paused"] = events(kernel, PAUSED)
        # sur ton accord : la demande attend, rien ne change avant l'accord
        await set_access(kernel, pid, {"who": "personne:user_2", "see": True, "steer": "toi"},
                         {"who": "toi", "see": True, "steer": "seule"}, nonce="a2")
        out["asked"] = await project_steer(_args(pid, what="instruct", text="Une page plus sobre."),
                                           talking(kernel, "user_2", camille))
        out["amended_before"] = events(kernel, AMENDED)
        [pending] = [v for v in kernel.mind.frame().get(rt.PENDING_EFFECTS) if v.capability == "projects.steer"]
        port = KernelPort(kernel)
        preview = await port.effect_preview(pending.proposal)
        out["preview"] = preview.text
        out["summary"] = events(kernel, rt.EFFECT_PROPOSED)[-1].data.summary.text
        out["resolved"] = await port.resolve_effect(pending.proposal, True, by="user_1", seen=preview.digest)
        for _ in range(20):
            if events(kernel, AMENDED):
                break
            await asyncio.sleep(1)
        out["amended"] = events(kernel, AMENDED)
        # refusée : rien
        out["asked_again"] = await project_steer(_args(pid, what="instruct", text="Tout en rouge."),
                                                 talking(kernel, "user_2", camille))
        [again] = [v for v in kernel.mind.frame().get(rt.PENDING_EFFECTS) if v.capability == "projects.steer"]
        preview = await port.effect_preview(again.proposal)
        out["refused"] = await port.resolve_effect(again.proposal, False, by="user_1", seen=preview.digest)
        await asyncio.sleep(5)
        out["amended_end"] = events(kernel, AMENDED)
        return pid, out

    pid, out = live(tmp_path, scenario)
    assert out["before"] is False  # avant : Camille ne pilote rien
    assert out["offered"] and not out["not_offered"]
    [paused] = out["paused"]  # aussitôt, à son nom
    assert paused.data.by == "user_2" and "pause" in str(out["alone"])
    assert "Demande transmise" in str(out["asked"]) and out["amended_before"] == []
    assert "Camille demande, pour le projet « Le site » : la consigne « Une page plus sobre. »" in out["summary"]
    assert "Demandé par : Camille" in out["preview"] and "« Une page plus sobre. »" in out["preview"]
    [amended] = out["amended"]
    assert amended.data.by == "user_2" and amended.data.instruction.text == "Une page plus sobre."
    assert len(out["amended_end"]) == 1  # la refusée ne s'est pas écrite


def _args(pid: int, **values) -> SteerArgs:
    return SteerArgs(project=str(pid), **values)


def test_without_see_she_does_not_speak_of_it(tmp_path):
    async def scenario(kernel, llm):
        await connect(kernel, "user_2", "Camille")
        pid = await create(kernel, "p1", title="Le site secret", objectives="Écrire la page d'accueil")
        await set_access(kernel, pid, {"who": "toi", "see": True, "steer": "seule"}, nonce="a1")
        mind = kernel.mind
        sections = {}
        for handle, aud in (("user_1", facing("user_1", owner=True)), ("user_2", facing("user_2"))):
            frame = Frame(mind.frame().root, mind.clock.now(), mind.registry, aud,
                          EpisodeRef(f"ep-{handle}", Kind.REPLY, target=handle))
            texts = {v.title_ref: "Le site secret" for v in frame.get(c.LIVE)}
            body = _live_section(frame.state("projects"), frame, {"projects": {"texts": texts}})
            sections[handle] = str(body.content) if body is not None else ""
        return events(kernel, ACCESS_SET), sections

    access, sections = live(tmp_path, scenario)
    assert len(access) == 1
    assert "Le site secret" in sections["user_1"] and "Le site secret" not in sections["user_2"]

