"""Les buts par HTTP : ses intentions à elle, séparées de ses projets (ADR 0031).

- le menu **Buts** ne parle plus de projets : ses buts vivants et clos ;
- la fiche d'une exploration se pilote pour de vrai : chaque onglet s'ouvre, le plan
  se tient en boutons, on la met en pause, on la clôt, on la rouvre — sans jamais
  pouvoir réécrire ce qu'elle a entrepris d'elle-même.
"""

from __future__ import annotations

import html

from mika.contracts import goals as goals_c
from mika.kernel.events import Content, Origin
from tests.protocol.test_web import WS, bootstrap, world  # noqa: F401 — fixture

TABS = ("resume", "politique", "seances", "carnet", "decisions", "episodes")


def _explore(client, live) -> int:
    async def go() -> int:
        opened = await live.kernel.mind.append([goals_c.GOAL_OPENED.draft(
            kind=goals_c.EXPLORATION, authority=goals_c.SELF, title=Content.of("Explorer : les jeux rétro", level=0),
            bundles=("goals",), max_steps=8, source="genese", sensitivity=0, desire=0.9)], emitter="goals",
            correlation="genese", origin=Origin.GENESIS)
        return opened.seqs[-1]

    return client.portal.call(go)


def test_the_goals_menu_and_an_exploration_fiche_are_driven_over_http(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    with client.websocket_connect(WS) as ws:
        ws.receive_json(), ws.receive_json()
    listing = html.unescape(client.get("/inspecteur/buts").text)
    assert "Buts vivants" in listing and "Confier un projet" not in listing and "Projets en cours" not in listing
    gid = str(_explore(client, live))
    token = client.cookies.get("csrftoken")

    def act(key: str, op: str, fixed: dict[str, str] | None = None, **values: str):
        data = {"csrf": token, "_op": op, "_retour": f"/inspecteur/fiche/goal/{gid}", "_sujet": gid,
                "_champs": list(values), **values}
        if fixed:
            data |= {"_fixes": list(fixed), **fixed}
        return client.post(f"/inspecteur/action/{key}", data=data, follow_redirects=False)

    fiche = html.unescape(client.get(f"/inspecteur/fiche/goal/{gid}").text)
    assert "Explorer : les jeux rétro" in fiche and "Avancer maintenant" in fiche and "Ajouter une tâche" in fiche
    assert "Modifier le projet" not in fiche and "Déposer un fichier" not in fiche
    assert act("goals.pause", "p1").status_code == 303
    assert act("goals.tache_ajouter", "t1", text="Lister les consoles").status_code == 303
    assert act("goals.tache_statut", "s1", {"task": "1", "status": "done"}).status_code == 303
    plan = html.unescape(client.get(f"/inspecteur/fiche/goal/{gid}?onglet=resume").text)
    assert "Plan de travail (1 / 1 faites)" in plan
    for tab in TABS:
        r = client.get(f"/inspecteur/fiche/goal/{gid}?onglet={tab}")
        assert r.status_code == 200 and "a échoué" not in r.text and "Action non déclarée" not in r.text, tab
    policy = html.unescape(client.get(f"/inspecteur/fiche/goal/{gid}?onglet=politique").text)
    assert "ne se réécrit pas" in policy
    assert act("goals.clore", "x1").status_code == 303
    assert act("goals.rouvrir", "o1", extra="2", instruction="").status_code == 303
    assert "rouvert" in html.unescape(client.get(f"/inspecteur/fiche/goal/{gid}?onglet=carnet").text)
