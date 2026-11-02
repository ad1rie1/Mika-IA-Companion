"""Projet › Dépôt git, dessiné (ADR 0183) : l'atelier et son dépôt distant face à face, l'écart entre eux et les
gestes qui le comblent, puis, en sous-onglets, l'histoire de chacun, ce qui n'est pas encore enregistré, les issues
et pull requests ouvertes, les échanges passés et les réglages du distant.

- Un seul bandeau : un envoi ou une récupération qui attend ton accord, sinon ce qui empêche de lire le distant, ou
  les deux histoires qui ont divergé.
- Deux cartes face à face. L'atelier : sa branche, son dernier commit, ce qui n'est pas enregistré. Le distant : son
  hôte et son nom, le bout de sa branche, ses issues et pull requests, quand il a été lu. Entre elles, l'écart (à
  pousser, à récupérer) et « Pousser », « Récupérer », « Relire » : le geste qui comble l'écart passe en avant.
- Les sous-onglets : Historique (un commit par ligne, ceux qui restent à pousser marqués ; un commit ouvert en diff
  au-dessus), Non enregistré, Sur le distant (ceux à récupérer marqués), Issues, Pull requests, Échanges, Réglages.
- Les données sont les blocs de la vue « git » de la faculté (``Got``) : elle reste la source, pour la console en
  MCP comme pour le repli ; l'adresse du distant se lit dans la tranche des projets.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from markupsafe import Markup

from mika.app.handmade.tabs import Got, Line, anchored, blank, lines, pairs, text, tiles
from mika.faculties.projects.faculty import project_at
from mika.inspector.ui import PREFIX

#: le titre de l'hôte d'un dépôt distant qu'on sait lire
HOSTS = {"github.com": "GitHub"}
#: les sous-onglets, dans l'ordre : (ancre, libellé)
PANES = (("git-historique", "Historique"), ("git-encours", "Non enregistré"), ("git-distant", "Sur le distant"),
         ("git-issues", "Issues"), ("git-pr", "Pull requests"), ("git-echanges", "Échanges"),
         ("git-reglages", "Réglages du distant"))
#: ce que la section du distant dit et que les cartes montrent déjà (le reste va aux réglages)
ON_CARDS = ("adresse", "branche", "au bout de la branche", "avec l'atelier", "issues ouvertes",
            "pull requests ouvertes", "visibilité", "lu", "relire")


def _count(words: str, what: str) -> int:
    """Un nombre dit dans l'écart (« 2 à pousser · 1 à récupérer »)."""
    m = re.search(rf"(\d+) {what}", words)
    return int(m.group(1)) if m else 0


def _commit(line: Line, mark: str) -> dict[str, Any]:
    """Un commit d'une histoire : son identifiant (son lien), son message, qui, quand, ses chiffres, son exécution,
    et s'il reste à pousser (ou à récupérer)."""
    sha = line.get("commit")
    run = line.get("exécution")
    return {"sha": text(sha), "href": (sha or {}).get("href") or line.href, "title": line.text("message"),
            "when": line.get("quand"), "author": "" if blank(line.get("auteur")) else line.text("auteur"),
            "files": line.text("fichiers"), "lines": "" if blank(line.get("lignes")) else line.text("lignes"),
            "run": run if run and run.get("t") == "link" else None,
            "seed": text(run) == "amorce", "mark": text(line.get(mark)) in ("à pousser", "à récupérer")}


def _ticket(line: Line) -> dict[str, Any]:
    n = line.get("n°")
    labels = "" if blank(line.get("étiquettes")) else line.text("étiquettes")
    return {"n": text(n), "href": (n or {}).get("href", ""), "title": line.text("titre"),
            "labels": [x.strip() for x in labels.split(",") if x.strip()], "author": line.text("auteur"),
            "comments": line.text("commentaires"), "when": line.get("mise à jour"),
            "branches": "" if blank(line.get("branches")) else line.text("branches"), "state": line.get("état")}


def _exchange(line: Line) -> dict[str, Any]:
    return {"when": line.get("quand"), "what": line.text("quoi"), "approval": line.text("accord"),
            "state": line.get("état"), "waiting": line.tone == "warn", "detail": line.rest}


def _banner(exchanges: list[dict[str, Any]], error: str, gap: dict[str, Any] | None) -> dict[str, Any] | None:
    if any(x["waiting"] for x in exchanges):
        return {"tone": "warn", "text": "Un envoi ou une récupération attend ton accord : rien ne part sans toi.",
                "button": "Le décider", "href": f"{PREFIX}/approbations/en_attente"}
    if error:
        return {"tone": "warn", "text": error, "button": "", "href": ""}
    if gap and gap.get("tone") == "danger":
        return {"tone": "danger", "text": "L'atelier et le distant ont divergé : chacun a des commits que l'autre "
                                          "n'a pas. Récupérer refusera (en ligne droite seulement), et pousser "
                                          "aussi, tant que l'un n'a pas repris l'histoire de l'autre.",
                "button": "", "href": ""}
    return None


