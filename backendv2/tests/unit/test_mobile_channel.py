"""L'application du téléphone est une messagerie (ADR 0062).

- ``mobile`` est une messagerie (on y lit quand on y pense) ; sans session elle ne prouverait rien (publique),
  avec, c'est un compte authentifié comme un autre ;
- un compte n'est joignable absent que par ce que dit ``identity.registered`` (une application vivante) : posé,
  retiré, ou laissé tel quel par un journal d'avant ; parler depuis le téléphone ne le rend pas joignable à vie ;
- un rappel qui échoit quand la personne n'est sur aucun écran lui est dit sur son téléphone, une messagerie
  (on le lira quand on y pensera) ; sans téléphone, il l'attend dans son fil, sur l'écran.
"""

from __future__ import annotations

import asyncio

from mika.contracts import goals as goals_c
from mika.contracts import identity as identity_c
from mika.contracts import runtime as rt
from mika.kernel.clock import HOUR, US
from mika.kernel.events import Origin
from mika.sim.clock import run_virtual
from mika.vocab import privacy
from mika.vocab.privacy import ChannelTrust
from tests.fixtures.mika import at_paris, boot, build, connect, disconnect, said
from tests.unit.test_goals import run


def test_mobile_is_a_messaging_channel_that_proves_only_through_a_session():
    assert privacy.is_messaging(privacy.MOBILE) and privacy.is_messaging("Mobile")
    assert not privacy.is_messaging(privacy.WEB)
    assert privacy.channel_trust(privacy.MOBILE) == ChannelTrust.PUBLIC  # un transport qui ne prouve rien seul
    assert privacy.channel_trust(privacy.MOBILE, authenticated=True) == ChannelTrust.AUTHENTICATED


async def _register(kernel, messaging, *, active=True) -> None:
    await kernel.mind.append([identity_c.REGISTERED.draft(handle="user_3", name="Bea", operator=False, active=active,
                                                          messaging=messaging)],
                             emitter=identity_c.OWNER, correlation="comptes", origin=Origin.EXTERNAL)


def test_reachability_of_an_account_follows_its_phone(tmp_path):
    kernel, clock, _, _ = build(tmp_path, None)

    async def main():
        await boot(kernel)
        seen = []

        def look() -> None:
            frame = kernel.mind.frame()
            view = frame.get(identity_c.IDENTITY("user_3"))
            seen.append((frame.get(identity_c.REACHABLE("user_3")), view.channel, view.push))

        await _register(kernel, None)  # un journal d'avant l'application : rien n'est dit
        look()
        await _register(kernel, privacy.MOBILE)
        look()
        # parler depuis le téléphone, puis l'écran : la joignabilité ne bouge pas avec le canal du moment
        await connect(kernel, "user_3", "Bea")
        await (await kernel.perceive(said("user_3", "coucou", channel=privacy.MOBILE))).reply
        look()
        await _register(kernel, None)  # rien dit : rien ne change
        look()
        await _register(kernel, "")  # plus d'application : plus joignable, le canal redevient l'écran
        look()
        await (await kernel.perceive(said("user_3", "et depuis le téléphone ?", channel=privacy.MOBILE))).reply
        look()  # une session ne rend pas joignable : seul ``registered`` le dit
        await _register(kernel, privacy.MOBILE, active=False)
        look()  # un compte désactivé n'est pas joignable
        await disconnect(kernel, "user_3")
        return seen

    seen = run_virtual(clock, main)
    assert seen == [
        ((), "web", False),
        (("user_3",), "mobile", True),
        (("user_3",), "mobile", True),
        (("user_3",), "mobile", True),
        ((), "web", False),
        ((), "web", False),
        ((), "web", False),
    ]


def _reminder_scenario(registered: str | None):
    async def scenario(kernel, llm):
        if registered is not None:
            await kernel.mind.append([identity_c.REGISTERED.draft(handle="user_1", name="Adrien", operator=True,
                                                                  active=True, messaging=registered)],
                                     emitter=identity_c.OWNER, correlation="comptes", origin=Origin.EXTERNAL)
        await connect(kernel, "user_1", "Adrien")
        await (await kernel.perceive(said("user_1", "rappelle-moi dans 20 minutes de rappeler Paul"))).reply
        await disconnect(kernel, "user_1")  # l'application passe en arrière-plan : personne devant l'écran
        await asyncio.sleep(HOUR / US)

    return scenario


def _reminder_said(r):
    [started] = [e for e in r.of(rt.EPISODE_STARTED) if goals_c.REMIND in e.data.reason.split(",")]
    return started, [u for u in r.of(rt.UTTERANCE) if u.at >= started.at and u.data.target == "user_1"]


def test_a_reminder_due_while_away_is_said_on_the_phone(tmp_path):
    r = run(tmp_path, _reminder_scenario(privacy.MOBILE), start=at_paris(2026, 9, 28, 15, 0))
    started, utterances = _reminder_said(r)
    assert started.data.target == "user_1"  # elle lui écrit, absente…
    assert utterances and utterances[0].data.channel == privacy.MOBILE  # …sur la messagerie : le téléphone recevra


def test_without_a_phone_the_reminder_waits_in_the_thread_on_the_screen(tmp_path):
    r = run(tmp_path, _reminder_scenario(""), start=at_paris(2026, 9, 28, 15, 0))
    started, utterances = _reminder_said(r)
    assert started.data.target == "user_1"
    assert utterances and utterances[0].data.channel != privacy.MOBILE
