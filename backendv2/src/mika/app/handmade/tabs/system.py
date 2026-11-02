"""Système : ses onglets, chacun dans sa forme (ADR 0177) ; Processus, Santé et Sorties sont dessinés à part
(``handmade/system.py``), sur la même feuille (``handmade/system.css``).

Des pages d'exploitation, faites pour diagnostiquer : ce qui ne va pas d'abord, en un seul bandeau ; des chiffres ;
puis les données denses en listes serrées, lisibles en colonnes.

- Anomalies : le bandeau (des tranches corrompues, des anomalies, ou rien), la bande de chiffres, puis côte à côte ce
  qui a échoué dans ses facultés (la faculté, l'événement, l'erreur en clair) et à l'arbitre ; les traces du journal
  en fil, chacune en mots (« épisode supplanté », « oubli »…).
- Journal d'événements : un fil jour par jour, en deux colonnes sur un grand écran — l'heure, ce qui s'est passé, son
  type ; les événements d'un même épisode se suivent sans répéter leur lien ; les données de chacun repliées. Les
  familles d'événements de la page en puces, qui filtrent.
- Écrans du monde : le bandeau (ce qui manque à un hôte connecté), les chiffres, puis côte à côte les connexions
  (leurs rôles, qui tient le bail) et ce que chaque hôte a chargé (ce qui lui manque, en puces).
- Contributions : un tableau d'ensemble (une ligne par faculté, ce qu'elle apporte en nombres), puis une faculté par
  sous-onglet — ce qu'elle publie, écoute, fournit (et qui le lit), ses sections, preuves, processus, outils…
- Simulations : le gabarit « client » — les rapports à gauche, celui qu'on lit à droite.
- Moteur des modèles : le bandeau (un rôle sans fournisseur, une file d'attente), les chiffres, puis chaque
  fournisseur (ses créneaux en cases, son quota en jauges, ce qu'il a fait en 24 h) et qui sert quoi, rôle par
  fournisseur.
- Appels et coûts : le bandeau des échecs, les chiffres, le coût et les appels de quatorze jours en barres (les échecs
  en rouge) ; puis en sous-onglets où va le coût (par rôle, par modèle, par fournisseur), tous les appels, le détail
  jour par jour.
- Stockage et sauvegardes : le bandeau des sauvegardes s'il y a lieu, les chiffres, puis côte à côte ce que garde
  ``mind`` (une barre par table) et les sauvegardes (la dernière, sa vérification, les archives).
- Actions des opérateurs : un fil jour par jour — l'heure, qui, l'action, sur quoi, l'issue ; ses événements en liens.
- Toutes les vues : en sous-onglets, par destination, sur les fiches, par faculté, et celles qui sont cachées.
- Diagnostic avancé : en sous-onglets, l'ensemble des tranches (la plus récemment modifiée d'abord), puis une faculté
  par sous-onglet — ses faits lus maintenant, sa tranche en JSON, repliée.

Ce sont des pages de la console (``inspector/pages/system.py``) : leurs blocs restent la source, leurs filtres, leur
pagination et leur bascule « Tableau » restent les siens. Quand la page a besoin de nombres que les blocs disent en
texte (les coûts, les créneaux, les quotas) ou de toute une liste que la console pagine (les vues, les faits), elle les
relit à la même source : le registre des appels, la passerelle, le registre des facultés, l'état du noyau.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from markupsafe import Markup

from mika.app.handmade.tabs import Got, Line, Tab, anchored, blank, instant, raw_lines, rest, subpanes
from mika.app.handmade.tabs.decisions import by_day
from mika.inspector import names, render
from mika.inspector.pages.system import backup_state
from mika.inspector.ui import PREFIX, UI
from mika.kernel.clock import DAY, US
from mika.kernel.codec import to_plain
from mika.kernel.inspect import Badge, Ref, Row, Text, day_fr, money_fr, num_fr, pct_fr

STYLES = ("handmade/system.css",)


# ── Ce que partagent les onglets ──────────────────────────────────────────


def _band(tone: str, said: str, href: str = "", link: str = "") -> dict[str, str]:
    """Le bandeau d'une page : ce qui ne va pas (ou ce qui va), en une phrase ; un lien vers où le régler."""
    return {"tone": tone, "text": said, "href": href, "link": link}


def _num(label: str, value: int, sub: str = "", tone: str = "") -> dict[str, Any]:
    """Un chiffre d'une bande de chiffres dessinée par la page."""
    return {"label": label, "value": {"t": "text", "text": num_fr(value), "kind": "num"}, "sub": sub, "tone": tone,
            "href": ""}


def _cells(row: Any) -> list[Any]:
    """Les cellules d'une ligne telle que la console l'a déclarée (un ``Row`` ou un simple tuple)."""
    return list(row.cells if isinstance(row, Row) else row)


def _stats(*items: dict[str, Any]) -> dict[str, Any]:
    return {"t": "stats", "title": "", "items": list(items)}



def _hm(got: Got, at: int, seconds: bool = False) -> str:
    """L'heure locale d'un instant (« 14:05 »)."""
    return got.ui.kernel.mind.frame().local(at).strftime("%H:%M:%S" if seconds else "%H:%M") if at else ""


