"""Elle dessine pour quelqu'un (ADR 0063), par ses intentions :

- le plancher vaut pour tout le monde : rien de sexuel avec un mineur (des mots, un âge, en français comme en
  anglais), rien de sexuel avec une personne réelle — et « sur son lit » ne dit pas un enfant ;
- l'outil n'est offert qu'en tête-à-tête, à sa propriétaire ou à quelqu'un qui a un compte ; jamais dans un salon,
  jamais à un inconnu ; rien de branché : elle le dit ;
- au-dessus du plancher : sa propriétaire sans quota, le contenu pour adultes seulement pour elle et seulement vers
  un fournisseur qui l'accepte ; une personne qui a un compte : un quota par jour, des dessins en cours bornés ;
- la qualité par défaut est le brouillon, la haute seulement si on la demande (et si elle est permise) ;
- une demande est journalisée, dessinée en fond, déposée dans ``shares``, regardée ; la section le lui dit (en
  cours, prêt) ; ``show_drawing`` la joint à son message, qui l'emporte : la personne seule la télécharge ;
- un échec (un refus de modération) se dit : l'initiative due le porte, une réponse à la personne le dit aussi ;
- un dessin prêt fait une initiative due (``OWED``), vers là où la personne est.
"""

from __future__ import annotations

import asyncio

from mika.adapters.imaging.config import LiveImaging
from mika.adapters.imaging.fake import FakeImageBackend
from mika.adapters.imaging.gateway import ImageGateway
from mika.adapters.shares import MemoryShares
from mika.app.composition import policies
from mika.app.mindport import KernelPort
from mika.contracts import agency as agency_c
from mika.contracts import imaging as c
from mika.contracts import runtime as rt
from mika.contracts import shares as shares_c
from mika.faculties.identity import audience_for
from mika.kernel.clock import MINUTE, ManualClock
from mika.kernel.registry import ArbitrationPolicy
from mika.plugins.imaging.faculty import ImagingParams
from mika.plugins.imaging.policy import floor, minor_in
from mika.plugins.imaging.prompt import _owed
from mika.ports.imaging import ImageCaps
from mika.ports.llm import LLMRequest, LLMResponse, ToolCall
from mika.runtime.pipeline import EpisodeRequest
from mika.sim.clock import run_virtual
from mika.vocab.episodes import Kind
from mika.vocab.phrasebook import phrase
from tests.fixtures.mika import boot, build, connect, said
from tests.unit.test_shares import call, journal

MINORS, REAL_PERSON = phrase("imaging.floor.minors"), phrase("imaging.floor.real_person")
NO_PORT, NOT_HERE = phrase("imaging.tools.no_port"), phrase("imaging.tools.not_here")

LOCAL = ImageCaps(edit=True, max_refs=4, adult=True, local=True)
HOSTED = ImageCaps(edit=True, max_refs=16)
CAT = "A ginger cat asleep on a wooden desk by a window, soft evening light, detailed illustration"
SEEN = "Un chat roux endormi sur un bureau, à la lumière du soir."


def quiet(req: LLMRequest) -> LLMResponse:
    return LLMResponse(SEEN if req.role == "caption" else "D'accord.")


def port_of(*backends: FakeImageBackend) -> LiveImaging:
    return LiveImaging(ImageGateway({b.name: b for b in backends}, {"draw": backends[0].name}, clock=ManualClock(),
                                    slots={b.name: 1 for b in backends}))


def live(tmp_path, scenario, *, respond=quiet, backend: FakeImageBackend | None = None, plugged: bool = True):
    shares = MemoryShares()
    backend = backend or FakeImageBackend("maison", caps=LOCAL)
    imaging = port_of(backend) if plugged else LiveImaging()
    kernel, clock, llm, deliveries = build(tmp_path, respond, ports={"shares": shares, "imaging": imaging},
                                           arbitration=ArbitrationPolicy())

    async def main():
        await boot(kernel)
        try:
            await connect(kernel, "user_1", "Adrien", operator=True)
            await connect(kernel, "user_2", "Béa")
            return await scenario(kernel, shares, backend, llm, deliveries)
        finally:
            await kernel.stop()

    return run_virtual(clock, main)


