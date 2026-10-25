"""Qui peut quoi sur un projet (ADR 0133), par ses intentions.

- un projet dont on n'a jamais réglé les accès : toi et elle qui travaille, tout ; les autres l'entendent selon sa
  confidentialité, en lecture seule ;
- un opérateur règle ses lignes d'un coup (``projects.acces``), journalisées ; la première qui désigne qui est en face
  décide — le voir, piloter projet ; une ligne ajoutée est fermée ; une ligne illisible est refusée ;
- piloter projet : en lecture seule, elle en dit le détail sans rien y changer ; en modification, la demande s'écrit
  aussitôt, au nom de qui l'a faite ; sur l'accord du propriétaire, elle est gardée et proposée : acceptée, elle
  s'écrit ; refusée, rien — toi en face, l'accord, c'est le tien : aussitôt ;
- une ligne coche ses sources : toi, tes proches en privé, tout le monde, des personnes ; sans « voir », elle n'en
  parle pas ; « tout le monde » le laisse voir et lire aussi dans un salon ou à une inconnue, jamais y changer quoi
  que ce soit.
"""

from __future__ import annotations

import asyncio
import itertools
from dataclasses import replace
from types import SimpleNamespace as NS

from mika.app.mindport import KernelPort
from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.faculties.projects.access import allowance, reads, sees, steering
from mika.faculties.projects.faculty import ACCESS_SET, AMENDED, PAUSED
from mika.faculties.projects.prompt import _live_section
from mika.faculties.projects.tools import SteerArgs, may_steer, project_steer
from mika.kernel.frame import Audience, EpisodeRef, Frame
from mika.runtime.operations import perform
from mika.runtime.tools import ToolContext, offer
from mika.vocab.access import CLOSE, EVERYONE, OWNER, PERSON
from mika.vocab.episodes import Kind
from mika.vocab.privacy import ChannelTrust
from tests.fixtures.mika import connect
from tests.unit.test_projects import create, events, live

FIELDS = ["ligne", "qui", "canal", "toujours", "moments", "voir", "piloter", "fichiers", "lecture", "action", "tous",
          "prend", "defaut_voir", "defaut_piloter", "defaut_fichiers", "defaut_lecture", "defaut_action", "faire"]
#: ce qu'elle vit, réduit à qui lui est proche (user_3) : la règle lit ses tableaux et ce lien par le cadre
NEAR = NS(env=NS(closeness=lambda frame: {"user_3"}.__contains__, access_tables=None), episode=None, audience=None)


