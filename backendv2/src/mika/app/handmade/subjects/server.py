"""La fiche d'un service branché, dessinée (ADR 0121, 0123, 0129, 0130, 0131) : trois onglets — « En bref », puis
deux du plugin dessinés ici, « Accès aux outils » et « Ses outils » ; « État » et « Appels » sous « Le détail ».

« En bref » résume d'un regard : s'il marche (et ce qui attend ton regard, ses outils non servis compris), ses lignes
d'accès (leur « Changer » est le seul lien de l'onglet vers « Accès aux outils »), ce qu'elle en lit pour décider de
s'en servir, pour qui et quand ; le côté technique replié. Qui peut quoi se règle en un tableau de lignes lues de haut
en bas, comme les règles d'un pare-feu, puis la ligne par défaut (ADR 0131), dans les colonnes et les mots des tableaux
de ses familles (``vocab.access``, ADR 0134 : « Un outil qui lit », « Ce qu'elle en garde », « un savoir »…) ; un
outil se règle sur sa ligne de « Ses outils » (servi, il lit ou il agit, ce qu'elle lit de lui), qui dit aussi ce
qu'il fait devant chacun : la règle du moteur (``access_for``) sur des personnes types (``console.faces``), jamais une
recopie — « En bref » ne le redit plus (audit du 2026-11-05, C6-Q1).

Un serveur réglé à la main a « Modifier la connexion » (sa page dans Ses outils › Paramètres). Celui qu'un plugin
système apporte (``ServerStatus.plugin``, ADR 0066) suit les paramètres de ce plugin : sa fiche y mène (« Régler son
plugin ») ; seuls ses accès se règlent ici (ADR 0131).
"""

from __future__ import annotations

import json
from typing import Any

from markupsafe import Markup

from mika.app.handmade.access import (
    KEEP_CHOICES,
    POLICY_CHOICES,
    canal_choices,
    canal_instances,
    people_with_accounts,
    who_choices,
)
from mika.inspector import render
from mika.inspector.pages import tools as catalog
from mika.inspector.pages.params import faculty_url
from mika.inspector.pages.subjects import subject_url
from mika.inspector.ui import UI, Overview, env
from mika.kernel.inspect import Pager, Ref, When, plural
from mika.plugins.mcp import access_for
from mika.plugins.mcp.inspect import (
    STATE_TONES,
    access_said,
    closeness,
    edit_server,
    faces,
    owner_name,
    said_level,
    serves_nobody,
    tool_state,
    tool_view,
    when_label,
    who_label,
    who_said,
)
from mika.ports.mcp import STATES
from mika.runtime.tool_offer import deferred, gate_of
from mika.vocab.access import KEEP_WORDS, MOMENTS, NO, PERSON, POLICY_WORDS
from mika.vocab.episodes import Kind

KIND = "serveur"
#: la ligne par défaut, dans la colonne « Qui » du résumé : comme dans les tableaux
DEFAULT_WHO = "Comportement par défaut"
#: les moments d'une ligne, dans sa liste à cocher
MOMENT_CHOICES = tuple((k, label[:1].upper() + label[1:]) for k, label in MOMENTS)
#: ce qu'un outil laisse voir de sa description dans une liste ; la suite se déplie
SHORT = 220
#: ce que le serveur dit d'un outil (ses annotations, quand il les donne) : une donnée, montrée telle quelle
HINTS = (("readOnlyHint", True, "le serveur dit : lecture seule", "info"),
         ("destructiveHint", True, "le serveur dit : peut détruire", "danger"),
         ("openWorldHint", True, "le serveur dit : touche le monde extérieur", "warn"))
#: le pluriel du mot d'un outil non servi (``tool_state``), dans « En bref » : « 2 désactivés » ; un mot absent ne
#: change pas (« à regarder »)
STATE_PLURALS = {"désactivé": "désactivés", "disparu": "disparus", "approuvé, disparu": "approuvés, disparus",
                 "changé : suspendu": "changés : suspendus"}


def _capital(text: str) -> str:
    return text[:1].upper() + text[1:]


def _short(text: str, size: int = SHORT) -> tuple[str, str]:
    """(le début, coupé à un mot avec « … » ; le texte entier s'il a été coupé, sinon rien)."""
    text = _capital(" ".join(text.split()))
    if len(text) <= size:
        return text, ""
    cut = text[:size].rsplit(" ", 1)[0].rstrip(" ,;:.")
    return cut + "…", text


