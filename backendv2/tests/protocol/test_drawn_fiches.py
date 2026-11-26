"""Les fiches dessinées des objets (``app/handmade/subjects/``, ADR 0121, 0218), à travers le vrai serveur : un but, un
réveil, une conversation et une réponse Teams, une boîte, un mail, un brouillon. Chacune s'ouvre dessinée (son
en-tête, son onglet principal), son HTML est valide, ses données y sont — et ses formulaires sont ceux que la console a
préparés : un formulaire repris du dessin s'envoie tel quel. Ses autres onglets se dessinent bloc par bloc ; un dessin
qui échoue rend la main aux blocs de la faculté. Ce que la vue de sa faculté montre, une fiche le lit dans la vue ; ce
qu'elle lit à côté, par les fonctions d'une faculté, est déclaré ici (``READS``)."""

from __future__ import annotations

import ast
import html
import json
import re
from pathlib import Path
from urllib.parse import quote

import pytest

import mika
from mika.app.domains.mail.console import subject as mail
from mika.app.handmade import pages
from mika.app.handmade.subjects import goal, parts
from mika.contracts import email as email_c
from mika.contracts import goals as goals_c
from mika.contracts import runtime as rt
from mika.contracts import wakeup as wakeup_c
from mika.faculties.goals import inspect as goals_inspect
from mika.kernel.events import Content, Origin
from mika.kernel.inspect import Badge, Meter
from mika.plugins.teams import WRITTEN, params_of
from mika.ports.mail import SIGNIN_NEEDED, SIGNIN_PENDING, SignIn
from mika.ports.mail import Draft as MailDraft
from mika.ports.teams import Draft as TeamsDraft
from mika.sim.outside import FakeMail
from tests.fixtures.console_html import ConsoleHTML
from tests.fixtures.courrier import framed, mailbox
from tests.protocol.test_moi_mail import journal
from tests.protocol.test_teams_accounts import BEA_DM, two_accounts
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
    forms = re.findall(r'<form[^>]+action="/admin/action/' + re.escape(action) + r'".*?</form>', page, re.S)
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


def open_goal(client, live, *, kind=goals_c.EXPLORATION, title="Explorer : les jeux rétro", details="", max_steps=8,
              **more) -> str:
    seqs = append(client, live, [goals_c.GOAL_OPENED.draft(
        kind=kind, authority=goals_c.SELF if kind == goals_c.EXPLORATION else goals_c.USER,
        title=Content.of(title, level=0), details=Content.of(details, level=0) if details else None,
        bundles=("goals",), max_steps=max_steps, source="genese", sensitivity=0, desire=0.9, **more)],
        "goals", "genese")
    return str(seqs[-1])


# ── un but ──


