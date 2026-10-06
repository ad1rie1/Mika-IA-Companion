"""Elle envoie des fichiers (ADR 0062), par leurs intentions.

- un nom de fichier est nettoyé (ni dossier ni caractère douteux, 80 caractères, une extension de texte, ``.txt``
  sans extension) ; une autre extension est refusée en le disant ;
- un texte vide, binaire, trop long ou trop lourd n'est pas envoyé ; le quota du jour et le plafond de l'épisode
  tiennent ;
- jamais dans un salon, jamais à quelqu'un sans compte : l'outil n'y est même pas offert ;
- le même appel recomposé retombe sur le même fichier ; une écriture supplantée ne laisse pas d'octets ;
- un fichier de projet : à qui parle en propriétaire, ou à qui l'a confié — pas à une autre amie, pas d'un projet
  archivé, pas ce qu'elle ne peut pas entendre ; ni ``../``, ni un fichier caché, ni un fichier trop gros ;
- il part avec son message (l'énoncé l'emporte, le fil le garde, la personne seule le télécharge), la section
  « CE QUE TU LUI AS DÉJÀ ENVOYÉ » le lui rappelle ; retiré (trop vieux, la place dépassée), ses octets s'effacent
  et il n'est plus disponible.
"""

from __future__ import annotations

import asyncio
import hashlib
import itertools

from mika.adapters.shares import MemoryShares
from mika.app.composition import policies
from mika.app.mindport import KernelPort
from mika.contracts import projects as projects_c
from mika.contracts import runtime as rt
from mika.contracts import shares as c
from mika.faculties.identity import audience_for
from mika.faculties.shares.faculty import MIB, SharesParams, due_expiries, params
from mika.faculties.shares.tools import clean_name, may_share, offered, text_name
from mika.kernel.clock import DAY, US
from mika.kernel.events import Origin
from mika.kernel.frame import Audience, EpisodeRef, Frame
from mika.kernel.guards import Guard
from mika.kernel.registry import ArbitrationPolicy
from mika.ports.llm import LLMRequest, LLMResponse, ToolCall
from mika.runtime.effects import with_content
from mika.runtime.operations import perform
from mika.runtime.pipeline import EpisodeRequest
from mika.runtime.tools import ToolContext
from mika.sim.clock import run_virtual
from mika.vocab.episodes import Kind
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import Sensitivity
from tests.fixtures.atelier import Atelier
from tests.fixtures.mika import boot, build, connect, said

_CALLS = itertools.count(1)


def quiet(req: LLMRequest) -> LLMResponse:
    return LLMResponse("D'accord.")


def live(tmp_path, scenario, *, respond=quiet, atelier: Atelier | None = None):
    store = MemoryShares()
    kernel, clock, llm, deliveries = build(tmp_path, respond, ports={"shares": store,
                                                                     "workshop": atelier or Atelier()},
                                           arbitration=ArbitrationPolicy())

    async def main():
        await boot(kernel)
        try:
            await connect(kernel, "user_1", "Adrien", operator=True)
            await connect(kernel, "user_2", "Béa")
            await connect(kernel, "user_3", "Chloé")
            return await scenario(kernel, store, llm, deliveries)
        finally:
            await kernel.stop()

    return run_virtual(clock, main)


def tool_ctx(kernel, name: str, handle: str, *, audience: Audience | None = None, scope: str | None = None,
             key: str | None = None, calls=(), guard: Guard | None = None) -> ToolContext:
    """Le contexte d'un appel d'outil pendant une réponse à ``handle`` (un appel distinct, sauf ``key``)."""
    mind = kernel.mind
    base = mind.frame()
    n = next(_CALLS)
    aud = audience if audience is not None else audience_for(base, EpisodeRequest(kind=Kind.REPLY, target=handle))
    frame = Frame(base.root, mind.clock.now(), mind.registry, aud, EpisodeRef(f"ep-{n}", Kind.REPLY, target=handle))
    ctx = ToolContext(mind, mind.registry.tools[name], f"appel-{n}", f"ep-{n}", frame, guard=guard,
                      ports=kernel.ports, calls=tuple(calls), dedupe_scope=scope)
    ctx.call_key = key or f"{name}:{n}"
    return ctx