def _form(forms: Any, action: str) -> Any:
    """Le formulaire que la console a préparé pour une action de l'onglet (son jeton, son retour)."""
    return next((v for k, v in dict(forms or {}).items() if k.split("|", 1)[0] == action), None)


def _refused(key: str) -> str:
    """Pourquoi ses outils sont refusés dans une situation, en mots de ses lignes d'accès."""
    if key == "inconnue":
        return "jamais avec une inconnue, quelles que soient ses lignes"
    if key == "salon":
        return "jamais dans un salon, quelles que soient ses lignes"
    return "aucune ligne d'accès ne le laisse servir ici"


#: sur quoi elle travaille quand un service ne sert que si l'épisode l'a pris
TAKEN = {Kind.STEP: "si le but ou le projet a pris ce service", Kind.WORK: "si le but ou le projet a pris ce service",
         Kind.TASK: "si la tâche a pris ce service"}


def _where(ui: UI, st: Any) -> list[dict[str, Any]]:
    """Pour qui et quand, situation par situation : ce que la porte d'offre lui donne des outils de ce service
    (celle de « Ce qu'elle peut faire », les règles des opérateurs comprises) ; sinon, pourquoi pas."""
    port, registry, policies = ui.kernel.ports.get("mcp"), ui.kernel.registry, ui.kernel.runner.policies
    specs = [registry.tools[t.name] for t in port.offered() if t.server == st.name and t.name in registry.tools]
    out: list[dict[str, Any]] = []
    for s in catalog.situations(ui):
        moment = catalog.MOMENTS.get(s.kind, catalog.ALONE)
        if not out or out[-1]["moment"] != moment:
            out.append({"moment": moment, "rows": []})
        offered = catalog.offered_in(ui, s)
        rights, _close = gate_of(ui.kernel.registry)
        got = [x for x in specs if x.name in offered]
        core = catalog.in_hand(ui, policies[s.kind])
        if got:
            asked = sum(1 for x in got if deferred(x, core, rights))
            how = "" if core is None else "à chercher" if asked == len(got) else \
                "sous la main" if not asked else f"{asked} à chercher"
            how = ", ".join(filter(None, (how, TAKEN.get(s.kind, ""))))
            row = {"yes": True, "said": f"{len(got)} outil{'s' if len(got) > 1 else ''}", "how": how}
        else:
            why = catalog.why_not(specs[0], policies[s.kind], s) if specs else "aucun outil servi"
            if specs and why == catalog.condition(specs[0]):
                why = _refused(s.key)
            row = {"yes": False, "said": "non", "how": why}
        out[-1]["rows"].append({"label": s.short, "title": s.label, **row})
    return out


def _cells(st: Any, remote: str, nature: str, columns: list[Any], frame: Any) -> list[dict[str, str]]:
    """Ce qu'un outil fait devant chaque colonne, et ce qu'elle en garde : la règle du moteur, en mots."""
    tool = tool_view(st, remote, nature)
    out = []
    for f in columns:
        level, keep = access_for(tool, f.audience, f.kind, closeness(f, frame))
        word, note, tone = said_level(level, f)
        out.append({"label": f.label, "word": word, "note": note, "tone": tone,
                    "keep": KEEP_WORDS[keep] if level != NO else ""})
    return out


def _nature_of(st: Any, remote: str) -> str:
    """Il lit ou il agit : ce que tu en as décidé, sinon ce qu'en dit le serveur."""
    review = st.reviews.get(remote)
    if review is not None:
        return review.nature
    tool = next((t for t in st.live if t.remote == remote), None)
    return "lecture" if tool is not None and tool.read_only_hint else "action"


def _alerts(st: Any, access_tab: str) -> list[dict[str, str]]:
    """Ce que ses lignes ne disent pas d'elles-mêmes : il ne sert à personne."""
    if not serves_nobody(st):
        return []
    return [{"tone": "danger", "href": access_tab, "link": "Ajouter un accès aux outils",
             "text": "Il ne sert à personne : aucune ligne d'accès ne l'ouvre, et le comportement par défaut est "
                     "fermé."}]


