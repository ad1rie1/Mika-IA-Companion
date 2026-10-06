"""Teams (ADR 0069), par ses intentions.

- un message qu'on adresse à la personne et qui pose une question à laquelle elle peut aider devient une réponse
  préparée **à sa place** ; le message est cité, sa voix (réglée par un opérateur) est de confiance ;
- **le texte d'une réponse n'entre jamais dans le journal** : une proposition ne porte que son identifiant et le
  condensé de ce qui a été montré ;
- **trois façons de partir** : posée dans Teams (la personne l'envoie, ou pas — et elle le sait, retouchée ou non),
  après un accord (une carte va à la personne ; sans accord à temps, rien ne part), sans accord ;
- un « [À COMPLÉTER » ne part jamais tout seul ; posé dans Teams, la personne le remplit ;
- elle ne prépare rien hors de propos : un canal où personne ne la mentionne, une conversation où la personne a
  déjà répondu, un message trop vieux, une conversation exclue ;
- une tâche Teams n'a pas sa mémoire (sa mémoire contient la vie de la personne et ce que d'autres lui ont confié) ;
- la signature est ajoutée par le serveur, jamais écrite par elle ;
- personne ne l'envoie à temps : elle ne part plus ;
- oublier un collègue atteint le journal et le cache.
"""

from __future__ import annotations

import asyncio
import json
import re
from types import SimpleNamespace

from mika.adapters.teams import TeamsConfig, TeamsStore
from mika.app import composition
from mika.app.mindport import KernelPort
from mika.app.teams import TeamsDesk, batch_of, digest
from mika.contracts import attention as attention_c
from mika.contracts import runtime as rt
from mika.contracts import teams as teams_c
from mika.kernel.clock import HOUR, MINUTE, US
from mika.kernel.events import Origin
from mika.plugins.teams import RECEIVED
from mika.ports.llm import LLMResponse, ToolCall
from mika.ports.teams import message_ref
from mika.runtime.operations import perform
from mika.sim.clock import SimClock, run_virtual
from mika.vocab.episodes import Kind
from tests.fixtures.mika import DOC, at_paris, build, connect

START = at_paris(2026, 10, 6, 10, 0)
KEY = "mtk_cle-de-test"
DM = "19:alice_adrien@unq.gbl.spaces"
GROUP = "19:projet@thread.v2"
CHANNEL = "19:general@thread.tacv2"
HR = "19:rh@thread.v2"
ALICE = "8:orgid:alice"
SELF = "8:orgid:adrien"
QUESTION = "Tu peux me rappeler la différence entre TCP et UDP ?"


class Settings:
    """Ce que la porte lit des réglages : la clé (son empreinte) et ce qu'un opérateur a réglé."""

    def __init__(self, cfg: TeamsConfig) -> None:
        self.cfg = cfg
        self.key = {"digest": digest(KEY), "hint": KEY[:8], "created_at": 0, "by": "test"}

    def teams(self) -> TeamsConfig:
        return self.cfg

    def teams_key(self) -> dict:
        return self.key


class Model:
    """Un modèle scripté : le tri dit « une question où elle peut aider » ; une tâche rédige."""

    def __init__(self, body="TCP garantit l'ordre et la livraison, UDP non : plus léger, sans garantie."):
        self.body = body

    def __call__(self, req):
        if req.role == "triage":
            return LLMResponse('{"importance": 0.6, "resume": "", "question": true, "aide": true, "emotion": ""}')
        if req.role == "step":
            if any(m.role == "tool" for m in req.messages):
                return LLMResponse("Réponse prête.")
            found = re.search(r"message=\[(t[0-9a-f]{12})\]", prompt_text(req))
            if found is None:
                return LLMResponse("Rien à faire.")
            return LLMResponse("", tool_calls=(ToolCall(f"{req.call_id}:d", "teams_draft",
                                                        {"message": found.group(1), "body": self.body}),),
                               stop="tool_use")
        return LLMResponse("d'accord [EMOTION:neutral:0.3]")


def prompt_text(req) -> str:
    return "\n".join([req.system_stable, req.system_volatile, *(str(m.content) for m in req.messages)])


def events(kernel, event_type) -> list:
    return [kernel.mind.decode(s) for s in kernel.mind.store.read(types={event_type.name})]


