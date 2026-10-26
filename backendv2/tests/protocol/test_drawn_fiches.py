"""Les fiches dessinées des objets (``app/handmade/fiches.py``, ADR 0121), à travers le vrai serveur : un but, un
réveil, une conversation et une réponse Teams, une boîte, un mail, un brouillon. Chacune s'ouvre dessinée (son
en-tête, son onglet principal), son HTML est valide, ses données y sont — et ses formulaires sont ceux que la console a
préparés : un formulaire repris du dessin s'envoie tel quel. Ses autres onglets se dessinent bloc par bloc ; un dessin
qui échoue rend la main aux blocs de la faculté."""

from __future__ import annotations

import html
import json
import re
from urllib.parse import quote

import pytest

from mika.app.handmade import fiches, goal
from mika.contracts import goals as goals_c
from mika.contracts import runtime as rt
from mika.contracts import wakeup as wakeup_c
from mika.kernel.events import Content, Origin
from mika.ports.mail import Draft as MailDraft
from mika.ports.teams import Draft as TeamsDraft
from tests.fixtures.console_html import ConsoleHTML
from tests.fixtures.courrier import mailbox
from tests.protocol.test_teams_web import DM, batch, headers, new_key
from tests.protocol.test_wakeup_web import configure, key_for, send
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée


def drawn(client, url: str) -> str:
    """Une fiche ouverte : 200, un HTML valide, le dessin (pas le repli sur les blocs), sa feuille."""
    page = client.get(url)
    assert page.status_code == 200, url
    ConsoleHTML(page.text).check()
    assert 'class="now-page' in page.text, url
    assert "Cette vue a échoué" not in page.text and "Action non déclarée" not in page.text, url
    return html.unescape(page.text)