def _plugin_settings(ui: UI, plugin: str) -> str:
    """Les paramètres du plugin qui apporte un serveur du système ; rien s'il n'en a pas (ou n'est pas composé)."""
    faculty = ui.kernel.registry.faculties.get(plugin)
    return faculty_url(plugin) if faculty is not None and faculty.params is not None else ""


def _summary(st: Any, frame: Any) -> list[dict[str, str]]:
    """Ses lignes d'accès, lisibles d'un regard (« En bref »), dans les mots des familles (``vocab.access``) : la
    dernière est le comportement par défaut, nommé ainsi."""
    return [{"who": who_label(a.who, frame) if a.who else DEFAULT_WHO, "when": _capital(when_label(a.when)),
             "read": POLICY_WORDS[a.read], "act": POLICY_WORDS[a.act], "keep": KEEP_WORDS[a.keep],
             "tools": "tous" if not a.tools else ", ".join(a.tools), "default": not a.who}
            for a in (*st.access, st.default)]


class ServerOverview(Overview):
    """« En bref » : le premier onglet de la fiche d'un service branché, d'un regard — qui peut quoi, outil par
    outil, est dans « Ses outils » (audit du 2026-11-05, C6-Q1) ; « État », qu'il résume, et « Appels » passent au
    bout de la barre, sous « Le détail »."""

    slug = "ensemble"
    title = "En bref"
    description = "S'il marche, ses accès, ce qu'elle en lit, pour qui et quand."
    styles = ("handmade/outils.css",)
    folded = ("etat", "appels")

    def head(self, ui: UI, key: str) -> Markup | None:
        """Son en-tête, sur tous ses onglets : son nom, à quoi il lui sert, où il en est, et ses réglages en bouton
        (la console y ajoute « Tester la connexion »)."""
        port = ui.kernel.ports.get("mcp")
        st = port.status(key) if port is not None else None
        if st is None:
            return None
        review = len(st.new) + len(st.changed)
        frame = ui.kernel.mind.frame()
        tags = [(STATES.get(st.state, st.state), STATE_TONES.get(st.state, "")),
                ("sur cette machine" if st.kind == "local" else "à une adresse", "info"),
                (f"avec {who_said(st, frame)}", "danger" if serves_nobody(st) else "info")]
        if st.owner.startswith(PERSON):  # branché par une personne sous son compte (ADR 0192)
            tags.insert(0, (f"à {owner_name(st, frame)}", "info"))
        if review:
            tags.append((f"{review} outil{'s' if review > 1 else ''} à revoir", "warn"))
        return Markup(env.get_template("handmade/outils/serveur_tete.html").render(
            name=st.name, purpose=_capital(st.purpose.strip()), tags=tags))

    def links(self, ui: UI, key: str) -> list[tuple[str, str]]:
        """« Modifier la connexion » (comment le joindre), à côté de « Tester la connexion » ; pour un serveur du
        système, « Régler son plugin » (s'il a des paramètres) : rien de lui ne se règle comme un serveur ajouté."""
        port = ui.kernel.ports.get("mcp")
        st = port.status(key) if port is not None else None
        if st is None:
            return []
        if st.plugin:
            plugin = _plugin_settings(ui, st.plugin)
            return [("Régler son plugin", plugin)] if plugin else []
        return [("Modifier la connexion", render.href(edit_server(key, Ref.subject(KIND, key, "")), ui.env()))]

    def render(self, ui: UI, key: str) -> Markup | None:
        port = ui.kernel.ports.get("mcp")
        st = port.status(key) if port is not None else None
        if st is None:
            return None
        shown = ui.env(ui.when)
        frame = ui.kernel.mind.frame()

        def ago(at: int) -> str:
            return render.cell(When(at), shown)["text"] if at else ""

        tools_tab, access_tab = subject_url(KIND, key, "outils"), subject_url(KIND, key, "fait")
        # ce qu'elle en lit : écrit à la main pour un serveur ajouté ; un serveur du système le tient de son plugin
        settings = "" if st.plugin else render.href(edit_server(key, Ref.subject(KIND, key, "")), shown)
        served = sum(1 for t in port.offered() if t.server == key)
        review = len(st.new) + len(st.changed)
        alerts = []
        if st.state == "panne":
            alerts.append({"tone": "danger", "text": "En panne : ses outils ne lui sont plus offerts. « Tester la "
                                                     "connexion » le relance s'il répond."})
        if st.detail:
            alerts.append({"tone": "danger" if st.state == "panne" else "warn", "text": st.detail})
        if review:
            alerts.append({"tone": "warn", "href": tools_tab, "link": "Les regarder",
                           "text": f"{review} outil{'s' if review > 1 else ''} à revoir : "
                                   f"nouveau{'x' if review > 1 else ''} ou changé{'s' if review > 1 else ''} "
                                   "depuis ton accord."})
        # le « Changer » de ses lignes d'accès, juste dessous, est le seul lien de l'onglet vers « Accès aux outils »
        alerts += _alerts(st, "")
        # ses outils non servis, d'un mot (« 1 à regarder ») ; qui peut quoi, outil par outil, est dans « Ses outils »
        live = {t.remote for t in st.live}
        states: dict[str, int] = {}
        for remote in [t.remote for t in st.live] + [r for r in st.reviews if r not in live]:
            word = tool_state(st, remote)[0]
            if word != "servi":
                states[word] = states.get(word, 0) + 1
        technical = [
            ("le serveur dit être", f"{st.server_name} {st.server_version}".strip() or "—"),
            ("protocole", st.protocol or "—"),
            ("joint", ui.when(st.last_ok_at) if st.last_ok_at else "jamais"),
            ("dernière panne", ui.when(st.last_error_at) if st.last_error_at else "aucune"),
            ("pannes d'affilée", str(st.consecutive)),
        ]
        situations = _where(ui, st)
        rows = max(1, sum(len(g["rows"]) for g in situations))
        return Markup(env.get_template("handmade/outils/serveur.html").render(
            state=STATES.get(st.state, st.state), state_tone=STATE_TONES.get(st.state, ""),
            joined=ago(st.last_ok_at), served=served, live=len(st.live), review=review,
            calls=st.calls, failures=st.failures, alerts=alerts, access=_summary(st, frame),
            access_pager=render._pager(Pager(size=len(st.access) + 1, total=len(st.access) + 1), {}),
            access_said=access_said(st), access_tab=access_tab,
            purpose=_capital(st.purpose.strip()), when_to_use=_capital(st.when_to_use.strip()),
            states=[plural(n, word, STATE_PLURALS.get(word, word)) for word, n in sorted(states.items())],
            known=bool(st.live),
            situations=situations, who_pager=render._pager(Pager(size=rows, total=rows), {}),
            technical=technical, log=list(st.log), instructions=st.instructions,
            local=st.kind == "local", address=st.address, settings=settings, system=bool(st.plugin),
            tools_tab=tools_tab, calls_tab=subject_url(KIND, key, "appels")))

    tabs = ("fait", "outils")

    def render_tab(self, ui: UI, key: str, tab: str, blocks: Any, query: Any, forms: Any = None) -> Any:
        """« Accès aux outils » et « Ses outils », dessinés (ADR 0129, 0130, 0131) ; ``?outil=`` ouvre un outil."""
        port = ui.kernel.ports.get("mcp")
        st = port.status(key) if port is not None else None
        if st is None:
            return None
        if tab == "fait":
            return self._access(ui, st, forms)
        if tab == "outils":
            return self._tools(ui, st, forms, str(dict(query or {}).get("outil", "")))
        return None

    @staticmethod
    def _tools(ui: UI, st: Any, forms: Any, wanted: str = "") -> Markup:
        frame = ui.kernel.mind.frame()
        live = {t.remote: t for t in st.live}
        remotes = [t.remote for t in st.live] + [r for r in st.reviews if r not in live]
        columns = faces(st, frame)
        # ce qui attend un regard : nouveau ou changé, avec ce que le serveur en dit — rien ne se sert sans un choix
        waiting = []
        for remote in (*st.new, *st.changed):
            tool, review = live[remote], st.reviews.get(remote)
            said = [{"text": text, "tone": tone} for key, value, text, tone in HINTS
                    if tool.annotations.get(key) is value]
            if "readOnlyHint" not in tool.annotations:
                said.append({"text": "le serveur ne dit pas s'il lit ou agit", "tone": "muted"})
            before = review.server_description if review is not None else ""
            waiting.append({
                "name": remote, "what": _capital(" ".join(tool.description.split())) or "(sans description)",
                "said": said, "changed": review is not None,
                "before": _capital(" ".join(before.split())) if before and before != tool.description else "",
                "path": f"outils.{remote}",
                "current": "lecture" if review is None and tool.read_only_hint else ""})
        groups: dict[str, list[dict[str, Any]]] = {"lecture": [], "action": []}
        for remote in remotes:
            if remote in st.new:
                continue
            tool, review = live.get(remote), st.reviews.get(remote)
            word, tone = tool_state(st, remote)
            nature = _nature_of(st, remote)
            what, full = _short((review.description if review is not None and review.description else "") or (
                tool.description if tool is not None else (review.server_description if review else "")))
            served = review is not None and review.enabled and word == "servi"
            slot = json.dumps(remote)
            form = next((v for k, v in dict(forms or {}).items()
                         if k.startswith("mcp.regler|") and f'"outil": {slot}' in k), None)
            cells = [c for c in _cells(st, remote, nature, columns, frame) if c["word"] != "non"] if served else []
            groups[nature].append({
                "name": remote, "what": what, "full": full, "state": word, "tone": tone, "cells": cells,
                "closed": served and not cells, "open": remote == wanted,
                "edit": {"form": form, "actif": review.enabled if review is not None else True, "nature": nature,
                         "description": review.description if review is not None else ""}
                if form is not None else None})
        notes = []
        if not st.live:
            notes.append({"tone": "warn", "text": "La liste de ses outils n'est pas connue : « Tester la connexion » "
                                                  "la charge."})
        access_tab = subject_url(KIND, st.name, "fait")
        return Markup(env.get_template("handmade/outils/outils.html").render(
            access_said=access_said(st), access_tab=access_tab, waiting=waiting,
            decide_form=_form(forms, "mcp.revoir"), notes=notes, alerts=_alerts(st, access_tab), groups=[
                {"key": "lit", "title": "Ce qui lit", "hint": "rien ne change ailleurs", "tools": groups["lecture"],
                 "empty": "Aucun outil qui lit."},
                {"key": "agit", "title": "Ce qui agit", "hint": "ça change quelque chose ailleurs",
                 "tools": groups["action"], "empty": "Aucun outil qui agit."}]))

    @staticmethod
    def _access(ui: UI, st: Any, forms: Any) -> Markup:
        """« Accès aux outils » (ADR 0131) : un tableau de lignes lues de haut en bas — qui, quand, ce qu'elle fait
        d'un outil qui lit et d'un outil qui agit, ce qu'elle en garde, à quels outils —, puis le comportement par
        défaut, obligatoire ; ses choix sont ceux des familles (``vocab.access``). Chaque bouton envoie tout le tableau
        (rien de ce qu'on a changé ne se perd)."""
        frame = ui.kernel.mind.frame()
        people, instances = people_with_accounts(ui), canal_instances(ui)
        known = list(dict.fromkeys([*(t.remote for t in st.live), *st.reviews]))
        rows = []
        for n, a in enumerate(st.access, start=1):
            chosen = set(a.tools)
            rows.append({
                "n": n, "who": who_choices(a.who, people, lambda person: who_label((PERSON + person,), frame),
                                           ui.her_name(), a.canal),
                "canal": canal_choices(a.canal, instances), "always": not a.when,
                "moments": [{"key": k, "label": label, "on": k in a.when} for k, label in MOMENT_CHOICES],
                "read": a.read, "act": a.act, "keep": a.keep, "all": not a.tools,
                "tools": [{"name": r, "nature": "lit" if _nature_of(st, r) == "lecture" else "agit",
                           "on": r in chosen, "state": tool_state(st, r)[0]} for r in known],
                "first": n == 1, "last": n == len(st.access)})
        return Markup(env.get_template("handmade/outils/fait.html").render(
            rows=rows, default=st.default, policies=POLICY_CHOICES, keeps=KEEP_CHOICES,
            pager=render._pager(Pager(size=len(rows) + 1, total=len(rows) + 1), {}),
            form=_form(forms, "mcp.acces"), system=bool(st.plugin), known=bool(known),
            alerts=_alerts(st, ""), tools_tab=subject_url(KIND, st.name, "outils")))
