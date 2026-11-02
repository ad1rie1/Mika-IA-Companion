"""Elle › Humeur et corps : ses onglets, chacun dans sa forme (ADR 0177). Des vues d'un objet — elle — : un bandeau
d'alerte au plus, une bande de chiffres, puis des tuiles ; ce qui est long et technique se replie ou passe en
sous-onglet.

- **Humeur** : son humeur en grand, comme « En ce moment » la dit (``now.mood``) — le mot, le mélange de ce qu'elle
  ressent, ce que son prompt lui en dit, le plan plaisir × éveil et sa trace sur la période choisie — ; une bande de
  chiffres (ce qui déborde, son fond, son visage, sa dernière balise) ; sa valence à côté de ses dernières balises,
  chacune avec ce qu'elle a dit ; les chiffres bruts repliés.
- **Postures** : une carte par personne — ce qu'elle ressent envers elle, la chaleur de part et d'autre du milieu,
  l'hostilité, l'attachement, ce qu'elle s'en dit — ; un bandeau si elle en veut à quelqu'un.
- **Besoins** : ses trois besoins en tuiles (la tension et son sens sur la dernière heure, ce qui le comble), ce que
  son prompt en dit, leur courbe, ce qui se passe ; ses règles repliées.
- **Sommeil et rythme** : une bande de chiffres ; ce que son prompt dit de l'heure et sa journée sur 24 heures (ses
  phases et leur teinte, sa nuit, maintenant) ; l'énergie et la pression de sommeil ; ses nuits à côté de ses
  transitions ; le détail replié.
- **Monde et corps** : une bande de chiffres ; ce qui est en route, pas à pas ; les choses rangées par où elles
  sont ; ce qu'elle a remarqué des éditions à côté des éditions.
- **Estime et récit** : une bande de chiffres qui mène à ses sous-onglets, un bandeau si elle doute ; son estime (sur
  son échelle, sa courbe, ses derniers coups, ses règles repliées), son récit, sa persona, son tempérament (sa
  réaction, sa défense, ses curseurs par famille, de part et d'autre du milieu).
- **Qui elle devient** : en sous-onglets, ce qu'elle sait d'elle, ce qui la passionne, ce qui la définit, ses
  changements d'avis.

Les données restent celles des facultés (``affect``, ``needs``, ``body``, ``world``, ``self``) : leurs filtres, leurs
paginations et la bascule « Tableau » des besoins aussi. Ce que leurs blocs ne disent pas se lit à leurs faits, au
même instant (``Look``) : le mélange et le plan de son humeur, son visage, le sens de ses besoins, ses nuits à
l'heure près, les familles de son tempérament.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from markupsafe import Markup

from mika.app.handmade import Look, date_fr
from mika.app.handmade.now import mood as mood_of
from mika.app.handmade.now import needs as needs_of
from mika.app.handmade.tabs import Got, Line, Tab, anchored, blank, pairs, text, tiles
from mika.contracts import affect as affect_c
from mika.contracts import needs as needs_c
from mika.contracts import self_ as self_c
from mika.faculties.affect.inspect import PERIODS
from mika.faculties.needs import describe as needs_said
from mika.faculties.needs.inspect import NAMES as NEED_NAMES
from mika.kernel import forms
from mika.kernel.clock import DAY
from mika.kernel.inspect import When, num_fr, pct_fr
from mika.vocab import affect as A
from mika.vocab import temperament as T

STYLES = ("handmade/vie.css",)

#: la période de l'humeur (le filtre de la faculté) : la fenêtre de sa trace sur le plan
SPANS = {"24h": DAY, "7j": 7 * DAY}
#: une heure dite « 06:00 » dans un texte de la faculté
HOUR_RE = re.compile(r"(\d{1,2}):(\d{2})")
#: un nombre dit à la française (« 0,35 »)
NUMBER_RE = re.compile(r"\d+(?:,\d+)?")
#: les deux bouts d'un curseur, à la fin de son aide (« … (0 : imperturbable · 1 : à fleur de peau) »)
ENDS_RE = re.compile(r"\s*\(0 : (.+) · 1 : (.+)\)\s*$")
MINUTES = 24 * 60


# ── des outils communs ──


def _cell(line: Line, label: str) -> dict[str, Any] | None:
    """Une cellule qui dit quelque chose (ni absente, ni vide, ni « — »)."""
    c = line.get(label)
    return None if blank(c) else c


def _meter(c: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Une jauge rendue, prête à dessiner : sa part (0–100), son texte, son ton."""
    if not c or c.get("t") != "meter":
        return None
    return {"w": round(100 * float(c["ratio"]), 1), "ratio": float(c["ratio"]), "text": c["text"],
            "tone": c.get("tone") or ""}