def _plural(n: int, word: str, words: str = "") -> str:
    return f"{num_fr(n)} {word if n == 1 else words or word + 's'}"


# ── Anomalies ─────────────────────────────────────────────────────────────

#: une anomalie d'une faculté, telle que ``runtime/mind.py`` l'écrit : « [évaluation ]faculté@seq: erreur »
FAILED_AT = re.compile(r"^(?P<eval>évaluation )?(?P<owner>[\w.-]+)@(?P<seq>\d+)\s*:\s*(?P<error>.*)$", re.S)
#: une anomalie de l'arbitre ou du journal : « faculté : ce qui ne va pas »
SAID_BY = re.compile(r"^(?P<owner>[\w.-]+) : (?P<error>.*)$", re.S)
#: les traces du journal (``Mind.trace``), en mots, et celles qui disent un problème
TRACES = {"superseded": "épisode supplanté", "forget": "oubli", "rebuild_mismatch": "reconstruction divergente",
          "tainted": "tranche corrompue", "gaps": "trous du journal", "snapshot_failed": "instantané manqué",
          "retired": "types sans propriétaire"}
TRACE_TROUBLE = frozenset({"rebuild_mismatch", "tainted", "gaps", "snapshot_failed"})


def _anomaly(ui: UI, said: str) -> dict[str, Any]:
    """Une anomalie : la faculté, l'événement où elle est née, l'erreur en clair (et telle quelle si elle dit plus)."""
    m = FAILED_AT.match(said.strip())
    if m:
        error, seq = m["error"].strip(), m["seq"]
        clear = names.detail(error)
        return {"faculty": ui.names.faculty(m["owner"]), "owner": m["owner"], "seq": seq,
                "href": f"{PREFIX}/evenement/{seq}", "eval": bool(m["eval"]), "said": clear,
                "raw": error if clear != error else ""}
    m = SAID_BY.match(said.strip())
    if m:
        return {"faculty": ui.names.faculty(m["owner"]), "owner": m["owner"], "seq": "", "href": "", "eval": False,
                "said": names.detail(m["error"].strip()), "raw": ""}
    return {"faculty": "", "owner": "", "seq": "", "href": "", "eval": False, "said": said, "raw": ""}


def _trace(got: Got, line: Line, raw: Mapping[str, Any]) -> dict[str, Any]:
    kind = line.text("sorte")
    said = line.text("détail")
    try:
        detail = json.loads(said)
    except ValueError:
        detail = None
    facts = [{"k": k, "v": ", ".join(map(str, v)) if isinstance(v, list) else str(v)}
             for k, v in detail.items()] if isinstance(detail, dict) else []
    at = instant(raw.get("quand"))
    return {"kind": TRACES.get(kind, kind.replace("_", " ")), "tech": kind, "warn": kind in TRACE_TROUBLE,
            "when": line.get("quand"), "at": at, "hm": _hm(got, at, True), "facts": facts,
            "said": "" if facts else said}


def anomalies(got: Got) -> Markup | None:
    """Système › Anomalies : le bandeau, les chiffres, ce qui a échoué, les traces du journal."""
    stats, traces = got.stats(), got.table("Traces du journal")
    if stats is None or traces is None:
        return None
    lists = []
    for title, key in (("Évaluations et réductions qui ont échoué", "an-evals"), ("Anomalies de l'arbitre", "an-arb")):
        t = got.table(title)
        if t is not None:
            lists.append({"t": t, "id": key, "items": [_anomaly(got.ui, x.text("anomalie")) for x in got.lines(title)]})
    notes = got.notes()
    note = next((n for n in notes if n.get("tone") in ("danger", "ok")), None)
    if note is not None:
        band = _band(note["tone"], note["text"])
    else:
        total = sum(x["t"]["count"] or 0 for x in lists)
        band = _band("warn", f"{_plural(total, 'anomalie')} depuis le démarrage : rien ne s'est arrêté, mais une "
                             "faculté ou l'arbitre n'a pas su traiter un événement.")
    items = [_trace(got, x, r) for x, r in zip(got.lines("Traces du journal"), raw_lines(got, traces), strict=False)]
    return got.draw("handmade/system/anomalies.html", band=band, stats=stats, lists=lists, traces=traces,
                    trace_days=by_day(got, items), notes=[n for n in notes if n is not note])


# ── Journal d'événements ──────────────────────────────────────────────────


def _event(got: Got, line: Line, raw: Mapping[str, Any]) -> dict[str, Any]:
    at = instant(raw.get("quand"))
    kind = line.text("type")
    return {"at": at, "hm": _hm(got, at, True), "when": line.get("quand"), "what": line.get("ce qui s'est passé"),
            "type": kind, "family": kind.split(".", 1)[0], "corr": line.text("corrélation"), "link": line.get("lié à"),
            "seq": line.text("événement").removeprefix("n° "), "href": line.href,
            "data": rest(line, ("événement", "type", "corrélation")), "open": line.open}


