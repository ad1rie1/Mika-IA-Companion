"""Ses outils de courrier, pour qu'elle gère une boîte sans tout rouvrir.

- chaque mail dit sa date, ce que son tri en a jugé (important, une réponse
  attendue) et ce qu'il porte (répondu, suivi, des pièces jointes) ;
- une liste se lit page par page, et dit jusqu'où remonte ce qu'elle a relevé :
  au-delà, « rien » ne veut pas dire que le mail n'existe pas ;
- chercher, c'est trouver chaque mot, dans n'importe quel ordre, et par
  expéditeur aussi ;
- elle retrouve l'adresse de quelqu'un.
"""

from __future__ import annotations

import asyncio
import itertools
import json

from mika.faculties.identity import audience_for
from mika.kernel.clock import MINUTE, US
from mika.kernel.frame import EpisodeRef, Frame
from mika.ports.llm import LLMRequest, LLMResponse
from mika.ports.mail import AccountInfo, Attachment, Mail
from mika.runtime.pipeline import EpisodeRequest
from mika.runtime.tools import ToolContext
from mika.sim.clock import run_virtual
from mika.sim.outside import FakeMail
from mika.vocab.episodes import Kind
from tests.fixtures.mika import at_paris, boot, build, connect

PERSO = AccountInfo("perso", "Perso", "mika@exemple.fr", display_name="Adrien", ready=True, can_send=True)
START = at_paris(2026, 10, 28, 10, 0)
ALICE = "Alice <alice@exemple.fr>"
_CALLS = itertools.count(1)


def mail(n: int, subject: str, sender: str, at: int, **kw) -> Mail:
    return Mail(f"<m{n}@exemple.fr>", sender, sender.split("<")[-1].rstrip(">"), subject, at, "Bonjour.",
                to="mika@exemple.fr", account="perso", **kw)


def ref(n: int) -> str:
    return f"perso:<m{n}@exemple.fr>"


def triage(req: LLMRequest) -> LLMResponse:
    """Le tri juge la facture importante, et qu'elle attend une réponse ; le reste, non."""
    if req.role == "triage":
        urgent = "Facture" in str(req.messages[0].content)
        return LLMResponse(json.dumps({"importance": 0.9 if urgent else 0.3, "resume": "", "reponse": urgent,
                                       "emotion": ""}))
    return LLMResponse("d'accord [EMOTION:neutral:0.3]")


async def call(kernel, tool: str, **args):
    """Un appel d'outil pendant une réponse à sa propriétaire, ses arguments validés comme la boucle les valide."""
    mind = kernel.mind
    base, n = mind.frame(), next(_CALLS)
    audience = audience_for(base, EpisodeRequest(kind=Kind.REPLY, target="user_1"))
    frame = Frame(base.root, mind.clock.now(), mind.registry, audience, EpisodeRef(f"ep-{n}", Kind.REPLY,
                                                                                    target="user_1"))
    spec = mind.registry.tools[tool]
    ctx = ToolContext(mind, spec, f"appel-{n}", f"ep-{n}", frame, guard=None, ports=kernel.ports)
    ctx.call_key = f"{tool}:{n}"
    out = await spec.handler(spec.args.model_validate(args), ctx)
    return out if isinstance(out, str) else out.content


def live(tmp_path, scenario):
    box = FakeMail(boxes=[PERSO])
    box.deliver(mail(1, "Facture de votre contrat EDF", "EDF <factures@edf.fr>", at_paris(2026, 10, 28, 9, 5),
                     attachments=(Attachment("facture.pdf", "application/pdf", 1200),)))
    box.deliver(mail(2, "Un café jeudi ?", ALICE, at_paris(2026, 10, 27, 22, 30), seen=True, answered=True))
    box.deliver(mail(3, "Compte rendu", "Bob <bob@exemple.fr>", at_paris(2026, 10, 12, 9, 14), flagged=True))
    box.deliver(mail(4, "Vieux souvenir", ALICE, at_paris(2025, 2, 3, 8, 0)))
    kernel, clock, _, _ = build(tmp_path, triage, start=START, ports={"mail": box})
    box.now = clock.now

    async def main():
        await boot(kernel)
        try:
            await connect(kernel, "user_1", "Adrien", operator=True)
            await asyncio.sleep(15 * MINUTE / US)  # relevé et tri
            return await scenario(kernel)
        finally:
            await kernel.lanes.join()
            await kernel.stop()

    return run_virtual(clock, main)