async def call(kernel, tool: str, handle: str, **args):
    """Un appel d'outil, ses arguments validés comme la boucle les valide."""
    ctx_kw = {k: args.pop(k) for k in ("audience", "scope", "key", "calls", "guard") if k in args}
    spec = kernel.mind.registry.tools[tool]
    return await spec.handler(spec.args.model_validate(args), tool_ctx(kernel, tool, handle, **ctx_kw))


def journal(kernel, *types) -> list:
    mind = kernel.mind
    names = {t.name for t in types}
    return [with_content(mind, mind.decode(e)) for e in mind.store.read() if e.type in names]


# ── Les noms ──────────────────────────────────────────────────────────────


def test_a_name_is_cleaned_and_keeps_a_text_extension():
    assert text_name("courses") == ("courses.txt", "text/plain")
    assert text_name("Notes.MD") == ("Notes.md", "text/markdown")
    assert text_name("../../etc/passwd") == ("passwd.txt", "text/plain")
    assert text_name('a<b>:c|d?*"e.csv') == ("abcde.csv", "text/csv")
    assert text_name("C:\\Users\\moi\\budget.json") == ("budget.json", "application/json")
    assert text_name("e\u0301te\u0301.md")[0] == "été.md"  # NFC
    assert text_name("v1.2 notes") == ("v1.2 notes.txt", "text/plain")  # « 2 notes » n'est pas une extension
    assert text_name("ligne\x00\u202e.txt")[0] == "ligne.txt"  # ni contrôle, ni bascule de sens
    assert text_name("   ") == ("fichier.txt", "text/plain")
    long = text_name("x" * 300 + ".py")
    assert long is not None and len(long[0]) == 80 and long[0].endswith(".py")
    assert text_name("virus.exe") is None and text_name("page.html") is None
    assert clean_name(".bashrc") == "bashrc"


# ── Écrire un texte et l'envoyer ──────────────────────────────────────────


def test_a_written_text_is_stored_out_of_the_journal_and_counted(tmp_path):
    content = "- pain\n- lait\n- œufs\n"

    async def scenario(kernel, store, llm, deliveries):
        out = await call(kernel, "share_text", "user_2", name="courses", content=content)
        [file] = out.attach
        port = KernelPort(kernel)
        frame = kernel.mind.frame()
        return (out, file, dict(store.blobs), journal(kernel, c.SHARED), port.shared([file, "f" * 32]),
                await port.shared_file(file, handle="user_2"), frame.get(c.SENT_TODAY("user_2")),
                frame.at(frame.now + DAY + 1).get(c.SENT_TODAY("user_2")))

    out, file, blobs, shared, meta, before_sent, today, tomorrow = live(tmp_path, scenario)
    assert out.ok and "« courses.txt »" in out.content and "ne recopie pas le contenu" in out.content
    assert blobs == {file: content.encode()}
    [e] = shared
    assert e.data.target == "user_2" and e.data.size == len(content.encode()) and e.data.origin == c.WRITTEN
    assert e.data.digest == hashlib.sha256(content.encode()).hexdigest() and e.data.name.text == "courses.txt"
    assert e.data.name.level == int(Sensitivity.PERSONAL)
    [m] = meta  # un identifiant inconnu n'y est pas
    assert (m.id, m.name, m.kind, m.mime, m.size, m.available) == (file, "courses.txt", "file", "text/plain",
                                                                    len(content.encode()), True)
    assert before_sent is None  # aucun message ne l'a encore emporté : personne ne le télécharge
    assert (today, tomorrow) == (1, 0)  # 24 heures glissantes


def test_what_is_not_a_good_text_is_refused_and_leaves_nothing(tmp_path):
    async def scenario(kernel, store, llm, deliveries):
        await kernel.set_params("shares", SharesParams(text_max_chars=1_000))
        got = {
            "exe": await call(kernel, "share_text", "user_2", name="outil.exe", content="MZ"),
            "vide": await call(kernel, "share_text", "user_2", name="vide.txt", content="  \n"),
            "binaire": await call(kernel, "share_text", "user_2", name="a.txt", content="a\x00b"),
            "long": await call(kernel, "share_text", "user_2", name="a.txt", content="x" * 1_001),
        }
        await kernel.set_params("shares", SharesParams())
        got["lourd"] = await call(kernel, "share_text", "user_2", name="a.txt", content="😀" * 140_000)
        return got, store.files(), journal(kernel, c.SHARED)

    got, files, shared = live(tmp_path, scenario)
    assert not any(r.ok for r in got.values()), {k: r.content for k, r in got.items()}
    assert ".md" in got["exe"].content and "vide" in got["vide"].content
    assert "1000 caractères" in got["long"].content and "512 Kio" in got["lourd"].content
    assert files == [] and shared == []