def chronologie(got: Got) -> Markup | None:
    """Système › Journal d'événements : un fil jour par jour, les données de chaque événement repliées."""
    t = got.table("Le journal")
    if t is None:
        return None
    items = [_event(got, x, r) for x, r in zip(got.lines("Le journal"), raw_lines(got, t), strict=False)]
    days = by_day(got, items)
    for d in days:  # un même épisode : son lien une fois, à son premier événement du jour (le plus récent)
        before = None
        for x in d["items"]:
            x["same"] = bool(x["corr"]) and x["corr"] == before
            before = x["corr"]
    kept = {k: v for k, v in got.query.items() if k == "correlation" and v}
    chosen = str(got.query.get("type") or "")
    families = [{"name": fam, "n": n, "href": "?" + urlencode({**kept, "type": f"{fam}."}),
                 "on": chosen == f"{fam}."}
                for fam, n in sorted(Counter(x["family"] for x in items).items(), key=lambda kv: (-kv[1], kv[0]))]
    everything = {"href": "?" + urlencode(kept), "on": not chosen} if chosen else None
    return got.draw("handmade/system/chronologie.html", t=t, days=days, families=families, everything=everything,
                    count=len(items), notes=got.notes())


# ── Écrans du monde ───────────────────────────────────────────────────────


def _lacks(said: str) -> list[dict[str, Any]]:
    """« ancres manquantes : a, b ; révision 6 chargée, 7 en vigueur » : chaque manque, ses éléments en puces."""
    out = []
    for part in (p.strip() for p in said.split(" ; ")):
        label, sep, things = part.partition(" : ")
        if part and part != "rien":
            out.append({"label": label if sep else part, "things": [x.strip() for x in things.split(",")] if sep
                        else []})
    return out


def monde(got: Got) -> Markup | None:
    """Système › Écrans du monde : ce qui manque à un hôte, les chiffres, les connexions et les chargements."""
    stats, notes = got.stats(), got.notes()
    sessions_t, loaded_t = got.table("Connexions"), got.table("Ce que chaque hôte a chargé")
    if stats is None:  # le monde n'est pas branché : sa note
        return got.draw("handmade/system/monde.html", off=notes, band=None) if notes else None
    if sessions_t is None or loaded_t is None:
        return None
    sessions = []
    for x in got.lines("Connexions"):
        lease = x.get("bail")
        sessions.append({"client": x.text("client"), "who": x.get("qui"),
                         "roles": [r for r in x.text("rôles").split(", ") if r and r != "—"],
                         "lease": lease if lease and lease.get("t") == "badge" else None,
                         "actor": x.text("acteur"), "session": x.text("connexion")})
    loaded = [{"when": x.get("quand"), "client": x.text("client"), "rev": x.text("révision"),
               "lacks": _lacks(x.text("ce qui lui manque")), "here": (x.get("connexion") or {}).get("t") == "badge",
               "warn": x.tone == "warn"} for x in got.lines("Ce que chaque hôte a chargé")]
    warns, infos = [n for n in notes if n.get("tone") == "warn"], [n for n in notes if n.get("tone") == "info"]
    band = _band("warn", warns[0]["text"] if len(warns) == 1 else
                 f"{len(warns)} hôtes connectés disent qu'il leur manque quelque chose : ce sont des lieux ou des objets "
                 "que leur moteur ne sait pas montrer.") if warns else \
        _band("info", infos[0]["text"]) if infos else None
    return got.draw("handmade/system/monde.html", off=None, band=band, stats=stats, sessions_t=sessions_t,
                    sessions=sessions, loaded_t=loaded_t, loaded=loaded)


# ── Contributions ─────────────────────────────────────────────────────────

#: ce qu'une faculté apporte, dans l'ordre de la page : (clé, titre, ce que c'est)
CONTRIBUTIONS = (
    ("publishes", "Publie", "ses événements publics, que les autres peuvent écouter"),
    ("listens", "Écoute", "les événements des autres qu'elle réduit"),
    ("facts", "Fournit", "ses faits, et les facultés qui les lisent"),
    ("sections", "Sections", "ce qu'elle écrit dans le prompt, et où"),
    ("proofs", "Preuves", "ce qu'elle apporte à l'arbitre, et leurs bornes"),
    ("processes", "Processus", "ses processus de fond"),
    ("tools", "Outils", "ce que le modèle peut appeler"),
    ("capabilities", "Capacités", "ce qu'elle fait sortir de la machine"),
    ("views", "Vues", "ce qu'elle montre d'elle à la console"),
    ("subjects", "Fiches", "les objets qu'elle déclare"),
    ("actions", "Actions", "ce qu'un opérateur peut lui demander"),
)
#: ce qui se dit en nom technique (en police à chasse fixe)
TECHNICAL = frozenset({"publishes", "listens", "sections", "proofs", "tools", "capabilities"})


