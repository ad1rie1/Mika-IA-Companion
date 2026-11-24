"""Système : ses onglets, chacun dans sa forme (ADR 0177), sur la même feuille (``handmade/systeme.css``).

Des pages d'exploitation, faites pour diagnostiquer : ce qui ne va pas d'abord, en un seul bandeau ; des chiffres ;
puis les données denses en listes serrées, lisibles en colonnes.

- Anomalies : le bandeau (des tranches corrompues, avec quand leur reconstruction sert et la commande qui les
  reconstruit serveur arrêté ; des anomalies ; ou rien), la bande de chiffres, les tranches corrompues (lues au
  tableau de la vue, ``TAINTED_TITLE``), chacune avec « Reconstruire » — en ligne, ADR 0234 —, puis côte à côte ce qui
  a échoué dans ses facultés (la faculté, l'événement, l'erreur en clair) et à l'arbitre ; les traces du journal en
  fil, chacune en mots (« épisode supplanté », « oubli »…).
- Journal d'événements : un fil jour par jour, en deux colonnes sur un grand écran — l'heure, ce qui s'est passé (un
  geste audité dit lequel et qui l'a fait), son type ; les événements d'un même épisode se suivent sans répéter leur
  lien ; les données de chacun repliées. Les familles d'événements de la page en puces, qui filtrent : chacune sous le
  nom de la faculté qui possède ses types (la colonne repliée « faculté » de la vue), celles du moteur sous leur sens
  (``ENGINE_FAMILIES``), son préfixe au survol.
- Écrans du monde : le bandeau (ce qui manque à un hôte connecté), les chiffres, puis côte à côte les connexions
  (leurs rôles, qui tient le bail) et ce que chaque hôte a chargé (ce qui lui manque, en puces).
- Contributions : un tableau d'ensemble (une ligne par faculté, ce qu'elle apporte en nombres), puis une faculté par
  sous-onglet — ce qu'elle publie, écoute, fournit (et qui le lit), ses sections, preuves, processus, outils… Elle lit
  ses listes à ``contributions_of``, la seule lecture du registre, que sa vue joint en texte ; ses processus sont ceux
  de l'ordonnanceur, par propriétaire, comme Processus les compte (le « Noyau » a l'arbitre et le relevé des courbes).
  Ses vues ne s'y relistent pas : un lien « Ses vues (N) » mène à Toutes les vues › Par faculté, ouverte sur elle
  (``views_of``, C8-12) ; leur nombre reste au tableau d'ensemble.
- Simulations : le gabarit « client » — les rapports à gauche, celui qu'on lit à droite ; sans dossier de rapports, la
  seule carte « Faire un rapport » (la note de la vue s'y tait), et le menu ne la montre pas (``menu_for``).
- Moteur des modèles : le bandeau (un rôle sans fournisseur, une file d'attente), les chiffres, puis chaque
  fournisseur (ses créneaux en cases, son quota en jauges, ce qu'il a fait en 24 h) et qui sert quoi, rôle par
  fournisseur. Un rôle facultatif sans modèle (``OPTIONAL_ROLES``, rendre naturel : la seconde passe) n'est pas « sans
  fournisseur » : il est coupé, par choix, et se range à part, sans alarme — aucun appel n'échoue.
- Appels et coûts : sur la période choisie (7, 14 ou 30 jours, un bouton à choix au bout de la barre d'onglets, 14
  posé), le bandeau des échecs, les chiffres, le coût et les appels en barres, une par jour (les échecs en rouge) ;
  puis en sous-onglets où va le coût (par rôle, par modèle, par fournisseur), tous les appels (paginés, sans période),
  le détail jour par jour. Elle lit les blocs de sa vue — son graphe (les jours de la période, leur coût), ses
  tableaux (par jour, par rôle, par modèle, par fournisseur, leur clé en colonne repliée) — : la période et ses
  agrégats se calculent une fois, dans la vue (``call_period``, ``CALL_PERIOD``).
- Stockage et sauvegardes : le bandeau des sauvegardes s'il y a lieu, les chiffres, puis côte à côte ses bases et ses
  dossiers (la place de chacun, ce qu'il garde, ce que la sauvegarde en fait) au-dessus de ce que garde ``mind`` (une
  barre par table), et les sauvegardes (la dernière, sa vérification, les archives, puis les commandes pour
  sauvegarder, vérifier, restaurer, avec ses vrais dossiers : la note de sa vue, ``backup_note``).
- Gestes audités : un fil jour par jour — l'heure, qui, le geste, d'où (la console, son espace, la ligne de
  commande), sur quoi (le titre de sa fiche, sa clé au survol), l'issue ; ses événements en liens.
- Toutes les vues : en sous-onglets, par destination, sur les fiches, par faculté (chaque faculté à son ancre,
  ``views_of`` : son adresse ouvre ce sous-onglet sur elle), et celles qui sont cachées.
- Diagnostic avancé : le bandeau des tranches corrompues (la phrase d'Anomalies, sa commande comprise), puis en
  sous-onglets l'ensemble des tranches (la plus récemment modifiée d'abord, « modifiée au n° N »), puis une faculté
  par sous-onglet — ses faits lus maintenant, sa tranche en JSON, repliée ; corrompue, « Reconstruire » en tête.
- Processus (ADR 0121) : ses processus de fond lus à l'ordonnanceur, comme l'onglet de la console — d'abord ce qui
  échoue, avec sa dernière erreur en clair, son prochain essai et, s'il est en échec et pas en cours, « Réessayer
  maintenant » (son recul effacé, ADR 0234 ; jamais sur un processus retenu pour une rafale) ; puis tous les autres,
  une carte par faculté, une ligne chacun. L'historique des échecs gardés au journal reste celui de la console (sa
  pagination à curseur).
- Sorties : le parcours d'un effet et où en sont les départs, ce qui est à traiter (ce qui n'est pas parti et à qui —
  une parole, son destinataire et son début ; une action, son résumé —, que faire pour sa sorte ; relancer, marquer
  comme vu), ce qui part, par sorte, et les derniers départs, une ligne par effet — ce qu'il fait partir, son état, son
  événement. Les mots de chaque effet (sa famille, son nom, ce que c'est) viennent de la composition
  (``Names.effect``, ``EFFECT_LABELS`` et ``EFFECT_FAMILIES`` de ``app/console.py``), comme ceux de sa vue et de la
  page d'un événement. Elle dit tout ce que disait le panneau de la console (``panel=False``), qui ne revient qu'au
  repli. Elle ne lit rien d'autre que les blocs de la console : la rangée des états et ses comptes, la page des
  départs, les lignes à traiter (avec à qui et quoi) et le tableau par sorte (leurs tailles et leurs pages sont celles
  de la console, que lit aussi la console en MCP).
- Santé : le bilan, lu dans les blocs de la console (le rapport de santé ne s'y calcule qu'une fois) — son verdict,
  puis ses tuiles : les dix contrôles, et deux qui n'en sont pas (les sauvegardes, les anomalies depuis le démarrage :
  la sonde publique ne les voit pas), ce qui ne va pas d'abord, chacune avec son constat, son détail et la page de son
  diagnostic ; ses projections, nommées en mots, lues dans ses tableaux ; la sonde publique en repli.

Ce sont des pages de la console (``inspector/pages/system.py``) : leurs blocs restent la source, leurs filtres, leur
pagination et leur bascule « Tableau » restent les siens. Une page qui a besoin de ce que sa vue ne dit pas le fait
ajouter à la vue — une colonne, un tableau, repliés au besoin — plutôt que de le relire à côté (ADR 0177) : un seul
calcul, une seule taille de page, pour la page dessinée, son repli et la console en MCP. Contributions a besoin de
listes que sa vue ne dit qu'en texte : la page et la vue partagent une seule fonction de données
(``contributions_of``), plutôt que de lire les blocs. Les pages qui relisent encore une source à côté de leurs blocs
(les créneaux, les quotas et ce qu'a fait chaque fournisseur en 24 h, au registre des appels et à la passerelle ; les
vues et les tranches à l'inspection et à l'état du noyau) sont des restes, pas la règle.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from markupsafe import Markup

from mika.app.console import EFFECT_FAMILIES
from mika.app.handmade import blocks as drawn_blocks
from mika.app.handmade.tabs import (
    Got,
    Line,
    Tab,
    anchored,
    blank,
    instant,
    key_of,
    number,
    raw_lines,
    raw_rows,
    rest,
    subpanes,
)
from mika.app.handmade.tabs.decisions import by_day
from mika.inspector import names, render
from mika.inspector.pages import diagnostics
from mika.inspector.pages.runtime_diagnostics import TAINTED_TITLE, rebuildable
from mika.inspector.pages.subjects import VIEWS
from mika.inspector.pages.system import (
    CALLS_ALL_TITLE,
    CALLS_BACKENDS_TITLE,
    CALLS_CHART_TITLE,
    CALLS_DAYS_TITLE,
    CALLS_MODELS_TITLE,
    CALLS_ROLES_TITLE,
    OPERATIONS_TITLE,
    OUTBOX_KINDS_TITLE,
    OUTBOX_RECENT_TITLE,
    OUTBOX_ROUTE,
    OUTBOX_TODO_TITLE,
    PLACES_TITLE,
    backup_state,
    call_period,
    contributions_of,
)
from mika.inspector.ui import PREFIX, UI, env
from mika.kernel.clock import DAY, US
from mika.kernel.codec import to_plain
from mika.kernel.faculty import Tier
from mika.kernel.inspect import (
    Badge,
    Chart,
    Code,
    Disclosure,
    Nav,
    Ref,
    Row,
    Stats,
    Text,
    agree,
    money_fr,
    num_fr,
    pct_fr,
    plural,
    relative_fr,
    short_day_fr,
)
from mika.ports.llm import EFFORT_LABELS
from mika.runtime import health as health_m
from mika.runtime.effects import (
    MAX_ATTEMPTS,
    OUTBOX_LABELS,
    OUTBOX_PROBLEMS,
    OUTBOX_SEEN_ONLY,
    RETRY_BASE_S,
    RETRY_MAX_S,
    STALE_AFTER_S,
)
from mika.runtime.inspection import SLOW_US
from mika.vocab.episodes import OPTIONAL_ROLES

STYLES = ("handmade/systeme.css",)


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


def _back(got: Got, path: str) -> str:
    """Où revient un geste de la page (``_retour``) : elle-même, ses paramètres gardés, sauf le message d'un geste."""
    kept = {k: v for k, v in got.query.items() if k != "flash"}
    return f"{PREFIX}/{path}" + (f"?{urlencode(kept)}" if kept else "")


