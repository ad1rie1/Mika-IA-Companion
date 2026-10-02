"""Le client mail de la console : écrire, répondre, relever, classer — et elle le sait.

- un mail écrit depuis la console part de sa boîte tout de suite, est gardé
  dans « Envoyés » avec son auteur, et journalisé comme venant de l'opérateur
  (``email.sent``, un signal) : son attention le remarque ;
- répondre part de la fiche d'un mail (le mail auquel on répond est posé par
  la page, jamais tapé) ; le fil relie les deux ; la réponse de l'autre, quand
  elle arrive, lui est présentée comme telle ;
- un double envoi ne part qu'une fois ; une boîte non configurée refuse sans
  rien envoyer ;
- « relever maintenant » relève même si elle dort ; classer et tout marquer
  comme lu la font taire sur ces mails.
"""

from __future__ import annotations

import asyncio

from mika.contracts import attention as attention_c
from mika.contracts import email as email_c
from mika.contracts import runtime as rt
from mika.inspector.formview import action_view
from mika.kernel.clock import MINUTE, US
from mika.kernel.events import Origin
from mika.kernel.inspect import (
    ActionSlot,
    Badge,
    Entry,
    Head,
    InspectContext,
    Prose,
    Table,
    Timeline,
    walk_blocks,
)
from mika.plugins.email.console import mail_key
from mika.plugins.email.console.mail import _document
from mika.ports.mail import Mail
from mika.runtime.inspection import Inspection, find, run_view
from mika.runtime.operations import perform
from mika.sim.clock import SimClock, run_virtual
from mika.sim.outside import FakeMail
from tests.fixtures.mika import at_paris, boot, build, reply

ALICE = "Alice <alice@exemple.fr>"


def test_long_reading_parts_preserve_every_character_and_use_line_boundaries():
    text = "Une ligne complète à conserver.\n" * 4000 + "DERNIÈRE LIGNE"
    pieces = []
    for number in (1, 2, 3):
        ctx = InspectContext(store=None, ports={}, params={"page_texte": str(number)})
        pieces.append(next(b.text for b in _document(ctx, "<long@x>", text) if isinstance(b, Prose)))
    assert "".join(pieces) == text
    assert all(p.startswith("Une ligne") for p in pieces)


def form(**values: str) -> dict[str, list[str]]:
    return {"_champs": [k for k in values if not k.startswith("_")], **{k: [v] for k, v in values.items()}}


def mail(n: int, subject: str, body: str, *, at: int, sender: str = ALICE, in_reply_to: str = "") -> Mail:
    address = sender.split("<")[-1].rstrip(">")
    return Mail(f"<m{n}@exemple.fr>", sender, address, subject, at, body, to="mika@exemple.fr",
                in_reply_to=in_reply_to)


def live(tmp_path, box: FakeMail, scenario, *, start: int):
    clock = SimClock(start)
    box.now = clock.now
    kernel, clock, _, _ = build(tmp_path, reply("d'accord [EMOTION:neutral:0.3]"), clock=clock,
                                ports={"mail": box})

    async def main():
        await boot(kernel)
        try:
            return await scenario(kernel)
        finally:
            await kernel.stop()

    return run_virtual(clock, main)


def events(kernel, event_type) -> list:
    return [kernel.mind.decode(s) for s in kernel.mind.store.read(types={event_type.name})]


def view(kernel, name: str, subject: str = "", **params: str) -> list:
    spec = find(kernel, "email", name)
    assert spec is not None, name
    return run_view(kernel, spec, params, subject=subject)


def table(blocks, title: str) -> Table:
    return next(b for b in walk_blocks(blocks) if isinstance(b, Table) and b.title.startswith(title))