def _contributions(ui: UI) -> list[dict[str, Any]]:
    """Ce que chaque faculté apporte, lu dans le registre comme la console le lit (``inspector/pages/system.py``) :
    en listes, pour la page, et non en texte."""
    reg = ui.kernel.registry
    readers: dict[str, set[str]] = defaultdict(set)
    for f in reg.faculties.values():
        for s in [*f.reducers, *f.facts, *f.sections, *f.enrichers, *f.proposers, *f.modulators, *f.processes,
                  *f.appraisals]:
            for r in getattr(s, "reads", ()):
                readers[r].add(f.name)
    out = []
    for f in reg.faculties.values():
        own = set(f.events)
        lists: dict[str, list[dict[str, Any]]] = {
            "publishes": [{"text": n, "hint": ui.names.event(n)} for n, t in sorted(f.events.items()) if t.public],
            "listens": [{"text": n, "hint": ui.names.event(n)} for n in
                        sorted({t.name for s in f.reducers for t in s.types if t.name not in own})] +
                       [{"text": f"forme {n}", "hint": ""} for n in
                        sorted({sh.__name__ for s in f.reducers for sh in s.shapes})],
            "facts": [{"text": s.key.name, "hint": getattr(s.key, "doc", ""),
                       "readers": sorted(ui.names.faculty(r) for r in readers.get(s.key.name, set()) - {f.name})}
                      for s in f.facts],
            "sections": [{"text": str(s.key), "hint": "", "where": s.zone.value} for s in f.sections],
            "proofs": [{"text": r, "hint": "", "where": f"[{num_fr(lo)} ; {num_fr(hi)}]"}
                       for s in f.proposers for r, (lo, hi) in s.reasons.items()],
            "processes": [{"text": ui.names.process(s.name), "hint": s.name} for s in f.processes],
            "tools": [{"text": s.name, "hint": ""} for s in sorted(f.tools, key=lambda s: s.name)],
            "capabilities": [{"text": s.name, "hint": ""} for s in sorted(f.capabilities, key=lambda s: s.name)],
            "views": [{"text": v.title, "hint": v.name, "href": render.href(Ref.view(v.owner, v.name, v.title))}
                      for v in sorted(f.inspectors, key=lambda v: v.title)],
            "subjects": [{"text": s.label, "hint": ""} for s in sorted(f.subjects, key=lambda s: s.label)],
            "actions": [{"text": a.title, "hint": ""} for a in sorted(f.actions, key=lambda a: a.title)],
        }
        out.append({"name": f.name, "label": ui.names.faculty(f.name), "lists": lists,
                    "counts": {k: len(v) for k, v in lists.items()},
                    "missing": [title.lower() for k, title, _what in CONTRIBUTIONS if not lists[k]]})
    return sorted(out, key=lambda f: f["label"].casefold())


def contributions(got: Got) -> Markup | None:
    """Système › Contributions : l'ensemble en un tableau, puis une faculté par sous-onglet."""
    if got.disclosure() is None:
        return None
    faculties = _contributions(got.ui)
    totals = {k: sum(f["counts"][k] for f in faculties) for k, _t, _w in CONTRIBUTIONS}
    unread = sum(1 for f in faculties for x in f["lists"]["facts"] if not x["readers"])
    band = _stats(_num("Facultés", len(faculties), "dans la composition"),
                  _num("Événements publics", totals["publishes"], "que les autres peuvent écouter"),
                  _num("Faits partagés", totals["facts"], f"dont {num_fr(unread)} sans autre lecteur déclaré"
                       if unread else "chacun lu par une autre faculté"),
                  _num("Processus", totals["processes"], "qui tournent en fond"),
                  _num("Outils", totals["tools"], "que le modèle peut appeler"))
    notes = got.notes()
    return got.draw("handmade/system/contributions.html", faculties=faculties, kinds=CONTRIBUTIONS,
                    technical=TECHNICAL, band=band, lede=" ".join(n["text"] for n in notes))


# ── Simulations ───────────────────────────────────────────────────────────

#: la sorte d'un rapport, par son extension
REPORT_KINDS = {"md": "texte", "txt": "texte", "html": "page", "json": "données"}


def simulations(got: Got) -> Markup | None:
    """Système › Simulations : les rapports à gauche, celui qu'on lit à droite."""
    t, notes = got.table("Rapports"), got.notes()
    if t is None:  # pas de dossier de rapports : sa note
        return got.draw("handmade/system/simulations.html", t=None, notes=notes) if notes else None
    chosen = str(got.query.get("fichier") or "")
    reports = []
    for x in got.lines("Rapports"):
        name = x.text("fichier")
        folder, _, base = name.rpartition("/")
        ext = base.rpartition(".")[2].lower()
        reports.append({"name": base, "folder": folder, "path": name, "href": (x.get("fichier") or {}).get("href", ""),
                        "kind": REPORT_KINDS.get(ext, ext), "when": x.get("modifié"), "on": name == chosen})
    return got.draw("handmade/system/simulations.html", t=t, reports=reports, chosen=chosen,
                    reading=got.first("prose"), notes=notes)


# ── Moteur des modèles ────────────────────────────────────────────────────


def _slots(busy: int, total: int) -> list[str]:
    """Les créneaux d'un fournisseur en cases : occupés d'abord (au plus douze montrées)."""
    return ["busy" if i < busy else "free" for i in range(min(total, 12))]


