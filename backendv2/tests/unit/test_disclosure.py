"""La divulgation graduée : une politique rédigée comme une spécification.

Ce que Mika peut dire d'autrui dépend de qui écoute (certitude d'identité,
canal, lien, chaleur, témoin). C'est une décision de produit (« elle est
humaine : un secret peut s'ébruiter, mais seulement en grande confiance »),
pas un réglage : ces cas la fixent. Puis la même politique, de bout en bout :
le fait ``DISCLOSURE`` du noyau et la garde du composeur.
"""

from __future__ import annotations

import asyncio

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mika.contracts import identity as identity_c
from mika.kernel.faculty import SectionSpec, Zone
from mika.kernel.prompt import Budget, Composer, SectionBody
from mika.ports.llm import LLMResponse
from mika.sim.clock import run_virtual
from mika.vocab import privacy
from mika.vocab.privacy import ChannelTrust, Disclosure, Sensitivity, decide, disclosable
from tests.fixtures.mika import befriend, boot, build, connect, said

A, P, C = Sensitivity.ANODYNE, Sensitivity.PERSONAL, Sensitivity.CONFIDENCE
ACC, AUTH, PUB, INT = ChannelTrust.ACCOUNT, ChannelTrust.AUTHENTICATED, ChannelTrust.PUBLIC, ChannelTrust.INTERNAL

# (certitude, canal, proximité, chaleur, témoin, attendu, pourquoi)
MATRIX = [
    (1.0, PUB, "close", 1.0, True, A, "en public, le risque est l'auditoire, pas l'erreur d'identité"),
    (0.70, PUB, "friend", 0.0, False, A, "en public, jamais plus qu'anodin"),
    (0.45, ACC, "close", 1.0, True, A, "sous la barre, on ne raconte pas l'histoire d'autrui"),
    (0.69, ACC, "friend", 0.0, False, A, "juste sous la barre"),
    (0.70, ACC, "stranger", 0.0, False, A, "à la barre sans lien : anodin"),
    (0.70, ACC, "acquaintance", 0.1, False, A, "une connaissance n'est pas un lien"),
    (0.70, ACC, "friend", 0.0, False, P, "un ami, à la barre"),
    (0.70, ACC, "stranger", 0.5, False, A, "la chaleur seule, pour une inconnue, n'ouvre rien sur autrui"),
    (0.70, ACC, "acquaintance", 0.5, False, P, "de la chaleur pour quelqu'un qu'elle connaît : un lien"),
    (0.70, ACC, "stranger", 0.0, True, P, "il était là quand ça s'est dit"),
    (0.70, ACC, "close", 1.0, False, P, "un proche à 0,70 n'a pas encore la confidence"),
    (0.85, ACC, "close", 0.0, False, C, "un proche, en privé, à haute certitude"),
    (0.85, ACC, "friend", 0.0, False, P, "un ami n'est pas un proche"),
    (0.85, ACC, "stranger", 0.0, True, P, "un simple témoin n'est pas un confident"),
    (0.85, ACC, "friend", 0.0, True, C, "une amie qui était là"),
    (1.0, AUTH, "stranger", 1.0, True, P, "même chaleureuse, une inconnue témoin n'a pas la confidence"),
    (1.0, AUTH, "stranger", 0.0, False, A, "le canal ne donne pas le lien"),
    (1.0, AUTH, "friend", 0.0, False, P, "la relation, oui"),
    (1.0, AUTH, "close", 0.0, False, C, "proche et connecté"),
    (0.0, INT, "", 0.0, False, C, "personne n'écoute : toute sa mémoire"),
]


@pytest.mark.parametrize("certainty,trust,closeness,warmth,witness,expected,why", MATRIX)
def test_policy_matrix(certainty, trust, closeness, warmth, witness, expected, why):
    assert disclosable(certainty, trust, closeness=closeness, warmth=warmth, witness=witness) is expected, why


def test_an_anecdote_can_slip_out_to_a_close_friend_at_the_bar():
    assert disclosable(0.70, ACC, closeness="close") is P
    assert Disclosure(P, P).admits("personnel")


def test_a_confidence_never_leaves_in_a_public_room():
    level = disclosable(1.0, ACC, closeness="close", warmth=1.0, witness=True, public=True)
    assert level is A
    assert not Disclosure(level, level).admits(C, witness=True)
    assert not Disclosure(level, level).admits(P)


@pytest.mark.parametrize("certainty", [0.0, 0.25, 0.45, 0.699])
def test_below_the_bar_nothing_personal(certainty):
    assert disclosable(certainty, ACC, closeness="close", warmth=1.0, witness=True) is A


