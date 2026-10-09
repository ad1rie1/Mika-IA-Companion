"""Lecture de la mémoire, des pensées et reprise explicite d'un passage."""

import html
import json
import re

from mika.contracts import attention, memory
from mika.contracts import runtime as rt
from mika.kernel.events import Content
from tests.protocol.test_console_diagnostics import stop
from tests.protocol.test_console_operator import post
from tests.protocol.test_console_workflows import append, page
from tests.protocol.test_web import bootstrap, world  # noqa: F401


def test_memory_reads_keep_privacy_status_source_filters_and_no_side_effects(world):  # noqa: F811
    client, live, backend = world
    bootstrap(client)
    kernel = live.kernel
    stop(client, kernel)
    source = append(client, kernel, [rt.PERCEPTION_RECEIVED.draft(handle="user_1", channel="web", addressed=False,
                    text=Content.of("Le lancement est confidentiel."))]).seqs[0]
    remembered = append(client, kernel, [memory.REMEMBERED.draft(text=Content.of("Lancement <script>secret</script>"),
                        about=("user_1",), sensitivity=3, secret=True, sources=(source,))], "memory").seqs[0]
    before, calls = kernel.mind.head, len(backend.calls)
    url = "/inspecteur/memoire/souvenirs?person=adrien"
    body = page(client, url)
    assert 'class="collection list"' in body and "secret" in body and "actif" in body
    assert f'/inspecteur/evenement/{remembered}' in body and f'/inspecteur/evenement/{source}' in body
    assert '<script>secret</script>' not in client.get(url).text
    assert 'name="person"' in body and "adrien" in body
    table = page(client, url + "&vue_pg1=table")
    assert 'class="collection list"' not in table and "Lancement" in table
    assert "Lancement" not in page(client, url + "&q=inexistant")
    assert kernel.mind.head == before and len(backend.calls) == calls


def test_retry_is_bound_to_its_passage_and_requires_a_valid_explicit_post(world):  # noqa: F811
    client, live, backend = world
    bootstrap(client)
    kernel = live.kernel
    stop(client, kernel)
    source = append(client, kernel, [rt.PERCEPTION_RECEIVED.draft(handle="user_1", channel="web", addressed=False,
                    text=Content.of("Un message à relire."))]).seqs[0]
    append(client, kernel, [memory.EXTRACTION_DEFERRED.draft(key=source, messages=(source,), status="review",
        attempts=3, failure_code="provider_error", detail=Content.of("Détail <script>indisponible</script>"))], "memory")
    before, calls = kernel.mind.head, len(backend.calls)
    body = page(client, "/inspecteur/memoire/consolidation")
    assert 'class="collection cards"' in body and "à examiner" in body and "Détail du passage" in body
    raw = client.get("/inspecteur/memoire/consolidation").text
    assert "<script>indisponible</script>" not in raw
    form = re.search(r'<form[^>]+action="/inspecteur/action/memory.reprendre".*?</form>', raw, re.S).group()
    assert f'type="hidden" name="key" value="{source}"' in form
    assert 'data-confirm="Relire ce passage' in form
    assert '<label for=' not in form
    assert kernel.mind.head == before and len(backend.calls) == calls
    values = {k: html.unescape(v) for k, v in re.findall(r'<input[^>]+name="([^"]+)" value="([^"]*)"', form)}
    rejected = client.post("/inspecteur/action/memory.reprendre", data={**values, "csrf": "invalid"})
    assert rejected.status_code == 403 and kernel.mind.head == before
    sent = post(client, "/inspecteur/action/memory.reprendre", values)
    assert sent.status_code == 200
    kept = client.portal.call(lambda: kernel.mind.store.latest([memory.EXTRACTION_DEFERRED.name], 10))
    assert len(kept) == 2 and json.loads(kept[0].data)["status"] == "queued"
    post(client, "/inspecteur/action/memory.reprendre", values)
    assert len(client.portal.call(lambda: kernel.mind.store.latest([memory.EXTRACTION_DEFERRED.name], 10))) == 2
    assert len(backend.calls) == calls


def test_thoughts_distinguish_live_content_from_history_and_keep_cursor_return(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    stop(client, live.kernel)
    append(client, live.kernel, [attention.THOUGHT_BORN.draft(text=Content.of(text), emotion="curious",
        intensity=intensity, origin="exchange", about=("user_1",))
        for text, intensity in (("Idée encore présente", 0.8), ("Idée qui s’est dissipée", 0.001))], "attention")
    body = page(client, "/inspecteur/pensees/pensees")
    live = body.split('<details class="card"><summary><b>Historique des pensées')[0]
    assert "Idée encore présente" in live and "Idée qui s’est dissipée" not in live
    assert '<details class="card"><summary><b>Historique des pensées' in body
    assert "Idée qui s’est dissipée" in body
    older = page(client, "/inspecteur/pensees/pensees?avant=1&pile=0,90")
    assert '<details class="card" open><summary><b>Historique des pensées' in older and "Plus récents" in older