def passerelle(got: Got) -> Markup | None:
    """Système › Moteur des modèles : le bandeau, les chiffres, chaque fournisseur, qui sert quoi."""
    stats, notes = got.stats(), got.notes()
    if stats is None:  # aucun modèle configuré : sa note
        return got.draw("handmade/system/passerelle.html", band=_band(notes[0]["tone"], notes[0]["text"],
                                                                       f"{PREFIX}/reglages/fournisseurs",
                                                                       "Déclarer un fournisseur"),
                        stats=None) if notes else None
    providers_t, roles_raw = got.table("Fournisseurs"), got.raw_table("Qui sert quoi")
    roles_t = got.table("Qui sert quoi")
    if providers_t is None or roles_raw is None or roles_t is None:
        return None
    gateway, calls, now = got.ui.kernel.deps.gateway, got.ui.deps.calls, got.env.now
    providers = []
    for b in list(getattr(gateway, "status", list)() or []):
        quota = (b.get("extra") or {}).get("quota") or {}
        profile = calls.profile(b["name"], now - DAY) if calls is not None else None
        providers.append({
            "name": b["name"], "slots": _slots(b["busy"], b["slots"]), "busy": b["busy"], "total": b["slots"],
            "waiting": b["waiting"], "preempt": b["preempt"],
            "quota": [{"label": k, "w": round(100 * min(1.0, max(0.0, float(v))), 1), "text": pct_fr(float(v)),
                       "tone": "danger" if v >= 0.9 else "warn" if v >= 0.7 else ""}
                      for k, v in quota.items() if isinstance(v, int | float)],
            "day": None if profile is None else {
                "calls": profile.total.calls, "failures": profile.total.failures,
                "median": num_fr(profile.median_s, 1), "slow": num_fr(profile.slow_s, 1),
                "last_failure": render.relative(profile.last_failure_at, now) if profile.last_failure_at else "",
                "last_role": names.role(profile.last_failure_role) if profile.last_failure_role else ""}})
    served: dict[str, list[dict[str, str]]] = defaultdict(list)
    unserved = []
    for row in roles_raw.rows:
        label, tech, by = (_cells(row) + [None] * 3)[:3]
        role = {"label": str(label), "tech": tech.text if isinstance(tech, Text) else str(tech)}
        if isinstance(by, Text) and by.kind == "muted":
            unserved.append(role)
        else:
            served[by.text if isinstance(by, Text) else str(by)].append(role)
    waiting = sum(p["waiting"] for p in providers)
    band = _band("danger", f"{_plural(len(unserved), 'rôle')} sans fournisseur : "
                           f"{', '.join(r['label'] for r in unserved)}. Chaque appel de ce rôle échoue.",
                 f"{PREFIX}/reglages/roles", "Qui sert quoi") if unserved else \
        _band("warn", f"{_plural(waiting, 'appel attend', 'appels attendent')} un créneau libre.") if waiting else None
    return got.draw("handmade/system/passerelle.html", band=band, stats=stats, providers_t=providers_t,
                    providers=providers, roles_t=roles_t, served=sorted(served.items()), unserved=unserved,
                    notes=[n for n in notes if n.get("tone") != "danger"])


# ── Appels et coûts ───────────────────────────────────────────────────────

#: les sous-onglets d'Appels et coûts ; une page de la liste des appels ouvre la sienne
CALL_PANES = ("calls-split", "calls-all", "calls-days")


def _usage_rows(rows: Sequence[Any], label: Any) -> list[dict[str, Any]]:
    """Un agrégat par rôle, modèle ou fournisseur : deux barres (son coût ; ses appels, leurs échecs en bout), ses
    chiffres ; le plus coûteux d'abord, puis le plus appelé."""
    cost_top = max((u.cost_usd for u in rows), default=0.0)
    calls_top = max((u.calls for u in rows), default=0) or 1
    out = []
    for u in sorted(rows, key=lambda u: (-u.cost_usd, -u.calls, u.key)):
        out.append({"name": label(u.key), "tech": u.key, "cost": money_fr(u.cost_usd), "calls": u.calls,
                    "failures": u.failures, "cache": pct_fr(u.cache_ratio), "latency": num_fr(u.latency_avg_s, 1),
                    "tokens": f"{num_fr(u.input_tokens)} → {num_fr(u.output_tokens)}",
                    "w": round(100 * u.cost_usd / cost_top, 1) if cost_top else 0.0,
                    "cw": round(100 * u.calls / calls_top, 1), "fw": round(100 * u.failures / calls_top, 1)})
    return out


