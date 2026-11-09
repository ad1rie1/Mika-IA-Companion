"""Relations & échanges › Identités et moyens de communication : ses onglets, chacun dans sa forme (ADR 0177).

- **Moyens de communication** : un bandeau si des revendications attendent (il mène à la file « À valider »), une
  bande de chiffres (qui mène à la file et aux règles), puis une ligne par moyen de communication, en colonnes — par
  où et sa clé, ce que son canal prouve et la certitude, pour qui il parle (relié, propriétaire, ce qu'il revendique),
  ce qu'il ouvre en privé et en public.
- **Règles de divulgation** : une page de règles, pas un mur de tableaux — les quatre barres en chiffres ; ce que
  chaque canal peut prouver, sur une même échelle de certitude où se lisent les degrés et la barre ; le poids des
  preuves, pour et contre ; les rangs de proximité ; les propriétaires. La calibration ne se dit en bandeau que si
  elle est fausse.

Les identités à confirmer et les noms à relier n'ont plus de page ici : ils ne se décident que dans la file
« À valider » (ADR 0180), qui lit les vues de la faculté et met chaque ligne en forme par ``claim_entry`` et
``name_entry``. Les actions d'une revendication sont celles de la fiche du moyen de communication, sur leur propre
page (``/action/…``), proposées seulement quand la faculté les offre ; elles arrivent déjà orientées — la faculté
pré-remplit la personne visée et le nom démenti, l'adresse choisit la preuve (``?valeur.kind=``).

Les données restent celles de la faculté ``identity`` : ses filtres, sa pagination et ses formulaires aussi.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import quote, urlencode

from markupsafe import Markup

from mika.app.handmade.handles import CHANNELS
from mika.app.handmade.tabs import Got, Line, Tab, blank, number, pairs, text, tiles
from mika.app.handmade.tabs.people import person_of
from mika.contracts.identity import DENIED, VOUCHED
from mika.inspector.formview import PREFILL
from mika.inspector.pages.subjects import fiche_key
from mika.inspector.ui import PREFIX
from mika.runtime.operations import offered

STYLES = ("handmade/identites.css",)
#: d'où reviennent les actions ouvertes depuis la file (ADR 0180)
CLAIMS = f"{PREFIX}/approbations/identites"
#: verser une preuve sur un moyen de communication (s'en porter garant, démentir un nom)
EVIDENCE = "identity.preuve"


def handle_of(c: Mapping[str, Any] | None) -> str:
    """Le moyen de communication qu'une cellule nomme : la clé de la fiche où son lien mène."""
    return fiche_key(str((c or {}).get("href") or ""), "handle")


def _split(said: str) -> tuple[str, str]:
    """« authentifiée (session vérifiée) » : le mot, puis sa raison."""
    head, sep, tail = said.partition(" (")
    return (head.strip(), tail.rstrip(")").strip()) if sep else (said.strip(), "")


def _pct(value: float) -> float:
    return round(100 * max(0.0, min(1.0, value)), 2)


# ── Moyens de communication ───────────────────────────────────────────────


#: par où, en mots, sur la ligne d'un moyen de communication (son nom dit déjà s'il est un compte)
WHERE = {"web": "par le chat web", "mobile": "par le téléphone", "external": "par un canal extérieur"}


def _channel(said: str) -> str:
    return WHERE.get(said) or CHANNELS.get(said, (said or "par un canal inconnu",))[0]


def _means(line: Line) -> dict[str, Any]:
    handle = line.get("moyen de communication")
    key = handle_of(handle)
    who = line.get("parle pour")
    trust = line.get("confiance du canal") or {}
    short, why = _split(text(trust))
    claim = line.text("revendique")
    return {
        "handle": handle, "key": line.text("clé") or key, "channel": _channel(line.text("canal")),
        "trust": short, "trust_why": why, "tone": trust.get("tone") or "", "certainty": line.text("certitude"),
        "who": who, "linked": bool(person_of(who)) and person_of(who) != key,
        "owner": line.text("propriétaire") == "oui", "claim": "" if claim in ("", "—") else claim,
        "private": line.text("divulgation en privé"), "public": line.text("divulgation en public"),
        "first": None if blank(line.get("vue pour la première fois")) else line.get("vue pour la première fois"),
    }


def moyens(got: Got) -> Markup | None:
    """Identités › Moyens de communication : un bandeau si des revendications attendent, la bande de chiffres, une
    ligne par moyen de communication."""
    table, stats = got.table("Moyens de communication"), got.stats()
    if table is None or stats is None:
        return None
    s = tiles(stats)
    claims = s.get("revendications en attente", {})
    waiting = text(claims.get("value"))
    return got.draw("handmade/identites/annuaire.html", t=table, band=stats["items"],
                    waiting={"n": waiting, "href": claims.get("href", "")} if waiting not in ("", "0") else None,
                    items=[_means(x) for x in got.lines("Moyens de communication")])


# ── Identités à confirmer et noms à relier, pour la file « À valider » ─────


def _action(got: Got, key: str, handle: str, label: str, back: str, **values: str) -> dict[str, str] | None:
    """Une action de la fiche d'un moyen de communication, sur sa propre page (qui ramène à cette file), déjà
    orientée (``values`` : ses valeurs de départ, ``?valeur.<champ>=``) ; rien si la faculté ne l'offre pas pour
    lui."""
    spec = got.ui.inspection.action(key)
    if spec is None or not handle or not offered(got.ui.kernel, spec, handle):
        return None
    query = {"retour": back, "sujet": handle, **{PREFILL + k: v for k, v in values.items()}}
    return {"label": label, "href": f"{PREFIX}/action/{quote(key, safe='')}?" + urlencode(query)}