def raw_journal(kernel) -> str:
    return "\n".join(s.data for s in kernel.mind.store.read())


def sleep(us: int):
    return asyncio.sleep(us / US)


def msg(clock, n: int, text: str, *, conv: str = DM, author: str = "Alice Martin", author_id: str = ALICE,
        own: bool = False, mentions_me: bool = False, ago_us: int = 0) -> dict:
    return {"id": f"{1_759_000_000_000 + n}", "conv": conv, "author": author, "author_id": author_id,
            "time": (clock.now() - ago_us) // 1000, "text": text, "own": own, "mentions_me": mentions_me}


def live(tmp_path, model, scenario, *, cfg: TeamsConfig | None = None, inputs: dict | None = None,
         overrides=None, start=START):
    cfg = cfg or TeamsConfig()
    clock = SimClock(start)
    store = TeamsStore(lambda: cfg, tmp_path / "teams.db", now=clock.now)
    kernel, clock, llm, _ = build(tmp_path, model, clock=clock, ports={"teams": store})
    desk = TeamsDesk(Settings(cfg), clock.now, store)
    desk.port = SimpleNamespace(kernel=kernel)
    teams_inputs = {"enabled": cfg.enabled, "mode": cfg.mode, "autodraft": cfg.enabled and cfg.autodraft,
                    "skip": cfg.skip, **(inputs or {})}

    # l'envie de rédiger au plus haut : la tâche part en quelques minutes, quel que soit le tirage de l'arbitre
    overrides = {**(overrides or {}), "teams": {"draft_evidence": 12.0, **(overrides or {}).get("teams", {})}}

    async def main():
        await kernel.start(configure=lambda k: composition.configure(k, DOC, overrides, {"teams": teams_inputs}))
        try:
            return await scenario(kernel, llm, desk, store, clock)
        finally:
            await kernel.lanes.join()
            await kernel.stop()

    return run_virtual(clock, main)


async def push(desk, *messages, conversations=()):
    got = await desk.inbox(KEY, {"self": {"id": SELF, "name": "Adrien Dupont"}, "conversations": list(conversations),
                                 "messages": list(messages)})
    assert got.outcome == "accepted", got
    return got


def conv(id_: str, title: str = "", kind: str = "dm") -> dict:
    return {"id": id_, "title": title, "kind": kind}


# ── Elle prépare, posée dans Teams ; la personne l'envoie ─────────────────


def test_a_question_she_can_help_with_becomes_a_reply_posted_in_teams_in_her_place(tmp_path):
    async def scenario(kernel, llm, desk, store, clock):
        await connect(kernel, "user_1", "Adrien", operator=True)
        await push(desk, msg(clock, 1, QUESTION), conversations=[conv(DM, kind="dm")])
        await sleep(30 * MINUTE)
        out = {"noticed": events(kernel, teams_c.NOTICED), "proposed": events(kernel, rt.EFFECT_PROPOSED),
               "tasks": [c for c in llm.calls if c.role == "step"], "outbox": store.outbox(clock.now())}
        [item] = out["outbox"]
        out["placed"] = await desk.ack(KEY, item.id, {"result": "placed"})
        out["placed again"] = await desk.ack(KEY, item.id, {"result": "placed"})
        out["after placed"] = store.outbox(clock.now())
        # la personne l'envoie, en retouchant la fin : son message arrive par l'extension
        await push(desk, msg(clock, 2, item.text.replace("sans garantie.", "sans garantie, mais plus rapide !"),
                             author="Adrien Dupont", author_id=SELF, own=True))
        await sleep(2 * MINUTE)
        out["sent"] = events(kernel, teams_c.SENT)
        out["attention"] = events(kernel, attention_c.NOTICED)
        out["state"] = kernel.mind.frame().state("teams")
        out["journal"] = raw_journal(kernel)
        out["draft"] = store.draft(item.id)
        return out

    out = live(tmp_path, Model(), scenario, cfg=TeamsConfig(display_name="Adrien"))
    ref = message_ref(DM, "1759000000001")
    [noticed] = out["noticed"]
    assert noticed.data.message == ref and noticed.data.needs_reply and noticed.data.where == "dm"
    assert noticed.data.about == ("teams:8:orgid:alice",)
    # une tâche silencieuse : à la place de la personne, le message cité, sa voix de confiance ; ni mémoire ni identité
    [task, *_] = out["tasks"]
    text = prompt_text(task)
    assert "à la place** de Adrien" in text and "[À COMPLÉTER" in text
    assert re.search(r"^> .*TCP et UDP", text, re.M)  # le message : cité
    assert {t.name for t in task.tools} == {"teams_conversations", "teams_read", "teams_draft"}
    # une proposition sans corps : l'identifiant et le condensé, jamais le texte ; partie sans accord (posée)
    [proposal] = out["proposed"]
    args = json.loads(proposal.data.args_json)
    assert set(args) == {"draft", "conversation", "message", "mode", "_apercu"} and args["mode"] == "brouillon"
    assert not proposal.data.approval and args["message"] == ref
    assert "garantit l'ordre" not in out["journal"]
    # la file : à poser, puis posée (rejoué, rien ne change)
    [item] = out["outbox"]
    assert item.mode == "draft" and item.status == "queued" and item.text.startswith("TCP garantit")
    assert out["placed"].outcome == out["placed again"].outcome == "accepted"
    assert [i.status for i in out["after placed"]] == ["placed"]
    # partie, retouchée par la personne : elle le sait
    assert out["draft"].state == "parti" and out["draft"].edited and "plus rapide" in out["draft"].sent_text
    [sent] = out["sent"]
    assert sent.data.edited and sent.data.draft == item.id
    assert sent.seq in {e.data.signal for e in out["attention"]}
    [d] = out["state"].drafts.values()
    assert d.state == "parti" and d.edited


def test_the_owner_writing_something_else_means_the_reply_was_not_used(tmp_path):
    async def scenario(kernel, llm, desk, store, clock):
        await push(desk, msg(clock, 1, QUESTION), conversations=[conv(DM)])
        await sleep(30 * MINUTE)
        [item] = store.outbox(clock.now())
        await desk.ack(KEY, item.id, {"result": "placed"})
        await push(desk, msg(clock, 2, "Je regarde ça demain, promis.", author="Adrien", author_id=SELF, own=True))
        await sleep(MINUTE)
        return store.draft(item.id), kernel.mind.frame().state("teams"), events(kernel, teams_c.SENT)

    draft, state, sent = live(tmp_path, Model(), scenario)
    assert draft.state == "inutilise" and "autre chose" in draft.reason
    assert [d.state for d in state.drafts.values()] == ["inutilise"] and sent == []


# ── Après un accord ───────────────────────────────────────────────────────


def test_in_validation_mode_a_card_goes_to_her_and_nothing_leaves_without_it(tmp_path):
    async def scenario(kernel, llm, desk, store, clock):
        await connect(kernel, "user_1", "Adrien", operator=True)
        await push(desk, msg(clock, 1, QUESTION), conversations=[conv(DM)])
        await sleep(30 * MINUTE)
        out = {"proposed": events(kernel, rt.EFFECT_PROPOSED), "before": store.outbox(clock.now())}
        out["cards"] = await KernelPort(kernel).approval_cards("user_1")
        [card] = out["cards"]
        out["decided"] = await KernelPort(kernel).decide_card("user_1", card["id"], True, card["digest"])
        await sleep(MINUTE)
        out["after"] = store.outbox(clock.now())
        return out

    out = live(tmp_path, Model(), scenario, cfg=TeamsConfig(mode="validation"))
    [proposal] = out["proposed"]
    args = json.loads(proposal.data.args_json)
    assert proposal.data.approval and args[rt.DECIDER] == "user_1" and args[rt.EXPIRES] > proposal.at
    assert out["before"] == []  # rien en file avant l'accord
    [card] = out["cards"]
    assert card["text"].startswith("Dans Teams") and "TCP garantit" in card["text"]
    assert out["decided"] == "approved"
    [item] = out["after"]
    assert item.mode == "send" and item.status == "queued"


def test_without_an_answer_in_time_the_reply_does_not_leave(tmp_path):
    async def scenario(kernel, llm, desk, store, clock):
        await connect(kernel, "user_1", "Adrien", operator=True)
        await push(desk, msg(clock, 1, QUESTION), conversations=[conv(DM)])
        await sleep(3 * HOUR)
        return (events(kernel, rt.EFFECT_RESOLVED), events(kernel, rt.EFFECT_EXECUTED), store.outbox(clock.now()),
                kernel.mind.frame().state("teams"))

    resolved, executed, outbox, state = live(tmp_path, Model(), scenario, cfg=TeamsConfig(mode="validation"))
    [r] = resolved
    assert not r.data.approved and r.data.by == "teams.delai"
    assert executed == [] and outbox == []
    assert [d.state for d in state.drafts.values()] == ["expire"]  # pas d'accord à temps (pas « refusée »)


# ── Sans accord ; jamais de blanc qui part seul ───────────────────────────


def test_autonomous_replies_are_sent_without_asking(tmp_path):
    async def scenario(kernel, llm, desk, store, clock):
        await push(desk, msg(clock, 1, QUESTION), conversations=[conv(DM)])
        await sleep(30 * MINUTE)
        return events(kernel, rt.EFFECT_PROPOSED), store.outbox(clock.now())

    proposed, outbox = live(tmp_path, Model(), scenario, cfg=TeamsConfig(mode="autonome"))
    [proposal] = proposed
    assert not proposal.data.approval
    [item] = outbox
    assert item.mode == "send"


def test_a_blank_never_leaves_alone_but_can_be_posted_for_the_owner_to_fill(tmp_path):
    blank = Model(body="Oui, c'est prévu pour [À COMPLÉTER : la date].")

    async def scenario(kernel, llm, desk, store, clock):
        await push(desk, msg(clock, 1, "C'est prévu pour quand ?"), conversations=[conv(DM)])
        await sleep(HOUR)
        return events(kernel, rt.EFFECT_PROPOSED), store.outbox(clock.now())

    proposed, outbox = live(tmp_path / "seule", blank, scenario, cfg=TeamsConfig(mode="autonome"))
    assert proposed == [] and outbox == []
    # contre-exemple : posée dans Teams, la personne la complète avant de l'envoyer
    proposed, outbox = live(tmp_path / "posee", blank, scenario, cfg=TeamsConfig(mode="brouillon"))
    [item] = outbox
    assert len(proposed) == 1 and "[À COMPLÉTER : la date]" in item.text


# ── Où, quand, avec quoi ──────────────────────────────────────────────────


def test_she_prepares_replies_only_where_and_when_it_makes_sense(tmp_path):
    async def scenario(kernel, llm, desk, store, clock):
        await push(desk,
                   msg(clock, 1, QUESTION),  # en privé : oui
                   msg(clock, 2, "Quelqu'un sait où est le doc ?", conv=CHANNEL, author="Bob", author_id="8:b"),
                   msg(clock, 3, "On décale la démo ?", conv=GROUP, author="Chloé", author_id="8:c"),
                   msg(clock, 4, "Tu as vu mon mail d'hier ?", conv="19:old@unq.gbl.spaces", author="Dan",
                       author_id="8:d", ago_us=3 * HOUR),
                   msg(clock, 5, "Tu as rempli le formulaire ?", conv=HR, author="Eve", author_id="8:e"),
                   conversations=[conv(DM), conv(CHANNEL, "Général", "channel"), conv(GROUP, "Projet", "group"),
                                  conv("19:old@unq.gbl.spaces"), conv(HR, "RH", "group")])
        # la personne a déjà répondu dans le groupe
        await push(desk, msg(clock, 6, "Oui, jeudi.", conv=GROUP, author="Adrien", author_id=SELF, own=True))
        await sleep(2 * HOUR)
        starts = [e for e in events(kernel, rt.EPISODE_STARTED) if e.data.kind == Kind.TASK]
        return [e.data.target for e in starts], events(kernel, teams_c.NOTICED)

    targets, noticed = live(tmp_path, Model(), scenario, cfg=TeamsConfig(skip=("rh",)))
    assert set(targets) == {f"task:teams:{message_ref(DM, '1759000000001')}"}
    by_conv = {e.data.conversation: e.data for e in noticed}
    assert not by_conv[CHANNEL].needs_reply  # un canal où personne ne la mentionne : pas pour elle
    assert by_conv[GROUP].needs_reply  # une question pour elle… à laquelle la personne a déjà répondu


def test_without_initiative_she_only_drafts_when_asked(tmp_path):
    async def scenario(kernel, llm, desk, store, clock):
        await connect(kernel, "user_1", "Adrien", operator=True)
        await push(desk, msg(clock, 1, QUESTION), conversations=[conv(DM)])
        await sleep(HOUR)
        before = [e for e in events(kernel, rt.EPISODE_STARTED) if e.data.kind == Kind.TASK]
        ref = message_ref(DM, "1759000000001")
        asked = await perform(kernel, "teams.rediger", {"_champs": ["instruction"], "instruction": ["Fais court."],
                                                        "_fixes": ["message"], "message": [ref]},
                              by="user_1", subject=DM, nonce="a1")
        await sleep(30 * MINUTE)
        task = [c for c in llm.calls if c.role == "step" and "teams_draft" in prompt_text(c)]
        return before, asked, task, store.outbox(clock.now())

    before, asked, task, outbox = live(tmp_path, Model(), scenario, cfg=TeamsConfig(autodraft=False))
    assert before == [] and asked.ok
    text = prompt_text(task[0])
    assert "CE QU'ON TE DEMANDE D'Y RÉPONDRE" in text and "Fais court." in text
    assert len(outbox) == 1


def test_the_signature_is_added_by_the_server_never_written_by_her(tmp_path):
    async def scenario(kernel, llm, desk, store, clock):
        await push(desk, msg(clock, 1, QUESTION), conversations=[conv(DM)])
        await sleep(30 * MINUTE)
        return [c for c in llm.calls if c.role == "step"][0], store.outbox(clock.now())

    task, outbox = live(tmp_path, Model(), scenario, cfg=TeamsConfig(sign=True))
    [item] = outbox
    assert item.text.endswith("\n\n— rédigé avec Mika") and item.text.count("rédigé avec Mika") == 1
    assert "est ajoutée à l'envoi : ne l'écris pas" in prompt_text(task)


# ── Personne ne l'envoie ; oublier ────────────────────────────────────────


def test_a_reply_nobody_sends_in_time_does_not_leave_later(tmp_path):
    async def scenario(kernel, llm, desk, store, clock):
        await push(desk, msg(clock, 1, QUESTION), conversations=[conv(DM)])
        await sleep(30 * MINUTE)
        [item] = store.outbox(clock.now())
        await sleep(9 * HOUR)
        return item, store.draft(item.id), store.outbox(clock.now()), kernel.mind.frame().state("teams")

    item, draft, outbox, state = live(tmp_path, Model(), scenario)
    assert draft.state == "inutilise" and outbox == []
    assert [d.state for d in state.drafts.values()] == ["inutilise"]


def test_forgetting_a_colleague_reaches_the_journal_and_the_cache(tmp_path):
    async def scenario(kernel, llm, desk, store, clock):
        await push(desk, msg(clock, 1, QUESTION), conversations=[conv(DM)])
        await sleep(30 * MINUTE)
        [noticed] = events(kernel, teams_c.NOTICED)
        before = kernel.mind.store.content([noticed.data.summary.ref])
        out = await kernel.forget("teams:8:orgid:alice")
        after = kernel.mind.store.content([noticed.data.summary.ref])
        return before, after, out, store.message(noticed.data.message), store.conversation(DM), store.drafts(10)

    before, after, out, message, conversation, drafts = live(tmp_path, Model(), scenario)
    assert "TCP" in next(iter(before.values()))
    assert not any(after.values())
    assert out["teams"] >= 1 and message is None and conversation is None and drafts == []


# ── Ce que la relecture a trouvé ──────────────────────────────────────────


def test_her_answering_is_judged_on_teams_time_not_on_arrival(tmp_path):
    """Un vieux message de la personne qui arrive avec une question plus récente (un même lot, un rattrapage) ne
    répond pas à la question."""
    async def scenario(kernel, llm, desk, store, clock):
        await push(desk, msg(clock, 1, "Oui c'est bon.", author="Adrien", author_id=SELF, own=True, ago_us=20 * US),
                   msg(clock, 2, QUESTION, ago_us=5 * US), conversations=[conv(DM)])
        await sleep(30 * MINUTE)
        return [e.data.target for e in events(kernel, rt.EPISODE_STARTED) if e.data.kind == Kind.TASK]

    assert live(tmp_path, Model(), scenario) == [f"task:teams:{message_ref(DM, '1759000000002')}"]


def test_a_refused_reply_is_not_proposed_again(tmp_path):
    async def scenario(kernel, llm, desk, store, clock):
        await connect(kernel, "user_1", "Adrien", operator=True)
        await push(desk, msg(clock, 1, QUESTION), conversations=[conv(DM)])
        await sleep(30 * MINUTE)
        [card] = await KernelPort(kernel).approval_cards("user_1")
        await KernelPort(kernel).decide_card("user_1", card["id"], False, "")
        await sleep(HOUR)
        return events(kernel, rt.EFFECT_PROPOSED), kernel.mind.frame().state("teams")

    proposed, state = live(tmp_path, Model(), scenario, cfg=TeamsConfig(mode="validation"))
    assert len(proposed) == 1 and [d.state for d in state.drafts.values()] == ["refuse"]


def test_a_large_backlog_is_triaged_to_the_end(tmp_path):
    async def scenario(kernel, llm, desk, store, clock):
        await push(desk, *[msg(clock, i, f"Message {i}", conv=GROUP, author="Bob", author_id="8:b")
                           for i in range(1, 8)], conversations=[conv(GROUP, "Projet", "group")])
        await sleep(30 * MINUTE)
        return events(kernel, teams_c.NOTICED)

    noticed = live(tmp_path, Model(), scenario, overrides={"teams": {"per_run": 2}})
    assert len(noticed) == 7


def test_a_task_only_answers_the_message_it_was_given(tmp_path):
    other = message_ref(CHANNEL, "1759000000009")

    class Elsewhere(Model):
        def __call__(self, req):
            if req.role == "step" and not any(m.role == "tool" for m in req.messages) \
                    and "message=[" in prompt_text(req):
                return LLMResponse("", tool_calls=(ToolCall(f"{req.call_id}:d", "teams_draft",
                                                            {"message": other, "body": "Hop."}),), stop="tool_use")
            return super().__call__(req)

    async def scenario(kernel, llm, desk, store, clock):
        await push(desk, msg(clock, 1, QUESTION), msg(clock, 9, "salut", conv=CHANNEL, author="Bob", author_id="8:b"),
                   conversations=[conv(DM), conv(CHANNEL, "Général", "channel")])
        await sleep(30 * MINUTE)
        return events(kernel, rt.EFFECT_PROPOSED)

    assert live(tmp_path, Elsewhere(), scenario, cfg=TeamsConfig(mode="autonome")) == []


def test_disabled_teams_proposes_nothing(tmp_path):
    """Désactivé, rien n'est préparé, même avec l'initiative permise (la porte refuse l'extension ; ce qui est déjà
    reçu reste, sans réponse)."""
    async def scenario(kernel, llm, desk, store, clock):
        batch, _ = batch_of({"self": {}, "conversations": [conv(DM)], "messages": [msg(clock, 1, QUESTION)]},
                            clock.now() // 1000)
        store.store_batch(batch, clock.now())
        await kernel.mind.append([RECEIVED.draft(new=1)], emitter="teams", correlation="t", origin=Origin.EXTERNAL)
        await sleep(HOUR)
        tasks = [e for e in events(kernel, rt.EPISODE_STARTED) if e.data.kind == Kind.TASK]
        return events(kernel, teams_c.NOTICED), tasks, events(kernel, rt.EFFECT_PROPOSED)

    noticed, tasks, proposed = live(tmp_path, Model(), scenario, cfg=TeamsConfig(enabled=False),
                                    inputs={"autodraft": True})
    assert len(noticed) == 1 and tasks == [] and proposed == []


def test_a_message_deleted_in_teams_leaves_the_cache(tmp_path):
    async def scenario(kernel, llm, desk, store, clock):
        await push(desk, msg(clock, 1, "Mon code de badge est 4471"), conversations=[conv(DM)])
        await push(desk, {**msg(clock, 1, ""), "deleted": True})
        return store.message(message_ref(DM, "1759000000001"))

    assert live(tmp_path, Model(), scenario).text == ""
