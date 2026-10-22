"""Ses autrices et leurs flux (ADR 0124), par leurs intentions.

- une installation qui n'a rien réglé a une autrice sur chaque flux (« Message » au chat, « Mail pro » à chaque boîte,
  « Pro Teams » à Teams, « SMS perso » au téléphone), chacune avec ses codes et son exemple ; enregistré, le réglage
  fait foi, mais un champ vide d'une autrice livrée reprend son défaut ;
- retirer une autrice libère ses flux ; un flux inconnu est refusé ; ses textes sont bornés ;
- au chat, ses codes s'ajoutent au cadre, son exemple prend la place du fil de référence de sa persona ;
- un chat sans autrice n'a pas de seconde passe : le premier jet part ;
- un brouillon (courriel, Teams, téléphone) se récrit dans le genre de son flux, selon ses codes, ce à quoi il répond
  cité ; le chat n'a pas cette passe-là ;
- dans Teams, la réponse préparée à la place de la personne est celle de l'autrice ; sans autrice, le premier jet.
"""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from mika.adapters.teams import TeamsConfig
from mika.app import authors as A
from mika.faculties.expression import polish, polish_draft
from mika.kernel.clock import MINUTE
from mika.ports.llm import LLMResponse, Message, PersonaRender
from mika.runtime.tools import ToolContext
from mika.vocab import flows
from mika.vocab.flows import Author
from mika.vocab.phrasebook import phrase
from tests.fixtures.mika import connect
from tests.unit.test_teams import DM, QUESTION, Model, conv, live, msg, push, sleep

WRITTEN = "Bonjour Alice, TCP garantit l'ordre et la livraison ; UDP, plus léger, ne garantit rien."


def test_an_installation_that_set_nothing_has_an_author_on_every_flow_with_every_field_filled():
    d = A.defaults(["perso", "pro"])
    assert set(d.authors) == {"message", "mail-pro", "teams-pro", "sms-perso"}
    assert d.flows == {flows.CHAT: "message", flows.mail("perso"): "mail-pro", flows.mail("pro"): "mail-pro",
                       flows.TEAMS: "teams-pro", flows.PHONE: "sms-perso"}
    assert all(spec.name and spec.codes and spec.example for spec in d.authors.values())
    assert d.author_for(flows.TEAMS).codes == phrase("expression.author.defaults.teams.codes")
    assert d.authors["message"].example == phrase("expression.author.defaults.message.example")
    # l'exemple de « Message » : le fil de référence de sa persona, s'il y en a un
    assert A.defaults(reference=" Léa : t'es où ").authors["message"].example == "Léa : t'es où"


def test_an_empty_field_of_a_shipped_author_takes_its_default_but_hers_stay_as_written():
    cfg = A.Authors.model_validate({"authors": {"message": {"name": "Message", "codes": "Court."},
                                                "mail-pro": {}, "moi": {"name": "Moi"}}, "flows": {}})
    got = A.filled(cfg)
    assert got.authors["message"].codes == "Court."
    assert got.authors["message"].example == phrase("expression.author.defaults.message.example")
    assert got.authors["mail-pro"] == A.shipped("mail-pro")
    assert got.authors["moi"] == A.AuthorSpec(name="Moi")
    # enregistré, le réglage fait foi : un flux laissé vide part en premier jet
    assert got.author_for(flows.TEAMS) is None


def test_removing_an_author_frees_her_flows_and_a_flow_must_be_known():
    kept = A.Authors.model_validate({"authors": {"message": {}}, "flows": {"chat": "message", "teams": "teams-pro"}})
    assert kept.flows == {"chat": "message"}
    with pytest.raises(ValidationError):
        A.Authors.model_validate({"authors": {"x": {}}, "flows": {"fax": "x"}})
    with pytest.raises(ValidationError):
        A.AuthorSpec(codes="x" * (A.CODES_MAX + 1))
    cfg = A.Authors.model_validate({"authors": {"pro": {"name": "  ", "codes": " Vouvoiement. "}},
                                    "flows": {flows.mail("pro"): "pro"}})
    assert cfg.author_for(flows.mail("pro")) == Author("pro", "pro", "Vouvoiement.")