def access_form(*rows: dict, faire: str = "", **default: str) -> dict[str, list[str]]:
    """Le tableau tel que la page l'envoie : ``rows`` (ses sources, quand, voir, piloter, lecture, action,
    outils)."""
    data: dict[str, list[str]] = {"_champs": FIELDS, "faire": [faire]}
    for n, r in enumerate(rows, start=1):
        data[f"ligne.{n}"] = [str(n)]
        for w in r["who"]:
            data[f"qui.{n}|{w}"] = ["on"]
        for m in r.get("when", ()):
            data[f"moments.{n}|{m}"] = ["on"]
        if not r.get("when"):
            data[f"toujours.{n}"] = ["on"]
        if r.get("see"):
            data[f"voir.{n}"] = ["on"]
        if r.get("files"):
            data[f"fichiers.{n}"] = ["on"]
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
        out["saved"] = await set_access(kernel, pid, {"who": [PERSON + "user_2"], "see": True, "steer": "modification"},
                                        {"who": [CLOSE], "when": ["conversation"], "see": True}, nonce="a1")
        out["refused"] = await set_access(kernel, pid, {"who": [PERSON + " user 2"]}, nonce="a2")
        out["no_moment"] = await set_access(kernel, pid, {"who": [OWNER], "when": ["jamais"]}, nonce="a3")
        out["after"] = kernel.mind.frame().get(c.LIVE)[0]
        await set_access(kernel, pid, {"who": [EVERYONE], "see": True, "steer": "modification"}, nonce="a4")
        out["everyone"] = kernel.mind.frame().get(c.LIVE)[0]
        return pid, out

    pid, out = live(tmp_path, scenario)
    before = out["before"]
    # jamais réglé : toi et elle seule, tout ; la personne qui l'a confié (ici, toi aussi) le voit, le pilote sur
    # ton accord et en reçoit les fichiers (ADR 0134)
    confider = c.ProjectAccess(who=(PERSON + "user_1",), see=True, steer=c.STEER_ASK, files=True)
    assert (before.access, before.default_access) == ((*c.UNSET, confider), c.UNSET_DEFAULT)
    owner, friend = facing("user_1", owner=True), facing("user_2")
    assert steering(before, owner, Kind.REPLY) == "modification" and steering(before, friend, Kind.REPLY) == "lecture"
    assert allowance(before, owner, Kind.REPLY).files and not allowance(before, friend, Kind.REPLY).files
    assert sees(before, friend, Kind.REPLY) and reads(before, friend, Kind.REPLY)  # sa confidentialité filtre
    # ajouter : une ligne fermée, enregistrée aussitôt
    assert out["added"].ok and "fermée" in out["added"].message
    assert out["closed"].access == (c.ProjectAccess(who=(OWNER,)),) and out["closed"].default_access.see
    assert steering(out["closed"], owner, Kind.REPLY) == "non"
    # deux lignes, de haut en bas ; la ligne par défaut fermée
    after = out["after"]
    assert out["saved"].ok and [a.who for a in after.access] == [(PERSON + "user_2",), (CLOSE,)]
    assert steering(after, friend, Kind.REPLY) == "modification"
    user_3 = facing("user_3")
    assert steering(after, user_3, Kind.REPLY, NEAR) == "non" and sees(after, user_3, Kind.REPLY, NEAR)
    assert not sees(after, user_3, Kind.REPLY)  # sans lien « proche » : la ligne par défaut, fermée
    assert not sees(after, user_3, Kind.INITIATIVE, NEAR)  # « quand elle répond » seulement
    assert not sees(after, owner, Kind.REPLY)  # toi n'a plus de ligne : la ligne par défaut, fermée
    # dans un salon ou avec une inconnue, seule « tout le monde » désigne : ces lignes-là, non
    assert not sees(after, facing("user_2", room="salon"), Kind.REPLY)
    assert not sees(after, facing("web_x", trust=ChannelTrust.ACCOUNT.value), Kind.REPLY)
    # tout le monde : chacun en tête-à-tête ; le voir et le lire, aussi dans un salon ou avec une inconnue — y
    # changer quelque chose, jamais (le plafond : lecture seule au plus)
    everyone, room = out["everyone"], facing("user_2", room="salon")
    stranger = facing("web_x", trust=ChannelTrust.ACCOUNT.value)
    assert steering(everyone, user_3, Kind.REPLY) == steering(everyone, owner, Kind.REPLY) == "modification"
    assert sees(everyone, room, Kind.REPLY) and sees(everyone, stranger, Kind.REPLY)
    assert reads(everyone, room, Kind.REPLY) and reads(everyone, stranger, Kind.REPLY)
    assert steering(everyone, room, Kind.REPLY) == steering(everyone, stranger, Kind.REPLY) == "lecture"
    assert not allowance(everyone, room, Kind.REPLY).files and not allowance(everyone, stranger, Kind.REPLY).files
    # lecture seule : elle en dit le détail, rien ne s'y change ; aucun pilotage : le titre seulement ; l'accord du
    # propriétaire, toi en face, c'est le tien
    reader = replace(after, access=(c.ProjectAccess(who=(PERSON + "user_2",), see=True, steer="lecture"),
                                    c.ProjectAccess(who=(OWNER,), see=True, steer="accord"),
                                    c.ProjectAccess(who=(EVERYONE,), see=True)))
    assert reads(reader, friend, Kind.REPLY) and steering(reader, friend, Kind.REPLY) == "lecture"
    assert not allowance(reader, friend, Kind.REPLY).files and allowance(reader, owner, Kind.REPLY).why
    assert sees(reader, user_3, Kind.REPLY) and not reads(reader, user_3, Kind.REPLY)
    assert steering(reader, owner, Kind.REPLY) == "modification"
    # une ligne illisible : refusée, rien n'est écrit
    assert not out["refused"].ok and "Ligne 1 : source inconnue" in out["refused"].message
    assert not out["no_moment"].ok and "coche au moins un moment" in out["no_moment"].message


def test_steering_alone_writes_at_once_and_on_your_approval_waits_for_it(tmp_path):
    async def scenario(kernel, llm):
        await connect(kernel, "user_2", "Camille")
        pid = await create(kernel, "p1", title="Le site", objectives="Écrire la page d'accueil")
        camille = facing("user_2")
        out = {"before": may_steer(camille, Kind.REPLY, kernel.mind.frame())}
        await set_access(kernel, pid, {"who": [PERSON + "user_2"], "see": True, "steer": "modification"},
                         {"who": [OWNER], "see": True, "steer": "modification"}, nonce="a1")
        frame = kernel.mind.frame()
        policy = kernel.runner.policies[Kind.REPLY]
        out["offered"] = "project_steer" in offer(kernel.mind.registry.tools, policy, Kind.REPLY, camille,
                                                  frame=frame)
        out["not_offered"] = "project_steer" in offer(kernel.mind.registry.tools, policy, Kind.REPLY,
                                                      facing("user_3"), frame=frame)
        out["alone"] = await project_steer(_args(pid, what="pause"), talking(kernel, "user_2", camille))
        out["paused"] = events(kernel, PAUSED)
        # sur ton accord : la demande attend, rien ne change avant l'accord
        await set_access(kernel, pid, {"who": [PERSON + "user_2"], "see": True, "steer": "accord"},
                         {"who": [OWNER], "see": True, "steer": "modification"}, nonce="a2")
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
        await set_access(kernel, pid, {"who": [OWNER], "see": True, "steer": "modification"}, nonce="a1")
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