async def drawn(kernel, *, limit=20 * MINUTE) -> None:
    """Attendre (en temps virtuel) que le processus ait fini ce qu'on lui a demandé."""
    end = kernel.mind.clock.now() + limit
    while kernel.mind.clock.now() < end:
        state = kernel.mind.frame().state("imaging")
        if state.jobs and all(j.status != c.WAITING for j in state.jobs.values()):
            return
        await asyncio.sleep(5)


# ── Le plancher ───────────────────────────────────────────────────────────


def test_the_floor_holds_for_everyone_in_both_languages():
    assert floor("nude elf by a waterfall, adult woman", adult=True, real_person=False) is None
    assert floor("une femme nue allongée sur son lit", adult=True, real_person=False) is None  # « son » : un possessif
    assert floor("a nude teenage girl", adult=True, real_person=False) == MINORS
    assert floor("une collégienne en lingerie", adult=False, real_person=False) == MINORS  # le mot suffit
    assert floor("naked woman, 16 years old", adult=True, real_person=False) == MINORS
    assert floor("une femme de 25 ans nue", adult=True, real_person=False) is None
    assert floor("a nude celebrity", adult=True, real_person=True) == REAL_PERSON
    assert floor("children playing in a park, watercolor", adult=False, real_person=False) is None  # rien de sexuel
    assert minor_in("12 ans") and not minor_in("an 18 years old woman")
    assert not minor_in("the adolescence of a tree")  # un mot entier : « adolescence » n'est pas « adolescent »


# ── Qui peut demander ─────────────────────────────────────────────────────


def test_offered_only_in_private_to_the_owner_or_an_account(tmp_path):
    async def scenario(kernel, shares, backend, llm, deliveries):
        await connect(kernel, "web_inconnu", "Zoé", authenticated=False)
        frame = kernel.mind.frame()
        pols = policies()
        out = {}
        for name, target, room in (("propriétaire", "user_1", None), ("compte", "user_2", None),
                                   ("salon", "user_2", "salon"), ("inconnu", "web_inconnu", None)):
            aud = audience_for(frame, EpisodeRequest(kind=Kind.REPLY, target=target, room=room))
            out[name] = {t for t in kernel.runner._tools(pols[Kind.REPLY], Kind.REPLY, aud) if t in ("draw", "show_drawing")}
        stranger = audience_for(frame, EpisodeRequest(kind=Kind.REPLY, target="web_inconnu"))
        refused = await call(kernel, "draw", "web_inconnu", prompt=CAT, audience=stranger)
        return out, refused

    out, refused = live(tmp_path, scenario)
    assert out["propriétaire"] == out["compte"] == {"draw", "show_drawing"}
    assert out["salon"] == out["inconnu"] == set()
    assert not refused.ok and refused.content == NOT_HERE


def test_nothing_plugged_in_she_says_so(tmp_path):
    async def scenario(kernel, shares, backend, llm, deliveries):
        return await call(kernel, "draw", "user_1", prompt=CAT), journal(kernel, c.REQUESTED)

    out, requested = live(tmp_path, scenario, plugged=False)
    assert not out.ok and out.content == NO_PORT and requested == []


