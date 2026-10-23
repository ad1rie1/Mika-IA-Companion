"""La fiche d'un service branché, dessinée (ADR 0121, 0123, 0128, 0129, 0130) : trois onglets — « En bref », puis deux
du plugin dessinés ici, « Réglages du service » et « Ses outils » ; « État » et « Appels » sous « Le détail ».

S'il marche (et ce qui attend ton regard), ses réglages en quatre réponses, ce qu'elle en lit pour décider de s'en
servir, qui peut quoi outil par outil, pour qui et quand ; le côté technique replié. Un outil se règle sur sa ligne,
d'un seul envoi, ses exceptions par situation et par personne repliées. Ce qu'un outil fait devant quelqu'un se
calcule par la règle du moteur (``level_of``) sur des personnes types (``console.faces``), jamais par une recopie.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote, urlencode

from markupsafe import Markup

from mika.adapters.mcp.system import BY as SYSTEM_BY
from mika.contracts import identity as identity_c
from mika.faculties.identity.faculty import known_as
from mika.faculties.identity.inspect import people as people_of
from mika.inspector import render
from mika.inspector.pages import tools as catalog
from mika.inspector.pages.subjects import fiche_url
from mika.inspector.ui import UI, Overview, env
from mika.kernel.inspect import Pager, When
from mika.plugins.mcp import level_of
from mika.plugins.mcp.console import (
    AS_SERVICE,
    AS_SITUATION,
    GENRES,
    PEOPLE_SLOTS,
    STATE_TONES,
    drift,
    edit_server,
    faces,
    genre_of,
    looser_tools,
    rules_of,
    said_level,
    sentence,
    serves_nobody,
    tool_state,
    who_said,
)
from mika.ports.mcp import AUTONOMIES, KEEPS, RULE_LEVELS, STATES, TOOL_SITUATIONS, tool_autonomy, tool_keep
from mika.runtime.tools import deferred
from mika.vocab.episodes import Kind
from mika.vocab.people import ACCOUNT_PREFIX

KIND = "serveur"
#: « Avant de se servir d'un de ses outils, elle… » (ADR 0130) : ce qu'elle fait seule, en mots simples
BEFORE = {"seule": ("ne demande pas", "l'appel part aussitôt"),
          "lit": ("lit sans demander, demande avant d'agir", "lire ne change rien ; créer, envoyer, supprimer : un accord"),
          "carte": ("demande à la personne en face", "une carte dans son chat ; quand elle travaille seule, la demande "
                                                     "t'attend dans la console"),
          "toi": ("te demande, à toi", "une carte dans ton chat si c'est toi en face ; sinon la demande t'attend dans "
                                       "la console (« À valider »)")}
#: « Ce qu'elle y lit, elle… » : ce qu'elle en garde, en mots simples
KEPT = {"public": ("peut l'apprendre et le raconter", "ça devient ce qu'elle sait"),
        "perso": ("s'en souvient", "comme de ce qu'on lui raconte"),
        "prive": ("le garde comme une confidence", "elle en reparle avec la personne, jamais avec quelqu'un d'autre"),
        "rien": ("l'oublie aussitôt", "elle s'en sert sur le moment, rien n'est gardé")}
#: ce qu'elle pourra en redire plus tard à quelqu'un d'autre, par niveau gardé
LATER = {"public": "elle peut le raconter", "perso": "en grande confiance, une anecdote peut échapper",
         "prive": "jamais", "rien": "rien n'est gardé"}
#: une situation d'outil, en clair (« toi » se dit d'après les moments du service)
SITUATION_HINTS = {"compte": "connectée à l'app ou au web, en tête-à-tête",
                   "travail": "un projet ou un but qui a pris ce service"}
#: ce qu'un outil laisse voir de sa description dans une liste ; la suite se déplie
SHORT = 220
#: ce que le serveur dit d'un outil (ses annotations, quand il les donne) : une donnée, montrée telle quelle
HINTS = (("readOnlyHint", True, "le serveur dit : lecture seule", "info"),
         ("destructiveHint", True, "le serveur dit : peut détruire", "danger"),
         ("openWorldHint", True, "le serveur dit : touche le monde extérieur", "warn"))


def _word(choices: tuple[tuple[str, str], ...], value: str) -> str:
    return next((label.split(" — ")[0] for key, label in choices if key == value), value)


def _capital(text: str) -> str:
    return text[:1].upper() + text[1:]


def _short(text: str, size: int = SHORT) -> tuple[str, str]:
    """(le début, coupé à un mot avec « … » ; le texte entier s'il a été coupé, sinon rien)."""
    text = _capital(" ".join(text.split()))
    if len(text) <= size:
        return text, ""
    cut = text[:size].rsplit(" ", 1)[0].rstrip(" ,;:.")
    return cut + "…", text


def _steps(choices: tuple[tuple[str, str], ...], words: dict[str, tuple[str, str]],
           later: dict[str, str] | None = None) -> list[dict[str, str]]:
    """Une échelle de choix en mots simples (ce qu'elle fait, ce que ça veut dire), pour un gabarit."""
    return [{"key": k, "name": _capital(words[k][0]), "what": words[k][1], "later": (later or {}).get(k, "")}
            for k, _ in choices]


def genre_cards(current: str) -> list[dict[str, Any]]:
    """Les genres de service, en cartes : leur nom, un exemple, et leurs réponses (avec qui, avant un outil, ce qu'elle
    y lit)."""
    out = []
    for k, label, example, preset in GENRES:
        who = ("toi" if preset["with_owner"] else "une personne choisie") + (
            " et les comptes" if preset["with_accounts"] else " seul" if preset["with_owner"] else "")
        out.append({"key": k, "label": label, "example": _capital(example), "on": k == current, "who": f"Avec {who}",
                    "alone": _capital(BEFORE[preset["autonomy"]][0]), "keep": _capital(KEPT[preset["keep"]][0])})
    return out


def _form(forms: Any, action: str) -> Any:
    """Le formulaire que la console a préparé pour une action de l'onglet (son jeton, son retour)."""
    return next((v for k, v in dict(forms or {}).items() if k.split("|", 1)[0] == action), None)


def _people(ui: UI) -> list[dict[str, str]]:
    """Les personnes qu'on peut nommer : celles qui ont un compte (seules à pouvoir être authentifiées), par leur
    nom — jamais une propriétaire, que sa propre ligne (« Toi ») règle déjà."""
    frame = ui.kernel.mind.frame()
    try:
        s = frame.state("identity")
    except KeyError:
        return []
    out = [{"key": person, "name": known_as(s, person)} for person, handles in people_of(s, frame).items()
           if any(str(h).startswith(ACCOUNT_PREFIX) for h in (*handles, person))
           and not frame.get(identity_c.IS_OWNER(person))]
    return sorted(out, key=lambda p: p["name"].casefold())


def _when(st: Any) -> str:
    """Quand elle s'en sert, d'après les moments du service."""
    return ", ".join(w for e, w in (("conversation", "quand elle répond"), ("initiative", "quand elle prend la parole"),
                                    ("travail", "quand elle travaille seule")) if e in st.episodes) or "jamais"


def _talks(st: Any) -> str:
    """Quand elle s'en sert devant toi, d'après les moments du service (vide : jamais)."""
    return " ou ".join(w for e, w in (("conversation", "quand elle te répond"),
                                      ("initiative", "quand elle te parle d'elle-même")) if e in st.episodes)


def _closed(st: Any, situation: str) -> str:
    """Pourquoi le service ferme une situation à ses outils (vide : il l'ouvre)."""
    if situation in ("proprietaire", "travail") and not st.with_owner:
        return "fermé par le service : il n'est pas avec toi"
    if situation == "proprietaire" and not _talks(st):
        return "fermé par le service : ni quand elle répond, ni quand elle prend la parole"
    if situation == "travail" and "travail" not in st.episodes:
        return "fermé par le service : pas quand elle travaille"
    if situation == "compte" and not st.with_accounts and not st.with_people:
        return "fermé par le service : ni les comptes, ni personne de choisi"
    return ""


def _refused(st: Any, key: str) -> str:
    """Pourquoi la condition de ses outils les refuse dans une situation de la grille, en mots du service."""
    if key == "inconnue":
        return "jamais avec une inconnue, quel que soit le réglage"
    if key == "salon":
        return "jamais dans un salon, quel que soit le réglage"
    where = {"proprietaire": "proprietaire", "initiative": "proprietaire", "compte": "compte"}.get(key, "travail")
    if where == "compte" and not st.with_accounts and st.with_people:
        return "seulement les personnes choisies du service"
    return _closed(st, where) or "retiré par les règles de ses outils"


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
        offered, ruled = catalog.offered_in(ui, s), catalog.rules(ui, s)
        got = [x for x in specs if x.name in offered]
        core = catalog.in_hand(ui, policies[s.kind])
        if got:
            asked = sum(1 for x in got if deferred(x, core, ruled))
            how = "" if core is None else "à chercher" if asked == len(got) else \
                "sous la main" if not asked else f"{asked} à chercher"
            how = ", ".join(filter(None, (how, TAKEN.get(s.kind, ""))))
            row = {"yes": True, "said": f"{len(got)} outil{'s' if len(got) > 1 else ''}", "how": how}
        else:
            why = catalog.why_not(specs[0], policies[s.kind], s, ruled) if specs else "aucun outil servi"
            if specs and why == catalog.condition(specs[0]):
                why = _refused(st, s.key)
            row = {"yes": False, "said": "non", "how": why}
        out[-1]["rows"].append({"label": s.short, "title": s.label, **row})
    return out


def _named(st: Any) -> tuple[str, ...]:
    """Les personnes que nomment les règles de ses outils servis."""
    return tuple(dict.fromkeys(p for v in st.reviews.values() if v.enabled for p in v.people))


def _cells(st: Any, review: Any, columns: list[Any]) -> list[dict[str, str]]:
    """Ce qu'un outil fait devant chaque colonne : la règle du moteur, en mots."""
    rules = rules_of(st, review)
    out = []
    for f in columns:
        word, note, tone = said_level(level_of(rules, f.audience), f)
        out.append({"label": f.label, "word": word, "note": note, "tone": tone})
    return out


def _keep_of(st: Any, review: Any) -> dict[str, Any]:
    keep = tool_keep(st.keep, review.keep)
    return {"word": _word(KEEPS, keep), "own": keep != st.keep}


def _rule_words(where: str) -> dict[str, str]:
    """Une exception, dans une situation : ce qu'elle fait. Devant toi, et sans personne en face, « carte » et « ton
    accord » reviennent au même — c'est toi qui décides."""
    if where == "compte":
        return {"seule": "ne demande pas", "carte": "lui demande, à elle", "toi": "te demande, à toi (dans la console)",
                "non": "ne s'en sert pas"}
    asks = "te demande" if where == "proprietaire" else "te demande (dans la console)"
    return {"seule": "ne demande pas", "carte": asks, "toi": asks, "non": "ne s'en sert pas"}


def _rule_options(where: str, current: str, empty: tuple[str, str]) -> tuple[tuple[str, str], ...]:
    """Les choix d'une exception : sans exception, puis ce qui a un sens dans cette situation (et la valeur actuelle)."""
    words = _rule_words(where)
    keep = [k for k, _ in RULE_LEVELS if where == "compte" or k != "carte" or current == "carte"]
    return (empty, *((k, words[k]) for k in keep))


def _editor(st: Any, review: Any, nature: str, form: Any, people: list[dict[str, str]]) -> dict[str, Any]:
    """Le réglage d'un outil sur sa ligne (ADR 0130), d'un seul envoi : servi, lit ou agit, avant de s'en servir,
    ce qu'elle en retient, ce qu'elle lit de lui — puis ses exceptions, par situation et par personne."""
    base = tool_autonomy(st.autonomy, "service", nature)
    own = review.autonomy if review is not None else "service"
    level = tool_autonomy(st.autonomy, own, nature)
    said = dict(review.situations) if review is not None else {}
    situations = []
    for k, label in TOOL_SITUATIONS:
        hint = (_talks(st) or "jamais") if k == "proprietaire" else SITUATION_HINTS.get(k, "")
        if k == "compte" and not st.with_accounts and st.with_people:
            hint += " — seulement les personnes choisies du service"
        value = said.get(k, AS_SERVICE)
        situations.append({"path": f"s_{k}", "label": _capital(label), "hint": hint, "why": _closed(st, k),
                           "value": value, "options": _rule_options(
                               k, value, (AS_SERVICE, f"pas d'exception : {_rule_words(k)[level]}"))})
    named = list(review.people.items())[:PEOPLE_SLOTS] if review is not None else []
    slots = [{"person_path": f"p{i + 1}", "level_path": f"r{i + 1}", "person": who, "level": value,
              "outside": not (st.with_accounts or who in st.with_people)} for i, (who, value) in enumerate(named)]
    if len(slots) < PEOPLE_SLOTS:
        n = len(slots) + 1
        slots.append({"person_path": f"p{n}", "level_path": f"r{n}", "person": "", "level": AS_SITUATION,
                      "outside": False})
    words = _rule_words("compte")
    return {
        "form": form, "actif": review.enabled if review is not None else True, "nature": nature,
        "before": ((AS_SERVICE, f"comme le service : {BEFORE[base][0]}"),
                   *((k, BEFORE[k][0]) for k in ("seule", "carte", "toi"))), "own": own,
        "kept": ((AS_SERVICE, f"comme le service : {KEPT[st.keep][0]}"), *((k, KEPT[k][0]) for k, _ in KEEPS)),
        "keep": review.keep if review is not None else AS_SERVICE,
        "description": review.description if review is not None else "",
        "situations": situations, "slots": slots, "people": people, "people_keys": [p["key"] for p in people],
        "person_options": ((AS_SITUATION, "comme sa situation"), *((k, words[k]) for k, _ in RULE_LEVELS)),
        "rules": len(said) + len(named)}


def _tool_url(server: str, remote: str) -> str:
    """Un outil ouvert sur sa ligne, dans « Ses outils »."""
    return fiche_url(KIND, server, "outils") + "&" + urlencode({"outil": remote}) + "#" + quote(f"outil-{remote}")


def _alerts(st: Any, frame: Any, tools_tab: str, service_tab: str) -> list[dict[str, str]]:
    """Ce que son réglage ne dit pas de lui-même : il ne sert à personne, des outils plus libres que lui."""
    out = []
    if serves_nobody(st):
        out.append({"tone": "danger", "href": service_tab, "link": "Choisir avec qui",
                    "text": "Il ne sert à personne : ni toi, ni les comptes, ni une personne choisie."})
    looser = looser_tools(st, frame)
    if looser:
        n = len(looser)
        out.append({"tone": "warn", "href": tools_tab, "link": "Les voir",
                    "text": f"{n} outil{'s' if n > 1 else ''} plus libre{'s' if n > 1 else ''} que le service "
                            f"({', '.join(looser[:4])}{'…' if n > 4 else ''}) : son genre ne le dit pas."})
    return out


class ServerOverview(Overview):
    """« En bref » : le premier onglet de la fiche d'un service branché ; « État », qu'il résume, et « Appels »
    passent au bout de la barre, sous « Le détail »."""

    slug = "ensemble"
    title = "En bref"
    description = "S'il marche, ses réglages, ce qu'elle en lit, qui peut quoi, pour qui et quand."
    styles = ("handmade/tools.css",)
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
                (f"avec {who_said(st, frame)}", "danger" if serves_nobody(st) else "info"),
                (genre_of(st)[1], "owner")]
        looser = len(looser_tools(st, frame))
        if looser:
            tags.append((f"{looser} outil{'s' if looser > 1 else ''} plus libre{'s' if looser > 1 else ''}", "warn"))
        if review:
            tags.append((f"{review} outil{'s' if review > 1 else ''} à revoir", "warn"))
        return Markup(env.get_template("handmade/outils/serveur_tete.html").render(
            name=st.name, purpose=_capital(st.purpose.strip()), tags=tags))

    def links(self, ui: UI, key: str) -> list[tuple[str, str]]:
        """« Modifier la connexion » (comment le joindre), à côté de « Tester la connexion »."""
        port = ui.kernel.ports.get("mcp")
        if port is None or port.status(key) is None:
            return []
        return [("Modifier la connexion", render.href(edit_server(key, fiche_url(KIND, key))))]

    def render(self, ui: UI, key: str) -> Markup | None:
        port = ui.kernel.ports.get("mcp")
        st = port.status(key) if port is not None else None
        if st is None:
            return None
        shown = render.Env(when=ui.when, now=ui.now())
        frame = ui.kernel.mind.frame()

        def ago(at: int) -> str:
            return render.cell(When(at), shown)["text"] if at else ""

        tools_tab, service_tab = fiche_url(KIND, key, "outils"), fiche_url(KIND, key, "fait")
        settings = render.href(edit_server(key, fiche_url(KIND, key)))
        # la grille de « Ce qu'elle peut faire », ouverte sur la famille de ses outils : là où l'on en retire
        bundles = {ui.kernel.registry.tools[t.name].bundle for t in port.offered()
                   if t.server == key and t.name in ui.kernel.registry.tools}
        grid = f"{catalog.BASE}/tous?" + urlencode({"lot": next(iter(bundles))}) if len(bundles) == 1 else ""
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
        alerts += _alerts(st, frame, tools_tab, service_tab)
        # qui peut quoi : ses outils servis, devant chaque personne que le service ouvre
        columns = faces(st, frame, _named(st))
        live = {t.remote: t for t in st.live}
        matrix = []
        for remote, decided in st.reviews.items():
            if tool_state(st, remote)[0] != "servi":
                continue
            what, _ = _short(decided.description or decided.server_description or live[remote].description, 120)
            matrix.append({"name": remote, "what": what, "cells": _cells(st, decided, columns),
                           "keep": _keep_of(st, decided), "looser": bool(drift(st, decided, frame)[0]),
                           "rules": _tool_url(key, remote)})
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
            calls=st.calls, failures=st.failures, alerts=alerts, genre=genre_of(st)[1],
            sentence=sentence(st, frame), service_tab=service_tab,
            who=_capital(who_said(st, frame)), when=_capital(_when(st)), alone=BEFORE[st.autonomy][0],
            keep=KEPT[st.keep][0], keep_later=LATER.get(st.keep, ""),
            purpose=_capital(st.purpose.strip()), when_to_use=_capital(st.when_to_use.strip()),
            columns=[f.label for f in columns], matrix=matrix, states=sorted(states.items()), known=bool(st.live),
            matrix_pager=render._pager(Pager(size=max(1, len(matrix)), total=max(1, len(matrix))), {}),
            situations=situations, who_pager=render._pager(Pager(size=rows, total=rows), {}),
            technical=technical, log=list(st.log), instructions=st.instructions,
            local=st.kind == "local", address=st.address, settings=settings, tools_tab=tools_tab,
            calls_tab=fiche_url(KIND, key, "appels"), grid=grid))

    tabs = ("fait", "outils")

    def render_tab(self, ui: UI, key: str, tab: str, blocks: Any, query: Any, forms: Any = None) -> Any:
        """« Réglages du service » et « Ses outils », dessinés (ADR 0128, 0129, 0130) ; ``?outil=`` ouvre un outil."""
        port = ui.kernel.ports.get("mcp")
        st = port.status(key) if port is not None else None
        if st is None:
            return None
        if tab == "fait":
            return self._service(ui, st, forms)
        if tab == "outils":
            return self._tools(ui, st, forms, str(dict(query or {}).get("outil", "")))
        return None

    @staticmethod
    def _tools(ui: UI, st: Any, forms: Any, wanted: str = "") -> Markup:
        frame = ui.kernel.mind.frame()
        live = {t.remote: t for t in st.live}
        remotes = [t.remote for t in st.live] + [r for r in st.reviews if r not in live]
        columns = faces(st, frame, _named(st))
        people = _people(ui)
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
            nature = review.nature if review is not None else (
                "lecture" if tool is not None and tool.read_only_hint else "action")
            what, full = _short((review.description if review is not None and review.description else "") or (
                tool.description if tool is not None else (review.server_description if review else "")))
            n = len(review.situations) + len(review.people) if review is not None else 0
            served = review is not None and review.enabled and word == "servi"
            slot = json.dumps(remote)
            form = next((v for k, v in dict(forms or {}).items()
                         if k.startswith("mcp.regler|") and f'"outil": {slot}' in k), None)
            looser, stricter = drift(st, review, frame) if served else ([], [])
            groups[nature].append({
                "name": remote, "what": what, "full": full, "state": word, "tone": tone,
                "cells": _cells(st, review, columns) if served else [],
                "keep": _keep_of(st, review) if served else None,
                "looser": ", ".join(looser), "stricter": ", ".join(stricter),
                "rules": f"{n} exception{'s' if n > 1 else ''}" if n else "", "open": remote == wanted,
                "edit": _editor(st, review, nature, form, people) if form is not None else None})
        notes = []
        if not st.live:
            notes.append({"tone": "warn", "text": "La liste de ses outils n'est pas connue : « Tester la connexion » "
                                                  "la charge."})
        return Markup(env.get_template("handmade/outils/outils.html").render(
            alone=BEFORE[st.autonomy][0], keep=KEPT[st.keep][0], genre=genre_of(st)[1],
            service_tab=fiche_url(KIND, st.name, "fait"), waiting=waiting, decide_form=_form(forms, "mcp.revoir"),
            notes=notes, alerts=_alerts(st, frame, "", fiche_url(KIND, st.name, "fait")), groups=[
                {"key": "lit", "title": "Ce qui lit", "hint": "rien ne change ailleurs", "tools": groups["lecture"],
                 "empty": "Aucun outil qui lit."},
                {"key": "agit", "title": "Ce qui agit", "hint": "ça change quelque chose ailleurs",
                 "tools": groups["action"], "empty": "Aucun outil qui agit."}]))

    @staticmethod
    def _service(ui: UI, st: Any, forms: Any) -> Markup:
        frame = ui.kernel.mind.frame()
        genre_key, genre = genre_of(st)
        genres = genre_cards(genre_key)
        people = _people(ui)
        chosen = list(st.with_people[:PEOPLE_SLOTS])
        slots = [{"path": f"qui{i + 1}", "value": v} for i, v in enumerate(chosen)]
        if len(slots) < PEOPLE_SLOTS:
            slots.append({"path": f"qui{len(slots) + 1}", "value": ""})
        system = bool(st.reviews) and all(v.by == SYSTEM_BY for v in st.reviews.values())
        return Markup(env.get_template("handmade/outils/fait.html").render(
            sentence=sentence(st, frame), genre=_capital(genre), genres=genres, genre_form=_form(forms, "mcp.genre"),
            form=_form(forms, "mcp.service"), system=system, with_owner=st.with_owner,
            with_accounts=st.with_accounts, episodes=tuple(st.episodes), people=people,
            people_keys=[p["key"] for p in people], people_slots=slots, autonomies=_steps(AUTONOMIES, BEFORE),
            autonomy=st.autonomy, keeps=_steps(KEEPS, KEPT, LATER), keep=st.keep,
            alerts=_alerts(st, frame, fiche_url(KIND, st.name, "outils"), "")))