def _days(got: Got, usage: Mapping[str, Any]) -> dict[str, Any]:
    """Quatorze jours en barres : le coût en haut (s'il y en a), les appels en bas, leurs échecs en rouge. Les jours
    sont ceux que touchent ses quatorze fois vingt-quatre heures, comme les chiffres de la console (quinze barres, le
    premier jour entamé)."""
    frame, now = got.ui.kernel.mind.frame(), got.env.now
    today, start = frame.local(now).date(), frame.local(now - 14 * DAY).date()
    days = [start + timedelta(days=i) for i in range((today - start).days + 1)]
    got_days = [usage.get(d.strftime("%Y-%m-%d")) for d in days]
    cost_top = max((u.cost_usd for u in got_days if u), default=0.0)
    calls_top = max((u.calls for u in got_days if u), default=0) or 1
    cost_h, calls_h = (40.0, 20.0) if cost_top else (0.0, 44.0)
    bars = []
    for i, (d, u) in enumerate(zip(days, got_days, strict=True)):
        cost, n, failed = (u.cost_usd, u.calls, u.failures) if u else (0.0, 0, 0)
        h = round(cost_h * cost / cost_top, 2) if cost_top else 0.0
        ch = round(calls_h * n / calls_top, 2)
        fh = round(calls_h * failed / calls_top, 2)
        base = cost_h + 4 + calls_h if cost_top else calls_h
        bars.append({"x": i * 10 + 1.5, "cost_y": round(cost_h - h, 2), "cost_h": h, "calls_y": round(base - ch, 2),
                     "calls_h": ch, "fail_y": round(base - fh, 2), "fail_h": fh, "n": n, "failed": failed,
                     "cost": money_fr(cost), "day": day_fr(d.year, d.month, d.day, d.weekday()),
                     "label": str(d.day), "today": d == today, "monday": d.weekday() == 0})
    return {"bars": bars, "width": 10 * len(bars), "cost_top": money_fr(cost_top) if cost_top else "",
            "calls_top": calls_top,
            "height": round(cost_h + 4 + calls_h, 2) if cost_top else calls_h, "cost_h": cost_h,
            "split": cost_h + 2 if cost_top else 0, "has_cost": bool(cost_top),
            "total": money_fr(sum(u.cost_usd for u in got_days if u)), "calls": sum(u.calls for u in got_days if u),
            "failures": sum(u.failures for u in got_days if u)}


def _call(line: Line) -> dict[str, Any]:
    outcome = line.get("issue") or {}
    failed = outcome.get("tone") == "danger" or line.tone == "danger"
    return {"when": line.get("quand"), "role": line.text("rôle"), "backend": line.text("fournisseur"),
            "model": line.text("modèle"), "wait": line.text("attente"), "took": line.text("durée"),
            "tokens": line.text("jetons"), "cost": line.text("coût"), "outcome": outcome, "failed": failed,
            "href": line.href}


def appels(got: Got) -> Markup | None:
    """Système › Appels et coûts : les échecs, les chiffres, quatorze jours en barres ; où va le coût, tous les
    appels et le détail jour par jour en sous-onglets."""
    stats, all_t, notes = got.stats(), got.table("Tous les appels"), got.notes()
    calls = got.ui.deps.calls
    if calls is None or stats is None or all_t is None:  # pas de registre : sa note
        return got.draw("handmade/system/appels.html", off=notes) if notes else None
    ui, now = got.ui, got.env.now

    def day_of(at: int) -> str:
        return datetime.fromtimestamp(at / US, ui.tz).strftime("%Y-%m-%d")

    usage = {u.key: u for u in calls.usage(now - 14 * DAY, by="day", day_of=day_of)}
    chart = _days(got, usage)
    roles = calls.usage(now - 7 * DAY, by="role")
    split = [{"id": "calls-roles", "title": "Par rôle", "rows": _usage_rows(roles, names.role)},
             {"id": "calls-models", "title": "Par modèle",
              "rows": _usage_rows(calls.usage(now - 7 * DAY, by="model"), str)},
             {"id": "calls-backends", "title": "Par fournisseur",
              "rows": _usage_rows(calls.usage(now - 7 * DAY, by="backend"), str)}]
    for g in split:
        g["cost"] = any(r["w"] for r in g["rows"])
    today = usage.get(day_of(now))
    failing = sorted((u for u in roles if u.failures), key=lambda u: -u.failures)
    band = None
    if chart["failures"]:
        worst = ", ".join(f"{names.role(u.key)} ({u.failures})" for u in failing[:3])
        band = _band("danger" if today and today.failures else "warn",
                     f"{_plural(chart['failures'], 'appel a échoué', 'appels ont échoué')} en quatorze jours"
                     + (f", dont {num_fr(today.failures)} aujourd'hui" if today and today.failures else "")
                     + (f" — surtout : {worst}" if worst else "") + ".", "#calls-all", "Les voir")
    first = "calls-all" if got.query.get("page") else ""
    return got.draw("handmade/system/appels.html", off=None, band=band, stats=stats, chart=chart, split=split,
                    all_t=anchored(all_t, "calls-all"), calls=[_call(x) for x in got.lines("Tous les appels")],
                    days_t=got.table("Par jour"),
                    panes=[p["id"] for p in subpanes([{"id": p} for p in CALL_PANES], first)])


# ── Stockage et sauvegardes ───────────────────────────────────────────────


def stockage(got: Got) -> Markup | None:
    """Système › Stockage et sauvegardes : le bandeau des sauvegardes, les chiffres, les bases, les sauvegardes."""
    bases, kept = got.first("stats"), got.table("Ce que garde")
    if bases is None or kept is None:
        return None
    rows = [(x, r) for x, r in zip(got.lines("Ce que garde"), raw_lines(got, kept), strict=False)]
    top = max((int(r.get("lignes") or 0) for _x, r in rows), default=0) or 1
    tables = [{"name": x.text("table"), "n": x.text("lignes"), "what": x.text("ce qu'elle garde"),
               "w": round(100 * int(r.get("lignes") or 0) / top, 1)} for x, r in rows]
    saves = got.stats("Sauvegardes")
    tone, said = backup_state(got.ui)
    band = _band(tone, f"Sauvegardes : {said}.") if tone in ("warn", "danger") else None
    archives = got.table("Archives")
    return got.draw("handmade/system/stockage.html", band=band, bases=bases, kept=kept, tables=tables,
                    saves=(saves or {}).get("items", []), last=got.fields("La dernière sauvegarde"),
                    archives=archives, archive_items=[{"name": x.text("archive"), "size": x.text("taille"),
                                                       "when": x.get("écrite")} for x in got.lines("Archives")],
                    notes=got.notes(), saved=saves is not None)