def _journal(got: Got) -> str:
    """Ce que relit une reconstruction : tout le journal, en nombre d'événements (la confirmation de « Reconstruire »)."""
    return plural(got.ui.kernel.mind.head, "événement", "événements")


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


def _tainted(got: Got) -> list[dict[str, Any]]:
    """Les tranches corrompues, lues au tableau de la vue (``TAINTED_TITLE``) : la faculté, l'événement où son réducteur
    a levé ; « Reconstruire » pour celle qui se rejoue (``rebuildable`` : une tranche volatile ne se rejoue pas)."""
    table = got.raw_table(TAINTED_TITLE)
    out = []
    for _row, cells in raw_rows(table) if table is not None else ():
        owner, seq = _said(cells.get("faculté (clé)")), getattr(cells.get("corrompue au"), "key", "")
        out.append({"owner": owner, "faculty": _said(cells.get("faculté")) or owner, "seq": seq,
                    "href": f"{PREFIX}/evenement/{seq}" if seq else "", "rebuild": rebuildable(got.ui.kernel, owner)})
    return out


def anomalies(got: Got) -> Markup | None:
    """Système › Anomalies : le bandeau, les chiffres, les tranches corrompues (chacune avec « Reconstruire »), ce qui
    a échoué, les traces du journal."""
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
        band = _band("warn", f"{plural(total, 'anomalie', 'anomalies')} depuis le démarrage : rien ne s'est arrêté, "
                             "mais une faculté ou l'arbitre n'a pas su traiter un événement.")
    items = [_trace(got, x, r) for x, r in zip(got.lines("Traces du journal"), raw_lines(got, traces), strict=False)]
    return got.draw("handmade/systeme/anomalies.html", band=band, stats=stats, lists=lists, traces=traces,
                    trace_days=by_day(got, items), notes=[n for n in notes if n is not note], tainted=_tainted(got),
                    csrf=getattr(got.forms, "csrf", ""), back=_back(got, "systeme/anomalies"), journal=_journal(got))


# ── Journal d'événements ──────────────────────────────────────────────────


#: les familles d'événements du moteur (``runtime`` les possède toutes, « Moteur ») sous leur sens, par leur préfixe :
#: les puces du Journal d'événements diraient sinon quatre fois « Moteur »
ENGINE_FAMILIES = {"episode": "Épisodes", "perception": "Ce qu'elle perçoit", "effect": "Effets", "runtime": "Moteur"}


def _event(got: Got, line: Line, raw: Mapping[str, Any]) -> dict[str, Any]:
    at = instant(raw.get("quand"))
    kind = line.text("type")
    return {"at": at, "hm": _hm(got, at, True), "when": line.get("quand"), "what": line.get("ce qui s'est passé"),
            "type": kind, "family": kind.split(".", 1)[0], "faculty": line.text("faculté"),
            "corr": line.text("corrélation"), "link": line.get("lié à"),
            "seq": line.text("événement").removeprefix("n° "), "href": line.href,
            "data": rest(line, ("faculté", "événement", "type", "corrélation")), "open": line.open}