def test_above_the_floor_the_owner_has_no_quota_and_an_account_has_one(tmp_path):
    async def scenario(kernel, shares, backend, llm, deliveries):
        await kernel.set_params("imaging", ImagingParams(per_day=1, max_waiting=5))
        got = {
            "adulte-compte": await call(kernel, "draw", "user_2", prompt="nude woman", adult=True),
            "compte-1": await call(kernel, "draw", "user_2", prompt=CAT),
            "compte-2": await call(kernel, "draw", "user_2", prompt=CAT + ", again"),
            "adulte-propriétaire": await call(kernel, "draw", "user_1", prompt="nude elf, adult woman", adult=True),
            "mineur-propriétaire": await call(kernel, "draw", "user_1", prompt="nude teen", adult=True),
        }
        for i in range(3):
            got[f"propriétaire-{i}"] = await call(kernel, "draw", "user_1", prompt=f"{CAT} #{i}")
        return got, journal(kernel, c.REQUESTED)

    got, requested = live(tmp_path, scenario)
    assert not got["adulte-compte"].ok and "propriétaire" in got["adulte-compte"].content
    assert got["compte-1"].ok and not got["compte-2"].ok and "aujourd'hui" in got["compte-2"].content
    assert got["adulte-propriétaire"].ok and not got["mineur-propriétaire"].ok
    assert got["mineur-propriétaire"].content == MINORS
    assert all(got[f"propriétaire-{i}"].ok for i in range(3))  # pas de quota pour elle
    adult = [e for e in requested if e.data.adult]
    assert len(adult) == 1 and adult[0].data.owner and adult[0].data.target == "user_1"
    assert "c'est lancé" in got["compte-1"].content.lower() and "ne le décris pas" in got["compte-1"].content.lower()


def test_an_adult_request_needs_a_provider_that_accepts_it(tmp_path):
    async def scenario(kernel, shares, backend, llm, deliveries):
        return await call(kernel, "draw", "user_1", prompt="nude elf", adult=True)

    out = live(tmp_path, scenario, backend=FakeImageBackend("hébergé", caps=HOSTED))
    assert not out.ok and "accepte" in out.content


def test_draft_by_default_high_only_when_asked_and_allowed(tmp_path):
    async def scenario(kernel, shares, backend, llm, deliveries):
        await call(kernel, "draw", "user_1", prompt=CAT)
        await call(kernel, "draw", "user_1", prompt=CAT + " 2", quality="high")
        await kernel.set_params("imaging", ImagingParams(allow_high=False, default_quality="normal"))
        capped = await call(kernel, "draw", "user_1", prompt=CAT + " 3", quality="high")
        await call(kernel, "draw", "user_1", prompt=CAT + " 4")
        return [e.data.quality for e in journal(kernel, c.REQUESTED)], capped

    qualities, capped = live(tmp_path, scenario)
    assert qualities == ["draft", "high", "normal", "normal"]
    assert "la haute n'est pas permise" in capped.content


# ── Dessiner, montrer ─────────────────────────────────────────────────────


def drawing(req: LLMRequest) -> LLMResponse:
    if req.role == "caption":
        return LLMResponse(SEEN)
    if req.role != "reply":
        return LLMResponse("D'accord.")
    asked = next((m.content for m in reversed(req.messages) if m.role == "user"), "")
    prompt = "\n".join([req.system_stable, *(m.content for m in req.messages)])
    used = {tc.name for m in req.messages for tc in m.tool_calls}
    if asked.rstrip().endswith("alors, ce dessin ?"):
        if "Il est prêt" in prompt and "show_drawing" not in used:
            return LLMResponse("", (ToolCall("s1", "show_drawing", {}),), stop="tool_use")
    elif asked.rstrip().endswith("tu peux me dessiner un chat ?") and "draw" not in used:
        return LLMResponse("", (ToolCall("d1", "draw", {"prompt": CAT, "aspect": "landscape"}),), stop="tool_use")
    return LLMResponse("Le voilà !" if "show_drawing" in used else "Je m'y mets !")


