"""Les réveils reçoivent des webhooks (ADR 0117).

- *Le texte* : ``{"text": "…"}`` comme avant, un ``context`` à côté ; le JSON d'un service tel quel, en lignes
  ``chemin: valeur`` (ses champs gardés seulement, s'il en a), l'évènement annoncé en tête, coupé à la longueur admise
  plutôt que refusé ; rien qui se lise : refusé.
- *La porte* (par le vrai serveur) : un réveil signé admet le corps signé par sa clé (``X-Hub-Signature-256``, comme
  GitHub), jamais une signature fausse ni celle d'un réveil qui ne signe pas ; un « ping » reçoit 200 sans rien
  journaliser ; un corps signé rejoué rend le même appel, quel que soit l'identifiant de sa livraison (seul le corps
  est signé) ; la clé recopiée par GitLab passe ; la copie
  chiffrée de la clé part quand le réveil ne signe plus, et la clé n'est jamais gardée en clair.
- *Ses buts* : dans un réveil qui a le lot ``goals``, elle plante un rappel pour qui le réveil rend compte (dit à
  l'heure dite) et ouvre une exploration qui ne garde que les outils du réveil ; sans personne à qui rendre compte,
  pas de rappel ; en impersonnel, pas d'exploration ; jamais sur un réveil qui a un projet.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from mika.app.wakeups import WakeEndpoint, call_text
from mika.contracts import goals as goals_c
from mika.contracts import identity as identity_c
from mika.contracts import runtime as rt
from mika.contracts import wakeup as c
from mika.kernel.clock import HOUR
from mika.plugins.wakeup import DONE
from mika.ports.llm import LLMRequest, LLMResponse, ToolCall
from mika.vocab.episodes import Kind, goal_target
from tests.fixtures.mika import at_paris
from tests.protocol.test_console_settings import html_of
from tests.protocol.test_wakeup_web import ROUTE, called, configure, key_for
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture
from tests.unit.test_wakeup import REPORT, call, live, of, script, settle, wake, wakes


def endpoint(**fields):
    return WakeEndpoint(label="le dépôt", **fields)


# ── Le texte d'un appel ───────────────────────────────────────────────────


def test_a_text_comes_as_before_and_a_context_follows_in_lines():
    ep = endpoint()
    assert call_text({"text": "  La PR 42 est fusionnée.  "}, ep) == "La PR 42 est fusionnée."
    got = call_text({"text": "La PR 42 est fusionnée.", "context": {"repo": "mika", "labels": ["cache", ""],
                                                                     "draft": False, "by": None}}, ep)
    assert got == "La PR 42 est fusionnée.\n\nrepo: mika\nlabels.0: cache\ndraft: false"
    assert call_text({"text": "x" * 4001}, ep) == ""  # l'appelant l'a écrit : trop long, refusé
    assert call_text({"text": "   "}, ep) == ""


def test_a_service_json_becomes_lines_with_its_kept_fields_and_its_event_first():
    payload = {"action": "opened", "issue": {"title": "Le cache déborde", "body": "", "number": 7},
               "commits": [{"id": "a1", "message": "réparer"}, {"id": "b2", "message": "tester"}],
               "sender": {"login": "adrien"}}
    assert call_text(payload, endpoint(), "issues").splitlines()[:4] == [
        "event: issues", "action: opened", "issue.title: Le cache déborde", "issue.number: 7"]
    kept = endpoint(fields=("issue.title", "commits.*.message", "absent.du.corps", "commits.0.id"))
    assert call_text(payload, kept) == ("issue.title: Le cache déborde\ncommits.0.message: réparer\n"
                                        "commits.1.message: tester\ncommits.0.id: a1")
    assert call_text({"commits": []}, kept) == ""  # rien de ce qu'il garde
    assert call_text({}, endpoint()) == "" and call_text(None, endpoint()) == "" and call_text(3, endpoint()) == ""


def test_a_big_service_body_is_cut_to_the_admitted_length_not_refused():
    got = call_text({"commits": [{"message": "m" * 300} for _ in range(50)]}, endpoint(max_chars=500), "push")
    assert len(got) == 500 and got.endswith("…") and got.startswith("event: push\ncommits.0.message: mmm")
    deep: dict = {}
    node = deep
    for _ in range(40):  # plus profond que ce qu'on lit : laissé, jamais une panne
        node["n"] = {}
        node = node["n"]
    node["v"] = "fond"
    assert call_text({"top": 1, **deep}, endpoint()) == "top: 1"


def test_kept_fields_are_paths_and_goals_never_go_with_a_project():
    assert endpoint(fields=(" issue.title ", "issue.title", "commits.*.message.")).fields == \
        ("issue.title", "commits.*.message")
    with pytest.raises(ValueError):
        endpoint(fields=("issue title",))
    with pytest.raises(ValueError):
        endpoint(project="3", tools=("goals",))
    assert endpoint(tools=("goals", "memory")).tools == ("goals", "memory")


# ── La porte, par le vrai serveur ─────────────────────────────────────────


def signed(key: str, body: bytes) -> str:
    return "sha256=" + hmac.new(key.encode(), body, hashlib.sha256).hexdigest()


def test_a_signed_endpoint_takes_a_github_delivery_and_nothing_false(world):  # noqa: F811
    client, live_, _ = world
    configure(client, live_, signed=True, max_pending=50, fields=("issue.title",))
    key = key_for(client, live_)
    body = json.dumps({"action": "opened", "issue": {"title": "Le cache déborde"}}).encode()
    github = {"Content-Type": "application/json", "X-GitHub-Event": "issues", "X-GitHub-Delivery": "d-1",
              "X-Hub-Signature-256": signed(key, body)}
    ok = client.post(ROUTE, content=body, headers=github)
    assert ok.status_code == 202
    again = client.post(ROUTE, content=body, headers=github)  # une livraison rejouée : le même appel
    assert again.status_code == 202 and again.json()["call"] == ok.json()["call"]
    # …même rejouée sous un autre identifiant (l'en-tête n'est pas signé : seul le corps l'est)
    replayed = client.post(ROUTE, content=body, headers={**github, "X-GitHub-Delivery": "d-9"})
    assert replayed.status_code == 202 and replayed.json()["call"] == ok.json()["call"]
    [ev] = called(client, live_)
    assert ev.data.text.text == "event: issues\nissue.title: Le cache déborde"
    # une signature fausse, ou d'un autre corps : le même 401 qu'une mauvaise clé
    forged = {**github, "X-GitHub-Delivery": "d-2", "X-Hub-Signature-256": signed(key + "x", body)}
    assert client.post(ROUTE, content=body, headers=forged).status_code == 401
    other = {**github, "X-GitHub-Delivery": "d-3"}
    assert client.post(ROUTE, content=body + b" ", headers=other).status_code == 401
    assert client.post(ROUTE, content=body, headers={**other, "X-Hub-Signature-256": b"sha256=\xe9"}).status_code == 401
    # la clé présentée passe toujours ; celle que GitLab recopie aussi
    assert client.post(ROUTE, json={"text": "à la main"}, headers={"Authorization": f"Bearer {key}"}).status_code == 202
    gitlab = client.post(ROUTE, json={"object_kind": "issue", "issue": {"title": "par GitLab"}},
                         headers={"X-Gitlab-Token": key})
    assert gitlab.status_code == 202
    # rien de ce qu'il garde : rien à lire
    assert client.post(ROUTE, json={"object_kind": "push"}, headers={"X-Gitlab-Token": key}).status_code == 400
    # un ping vérifie le webhook : 200, rien n'est journalisé
    ping = json.dumps({"zen": "Keep it logically awesome.", "hook_id": 1}).encode()
    pong = client.post(ROUTE, content=ping, headers={"X-GitHub-Event": "ping", "X-Hub-Signature-256": signed(key, ping)})
    assert pong.status_code == 200 and pong.json() == {"ok": True, "call": None}
    assert len(called(client, live_)) == 3
    # la clé n'est gardée nulle part en clair (chiffrée, pour vérifier une signature)
    rows = client.portal.call(lambda: live_.settings.store.run_mind(
        lambda sql: sql.execute("SELECT value FROM settings").fetchall()))
    assert all(key not in r[0] for r in rows)
    assert client.portal.call(live_.settings.wakeup_keys)["serre"]["sealed"]


def test_an_unsigned_endpoint_refuses_signatures_and_drops_the_sealed_key(world):  # noqa: F811
    client, live_, _ = world
    configure(client, live_, signed=True, max_pending=50)
    key = key_for(client, live_)
    configure(client, live_, signed=False, max_pending=50)  # il ne signe plus : la copie chiffrée part
    assert "sealed" not in client.portal.call(live_.settings.wakeup_keys)["serre"]
    body = json.dumps({"text": "signé"}).encode()
    assert client.post(ROUTE, content=body, headers={"X-Hub-Signature-256": signed(key, body)}).status_code == 401
    assert client.post(ROUTE, content=body, headers={"Authorization": f"Bearer {key}"}).status_code == 202
    # signé de nouveau, avec la clé d'avant : rien à vérifier tant qu'une clé neuve n'est pas générée
    configure(client, live_, signed=True, max_pending=50)
    assert client.post(ROUTE, content=body, headers={"X-Hub-Signature-256": signed(key, body)}).status_code == 401
    fiche = client.portal.call(live_.wakeups.endpoint, "serre")
    assert fiche.signed and fiche.key is not None and not fiche.key.signs
    bootstrap(client)
    page = html_of(client.get("/inspecteur/fiche/reveil/serre"))
    assert "aucune signature ne passe" in page and "Un webhook GitHub, Gitea ou Forgejo" in page
    fresh = key_for(client, live_)
    assert client.post(ROUTE, content=body, headers={"X-Hub-Signature-256": signed(fresh, body)}).status_code == 202
    assert "aucune signature ne passe" not in html_of(client.get("/inspecteur/fiche/reveil/serre"))
    # une copie qui ne s'ouvre plus (``secret.key`` changée) ne vérifie rien : jamais une signature par une clé vide
    client.portal.call(live_.settings.save_wakeup_key, "serre", "0" * 64, "mwk_xxxx", 0, "test", "illisible")
    other = json.dumps({"text": "forgé"}).encode()
    for key_ in ("", hashlib.sha256(b"").hexdigest(), fresh):  # ce qu'on ouvre quand il n'y a rien à ouvrir
        assert client.post(ROUTE, content=other, headers={"X-Hub-Signature-256": signed(key_, other)}).status_code == 401


# ── Ses buts, dans un réveil ──────────────────────────────────────────────

#: deux heures après l'appel (le lundi à 14 h)
DUE = "2026-09-28T16:00"


def planner(req: LLMRequest) -> LLMResponse:
    """Un réveil qui plante un rappel et ouvre une exploration (si on les lui offre), puis conclut."""
    names = {t.name for t in req.tools}
    if req.role in ("project", "job") and "report_wake" in names:
        if not any(m.role == "tool" for m in req.messages):
            calls = [ToolCall("g1", "goal_plan_reminder", {"when": DUE, "what": "relancer la PR 42"})]
            if "goal_plan_exploration" in names:
                calls.append(ToolCall("g2", "goal_plan_exploration", {
                    "what": "ce que la PR 42 change au cache", "details": "PR 42 : refonte du cache, à relire"}))
            return LLMResponse("", tool_calls=tuple(calls), stop="tool_use")
        return LLMResponse("", tool_calls=(ToolCall("w1", "report_wake", {"outcome": "fait", "summary": REPORT}),),
                           stop="tool_use")
    return script(req)


def tool_results(reqs):
    return {m.tool_call_id: m for r in reqs for m in r.messages if m.role == "tool"}


def test_a_wake_plants_a_reminder_for_whom_it_reports_to_and_an_exploration_with_its_tools(tmp_path):
    async def scenario(kernel, llm):
        seq = await wake(kernel, bundles=("goals", "memory"), notify=c.OWNERS)
        await settle(kernel, lambda: call(kernel, seq).status == DONE)
        opened = of(kernel, goals_c.GOAL_OPENED)
        reminder = next(e for e in opened if e.data.kind == goals_c.REMINDER)
        target = goal_target(reminder.seq)
        await settle(kernel, lambda: any(e.data.kind == Kind.INITIATIVE and e.data.subject == target
                                         for e in of(kernel, rt.EPISODE_STARTED)), limit=3 * HOUR, step=60)
        reminded = [e for e in of(kernel, rt.EPISODE_STARTED) if e.data.subject == target]
        return seq, opened, reminded, wakes(llm), kernel.mind.frame().get(identity_c.PERSON("user_1"))

    seq, opened, reminded, reqs, adrien = live(tmp_path, scenario, respond=planner)
    names = {t.name for t in reqs[0].tools}
    assert {"goal_plan_reminder", "goal_plan_exploration", "report_wake"} <= names
    assert not names & {"goal_remind", "report_step", "goal_note"}  # ceux d'une conversation, d'un pas : pas ici
    by_kind = {e.data.kind: e for e in opened}
    reminder, exploration = by_kind[goals_c.REMINDER], by_kind[goals_c.EXPLORATION]
    assert reminder.data.owner == adrien and reminder.data.authority == goals_c.USER
    assert reminder.data.source == c.subject(seq) and reminder.data.title.text == "relancer la PR 42"
    assert reminder.data.due == at_paris(2026, 9, 28, 16, 0)
    assert reminded and reminded[0].data.target == "user_1" and reminded[0].at >= reminder.data.due  # dit à l'heure
    d = exploration.data
    assert d.bundles == ("goals", "memory") and d.origin == goals_c.FROM_SIGNAL and d.source == c.subject(seq)
    assert d.title.text == "ce que la PR 42 change au cache" and d.details.text == "PR 42 : refonte du cache, à relire"
    assert d.owner == adrien and d.authority == goals_c.SELF


def test_no_reminder_without_anyone_to_report_to_and_no_exploration_when_impersonal(tmp_path):
    async def scenario(kernel, llm):
        seq = await wake(kernel, bundles=("goals",), notify=c.NOBODY, plain=True)
        await settle(kernel, lambda: call(kernel, seq).status == DONE)
        return of(kernel, goals_c.GOAL_OPENED), [r for r in llm.calls if r.role == "job"]

    opened, jobs = live(tmp_path, scenario, respond=planner)
    assert opened == []
    names = {t.name for t in jobs[0].tools}
    assert "goal_plan_reminder" in names and "goal_plan_exploration" not in names  # impersonnel : pas d'exploration
    refused = tool_results(jobs)["g1"]
    assert refused.is_error and "personne" in refused.content
