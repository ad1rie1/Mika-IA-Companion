"""« Corriger » (ADR 0307), par l'API par personne : éteint sans modèle (``GET /api/moi`` → ``correct``, la route
refuse) ; avec un modèle, le texte corrigé, ses corrections et ses changements écartés, au premier plan, sans
persona ; rien à corriger, le texte tel quel ; une réponse qui touche aux mots ne remplace pas ton texte ; une réponse
incomplète (un refus du fournisseur, un plafond atteint) n'est jamais posée, même en partie."""

from __future__ import annotations

from mika.app.me.writing import NO_MODEL, REFUSED, TOO_LONG
from mika.ports.llm import LLMResponse
from mika.vocab.phrasebook import phrase
from tests.protocol.test_moi_mail import API, post
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée

TEXT = "Bonjour Albert, je te renvoi le fichier corriger demain matin."
FIXED = "Bonjour Albert, je te renvoie le fichier corrigé demain matin."


def test_correct_stays_off_without_a_model(world):  # noqa: F811
    client, _live, _ = world
    bootstrap(client)
    assert client.get(API).json()["correct"] is False
    r = post(client, "/correct", {"text": TEXT})
    assert r.status_code == 409 and r.json()["error"] == NO_MODEL


def test_correct_fixes_the_faults_and_never_the_words(world, monkeypatch):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    gateway = live.kernel.deps.gateway
    serving, call = gateway.serving, gateway.call
    asked, answers = [], iter([
        LLMResponse(FIXED), LLMResponse(TEXT),
        LLMResponse("Bien sûr Albert ! Je t'envoie tout ça demain, promis."),
        LLMResponse(FIXED[:30], stop="refusal"), LLMResponse(FIXED[:30], stop="max_tokens"),
    ])

    async def model(req):
        if req.role != "correct":
            return await call(req)
        asked.append(req)
        return next(answers)

    monkeypatch.setattr(gateway, "serving", lambda role: "fake" if role == "correct" else serving(role))
    monkeypatch.setattr(gateway, "call", model)
    assert client.get(API).json()["correct"] is True

    fixed = post(client, "/correct", {"text": TEXT})
    assert fixed.status_code == 200, fixed.text
    assert fixed.json() == {"text": FIXED, "changes": 2, "refused": 0}
    [req] = asked
    assert req.system_stable == phrase("correct.system") and req.persona is None
    assert [m.content for m in req.messages] == [TEXT]
    assert req.priority == 0 and req.lane == "conversation"  # tu attends : au premier plan
    assert post(client, "/correct", {"text": TEXT}).json() == {"text": TEXT, "changes": 0, "refused": 0}
    rewritten = post(client, "/correct", {"text": TEXT}).json()
    assert rewritten["text"] == TEXT and rewritten["changes"] == 0 and rewritten["refused"] >= 1
    refused = post(client, "/correct", {"text": TEXT})
    assert refused.status_code == 422 and refused.json()["error"] == REFUSED  # jamais un texte coupé
    cut = post(client, "/correct", {"text": TEXT})
    assert cut.status_code == 413 and cut.json()["error"] == TOO_LONG
    assert post(client, "/correct", {"text": "   "}).status_code == 400