def form_of(page: str, action: str, having: str = "") -> dict[str, list[str]]:
    """Les champs cachés du formulaire d'une action, tel que la page le montre (son jeton compris) ; ``having`` : le
    premier dont un champ caché vaut cela (le bouton « fait » d'une tâche)."""
    forms = re.findall(r'<form[^>]+action="/inspecteur/action/' + re.escape(action) + r'".*?</form>', page, re.S)
    form = next((f for f in forms if not having or f'value="{having}"' in f), None)
    assert form is not None, f"pas de formulaire {action} {having}"
    data: dict[str, list[str]] = {}
    for name, value in re.findall(r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"', form):
        data.setdefault(name, []).append(html.unescape(value))
    return data


def append(client, live, drafts, emitter: str, correlation: str = "fiches") -> list[int]:
    commit = client.portal.call(lambda: live.kernel.mind.append(drafts, emitter=emitter, correlation=correlation,
                                                                 origin=Origin.GENESIS))
    return list(commit.seqs)


def open_goal(client, live, *, kind=goals_c.EXPLORATION, title="Explorer : les jeux rétro", details="", **more) -> str:
    seqs = append(client, live, [goals_c.GOAL_OPENED.draft(
        kind=kind, authority=goals_c.SELF if kind == goals_c.EXPLORATION else goals_c.USER,
        title=Content.of(title, level=0), details=Content.of(details, level=0) if details else None,
        bundles=("goals",), max_steps=8, source="genese", sensitivity=0, desire=0.9, **more)], "goals", "genese")
    return str(seqs[-1])


# ── un but ──


def test_a_goal_opens_on_its_drawn_summary_and_its_plan_keeps_its_buttons(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    gid = open_goal(client, live, details="Retrouver les consoles des années 90 et ce qui les rendait si attachantes.")
    url = f"/inspecteur/fiche/goal/{gid}"
    empty = drawn(client, url)
    assert 'class="now-page goal"' in empty and f"But n° {gid} · exploration · à elle" in empty
    assert "<h1>Explorer : les jeux rétro</h1>" in empty
    assert "Retrouver les consoles des années 90" in empty  # ce qu'elle cherche, en grand
    assert "aucune tâche écrite" in empty and "aucune séance rapportée encore" in empty  # l'état vide
    assert "Son envie" in empty and "0 / 8" in empty.replace("<b>", "").replace("</b>", "")
    assert "/inspecteur/action/goals.tache_ajouter" in empty and "Tout le détail" in empty
    # une tâche ajoutée par le formulaire du dessin, puis cochée par le bouton de sa ligne
    data = form_of(empty, "goals.tache_ajouter")
    added = client.post("/inspecteur/action/goals.tache_ajouter", data={**data, "text": "Lister les consoles"},
                        follow_redirects=False)
    assert added.status_code == 303
    page = drawn(client, url)
    assert "Lister les consoles" in page and "posée par toi" in page and "Changer cette tâche" in page
    done = form_of(page, "goals.tache_statut", having=goals_c.TASK_DONE)
    assert client.post("/inspecteur/action/goals.tache_statut", data=done, follow_redirects=False).status_code == 303
    after = drawn(client, url + "?onglet=resume")
    assert "1 / 1" in after.replace("<b>", "").replace("</b>", "") and "tâches faites" in after


def test_a_reminder_says_what_when_and_to_whom(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    now = live.kernel.mind.clock.now()
    gid = open_goal(client, live, kind=goals_c.REMINDER, title="Rappeler d'arroser les plantes",
                    due=now + 3_600_000_000)
    page = drawn(client, f"/inspecteur/fiche/goal/{gid}")
    assert "À rappeler" in page and "Rappeler d'arroser les plantes" in page and "pas encore" in page
    assert "Plan de travail" not in page  # un rappel n'a ni plan ni séances


def test_a_paused_goal_says_so_first(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    gid = open_goal(client, live)
    page = drawn(client, f"/inspecteur/fiche/goal/{gid}")
    paused_at = client.post("/inspecteur/action/goals.pause", data=form_of(page, "goals.pause"), follow_redirects=False)
    assert paused_at.status_code == 303
    paused = drawn(client, f"/inspecteur/fiche/goal/{gid}")
    assert 'class="obj-alert warn"' in paused and "En pause depuis" in paused


@pytest.mark.parametrize("tab", [t for t in goal.TABS if t != "resume"])
def test_every_other_goal_tab_is_drawn_block_by_block(world, tab):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    gid = open_goal(client, live)
    page = drawn(client, f"/inspecteur/fiche/goal/{gid}?onglet={tab}")
    assert 'class="now-page person-tab"' in page and f"But n° {gid}" in page  # l'en-tête dessiné, sur tous ses onglets


def test_a_failing_drawing_gives_back_the_faculty_blocks(world, monkeypatch):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    gid = open_goal(client, live)

    def broken(*args, **kwargs):
        raise RuntimeError("dessin cassé")

    monkeypatch.setattr(goal.GoalFiche, "_summary", staticmethod(broken))
    page = client.get(f"/inspecteur/fiche/goal/{gid}")
    assert page.status_code == 200 and 'class="now-page goal"' not in page.text
    assert "Plan de travail" in html.unescape(page.text)  # les blocs de la faculté


# ── un réveil ──


def test_a_wakeup_shows_what_it_does_its_key_and_its_last_calls(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    configure(client, live, tools=("memory",), notify=wakeup_c.NOBODY)
    bare = drawn(client, "/inspecteur/fiche/reveil/serre")
    assert 'class="now-page wake"' in bare and "Réveil par API" in bare and "<h1>serre</h1>" in bare
    assert "l'alerte de la serre" in bare and "Résume-la." in bare  # à quoi il sert, ses consignes
    assert "Sans clé, il ne reçoit rien" in bare and "aucun appel pour l'instant" in bare  # l'état vide
    assert "/inspecteur/action/wakeup.nouvelle_cle" in bare and "/inspecteur/action/wakeup.retirer_cle" not in bare
    assert "POST /api/wake/serre" in bare and "curl -X POST" in bare
    assert "Modifier ses réglages" in bare  # ses réglages, en bouton dans l'en-tête
    key = key_for(client, live)
    assert send(client, key).status_code == 202
    page = drawn(client, "/inspecteur/fiche/reveil/serre")
    assert "Il fait 41 °C dans la serre." in page and "en attente" in page  # ce qu'il apportait, où il en est
    assert "clé définie" in page and "générée" in page
    assert "/inspecteur/action/wakeup.retirer_cle" in page and "Sans clé" not in page
    calls = drawn(client, "/inspecteur/fiche/reveil/serre?onglet=appels")
    assert 'class="now-page person-tab"' in calls and "Il fait 41 °C dans la serre." in calls


# ── Teams ──


def test_a_teams_conversation_is_a_thread_of_bubbles_with_its_ask_form(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    key = new_key(client, live)
    assert client.post("/api/teams/inbox", json=batch(), headers=headers(key)).status_code == 202
    page = drawn(client, f"/inspecteur/fiche/conversation_teams/{quote(DM, safe='')}")
    assert 'class="now-page teams-thread"' in page and "Conversation Teams · tête-à-tête" in page
    assert "On se voit à 14 h ?" in page and "Alice" in page and 'class="person-bubble"' in page
    assert "elle n'a rien préparé dans cette conversation" in page  # l'état vide
    assert "/inspecteur/action/teams.rediger" in page  # le formulaire de la console, dans le dessin


def test_a_teams_reply_shows_what_will_leave_and_its_decisions(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    key = new_key(client, live)
    assert client.post("/api/teams/inbox", json=batch(), headers=headers(key)).status_code == 202
    store = live.kernel.ports["teams"]
    [message] = client.portal.call(store.thread, DM, 10)
    draft = client.portal.call(store.save_draft, TeamsDraft(id="", conversation=DM, body="Oui, 14 h me va.",
                                                            reply_to=message.ref))
    append(client, live, [rt.EFFECT_PROPOSED.draft(
        capability="teams.send", owner="teams", summary=Content.of("Répondre à Alice dans Teams"), context="teams",
        args_json=json.dumps({"draft": draft.id, "conversation": DM, "message": message.ref, "mode": "validation"}))],
        "runtime")
    page = drawn(client, f"/inspecteur/fiche/reponse_teams/{draft.id}")
    assert 'class="now-page teams-reply"' in page and "Réponse Teams · d'elle-même" in page
    assert "On se voit à 14 h ?" in page and "Oui, 14 h me va." in page  # en face du message, ce qui partira
    assert "attend ton accord" in page and "proposée" in page  # son parcours
    for action in ("teams.envoyer", "teams.retoucher", "teams.refuser", "teams.reprendre"):
        assert f"/inspecteur/action/{action}" in page, action
    conversation = drawn(client, f"/inspecteur/fiche/conversation_teams/{quote(DM, safe='')}")
    assert "Oui, 14 h me va." in conversation and f"/inspecteur/fiche/reponse_teams/{draft.id}" in conversation


# ── le courrier ──


def with_mail(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    box = mailbox(5)
    live.kernel.ports["mail"] = box
    return client, live, box


def test_a_mailbox_shows_its_state_folders_and_how_she_writes_there(world):  # noqa: F811
    client, _, box = with_mail(world)
    page = drawn(client, "/inspecteur/fiche/compte/pro")
    assert 'class="now-page mailbox"' in page and "Boîte aux lettres" in page and "<h1>Atelier</h1>" in page
    assert "Ses dossiers" in page and "Archives" in page and "/inspecteur/courrier/reception?compte=pro" in page
    assert "Comment elle y écrit" in page and "/inspecteur/action/email.ecrire" in page
    voice = drawn(client, "/inspecteur/fiche/compte/pro?onglet=voix")
    assert 'class="now-page person-tab"' in voice and "Ce qu'elle lit avant d'écrire" in voice


def test_a_mail_reads_with_what_she_knows_beside_it(world):  # noqa: F811
    client, _, box = with_mail(world)
    page = drawn(client, "/inspecteur/fiche/mail/" + quote("pro:<projet@example.test>", safe=""))
    assert 'class="now-page mailf"' in page and "Mail reçu" in page
    assert "Maquettes du projet" in page and "<strong>Ton retour jeudi</strong>" in page and "maquettes.pdf" in page
    assert "/inspecteur/action/email.repondre" in page  # ses actions, celles de la console
    assert "Elle ne l'a pas (ou plus) remarqué" in page  # ce qu'elle en sait : rien de plus que la boîte
    assert not box.actions and not box.sent  # consulter ne range rien
    sent = drawn(client, "/inspecteur/fiche/mail/" + quote(box.outgoing[0].ref, safe=""))
    assert "Mail parti de sa boîte" in sent and "Bien reçu !" in sent
    for tab in ("fil", "remarque"):
        other = drawn(client, "/inspecteur/fiche/mail/" + quote("pro:<projet@example.test>", safe="") + "?onglet=" + tab)
        assert 'class="now-page person-tab"' in other, tab


def test_a_draft_is_an_envelope_with_its_decisions_and_its_journey(world):  # noqa: F811
    client, live, box = with_mail(world)
    draft = box.save_draft(MailDraft(id="", account="pro", to="lea@example.test", subject="Re: Maquettes",
                                     body="Merci Léa, retour jeudi.", reply_to="pro:<projet@example.test>"))
    append(client, live, [rt.EFFECT_PROPOSED.draft(
        capability="email.send", owner="email", summary=Content.of("Répondre à Léa"), context="email",
        args_json=json.dumps({"draft": draft.id, "account": "pro", "mail": "pro:<projet@example.test>"}))],
        "runtime")
    page = drawn(client, f"/inspecteur/fiche/brouillon/{draft.id}")
    assert 'class="now-page draftf"' in page and "Brouillon · d'elle-même" in page
    assert "Ce qui partira" in page and "lea@example.test" in page and "Merci Léa, retour jeudi." in page
    assert "Maquettes du projet" in page  # le mail auquel il répond, en lien
    for action in ("email.envoyer_brouillon", "email.retoucher", "email.refuser_brouillon", "email.reprendre"):
        assert f"/inspecteur/action/{action}" in page, action
    assert "D'où il vient" in page and "Ce qui lui est arrivé" in page  # à côté : son origine, son parcours
    refused = client.post("/inspecteur/action/email.refuser_brouillon",
                          data={**form_of(page, "email.refuser_brouillon"), "note": "trop sec"}, follow_redirects=False)
    assert refused.status_code == 303
    decided = drawn(client, f"/inspecteur/fiche/brouillon/{draft.id}")
    assert "Où il en est" in decided and "refusé" in decided and "email.envoyer_brouillon" not in decided


def test_every_fiche_kind_is_registered_once():
    assert set(fiches.OVERVIEWS) == {"goal", "reveil", "conversation_teams", "reponse_teams", "compte", "mail",
                                     "brouillon"}
    assert "app" not in fiches.OVERVIEWS  # la Forge garde le rendu de la console