def test_a_goal_opens_on_its_drawn_summary_and_its_plan_keeps_its_buttons(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    gid = open_goal(client, live, details="Retrouver les consoles des années 90 et ce qui les rendait si attachantes.")
    url = f"/admin/fiche/goal/{gid}"
    empty = drawn(client, url)
    assert 'class="now-page goal"' in empty and f"But n° {gid} · exploration · à elle" in empty
    assert "<h1>Explorer : les jeux rétro</h1>" in empty
    assert "Retrouver les consoles des années 90" in empty  # ce qu'elle cherche, en grand
    assert "aucune tâche écrite" in empty and "aucune séance rapportée encore" in empty  # l'état vide
    assert "Son envie" in empty and "0 / 8" in empty.replace("<b>", "").replace("</b>", "")
    assert "/admin/action/goals.tache_ajouter" in empty and "Tout le détail" in empty
    # une tâche ajoutée par le formulaire du dessin, puis cochée par le bouton de sa ligne
    data = form_of(empty, "goals.tache_ajouter")
    added = client.post("/admin/action/goals.tache_ajouter", data={**data, "text": "Lister les consoles"},
                        follow_redirects=False)
    assert added.status_code == 303
    page = drawn(client, url)
    assert "Lister les consoles" in page and "posée par toi" in page and "Changer cette tâche" in page
    done = form_of(page, "goals.tache_statut", having=goals_c.TASK_DONE)
    assert client.post("/admin/action/goals.tache_statut", data=done, follow_redirects=False).status_code == 303
    after = drawn(client, url + "?onglet=resume")
    assert "1 / 1" in after.replace("<b>", "").replace("</b>", "")
    assert progress_unit(after) == "tâche faite"  # l'unité s'accorde au total : une seule tâche


def progress_unit(page: str) -> str:
    """Le texte sous le compte de l'avancement (``goal-unit``), sans ses balises."""
    found = re.search(r'<p class="goal-unit">(.*?)</p>', page, re.S)
    assert found, "pas d'avancement dessiné"
    return re.sub(r"<[^>]+>", "", found.group(1)).strip()


def test_the_progress_of_a_goal_agrees_with_its_total(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    one = drawn(client, f"/admin/fiche/goal/{open_goal(client, live, max_steps=1)}")
    assert "0 / 1" in one.replace("<b>", "").replace("</b>", "") and progress_unit(one) == "séance"
    eight = drawn(client, f"/admin/fiche/goal/{open_goal(client, live, title='Explorer : les cartes')}")
    assert progress_unit(eight) == "séances"


def test_a_reminder_says_what_when_and_to_whom(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    now = live.kernel.mind.clock.now()
    gid = open_goal(client, live, kind=goals_c.REMINDER, title="Rappeler d'arroser les plantes",
                    due=now + 3_600_000_000)
    page = drawn(client, f"/admin/fiche/goal/{gid}")
    assert "À rappeler" in page and "Rappeler d'arroser les plantes" in page and "pas encore" in page
    assert "Plan de travail" not in page  # un rappel n'a ni plan ni séances


def test_a_paused_goal_says_so_first(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    gid = open_goal(client, live)
    page = drawn(client, f"/admin/fiche/goal/{gid}")
    paused_at = client.post("/admin/action/goals.pause", data=form_of(page, "goals.pause"), follow_redirects=False)
    assert paused_at.status_code == 303
    paused = drawn(client, f"/admin/fiche/goal/{gid}")
    assert 'class="obj-alert warn"' in paused and "En pause depuis" in paused


@pytest.mark.parametrize("tab", [t for t in goal.TABS if t != "resume"])
def test_every_other_goal_tab_is_drawn_block_by_block(world, tab):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    gid = open_goal(client, live)
    page = drawn(client, f"/admin/fiche/goal/{gid}?onglet={tab}")
    assert 'class="now-page person-tab"' in page and f"But n° {gid}" in page  # l'en-tête dessiné, sur tous ses onglets


def test_a_failing_drawing_gives_back_the_faculty_blocks(world, monkeypatch):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    gid = open_goal(client, live)

    def broken(*args, **kwargs):
        raise RuntimeError("dessin cassé")

    monkeypatch.setattr(goal.GoalFiche, "_summary", staticmethod(broken))
    page = client.get(f"/admin/fiche/goal/{gid}")
    assert page.status_code == 200 and 'class="now-page goal"' not in page.text
    assert "Plan de travail" in html.unescape(page.text)  # les blocs de la faculté


def test_a_goal_fiche_says_what_its_faculty_head_says(world, monkeypatch):  # noqa: F811
    """Q05, ADR 0218 : sa sorte, son statut et son envie ne se recalculent pas à côté — la fiche les lit dans l'en-tête
    que la faculté déclare, sur son en-tête comme sur son résumé. Ce que la faculté dit autrement, la fiche le suit."""
    client, live, _ = world
    bootstrap(client)
    gid = open_goal(client, live)
    monkeypatch.setattr(goals_inspect, "_kind_fr", lambda g: "sorte de la vue")
    monkeypatch.setattr(goals_inspect, "_status", lambda g, now: Badge("statut de la vue", "danger"))
    monkeypatch.setattr(goals_inspect, "_desire", lambda g, now, frame: Meter(0.42, "42 %"))
    page = drawn(client, f"/admin/fiche/goal/{gid}")
    assert f"But n° {gid} · sorte de la vue · à elle" in page  # l'en-tête
    assert "statut de la vue" in page and "42 %" in page  # le résumé
    assert ">exploration<" not in page and "en cours" not in page


# ── un réveil ──


def test_a_wakeup_shows_what_it_does_its_key_and_its_last_calls(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    configure(client, live, tools=("memory",), notify=wakeup_c.NOBODY)
    bare = drawn(client, "/admin/fiche/reveil/serre")
    assert 'class="now-page wake"' in bare and "Réveil par API" in bare and "<h1>serre</h1>" in bare
    assert "l'alerte de la serre" in bare and "Résume-la." in bare  # à quoi il sert, ses consignes
    assert "Sans clé, il ne reçoit rien" in bare and "aucun appel pour l'instant" in bare  # l'état vide
    assert "/admin/action/wakeup.nouvelle_cle" in bare and "/admin/action/wakeup.retirer_cle" not in bare
    assert "POST /api/wake/serre" in bare and "curl -X POST" in bare
    assert "Modifier ses réglages" in bare  # ses réglages, en bouton dans l'en-tête
    key = key_for(client, live)
    assert send(client, key).status_code == 202
    page = drawn(client, "/admin/fiche/reveil/serre")
    assert "Il fait 41 °C dans la serre." in page and "en attente" in page  # ce qu'il apportait, où il en est
    assert "clé définie" in page and "générée" in page
    assert "/admin/action/wakeup.retirer_cle" in page and "Sans clé" not in page
    calls = drawn(client, "/admin/fiche/reveil/serre?onglet=appels")
    assert 'class="now-page person-tab"' in calls and "Il fait 41 °C dans la serre." in calls


# ── Teams ──


def test_a_teams_conversation_is_a_thread_of_bubbles_with_its_ask_form(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    key = new_key(client, live)
    assert client.post("/api/teams/inbox", json=batch(), headers=headers(key)).status_code == 202
    page = drawn(client, f"/admin/fiche/conversation_teams/{quote(DM, safe='')}")
    assert 'class="now-page teams-thread"' in page and "Conversation Teams · tête-à-tête" in page
    assert "On se voit à 14 h ?" in page and "Alice" in page and 'class="person-bubble"' in page
    assert "elle n'a rien préparé dans cette conversation" in page  # l'état vide
    assert "/admin/action/teams.rediger" in page  # le formulaire de la console, dans le dessin
    assert "/admin/action/teams.ecrire" in page  # écrire soi-même, sur sa carte


def card(page: str, heading: str) -> str:
    """Une carte de la fiche, par l'identifiant de son titre."""
    return page.split(f'aria-labelledby="{heading}"', 1)[1].split("</section>", 1)[0]


def test_a_teams_conversation_offers_to_write_there_and_says_under_which_name(world):  # noqa: F811
    """C4-05, décision C4-Q1 (ADR 0231) : la console écrit dans toute conversation Teams, comme la personne du compte
    depuis son espace — une note dit sous quel nom il part (« ton nom » pour un compte à toi, le nom de la personne
    sinon), la confirmation le redit ; le message entre dans la file de l'extension de ce compte, `teams.written` est
    journalisé, le geste audité. Teams coupé ou le compte décoché, la fiche ne l'offre pas et dit pourquoi."""
    client, live, _ = world
    bootstrap(client)
    two_accounts(client, live)
    mine, hers = new_key(client, live), new_key(client, live, "bea_t")
    assert client.post("/api/teams/inbox", json=batch(), headers=headers(mine)).status_code == 202
    assert client.post("/api/teams/inbox", json=batch(conv=BEA_DM, text="Tu viens ?"),
                       headers=headers(hers)).status_code == 202
    yours = card(drawn(client, f"/admin/fiche/conversation_teams/{quote(DM, safe='')}"), "teams-write")
    assert "Il part sous ton nom" in yours and "ce compte Teams est à toi" in yours
    assert "/admin/action/teams.ecrire" in yours and "Lui demander une réponse" not in yours
    url = f"/admin/fiche/conversation_teams/{quote('bea_t~' + BEA_DM, safe='')}"
    page = drawn(client, url)
    bea = card(page, "teams-write")
    assert "Il part sous le nom de Béa Martin" in bea and "pas sous le tien" in bea  # le garde-fou, par son nom
    assert ('data-confirm="L\'envoyer dans Teams maintenant, sous le nom de la personne de ce compte, sans sa '
            'signature ?"') in bea
    store = live.kernel.ports["teams"]
    [received] = client.portal.call(store.thread, "bea_t", BEA_DM, 10)
    data = form_of(page, "teams.ecrire")
    assert data["conversation"] == [f"bea_t~{BEA_DM}"] and data["reply_to"] == [received.ref]
    sent = client.post("/admin/action/teams.ecrire", data={**data, "body": "J'arrive dans dix minutes."},
                       follow_redirects=False)
    assert sent.status_code == 303
    [item] = client.get("/api/teams/outbox", headers=headers(hers)).json()["items"]
    assert item["mode"] == "send" and item["text"] == "J'arrive dans dix minutes."  # sans sa signature
    assert client.get("/api/teams/outbox", headers=headers(mine)).json()["items"] == []  # par son compte seulement
    assert client.portal.call(store.draft, item["id"]).author == "user_1"  # qui l'a écrit
    [written] = journal(live, WRITTEN)
    assert (written.data.account, written.data.conversation) == ("bea_t", BEA_DM)
    assert [(e.data.action, e.data.by) for e in journal(live, rt.OPERATED)
            if e.data.action.endswith("teams.ecrire")] == [("teams.ecrire", "user_1")]  # audité, depuis la console
    # le compte décoché : rien n'en part, la fiche ne l'offre plus et dit pourquoi
    off = params_of(live.kernel.mind.frame()).model_copy(update={"accounts_off": ("bea_t",)})
    client.portal.call(live.kernel.set_params, "teams", off)
    unchecked = card(drawn(client, url), "teams-write")
    assert "/admin/action/teams.ecrire" not in unchecked
    assert "Ce compte Teams est décoché : rien n'en part." in unchecked


def test_a_teams_reply_shows_what_will_leave_and_its_decisions(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    key = new_key(client, live)
    assert client.post("/api/teams/inbox", json=batch(), headers=headers(key)).status_code == 202
    store = live.kernel.ports["teams"]
    [message] = client.portal.call(store.thread, "principal", DM, 10)
    draft = client.portal.call(store.save_draft, TeamsDraft(id="", conversation=DM, body="Oui, 14 h me va.",
                                                            reply_to=message.ref))
    append(client, live, [rt.EFFECT_PROPOSED.draft(
        capability="teams.send", owner="teams", summary=Content.of("Répondre à Alice dans Teams"), context="teams",
        args_json=json.dumps({"draft": draft.id, "conversation": DM, "message": message.ref, "mode": "validation"}))],
        "runtime")
    page = drawn(client, f"/admin/fiche/reponse_teams/{draft.id}")
    assert 'class="now-page teams-reply"' in page and "Réponse Teams · d'elle-même" in page
    assert "On se voit à 14 h ?" in page and "Oui, 14 h me va." in page  # en face du message, ce qui partira
    assert "attend ton accord" in page and "proposée" in page  # son parcours
    for action in ("teams.envoyer", "teams.retoucher", "teams.refuser", "teams.reprendre"):
        assert f"/admin/action/{action}" in page, action
    conversation = drawn(client, f"/admin/fiche/conversation_teams/{quote(DM, safe='')}")
    assert "Oui, 14 h me va." in conversation and f"/admin/fiche/reponse_teams/{draft.id}" in conversation


# ── le courrier ──


def with_mail(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    box = mailbox(5)
    live.kernel.ports["mail"] = box
    return client, live, box


def test_a_mailbox_shows_its_state_folders_and_how_she_writes_there(world):  # noqa: F811
    client, _, box = with_mail(world)
    page = drawn(client, "/admin/fiche/compte/pro")
    assert 'class="now-page mailbox"' in page and "Boîte aux lettres" in page and "<h1>Atelier</h1>" in page
    assert "Ses dossiers" in page and "Archives" in page and "/admin/courrier/reception?compte=pro" in page
    assert "Comment elle y écrit" in page and "/admin/action/email.ecrire" in page
    voice = drawn(client, "/admin/fiche/compte/pro?onglet=voix")
    assert 'class="now-page mailvoice"' in voice and "Ce qu'elle lit avant d'écrire" in voice
    assert "Comment elle y écrit" in voice and "en assistante" in voice and "à ta place" in voice  # les trois voix
    assert "<atelier@example.test>" in voice  # l'expéditeur tel qu'il partira
    assert "pas de signature" in voice and "/admin/reglages/canaux?canal=courrier%3Apro" in voice


def test_a_microsoft_mailbox_says_how_to_connect_it(world, monkeypatch):  # noqa: F811
    client, _, box = with_mail(world)
    assert "/admin/action/email.microsoft" not in drawn(client, "/admin/fiche/compte/pro")  # un mot de passe
    monkeypatch.setattr(FakeMail, "signin", lambda self, key: SignIn(
        SIGNIN_PENDING, code="ABCD-EFGH", url="https://microsoft.com/devicelogin", until=1_793_000_000_000_000))
    page = drawn(client, "/admin/fiche/compte/pro")
    assert "/admin/action/email.microsoft" in page and "Se connecter à Microsoft" in page
    assert "https://microsoft.com/devicelogin" in page and "ABCD-EFGH" in page  # le code à entrer, sur la fiche
    monkeypatch.setattr(FakeMail, "signin", lambda self, key: SignIn(SIGNIN_NEEDED, error="Microsoft ne renouvelle "
                                                                                         "plus sa connexion"))
    assert "n'est pas connectée : Microsoft ne renouvelle plus sa connexion" in drawn(
        client, "/admin/fiche/compte/pro")


def test_a_mail_reads_with_what_she_knows_beside_it(world):  # noqa: F811
    client, _, box = with_mail(world)
    page = drawn(client, "/admin/fiche/mail/" + quote("pro:<projet@example.test>", safe=""))
    assert 'class="now-page mailf"' in page and "Mail reçu" in page
    assert "Maquettes du projet" in page and "maquettes.pdf" in page
    assert "<strong>Ton retour jeudi</strong>" in framed(client, page)  # dans son cadre (ADR 0169)
    assert "/admin/action/email.repondre" in page  # ses actions, celles de la console
    assert "Elle ne l'a pas (ou plus) remarqué" in page  # ce qu'elle en sait : rien de plus que la boîte
    assert not box.actions and not box.sent  # consulter ne range rien
    sent = drawn(client, "/admin/fiche/mail/" + quote(box.outgoing[0].ref, safe=""))
    assert "Mail parti de sa boîte" in sent and "Bien reçu !" in sent
    base = "/admin/fiche/mail/" + quote("pro:<projet@example.test>", safe="")
    thread = drawn(client, base + "?onglet=fil")
    assert 'class="now-page mailthread"' in thread and "La conversation" in thread
    assert '<li class=" here">' in thread and "ce mail" in thread  # reçu : à gauche, en évidence
    known = drawn(client, base + "?onglet=remarque")
    assert 'class="now-page mailknown"' in known and "Elle ne l'a pas (ou plus) remarqué" in known  # l'état vide
    gone = drawn(client, "/admin/fiche/mail/" + quote(box.outgoing[0].ref, safe="") + "?onglet=fil")
    assert '<li class="mine here">' in gone and "↗ parti" in gone  # parti de sa boîte : à droite


def test_what_she_knows_of_a_mail_says_each_fact_once_and_its_shares_in_percent(world):  # noqa: F811
    """Un mail que son tri a remarqué, important, qui attend une réponse : l'en-tête de la fiche dit son état et la
    réponse attendue, la carte de côté et « Ce qu'elle en sait » ne les redisent pas ; sa pertinence et ce que son
    attention en a gardé, des parts, se disent en % (audit du 2026-11-05, C4-04) ; qui l'a jugé, son tri ou le repli,
    une ligne (ADR 0240) — et, avant, qu'il attend son tri."""
    client, live, box = with_mail(world)
    base = "/admin/fiche/mail/" + quote("pro:<projet@example.test>", safe="")
    box.offered.add("pro:<projet@example.test>")  # relevé, pas encore accusé
    assert "Son tri ne l'a pas encore lu" in drawn(client, base + "?onglet=remarque")
    box.offered.clear()
    append(client, live, [email_c.NOTICED.draft(
        source="email", kind=email_c.MAIL, summary=Content.of("Léa attend ton retour sur les maquettes."),
        pertinence=0.9, bundle="email", mail="pro:<projet@example.test>", sender="Léa Martin <lea@example.test>",
        address="lea@example.test", importance=0.85, needs_reply=True, account="pro", folder="INBOX",
        triage=email_c.TRIAGE_MODEL)], "email")
    page, known = drawn(client, base), drawn(client, base + "?onglet=remarque")
    assert "lu par le modèle" in known
    for shown in (page, known):
        assert shown.count("important, non lu") == 1, shown  # l'en-tête, pas une ligne « état »
        assert shown.casefold().count("réponse attendue") == 1  # l'en-tête, ni une ligne ni une tuile
    assert "Léa attend ton retour sur les maquettes." in page  # la carte de côté, toujours là
    tiles = re.search(r'<ul class="person-tiles-list".*?</ul>', known, re.S).group()
    assert "Pertinence estimée" in tiles and "85\u202f%" in tiles and "Important" in tiles
    said = re.findall(r'<span class="num">([^<]*)</span>', tiles)  # ce que dit chaque jauge, à côté de sa barre
    assert said and all(n.endswith(" %") for n in said), said  # ni « 0.85 », ni « 1.00 »


def test_a_draft_is_an_envelope_with_its_decisions_and_its_journey(world):  # noqa: F811
    client, live, box = with_mail(world)
    draft = box.save_draft(MailDraft(id="", account="pro", to="lea@example.test", subject="Re: Maquettes",
                                     body="Merci Léa, retour jeudi.", reply_to="pro:<projet@example.test>"))
    append(client, live, [rt.EFFECT_PROPOSED.draft(
        capability="email.send", owner="email", summary=Content.of("Répondre à Léa"), context="email",
        args_json=json.dumps({"draft": draft.id, "account": "pro", "mail": "pro:<projet@example.test>"}))],
        "runtime")
    page = drawn(client, f"/admin/fiche/brouillon/{draft.id}")
    assert 'class="now-page draftf"' in page and "Brouillon · d'elle-même" in page
    assert "Ce qui partira" in page and "lea@example.test" in page and "Merci Léa, retour jeudi." in page
    assert "Maquettes du projet" in page  # le mail auquel il répond, en lien
    for action in ("email.envoyer_brouillon", "email.retoucher", "email.refuser_brouillon", "email.reprendre"):
        assert f"/admin/action/{action}" in page, action
    assert "D'où il vient" in page and "Ce qui lui est arrivé" in page  # à côté : son origine, son parcours
    why = drawn(client, f"/admin/fiche/brouillon/{draft.id}?onglet=pourquoi")
    assert 'class="now-page draftwhy"' in why and "Le mail auquel il répond" in why
    assert "Maquettes du projet" in why and "de Léa Martin <lea@example.test>" in why  # le mail, lu dans la boîte
    assert "Voici les maquettes." in why and "Elle l'a préparé d'elle-même" in why
    history = drawn(client, f"/admin/fiche/brouillon/{draft.id}?onglet=historique")
    assert 'class="now-page drafthist"' in history and "Ce qui lui est arrivé" in history and "Proposé" in history
    assert "Sa version" not in history  # jamais retouché : une seule version
    refused = client.post("/admin/action/email.refuser_brouillon",
                          data={**form_of(page, "email.refuser_brouillon"), "note": "trop sec"}, follow_redirects=False)
    assert refused.status_code == 303
    decided = drawn(client, f"/admin/fiche/brouillon/{draft.id}")
    assert "Où il en est" in decided and "refusé" in decided and "email.envoyer_brouillon" not in decided
    assert "Refusé" in drawn(client, f"/admin/fiche/brouillon/{draft.id}?onglet=historique")


def propose(client, live, draft_id: str, **more) -> None:
    append(client, live, [rt.EFFECT_PROPOSED.draft(
        capability="email.send", owner="email", summary=Content.of("Répondre à Léa"), context="email",
        args_json=json.dumps({"draft": draft_id, "account": "pro", **more}))], "runtime")


def test_a_retouched_draft_shows_both_versions_and_a_vanished_one_keeps_its_fiche(world):  # noqa: F811
    client, live, box = with_mail(world)
    draft = box.save_draft(MailDraft(id="", account="pro", to="lea@example.test", subject="Re: Maquettes",
                                     body="Merci Léa, je regarde les deux pistes.", reply_to="pro:<projet@example.test>",
                                     edited_by="user_1", original_body="Merci !"))
    propose(client, live, draft.id, mail="pro:<projet@example.test>")
    history = drawn(client, f"/admin/fiche/brouillon/{draft.id}?onglet=historique")
    assert "Sa version" in history and "Merci !" in history and "Merci Léa, je regarde les deux pistes." in history
    # qui l'a retouché, par son nom, jamais sa clé (audit du 2026-11-05, C4-R4) ; la carte de côté de la fiche aussi
    assert "Retouché" in history and "par user_1" not in history
    assert "par user_1" not in drawn(client, f"/admin/fiche/brouillon/{draft.id}")
    propose(client, live, "parti-de-la-boite")
    vanished = drawn(client, "/admin/fiche/brouillon/parti-de-la-boite")
    assert 'class="now-page draftf"' in vanished and "n'est plus dans la boîte" in vanished
    assert "attend ton accord" in vanished and "il ne partira pas" in vanished  # où il en est, sans texte
    assert "email.envoyer_brouillon" not in vanished
    assert 'class="now-page draftwhy"' in drawn(client, "/admin/fiche/brouillon/parti-de-la-boite?onglet=pourquoi")
    # il attend encore ton accord : sa fiche le refuse (C4-02), comme la file À valider ; la liste le nomme comme elle
    assert "Ce que tu peux en faire" in vanished and "/admin/action/email.refuser_brouillon" in vanished
    assert "Il attend encore ton accord" in vanished and "Il attendait" not in vanished
    assert "Un brouillon disparu" in drawn(client, "/admin/courrier/brouillons")
    refused = client.post("/admin/action/email.refuser_brouillon",
                          data={**form_of(vanished, "email.refuser_brouillon"), "note": "disparu de la boîte"},
                          follow_redirects=False)
    assert refused.status_code == 303
    decided = drawn(client, "/admin/fiche/brouillon/parti-de-la-boite")
    assert "Où il en est" in decided and "refusé" in decided and "email.refuser_brouillon" not in decided
    assert "Il attend encore" not in decided
    told = drawn(client, "/admin/fiche/brouillon/parti-de-la-boite?onglet=historique")
    assert "« disparu de la boîte »" in told and "par user_1" not in told  # qui l'a refusé : un nom, pas sa clé


def test_drafts_and_contacts_are_drawn_in_the_mail_space(world):  # noqa: F811
    client, live, box = with_mail(world)
    draft = box.save_draft(MailDraft(id="", account="pro", to="lea@example.test", subject="Re: Maquettes",
                                     body="Merci Léa, retour jeudi.", reply_to="pro:<projet@example.test>"))
    propose(client, live, draft.id, mail="pro:<projet@example.test>")
    drafts = drawn(client, "/admin/courrier/brouillons")
    assert 'mail-drafts-page' in drafts and 'class="hm-workspace mail-views"' in drafts  # l'espace du courrier
    assert "À décider" in drafts and "Re: Maquettes" in drafts and "Relire le brouillon" in drafts
    assert f'href="/admin/fiche/brouillon/{draft.id}"' in drafts and "Maquettes du projet" in drafts
    assert "Déjà décidés" in drafts and "aucun encore" in drafts.lower()
    # la page porte le nom de sa ligne dans la colonne (C4-11) ; l'intro suffit, sans bandeau qui la répète (C4-15)
    assert "<h1>Ses brouillons</h1>" in drafts and "Rien ne part sans toi" not in drafts
    # Envoyés ne redit pas ce que la colonne compte déjà, « Ses brouillons 1 », en lien (C4-R2)
    sent = html.unescape(client.get("/admin/courrier/envoyes").text)
    assert "Envoyés" in sent and "attend(ent)" not in sent and "brouillon(s)" not in sent
    # ses contacts sont dans l'annuaire, avec ceux de Teams et du téléphone (ADR 0298) : l'ancienne adresse y mène
    moved = client.get("/admin/courrier/contacts", follow_redirects=False)
    assert moved.status_code == 301 and moved.headers["location"].endswith("/admin/personnes/personnes")


def test_every_fiche_kind_is_registered_once():
    assert set(pages.OVERVIEWS) == {"serveur", "handle", "project", "goal", "reveil", "conversation_teams",
                                       "reponse_teams", "compte", "mail", "brouillon", "contact", "agenda"}
    assert "app" not in pages.OVERVIEWS  # la Forge garde le rendu de la console
    assert "person" not in pages.OVERVIEWS  # la fiche d'une personne a son paquet (``person/``)


# ── où elles vivent, ce qu'elles lisent ──

APP = Path(mika.__file__).parent / "app"
HANDMADE = APP / "handmade"
#: où vivent les fiches : celles du cadre (``subjects/``), celle d'un projet et ses onglets, dans le dossier de
#: leur domaine (ADR 0310)
FICHES = (HANDMADE / "subjects", APP / "domains" / "projects" / "console")
#: … et celles des autres domaines, chacune dans la console de son dossier (``<nom>/console/subject.py``)
DOMAIN_FICHES = tuple(sorted((APP / "domains").glob("*/console/subject.py")))

#: Ce qu'une fiche lit par les fonctions d'une faculté, à côté de sa vue (ADR 0218, décision Q05 de l'audit du
#: 2026-11-05) : par module de ``subjects/``, de la console des projets (``FICHES``) et par fiche d'un autre domaine
#: (``DOMAIN_FICHES``), chaque nom importé d'une
#: faculté hors de son ``inspect`` (ses mots et ses règles restent permis), et sa raison. Ce que sa vue montre déjà se lit dans ses blocs ou son en-tête : un nom
#: qui n'est pas ici fait échouer ``test_a_fiche_reads_beside_its_view_only_what_it_declares``.
READS: dict[str, dict[str, str]] = {
    "handmade/subjects/goal.py": {
        "Goal": "le type du but lu",
        "goal_at": "le but lui-même, dans sa tranche",
        "budget": "le budget de séances, que sa vue ne dit qu'en phrase (« 2 / 8 séances ») : la fiche en dessine "
                  "la barre",
        "params": "les seuils de ses garde-fous, que sa vue ne dit qu'en phrase : la fiche en dessine les barres",
    },
    "handmade/subjects/handle.py": {
        "view_of": "son verdict, par la fonction même de sa vue, que la fiche range en tuiles : son onglet « Verdict » "
                   "le dit en blocs — à reprendre sur eux",
        "known_as": "le nom de la personne derrière lui",
        "handles_of": "ses autres moyens de communication, que son onglet « Autres » liste — à reprendre sur lui",
    },
    "domains/projects/console/subject.py": {
        "project_at": "le projet lui-même, dans sa tranche",
        "glance": "ce qu'un projet montre d'un coup d'œil (ADR 0297) : ses objectifs et leurs jalons en barres, ses "
                  "pull requests ouvertes, ses tickets par étape, ses dépendances — la source que lit aussi l'API "
                  "par personne, pour que les deux écrans disent la même chose",
        "access_of": "ses lignes d'accès, qu'un formulaire édite et que sa vue ne porte pas",
        "who_named": "le nom de qui une ligne d'accès nomme",
        "docs": "les pages de sa documentation, pour rendre l'aperçu de l'éditeur avec ses liens (ADR 0297)",
    },
    # Objectifs, Tickets et Listes sont calqués sur l'écran Projets (ADR 0297) : des listes serrées, un détail en
    # volets, un diagramme — des formes que les blocs de leur vue ne portent pas. Ils lisent la tranche du projet par
    # les fonctions mêmes que lit l'API par personne (une seule source), et la vue de la faculté garde ses blocs
    "domains/projects/console/zones.py": {
        "project_at": "le projet lui-même, dans sa tranche",
        "glance": "où en est un jalon, en un mot : la couleur de son segment",
        "pulls": "le titre d'une pull request et son adresse chez l'hôte, composés par le moteur",
        "pull_key": "ce qui nomme une pull request dans l'adresse de Code (son numéro, ou son objectif)",
    },
    "domains/projects/console/goals.py": {
        "glance": "où en est un jalon (``milestone_state``) et la cadence d'une mission en mots",
        "milestones_of": "ses jalons qui comptent (sans les retirés)",
        "awaiting": "le point d'arrêt qu'elle a dit prêt et qui attend d'être tranché",
        "objective_at": "l'objectif que l'adresse choisit",
        "by_pulls": "si le projet passe par des pull requests",
        "objective_tickets": "ses tickets liés, que l'état garde : celui dont il est né, ceux qu'il tient",
        "milestones": "la commande d'un jalon, telle qu'elle est gardée (``decoded``)",
        "tracker": "le statut d'un ticket lié et d'un élément attendu, en mots",
        "trigger_words": "ce qui déclenche une mission, en mots",
    },
    "domains/projects/console/diagram.py": {
        "diagram": "le diagramme des objectifs (ADR 0297) : ses lignes et leurs vraies dates, la source que lit "
                   "aussi ``GET …/diagramme`` de l'API par personne",
        "objective_at": "l'objectif que l'adresse choisit",
        "milestone_at": "le jalon que l'adresse choisit",
    },
    "domains/projects/console/tickets.py": {
        "tracker": "son registre dans sa projection : une page d'une liste, un élément, son fil, son histoire "
                   "rejouée du journal (``passages``)",
        "tickets": "le parcours d'un ticket en six étapes et à qui est la main",
        "issues": "la page d'une issue chez l'hôte, et si un ticket peut encore se publier",
        "objective_at": "l'objectif qui tient un ticket",
        "by_pulls": "si le projet passe par des pull requests",
        "reflected": "si le projet reflète ses tickets en issues",
        "issue_move": "si la publication d'un ticket est déjà demandée",
        "shown_author": "qui a écrit, tel que la console le dit (les mots de la vue de son registre)",
        "shown_changer": "qui a fait un changement, tel que la console le dit",
        "shown_actor": "à qui est un élément, tel que la console le dit",
        "shown_hand": "à qui est la main sur un ticket, tel que la console le dit",
    },
    # Code est calqué sur l'écran Projets (ADR 0297) : ses sous-vues lisent les blocs de la vue « git »
    # (``inspect_code``) ; ce que le journal sait d'une pull request, par les règles que lit aussi l'API par personne
    "domains/projects/console/code.py": {
        "inspect_code": "les mots et les titres des blocs de la vue « git », et ses pull requests (``pulled``)",
        "diff_rows": "un diff de la vue relu ligne à ligne, ses numéros avant et après",
        "pull_order": "ses pull requests dans l'ordre de l'écran (les prêtes d'abord)",
        "pull_named": "la pull request que l'adresse nomme",
        "pull_stage": "où en est une pull request : proposée, ouverte, prête, fusionnée, fermée",
        "merge": "ce qui retient une fusion (``blocked``) et si elle est demandée (``merging``) : la règle même de "
                 "l'action ``projects.fusionner``",
        "writable": "si l'on peut écrire sur une pull request (la modifier, y répondre)",
        "objective_on": "l'objectif d'une branche de travail",
        "objective_at": "l'objectif lié à un commit ou à un ticket",
        "ticket_held": "le ticket que tient un objectif",
        "issue_ticket": "le ticket que reflète une issue",
        "status_words": "l'étape d'un ticket lié, en mots",
        "repo_page": "son dépôt distant en mots quand la vue ne le donne pas : sa page chez l'hôte, la règle unique",
    },
    # Documentation, Activité et Dépendances (ADR 0297) : l'espace de documentation, le journal et les liens, lus par
    # les fonctions mêmes de la faculté que lit l'API par personne
    "domains/projects/console/docs.py": {
        "docs": "ses pages (l'arbre, une page, ses versions, la recherche) et ses images, lues dans leur projection",
        "objective_at": "l'objectif pendant lequel une décision a été prise",
        "who_wrote": "qui a écrit une version et par où, en mots de console",
    },
    "domains/projects/console/activity.py": {
        "feed": "ce que chaque événement du journal donne au fil, et les pas d'une exécution : la fonction que lit "
                "l'API par personne",
        "episode_sort": "ce qu'était une exécution (cadrage, travail, relecture) et son objectif",
        "glance": "son prochain passage et son rythme",
        "objective_at": "l'objectif qu'une ligne nomme",
        "tracker": "un ticket nommé par le fil (``tracker.entry``)",
    },
    "domains/projects/console/links.py": {
        "links": "ce qu'il lit et qui le lit, et ce que chaque lien donne (``readings``, ``readers``, ``grant``)",
        "asks": "où en est une demande, comment elle naîtrait (directe, sur accord), et celles qu'il a reçues",
        "tie_of": "le mot et la date d'un lien",
        "link_options": "les projets qu'il peut lire : ceux que propose « Ajouter une dépendance »",
        "link_knob": "la case d'un lien dans ``projects.liens``, que la page pose pour un geste",
        "direct_knob": "la case du mode direct d'un lien, idem",
        "links_seen": "l'état de « Ce qu'il lit » que la page a lu, posé avec chaque geste : l'action refuse s'il a "
                      "bougé depuis (un autre onglet)",
        "tickets": "à qui la main sur le ticket d'une demande",
        "tracker": "le ticket d'une demande chez le projet visé",
    },
    "domains/projects/console/git.py": {
        "project_at": "l'adresse du distant telle qu'elle est réglée, son hôte et son nom : sa vue ne la donne qu'en "
                      "lien, et seulement en http(s) — à reprendre sur ce lien",
        "repo_page": "la page du dépôt chez l'hôte où mène la carte du distant, et son nom : la règle unique",
    },
}


def _faculty_reads(path: Path) -> set[str]:
    """Les noms qu'un module importe d'une faculté, hors de son ``inspect`` et hors des mots (des constantes)."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.ImportFrom) or not (node.module or "").startswith("mika.faculties."):
            continue
        if (node.module or "").rsplit(".", 1)[-1] == "inspect":
            continue
        names |= {a.name for a in node.names if not a.name.isupper()}
    return names


def test_a_fiche_reads_beside_its_view_only_what_it_declares():
    """La fiche d'un but recalculait sa sorte, son statut et son envie à côté de sa vue (K11-08) : la vue n'était plus
    la source, et la prochaine séance avait déjà divergé."""
    read = {*(path for folder in FICHES for path in folder.glob("*.py")), *DOMAIN_FICHES}
    assert len(DOMAIN_FICHES) >= 6  # les fiches des domaines sont bien lues
    found = {path.relative_to(APP).as_posix(): _faculty_reads(path) for path in sorted(read)}
    assert {name: reads for name, reads in found.items() if reads} == {name: set(r) for name, r in READS.items()}


def test_every_fiche_lives_in_subjects():
    """K0-10 : les fiches des objets sont dans ``subjects/``, sous des noms anglais ; plus rien ne vit à côté des
    onglets, et ni un gabarit, ni une feuille, ni le code ne renvoient aux anciens modules (on lit ici les
    commentaires : le texte, pas l'arbre du code)."""
    gone = ("goal", "handles", "mail_fiches", "teams_fiches", "wakeup", "projects", "project_git", "servers", "fiches",
            "fiche_parts")
    assert [n for n in gone if (HANDMADE / f"{n}.py").exists()] == []
    cited_as = re.compile(r"app/handmade/(?:" + "|".join(gone) + r")\.py"
                          r"|\b(?:mail_fiches|teams_fiches|fiche_parts)\b")
    root = Path(mika.__file__).parent
    cited = [f"{path.relative_to(root)}:{at}" for path in sorted(root.rglob("*"))
             if path.suffix in (".py", ".html", ".css", ".js") and "__pycache__" not in path.parts
             for at, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1) if cited_as.search(line)]
    assert cited == []


def test_a_fiche_calls_each_helper_by_its_own_name():
    """K11-05, K11-06 : plus d'alias — un bloc se met en forme par ``blocks.shape_block``, un onglet entier par
    ``blocks.page`` ; le texte d'une cellule se lit par ``tabs.text``."""
    assert not hasattr(parts, "shaped") and not hasattr(parts, "whole")
    assert not hasattr(mail, "_text")
