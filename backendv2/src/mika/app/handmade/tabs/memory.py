"""Elle › Mémoire : ses onglets, chacun dans sa forme (ADR 0177).

- Souvenirs : une entrée par souvenir, son texte d'abord — la couleur de l'émotion qu'il porte, à qui il se rapporte,
  ce qu'il en reste —, en deux colonnes sur un grand écran ; le détail (qui l'a confié, d'où il vient) replié.
- Croyances : la même liste, chaque croyance avec sa confiance en avant (un chiffre et sa jauge) et son origine
  (on le lui a dit, elle l'a vu, elle le déduit) ; une croyance remplacée ou jointe à une autre s'estompe, celle qui
  la remplace le dit.
- Promesses : celles qui l'engagent encore d'abord, leur échéance à gauche (en retard : dit) ; puis, côte à côte,
  celles qu'elle a tenues et celles qu'elle a abandonnées.
- La vie des autres : un agenda — ce qui dure en ce moment, ce qui vient (le plus proche d'abord), ce qui est passé
  et comment ça a tourné —, chaque moment avec sa date en pavé de calendrier.
- Voir venir : ses attentes par sorte d'annonce, sur une échelle de « toujours juste » à « pile ou face » ; et qui
  tient ce qu'il annonce, tenus et manqués sur une même barre.
- Pièces reçues : la place en chiffres, puis en sous-onglets les pièces — une entrée chacune : sa sorte en icône, son
  nom vers sa fiche, qui l'a envoyée, ce qu'elle y a lu, ce qui s'y relie, la télécharger, la retirer (ADR 0205) — et
  la place de chacun, une jauge par personne, de la plus chargée à la moins chargée (ADR 0182).
- Fichiers envoyés (ADR 0205) : ce qu'elle a envoyé, à tout le monde — une entrée par fichier : sa sorte en icône,
  son nom vers sa fiche, pour qui, son origine, le message qui l'a emporté, son état ; le télécharger, le retirer.
- Consolidation : où en est la relecture, en une phrase et une bande de chiffres ; puis en sous-onglets les passages
  à reprendre (leur action sur leur ligne), ses relectures, les tris de la nuit, ses lectures relues la nuit (ce
  qu'elle en a retenu, et en détail les croyances que la même nuit a réunies ou confrontées) et l'état détaillé.

Souvenirs, croyances, promesses et moments viennent de la même liste de la faculté (``memory``) : leurs filtres, leur
pagination et leur bascule « Tableau » restent les siens ; ce qui distingue chacun se lit dans ses colonnes, et pour
un moment, dans ce que la faculté sait de lui (une situation qui dure, comment il a tourné). Un élément d'avant
(remplacé, fondu dans un autre, joint à un autre, démenti) s'estompe comme sa ligne dans la vue (son ton). L'état d'un
élément — son statut, sa sensibilité, son origine, la sorte et l'état d'un fichier — se lit dans la clé de son
étiquette (``Badge.key``), jamais dans ses mots : un libellé renommé dans la vue ne range rien ailleurs.

Chaque carte porte ses gestes de correction (ADR 0230), là où l'opératrice voit l'erreur : une promesse en cours,
« Marquer tenue » et « Abandonner » ; une situation qui dure, « C'est fini » ; un moment daté sans issue, « Comment ça
a tourné » (son choix) ; un souvenir ou une croyance encore actif, « Ce n'est pas vrai », sous « ⋯ ». Ce sont les
actions de la faculté (``faculties/memory/actions.py``), confirmées et auditées, l'élément dans un champ caché ; une
carte d'un statut d'avant n'en offre aucun. Rien n'efface son texte.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from markupsafe import Markup

from mika.app.handmade import MONTHS, WEEKDAYS
from mika.app.handmade.lists import forms_for, subject_key
from mika.app.handmade.tabs import (
    Got,
    Line,
    Tab,
    anchored,
    blank,
    gauge,
    instant,
    key_of,
    number,
    pairs,
    raw_lines,
    rest,
    subpanes,
    text,
    tiles,
)
from mika.app.handmade.tabs.thoughts import day_label
from mika.contracts import attachments as attachments_c
from mika.contracts import memory as memory_c
from mika.contracts import shares as shares_c
from mika.faculties.attachments import inspect as received
from mika.faculties.memory.inspect import DORMANT, ENDED, ONGOING, ORIGIN_FR
from mika.faculties.shares import inspect as sent
from mika.inspector import render
from mika.inspector.ui import PREFIX
from mika.kernel.frame import Frame
from mika.kernel.inspect import Ref, agree
from mika.vocab.privacy import Sensitivity

STYLES = ("handmade/memoire.css",)


# ── Ce que partagent les onglets ──────────────────────────────────────────


#: les clés (``Badge.key``) des étiquettes qui disent l'état ordinaire d'un élément retenu : actif, en cours, anodin
QUIET = frozenset({memory_c.ACTIVE_STATUS, memory_c.PENDING_STATUS, str(int(Sensitivity.ANODYNE))})


def _item(line: Line, body: str, *quiet: str, shown: Iterable[str] = ()) -> dict[str, Any]:
    """Ce que partagent un souvenir, une croyance, une promesse et un moment : leur texte, les étiquettes qui disent
    quelque chose (l'état ordinaire se tait, ``QUIET`` et les clés ``quiet`` que la page passe), leur numéro, leur
    origine, leur détail (``shown`` : les colonnes repliées que la page montre déjà)."""
    hush = QUIET | set(quiet)
    return {"text": line[body], "n": line.get("n°"), "href": line.href, "faded": line.tone == "muted",
            "tags": [b for b in (line.get("sensibilité"), line.get("statut"))
                     if not blank(b) and key_of(b) not in hush],
            "detail": rest(line, shown), "open": line.open}


def _detail(line: Line) -> dict[str, dict[str, Any]]:
    """Les faits du détail d'un élément retenu (« Détail » : qui l'a confié, ce qu'il remplace…)."""
    return pairs(next((d for d in line.detail if d.get("t") == "fields" and d.get("title") == "Détail"), None))


#: les gestes de correction d'une carte (ADR 0230), dans leur ordre : l'action de la faculté, et le champ caché qui
#: dit l'élément (son numéro)
GESTURES = {"memory.tenir": "promise", "memory.abandonner": "promise", "memory.finir": "event",
            "memory.issue": "event", "memory.dementir": "item"}
#: le bouton du formulaire d'un geste qui a un choix (son panneau porte déjà son titre)
CHOSEN = {"memory.issue": "Noter"}
#: les statuts (la clé de l'étiquette) d'un souvenir ou d'une croyance qu'elle tient encore pour vrai : actif, ou
#: actif qui dort
HELD = frozenset({memory_c.ACTIVE_STATUS, DORMANT})


def _number(raw: Mapping[str, Any]) -> str:
    """Le numéro d'un élément retenu : la cellule « n° » telle que la faculté l'a déclarée (un lien vers l'événement
    qui l'a noté) ; vide sinon."""
    ref = raw.get("n°")
    return ref.key if isinstance(ref, Ref) and ref.kind == "event" else ""


def _offers(raw: Mapping[str, Any], *actions: str) -> dict[str, Any]:
    """Ce qu'une carte offre de corriger : son numéro, les gestes qui ont un sens pour l'élément dans son état
    (``can``) ; ``_corrections`` y pose leurs formulaires."""
    return {"key": _number(raw), "can": actions, "acts": [], "more": []}


def _corrections(got: Got, items: list[dict[str, Any]]) -> None:
    """Les gestes de correction de chaque carte (ADR 0230) : les formulaires que la console prépare pour les actions de
    la faculté que la carte offre (``can``), l'élément dans leur champ caché et pour objet, chacun confirmé par la
    question de son action. En vue (``acts``) ; une action dangereuse (démentir) sous « ⋯ » (``more``). Une action
    que la faculté n'offre pas maintenant (``available``) n'en a aucun ; sans formulaires (un rendu hors d'une page),
    rien."""
    for action, field in GESTURES.items():
        keys = [x["key"] for x in items if action in x["can"]]
        if not keys:
            continue
        extra = {"button": CHOSEN[action]} if action in CHOSEN else {}
        prepared = forms_for(got.ui, got.forms, action, keys, got.query, fill=field, **extra)
        for x in items:
            form = prepared.get(x["key"]) if action in x["can"] else None
            if form is not None:
                x["more" if form.get("danger") else "acts"].append(form)


def _empty_or_none(got: Got, template: str) -> Markup | None:
    """Une liste que la faculté n'a pas pu lire (sa table n'existe pas encore) : sa note, dans la forme de la page ;
    une liste qui manque sans rien dire (un titre changé) : ses blocs."""
    notes = got.notes()
    return got.draw(template, t=None, notes=notes) if notes else None


# ── Souvenirs ─────────────────────────────────────────────────────────────


def _held(line: Line, item: Mapping[str, Any]) -> bool:
    """Un souvenir ou une croyance qu'elle tient encore pour vrai : il se dément ; un élément d'avant, ou vidé par
    l'oubli (estompé), non."""
    return not item["faded"] and key_of(line.get("statut")) in HELD


def _memory(line: Line, raw: Mapping[str, Any]) -> dict[str, Any]:
    emotion = line.get("émotion")
    item = _item(line, "souvenir", shown=("ce qu'il en reste", "émotion"))
    return {**item, "about": line.get("concerne"),
            "born": line.get("né"), "emotion": emotion if emotion and emotion.get("t") == "swatch" else None,
            "left": gauge(line.get("ce qu'il en reste")),
            **_offers(raw, *(("memory.dementir",) if _held(line, item) else ()))}


def souvenirs(got: Got) -> Markup | None:
    """Mémoire › Souvenirs : une entrée par souvenir, et ce qui s'y corrige."""
    table = got.table("Ses souvenirs")
    if table is None:
        return _empty_or_none(got, "handmade/memoire/souvenirs.html")
    items = [_memory(x, r) for x, r in zip(got.lines("Ses souvenirs"), raw_lines(got, table), strict=False)]
    _corrections(got, items)
    return got.draw("handmade/memoire/souvenirs.html", t=table, items=items, notes=got.notes())


# ── Croyances ─────────────────────────────────────────────────────────────


def _origin(said: Mapping[str, Any] | None, by: Mapping[str, Any] | None) -> dict[str, str] | None:
    """Son origine : sa sorte, la clé de l'étiquette de la colonne « origine » (``told``…) ; ses mots, ceux de la
    seule table de la faculté (``ORIGIN_FR``, chaque origine d'une croyance, « elle l'a lu » comprise) ; qui la lui a
    dite, le fait « dite par » de son détail (``by``). Une origine que la faculté ne nommerait pas garde les mots de la
    colonne, sans sorte."""
    if blank(said):
        return None
    kind = key_of(said)
    if kind not in ORIGIN_FR:
        return {"kind": "", "text": text(said), "who": ""}
    return {"kind": kind, "text": ORIGIN_FR[kind], "who": text(by, dash=False)}


def _belief(line: Line, raw: Mapping[str, Any]) -> dict[str, Any]:
    """Une croyance ; estompée comme sa ligne (``faded`` : remplacée, jointe à une autre, démentie, ou vidée par
    l'oubli)."""
    detail = _detail(line)
    item = _item(line, "croyance", shown=("née",))
    return {**item, "trust": gauge(line.get("confiance")),
            "origin": _origin(line.get("origine"), detail.get("dite par")), "about": line.get("concerne"),
            "born": line.get("née"), "replaces": detail.get("remplace"),
            **_offers(raw, *(("memory.dementir",) if _held(line, item) else ()))}


def croyances(got: Got) -> Markup | None:
    """Mémoire › Croyances : chacune avec sa confiance et son origine, et ce qui s'y corrige."""
    table = got.table("Ses croyances")
    if table is None:
        return _empty_or_none(got, "handmade/memoire/croyances.html")
    items = [_belief(x, r) for x, r in zip(got.lines("Ses croyances"), raw_lines(got, table), strict=False)]
    _corrections(got, items)
    return got.draw("handmade/memoire/croyances.html", t=table, items=items, notes=got.notes())


# ── Promesses ─────────────────────────────────────────────────────────────

#: le statut d'une promesse (la clé de son étiquette, le statut gardé) et sa place dans la page
PROMISE_STATES = {memory_c.PENDING_STATUS: "open", memory_c.HONORED: "kept", memory_c.DROPPED: "dropped"}


def _promise(line: Line, raw: Mapping[str, Any], now: int) -> dict[str, Any]:
    """Une promesse ; en cours (son statut gardé, ``pending``), elle se marque tenue ou s'abandonne."""
    status = key_of(line.get("statut"))
    state = PROMISE_STATES.get(status, "open")
    due = instant(raw.get("échéance"))
    item = _item(line, "promesse", *PROMISE_STATES, shown=("faite",))
    pending = status == memory_c.PENDING_STATUS and not item["faded"]
    return {**item, "state": state, "to": line.get("à qui"),
            "due": line.get("échéance") if due else None, "late": state == "open" and 0 < due < now,
            "made": line.get("faite"),
            **_offers(raw, *(("memory.tenir", "memory.abandonner") if pending else ()))}


def promesses(got: Got) -> Markup | None:
    """Mémoire › Promesses : celles qui l'engagent, puis celles qu'elle a tenues ou abandonnées ; et ce qui s'y
    corrige."""
    table = got.table("Ses promesses")
    if table is None:
        return _empty_or_none(got, "handmade/memoire/promesses.html")
    items = [_promise(x, r, got.env.now) for x, r in zip(got.lines("Ses promesses"), raw_lines(got, table),
                                                          strict=False)]
    _corrections(got, items)
    groups = {state: [x for x in items if x["state"] == state] for state in PROMISE_STATES.values()}
    return got.draw("handmade/memoire/promesses.html", t=table, items=items, groups=groups, notes=got.notes())


# ── La vie des autres ─────────────────────────────────────────────────────

WEEKDAYS_SHORT = tuple(d[:3] + "." for d in WEEKDAYS)


def _moment(frame: Frame, line: Line, raw: Mapping[str, Any]) -> dict[str, Any]:
    """Un moment, tel que la vue le dit — lu dans l'archive de la faculté : une situation qui dure encore, comment il
    a tourné, s'il se fête, même passé depuis longtemps. Son statut fini se tait (l'étiquette de la situation le dit
    déjà), et sa sensibilité personnelle, celle de la vie des autres ; estompé comme sa ligne (``faded`` : remplacé,
    ou vidé par l'oubli)."""
    at = instant(raw.get("quand"))
    situation = key_of(line.get("situation"))
    ongoing = situation == ONGOING
    item = _item(line, "moment", str(int(Sensitivity.PERSONAL)), memory_c.ENDED_STATUS)
    tags = [line["issue"]] if not blank(line.get("issue")) else []
    if not blank(line.get("chaque année")):
        tags.append({"text": "revient chaque année", "tone": "info"})
    if not blank(line.get("se fête")):
        tags.append(line["se fête"])
    if situation == ENDED:
        tags.append(line["situation"])
    date = frame.local(at) if at else None
    return {**item, "tags": tags + list(item["tags"]), "who": line.get("de qui"), "when": line.get("quand"),
            "at": at, "place": "current" if ongoing else "ahead" if at >= frame.now else "past",
            "day": {"d": date.day, "m": MONTHS[date.month - 1], "w": WEEKDAYS_SHORT[date.weekday()]} if date else None,
            "noted": line.get("noté"), **_offers(raw, *_moment_gestures(line, item, situation))}


def _moment_gestures(line: Line, item: Mapping[str, Any], situation: str) -> tuple[str, ...]:
    """Ce qui se corrige d'un moment encore suivi (son statut gardé, ``active``) : une situation qui dure se finit ;
    un moment daté qui n'a pas d'issue en reçoit une. Une date qui revient chaque année, une situation finie, un
    moment déjà tranché, remplacé ou vidé par l'oubli : rien."""
    if item["faded"] or key_of(line.get("statut")) != memory_c.ACTIVE_STATUS:
        return ()
    if situation == ONGOING:
        return ("memory.finir",)
    if not situation and blank(line.get("issue")) and blank(line.get("chaque année")):
        return ("memory.issue",)
    return ()


def moments(got: Got) -> Markup | None:
    """Mémoire › La vie des autres : ce qui dure, ce qui vient, ce qui est passé — chaque moment à sa date, et ce
    qui s'y corrige."""
    table = got.table("Ce qui se passe dans la vie des autres")
    if table is None:
        return _empty_or_none(got, "handmade/memoire/moments.html")
    frame = got.ui.kernel.mind.frame()
    items = [_moment(frame, x, r) for x, r in zip(got.lines("Ce qui se passe dans la vie des autres"),
                                                       raw_lines(got, table), strict=False)]
    _corrections(got, items)
    groups = [
        ("current", "En ce moment", "ce qui dure dans leur vie, depuis le jour où ça a commencé",
         sorted((x for x in items if x["place"] == "current"), key=lambda x: -x["at"])),
        ("ahead", "À venir", "le plus proche d'abord : elle y pense quand c'est proche",
         sorted((x for x in items if x["place"] == "ahead"), key=lambda x: x["at"])),
        ("past", "Passés", "elle en demande des nouvelles après",
         sorted((x for x in items if x["place"] == "past"), key=lambda x: -x["at"])),
    ]
    return got.draw("handmade/memoire/moments.html", t=table, items=items,
                    groups=[{"id": g, "title": title, "lede": lede, "items": xs}
                            for g, title, lede, xs in groups if xs],
                    notes=got.notes())


# ── Pièces reçues, place des pièces ──────────────────────────────────────

#: la sorte d'une pièce (la clé de son étiquette, celle du contrat) et son icône
PIECE_KINDS = {attachments_c.IMAGE: "image", attachments_c.AUDIO: "audio", attachments_c.FILE: "file"}


def _download(line: Line) -> dict[str, Any] | None:
    """Le lien « télécharger » d'un fichier encore là (« — » une fois retiré)."""
    got = line.get("télécharger")
    return got if (got or {}).get("t") == "link" else None


def _removals(got: Got, items: list[dict[str, Any]], action: str, question: Callable[[str], str]) -> None:
    """« Retirer » sur chaque fichier encore là (ADR 0205) : le formulaire que la console prépare pour l'action de sa
    faculté, le fichier pour objet, confirmé par son nom (``remove`` de l'entrée)."""
    prepared = forms_for(got.ui, got.forms, action, [x["key"] for x in items], got.query, title="Retirer",
                         button="Retirer")
    for x in items:
        if x["key"] in prepared:
            x["remove"] = {**prepared[x["key"]], "confirm": question(x["title"])}


def _piece(line: Line, raw: Mapping[str, Any]) -> dict[str, Any]:
    state = line.get("état")
    said = key_of(state)
    href = raw.get("nom")
    tied = int(number(line.get("liens")) or 0)
    links = render.href(Ref(href.kind, href.key, "", (("onglet", "liens"),))) if isinstance(href, Ref) else ""
    return {"key": subject_key(href, received.KIND), "title": line.text("nom"),
            "name": line["nom"], "from": line.get("de"), "kind": PIECE_KINDS.get(key_of(line.get("sorte")), "file"),
            "sort": line.text("sorte"), "size": line.text("taille"), "at": line.get("reçue"),
            "seen": None if blank(line.get("ce qu'elle y a lu")) else line.get("ce qu'elle y a lu"),
            "state": None if blank(state) or said == received.KEPT_STATE else state,
            "gone": said == received.GONE_STATE, "unread": said == received.UNREAD,
            "tied": tied, "links": links if tied else "", "download": _download(line)}


def recues(got: Got) -> Markup | None:
    """Mémoire › Pièces reçues : la place en chiffres ; en sous-onglets, une entrée par pièce (ce qu'elle y a lu en
    avant ; la télécharger, la retirer), puis la place de chacun, une jauge par personne. Une page plus loin d'une liste
    rouvre son sous-onglet."""
    table, by_person, facts = got.table("Pièces reçues"), got.table("Par personne"), got.fields("Place")
    if table is None or by_person is None or facts is None:
        return _empty_or_none(got, "handmade/memoire/recues.html")
    items = [_piece(x, r) for x, r in zip(got.lines("Pièces reçues"), raw_lines(got, table), strict=False)]
    _removals(got, items, received.REMOVE, received.removal_question)
    f = pairs(facts)
    holders = int(number(f.get("personnes")) or 0)
    people = [{"who": x["personne"], "href": x.href, "n": x.text("pièces"), "used": x.text("occupé"),
               "share": gauge(x.get("de sa place"))} for x in got.lines("Par personne")]
    band = {"t": "stats", "title": "", "items": [
        {"label": "Place de chacun", "value": f.get("place par personne") or {"t": "text", "text": "—"},
         "sub": "tous ses moyens de communication réunis"},
        {"label": "En tout", "value": f.get("en tout") or {"t": "text", "text": "—"},
         "sub": f"pour {text(f.get('personnes'))} {agree(holders, 'personne', 'personnes')}" if holders
         else "rien de gardé"}]}
    return got.draw("handmade/memoire/recues.html", t=anchored(table, "pieces-list"),
                    p=anchored(by_person, "pieces-place"), band=band, budget=text(f.get("place par personne")),
                    items=items, people=people, notes=got.notes())


# ── Fichiers envoyés ──────────────────────────────────────────────────────

#: la sorte d'un fichier envoyé (la clé de son étiquette, celle du contrat) et son icône
SENT_KINDS = {shares_c.IMAGE: "image", shares_c.FILE: "file"}


def _sent(line: Line, raw: Mapping[str, Any]) -> dict[str, Any]:
    state = line.get("état")
    said = key_of(state)
    return {"key": subject_key(raw.get("nom"), sent.KIND), "title": line.text("nom"), "name": line["nom"],
            "to": None if blank(line.get("pour")) else line.get("pour"),
            "kind": SENT_KINDS.get(key_of(line.get("sorte")), "file"), "sort": line.text("sorte"),
            "size": line.text("taille"), "at": line.get("quand"), "origin": line.get("origine"),
            "message": None if blank(line.get("message")) else line.get("message"),
            "state": None if blank(state) or said == sent.SENT_STATE else state,
            "gone": said == sent.GONE_STATE, "download": _download(line)}


def envoyes(got: Got) -> Markup | None:
    """Mémoire › Fichiers envoyés (ADR 0205) : une entrée par fichier qu'elle a envoyé, à tout le monde — pour qui,
    quand, son origine, le message qui l'a emporté, son état ; le télécharger, le retirer. La pagination de la
    faculté."""
    table = got.table("Fichiers envoyés")
    if table is None:
        return _empty_or_none(got, "handmade/memoire/envoyes.html")
    items = [_sent(x, r) for x, r in zip(got.lines("Fichiers envoyés"), raw_lines(got, table), strict=False)]
    _removals(got, items, sent.REMOVE, sent.removal_question)
    return got.draw("handmade/memoire/envoyes.html", t=table, items=items, notes=got.notes())


# ── Voir venir ────────────────────────────────────────────────────────────

#: l'écart quadratique moyen (Brier) d'une attente : 0, toujours juste ; 0,25, comme à pile ou face ; l'échelle
#: montrée va jusqu'à 0,5
BRIER_SCALE = 0.5
COIN = 0.25


def _calibration(line: Line) -> dict[str, Any]:
    brier = number(line.get("écart moyen (Brier)"))
    tone = "" if brier is None else "ok" if brier < 0.1 else "warn" if brier < COIN else "danger"
    return {"nature": line.text("sorte d'annonce"), "seen": line.text("constatés"),
            "brier": line.text("écart moyen (Brier)"),
            "x": None if brier is None else round(100 * min(brier, BRIER_SCALE) / BRIER_SCALE, 1), "tone": tone,
            "verdict": line.get("ce qu'elle en fait")}


def _teller(line: Line) -> dict[str, Any]:
    kept, missed = int(number(line.get("tenus")) or 0), int(number(line.get("reportés ou annulés")) or 0)
    total = kept + missed
    return {"who": line.text("qui annonce"), "kept": kept, "missed": missed,
            "split": round(100 * kept / total, 1) if total else 0.0,
            "worth": gauge(line.get("ce que vaut son annonce"))}


def voir_venir(got: Got) -> Markup | None:
    """Mémoire › Voir venir : ses attentes sur une échelle, et qui tient ce qu'il annonce."""
    expected, tellers = got.table("Ce qu'elle attendait"), got.table("Ce qu'elle apprend de qui annonce")
    if expected is None or tellers is None:
        return None
    return got.draw("handmade/memoire/voir_venir.html", expected=expected, tellers=tellers,
                    natures=[_calibration(x) for x in got.lines("Ce qu'elle attendait")],
                    people=[_teller(x) for x in got.lines("Ce qu'elle apprend de qui annonce")],
                    coin=round(100 * COIN / BRIER_SCALE, 1))


# ── Consolidation ─────────────────────────────────────────────────────────

#: les chiffres de « Ce qu'elle garde », et l'onglet où ils mènent
KEPT_TABS = {"Souvenirs": "souvenirs", "Croyances": "croyances", "Promesses en cours": "promesses"}
#: les curseurs de ses listes au journal (``faculties/memory/inspect.py``) : leur sous-onglet
CURSORS = (("avant", "consol-runs"), ("avant_nuits", "consol-nights"), ("avant_lectures", "consol-rereads"),
           ("reprises", "consol-queue"))


def _passage(line: Line) -> dict[str, Any]:
    acts = [d for d in line.rest if d.get("t") == "action"]
    return {"title": line["passage"], "state": line.get("état"), "cause": line.get("cause"),
            "since": line.get("depuis"),
            "tries": line.text("essais"), "next": line.get("prochaine reprise"), "acts": acts,
            "detail": [d for d in line.rest if d.get("t") != "action"], "open": line.open}


def _run(line: Line) -> dict[str, Any]:
    return {"when": line.get("quand"), "upto": line.get("relu jusqu'au"), "kept": line.text("retenus"),
            "outcome": line.get("issue"), "model": line.text("modèle"), "href": line.href,
            "failed": line.tone == "danger"}


def _night(line: Line) -> dict[str, Any]:
    return {"night": day_label(line.text("nuit")), "merges": line.text("fusions"), "pairs": line.get("fondu → gardé"),
            "when": line.get("quand"), "href": line.href, "detail": line.rest}


def _reread(line: Line) -> dict[str, Any]:
    return {"night": day_label(line.text("nuit")), "readings": line.text("lectures"), "pairs": line.text("paires"),
            "kept": line.text("retenus"), "upto": line.get("relues jusqu'au"), "model": line.text("modèle"),
            "when": line.get("quand"), "href": line.href, "detail": line.rest}


def consolidation(got: Got) -> Markup | None:
    """Mémoire › Consolidation : où en est la relecture, puis ses sous-onglets."""
    state, runs = got.fields("La consolidation"), got.table("Les dernières relectures")
    nights, rereads = got.table("Les tris de la nuit"), got.table("Ses lectures relues la nuit")
    if state is None or runs is None or nights is None or rereads is None:
        return None
    f = pairs(state)
    queue = got.table("Passages à reprendre")
    kept = tiles(got.stats("Ce qu'elle garde"))
    band = [{**s, "href": f"{PREFIX}/memoire/{KEPT_TABS[label]}"} for label, s in kept.items() if label in KEPT_TABS]
    waiting = text(f.get("messages pas encore relus")) or "0"
    band.append({"label": "Pas encore relus", "value": {"t": "text", "text": waiting, "kind": "num"},
                 "sub": "messages en attente",
                 "tone": ""})
    if queue is not None:
        band.append({"label": "À reprendre", "value": {"t": "text", "text": str(queue["count"] or 0), "kind": "num"},
                     "sub": "passages que la relecture n'a pas pu traiter", "tone": "warn" if queue["count"] else "",
                     "href": "#consol-queue"})
    first = next((pane for param, pane in CURSORS if got.query.get(param)), "")
    panes = subpanes([{"id": "consol-queue"}, {"id": "consol-runs"}, {"id": "consol-nights"},
                      {"id": "consol-rereads"}, {"id": "consol-state"}], first)
    return got.draw("handmade/memoire/consolidation.html", f=f, band={"t": "stats", "title": "", "items": band},
                    state=state, queue=queue, passages=[_passage(x) for x in got.lines("Passages à reprendre")],
                    runs=runs, run_items=[_run(x) for x in got.lines("Les dernières relectures")],
                    nights=nights, night_items=[_night(x) for x in got.lines("Les tris de la nuit")],
                    rereads=rereads, reread_items=[_reread(x) for x in got.lines("Ses lectures relues la nuit")],
                    panes=[p["id"] for p in panes], notes=got.notes())


TABS: dict[str, Any] = {
    "memoire/souvenirs": Tab(souvenirs, *STYLES),
    "memoire/croyances": Tab(croyances, *STYLES),
    "memoire/recues": Tab(recues, *STYLES),
    "memoire/envoyes": Tab(envoyes, *STYLES),
    "memoire/promesses": Tab(promesses, *STYLES),
    "memoire/moments": Tab(moments, *STYLES),
    "memoire/voir-venir": Tab(voir_venir, *STYLES),
    "memoire/consolidation": Tab(consolidation, *STYLES),
}