def test_the_operator_writes_replies_and_she_knows(tmp_path):
    box = FakeMail()
    start = at_paris(2026, 9, 28, 10, 0)
    box.deliver(mail(1, "Un café jeudi ?", "On se voit jeudi ?", at=start))

    async def scenario(kernel):
        await asyncio.sleep(15 * MINUTE / US)  # la relève remarque le mail d'Alice
        out = {}
        out["écrire"] = await perform(kernel, "email.ecrire", form(to="Bob <bob@exemple.fr>", subject="Salut",
                                                                    body="Coucou Bob."), by="user_1", nonce="w1")
        out["encore"] = await perform(kernel, "email.ecrire", form(to="Bob <bob@exemple.fr>", subject="Salut",
                                                                    body="Coucou Bob."), by="user_1", nonce="w1")
        reply_form = {**form(to="alice@exemple.fr", subject="Re: Un café jeudi ?", body="Avec plaisir !"),
                      "_fixes": ["reply_to"], "reply_to": ["<m1@exemple.fr>"]}
        out["répondre"] = await perform(kernel, "email.repondre", reply_form, by="user_1", nonce="r1")
        out["mauvaise adresse"] = await perform(kernel, "email.ecrire", form(to="pas une adresse", subject="x",
                                                                              body="y"), by="user_1", nonce="w2")
        await asyncio.sleep(2 * MINUTE / US)  # son attention remarque ce qui est parti
        answer_to = box.outgoing[-1].message_id
        box.deliver(mail(2, "Re: Un café jeudi ?", "Super, à jeudi !", at=kernel.mind.clock.now(),
                         in_reply_to=answer_to))
        await asyncio.sleep(15 * MINUTE / US)  # la réponse d'Alice arrive
        out["sent"] = events(kernel, email_c.SENT)
        out["noticed"] = events(kernel, email_c.NOTICED)
        out["texts"] = kernel.mind.store.content([e.data.summary.ref for e in out["noticed"]])
        out["attention"] = events(kernel, attention_c.NOTICED)
        out["audit"] = events(kernel, rt.OPERATED)
        out["envoyés"] = view(kernel, "envoyes")
        out["contacts"] = view(kernel, "contacts")
        out["fil"] = view(kernel, "fil", subject=mail_key(answer_to))
        out["sait"] = view(kernel, "remarque", subject=mail_key(answer_to))
        out["fiche"] = Inspection(kernel).head("mail", mail_key(answer_to))
        out["message"] = view(kernel, "message", subject="<m1@exemple.fr>")
        return out

    out = live(tmp_path, box, scenario, start=start)
    assert out["écrire"].ok and out["encore"].deduped and out["répondre"].ok
    assert not out["mauvaise adresse"].ok and "to" in out["mauvaise adresse"].errors
    assert [(m.to, m.by, m.in_reply_to) for m in box.outgoing] == [
        ("Bob <bob@exemple.fr>", "user_1", ""), ("alice@exemple.fr", "user_1", "<m1@exemple.fr>")]  # un envoi chacun
    sent = out["sent"]
    assert len(sent) == 2 and all(e.origin is Origin.EXTERNAL and e.data.by == "user_1" for e in sent)
    assert {e.seq for e in sent} <= {e.data.signal for e in out["attention"]}  # elle l'a remarqué
    assert [e.data.outcome for e in out["audit"] if e.data.action.startswith("email.")] == ["done", "done", "refused"]
    answer = next(e for e in out["noticed"] if e.data.mail == "<m2@exemple.fr>")
    summary = out["texts"].get(answer.data.summary.ref, "")
    # la réponse ne la surprend pas ; et elle ne dit jamais « ton opérateur » (son prénom, sinon ceci)
    assert summary.startswith("Réponse à un mail que la personne qui s'occupe de toi a envoyé")
    gone = table(out["envoyés"], "Envoyés")
    assert len(gone.rows) == 2 and all(isinstance(r.cells[3], Badge) and "opérateur" in r.cells[3].text
                                       for r in gone.rows)
    book = {r.cells[1].text: (r.cells[2].text, r.cells[3].text) for r in table(out["contacts"], "Contacts").rows}
    assert book["alice@exemple.fr"] == ("2", "1") and book["bob@exemple.fr"] == ("0", "1")
    thread = next(b for b in out["fil"] if isinstance(b, Timeline))
    assert [e.title for e in thread.entries if isinstance(e, Entry)] == [
        "Un café jeudi ?", "↗ Re: Un café jeudi ?", "Re: Un café jeudi ?"]
    assert isinstance(out["fiche"], Head) and "parti de sa boîte" in [b.text for b in out["fiche"].badges]
    assert any("opérateur" in str(getattr(b, "pairs", "")) for b in out["sait"])
    slot = [b for b in walk_blocks(out["message"]) if isinstance(b, ActionSlot) and b.title == "Répondre"]
    assert slot and dict(slot[0].initial)["reply_to"] == "<m1@exemple.fr>"