def _persona(reference: str = "") -> PersonaRender:
    return PersonaRender(text="Tu es Mika.", hash="h", depth="full", name="Mika", reference=reference)


def test_on_the_chat_her_codes_join_the_frame_and_her_example_replaces_the_reference_thread():
    msgs = [Message("user", "salut")]
    plain, _m, _keep = polish("Coucou !", msgs, "salut", _persona("Léa : t'es où\nMoi : là"))
    assert "Léa : t'es où" in plain and "ses codes" not in plain
    author = Author("message", "Message", codes="Pas d'émoji.", example="Zoé : ok\nMoi : ça marche")
    system, _m, _keep = polish("Coucou !", msgs, "salut", _persona("Léa : t'es où\nMoi : là"), author)
    assert phrase("expression.polish.codes", codes="Pas d'émoji.") in system
    assert "Zoé : ok" in system and "Léa : t'es où" not in system


def test_a_draft_is_rewritten_in_the_genre_of_its_flow_and_its_codes():
    author = Author("pro", "Mail pro", codes="Vouvoiement.", example="Bonjour Madame,\n…")
    system, message = polish_draft(flows.mail("pro"), "ok pour jeudi", "Jean — Réunion\n> jeudi ?", author)
    assert phrase("expression.author.genre.courrier") in system and "Vouvoiement." in system
    assert phrase("expression.author.example", example="Bonjour Madame,\n…") in system
    assert "> jeudi ?" in message and "<brouillon>\nok pour jeudi\n</brouillon>" in message
    teams, _m = polish_draft(flows.TEAMS, "ok", "", Author("t", "Teams"))
    assert phrase("expression.author.genre.teams") in teams and "codes" not in teams
    _s, opening = polish_draft(flows.PHONE, "ok", "", Author("t", "SMS"))
    assert phrase("expression.author.opening") in opening
    assert polish_draft(flows.CHAT, "ok", "", author) is None and polish_draft(flows.TEAMS, "  ", "", author) is None


def test_a_tool_context_without_an_author_leaves_the_draft_as_it_is():
    async def rewrite(flow, text, about):
        return f"[{flow}] {text.upper()}"

    async def main():
        bare = ToolContext(None, None, "c", "e", None)  # type: ignore[arg-type]
        hooked = ToolContext(None, None, "c", "e", None, authoring=rewrite)  # type: ignore[arg-type]
        return (await flows.written(bare, flows.TEAMS, "ok"), await flows.written(hooked, flows.TEAMS, "ok"),
                await flows.written(object(), flows.TEAMS, "ok"))

    assert asyncio.run(main()) == ("ok", "[teams] OK", "ok")


class Authored(Model):
    """Le modèle de Teams, et une autrice qui récrit."""

    def __call__(self, req):
        if req.role == "polish":
            return LLMResponse(WRITTEN)
        return super().__call__(req)


def _teams_reply(tmp_path, authors):
    async def scenario(kernel, llm, desk, store, clock):
        await connect(kernel, "user_1", "Adrien", operator=True)
        await push(desk, msg(clock, 1, QUESTION), conversations=[conv(DM, kind="dm")])
        await sleep(30 * MINUTE)
        return store.outbox(clock.now()), [c for c in llm.calls if c.role == "polish"]

    return live(tmp_path, Authored(), scenario, cfg=TeamsConfig(display_name="Adrien"), polish=True, authors=authors)


def test_in_teams_the_reply_prepared_in_her_place_is_the_authors(tmp_path):
    pro = Author("teams-pro", "Pro Teams", codes="Direct et courtois.")
    [item], [call] = _teams_reply(tmp_path / "a", lambda flow: pro if flow == flows.TEAMS else None)
    assert item.text == WRITTEN
    asked = call.system_stable + call.messages[0].content
    assert "Direct et courtois." in asked and "TCP garantit l'ordre" in asked and "TCP et UDP" in asked
    [item], calls = _teams_reply(tmp_path / "b", lambda flow: None)
    assert item.text.startswith("TCP garantit") and calls == []