def _note(blocks: Sequence[Mapping[str, Any]]) -> str:
    """Le texte de la première note d'un détail (ce qu'elle a dit, ce qu'elle se dit)."""
    return next((str(d.get("text") or "") for d in blocks if d.get("t") == "note"), "")


def _number(value: str) -> float | None:
    found = NUMBER_RE.search(value or "")
    return float(found.group().replace(",", ".")) if found else None


def _minutes(value: str) -> int | None:
    found = HOUR_RE.search(value or "")
    return int(found[1]) % 24 * 60 + int(found[2]) if found else None




# ── Humeur ──


def _face(look: Look) -> dict[str, Any]:
    """Son visage : la lecture absolue de son humeur (ce que montre son avatar), comme une pastille rendue."""
    m = look.frame.get(affect_c.MOOD)
    return {"t": "swatch", "key": m.label.value, "text": A.FR[m.label], "weight": pct_fr(m.intensity)}


def _tag(line: Line) -> dict[str, Any]:
    emotion = line.get("émotion déclarée")
    return {"when": line.get("quand"), "who": line.get("à qui"), "how": line.text("comment"),
            "emotion": emotion if emotion and emotion.get("t") == "swatch" else None,
            "word": line.text("émotion déclarée"), "said": _note(line.detail)}


def humeur(got: Got) -> Markup | None:
    """Humeur : son humeur en grand, la bande de chiffres, sa valence et ses balises, les chiffres bruts."""
    stats, table = got.stats("Humeur générale"), got.table("Dernières balises")
    if stats is None or table is None:
        return None
    period = got.query.get("periode") or "24h"
    look = Look.of(got.ui, SPANS.get(period, DAY))
    m = mood_of(look)
    s = tiles(stats)
    voice = next((n["text"] for n in got.notes() if not n.get("title")), m["line"])
    detail = got.disclosure("Détails")
    raw = next((b for b in (detail or {}).get("items", []) if b.get("t") == "fields"), None)
    band = [
        {"label": "Ce qui déborde", "value": s.get("débordement", {}).get("value"),
         "sub": s.get("débordement", {}).get("sub", ""), "tone": s.get("débordement", {}).get("tone", "")},
        {"label": "Son fond", "value": s.get("son fond", {}).get("value"),
         "sub": s.get("son fond", {}).get("sub", "")},
        {"label": "Son visage", "value": _face(look), "sub": "ce que montre son avatar : la lecture absolue"},
        {"label": "Dernière balise", "value": s.get("dernière balise", {}).get("value"),
         "sub": s.get("dernière balise", {}).get("sub", "")},
    ]
    return got.draw("handmade/vie/humeur.html", m=m, voice=voice, band=[b for b in band if b["value"]],
                    chart=got.chart("Valence"), t=table, tags=[_tag(x) for x in got.lines("Dernières balises")],
                    raw=(raw or {}).get("pairs", []), period=dict(PERIODS).get(period, period))


# ── Postures ──