def claim_entry(got: Got, line: Line) -> dict[str, Any]:
    handle = line.get("moyen de communication")
    key = handle_of(handle)
    target = line.get("vise")
    known = bool(target and target.get("t") == "link")
    # se porter garant n'a de sens que pour une personne connue ; relier arrive sur elle (la faculté la pré-remplit),
    # démentir sur le nom revendiqué
    actions = [_action(got, EVIDENCE, key, "S'en porter garant", CLAIMS, kind=VOUCHED) if known else None,
               _action(got, EVIDENCE, key, "La démentir", CLAIMS, kind=DENIED),
               _action(got, "identity.relier", key, "Relier à une personne", CLAIMS)]
    return {
        "handle": handle, "name": line.text("nom revendiqué"), "target": target,
        "known": known, "channel": line.get("canal"), "evidence": line.text("preuves comptées"),
        "since": line.get("depuis"), "ends": line.get("s'éteint"), "actions": [a for a in actions if a],
    }


def name_entry(line: Line) -> dict[str, Any]:
    """Un nom qui attend quelqu'un : ce qu'on lui en a dit, la personne qui le porte, et ses deux réponses — la fiche
    pré-remplie (« C'est elle ») et le bouton de la faculté (« Ce n'est pas elle »)."""
    toolbar = next((d for d in line.detail if d.get("t") == "toolbar"), None)
    dismiss = next((x for x in (toolbar or {}).get("items", []) if x.get("t") == "action"), None)
    homonyms = next((d["text"] for d in line.detail if d.get("t") == "note"), "")
    return {
        "name": line.text("nom dont on lui a parlé"), "told": line.get("qui lui en a parlé"),
        "what": line.text("ce qui attend"), "person": line.get("personne qui le porte"), "where": line.text("par où"),
        "first": None if blank(line.get("vue pour la première fois")) else line.get("vue pour la première fois"),
        "homonyms": homonyms, "href": line.href, "dismiss": dismiss,
    }


# ── Règles de divulgation ─────────────────────────────────────────────────


def _bars(fields: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Les barres en chiffres : « barre de divulgation (personnel sur autrui, sa propre fiche) » → le mot, sa
    portée."""
    out = []
    for p in (fields or {}).get("pairs", []):
        label, scope = _split(p["label"])
        out.append({"label": label, "value": p["value"], "sub": scope})
    return out


def _scale(degrees: Sequence[Line], bar: tuple[float, str], confidence: tuple[float, str]) -> dict[str, Any]:
    """L'échelle de la certitude (0 à 1) : ses degrés, la barre et celle des confidences, en pourcentages."""
    marks = []
    for i, x in enumerate(sorted(degrees, key=lambda d: number(d.text("certitude")) or 0.0)):
        value = number(x.text("certitude")) or 0.0
        marks.append({"name": x.text("degré"), "value": x.text("certitude"), "x": _pct(value),
                      "row": i % 2, "over": x.text("barre") == "atteint la barre",
                      "anchor": "start" if value <= 0.02 else "end" if value >= 0.98 else "middle"})
    return {"marks": marks, "bar": _pct(bar[0]), "bar_text": bar[1], "confidence": _pct(confidence[0]),
            "confidence_text": confidence[1]}


def _channels(lines: Sequence[Line]) -> list[dict[str, Any]]:
    out = []
    for x in lines:
        floor, ceiling = number(x.text("plancher")) or 0.0, number(x.text("plafond")) or 0.0
        short, why = _split(x.text("ce que prouve le canal"))
        out.append({"trust": x.get("confiance"), "why": why or short, "floor": x.text("plancher"),
                    "ceiling": x.text("plafond"), "x1": _pct(floor), "x2": _pct(ceiling),
                    "point": abs(ceiling - floor) < 0.005, "best": x.text("au mieux")})
    return out


def _weights(lines: Sequence[Line]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {"pour": [], "contre": []}
    for x in lines:
        weight = number(x.text("poids")) or 0.0
        out.setdefault(x.text("sens"), []).append({"name": x.text("preuve"), "key": x.text("clé"),
                                                  "weight": x.text("poids"), "w": _pct(abs(weight))})
    for side in out.values():
        side.sort(key=lambda w: -w["w"])
    return out


def politique(got: Got) -> Markup | None:
    """Identités › Règles de divulgation : les barres, l'échelle de la certitude et les canaux, les preuves, les
    rangs, les propriétaires."""
    channels, degrees = got.table("Les canaux"), got.table("Les degrés")
    weights, ranks = got.table("Le poids"), got.table("Les rangs")
    bars, owners = got.fields("Les barres"), got.fields("Propriétaires")
    if None in (channels, degrees, weights, ranks, bars, owners):
        return None
    values = {_split(k)[0]: (number(v) or 0.0, text(v)) for k, v in pairs(bars).items()}
    calibration = next((n for n in got.notes() if n.get("title") == "Calibration"), None)
    return got.draw(
        "handmade/identites/politique.html", bars=_bars(bars),
        scale=_scale(got.lines("Les degrés"), values.get("barre de divulgation", (0.7, "0,70")),
                     values.get("confidences", (0.85, "0,85"))),
        channels=_channels(got.lines("Les canaux")), channels_help=(channels or {}).get("caption", ""),
        weights=_weights(got.lines("Le poids")), weights_help=(weights or {}).get("caption", ""),
        ranks=[{"name": x.text("proximité"), "key": x.text("clé"), "rank": x.text("rang")}
               for x in got.lines("Les rangs")],
        owners=(owners or {}).get("pairs", []), calibration=calibration)


TABS: dict[str, Any] = {
    "identites/annuaire": Tab(moyens, *STYLES),
    "identites/politique": Tab(politique, *STYLES),
}