def test_the_day_and_the_episode_have_their_limits(tmp_path):
    async def scenario(kernel, store, llm, deliveries):
        await kernel.set_params("shares", SharesParams(per_day=2))
        a = await call(kernel, "share_text", "user_2", name="un.md", content="un")
        b = await call(kernel, "share_text", "user_2", name="deux.md", content="deux")
        c3 = await call(kernel, "share_text", "user_2", name="trois.md", content="trois")
        other = await call(kernel, "share_text", "user_1", name="pour-adrien.md", content="ok")
        await kernel.set_params("shares", SharesParams())
        full = await call(kernel, "share_text", "user_1", name="x.md", content="x",
                          calls=(("share_text", True), ("share_project_file", True), ("share_text", True)))
        return a, b, c3, other, full

    a, b, third, other, full = live(tmp_path, scenario)
    assert a.ok and b.ok and not third.ok and "aujourd'hui" in third.content
    assert other.ok  # le quota est par personne
    assert not full.ok and "3 fichiers" in full.content


def test_never_in_a_room_never_to_someone_without_an_account(tmp_path):
    async def scenario(kernel, store, llm, deliveries):
        await connect(kernel, "web_inconnu", "Zoé", authenticated=False)
        frame = kernel.mind.frame()
        private = audience_for(frame, EpisodeRequest(kind=Kind.REPLY, target="user_2"))
        room = audience_for(frame, EpisodeRequest(kind=Kind.REPLY, target="user_2", room="salon"))
        stranger = audience_for(frame, EpisodeRequest(kind=Kind.REPLY, target="web_inconnu"))
        pols = policies()
        offered_tools = {
            name: {t for t in kernel.runner._tools(pols[kind], kind, aud) if t.startswith(("share_", "project_f"))}
            for name, kind, aud in (("privé", Kind.REPLY, private), ("initiative", Kind.INITIATIVE, private),
                                    ("salon", Kind.REPLY, room), ("inconnu", Kind.REPLY, stranger))}
        refused = await call(kernel, "share_text", "web_inconnu", name="a.md", content="a", audience=stranger)
        in_room = await call(kernel, "share_text", "user_2", name="a.md", content="a", audience=room)
        return offered_tools, refused, in_room, store.files()

    offered_tools, refused, in_room, files = live(tmp_path, scenario)
    every = {"share_text", "project_files", "share_project_file"}
    assert offered_tools["privé"] == every and offered_tools["initiative"] == every
    assert offered_tools["salon"] == set() and offered_tools["inconnu"] == set()
    assert refused.content == phrase("shares.tools.not_here") and in_room.content == phrase("shares.tools.not_here") and files == []
    assert not offered(Audience(persons=("user_2",), public=True, trust="authenticated"))
    assert not offered(Audience(persons=(), public=False, trust="authenticated"))


def test_the_same_call_recomposed_is_the_same_file_and_a_superseded_one_leaves_nothing(tmp_path):
    async def scenario(kernel, store, llm, deliveries):
        first = await call(kernel, "share_text", "user_2", name="liste.md", content="a", scope="tour:x", key="k")
        again = await call(kernel, "share_text", "user_2", name="liste.md", content="a", scope="tour:x", key="k")
        n = len(journal(kernel, c.SHARED))
        never = Guard("supplantée", predicate=lambda view: False)
        lost = await call(kernel, "share_text", "user_2", name="autre.md", content="b", guard=never)
        return first, again, n, lost, store.files(), len(journal(kernel, c.SHARED))

    first, again, n, lost, files, after = live(tmp_path, scenario)
    assert first.ok and again.ok and first.attach == again.attach and n == 1
    assert not lost.ok and lost.attach == () and "n'est pas parti" in lost.content
    assert files == list(first.attach) and after == 1  # ses octets ne sont pas restés