# ── Actions des opérateurs ────────────────────────────────────────────────


def _operation(got: Got, line: Line, raw: Mapping[str, Any]) -> dict[str, Any]:
    at = instant(raw.get("quand"))
    outcome = line.get("issue") or {}
    seqs = [s.strip() for s in line.text("événements").split(",") if s.strip().isdigit()]
    return {"at": at, "hm": _hm(got, at), "when": line.get("quand"), "action": line.text("action"),
            "by": line.text("par"), "on": None if blank(line.get("sur")) else line.get("sur"),
            "outcome": outcome, "key": line.text("action (clé)"), "href": line.href,
            "events": [{"n": s, "href": f"{PREFIX}/evenement/{s}"} for s in seqs]}


def operations(got: Got) -> Markup | None:
    """Système › Actions des opérateurs : un fil jour par jour, qui a fait quoi, sur quoi, avec quelle issue."""
    t = got.table("Ce que les opérateurs ont fait")
    if t is None:
        return None
    items = [_operation(got, x, r) for x, r in zip(got.lines("Ce que les opérateurs ont fait"), raw_lines(got, t),
                                                   strict=False)]
    outcomes = Counter((x["outcome"].get("text", ""), x["outcome"].get("tone", "")) for x in items)
    who = Counter(x["by"] for x in items)
    return got.draw("handmade/system/operations.html", t=t, days=by_day(got, items),
                    outcomes=[{"text": k, "tone": tone, "n": n} for (k, tone), n in outcomes.most_common() if k],
                    who=[{"name": k, "n": n} for k, n in who.most_common()], shown=len(items))


# ── Toutes les vues ───────────────────────────────────────────────────────