def _families(items: Sequence[Mapping[str, Any]], kept: Mapping[str, str], chosen: str) -> list[dict[str, Any]]:
    """Les familles d'événements de la page, les plus nombreuses d'abord : chacune sous le nom de la faculté qui possède
    ses types (celles du moteur sous leur sens), son préfixe au survol ; elle filtre par ce préfixe (``?type=<préfixe>.``),
    la corrélation choisie (``kept``) gardée."""
    named: dict[str, str] = {}
    for x in items:
        named.setdefault(x["family"], ENGINE_FAMILIES.get(x["family"]) or x["faculty"] or x["family"])
    return [{"name": named[fam], "prefix": fam, "n": n, "href": "?" + urlencode({**kept, "type": f"{fam}."}),
             "on": chosen == f"{fam}."}
            for fam, n in sorted(Counter(x["family"] for x in items).items(), key=lambda kv: (-kv[1], kv[0]))]


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
    families = _families(items, kept, chosen)
    everything = {"href": "?" + urlencode(kept), "on": not chosen} if chosen else None
    return got.draw("handmade/systeme/chronologie.html", t=t, days=days, families=families, everything=everything,
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
        return got.draw("handmade/systeme/monde.html", off=notes, band=None) if notes else None
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
    return got.draw("handmade/systeme/monde.html", off=None, band=band, stats=stats, sessions_t=sessions_t,
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


#: l'ancre d'une faculté dans Toutes les vues › Par faculté (``views_of``)
VIEWS_ANCHOR = "vues-de-"


def views_of(owner: str) -> str:
    """Où se lisent les vues d'une faculté : Toutes les vues › Par faculté, ouverte sur son groupe — son ancre, que le
    script des sous-onglets suit (``console.js``, la section qui contient l'élément visé). Contributions y mène plutôt
    que de relister ses vues (C8-12)."""
    return f"{VIEWS}#{VIEWS_ANCHOR}{owner}"


def _contributions(ui: UI) -> list[dict[str, Any]]:
    """Ce que chaque faculté apporte, en listes pour la page : la lecture que joint aussi sa vue (``contributions_of``,
    ``inspector/pages/system.py``), ses processus à l'ordonnanceur compris. La page n'y ajoute que ses mots (un
    processus, une faculté en clair), ses indices (au survol) et où se lisent ses vues (``views_of``)."""
    out = []
    for c in contributions_of(ui.kernel):
        lists: dict[str, list[dict[str, Any]]] = {
            "publishes": [{"text": n, "hint": ui.names.event(n)} for n in c.publishes],
            "listens": [{"text": n, "hint": ui.names.event(n)} for n in c.listens] +
                       [{"text": f"forme {n}", "hint": ""} for n in c.shapes],
            "facts": [{"text": x.key.name, "hint": getattr(x.key, "doc", ""),
                       "readers": sorted(ui.names.faculty(r) for r in x.readers)} for x in c.facts],
            "sections": [{"text": str(s.key), "hint": "", "where": s.zone.value} for s in c.sections],
            "proofs": [{"text": r, "hint": "", "where": f"[{num_fr(lo)} ; {num_fr(hi)}]"}
                       for s in c.proposers for r, (lo, hi) in s.reasons.items()],
            "processes": sorted(({"text": ui.names.process(s.name), "hint": s.name} for s in c.processes),
                                key=lambda x: x["text"].casefold()),
            "tools": [{"text": s.name, "hint": ""} for s in c.tools],
            "capabilities": [{"text": s.name, "hint": ""} for s in c.capabilities],
            "views": [{"text": ui.named(v.title), "hint": v.name} for v in c.views],
            "subjects": [{"text": s.label, "hint": ""} for s in c.subjects],
            "actions": [{"text": a.title, "hint": ""} for a in c.actions],
        }
        out.append({"name": c.owner, "label": ui.names.faculty(c.owner), "lists": lists, "views_href": views_of(c.owner),
                    "counts": {k: len(v) for k, v in lists.items()},
                    "missing": [title.lower() for k, title, _what in CONTRIBUTIONS if not lists[k]]})
    return sorted(out, key=lambda f: f["label"].casefold())


def contributions(got: Got) -> Markup | None:
    """Système › Contributions : l'ensemble en un tableau, puis une faculté par sous-onglet. La bande compte les
    processus de l'ordonnanceur, comme Système › Processus."""
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
    return got.draw("handmade/systeme/contributions.html", faculties=faculties, kinds=CONTRIBUTIONS,
                    technical=TECHNICAL, band=band, lede=" ".join(n["text"] for n in notes))


# ── Simulations ───────────────────────────────────────────────────────────

#: la sorte d'un rapport, par son extension
REPORT_KINDS = {"md": "texte", "txt": "texte", "html": "page", "json": "données"}


def simulations(got: Got) -> Markup | None:
    """Système › Simulations : les rapports à gauche, celui qu'on lit à droite. Sans dossier de rapports, la vue n'a
    que sa note : la page dit une seule fois comment en faire, par sa carte, et la note s'y tait (C8-12)."""
    t, notes = got.table("Rapports"), got.notes()
    if t is None:  # pas de dossier de rapports : comment en faire, une fois
        return got.draw("handmade/systeme/simulations.html", t=None) if notes else None
    chosen = str(got.query.get("fichier") or "")
    reports = []
    for x in got.lines("Rapports"):
        name = x.text("fichier")
        folder, _, base = name.rpartition("/")
        ext = base.rpartition(".")[2].lower()
        reports.append({"name": base, "folder": folder, "path": name, "href": (x.get("fichier") or {}).get("href", ""),
                        "kind": REPORT_KINDS.get(ext, ext), "when": x.get("modifié"), "on": name == chosen})
    return got.draw("handmade/systeme/simulations.html", t=t, reports=reports, chosen=chosen,
                    reading=got.first("prose"), notes=notes)


# ── Moteur des modèles ────────────────────────────────────────────────────


def _slots(busy: int, total: int) -> list[str]:
    """Les créneaux d'un fournisseur en cases : occupés d'abord (au plus douze montrées)."""
    return ["busy" if i < busy else "free" for i in range(min(total, 12))]


def passerelle(got: Got) -> Markup | None:
    """Système › Moteur des modèles : le bandeau, les chiffres, chaque fournisseur, qui sert quoi."""
    stats, notes = got.stats(), got.notes()
    if stats is None:  # aucun modèle configuré : sa note
        return got.draw("handmade/systeme/passerelle.html", band=_band(notes[0]["tone"], notes[0]["text"],
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
                "last_failure": relative_fr(profile.last_failure_at, now) if profile.last_failure_at else "",
                "last_role": names.role(profile.last_failure_role) if profile.last_failure_role else ""}})
    # un rôle sans fournisseur se lit à sa clé (la colonne « nom technique ») autant qu'à sa cellule : un rôle
    # facultatif (``OPTIONAL_ROLES``, rendre naturel) sans modèle est coupé, par choix — aucun appel n'échoue, il se
    # range à part, sans alarme ; tout autre rôle que personne ne sert garde la sienne
    served: dict[str, list[dict[str, str]]] = defaultdict(list)
    unserved, cut = [], []
    effort_of = getattr(gateway, "effort_of", None)
    for row in roles_raw.rows:
        label, tech, by = (_cells(row) + [None] * 3)[:3]
        role = {"label": str(label), "tech": tech.text if isinstance(tech, Text) else str(tech),
                "said": by.text if isinstance(by, Text) else str(by), "effort": ""}
        # l'effort réglé pour ce rôle (ADR 0285) se lit sur sa pastille ; celui de la fiche est celui du fournisseur
        effort, own = effort_of(role["tech"]) if callable(effort_of) else ("", False)
        if own:
            role["effort"] = EFFORT_LABELS.get(effort, effort)
        if not (isinstance(by, Text) and by.kind == "muted"):
            served[role["said"]].append(role)
        elif role["tech"] in OPTIONAL_ROLES:
            cut.append(role)
        else:
            unserved.append(role)
    waiting = sum(p["waiting"] for p in providers)
    band = _band("danger", f"{plural(len(unserved), 'rôle', 'rôles')} sans fournisseur : "
                           f"{', '.join(r['label'] for r in unserved)}. Chaque appel "
                           f"{agree(len(unserved), 'de ce rôle', 'de ces rôles')} échoue.",
                 f"{PREFIX}/reglages/roles", "Qui sert quoi") if unserved else \
        _band("warn", f"{plural(waiting, 'appel attend', 'appels attendent')} un créneau libre.") if waiting else None
    return got.draw("handmade/systeme/passerelle.html", band=band, stats=stats, providers_t=providers_t,
                    providers=providers, roles_t=roles_t, served=sorted(served.items()), unserved=unserved, cut=cut,
                    notes=[n for n in notes if n.get("tone") != "danger"])


# ── Appels et coûts ───────────────────────────────────────────────────────

#: les sous-onglets d'Appels et coûts ; une page de la liste des appels ouvre la sienne
CALL_PANES = ("calls-split", "calls-all", "calls-days")


def _usage_rows(got: Got, title: str, label: str) -> list[dict[str, Any]]:
    """Un agrégat par rôle, modèle ou fournisseur, lu dans le tableau ``title`` de la vue (``label`` : sa première
    colonne ; sa clé, si elle en a une à part, dans « <label> (clé) ») : deux barres (son coût ; ses appels, leurs
    échecs en bout), ses chiffres ; le plus coûteux d'abord, puis le plus appelé. Le coût se relit dans ses mots
    (``number``) : rien ne se recalcule."""
    table = got.raw_table(title)
    rows = []
    for _row, c in raw_rows(table) if table is not None else ():
        rows.append({"name": str(c[label]), "tech": str(c.get(f"{label} (clé)") or c[label]),
                     "usd": number(str(c["coût"])) or 0.0, "cost": str(c["coût"]), "calls": int(c["appels"]),
                     "failures": int(c["échecs"]), "cache": str(c["part du cache"]), "latency": str(c["durée moy."]),
                     "tokens": f"{c['entrée']} → {c['sortie']}"})
    cost_top = max((r["usd"] for r in rows), default=0.0)
    calls_top = max((r["calls"] for r in rows), default=0) or 1
    for r in rows:
        r.update(w=round(100 * r["usd"] / cost_top, 1) if cost_top else 0.0, cw=round(100 * r["calls"] / calls_top, 1),
                 fw=round(100 * r["failures"] / calls_top, 1))
    return sorted(rows, key=lambda r: (-r["usd"], -r["calls"], r["tech"]))


def _days(got: Got) -> dict[str, Any] | None:
    """La période choisie en barres, une par jour, le premier jour entamé compris (huit, quinze ou trente et une) :
    le coût en haut (s'il y en a), les appels en bas, leurs échecs en rouge. Les jours et leur coût sont ceux du
    graphe de la vue (« Coût par jour » : de ``since`` à ``until``), les appels et les échecs ceux de son tableau
    « Par jour » (sa colonne repliée « jour (clé) ») : la période ne se recalcule pas ici. Rien sans le graphe."""
    chart = next((b for b in got.raw if isinstance(b, Chart) and b.title.startswith(CALLS_CHART_TITLE)), None)
    if chart is None or chart.since is None or chart.until is None:
        return None
    tz = got.ui.tz

    def day(at: int) -> date:
        return datetime.fromtimestamp(at / US, tz).date()

    first, today = day(chart.since), day(chart.until)
    days = [first + timedelta(days=i) for i in range((today - first).days + 1)]
    costs = {day(at): v for s in chart.series for at, v in s.points}
    table = got.raw_table(CALLS_DAYS_TITLE)
    counts = {str(c.get("jour (clé)")): (int(c["appels"]), int(c["échecs"]))
              for _row, c in (raw_rows(table) if table is not None else ())}
    got_days = [(costs.get(d, 0.0), *counts.get(d.strftime("%Y-%m-%d"), (0, 0))) for d in days]
    cost_top = max((cost for cost, _n, _f in got_days), default=0.0)
    calls_top = max((n for _c, n, _f in got_days), default=0) or 1
    cost_h, calls_h = (40.0, 20.0) if cost_top else (0.0, 44.0)
    bars = []
    for i, (d, (cost, n, failed)) in enumerate(zip(days, got_days, strict=True)):
        h = round(cost_h * cost / cost_top, 2) if cost_top else 0.0
        ch = round(calls_h * n / calls_top, 2)
        fh = round(calls_h * failed / calls_top, 2)
        base = cost_h + 4 + calls_h if cost_top else calls_h
        bars.append({"x": i * 10 + 1.5, "cost_y": round(cost_h - h, 2), "cost_h": h, "calls_y": round(base - ch, 2),
                     "calls_h": ch, "fail_y": round(base - fh, 2), "fail_h": fh, "n": n, "failed": failed,
                     "cost": money_fr(cost), "day": short_day_fr(d),
                     "label": str(d.day), "today": d == today, "monday": d.weekday() == 0})
    return {"bars": bars, "width": 10 * len(bars), "cost_top": money_fr(cost_top) if cost_top else "",
            "calls_top": calls_top,
            "height": round(cost_h + 4 + calls_h, 2) if cost_top else calls_h, "cost_h": cost_h,
            "split": cost_h + 2 if cost_top else 0, "has_cost": bool(cost_top),
            "total": money_fr(sum(costs.values())), "calls": sum(n for _c, n, _f in got_days),
            "failures": sum(f for _c, _n, f in got_days), "today_failures": got_days[-1][2] if got_days else 0}


def _call(line: Line) -> dict[str, Any]:
    outcome = line.get("issue") or {}
    failed = outcome.get("tone") == "danger" or line.tone == "danger"
    return {"when": line.get("quand"), "role": line.text("rôle"), "backend": line.text("fournisseur"),
            "model": line.text("modèle"), "wait": line.text("attente"), "took": line.text("durée"),
            "tokens": line.text("jetons"), "cost": line.text("coût"), "outcome": outcome, "failed": failed,
            "href": line.href}


def appels(got: Got) -> Markup | None:
    """Système › Appels et coûts : les échecs, les chiffres, la période choisie en barres ; où va le coût, tous les
    appels et le détail jour par jour en sous-onglets. Elle ne lit que les blocs de sa vue — ses chiffres, son graphe,
    ses tableaux par jour, par rôle, par modèle, par fournisseur, tous calculés une fois, sur la période qu'elle a
    choisie (``CALL_PERIOD``, au bout de la barre d'onglets) ; d'elle, la page ne reprend que les mots."""
    stats, all_t, notes = got.stats(), got.table(CALLS_ALL_TITLE), got.notes()
    if stats is None or all_t is None:  # pas de registre : sa note
        return got.draw("handmade/systeme/appels.html", off=notes) if notes else None
    chart = _days(got)
    if chart is None:
        return None
    _, period = call_period(got.query)
    roles = _usage_rows(got, CALLS_ROLES_TITLE, "rôle")
    split = [{"id": "calls-roles", "title": "Par rôle", "rows": roles},
             {"id": "calls-models", "title": "Par modèle",
              "rows": _usage_rows(got, CALLS_MODELS_TITLE, "fournisseur · modèle")},
             {"id": "calls-backends", "title": "Par fournisseur",
              "rows": _usage_rows(got, CALLS_BACKENDS_TITLE, "fournisseur")}]
    for g in split:
        g["cost"] = any(r["w"] for r in g["rows"])
    failing = sorted((r for r in roles if r["failures"]), key=lambda r: -r["failures"])
    band = None
    if chart["failures"]:
        worst = ", ".join(f"{r['name']} ({r['failures']})" for r in failing[:3])
        today = chart["today_failures"]
        band = _band("danger" if today else "warn",
                     f"{plural(chart['failures'], 'appel a échoué', 'appels ont échoué')} en {period}"
                     + (f", dont {num_fr(today)} aujourd'hui" if today else "")
                     + (f" — surtout : {worst}" if worst else "") + ".", "#calls-all", "Les voir")
    first = "calls-all" if got.query.get("page") else ""
    return got.draw("handmade/systeme/appels.html", off=None, band=band, stats=stats, chart=chart, split=split,
                    period=period, all_t=anchored(all_t, "calls-all"),
                    calls=[_call(x) for x in got.lines(CALLS_ALL_TITLE)], days_t=got.table(CALLS_DAYS_TITLE),
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
    places = got.table(PLACES_TITLE)
    return got.draw("handmade/systeme/stockage.html", band=band, bases=bases, kept=kept, tables=tables,
                    places=places, place_items=[{"name": x.text("nom"), "size": x.text("place"),
                                                 "what": x.text("ce qu'il garde"), "kept": x.get("sauvegarde") or {}}
                                                for x in got.lines(PLACES_TITLE)],
                    saves=(saves or {}).get("items", []), last=got.fields("La dernière sauvegarde"),
                    archives=archives, archive_items=[{"name": x.text("archive"), "size": x.text("taille"),
                                                       "when": x.get("écrite")} for x in got.lines("Archives")],
                    notes=got.notes(), saved=saves is not None)


# ── Gestes audités ────────────────────────────────────────────────────────


def _operation(got: Got, line: Line, raw: Mapping[str, Any]) -> dict[str, Any]:
    at = instant(raw.get("quand"))
    outcome = line.get("issue") or {}
    seqs = [s.strip() for s in line.text("événements").split(",") if s.strip().isdigit()]
    return {"at": at, "hm": _hm(got, at), "when": line.get("quand"), "action": line.text("action"),
            "by": line.text("par"), "from": line.text("depuis"), "on": None if blank(line.get("sur")) else line.get("sur"),
            "outcome": outcome, "key": line.text("action (clé)"), "subject": "" if blank(line.get("sur (clé)")) else line.text("sur (clé)"),
            "href": line.href,
            "events": [{"n": s, "href": f"{PREFIX}/evenement/{s}"} for s in seqs]}


def operations(got: Got) -> Markup | None:
    """Système › Gestes audités : un fil jour par jour, qui a fait quoi, d'où, sur quoi, avec quelle issue."""
    t = got.table(OPERATIONS_TITLE)
    if t is None:
        return None
    items = [_operation(got, x, r) for x, r in zip(got.lines(OPERATIONS_TITLE), raw_lines(got, t), strict=False)]
    outcomes = Counter((x["outcome"].get("text", ""), x["outcome"].get("tone", "")) for x in items)
    who = Counter(x["by"] for x in items)
    return got.draw("handmade/systeme/operations.html", t=t, days=by_day(got, items),
                    outcomes=[{"text": k, "tone": tone, "n": n} for (k, tone), n in outcomes.most_common() if k],
                    who=[{"name": k, "n": n} for k, n in who.most_common()], shown=len(items))


# ── Toutes les vues ───────────────────────────────────────────────────────


def _groups(views: Sequence[dict[str, Any]], key: str, labels: Mapping[str, str], order: Sequence[str] = (),
            hrefs: Mapping[str, str] | None = None, ids: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    """Les vues rangées par ``key``, un groupe chacun : son nom, son lien (``hrefs``), son ancre (``ids``)."""
    by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for v in views:
        if v[key]:
            by[v[key]].append(v)
    rank = {k: i for i, k in enumerate(order)}
    keys = sorted(by, key=lambda k: (rank.get(k, len(rank)), labels.get(k, k).casefold()))
    return [{"key": k, "label": labels.get(k, k), "href": (hrefs or {}).get(k, ""), "id": (ids or {}).get(k, ""),
             "views": sorted(by[k], key=lambda v: v["title"].casefold())} for k in keys]


def vues(got: Got) -> Markup | None:
    """Système › Toutes les vues : par destination, sur les fiches, par faculté (chacune à son ancre, ``views_of``), et
    les cachées."""
    raw = got.raw_table("Ce que chaque faculté montre")
    if raw is None:
        return None
    dests = {d.key: d.label for g in (got.ui.deps.navigation or ()) for d in g.items}
    views = []
    for row in raw.rows:
        ref, fac, section, subject, hidden = (_cells(row) + [None] * 5)[:5]
        title = ref.text if isinstance(ref, Ref) else str(ref)
        views.append({"title": title, "href": render.href(ref, got.ui.env()) if isinstance(ref, Ref) else "",
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
    # l'ancre de chaque faculté dans « Par faculté » : le lien « Ses vues » de Contributions y mène (``views_of``)
    anchors = {v["faculty"]: VIEWS_ANCHOR + v["owner"] for v in views if v["owner"]}
    shown = [v for v in views if not v["hidden"]]
    panes = [
        {"id": "views-dest", "title": "Par destination", "lede": "Les onglets de chaque destination de la console : "
         "une vue de faculté y prend place à côté des pages de la console.",
         "groups": _groups(shown, "section", dests, list(dests), {k: f"{PREFIX}/{k}" for k in dests})},
        {"id": "views-subject", "title": "Sur les fiches", "lede": "Les onglets de la fiche d'un objet (une personne, "
         "un mail, un projet…).", "groups": _groups(shown, "subject", subjects)},
        {"id": "views-faculty", "title": "Par faculté", "lede": "Ce que chaque faculté montre d'elle, et où.",
         "groups": _groups(views, "faculty", {}, ids=anchors), "where": True},
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
    return got.draw("handmade/systeme/vues.html", panes=[p for p in panes if p["n"]], total=len(views),
                    faculties=len(owners), places=len({v["section"] for v in shown if v["section"]}),
                    subjects=len(subjects), hidden=sum(1 for v in views if v["hidden"]))


def _subject_label(got: Got, kind: str) -> str:
    spec = got.ui.inspection.subject(kind)
    return getattr(spec, "label", "") or kind


# ── Diagnostic avancé ─────────────────────────────────────────────────────

#: la tranche d'une faculté, en JSON, montrée jusqu'à tant de caractères
SLICE_MAX = 12_000
#: le titre que la console donne au repli d'une tranche : « faculté · modifiée au n° N » (``inspector/pages/system.py``,
#: ``etat`` : les deux changent ensemble, ou la page retombe sur le repli)
SLICE_TITLE = re.compile(r"^(?P<owner>.+?) · modifiée au n° (?P<seq>\d+)$")
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
    tranche ; « Reconstruire » si elle est corrompue)."""
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
                      "tainted": tainted.get(owner), "age": head - s["seq"] if s["seq"] else None,
                      "rebuild": owner in tainted and rebuildable(ui.kernel, owner)})
    panes.sort(key=lambda p: p["label"].casefold())
    recent = sorted(panes, key=lambda p: -p["seq"])
    notes = got.notes()
    note = next((n for n in notes if n.get("tone") == "danger"), None)
    return got.draw("handmade/systeme/etat.html", panes=panes, recent=recent, head=head,
                    band=_band("danger", note["text"]) if note else None,  # la commande y est (``tainted_said``)
                    total=sum(len(p["facts"]) for p in panes),
                    errors=sum(1 for p in panes for f in p["facts"] if f["error"]),
                    csrf=getattr(got.forms, "csrf", ""), back=_back(got, "systeme/etat"), journal=_journal(got))


# ── Processus, File de sortie, Santé générale ─────────────────────────────

#: l'ordre des états, du plus urgent au plus calme, et ce que chacun dit
STATES = (("ko", "en échec"), ("stumbling", "a trébuché"), ("held", "retenu"), ("running", "en cours"),
          ("ok", "passé"), ("never", "pas encore exécuté"))


def _state(sched: Any, name: str, running: set[str], now: int) -> str:
    consecutive = sched.consecutive.get(name, 0)
    if consecutive >= health_m.PROCESS_FAILURES_MAX:
        return "ko"
    if consecutive:
        return "stumbling"
    if sched.held(name, now):
        return "held"
    if name in running:
        return "running"
    return "ok" if sched.runs.get(name, 0) else "never"


def processes(got: Got) -> tuple[Markup, list[Any]] | None:
    """Système › Processus : ce qui échoue d'abord (« Réessayer maintenant » sur ce qui est en échec), puis une carte
    par faculté ; l'historique à la console."""
    table = got.raw_table()
    if table is None:
        return None
    ui = got.ui
    sched, now = ui.kernel.scheduler, ui.now()
    running = set(sched.running())
    rows = []
    for spec in sched.specs:
        nd = render.dated(sched.due(spec.name))  # l'échéance retenue (recul et garde compris), pas ``next_due``
        last = sched.last_run(spec.name)
        error_at, error = sched.last_error.get(spec.name, (0, ""))
        state = _state(sched, spec.name, running, now)
        held = sched.held(spec.name, now)  # une rafale retenue, même sur un processus en échec
        rows.append({
            "name": ui.names.process(spec.name), "tech": spec.name, "state": state,
            "faculty": ui.names.faculty(spec.owner), "lane": names.process_lane(spec.lane),
            "runs": sched.runs.get(spec.name, 0), "failures": sched.failures.get(spec.name, 0),
            "consecutive": sched.consecutive.get(spec.name, 0),
            "last": relative_fr(last, now) if last else "jamais",
            "next": "en cours" if spec.name in running else
            relative_fr(nd, now) if nd is not None and nd > now else "dès que possible" if nd is not None
            else "à un événement" if spec.wake_on else "rien de prévu",
            "error": names.detail(error) if error else "",
            "error_at": relative_fr(error_at, now) if error_at else "",
            # « Réessayer maintenant » : en échec, pas en cours, pas retenu pour une rafale (``Scheduler.retry_now``
            # refuse les autres) ; en échec et retenu, la ligne dit pourquoi il n'a pas le bouton
            "retry": state in ("ko", "stumbling") and spec.name not in running and not held, "held": held,
        })
    order = {key: i for i, (key, _) in enumerate(STATES)}
    said = dict(STATES)
    for r in rows:
        r["said"] = said[r["state"]]
    trouble = sorted((r for r in rows if r["state"] in ("ko", "stumbling", "held")),
                     key=lambda r: (order[r["state"]], -r["consecutive"], r["name"]))
    by: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by.setdefault(r["faculty"], []).append(r)
    faculties = [{"name": name, "rows": sorted(items, key=lambda r: (order[r["state"]], r["name"].casefold())),
                  "trouble": sum(1 for r in items if r["state"] in ("ko", "stumbling", "held"))}
                 for name, items in by.items()]
    faculties.sort(key=lambda f: (not f["trouble"], f["name"].casefold()))
    counts = [{"key": key, "label": label, "count": sum(1 for r in rows if r["state"] == key)} for key, label in STATES]
    total = len(rows) or 1
    left = 0.0
    for c in counts:
        c["x"], c["w"] = f"{100 * left / total:.3f}%", f"{100 * c['count'] / total:.3f}%"
        left += c["count"]
    listed = render.block(table, got.env, got.query)
    as_table = "?" + urlencode({**got.query, f"vue_{listed['id']}": "table"})
    rest = [b for b in got.raw if b is not table and not isinstance(b, Stats)]
    return Markup(env.get_template("handmade/systeme/processes.html").render(
        total=len(rows), counts=[c for c in counts if c["count"]], trouble=trouble, faculties=faculties,
        failures=sum(r["failures"] for r in rows), as_table=as_table, csrf=getattr(got.forms, "csrf", ""),
        back=_back(got, "systeme/processus"))), rest


#: les parts d'une barre, en mots : les colonnes du tableau « Par sorte » de la console, qui les compte
SEGMENTS = {"done": "parti", "route": "en route", "stuck": "à traiter", "seen": "vu, laissé"}
#: la rangée des états de la console, qui compte chacun
STATES_NAV = "État"


def _segments(parts: Mapping[str, int]) -> list[dict[str, Any]]:
    """Une barre empilée, de gauche à droite : parti, en route, à traiter, vu (en % du total)."""
    total = sum(parts.get(k, 0) for k in SEGMENTS) or 1
    out, left = [], 0.0
    for key in SEGMENTS:
        n = parts.get(key, 0)
        if n:
            out.append({"key": key, "x": round(100 * left / total, 2), "w": round(100 * n / total, 2), "n": n})
            left += n
    return out


def _said(c: Any) -> str:
    """Le texte d'une cellule déclarée (un ``Text``, un ``Badge``, un texte) ; rien pour « — »."""
    said = str(getattr(c, "text", c) if c is not None else "").strip()
    return "" if said == "—" else said


def outbox(got: Got) -> Markup | None:
    """Système › File de sortie, dessinée : à quoi elle sert et où en est ce qui part (une ligne qui va du journal au
    départ), ce qui est à traiter (avec ses boutons), ce qui part par sorte, les derniers départs. Tout se lit dans
    les blocs de la console (``inspector/pages/system.py::sorties``) : la rangée des états et ses comptes, la page de
    départs, les lignes à traiter, le tableau par sorte — leurs tailles, leurs tris et leurs pages sont les siens."""
    ui, query, forms = got.ui, got.query, got.forms
    now = ui.now()
    nav = next((b for b in got.raw if isinstance(b, Nav) and b.title == STATES_NAV), None)
    shown_nav = got.nav(STATES_NAV)
    recent_t, todo_t, kinds_t = (got.raw_table(t) for t in (OUTBOX_RECENT_TITLE, OUTBOX_TODO_TITLE, OUTBOX_KINDS_TITLE))
    shown_recent, shown_todo = got.table(OUTBOX_RECENT_TITLE), got.table(OUTBOX_TODO_TITLE)
    if nav is None or shown_nav is None or recent_t is None or todo_t is None or kinds_t is None \
            or shown_recent is None or shown_todo is None:
        return None
    keyed = [(dict(item.href.params).get("etat", ""), item) for item in nav.items]
    counts = {k: int(item.count or 0) for k, item in keyed if k}
    everything = next((item for k, item in keyed if not k), None)
    asked = str(query.get("etat", ""))[:40]
    # l'état filtré : la puce allumée ; aucune, et « tout » éteint : un état connu que la file n'a pas
    status = next((k for k, item in keyed if k and item.active),
                  "" if everything is None or everything.active else asked)

    def when(c: Any) -> str:
        at = instant(c)
        return relative_fr(at, now) if at else ""

    def named(cells: Mapping[str, Any]) -> tuple[str, str]:
        effect = _said(cells.get("effet (clé)"))
        name, action = ui.names.effect(effect).name, _said(cells.get("action"))
        return effect, f"{name} : {action}" if action else name

    back = _back(got, "systeme/sorties")
    families = []
    kinds = [cells for _row, cells in raw_rows(kinds_t)]
    for key, title in EFFECT_FAMILIES:
        rows = []
        for cells in kinds:
            effect = _said(cells.get("effet (clé)"))
            fam, name, what = ui.names.effect(effect)
            if fam != key:
                continue
            parts = {k: int(cells.get(label) or 0) for k, label in SEGMENTS.items()}
            segments = _segments(parts)
            rows.append({"name": name, "what": what, "total": int(cells.get("départs") or 0), "stuck": parts["stuck"],
                         "segments": segments,
                         "bar": ", ".join(f"{SEGMENTS[g['key']]} {g['n']}" for g in segments),
                         "last": when(cells.get("dernier départ"))})
        if rows:
            families.append({"title": title, "rows": rows})
    stuck = []
    for _row, cells in raw_rows(todo_t):
        state = cells.get("état")
        _effect, name = named(cells)
        st = getattr(state, "key", "")
        stuck.append({"key": _said(cells.get("clé")), "seq": getattr(cells.get("n°"), "key", ""), "name": name,
                      "to": _said(cells.get("à qui")), "text": _said(cells.get("quoi")),
                      "when": when(cells.get("quand")), "state": _said(state).capitalize(),
                      "tone": getattr(state, "tone", "") or "warn", "hint": _said(cells.get("que faire")),
                      "error": _said(cells.get("erreur")), "retry": st not in OUTBOX_SEEN_ONLY})
    recent = []
    for _row, cells in raw_rows(recent_t):
        state = cells.get("état")
        effect, name = named(cells)
        recent.append({"seq": getattr(cells.get("n°"), "key", ""), "name": name, "when": when(cells.get("quand")),
                       "state": _said(state).capitalize(), "tone": getattr(state, "tone", ""),
                       "plain": getattr(state, "key", "") == "done", "attempts": int(cells.get("essais") or 0),
                       "error": _said(cells.get("dernière erreur")), "tech": effect})
    stuck_total = sum(counts.get(s, 0) for s in OUTBOX_PROBLEMS)
    stuck_tone = "danger" if counts.get("failed") or counts.get("orphan") else "warn" if stuck_total else "ok"
    return Markup(env.get_template("handmade/systeme/sorties.html").render(
        tone=stuck_tone, stuck_total=stuck_total, route=sum(counts.get(s, 0) for s in OUTBOX_ROUTE),
        done=counts.get("done", 0), seen=counts.get("seen", 0),
        attempts=MAX_ATTEMPTS, base_s=int(RETRY_BASE_S), max_min=int(RETRY_MAX_S // 60),
        stale_min=int(STALE_AFTER_S // 60), csrf=getattr(forms, "csrf", ""), back=back,
        unknown=bool(asked and not status), chosen_total=int(shown_todo.get("count") or 0),
        stuck_pager=shown_todo["pager"], stuck=stuck, families=families,
        chips=[{"label": c["text"], "href": c["href"], "n": c["count"], "on": c["active"], "tone": c["tone"]}
               for c in shown_nav["items"]],
        recent=recent, pager=shown_recent["pager"], filtered=OUTBOX_LABELS.get(status, status)))


#: ce que tient chaque projection, en mots (la console n'a que leur nom technique, montré à côté) ; une garde
#: (``tests/architecture/test_console_labels.py``) veut un nom pour chaque projection du registre composé
PROJECTIONS = {
    "memory_chunks": "Sa mémoire, découpée pour la recherche",
    "memory_extraction_queue": "Ce que sa mémoire doit encore relire",
    "memory_items": "Ses souvenirs et ses croyances",
    "memory_life": "Ce qu'elle sait de la vie des autres",
    "memory_readings": "Ses lectures",
    "memory_told": "Qui a entendu quoi",
    "project_items": "Le registre des projets (tickets, listes de suivi)",
    "project_doc_pages": "La documentation des projets (pages, versions)",
    "received_files": "Les pièces qu'on lui envoie",
    "shared_files": "Les fichiers qu'elle envoie",
    "social_relations": "Ses relations",
    "strands": "Ses fils de travail (mode pro)",
    "thread_efforts": "L'effort de réflexion forcé (conversations, fils de travail)",
    "thread": "Le fil des conversations",
}


def _probe(got: Got) -> dict[str, Any] | None:
    """Ce que publie la sonde (``/health``), tel que la vue le montre dans son repli : son état, ou sa phase hors
    marche, et si elle est prête ; rien si la vue ne le dit plus."""
    fold = next((b for b in got.raw if isinstance(b, Disclosure) and b.title == diagnostics.PROBE_FOLD), None)
    code = next((x for x in (fold.items if fold is not None else ()) if isinstance(x, Code)), None)
    try:
        said = json.loads(code.text) if code is not None else None
    except ValueError:
        return None
    return said if isinstance(said, dict) and "status" in said else None


def _tile(line: Line) -> dict[str, Any]:
    """Une tuile, lue sur une ligne des tableaux de la vue : son nom, son état (les mots et le ton de l'étiquette), son
    constat, son détail, sa clé (repliée) et la page de son diagnostic."""
    state = line.get("État") or {}
    key = line.text("clé")
    return {"name": line.text("Contrôle"), "key": key, "state": str(state.get("text") or ""),
            "tone": str(state.get("tone") or "warn"), "summary": line.text("Constat"),
            "detail": next((str(d.get("text") or "") for d in line.rest if d.get("t") == "code"), ""),
            # les projections sont dessinées plus bas, sur la page même
            "href": "#sys-projections" if key == "projections" else line.href}


def health(got: Got) -> Markup | None:
    """Système › Santé générale : le verdict, les tuiles (les dix contrôles, puis les sauvegardes et les anomalies),
    ses projections, les replis techniques — tout lu dans les blocs de sa vue (``inspector/pages/diagnostics.py``) :
    le rapport de santé ne s'y calcule qu'une fois."""
    ui = got.ui
    probe, proj = _probe(got), projections(got)
    if probe is None or proj is None:
        return None
    # les problèmes, en panne d'abord, puis ce qui va : dans l'ordre de la vue
    lines = [*got.lines(diagnostics.PROBLEMS_TITLE), *got.lines(diagnostics.HEALTHY_TITLE)]
    tiles = [_tile(line) for line in lines]
    problems = [t for t in tiles if t["tone"] != "ok"]
    # le verdict, celui de la vue : l'état que publie la sonde (sa phase hors marche), et l'état de chaque tuile
    title, tone = diagnostics.verdict(str(probe["status"]), [key_of(line.get("État")) for line in lines],
                                      ui.her_name())
    technical = [b for b in got.raw if isinstance(b, Disclosure)
                 and b.title.split(" (")[0] not in (diagnostics.HEALTHY_TITLE, diagnostics.TECHNICAL_FOLD)]
    folds = drawn_blocks.page(ui, technical, got.query)
    # « points vérifiés », pas « contrôles » : les tuiles de la console en sont, comme dans ses compteurs
    return Markup(env.get_template("handmade/systeme/health.html").render(
        title=title, her=ui.her_name(), tone=tone, ready=bool(probe.get("ready")), checks=tiles,
        all_clear=diagnostics.all_clear(len(tiles)),
        problems=len(problems), failed=sum(1 for t in problems if t["tone"] == "danger"),
        healthy=len(tiles) - len(problems), snapshot=ui.when_long(ui.now()), proj=proj, folds=folds or ""))


def _arc(share: float) -> str:
    """L'arc rempli d'une jauge en demi-cercle (centre 60,60, rayon 50), de 0 à 1 ; vide : rien à tracer."""
    share = max(0.0, min(1.0, share))
    if share <= 0:
        return ""
    angle = math.pi * (1 - share)
    return f"M10,60 A50,50 0 0 1 {60 + 50 * math.cos(angle):.1f},{60 - 50 * math.sin(angle):.1f}"


def projections(got: Got) -> dict[str, Any] | None:
    """Ses projections, lues dans les tableaux de la vue (« Projections », « Quarantaine », « Vues lentes ») : combien
    sont à jour (une jauge), où chacune en est du journal, ce qui est en quarantaine, et les vues lentes de la
    console. Rien si la vue ne les dit plus."""
    listed = got.raw_table(diagnostics.PROJECTIONS_TITLE)
    if listed is None:
        return None
    head = got.ui.kernel.mind.head
    held = got.raw_table(diagnostics.QUARANTINE_TITLE)
    quarantine = [{"tech": str(cells.get("Projection")), "seq": getattr(cells.get("Événement"), "key", ""),
                   "error": getattr(cells.get("Erreur"), "text", "")[:300]}
                  for _row, cells in (raw_rows(held) if held is not None else ())]
    stuck = Counter(q["tech"] for q in quarantine)
    in_transaction = diagnostics.TIERS[Tier.T0]
    rows = []
    for _row, cells in raw_rows(listed):
        tech, tier = str(cells.get("Projection")), str(cells.get("Niveau") or "")
        lag = cells.get("Retard")
        behind = max(0, lag) if isinstance(lag, int) and tier != in_transaction else 0
        n = stuck[tech]
        rows.append({
            "name": PROJECTIONS.get(tech, tech), "tech": tech, "version": cells.get("Version"),
            "faculty": str(cells.get("Faculté") or ""), "tier": tier, "behind": behind,
            "share": 100.0 if not behind or head <= 0 else round(100 * max(0, head - behind) / head, 1),
            "tone": "danger" if n else "warn" if behind else "ok",
            "state": plural(n, "événement en quarantaine", "événements en quarantaine") if n else
            plural(behind, "événement de retard", "événements de retard") if behind else "à jour"})
    rows.sort(key=lambda r: r["name"])
    up, total = sum(1 for r in rows if r["tone"] == "ok"), len(rows)
    behind = sum(r["behind"] for r in rows)
    deferred = sum(1 for r in rows if r["tier"] != in_transaction)
    slow_t = got.raw_table(diagnostics.SLOW_TITLE)
    slow = [(str(c.get("Vue")), int(c.get("Passages") or 0), int(c.get("Dernière (ms)") or 0),
             int(c.get("Pire (ms)") or 0)) for _row, c in (raw_rows(slow_t) if slow_t is not None else ())]
    worst = max((w for *_rest, w in slow), default=0)
    return {
        "rows": rows, "up": up, "total": total, "head": plural(head, "événement", "événements"),
        "arc": _arc(up / total if total else 1.0),
        "up_said": f"{plural(up, 'projection à jour', 'projections à jour')} sur {num_fr(total)}",
        "behind": behind, "behind_said": plural(behind, "événement à rattraper", "événements à rattraper"),
        "deferred": deferred,
        "deferred_said": f"{plural(deferred, 'différée', 'différées')}, {num_fr(total - deferred)} dans la transaction",
        "tone": "danger" if stuck else "warn" if up < total else "ok",
        "quarantine": [{**q, "name": PROJECTIONS.get(q["tech"], q["tech"]), "href": f"{PREFIX}/evenement/{q['seq']}"}
                       for q in quarantine],
        "views": [{"name": k, "runs": plural(runs, "passage", "passages"), "last": last, "worst": w,
                   "share": round(100 * w / worst, 1) if worst else 0.0,
                   "last_share": round(100 * last / worst, 1) if worst else 0.0} for k, runs, last, w in slow],
        "slow_ms": SLOW_US // 1000}


TABS: dict[str, Any] = {
    "systeme/processus": Tab(processes, *STYLES),
    "systeme/sorties": Tab(outbox, *STYLES, panel=False),
    "systeme/sante": Tab(health, *STYLES, panel=False),
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