# ── Les fichiers de ses projets ───────────────────────────────────────────


def _form(unchecked: tuple[str, ...] = (), **values: str) -> dict[str, list[str]]:
    return {"_champs": [*values, *unchecked], **{k: [v] for k, v in values.items()}}


async def _project(kernel, nonce: str, **values: str) -> int:
    fields = {"title": "Un projet", "schedule": "manual", "mode": "persona", "days": "all", "cadence_hours": "0",
              "runs_per_day": "0", "priority": "normal", "branch": "main", "objectives": "Avancer", **values}
    got = await perform(kernel, "projects.creer", _form(("approval", "auto_push"), **fields), by="user_1", nonce=nonce)
    assert got.ok, got
    return journal(kernel, projects_c.PROJECT_CREATED)[-1].seq


def test_project_files_go_to_who_has_the_right_and_only_them(tmp_path):
    atelier = Atelier()

    async def scenario(kernel, store, llm, deliveries):
        await kernel.set_params("shares", SharesParams(project_max_mb=1))
        mine = await _project(kernel, "p1", title="Site")
        confided = await _project(kernel, "p2", title="Recettes de Béa", owner="user_2")
        old = await _project(kernel, "p3", title="Vieux")
        atelier.files[mine] = {"notes/plan.md": "plan", "logo.png": "\x89PNG", "big.bin": "x" * (MIB + 1),
                               ".env": "SECRET=1"}
        atelier.files[confided] = {"recette.md": "farine"}
        atelier.files[old] = {"vieux.md": "vieux"}
        got = await perform(kernel, "projects.archiver", _form(), by="user_1", subject=str(old), nonce="p3-arch")
        assert got.ok, got
        share = "share_project_file"
        out = {
            "proprio": await call(kernel, share, "user_1", project=mine, path="notes/plan.md"),
            "image": await call(kernel, share, "user_1", project=mine, path="/logo.png"),
            "confiante": await call(kernel, share, "user_2", project=confided, path="recette.md"),
            "amie": await call(kernel, share, "user_3", project=mine, path="notes/plan.md"),
            "pas-a-elle": await call(kernel, share, "user_2", project=mine, path="notes/plan.md"),
            "archive": await call(kernel, share, "user_1", project=old, path="vieux.md"),
            "remonte": await call(kernel, share, "user_1", project=mine, path="../autre/secret.md"),
            "cache": await call(kernel, share, "user_1", project=mine, path=".env"),
            "gros": await call(kernel, share, "user_1", project=mine, path="big.bin"),
            "absent": await call(kernel, share, "user_1", project=mine, path="nulle-part.md"),
        }
        listing = await call(kernel, "project_files", "user_1")
        tree = await call(kernel, "project_files", "user_1", project=mine)
        other = await call(kernel, "project_files", "user_3")
        return mine, out, listing, tree, other, journal(kernel, c.SHARED)

    mine, out, listing, tree, other, shared = live(tmp_path, scenario, atelier=atelier)
    assert out["proprio"].ok and out["image"].ok and out["confiante"].ok
    for refused in ("amie", "pas-a-elle", "archive"):
        assert out[refused].content == phrase("shares.tools.project_files.not_shared"), refused
    assert not out["remonte"].ok and not out["cache"].ok and not out["absent"].ok
    assert not out["gros"].ok and "1 Mio" in out["gros"].content
    by_name = {e.data.name.text: e.data for e in shared}
    assert set(by_name) == {"plan.md", "logo.png", "recette.md"}
    plan = by_name["plan.md"]
    assert (plan.origin, plan.project, plan.path.text, plan.mime, plan.kind) == (c.PROJECT, mine, "notes/plan.md",
                                                                                 "text/markdown", c.FILE)
    assert by_name["logo.png"].kind == c.IMAGE and by_name["logo.png"].mime == "image/png"
    assert "user_2" in by_name["recette.md"].about or by_name["recette.md"].target == "user_2"
    # une propriétaire qui peut l'entendre voit aussi le projet qu'elle a confié pour Béa ; jamais un archivé
    assert f"n° {mine} « Site »" in listing.content and "Recettes de Béa" in listing.content
    assert "Vieux" not in listing.content
    assert "notes/plan.md" in tree.content and "logo.png" in tree.content and ".env" in tree.content
    assert "Aucun" in other.content