def test_an_unconfigured_box_refuses_and_sends_nothing(tmp_path):
    box = FakeMail(enabled=False)

    async def scenario(kernel):
        return (await perform(kernel, "email.ecrire", form(to="bob@exemple.fr", subject="x", body="y"),
                              by="user_1", nonce="n"),
                await perform(kernel, "email.relever", form(), by="user_1", nonce="p"))

    written, polled = live(tmp_path, box, scenario, start=at_paris(2026, 9, 28, 10, 0))
    assert not written.ok and "pas configurée" in written.message and box.outgoing == []
    assert not polled.ok


def test_poll_now_works_while_she_sleeps_and_filing_quiets_her(tmp_path):
    box = FakeMail()
    night = at_paris(2026, 9, 29, 3, 0)
    box.deliver(mail(1, "Important", "Réponds vite.", at=night))
    box.deliver(mail(2, "Autre", "Rien d'urgent.", at=night + 1))

    async def scenario(kernel):
        await asyncio.sleep(20 * MINUTE / US)
        box.deliver(mail(3, "Arrivé en pleine nuit", "…", at=kernel.mind.clock.now()))
        before = box.polls
        asked = await perform(kernel, "email.relever", form(), by="user_1", nonce="p1")
        await asyncio.sleep(MINUTE / US)
        after = box.polls
        await asyncio.sleep(40 * MINUTE / US)
        later = box.polls
        unread = sorted(m.mail for m in kernel.mind.frame().get(email_c.UNREAD))
        filed = await perform(kernel, "email.classer", form(), by="user_1", subject="<m1@exemple.fr>", nonce="c1")
        left = sorted(m.mail for m in kernel.mind.frame().get(email_c.UNREAD))
        again = await perform(kernel, "email.classer", form(), by="user_1", subject="<m1@exemple.fr>", nonce="c2")
        everything = await perform(kernel, "email.tout_lu", form(), by="user_1", nonce="t1")
        return (before, asked, after, later, unread, filed, left, again, everything,
                kernel.mind.frame().get(email_c.UNREAD))

    before, asked, after, later, unread, filed, left, again, everything, final = live(tmp_path, box, scenario,
                                                                                    start=night)
    assert asked.ok and after == before + 1  # endormie, une relève quand même : celle qu'on a demandée
    assert later == after  # et aucune autre avant son réveil
    assert unread == ["<m1@exemple.fr>", "<m2@exemple.fr>", "<m3@exemple.fr>"]  # le mail de la nuit est là
    assert filed.ok and left == ["<m2@exemple.fr>", "<m3@exemple.fr>"]
    assert not again.ok  # déjà classé : l'action n'est plus offerte
    assert everything.ok and final == ()


def test_the_reply_form_carries_the_mail_it_answers_without_showing_it():
    """Le mail auquel on répond est posé par la page (une valeur fixée) : il n'est
    jamais un champ à taper, et il revient au moteur tel quel."""

    class Spec:
        from mika.plugins.email.console import ReplyArgs as args

        owner, name, key, title, description = "email", "repondre", "email.repondre", "Répondre", ""
        retype, confirm, danger = False, "", False

    view_ = action_view(Spec, csrf="t", back="/inspecteur/", initial={"to": "a@b.fr", "subject": "Re: x",
                                                                      "reply_to": "<m1@exemple.fr>"})
    assert [f["path"] for f in view_["fields"]] == ["to", "cc", "subject", "body", "quote"]
    assert ("reply_to", "<m1@exemple.fr>") in view_["fixed"]