def git_page(got: Got, key: str) -> Markup | None:
    """Projet › Dépôt git : l'atelier et le distant face à face, puis leurs histoires en sous-onglets."""
    remote = got.first("section", "Son dépôt distant")
    if remote is None:
        return None
    p = project_at(got.ui.kernel.mind.frame().state("projects"), key)
    if p is None:
        return None
    band = tiles(got.stats())
    facts = pairs(next((x for x in remote["items"] if x.get("t") == "fields"), None))
    notes = [x for x in remote["items"] if x.get("t") == "note"]
    error = next((n["text"] for n in notes if n.get("tone") == "warn"), "")
    bar = next((x for x in remote["items"] if x.get("t") == "toolbar"), None)
    settle = next((x for x in remote["items"] if x.get("t") == "disclosure"), None)
    actions = {a["key"]: a for a in (bar or {}).get("items", []) if a.get("t") == "action"}
    gap = band.get("Avec le distant")
    words = text((gap or {}).get("value"))
    ahead, behind = _count(words, "à pousser"), _count(words, "à récupérer")

    history = anchored(got.table("Historique"), "git-historique")
    distant = got.table("Sur le distant")
    issues, pulls = got.table("Issues ouvertes"), got.table("Pull requests ouvertes")
    exchanged = got.table("Échanges avec le distant")
    commits = [_commit(x, "distant") for x in lines(history)]
    exchanges = [_exchange(x) for x in lines(exchanged)]
    opened = got.first("section", "L'enregistrement ")
    pending = got.disclosure("Ce qui n'est pas encore enregistré")
    last = band.get("Le dernier") or {}
    head_sha = str(last.get("sub") or "")
    host = (urlsplit(p.remote).hostname or "").lower() if p.remote else ""
    tip = facts.get("au bout de la branche")
    local = {
        "branch": str((band.get("Enregistrements") or {}).get("sub") or ""),
        "count": text((band.get("Enregistrements") or {}).get("value")),
        "sha": head_sha, "href": next((k["href"] for k in commits if k["sha"] == head_sha), ""),
        "title": next((k["title"] for k in commits if k["sha"] == head_sha), ""), "when": last.get("value"),
        "pending": band.get("Non enregistré"),
        "none": next((n["text"] for n in got.notes() if n.get("text", "").startswith("Pas encore de dépôt")), ""),
    }
    distant_card = None
    if p.remote:
        sha, _, said = text(tip).partition(" — ")
        distant_card = {
            "host": HOSTS.get(host, host), "name": re.sub(r"\.git$", "", urlsplit(p.remote).path.strip("/")),
            "url": re.sub(r"\.git$", "", p.remote), "branch": p.branch, "read": bool(tip),
            "tip": tip, "sha": sha if tip and tip.get("t") == "link" else "", "said": said,
            "visibility": text(facts.get("visibilité")), "seen": facts.get("lu"),
            "issues": facts.get("issues ouvertes"), "pulls": facts.get("pull requests ouvertes"),
            "fresh": (facts.get("relire") or {}).get("href", ""), "last": facts.get("dernier échange"),
            "error": error, "readable": host in HOSTS,
        }
    counts = {"git-historique": local["count"] or "0",
              "git-encours": re.sub(r" fichier.*", "", text((local["pending"] or {}).get("value"))).replace(
                  "rien", "0"),
              "git-distant": str(len(lines(distant))) if distant else "",
              "git-issues": text(facts.get("issues ouvertes")), "git-pr": text(facts.get("pull requests ouvertes")),
              "git-echanges": str(len(exchanges)) if exchanged else "", "git-reglages": ""}
    shown = {"git-historique": bool(history), "git-encours": bool(history), "git-distant": distant is not None,
             "git-issues": issues is not None, "git-pr": pulls is not None, "git-echanges": exchanged is not None,
             "git-reglages": True}
    panes = [{"id": i, "label": label, "count": counts[i],
              "warn": (i == "git-encours" and (local["pending"] or {}).get("tone") == "warn")
              or (i == "git-echanges" and any(x["waiting"] for x in exchanges))}
             for i, label in PANES if shown[i]]
    return got.draw(
        "handmade/projets/git.html", banner=_banner(exchanges, error, gap), local=local, distant=distant_card,
        gap=gap, ahead=ahead, behind=behind, push=actions.get("projects.pousser"),
        pull=actions.get("projects.recuperer"), panes=panes, opened=opened, pending=pending,
        history=history, commits=commits, remote_table=distant,
        remote_commits=[_commit(x, "atelier") for x in lines(distant)],
        issues=issues, issue_items=[_ticket(x) for x in lines(issues)],
        pulls=pulls, pull_items=[_ticket(x) for x in lines(pulls)],
        exchanged=exchanged, exchanges=exchanges, settle=settle,
        settings=[(k, v) for k, v in facts.items() if k not in ON_CARDS],
        token_note=next((n["text"] for n in notes if n.get("tone") == "muted"), ""),
        remote_help=remote.get("description", ""))