def _view(**kw) -> projects_c.ProjectView:
    base = {"id": 1, "title_ref": "", "authority": projects_c.USER, "mode": projects_c.PERSONA,
            "status": projects_c.ACTIVE, "owner": "user_2", "about": ("user_2",), "sensitivity": 1,
            "created_at": 0}
    return projects_c.ProjectView(**{**base, **kw})


def test_who_may_receive_a_project_file():
    owner = Audience(persons=("user_1",), public=False, level=1, witness_level=2, private_ok=True, owner=True,
                     trust="authenticated")
    friend = Audience(persons=("user_3",), public=False, level=1, witness_level=2, private_ok=True,
                      trust="authenticated")
    confider = Audience(persons=("user_2",), public=False, level=1, witness_level=2, private_ok=True,
                        trust="authenticated")
    mine = _view(owner="user_1", about=("user_1",))
    assert may_share(mine, "user_1", owner)
    assert may_share(_view(), "user_2", confider)  # c'est elle qui l'a confié
    assert not may_share(mine, "user_3", friend)  # une autre amie
    assert not may_share(_view(status=projects_c.ARCHIVED, owner="user_1", about=("user_1",)), "user_1", owner)
    # ce qu'elle ne peut pas entendre : un projet sur une autre personne, devant une audience qui n'en a pas le niveau
    assert not may_share(_view(owner="user_2", about=("user_9",)), "user_2", confider)
    assert not may_share(_view(owner="user_1", about=("user_9",)), "user_1", owner)
    assert may_share(_view(owner="user_1", about=("user_9",)), "user_1", Audience(
        persons=("user_1",), public=False, level=2, witness_level=2, private_ok=True, owner=True))
    # une confiée par l'opérateur à elle-même (autorité « self ») n'ouvre rien à une amie
    assert not may_share(_view(authority=projects_c.SELF), "user_2", confider)


# ── Il part avec son message ──────────────────────────────────────────────

LIST = {"name": "courses.md", "content": "- pain\n- lait\n"}
SAID = "Je te mets la liste en pièce jointe. [EMOTION:happy:0.5]"


def sharing(req: LLMRequest) -> LLMResponse:
    if req.role != "reply":
        return LLMResponse("D'accord.")
    asked = next((m.content for m in reversed(req.messages) if m.role == "user"), "")
    if "liste" in asked and not any(m.role == "tool" for m in req.messages):
        return LLMResponse("", (ToolCall("c1", "share_text", dict(LIST)),), stop="tool_use")
    return LLMResponse(SAID if "liste" in asked else "Avec plaisir.")


def test_a_file_leaves_with_her_message_and_only_its_recipient_downloads_it(tmp_path):
    async def scenario(kernel, store, llm, deliveries):
        report = await (await kernel.perceive(said("user_2", "tu peux me faire la liste de courses ?"))).reply
        await asyncio.sleep(1)
        [utterance] = [e for e in journal(kernel, rt.UTTERANCE) if e.data.attachments]
        delivered = [d for d in deliveries.items if d.target == "user_2" and d.text]
        port = KernelPort(kernel)
        [file] = utterance.data.attachments
        history = port.recent("user_2", 10)
        mine = await port.shared_file(file, handle="user_2")
        theirs = await port.shared_file(file, handle="user_1")
        state = kernel.mind.frame().get(c.RECENT("user_2"))
        # elle lui reparle : la section lui rappelle ce qu'elle a envoyé
        await (await kernel.perceive(said("user_2", "merci beaucoup !"))).reply
        last = [r for r in llm.calls if r.role == "reply"][-1]
        prompt = "\n".join([last.system_stable, *(m.content for m in last.messages)])
        await kernel.mind.append([c.EXPIRED.draft(files=(file,), target="user_2", reason=c.RETENTION)],
                                 emitter="shares", correlation="essai", origin=Origin.PROCESS)
        await asyncio.sleep(1)  # l'effet efface les octets après le commit
        gone = await port.shared_file(file, handle="user_2")
        return (report, utterance, delivered, file, history, mine, theirs, state, prompt, gone, port.shared([file]),
                store.files())

    (report, utterance, delivered, file, history, mine, theirs, state, prompt, gone, after,
     files) = live(tmp_path, scenario, respond=sharing)
    assert report.outcome.value == "done" and utterance.data.text.text.startswith("Je te mets la liste")
    assert delivered[-1].attachments == (file,)
    assistant = [r for r in history if r.role == "assistant"]
    assert assistant[-1].attachments == f'[{{"id": "{file}"}}]'
    assert [v.message for v in state] == [utterance.seq]
    assert mine is not None and not mine.gone and mine.data == LIST["content"].encode() and mine.name == "courses.md"
    assert theirs is None  # pas son fil : la même réponse qu'un fichier inconnu
    assert "CE QUE TU LUI AS DÉJÀ ENVOYÉ" in prompt and "« courses.md »" in prompt
    assert gone is not None and gone.gone and gone.data == b""
    assert [m.available for m in after] == [False] and files == []