def _groups(views: Sequence[dict[str, Any]], key: str, labels: Mapping[str, str], order: Sequence[str] = (),
            hrefs: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for v in views:
        if v[key]:
            by[v[key]].append(v)
    rank = {k: i for i, k in enumerate(order)}
    keys = sorted(by, key=lambda k: (rank.get(k, len(rank)), labels.get(k, k).casefold()))
    return [{"key": k, "label": labels.get(k, k), "href": (hrefs or {}).get(k, ""),
             "views": sorted(by[k], key=lambda v: v["title"].casefold())} for k in keys]


def vues(got: Got) -> Markup | None:
    """Système › Toutes les vues : par destination, sur les fiches, par faculté, et les cachées."""
    raw = got.raw_table("Ce que chaque faculté montre")
    if raw is None:
        return None
    dests = {d.key: d.label for g in (got.ui.deps.navigation or ()) for d in g.items}
    views = []
    for row in raw.rows:
        ref, fac, section, subject, hidden = (_cells(row) + [None] * 5)[:5]
        title = ref.text if isinstance(ref, Ref) else str(ref)
        views.append({"title": title, "href": render.href(ref) if isinstance(ref, Ref) else "",
                      "faculty": fac.text if isinstance(fac, Text) else str(fac),
                      "owner": fac.hint if isinstance(fac, Text) else "",
                      "section": "" if section in (None, "—") else str(section),
                      "subject": "" if subject in (None, "—") else str(subject),
                      "hidden": isinstance(hidden, Badge)})
    for v in views:
        v["where"] = (dests.get(v["section"], v["section"]) if v["section"] else
                      f"fiche {_subject_label(got, v['subject'])}" if v["subject"] else "")
        v["nowhere"] = "" if v["section"] or v["subject"] or v["hidden"] else "sans place"
    subjects = {v["subject"]: _subject_label(got, v["subject"]) for v in views if v["subject"]}
    shown = [v for v in views if not v["hidden"]]
    panes = [
        {"id": "views-dest", "title": "Par destination", "lede": "Les onglets de chaque destination de la console : "
         "une vue de faculté y prend place à côté des pages de la console.",
         "groups": _groups(shown, "section", dests, list(dests), {k: f"{PREFIX}/{k}" for k in dests})},
        {"id": "views-subject", "title": "Sur les fiches", "lede": "Les onglets de la fiche d'un objet (une personne, "
         "un mail, un projet…).", "groups": _groups(shown, "subject", subjects)},
        {"id": "views-faculty", "title": "Par faculté", "lede": "Ce que chaque faculté montre d'elle, et où.",
         "groups": _groups(views, "faculty", {}), "where": True},
        {"id": "views-hidden", "title": "Cachées", "lede": "Des vues qui ne s'affichent dans aucune destination : "
         "elles s'ouvrent par leur adresse, ou servent à la console en MCP.",
         "groups": _groups([v for v in views if v["hidden"]], "faculty", {}), "where": True},
    ]
    for p in panes:
        p["n"] = sum(len(g["views"]) for g in p["groups"])
    lost = [v for v in shown if v["nowhere"]]
    if lost:
        panes[0]["groups"].append({"key": "", "label": "Sans place", "href": "", "views": lost})
        panes[0]["n"] += len(lost)
    owners = {v["owner"] or v["faculty"] for v in views}
    return got.draw("handmade/system/vues.html", panes=[p for p in panes if p["n"]], total=len(views),
                    faculties=len(owners), places=len({v["section"] for v in shown if v["section"]}),
                    subjects=len(subjects), hidden=sum(1 for v in views if v["hidden"]))


def _subject_label(got: Got, kind: str) -> str:
    spec = got.ui.inspection.subject(kind)
    return getattr(spec, "label", "") or kind


# ── Diagnostic avancé ─────────────────────────────────────────────────────

#: la tranche d'une faculté, en JSON, montrée jusqu'à tant de caractères
SLICE_MAX = 12_000
#: le titre que la console donne au repli d'une tranche : « faculté · modifiée au seq N »
SLICE_TITLE = re.compile(r"^(?P<owner>.+?) · modifiée au seq (?P<seq>\d+)$")
#: une valeur de fait montrée telle quelle jusqu'à tant de caractères, repliée au-delà
VALUE_SHORT = 160


def _slice_json(ui: UI, owner: str, fallback: str) -> tuple[str, bool]:
    """La tranche d'une faculté en JSON (indentée) ; telle que la console l'écrit si elle ne s'y réduit pas."""
    value = ui.kernel.mind.root.slices.get(owner)
    try:
        said = json.dumps(to_plain(value), ensure_ascii=False, indent=1)
    except (TypeError, ValueError):
        said = fallback
    return said[:SLICE_MAX], len(said) > SLICE_MAX


def etat(got: Got) -> Markup | None:
    """Système › Diagnostic avancé : l'ensemble des tranches, puis une faculté par sous-onglet (ses faits, sa
    tranche)."""
    facts_raw, slices = got.raw_table("Faits"), got.disclosure("Tranches")
    if facts_raw is None or slices is None:
        return None
    ui, head = got.ui, got.ui.kernel.mind.head
    facts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in facts_raw.rows:
        name, owner, doc, value = (_cells(row) + [None] * 4)[:4]
        said = value.text if isinstance(value, Text) else str(value)
        facts[str(owner)].append({"name": name.text if isinstance(name, Text) else str(name),
                                  "doc": doc.text if isinstance(doc, Text) else str(doc or ""), "value": said,
                                  "short": said[:VALUE_SHORT], "long": len(said) > VALUE_SHORT,
                                  "family": said.startswith("famille"), "error": said.startswith("(erreur")})
    tainted = dict(ui.kernel.mind.root.tainted.items())
    owners: dict[str, dict[str, Any]] = {}
    for d in slices.get("items", []):
        m = SLICE_TITLE.match(str(d.get("title") or ""))
        if m is None:
            continue
        code = next((x.get("text", "") for x in d.get("items", []) if x.get("t") == "code"), "")
        said, cut = _slice_json(ui, m["owner"], code)
        owners[m["owner"]] = {"seq": int(m["seq"]), "json": said, "cut": cut, "size": len(code)}
    for owner in facts:
        owners.setdefault(owner, {"seq": 0, "json": "", "cut": False, "size": 0})
    panes = []
    for owner, s in owners.items():
        mine = facts.get(owner, [])
        panes.append({"id": f"st-{re.sub(r'[^A-Za-z0-9_-]', '-', owner)}", "owner": owner,
                      "label": ui.names.faculty(owner), "facts": mine,
                      "read": [f for f in mine if not f["family"]], "families": [f for f in mine if f["family"]], **s,
                      "href": f"{PREFIX}/evenement/{s['seq']}" if s["seq"] else "",
                      "tainted": tainted.get(owner), "age": head - s["seq"] if s["seq"] else None})
    panes.sort(key=lambda p: p["label"].casefold())
    recent = sorted(panes, key=lambda p: -p["seq"])
    notes = got.notes()
    note = next((n for n in notes if n.get("tone") == "danger"), None)
    return got.draw("handmade/system/etat.html", panes=panes, recent=recent, head=head,
                    band=_band("danger", note["text"] + " Leur état est figé jusqu'à leur reconstruction "
                                                        "(« mika rebuild »).") if note else None,
                    total=sum(len(p["facts"]) for p in panes),
                    errors=sum(1 for p in panes for f in p["facts"] if f["error"]))


TABS: dict[str, Any] = {
    "systeme/anomalies": Tab(anomalies, *STYLES),
    "systeme/chronologie": Tab(chronologie, *STYLES),
    "systeme/monde": Tab(monde, *STYLES),
    "systeme/contributions": Tab(contributions, *STYLES),
    "systeme/simulations": Tab(simulations, *STYLES),
    "systeme/passerelle": Tab(passerelle, *STYLES),
    "systeme/appels": Tab(appels, *STYLES),
    "systeme/stockage": Tab(stockage, *STYLES),
    "systeme/operations": Tab(operations, *STYLES),
    "systeme/vues": Tab(vues, *STYLES),
    "systeme/etat": Tab(etat, *STYLES),
}
