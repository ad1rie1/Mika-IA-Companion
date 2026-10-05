"""Ses brouillons, par leurs intentions.

- elle écrit dans la voix de la boîte (à la place de son opérateur, son ton,
  ses consignes : de confiance ; le mail, lui, est cité) ;
- **le texte d'un brouillon n'entre jamais dans le journal** : une proposition
  ne porte que son identifiant et le condensé de ce qui a été montré ;
- l'opérateur lit exactement ce qui partira, peut le retoucher ; **c'est ce
  qu'il a lu qui part** (retouché après, ça ne part pas ; un « [À COMPLÉTER »
  ne part jamais) ; parti, elle le sait (retouché ou non) ;
- elle prépare d'elle-même des réponses sur les boîtes où on le lui a permis,
  jamais aux envois de masse ni aux adresses exclues, au plus quelques-unes
  par jour, sans s'acharner ; une réponse demandée passe devant ;
- refuser, lui demander de reprendre : elle l'apprend ;
- ranger (archiver, suivre, corbeille, supprimer depuis la corbeille) agit sur
  le serveur, et elle ne parle plus d'un mail rangé ; un mail lu ailleurs non
  plus ;
- une faculté ne décide que de ses propres propositions.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import replace

from mika.app import composition
from mika.app.mindport import KernelPort
from mika.contracts import attention as attention_c
from mika.contracts import email as email_c
from mika.contracts import runtime as rt
from mika.inspector import render
from mika.kernel.clock import HOUR, MINUTE, US
from mika.kernel.events import Content, Origin
from mika.kernel.inspect import (
    ActionSlot,
    Fields,
    Nav,
    NavItem,
    Note,
    Prose,
    Ref,
    Table,
    walk_blocks,
)
from mika.plugins.email.console.common import mail_key
from mika.ports.llm import LLMResponse, ToolCall
from mika.ports.mail import AccountInfo, Mail
from mika.runtime import decisions
from mika.runtime.inspection import find, run_view
from mika.runtime.operations import perform
from mika.sim.clock import SimClock, run_virtual
from mika.sim.outside import FakeMail
from mika.vocab.episodes import Kind
from tests.fixtures.mika import DOC, at_paris, build, connect, said

ALICE = "Alice <alice@exemple.fr>"
PERSO = AccountInfo("perso", "Perso", "mika@exemple.fr", display_name="Adrien Dupont", voice="proprietaire",
                    tone="sobre, vouvoiement", instructions="Ne jamais promettre de date ferme.",
                    signature="Adrien Dupont", ready=True, can_send=True)
PRO = AccountInfo("pro", "Pro", "contact@atelier.fr", voice="assistante", display_name="Adrien", ready=True,
                  can_send=True)
START = at_paris(2026, 9, 28, 10, 0)


def form(**values) -> dict[str, list[str]]:
    return {"_champs": [k for k in values if not k.startswith("_")], **{k: [str(v)] for k, v in values.items()}}


def fixed(**values) -> dict[str, list[str]]:
    """Des valeurs posées par la page (champs cachés)."""
    return {"_fixes": list(values), **{k: [str(v)] for k, v in values.items()}}


def mail(n: int, subject: str, body: str, *, account: str = "perso", sender: str = ALICE, at: int = START,
         bulk: bool = False) -> Mail:
    address = sender.split("<")[-1].rstrip(">")
    return Mail(f"<m{n}@exemple.fr>", sender, address, subject, at, body, to="mika@exemple.fr", bulk=bulk,
                account=account)


def prompt_text(req) -> str:
    return "\n".join([req.system_stable, req.system_volatile, *(str(m.content) for m in req.messages)])


def events(kernel, event_type) -> list:
    return [kernel.mind.decode(s) for s in kernel.mind.store.read(types={event_type.name})]


def raw_journal(kernel) -> str:
    return "\n".join(s.data for s in kernel.mind.store.read())


def view(kernel, name: str, subject: str = "", **params: str) -> list:
    spec = find(kernel, "email", name)
    assert spec is not None, name
    return run_view(kernel, spec, params, subject=subject)


def walk(blocks):
    return walk_blocks(blocks)

class Model:
    """Un modèle scripté : le tri dit « réponse attendue » ; une tâche rédige (ou pas)."""

    def __init__(self, bodies=("Avec plaisir pour jeudi. [À COMPLÉTER : l'heure]",), *, draft_in_tasks=True):
        self.bodies = list(bodies)
        self.draft_in_tasks = draft_in_tasks

    def __call__(self, req):
        if req.role == "triage":
            return LLMResponse('{"importance": 0.6, "resume": "", "reponse": true, "emotion": ""}')
        if req.role == "step":
            if any(m.role == "tool" for m in req.messages) or not self.draft_in_tasks:
                return LLMResponse("Brouillon prêt.")
            found = re.search(r"mail=\[(.+?)\]", prompt_text(req))
            if found is None:  # un pas de travail ordinaire, pas une tâche de rédaction
                return LLMResponse("Rien à faire.")
            ref = found.group(1)
            body = self.bodies.pop(0) if len(self.bodies) > 1 else self.bodies[0]
            return LLMResponse("", tool_calls=(ToolCall(f"{req.call_id}:d", "email_draft",
                                                        {"mail": ref, "body": body}),), stop="tool_use")
        if req.role in ("reply", "initiative"):
            return LLMResponse("d'accord [EMOTION:neutral:0.3]")
        return LLMResponse("{}")


def live(tmp_path, box: FakeMail, model, scenario, *, inputs=None, overrides=None, start=START):
    clock = SimClock(start)
    box.now = clock.now
    kernel, clock, llm, _ = build(tmp_path, model, clock=clock, ports={"mail": box})

    async def main():
        await kernel.start(configure=lambda k: composition.configure(k, DOC, overrides, inputs))
        try:
            return await scenario(kernel, llm)
        finally:
            await kernel.lanes.join()
            await kernel.stop()

    return run_virtual(clock, main)


def sleep(seconds_us: int):
    return asyncio.sleep(seconds_us / US)


# ── Elle rédige ; ce que tu as lu part ────────────────────────────────────


def test_she_drafts_in_the_voice_of_the_box_and_only_what_you_read_leaves(tmp_path):
    box = FakeMail(boxes=[PERSO])
    box.deliver(mail(1, "Un café jeudi ?", "On se voit jeudi ?"))
    ref = "perso:<m1@exemple.fr>"

    async def scenario(kernel, llm):
        await connect(kernel, "user_1", "Adrien", operator=True)
        await sleep(40 * MINUTE)  # relevé, tri, puis la tâche de rédaction
        out = {"proposed": events(kernel, rt.EFFECT_PROPOSED), "tasks": [c for c in llm.calls if c.role == "step"]}
        [draft] = box.drafts(5)
        out["draft"] = draft.id
        out["fiche"] = view(kernel, "brouillon", subject=draft.id)
        shown = box.preview(draft.id)
        out["blocked send"] = await perform(kernel, "email.envoyer_brouillon", fixed(draft=draft.id, seen=shown.digest),
                                            by="user_1", nonce="e0")
        out["retouch"] = await perform(kernel, "email.retoucher", {**form(to=draft.to, cc="", subject=draft.subject,
                                                                          body="Avec plaisir pour jeudi, à 15 h.",
                                                                          quote="1"),
                                                                     **fixed(draft=draft.id)}, by="user_1", nonce="r1")
        out["stale send"] = await perform(kernel, "email.envoyer_brouillon", fixed(draft=draft.id, seen=shown.digest),
                                          by="user_1", nonce="e1")
        now = box.preview(draft.id)
        out["approvals preview"] = await KernelPort(kernel).effect_preview(out["proposed"][0].seq)
        out["send"] = await perform(kernel, "email.envoyer_brouillon", fixed(draft=draft.id, seen=now.digest),
                                    by="user_1", nonce="e2")
        await sleep(2 * MINUTE)
        out["sent"] = events(kernel, email_c.SENT)
        out["attention"] = events(kernel, attention_c.NOTICED)
        out["executed"] = events(kernel, rt.EFFECT_EXECUTED)
        out["state"] = kernel.mind.frame().state("email")
        out["journal"] = raw_journal(kernel)
        out["contents"] = kernel.mind.store.content([e.data.summary.ref for e in out["proposed"]])
        await (await kernel.perceive(said("user_1", "tu as vu mes mails ?"))).reply
        out["reply"] = [c for c in llm.calls if c.role == "reply"][-1]
        return out

    out = live(tmp_path, box, Model(), scenario, inputs={"email": {"autodraft": ("perso",)}})
    # une tâche silencieuse, dans la voix de la boîte ; le mail cité, les consignes de confiance
    task = prompt_text(out["tasks"][0])
    assert "à la place** de Adrien Dupont" in task and "Ne jamais promettre de date ferme." in task
    assert "> On se voit jeudi ?" in task  # le mail : cité
    assert not re.search(r"^> .*Ne jamais promettre", task, re.M)  # les consignes : pas citées comme des données
    # une proposition sans corps : l'identifiant et le condensé, jamais le texte
    [proposal] = out["proposed"]
    args = json.loads(proposal.data.args_json)
    assert set(args) == {"draft", "account", "mail", "_apercu"} and args["mail"] == ref
    assert "Avec plaisir" not in out["journal"] and "15 h" not in out["journal"]
    assert "Avec plaisir" not in str(out["contents"])
    assert f"mail:{'alice@exemple.fr'}" in proposal.data.about
    # la fiche : exactement ce qui partira ; « à compléter » ne part pas
    fiche = out["fiche"]
    head = next(b for b in fiche if isinstance(b, Fields) and b.title == "Ce qui partira")
    assert dict(head.pairs)["de"].text == "Adrien Dupont <mika@exemple.fr>"
    text = next(b for b in fiche if isinstance(b, Prose)).text
    assert "-- \nAdrien Dupont" in text and "> On se voit jeudi ?" in text
    assert any(isinstance(b, Note) and "compléter" in b.text for b in fiche)
    assert not out["blocked send"].ok and "tel quel" in out["blocked send"].message
    # retouché : c'est la version lue qui part ; un accord sur l'ancienne est refusé
    assert out["retouch"].ok and box.draft(out["draft"]).edited_by == "user_1"
    assert not out["stale send"].ok and "relis-le" in out["stale send"].message
    assert "De : Adrien Dupont <mika@exemple.fr>" in out["approvals preview"].text
    assert out["send"].ok
    [executed] = out["executed"]
    assert executed.data.ok
    [gone] = box.outgoing
    assert "15 h" in gone.body and "-- \nAdrien Dupont" in gone.body and gone.in_reply_to == ref
    # elle le sait : parti, retouché par son opérateur ; le mail quitte ses non-lus (elle y a répondu)
    [sent] = out["sent"]
    assert sent.data.edited and sent.data.by == "user_1" and sent.data.draft == out["draft"]
    assert sent.seq in {e.data.signal for e in out["attention"]}
    assert out["state"].mails[ref].read and out["state"].mails[ref].how == "répondu"
    reply = prompt_text(out["reply"])
    assert "TES BROUILLONS DE MAILS" in reply and "est parti" in reply


# ── Préparer d'elle-même : où, pour qui, combien ──────────────────────────


def test_she_prepares_replies_only_where_allowed_and_never_endlessly(tmp_path):
    box = FakeMail(boxes=[PERSO, PRO])
    box.deliver(mail(1, "Un café jeudi ?", "On se voit jeudi ?"))
    box.deliver(mail(2, "Devis", "Pouvez-vous m'envoyer un devis ?", account="pro", sender="Bob <bob@client.fr>"))
    box.deliver(mail(3, "Promo !", "Profitez-en ?", sender="Boutique <promo@shop.fr>", bulk=True))
    box.deliver(mail(4, "Votre commande", "Une question ?", sender="Service <aide@shop.fr>"))
    box.deliver(mail(5, "Samedi ?", "Tu viens samedi ?", sender="Carla <carla@exemple.fr>"))

    async def scenario(kernel, llm):
        await sleep(8 * HOUR)
        starts = [e for e in events(kernel, rt.EPISODE_STARTED) if e.data.kind == Kind.TASK]
        return [e.data.target for e in starts], kernel.mind.frame().state("email")

    targets, state = live(tmp_path, box, Model(draft_in_tasks=False), scenario,
                          inputs={"email": {"autodraft": ("perso",), "autodraft_skip": ("@shop.fr",)}},
                          overrides={"email": {"drafts_per_day": 1}})
    mails = {t.rsplit(":", 1)[-1] for t in targets}
    assert mails <= {"<m1@exemple.fr>", "<m5@exemple.fr>"}  # ni la boîte pro, ni la masse, ni une adresse exclue
    # sans brouillon, elle ne s'acharne pas : deux essais par mail au plus
    assert all(targets.count(t) <= 2 for t in set(targets)) and targets
    assert all(n <= 2 for n in state.attempts.values())


def test_a_reply_you_ask_for_goes_first_and_redoing_it_is_learnt(tmp_path):
    box = FakeMail(boxes=[PERSO])
    box.deliver(mail(1, "Un café jeudi ?", "On se voit jeudi ?"))
    ref = "perso:<m1@exemple.fr>"

    async def scenario(kernel, llm):
        await connect(kernel, "user_1", "Adrien", operator=True)
        await sleep(15 * MINUTE)
        out = {"before": [c for c in llm.calls if c.role == "step"]}
        out["ask"] = await perform(kernel, "email.rediger", form(instruction="Dis oui, mais pas avant 15 h."),
                                   by="user_1", subject=ref, nonce="a1")
        out["ask again"] = await perform(kernel, "email.rediger", form(instruction="x"), by="user_1", subject=ref,
                                         nonce="a2")
        await sleep(20 * MINUTE)
        out["task"] = [c for c in llm.calls if c.role == "step"]
        [first] = box.drafts(5)
        out["redo"] = await perform(kernel, "email.reprendre", {**form(instruction="Plus court."),
                                                                  **fixed(draft=first.id)}, by="user_1", nonce="p1")
        await sleep(20 * MINUTE)
        second = next(d for d in box.drafts(5) if d.id != first.id)
        out["refuse"] = await perform(kernel, "email.refuser_brouillon", {**form(note="finalement non"),
                                                                            **fixed(draft=second.id)},
                                      by="user_1", nonce="f1")
        await (await kernel.perceive(said("user_1", "alors, ce mail ?"))).reply
        out["reply"] = [c for c in llm.calls if c.role == "reply"][-1]
        out["state"] = kernel.mind.frame().state("email")
        out["notes"] = kernel.mind.store.content([d.note_ref for d in out["state"].drafts.values()])
        out["first"], out["second"] = box.draft(first.id), box.draft(second.id)
        return out

    out = live(tmp_path, box, Model(bodies=("Oui pour jeudi, 15 h.", "Oui, 15 h.")), scenario)
    assert out["before"] == []  # pas de brouillon d'elle-même sur cette boîte
    assert out["ask"].ok and not out["ask again"].ok  # déjà demandé : l'action n'est plus offerte
    task = prompt_text(out["task"][0])
    assert "CE QU'ON TE DEMANDE D'Y RÉPONDRE" in task and "Dis oui, mais pas avant 15 h." in task
    # elle dit le prénom de qui le lui demande, jamais « ton opérateur »
    assert "Adrien te demande de préparer une réponse" in task and "opérateur" not in task
    assert out["redo"].ok and out["refuse"].ok
    drafts = sorted(out["state"].drafts.values(), key=lambda d: d.proposal)
    assert [d.state for d in drafts] == ["refuse", "refuse"] and all(d.asked for d in drafts)
    notes = out["notes"]
    assert notes[drafts[0].note_ref].startswith("à reprendre : Plus court") and notes[drafts[1].note_ref] == "finalement non"
    assert out["first"].state == "abandonne" and out["second"].state == "abandonne"
    reply = prompt_text(out["reply"])
    assert "a été refusé" in reply and "finalement non" in reply


# ── Ranger : sur le serveur, et elle n'en parle plus ──────────────────────


def test_tidying_acts_on_the_server_and_quiets_her(tmp_path):
    box = FakeMail()
    for n, subject in enumerate(("Archive-moi", "Lu ailleurs", "À jeter", "À suivre"), start=1):
        box.deliver(mail(n, subject, "Rien d'urgent.", account=""))

    async def scenario(kernel, llm):
        await sleep(15 * MINUTE)
        out = {"before": sorted(m.mail for m in kernel.mind.frame().get(email_c.UNREAD))}
        out["archive"] = await perform(kernel, "email.ranger", fixed(mail="<m1@exemple.fr>", geste="archiver"),
                                       by="user_1", nonce="g1")
        out["follow"] = await perform(kernel, "email.ranger", fixed(mail="<m4@exemple.fr>", geste="suivre"),
                                      by="user_1", nonce="g2")
        box.read_on_another_device("<m2@exemple.fr>")
        out["trash"] = await perform(kernel, "email.corbeille", form(), by="user_1", subject="<m3@exemple.fr>",
                                     nonce="c1")
        out["delete wrong"] = await perform(kernel, "email.supprimer", {**form(), "_confirmer": ["<m3@exemple.fr>"]},
                                            by="user_1", subject="<m4@exemple.fr>", nonce="d0")
        out["delete"] = await perform(kernel, "email.supprimer", {**form(), "_confirmer": ["<m3@exemple.fr>"]},
                                      by="user_1", subject="<m3@exemple.fr>", nonce="d1")
        await sleep(15 * MINUTE)  # le relevé suivant apprend ce qui a été lu ailleurs
        out["after"] = sorted(m.mail for m in kernel.mind.frame().get(email_c.UNREAD))
        out["how"] = {k: m.how for k, m in kernel.mind.frame().state("email").mails.items()}
        out["box"] = view(kernel, "reception", dossier="*")
        return out

    out = live(tmp_path, box, Model(), scenario)
    assert out["before"] == ["<m1@exemple.fr>", "<m2@exemple.fr>", "<m3@exemple.fr>", "<m4@exemple.fr>"]
    assert out["archive"].ok and out["follow"].ok and out["trash"].ok and out["delete"].ok
    assert not out["delete wrong"].ok  # on ne supprime définitivement que depuis la corbeille
    assert ("move", "<m1@exemple.fr>", "Archives") in box.actions and ("flagged", "<m4@exemple.fr>") in box.actions
    assert ("delete", "<m3@exemple.fr>") in box.actions and box.cached_one("<m3@exemple.fr>") is None
    assert out["after"] == ["<m4@exemple.fr>"]  # suivre n'est pas lire
    assert out["how"]["<m1@exemple.fr>"] == "archivé" and out["how"]["<m2@exemple.fr>"] == "ailleurs"
    assert out["how"]["<m3@exemple.fr>"] == "corbeille"
    listed = next(b for b in walk(out["box"]) if isinstance(b, Table) and b.title.startswith("Tous les dossiers"))
    starred = {r.cells[0].text: r.cells[-1] for r in listed.rows}
    assert starred["À suivre"].text == "★ Suivi · Non lu"
    nav = [b for b in walk(out["box"]) if isinstance(b, Nav) and b.title == "Dossiers"]
    assert nav and "Archives" in [i.text for i in nav[-1].items]


# ── Les décisions : génériques, et bornées ────────────────────────────────


def test_a_faculty_decides_only_its_own_proposals_and_what_changed_is_reread(tmp_path):
    box = FakeMail(boxes=[PERSO])
    box.deliver(mail(1, "Un café jeudi ?", "On se voit jeudi ?"))

    async def scenario(kernel, llm):
        await sleep(40 * MINUTE)
        [draft] = box.drafts(5)
        box.save_draft(replace(draft, body="Oui, 15 h."))  # retouché hors de la page
        mine = next(e for e in events(kernel, rt.EFFECT_PROPOSED) if e.data.owner == "email")
        await kernel.mind.append([rt.EFFECT_PROPOSED.draft(
            capability="goals.networked", owner="goals", args_json="{}", summary=Content.of("autre chose"),
            approval=True, context="goal:1")], emitter="runtime", correlation="t", origin=Origin.TOOL)
        other = next(e for e in events(kernel, rt.EFFECT_PROPOSED) if e.data.owner == "goals")
        port = KernelPort(kernel)
        return (await decisions.prepare(kernel.mind, kernel.ports, other.seq, True, by="user_1", owner="email"),
                await port.resolve_effect(mine.seq, True, by="user_1"),  # sans aperçu lu : celui de la proposition
                await port.resolve_effect(mine.seq, True, by="user_1", seen=box.preview(draft.id).digest))

    foreign, stale, fresh = live(tmp_path, box, Model(bodies=("Oui pour jeudi.",)), scenario,
                                 inputs={"email": {"autodraft": ("perso",)}})
    assert foreign.status == decisions.UNKNOWN and foreign.draft is None
    assert stale == decisions.CHANGED and fresh == decisions.APPROVED


def test_a_navigation_row_stays_text_and_encodes_its_links():
    block = Nav((NavItem('<b onclick="x">Réception</b>', Ref("local", "/inspecteur/courrier/reception", "",
                                                              (("dossier", "R&D / Été"), ("compte", "perso"))),
                         count=3, active=True),
                 NavItem("Ailleurs", Ref("local", "https://ailleurs.example/", "")),), title="Dossiers")
    shown = render.block(block, render.Env(when=str, now=0), {})
    first, second = shown["items"]
    assert first["href"] == "/inspecteur/courrier/reception?dossier=R%26D+%2F+%C3%89t%C3%A9&compte=perso"
    assert first["text"] == '<b onclick="x">Réception</b>' and first["active"] and first["count"] == "3"
    assert second["href"] == ""  # jamais une autre adresse
    from mika.inspector.ui import env as jinja

    html = jinja.from_string('{% from "_blocks.html" import render %}{{ render(items, {}) }}').render(items=[shown])
    assert "&lt;b onclick" in html and "<b onclick" not in html and 'aria-current="page"' in html


def test_the_draft_actions_are_placed_on_the_fiche_with_what_was_read(tmp_path):
    box = FakeMail(boxes=[PERSO])
    box.deliver(mail(1, "Un café jeudi ?", "On se voit jeudi ?"))

    async def scenario(kernel, llm):
        await sleep(40 * MINUTE)
        [draft] = box.drafts(5)
        return draft, view(kernel, "brouillon", subject=draft.id), view(kernel, "brouillons")

    draft, fiche, listing = live(tmp_path, box, Model(bodies=("Oui pour jeudi.",)), scenario,
                                 inputs={"email": {"autodraft": ("perso",)}})
    slots = {s.action: dict(s.initial) for s in walk(fiche) if isinstance(s, ActionSlot)}
    assert slots["email.envoyer_brouillon"]["seen"] == box.preview(draft.id).digest
    assert slots["email.retoucher"]["body"] == "Oui pour jeudi." and "email.refuser_brouillon" in slots
    waiting = next(b for b in walk(listing) if isinstance(b, Table) and b.title.startswith("À décider"))
    assert len(waiting.rows) == 1 and waiting.rows[0].href.key == f"brouillon/{draft.id}"
    assert mail_key("perso:<m1@exemple.fr>") == "perso:<m1@exemple.fr>"
