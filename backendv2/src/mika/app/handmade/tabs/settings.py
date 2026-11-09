"""Réglages : ses onglets, chacun dans sa forme (ADR 0177).

- Paramètres avancés › Vue d'ensemble : ses paramètres en chiffres, d'où vient une valeur (les quatre sources, des
  étiquettes que chaque page de faculté reprend) ; puis en sous-onglets les facultés rangées par famille (chacune :
  combien de paramètres, ce que le tempérament en dérive, ce qui est surchargé, réglé ailleurs ou refusé), et ce que
  pilote chaque curseur du tempérament.
- Paramètres avancés › une faculté : ses chiffres (ce que le tempérament dérive mène au tempérament), d'où vient une
  valeur, ses groupes dans la colonne de gauche ; puis l'aperçu de « Voir l'effet » et le formulaire de ses paramètres,
  le panneau de la console (le gabarit « paramétrage »).
- Comptes : les comptes en chiffres, puis un par entrée — son nom, son identifiant, son rôle, son état, sa fiche ; la
  bascule « Tableau » et la pagination de la liste. Ajouter un compte reste l'action de la page (barre de titre, par
  le panneau) ; ajouter et modifier un compte ont leur page (le panneau seul).
- Journal des modifications : jour par jour, chaque réglage enregistré (qui, quoi, sur quoi) et chaque journalisation
  des paramètres — celles d'un même moment (le démarrage) réunies en une ligne.
- Configuration des plugins (``plugins``, l'en-tête dessiné de sa page de réglages) : une ligne par plugin composé — ce
  qui s'y règle, ses pages de réglages, ses paramètres avancés, où s'en servir —, puis ce qui se branche sans être un
  plugin ; les lignes viennent d'``app/settings_sections/plugins.py`` (``PLUGINS``), sans pagination.
- Droits (``handmade/rights.py`` : ce qu'il y a à montrer, ressource par ressource ; ADR 0133, 0134, 0210) : ce qu'elle a,
  le détail des accès d'une ressource, les droits exacts quand on a choisi qui et par quel canal, les partages.

La vue d'ensemble lit ses facultés dans les paramètres de la console (``ui.deps.parameters``), comme la page de la
console (``inspector/pages/params.py``) qui reste la source : ses blocs disent les chiffres, la liste se dessine par
famille, sans pagination (une trentaine de facultés).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from markupsafe import Markup

from mika.app.handmade import Look, rights
from mika.app.handmade.tabs import Got, Line, Tab, blank, instant, raw_lines, text, tiles
from mika.inspector import render
from mika.inspector.pages import tools as catalog
from mika.inspector.pages.params import FACULTY_PAGE, SOURCES_FR, TONES, faculty_url, slider_influences
from mika.inspector.ui import PREFIX, UI, env
from mika.kernel.clock import DAY, MINUTE
from mika.kernel.inspect import Nav, Note, Pager, Stats

STYLES = ("handmade/reglages_onglets.css",)
#: la page du tempérament (ce que les facultés en dérivent)
TEMPERAMENT = f"{PREFIX}/reglages/temperament"
#: la famille d'une faculté que la composition ne range nulle part
OTHERS = "Autres"
#: les surcharges refusées, telles que la page d'une faculté les annonce
REFUSED = "Des surcharges enregistrées sont refusées"


def _sources() -> list[dict[str, str]]:
    """D'où vient une valeur : les quatre sources, dans l'ordre où elles se recouvrent, et leur ton."""
    return [{"word": s, "tone": tone, "text": SOURCES_FR.get(s, s)} for s, tone in TONES.items()]


# ── Configuration des plugins ─────────────────────────────────────────────


def plugins(groups: list[dict[str, Any]]) -> Markup:
    """Réglages › Configuration des plugins : chaque groupe (les plugins, puis ce qui n'en est pas) en table, une ligne
    par plugin — son nom et ce qui s'y règle, ses pages de réglages, ses paramètres avancés, où s'en servir."""
    shown = [{**g, "pager": render._pager(Pager(size=len(g["rows"]), total=len(g["rows"])), {})}
             for g in groups if g["rows"]]  # une page, toujours : sa pagination ne se montre pas (``.hm-pager.single``)
    return Markup(env.get_template("handmade/reglages/plugins.html").render(groups=shown))


# ── Paramètres avancés › Vue d'ensemble ───────────────────────────────────


def _faculty(ui: UI, ps: Any, fac: Any, overrides: Mapping[str, Any]) -> dict[str, Any] | None:
    p = ps.plan(fac.name)
    if p is None:
        return None
    counts = {s: sum(1 for v in p.sources.values() if v == s) for s in TONES}
    return {"name": fac.name, "label": dict(ui.deps.faculty_labels or {}).get(fac.name, fac.name),
            "href": faculty_url(fac.name), "params": len(p.sources),
            "derived": counts["tempérament"] if fac.derive is not None else None,
            "overrides": len(overrides.get(fac.name) or {}), "elsewhere": counts["réglage"],
            "refused": len(p.refused), "journaled": ps.journaled(fac.name) is not None}


def _families(ui: UI, ps: Any) -> list[dict[str, Any]]:
    """Les facultés qui ont des paramètres, rangées par famille (celle que la composition déclare, sinon « Autres »)."""
    overrides = ps.overrides()
    found = {f["name"]: f for fac in ps.faculties() if (f := _faculty(ui, ps, fac, overrides)) is not None}
    out, placed = [], set()
    for family, owners in ui.deps.param_families or ():
        items = [found[o] for o in owners if o in found]
        placed |= {f["name"] for f in items}
        if items:
            out.append({"title": family, "items": items})
    rest = [f for name, f in found.items() if name not in placed]
    if rest:
        out.append({"title": OTHERS, "items": rest})
    return out


def _sliders(ui: UI, ps: Any) -> list[dict[str, Any]]:
    """Ce que pilote chaque curseur du tempérament : chaque paramètre, de sa valeur à 0 à sa valeur à 1."""
    return slider_influences(ps, dict(ui.deps.faculty_labels or {}))


def comportement(got: Got) -> Markup | None:
    """Paramètres avancés › Vue d'ensemble : les chiffres, les facultés par famille, ce que pilote le tempérament."""
    band, table = got.stats(), got.table("Les facultés")
    ps = got.ui.deps.parameters
    if band is None or table is None or ps is None:
        return None
    families = _families(got.ui, ps)
    return got.draw("handmade/reglages/comportement.html", band=band, sources=_sources(),
                    families=families, count=sum(len(f["items"]) for f in families), sliders=_sliders(got.ui, ps))


# ── Paramètres avancés › une faculté ──────────────────────────────────────


def faculte(got: Got) -> tuple[Markup, list[Any]] | None:
    """Paramètres avancés › une faculté : ses chiffres, d'où vient une valeur, ses groupes ; puis l'aperçu de « Voir
    l'effet » (des blocs de la console) et le formulaire de ses paramètres (le panneau)."""
    band = got.stats()
    if band is None:
        return None
    refused = next((b for b in got.raw if isinstance(b, Note) and b.text.startswith(REFUSED)), None)
    rest = [b for b in got.raw if not isinstance(b, Stats | Nav) and b is not refused]
    nav = got.nav("Groupes")
    groups = len((nav or {}).get("items", []))
    said = tiles(band)
    items = []
    for label, s in said.items():
        if label == "Paramètres" and groups:
            s = {**s, "sub": f"en {groups} groupes"}
        elif label == "Dérivés du tempérament":
            s = {**s, "href": TEMPERAMENT, "sub": "pilotés par ses curseurs"}
        elif label == "Surchargés" and text(s["value"]) not in ("0", ""):
            s = {**s, "sub": "posés par un opérateur"}
        items.append(s)
    html = got.draw("handmade/reglages/faculte.html", band={**band, "items": items},
                    refused=refused.text if refused is not None else "", sources=_sources(), nav=nav)
    return html, rest


# ── Comptes ───────────────────────────────────────────────────────────────


def _account(line: Line) -> dict[str, Any]:
    login, shown = line.get("identifiant") or {}, line.get("nom affiché")
    role, active = line.get("rôle") or {}, line.get("état") or {}
    name = text(shown) if not blank(shown) else text(login)
    return {"login": text(login), "href": login.get("href") or line.href, "name": name,
            "initial": (name[:1] or "?").upper(), "person": line.get("personne"), "role": role,
            "operator": text(role) == "opérateur", "off": active.get("tone") == "muted", "state": active}


def accounts(got: Got) -> Markup | None:
    """Comptes : les chiffres, puis un compte par entrée. Ajouter ou modifier un compte : le panneau seul."""
    band, table = got.stats(), got.table("Comptes")
    if band is None or table is None:
        return None
    return got.draw("handmade/reglages/comptes.html", band=band, t=table,
                    items=[_account(x) for x in got.lines("Comptes")])


# ── Journal des modifications ─────────────────────────────────────────────

#: deux journalisations des paramètres à moins d'une minute, de même origine : un seul moment (le démarrage)
TOGETHER = MINUTE


def _change(line: Line, at: int) -> dict[str, Any]:
    kind = line.get("sorte") or {}
    params = text(kind) == "paramètres"
    return {"at": at, "params": params, "kind": kind, "what": [line["quoi"]], "by": None if blank(line.get("par"))
            else line.get("par"), "on": "" if blank(line.get("sur / origine")) else line.text("sur / origine"),
            "when": line.get("quand"), "hrefs": [line.href] if line.href else []}


def _gathered(changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Les journalisations des paramètres d'un même moment et d'une même origine, réunies en une ligne."""
    out: list[dict[str, Any]] = []
    for c in changes:
        last = out[-1] if out else None
        if last is not None and c["params"] and last["params"] and c["on"] == last["on"] \
                and abs(last["at"] - c["at"]) <= TOGETHER:
            last["what"].append(c["what"][0])
            last["hrefs"] += c["hrefs"]
            continue
        out.append({**c, "what": list(c["what"]), "hrefs": list(c["hrefs"])})
    return out


def journal(got: Got) -> Markup | None:
    """Journal des modifications : jour par jour, ce qui a changé, qui l'a fait, sur quoi."""
    table = got.table("Journal des modifications")
    if table is None:
        return None
    look = Look.of(got.ui, DAY)
    changes = [_change(x, instant(r.get("quand"))) for x, r in zip(got.lines("Journal des modifications"),
                                                                 raw_lines(got, table), strict=False)]
    days: list[dict[str, Any]] = []
    for c in _gathered(changes):
        day = look.day(c["at"], all_day=True) if c["at"] else "—"
        if c["at"] and day not in ("aujourd'hui", "hier"):
            day = look.date(c["at"])
        if not days or days[-1]["day"] != day:
            days.append({"day": day, "items": []})
        days[-1]["items"].append({**c, "time": look.hm(c["at"]) if c["at"] else ""})
    return got.draw("handmade/reglages/journal.html", t=table, days=days)


# ── Droits ────────────────────────────────────────────────────────────────


def droits(got: Got) -> Markup:
    """La page : les ressources et leurs outils ; le détail d'une (``?detail=``) ; les droits exacts quand on a choisi
    qui (``?qui=``) et par quel canal (``?canal=``) ; les partages, et le jeton de leurs formulaires (``forms.csrf``)."""
    ui, query, forms = got.ui, got.query, got.forms
    all_whos = rights.whos(ui)
    who = next((w for w in all_whos if w.key == query.get("qui", "")), None)
    canal = query.get("canal", "") if query.get("canal", "") in dict(rights.CANAL_CHOICES) else ""
    granted = rights.exact(ui, who, canal) if who is not None and canal else None
    kept = "&".join(f"{k}={v}" for k, v in (("qui", who.key if who else ""), ("canal", canal)) if v)
    shown = rights.detail(ui, query["detail"]) if query.get("detail") else None
    listed, given = rights.sections(ui, granted, kept), rights.shared(ui)
    # « Retour » ramène à la ligne de la ressource, dans son sous-onglet
    back = next((r["id"] for s in listed for r in s["rows"] if shown and r["detail_key"] == query["detail"]), "")
    return Markup(env.get_template("handmade/droits/page.html").render(
        whos=[{"key": w.key, "label": w.label, "on": w is who} for w in all_whos],
        canals=[{"key": k, "label": label, "on": k == canal} for k, label in rights.CANAL_CHOICES],
        chosen=(who.label if who else "", dict(rights.CANAL_CHOICES).get(canal, "")), got=granted,
        canal_said=rights.what_of(granted["canal"]) if granted else "", sections=listed, kept=kept, back=back,
        detail=shown, fixed=rights.FIXED, tools=rights.fixed_tools(ui), catalogue=f"{catalog.BASE}/tous",
        shares=given, shares_pager=rights.one_page(len(given)), unshare=rights.UNSHARE, csrf=getattr(forms, "csrf", "")))


TABS: dict[str, Any] = {
    "reglages/comportement": Tab(comportement, *STYLES),
    f"reglages/{FACULTY_PAGE}*": Tab(faculte, *STYLES),
    "reglages/comptes": Tab(accounts, *STYLES),
    "reglages/journal": Tab(journal, *STYLES),
    "reglages/droits": Tab(droits, "handmade/tools.css", "handmade/rights.css", panel=False),
}