def test_a_list_says_when_what_her_triage_judged_and_how_far_it_goes(tmp_path):
    async def scenario(kernel):
        out = {"first": await call(kernel, "email_list", limit=2),
               "second": await call(kernel, "email_list", limit=2, page=2),
               "past": await call(kernel, "email_list", limit=2, page=3),
               "unread": await call(kernel, "email_list", unread_only=True)}
        out["read"] = await call(kernel, "email_read", mail=f"[{ref(1)}]")
        out["unread after"] = await call(kernel, "email_list", unread_only=True)
        return out

    out = live(tmp_path, scenario)
    first, second = out["first"].splitlines(), out["second"].splitlines()
    # la date, son tri, ce qu'il porte ; la page et la suite
    assert first[1] == (f"[{ref(1)}] aujourd'hui 9 h 05 · (non lu) de EDF <factures@edf.fr> : « Facture de votre "
                        "contrat EDF » (important) (attend une réponse) (1 pièce(s) jointe(s))")
    assert first[2] == f"[{ref(2)}] hier 22 h 30 · de Alice <alice@exemple.fr> : « Un café jeudi ? » (répondu)"
    assert first[-1] == "(page 1 sur 2, 4 mails ; la suite : page=2)"
    assert "relevé commence" not in out["first"]  # pas encore au bout
    # la dernière page : une autre année n'a que son jour ; jusqu'où remonte ce qu'elle a relevé, et qui l'étend
    assert second[1].startswith(f"[{ref(3)}] le 12/10 9 h 14 · (non lu) de Bob") and second[1].endswith("(suivi)")
    assert second[2].startswith(f"[{ref(4)}] le 03/02/2025 · ")
    assert second[3] == "(page 2 sur 2, 4 mails : la dernière)"
    assert "ce que tu as relevé commence le 03/02/2025" in second[4] and "Adrien peut le charger" in second[4]
    assert out["past"] == "Il n'y a pas de page aussi loin."
    # non lu : ni sur le serveur, ni par elle
    assert [ref(1), ref(3), ref(4)] == [r for r in (ref(n) for n in range(1, 5)) if f"[{r}]" in out["unread"]]
    assert f"[{ref(1)}]" not in out["unread after"] and f"[{ref(3)}]" in out["unread after"]
    assert "Date : aujourd'hui 9 h 05" in out["read"]


def test_a_search_finds_every_word_by_sender_too_and_says_how_far_it_goes(tmp_path):
    async def scenario(kernel):
        return {"words": await call(kernel, "email_search", query="edf facture"),
                "none": await call(kernel, "email_search", query="facture gaz"),
                "sender": await call(kernel, "email_search", sender="alice"),
                "both": await call(kernel, "email_search", query="café", sender="bob"),
                "empty": await call(kernel, "email_search"),
                "contacts": await call(kernel, "email_contacts", query="alice"),
                "nobody": await call(kernel, "email_contacts", query="zoé")}

    out = live(tmp_path, scenario)
    assert f"[{ref(1)}]" in out["words"] and "relevé commence le 03/02/2025" in out["words"]
    # rien : elle sait que ce n'est que dans ce qu'elle a relevé
    assert out["none"].startswith("Rien ne correspond.") and "relevé commence le 03/02/2025" in out["none"]
    assert [f"[{ref(n)}]" in out["sender"] for n in range(1, 5)] == [False, True, False, True]
    assert out["both"].startswith("Rien ne correspond.")
    assert out["empty"] == "Dis des mots à chercher, ou un expéditeur."
    # l'adresse de quelqu'un, et combien on s'est écrit
    assert "- Alice <alice@exemple.fr> : 2 reçu(s), 0 envoyé(s) ; dernier échange : hier 22 h 30" in out["contacts"]
    assert out["nobody"] == "Personne ne correspond dans ce que tu as relevé."