def test_a_drawing_is_made_in_the_background_and_leaves_with_her_message(tmp_path):
    async def scenario(kernel, shares, backend, llm, deliveries):
        await (await kernel.perceive(said("user_2", "tu peux me dessiner un chat ?"))).reply
        await drawn(kernel)
        [done] = journal(kernel, c.DRAWN)
        port = KernelPort(kernel)
        meta = port.shared([done.data.file])
        before = await port.shared_file(done.data.file, handle="user_2")  # pas encore parti : rien à télécharger
        await (await kernel.perceive(said("user_2", "alors, ce dessin ?"))).reply
        await asyncio.sleep(1)
        [utterance] = [e for e in journal(kernel, rt.UTTERANCE) if e.data.attachments]
        replies = [r for r in llm.calls if r.role == "reply"]
        mine = await port.shared_file(done.data.file, handle="user_2")
        theirs = await port.shared_file(done.data.file, handle="user_1")
        again = await call(kernel, "show_drawing", "user_2")
        state = kernel.mind.frame().state("imaging")
        return (done, meta, before, utterance, replies, mine, theirs, again, state, dict(shares.blobs),
                backend.requests)

    (done, meta, before, utterance, replies, mine, theirs, again, state, blobs,
     asked) = live(tmp_path, scenario, respond=drawing)
    [req] = asked
    assert req.prompt == CAT and req.aspect == "landscape" and req.quality == "draft" and not req.adult
    assert done.data.target == "user_2" and done.data.caption.text == SEEN and done.data.mime == "image/png"
    assert done.data.name.text.startswith("dessin-") and blobs[done.data.file][:8] == b"\x89PNG\r\n\x1a\n"
    [m] = meta
    assert (m.kind, m.mime, m.name) == (shares_c.IMAGE, "image/png", done.data.name.text)
    assert before is None  # préparé, pas encore parti
    # la section lui disait qu'il était en cours, puis prêt — avec ce qu'elle y voit
    first, *_, last = replies
    assert "TES DESSINS" not in "\n".join(m.content for m in first.messages if m.role == "user")
    assert "Il est prêt" in "\n".join([last.system_stable, *(m.content for m in last.messages)])
    assert SEEN in "\n".join([last.system_stable, *(m.content for m in last.messages)])
    assert utterance.data.attachments == (done.data.file,) and utterance.data.target == "user_2"
    assert mine is not None and mine.data == blobs[done.data.file] and theirs is None
    assert not again.ok  # montré : plus rien de prêt
    [job] = state.jobs.values()
    assert job.status == c.SHOWN and job.message == utterance.seq


def test_a_refusal_is_said_and_a_ready_drawing_is_owed(tmp_path):
    async def scenario(kernel, shares, backend, llm, deliveries):
        await call(kernel, "draw", "user_2", prompt="a cat wearing a hat")
        await call(kernel, "draw", "user_2", prompt=CAT)
        await drawn(kernel)
        frame = kernel.mind.frame()
        candidates = _owed(frame.state("imaging"), frame)
        failed = journal(kernel, c.FAILED)
        await (await kernel.perceive(said("user_2", "et mes dessins ?"))).reply
        last = [r for r in llm.calls if r.role == "reply"][-1]
        prompt = "\n".join([last.system_stable, *(m.content for m in last.messages)])
        return candidates, failed, prompt, kernel.mind.frame().state("imaging")

    hosted = FakeImageBackend("hébergé", caps=HOSTED, refuse=("hat",))
    candidates, failed, prompt, state = live(tmp_path, scenario, backend=hosted)
    [f] = failed
    assert f.data.outcome == c.REFUSED and "modération" in f.data.reason.text
    reasons = sorted(cand.reason for cand in candidates)
    assert reasons == [c.DELIVER, c.COULD_NOT] or reasons == sorted([c.COULD_NOT, c.DELIVER])
    assert all(cand.kind == Kind.INITIATIVE and cand.target == "user_2" for cand in candidates)
    assert all(cand.args["bundles"] == (c.BUNDLE,) and cand.args["subject"].startswith("dessin:") for cand in candidates)
    assert {c.DELIVER, c.COULD_NOT} <= agency_c.OWED  # ce qui est dû : ni plafond ni période réfractaire
    assert "n'a pas pu se faire" in prompt and "modération" in prompt
    statuses = sorted(j.status for j in state.jobs.values())
    assert statuses == sorted([c.TOLD, c.READY])  # l'échec est dit par sa réponse ; le prêt attend show_drawing