def test_the_pure_policy_never_answers_nothing_only_the_edge_does():
    for trust in ChannelTrust:
        for c in (0.0, 0.7, 0.85, 1.0):
            assert disclosable(c, trust) is not Sensitivity.NONE
    assert privacy.CLOSED.closed and not privacy.CLOSED.admits(A)
    assert privacy.EVERYTHING.admits(C)


def test_decide_gives_both_facets_and_the_own_file_gate():
    d = decide(0.70, ACC, closeness="stranger")
    assert d.level is A and d.witness_level is P and d.own_file is True
    assert d.admits(P, witness=True) and not d.admits(P)
    assert decide(1.0, AUTH, public=True).own_file is False  # en public, jamais sa fiche


def test_evidence_calibration_is_an_invariant():
    assert privacy.POLICY.check() is None
    broken = privacy.TrustPolicy(evidence={**privacy.EVIDENCE, "self_declared": 0.75})
    assert broken.check() is not None


def test_unreadable_sensitivity_is_personal():
    assert Sensitivity.parse("???") is P
    assert Sensitivity.parse("anodin") is A and Sensitivity.parse("confidence") is C


@given(st.floats(0.0, 1.0), st.floats(0.0, 1.0), st.sampled_from(list(ChannelTrust)),
       st.sampled_from(["", "stranger", "acquaintance", "friend", "close"]), st.floats(0.0, 1.0), st.booleans())
def test_more_certainty_never_discloses_less(c1, c2, trust, closeness, warmth, witness):
    lo, hi = sorted((c1, c2))
    kw = {"closeness": closeness, "warmth": warmth, "witness": witness}
    assert disclosable(lo, trust, **kw) <= disclosable(hi, trust, **kw)
    assert disclosable(hi, trust, public=True, **kw) <= A or trust is INT


# ── La garde du composeur ─────────────────────────────────────────────────


def _block(key: str, level: int) -> tuple[SectionSpec, SectionBody]:
    spec = SectionSpec("test", key, Zone.VOLATILE, frozenset({"REPLY"}), lambda *a: None)
    return spec, SectionBody(f"contenu {key}", level=level)


def test_the_composer_drops_what_the_audience_may_not_hear():
    blocks = [_block("self", 0), _block("anecdote", int(A)), _block("personal", int(P)), _block("secret", int(C))]
    for audience, kept in ((Sensitivity.NONE, {"self"}), (A, {"self", "anecdote"}),
                           (P, {"self", "anecdote", "personal"}), (C, {"self", "anecdote", "personal", "secret"})):
        _, trace = Composer().compose(blocks, kind="REPLY", audience_level=int(audience), muted_tags=frozenset(),
                                      message="?", budget=Budget(max_tokens=4000))
        assert set(trace.included) == kept, audience


# ── De bout en bout : le fait DISCLOSURE ──────────────────────────────────


def test_disclosure_fact_follows_warmth_for_an_authenticated_person(tmp_path):
    """Connectée avec son compte : sa fiche est ouverte ; ce qu'on peut lui
    dire des autres suit le lien — ici, la chaleur que leurs échanges ont
    installée, pour quelqu'un qu'elle connaît déjà. La même chaleur pour une
    inconnue d'un jour n'ouvre rien sur autrui."""
    kernel, clock, _llm, _out = build(tmp_path, lambda req: LLMResponse("oui [EMOTION:love:0.9]"))

    async def main():
        await boot(kernel)
        await connect(kernel, "user_1", "Adrien")
        await connect(kernel, "user_4", "Zoé")
        await befriend(kernel, "user_1", "acquaintance")
        first = kernel.mind.frame().get(identity_c.DISCLOSURE(("user_1", "web", False)))
        for _ in range(8):
            for handle in ("user_1", "user_4"):
                p = await kernel.perceive(said(handle, "tu comptes beaucoup pour moi"))
                await p.reply
                await asyncio.sleep(60)
        later = kernel.mind.frame().get(identity_c.DISCLOSURE(("user_1", "web", False)))
        warm_stranger = kernel.mind.frame().get(identity_c.DISCLOSURE(("user_4", "web", False)))
        public = kernel.mind.frame().get(identity_c.DISCLOSURE(("user_1", "web", True)))
        stranger = kernel.mind.frame().get(identity_c.DISCLOSURE(("web_x", "web", False)))
        internal = kernel.mind.frame().get(identity_c.DISCLOSURE(("conscience_mika", "internal", False)))
        await kernel.stop()
        return first, later, warm_stranger, public, stranger, internal

    first, later, warm_stranger, public, stranger, internal = run_virtual(clock, main)
    assert first.own_file and first.level is A
    assert later.level is P  # la chaleur a ouvert le personnel
    assert warm_stranger.own_file and warm_stranger.level is A, "la chaleur seule ne fait pas d'une inconnue une confidente"
    assert public.level is A and not public.own_file
    assert stranger.level is A and not stranger.own_file
    assert internal.closed