def _signed(c: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """La chaleur, signée (−1…1) : une jauge de part et d'autre de son milieu, vers le chaud ou vers le froid."""
    if not c or c.get("t") != "meter":
        return None
    cold = str(c["text"]).lstrip().startswith(("−", "-"))
    half = round(50 * float(c["ratio"]), 1)
    return {"x1": 50 - half if cold else 50, "x2": 50 if cold else 50 + half, "text": c["text"],
            "side": "cold" if cold and half > 2.5 else "warm" if half > 2.5 else ""}


def _stance(line: Line) -> dict[str, Any]:
    who = line.get("personne") or {"t": "text", "text": "?"}
    felt = line.get("ressentie envers elle")
    hostility = _meter(line.get("hostilité"))
    facts = [d for d in line.rest if d.get("t") != "note"]
    installed = next((text(p["value"]) for d in facts if d.get("t") == "fields" for p in d.get("pairs", [])
                      if p["label"] == "installée"), "")
    return {
        "who": who, "initial": (text(who)[:1] or "?").upper(),
        "felt": felt if felt and felt.get("t") == "swatch" else None,
        "emotion": felt["key"] if felt and felt.get("t") == "swatch" else "neutral",
        "warmth": _signed(line.get("chaleur (−1…1)")), "hostility": hostility,
        "bond": _meter(line.get("attachement")), "anchor": _cell(line, "ancre"),
        "last": _cell(line, "dernière balise"), "when": line.get("quand"), "says": _note(line.rest),
        "installed": installed.startswith("oui"), "grudge": bool(hostility and hostility["tone"] == "danger"),
        "facts": facts, "open": line.open,
    }


def postures(got: Got) -> Markup | None:
    """Postures : une carte par personne, un bandeau si elle en veut à quelqu'un."""
    table = got.table("Postures envers chacun")
    if table is None:
        return None
    people = [_stance(x) for x in got.lines("Postures envers chacun")]
    installed = sum(1 for p in people if p["installed"])
    lede = "ce qu'elle ressent envers chacun, et ce que leurs échanges ont installé"
    if installed:
        lede = (f"{installed} posture{'s' if installed > 1 else ''} installée{'s' if installed > 1 else ''} "
                f"(plusieurs échanges concordants) · {lede}")
    return got.draw("handmade/vie/postures.html", t=table, people=people, lede=lede,
                    grudges=[p["who"] for p in people if p["grudge"]])


# ── Besoins ──


#: un besoin, de son nom (la faculté le dit en mots) à sa clé (sa couleur, sa série)
NEED_KEYS = {name: key for key, name in NEED_NAMES.items()}
#: « En détail » : ce qui se passe en ce moment ; le reste (ses règles) se replie
NEEDS_NOW = ("rien ne s'est passé depuis", "on lui a parlé pour la dernière fois", "dernier vide ressenti",
             "en ce moment", "ce qu'elle a fait de ses mains")


def _need(line: Line, trends: Mapping[str, str]) -> dict[str, Any]:
    name = line.text("besoin")
    key = NEED_KEYS.get(name, "")
    return {"name": name[:1].upper() + name[1:], "key": key, "tension": _meter(line.get("tension")),
            "horizon": line.text("horizon"), "relief": line.text("ce qui le comble"),
            "when": line.get("dernier relevé"), "trend": trends.get(key, "")}


def besoins(got: Got) -> Markup | None:
    """Besoins : ses trois besoins en tuiles, ce que son prompt en dit, leur courbe, ce qui se passe."""
    table, fields = got.table("Ses besoins"), got.fields("En détail")
    if table is None or fields is None:
        return None
    look = Look.of(got.ui, DAY)
    trends = {r["key"]: r["trend"] for r in needs_of(look)["rows"]}
    needs = [_need(x, trends) for x in got.lines("Ses besoins")]
    strongest = max((n["tension"]["ratio"] for n in needs if n["tension"]), default=0.0)
    for n in needs:
        n["dominant"] = bool(n["tension"]) and strongest >= 0.05 and n["tension"]["ratio"] == strongest
    said = needs_said(look.frame.get(needs_c.NEEDS))
    calm = next((n["text"] for n in got.notes() if n.get("title")), "")
    every = fields.get("pairs", [])
    return got.draw("handmade/vie/besoins.html", t=table, needs=needs, said=said, calm=calm,
                    chart=got.chart("Ses besoins"), now=[p for p in every if p["label"] in NEEDS_NOW],
                    rules=[p for p in every if p["label"] not in NEEDS_NOW])


# ── Sommeil et rythme ──


def _pieces(start: int, end: int) -> list[tuple[int, int]]:
    """Un intervalle de la journée (en minutes), coupé à minuit s'il le passe."""
    end = end if end > start else end + MINUTES
    return [(start, min(end, MINUTES))] + ([(0, end - MINUTES)] if end > MINUTES else [])


def _pct(minutes: float) -> float:
    return round(100 * minutes / MINUTES, 3)


def _day(phases: Sequence[Line], night: str, now: int) -> dict[str, Any] | None:
    """Sa journée sur 24 heures : ses phases (leur teinte), sa nuit, maintenant — en pourcentages de la journée."""
    starts = sorted(((m, x) for x in phases if (m := _minutes(x.text("début"))) is not None), key=lambda p: p[0])
    if not starts:
        return None
    out = []
    for i, (start, line) in enumerate(starts):
        end = starts[(i + 1) % len(starts)][0]
        pieces = _pieces(start, end if len(starts) > 1 else start)
        tint = line.get("teinte")
        main = max(pieces, key=lambda p: p[1] - p[0])
        out.append({"name": line.text("phase"), "start": line.text("début"),
                    "tint": tint if tint and tint.get("t") == "swatch" else None,
                    "key": tint["key"] if tint and tint.get("t") == "swatch" else "neutral",
                    "rects": [{"x": _pct(a), "w": _pct(b - a)} for a, b in pieces],
                    "mid": _pct((main[0] + main[1]) / 2)})
    found = HOUR_RE.findall(night or "")
    sleep = []
    if len(found) >= 2:
        a, b = (int(h) % 24 * 60 + int(m) for h, m in found[:2])
        sleep = [{"x": _pct(x), "w": _pct(y - x)} for x, y in _pieces(a, b)]
    return {"phases": out, "sleep": sleep, "night": night,
            "now": _pct(now), "now_label": f"{now // 60:02d}:{now % 60:02d}",
            "now_anchor": "end" if now > MINUTES - 90 else "start" if now < 90 else "middle",
            "ticks": [{"x": _pct(h * 60), "label": f"{h:02d}:00",
                       "anchor": "start" if h == 0 else "end" if h == 24 else "middle", "major": h % 6 == 0}
                      for h in range(0, 25, 3)]}


def _nights(got: Got, look: Look) -> list[dict[str, Any]]:
    """Ses dernières nuits, lues dans la liste de la faculté (les instants à l'heure près, pas en dates longues)."""
    table = got.raw_table("Ses dernières nuits")
    out = []
    for row in (table.rows if table is not None else ()):
        cells = row.cells if hasattr(row, "cells") else tuple(row)
        start, end, slept, rousings, late, told = (*cells, *([None] * 6))[:6]
        if not isinstance(start, When):
            continue
        out.append({"day": date_fr(look.frame.local(start.at)), "from": look.hm(start.at),
                    "to": look.hm(end.at) if isinstance(end, When) else "", "slept": str(slept or ""),
                    "rousings": "" if str(rousings or "—") == "—" else str(rousings),
                    "late": str(late) == "oui", "told": str(told or "")})
    return out


#: « En détail » du rythme : ce qui se dit aussi en étiquettes, à côté de ce que son prompt dit de l'heure
RHYTHM_FLAGS = ("réveillée par un message", "messages qui attendent son réveil", "initiatives et travail ordinaires")


def rythme(got: Got) -> Markup | None:
    """Sommeil et rythme : la bande de chiffres, sa journée sur 24 heures, ses courbes, ses nuits, ses transitions."""
    stats, fields, phases = got.stats("Son corps"), got.fields("En détail"), got.table("Son rythme")
    if stats is None or fields is None or phases is None:
        return None
    look = Look.of(got.ui, DAY)
    local = look.frame.local(look.now)
    facts = pairs(fields)
    flags = []
    if text(facts.get("réveillée par un message")) == "oui":
        flags.append({"text": "réveillée par un message", "tone": "info"})
    waiting = text(facts.get("messages qui attendent son réveil"))
    if waiting and waiting != "aucun":
        flags.append({"text": f"{waiting} message(s) attendent son réveil", "tone": "warn"})
    gate = text(facts.get("initiatives et travail ordinaires"))
    if gate and gate != "libres":
        flags.append({"text": f"initiatives et travail {gate}", "tone": "warn" if gate.startswith("retenues") else ""})
    return got.draw("handmade/vie/rythme.html", band=stats["items"],
                    voice=next((n["text"] for n in got.notes()), ""), flags=flags,
                    day=_day(got.lines("Son rythme"), text(facts.get("sa nuit")), local.hour * 60 + local.minute),
                    chart=got.chart("Énergie"), nights=_nights(got, look), t_nights=got.table("Ses dernières nuits"),
                    timeline=got.timeline("Dernières transitions"),
                    detail=[p for p in fields.get("pairs", []) if p["label"] not in RHYTHM_FLAGS])


# ── Monde et corps ──


def _intent(line: Line) -> dict[str, Any]:
    steps = [s.strip() for s in line.text("les pas").split(" · ") if s.strip()]
    return {"actor": line.get("acteur"), "by": line.text("décidé par"), "steps": steps,
            "eta": _cell(line, "fin prévue"), "deadline": _cell(line, "échéance")}


def _places(things: Sequence[Line]) -> tuple[str, list[dict[str, Any]]]:
    """Les choses rangées par où elles sont, dans l'ordre où la liste les nomme ; et la pièce, quand toutes y sont
    (« ta chambre, sur ton lit » : la pièce se dit une fois, le lieu à chaque groupe)."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for x in things:
        groups.setdefault(x.text("où") or "—", []).append(
            {"name": x.get("objet"), "id": x.text("identifiant"), "state": _cell(x, "état")})
    rooms = {where.partition(", ")[0] for where in groups if ", " in where}
    room = next(iter(rooms)) if len(rooms) == 1 and all(", " in where for where in groups) else ""
    return room, [{"where": where.removeprefix(f"{room}, ") if room else where, "things": items}
                  for where, items in groups.items()]


def _remark(line: Line) -> dict[str, Any]:
    return {"when": line.get("quand"), "what": line.get("ce qu'elle remarque"), "weight": line.text("pertinence"),
            "state": line.text("état")}


def _edit(line: Line) -> dict[str, Any]:
    return {"when": line.get("quand"), "by": line.text("par"), "rev": line.text("révision"),
            "changes": line.text("les changements")}


def monde(got: Got) -> Markup | None:
    """Monde et corps : la bande de chiffres, ce qui est en route, les choses par où elles sont, les éditions."""
    stats, intents, things = got.stats("Son corps"), got.table("Ce qui est en route"), got.table("Les choses")
    edits, remarks = got.table("Les dernières éditions"), got.table("Ce qu'elle en a remarqué")
    if stats is None or intents is None or things is None or edits is None or remarks is None:
        return None
    room, places = _places(got.lines("Les choses"))
    return got.draw("handmade/vie/monde.html", band=stats["items"], t_intents=intents,
                    intents=[_intent(x) for x in got.lines("Ce qui est en route")], t_things=things,
                    room=room, places=places, t_edits=edits,
                    edits=[_edit(x) for x in got.lines("Les dernières éditions")], t_remarks=remarks,
                    remarks=[_remark(x) for x in got.lines("Ce qu'elle en a remarqué")],
                    notes=[n for n in got.notes() if n.get("tone") == "muted"])


# ── Estime et récit ──


#: la persona : ce qui la nomme (une ligne de faits), ce qui se lit en liste (des éléments séparés par « · »)
PERSONA_IDENTITY = ("nom", "nature", "langue", "fuseau")
PERSONA_LISTS = ("ce qui est vrai d'elle", "centres d'intérêt", "salutations", "exemples en conversation")


def _scale(s: Mapping[str, Any], rules: Mapping[str, dict[str, Any]]) -> dict[str, Any] | None:
    """Son estime sur son échelle (0–1) : là où elle doute, là où elle est sûre d'elle, ses bornes."""
    estime = _meter(s.get("Estime", {}).get("value"))
    if estime is None:
        return None
    doubt = _number(text(rules.get("elle doute sous")))
    sure = _number(text(rules.get("sûre d'elle au-dessus de")))
    bounds = [float(n.replace(",", ".")) for n in NUMBER_RE.findall(text(rules.get("bornes")))]
    return {"value": estime["w"], "text": estime["text"], "tone": estime["tone"],
            "doubt": None if doubt is None else round(100 * doubt, 1),
            "sure": None if sure is None else round(100 * sure, 1),
            "lo": round(100 * bounds[0], 1) if len(bounds) == 2 else 0.0,
            "hi": round(100 * bounds[1], 1) if len(bounds) == 2 else 100.0,
            "doubt_text": text(rules.get("elle doute sous")), "sure_text": text(rules.get("sûre d'elle au-dessus de"))}


def _knock(line: Line) -> dict[str, Any]:
    delta = line.text("coup")
    return {"when": line.get("quand"), "why": line.text("pourquoi"), "delta": delta,
            "tone": "danger" if delta.startswith(("−", "-")) else "ok"}


def _persona(fields: Mapping[str, Any] | None) -> dict[str, Any]:
    identity, lists, texts = [], [], []
    for p in (fields or {}).get("pairs", []):
        label, value = p["label"], p["value"]
        if label in PERSONA_IDENTITY:
            identity.append({"label": label, "value": value})
        elif label.startswith(PERSONA_LISTS):
            items = [x.strip() for x in text(value).split(" · ") if x.strip()] if not blank(value) else []
            lists.append({"label": label, "entries": items, "pairs": [x.split(" → ", 1) for x in items]
                          if label.startswith("exemples") and all(" → " in x for x in items) else []})
        else:
            texts.append({"label": label, "text": "" if blank(value) else text(value)})
    return {"identity": identity, "lists": lists, "texts": texts}


def _temperament(look: Look) -> dict[str, Any]:
    """Son tempérament, lu à sa persona : ses curseurs par famille, chacun avec ses deux bouts et ce qu'il pilote, de
    part et d'autre du milieu (0,5 : comme la plupart des gens) ; son profil."""
    t = look.frame.get(self_c.PERSONA).temperament
    sliders = set(T.SLIDERS)
    families: dict[str, list[dict[str, Any]]] = {}
    for f in forms.describe(T.Temperament):
        if f.path not in sliders:
            continue
        value = float(getattr(t, f.path))
        ends = ENDS_RE.search(f.help)
        drift = round(100 * (value - 0.5), 1)
        families.setdefault(f.group, []).append({
            "label": f.label, "value": num_fr(value, 2), "help": ENDS_RE.sub("", f.help),
            "lo": ends[1] if ends else "", "hi": ends[2] if ends else "",
            "x1": min(50.0, 50 + drift), "x2": max(50.0, 50 + drift), "far": abs(value - 0.5) >= 0.2})
    key = T.profile_of(t)
    return {"families": [{"name": k, "sliders": v} for k, v in families.items()],
            "profile": T.PROFILES[key].label if key else "ajusté à la main",
            "background": {"t": "swatch", "key": t.background.value, "text": A.FR[t.background], "weight": None}}


def soi(got: Got) -> Markup | None:
    """Estime et récit : la bande de chiffres, un bandeau si elle doute, puis ses sous-onglets."""
    stats, rules, persona = got.stats(), got.fields("L'estime"), got.fields("La persona")
    if stats is None or rules is None or persona is None:
        return None
    look = Look.of(got.ui, DAY)
    s = tiles(stats)
    story = got.fields("Son récit")
    prose = next((b for b in got.walk() if b.get("t") == "prose"), None)
    knocks = anchored(got.table("Les derniers coups"), "soi-estime")
    return got.draw("handmade/vie/soi.html", band=stats["items"],
                    doubt=next((n["text"] for n in got.notes() if n.get("tone") == "warn"), ""),
                    scale=_scale(s, pairs(rules)), chart=got.chart("L'estime"), t_knocks=knocks,
                    knocks=[_knock(x) for x in got.lines("Les derniers coups")], rules=rules.get("pairs", []),
                    story=(story or {}).get("pairs", []), prose=prose,
                    untold=next((n["text"] for n in got.notes() if n.get("tone") == "muted"), ""),
                    persona=_persona(persona),
                    character=(got.fields("Quand on la blesse") or {}).get("pairs", []),
                    temperament=_temperament(look))


# ── Qui elle devient ──


def _knowing(line: Line) -> dict[str, Any]:
    said = line.get("ce que son prompt en dit") or {}
    return {"name": line.text("ce qu'elle sait d'elle"), "marks": line.text("ses marques"),
            "rule": line.text("les seuils"), "said": text(said), "quiet": said.get("kind") == "muted"}


def _passion(line: Line) -> dict[str, Any]:
    return {"subject": line.get("sujet"), "origin": line.text("d'où"), "level": line.get("niveau"),
            "glow": _meter(line.get("vivacité")), "fed": line.text("nourri"), "times": line.text("fois")}


def devenir(got: Got) -> Markup | None:
    """Qui elle devient : en sous-onglets, ce qu'elle sait d'elle, ce qui la passionne, ce qui la définit, ses
    changements d'avis."""
    knowing, passions = got.table("Tenir parole"), got.table("Ce qui la passionne")
    changes, defining = got.table("Ses changements d'avis"), got.table("Ses goûts")
    if knowing is None or passions is None or changes is None or defining is None:
        return None
    return got.draw(
        "handmade/vie/devenir.html",
        t_knowing=anchored(knowing, "devenir-sait"), knowing=[_knowing(x) for x in got.lines("Tenir parole")],
        t_passions=anchored(passions, "devenir-passions"),
        passions=[_passion(x) for x in got.lines("Ce qui la passionne")],
        leads=(got.fields("Ses pistes") or {}).get("pairs", []),
        t_changes=anchored(changes, "devenir-avis"), changes=[
            {"was": x.get("avant"), "now": x.get("maintenant"), "kind": x.text("sorte"), "when": x.get("quand")}
            for x in got.lines("Ses changements d'avis")],
        t_defining=anchored(defining, "devenir-definit"), defining=[
            {"text": x.get("ce qui la définit"), "kind": x.text("sorte"), "since": x.get("depuis")}
            for x in got.lines("Ses goûts")])


TABS: dict[str, Any] = {
    "vie/humeur": Tab(humeur, "handmade/now.css", *STYLES),
    "vie/postures": Tab(postures, *STYLES),
    "vie/needs": Tab(besoins, *STYLES),
    "vie/rythme": Tab(rythme, *STYLES),
    "vie/monde": Tab(monde, *STYLES),
    "vie/soi": Tab(soi, *STYLES),
    "vie/devenir": Tab(devenir, *STYLES),
}
