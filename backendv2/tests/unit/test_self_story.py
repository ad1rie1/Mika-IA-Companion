"""Le récit qu'elle fait d'elle-même (« QUI TU ES DEVENUE », ADR 0053), par ses intentions.

Sonde réelle du 2026-10-03 : la semaine où le chat de Sam est mort, son récit a été réécrit à partir de « Sam est
parti en disant 'allez j'y vais' » et « je vais essayer de dormir » — les deux seuls souvenirs anodins, les plus
récents. Ce qui l'avait marquée (une perte chez quelqu'un qui compte, sa confiance) était personnel, donc absent.

- le récit choisit ses matériaux par saillance (importance, émotion), pas par ordre d'arrivée ;
- ce qui l'a marquée sans pouvoir se raconter y entre par ce que ça lui a fait — jamais qui, ni quoi.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace

from mika.contracts import memory as memory_c
from mika.faculties.self import SelfParams
from mika.kernel.clock import MINUTE, US
from mika.kernel.events import Content, Origin
from mika.ports.llm import LLMResponse
from mika.sim.clock import run_virtual
from tests.fixtures.mika import at_paris, befriend, boot, build

MARKING = "J'ai appris à rester là, sans rien dire, quand quelqu'un a de la peine"
BANAL = ["Quelqu'un est parti en disant « allez j'y vais »", "On m'a dit « je vais essayer de dormir »",
         "On m'a dit bonjour ce matin", "Quelqu'un a dit « bon, à plus »", "On m'a demandé l'heure",
         "Quelqu'un a dit « ok »"]


def respond(req):
    if req.role == "narrative":
        return LLMResponse("Je suis quelqu'un qui apprend à rester là.")
    if req.role in ("extract", "profile", "compact"):
        return LLMResponse("{}")
    return LLMResponse("d'accord [EMOTION:happy:0.5]")


def souvenir(text, *, importance, emotion=None, about=(), sensitivity=1):
    return memory_c.REMEMBERED.draft(text=Content.of(text, level=sensitivity), about=about, sensitivity=sensitivity,
                                     importance=importance, emotion=emotion)


def narrated_from(tmp_path):
    kernel, clock, llm, _ = build(tmp_path, respond, start=at_paris(2026, 10, 6, 21, 0))

    async def main():
        await boot(kernel)
        try:
            await kernel.set_params("self", SelfParams(narrative_max_souvenirs=5))
            await befriend(kernel, "user_1", "close")
            # le plus marquant est le plus ancien ; la confidence ne se raconte pas ; puis des banalités récentes
            drafts = [souvenir(MARKING, importance=0.9, emotion="sad"),
                      souvenir("CANARI-CONFIDENCE Pixel, le chat de Sam, est mort", importance=0.95, emotion="sad",
                               about=("user_1",), sensitivity=3),
                      *(souvenir(t, importance=0.2) for t in BANAL)]
            await kernel.mind.append(drafts, emitter="memory", correlation="genese", origin=Origin.GENESIS)
            await asyncio.sleep(10 * MINUTE / US)
        finally:
            await kernel.stop()

    run_virtual(clock, main)
    return [c.messages[-1].content for c in llm.calls if c.role == "narrative"]


def test_her_story_starts_from_what_marked_her_not_from_the_latest_trifles(tmp_path):
    shown = narrated_from(tmp_path)
    assert shown, "elle a réécrit son récit"
    told = shown[-1].split("Ce que tu as vécu, du plus marquant au moins marquant :\n", 1)[1].splitlines()
    assert told[0] == f"- {MARKING}"  # avant : les cinq plus récents — des banalités, et pas lui
    assert len(told) == 5 and sum(1 for t in told if t[2:] in BANAL) == 4


def test_what_marked_her_but_cannot_be_told_enters_only_as_what_it_did_to_her(tmp_path):
    shown = narrated_from(tmp_path)[-1]
    assert "tu t'es sentie triste, avec quelqu'un qui compte pour toi" in shown
    assert "CANARI-CONFIDENCE" not in shown and "Pixel" not in shown and "Sam" not in shown


# ── Qui elle devient : le récit sur tout ce qu'elle sait d'elle (ADR 0090) ──────────────────────────────────


from types import SimpleNamespace as NS  # noqa: E402

from mika.contracts import self_ as self_c  # noqa: E402
from mika.contracts import social as social_c  # noqa: E402
from mika.faculties.self import SelfState  # noqa: E402
from mika.faculties.self.narrative import (  # noqa: E402
    Narrate,
    _forgot_someone,
    changes_since,
    gather,
    prompt_of,
)
from mika.kernel.builtin import SUBJECT_FORGOTTEN  # noqa: E402
from mika.kernel.clock import DAY, HOUR  # noqa: E402
from mika.vocab import interests as v  # noqa: E402
from mika.vocab.privacy import Sensitivity  # noqa: E402
from tests.unit.test_knowledge_coherence import FRAME, Frame, Store  # noqa: E402
from tests.unit.test_self_said import JAZZ, NO_JAZZ, said_of_herself  # noqa: E402

P = SelfParams()
NOW = FRAME.now
ALICE, INES = "user_2", "user_5"
CITY_POP = v.InterestView("lived:2026-10-01", v.LIVED, v.VIVID, label_ref="cp.label")
DRAWING = v.InterestView("Le dessin", v.PERSONA, v.PRESENT, line="Le dessin")


class Her(Frame):
    """Son cadre : Inès est sa propriétaire, Alice une amie ; ce qu'elle sait d'elle, ses intérêts."""

    env = NS(tz_of=FRAME.env.tz_of, params_of=lambda owner, *_: P if owner == "self" else FRAME.env.params_of())

    def __init__(self, known=(self_c.PROMISES_KEPT,), views=(CITY_POP, DRAWING), nature=self_c.AI, **kw):
        super().__init__(**kw)
        self.known, self.views, self.nature = tuple(known), tuple(views), nature

    def get(self, key):
        names = {ALICE: "Alice", INES: "Inès"}
        return {"self.knows": lambda: self.known, "self.interests": lambda: self.views,
                "identity.is_owner": lambda: key.arg == INES, "social.circle": lambda: (ALICE, INES),
                "social.closeness": lambda: {ALICE: social_c.FRIEND, INES: social_c.CLOSE}.get(key.arg, ""),
                "identity.identity": lambda: NS(name=names.get(key.arg, "")),
                "self.persona": lambda: self_c.PersonaDoc(nature=self.nature),
                }.get(key.name, lambda: super(Her, self).get(key))()


def lived(db: Store, seq: int, text: str, gist: str, who: str, *, sensitivity: int = 2, secret: bool = False):
    db.texts[f"{seq}.gist"] = gist
    db.put(memory_c.REMEMBERED.draft(text=Content.of(text, level=sensitivity), about=(who,), told_by=(who,),
                                     sensitivity=sensitivity, importance=0.6, secret=secret,
                                     gist=Content(ref=f"{seq}.gist", text=gist)), seq, NOW - DAY)


def her_life() -> Store:
    db = Store()
    db.texts["cp.label"] = "la city pop"
    for seq, text, genre in ((5, JAZZ, "avis"), (7, "Mon livre préféré, c'est L'Écume des jours", "gout")):
        (d,) = said_of_herself(db, text, genre)
        db.put(d, seq, NOW - 3 * DAY)
    (no,) = said_of_herself(db, NO_JAZZ, "avis", remplace=5, known=(5,))
    db.put(no, 6, NOW - DAY)
    db.put(memory_c.BELIEVED.draft(text=Content.of("CANARI-TAIRE je déteste mon deuxième prénom"), about_self=True,
                                   durable=True, secret=True, sensitivity=int(Sensitivity.CONFIDENCE)), 8, NOW - DAY)
    (rap,) = said_of_herself(db, "Je n'aime pas le rap", "avis")
    db.put(rap, 3, NOW - 3 * DAY)
    db.put(memory_c.BELIEVED.draft(text=Content.of("CANARI-CHANGE j'aime le rap en cachette"), about_self=True,
                                   durable=True, secret=True, sensitivity=int(Sensitivity.CONFIDENCE), replaces=3),
           9, NOW - DAY)  # un changement d'avis qu'elle garde pour elle
    # le plus ancien est celui de sa propriétaire : il passe quand même d'abord
    lived(db, 10, "J'ai vécu à travers Inès : le salon du manga avec Inès", "un salon du manga", INES)
    lived(db, 11, "J'ai vécu à travers Alice : le concert de jazz d'Alice au Duc des Lombards", "un concert de jazz",
          ALICE)
    lived(db, 12, "J'ai vécu à travers Alice : sa soirée secrète", "une soirée", ALICE, secret=True)
    lived(db, 13, "J'ai vécu à travers Alice : son rendez-vous médical", "un rendez-vous", ALICE,
          sensitivity=int(Sensitivity.CONFIDENCE))
    db.put(memory_c.REMEMBERED.draft(text=Content.of("J'ai appris à dessiner des mains"), importance=0.7), 14,
           NOW - DAY)
    db.put(memory_c.REMEMBERED.draft(text=Content.of("Alice m'a dit qu'il pleuvait", level=1), about=(ALICE,),
                                     sensitivity=1, importance=0.9), 15, NOW - DAY)  # anodin, mais il la nomme
    return db


def test_her_story_is_made_of_what_she_knows_of_herself_and_names_no_one():
    m = gather(Her(), her_life(), SelfState(narrated_at=NOW - 2 * DAY), P)
    assert NO_JAZZ in m.beliefs and "Mon livre préféré, c'est L'Écume des jours" in m.beliefs
    assert not any("CANARI-TAIRE" in b for b in m.beliefs)  # ce qu'elle a demandé de taire, jamais
    assert m.changes == [(JAZZ, NO_JAZZ)]
    assert m.lived == [("un salon du manga", "la personne qui compte le plus pour toi"),
                       ("un concert de jazz", "quelqu'un que tu aimes bien")]  # sa propriétaire d'abord
    assert m.about == (ALICE, INES)  # l'oubli de l'une ou l'autre l'atteint
    assert [k.text for k in m.told] == ["J'ai appris à dessiner des mains"]  # ses vécus ne s'y redisent pas nommés
    assert any("la city pop" in x for x in m.passions) and any("tu tiens parole" in x for x in m.knows)
    shown = prompt_of(m, None)
    assert "Alice" not in shown and "Inès" not in shown and "Duc des Lombards" not in shown
    assert "une soirée" not in shown and "un rendez-vous" not in shown  # un secret, une confidence : jamais
    assert f"avant, « {JAZZ} » ; maintenant, « {NO_JAZZ} »" in shown


def test_she_rewrites_her_story_when_she_has_changed_not_before():
    frame = Her()
    assert changes_since(SelfState(souvenirs=4), frame, P) < P.narrative_min_changes  # quatre souvenirs : rien
    assert changes_since(SelfState(souvenirs=5), frame, P) >= P.narrative_min_changes  # cinq : comme avant
    first = SelfState(narrated_at=NOW - 2 * DAY, narrated_knows=(self_c.PROMISES_KEPT,),
                      narrated_interests=(("Le dessin", v.PRESENT),))
    assert changes_since(first, Her(views=(DRAWING,)), P) == 0  # rien de neuf
    assert changes_since(first, frame, P) == 2  # un intérêt est né
    assert changes_since(replace(first, self_beliefs=1), Her(views=(DRAWING,)), P) == 1  # un goût dit, qui tient
    assert changes_since(first, Her(known=(), views=(DRAWING,)), P) == 2  # elle ne sait plus qu'elle tient parole
    today = replace(first, narrated_at=NOW - HOUR, self_beliefs=3)
    assert Narrate().next_due(today, frame, None) == NOW - HOUR + P.narrative_every_us  # jamais deux fois par jour


def test_forgetting_someone_she_lived_through_silences_her_story():
    s = SelfState(narrative_ref="r", narrative_about=(ALICE, INES))
    gone = _forgot_someone(s, NS(data=NS(subject=ALICE)), None)
    assert gone.narrative_masked and gone.narrative_stale and gone.narrative_about == (INES,)
    assert _forgot_someone(s, NS(data=NS(subject="user_9")), None) is s
    assert SUBJECT_FORGOTTEN.name == "kernel.subject_forgotten"


class Voice:
    def __init__(self, text: str):
        self.text, self.requests = text, []

    async def call(self, request):
        self.requests.append(request)
        return NS(text=self.text, model="haiku")


async def write(frame: Frame, text: str = "Je suis quelqu'un qui écoute.", store=None) -> tuple[Voice, list]:
    emitted: list = []

    async def emit(*drafts):
        emitted.extend(drafts)

    voice = Voice(text)
    ctx = NS(frame=frame, state=SelfState(), ports={"store": store or her_life()}, llm=voice, run_id="r",
             emit=emit)
    await Narrate().run(ctx)
    return voice, emitted


async def test_embodied_she_hears_nothing_of_an_ai_and_her_story_names_no_one():
    ai, emitted = await write(Her())
    assert "Tu n'as pas de corps" in ai.requests[0].system_stable and emitted
    assert emitted[0].data.about == (ALICE, INES) and emitted[0].data.knows == (self_c.PROMISES_KEPT,)
    embodied, _ = await write(Her(nature=self_c.EMBODIED))
    assert "Tu n'as pas de corps" not in embodied.requests[0].system_stable
    named, nothing = await write(Her(), "Je suis quelqu'un qui écoute Alice parler de jazz.")
    assert named.requests and nothing == []  # un prénom de son cercle : il ne s'écrit pas
    empty, none = await write(Her(), store=Store())
    assert empty.requests == [] and none == []  # rien de vécu : pas un récit de rien