def test_a_reply_that_never_left_keeps_its_file_unsent(tmp_path):
    """Elle prépare un fichier puis se tait : il n'est jamais parti — personne ne le télécharge, la console le dit."""
    def mute(req: LLMRequest) -> LLMResponse:
        if req.role == "reply" and not any(m.role == "tool" for m in req.messages):
            return LLMResponse("", (ToolCall("c1", "share_text", dict(LIST)),), stop="tool_use")
        return LLMResponse("[SILENCE]" if req.role == "reply" else "D'accord.")

    async def scenario(kernel, store, llm, deliveries):
        report = await (await kernel.perceive(said("user_2", "la liste ?"))).reply
        [e] = journal(kernel, c.SHARED)
        port = KernelPort(kernel)
        return report, e.data.file, await port.shared_file(e.data.file, handle="user_2"), \
            kernel.mind.frame().get(c.RECENT("user_2")), [d for d in deliveries.items if d.attachments]

    report, file, download, state, carried = live(tmp_path, scenario, respond=mute)
    assert report.outcome.value == "abstained"
    assert download is None and [v.message for v in state] == [0] and carried == []


# ── La rétention ──────────────────────────────────────────────────────────


def test_old_files_expire_and_a_full_place_retires_the_oldest(tmp_path):
    atelier = Atelier()

    async def scenario(kernel, store, llm, deliveries):
        await kernel.set_params("shares", SharesParams(per_person_mb=10))
        pid = await _project(kernel, "p1", title="Gros")
        atelier.files[pid] = {"a.bin": "a" * (6 * MIB), "b.bin": "b" * (6 * MIB)}
        first = await call(kernel, "share_project_file", "user_1", project=pid, path="a.bin")
        await asyncio.sleep(1)
        second = await call(kernel, "share_project_file", "user_1", project=pid, path="b.bin")
        await asyncio.sleep(5)  # la rétention passe, puis l'effet efface
        await kernel.lanes.join()
        expired = journal(kernel, c.EXPIRED)
        port = KernelPort(kernel)
        frame = kernel.mind.frame()
        later = due_expiries(frame.state("shares"), frame.now + 400 * DAY, params(None))
        return first, second, expired, store.files(), port.shared([*first.attach, *second.attach]), later

    first, second, expired, files, metas, later = live(tmp_path, scenario, atelier=atelier)
    assert first.ok and second.ok
    [e] = expired
    assert e.data.reason == c.BUDGET and e.data.files == first.attach and e.data.target == "user_1"
    assert files == list(second.attach)
    assert [m.available for m in metas] == [False, True]
    assert later == [("user_1", c.RETENTION, second.attach)]  # au-delà d'un an : trop vieux


def test_the_retention_waits_until_a_file_is_due():
    from mika.faculties.shares.faculty import SharesState
    from mika.kernel.state import FrozenDict

    sent = c.SentView(file="a" * 32, at=10 * US, size=100, name_ref="r")
    state = SharesState(sent=FrozenDict({"user_1": (sent,)}))
    p = SharesParams(keep_days=2)
    assert due_expiries(state, 10 * US + 2 * DAY - 1, p) == []
    assert due_expiries(state, 10 * US + 2 * DAY, p) == [("user_1", c.RETENTION, ("a" * 32,))]
