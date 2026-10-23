"""La fiche d'un service branché, dessinée (ADR 0121, 0123, 0128) : son premier onglet, « En bref », et deux onglets
du plugin dessinés ici — « Ce qu'elle en fait » et « Par situation et par personne ».

S'il marche (et ce qui attend ton regard), ce qu'elle en fait en une phrase, ce qu'elle en lit pour décider de s'en
servir, ses outils et ce que tu en as décidé, pour qui et quand ; le côté technique replié. Lu au port MCP, comme les
onglets du plugin, qui restent à un clic (« État » sous « Le détail », « Ses outils » pour les régler, « Appels »).
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

from markupsafe import Markup

from mika.adapters.mcp.system import BY as SYSTEM_BY
from mika.faculties.identity.faculty import known_as
from mika.faculties.identity.inspect import people as people_of
from mika.inspector import render
from mika.inspector.pages import tools as catalog
from mika.inspector.pages.subjects import fiche_url
from mika.inspector.ui import UI, Overview, env
from mika.kernel.inspect import Pager, When
from mika.plugins.mcp.console import (
    AS_SERVICE,
    AS_SITUATION,
    GENRES,
    PEOPLE_SLOTS,
    STATE_TONES,
    WORDS,
    edit_server,
    genre_of,
    name_of,
    sentence,
    tool_state,
    who_said,
)
from mika.ports.mcp import AUTONOMIES, KEEPS, NATURES, RULE_LEVELS, STATES, TOOL_SITUATIONS
from mika.runtime.tools import deferred
from mika.vocab.episodes import Kind
from mika.vocab.people import ACCOUNT_PREFIX

KIND = "serveur"
#: ce qu'un accord veut dire, dans « En clair »
SAY = {"seule": "oui, elle s'en sert seule", "carte": "oui, sur accord de la personne", "toi": "oui, avec ton accord",
       "non": "non"}
#: ce qu'elle pourra en redire plus tard à quelqu'un d'autre, par niveau gardé
LATER = {"public": "elle peut le raconter", "perso": "en grande confiance, une anecdote peut échapper",
         "prive": "jamais", "rien": "rien : rien n'est gardé"}
#: une situation d'outil, en clair
SITUATION_HINTS = {"proprietaire": "quand elle te répond ou te parle", "compte": "authentifiée, en tête-à-tête",
                   "travail": "un projet ou un but qui a pris ce service"}


def _word(choices: tuple[tuple[str, str], ...], value: str) -> str:
    return next((label.split(" — ")[0] for key, label in choices if key == value), value)


def _capital(text: str) -> str:
    return text[:1].upper() + text[1:]


def _steps(choices: tuple[tuple[str, str], ...], later: dict[str, str] | None = None) -> list[dict[str, str]]:
    """Une échelle de choix (« nom — ce que c'est »), pour un gabarit."""
    out = []
    for k, label in choices:
        name, _, what = label.partition(" — ")
        out.append({"key": k, "name": _capital(name), "what": what, "later": (later or {}).get(k, "")})
    return out


def genre_cards(current: str) -> list[dict[str, Any]]:
    """Les genres de service, en cartes : leur nom, un exemple, et ce qu'ils règlent (avec qui, seule, ce qu'elle garde)."""
    out = []
    for k, label, example, preset in GENRES:
        who = ("toi" if preset["with_owner"] else "une personne choisie") + (
            " et les comptes" if preset["with_accounts"] else " seul" if preset["with_owner"] else "")
        out.append({"key": k, "label": label, "example": _capital(example), "on": k == current, "who": f"Avec {who}",
                    "alone": _capital(WORDS.get(preset["autonomy"], "")), "keep": f"Garde : {_word(KEEPS, preset['keep'])}"})
    return out


def _form(forms: Any, action: str) -> Any:
    """Le formulaire que la console a préparé pour une action de l'onglet (son jeton, son retour)."""
    return next((v for k, v in dict(forms or {}).items() if k.split("|", 1)[0] == action), None)


def _people(ui: UI) -> list[dict[str, str]]:
    """Les personnes qu'on peut nommer : celles qui ont un compte (seules à pouvoir être authentifiées), par leur
    nom."""
    frame = ui.kernel.mind.frame()
    try:
        s = frame.state("identity")
    except KeyError:
        return []
    out = [{"key": person, "name": known_as(s, person)} for person, handles in people_of(s, frame).items()
           if any(str(h).startswith(ACCOUNT_PREFIX) for h in (*handles, person))]
    return sorted(out, key=lambda p: p["name"].casefold())


def default_level(st: Any, review: Any) -> str:
    """L'accord d'un outil hors de toute règle de situation ou de personne : le sien, sinon celui de son service."""
    if review.autonomy != "service":
        return str(review.autonomy)
    if st.autonomy == "lit":
        return "seule" if review.nature == "lecture" else "carte"
    return str(st.autonomy)


def _closed(st: Any, situation: str) -> str:
    """Pourquoi le service ferme une situation à ses outils (vide : il l'ouvre)."""
    if situation in ("proprietaire", "travail") and not st.with_owner:
        return "fermé par le service : il n'est pas avec toi"
    if situation == "travail" and "travail" not in st.episodes:
        return "fermé par le service : pas quand elle travaille"
    if situation == "compte" and not st.with_accounts and not st.with_people:
        return "fermé par le service : ni les comptes, ni personne de choisi"
    return ""


def _where(ui: UI, key: str) -> list[dict[str, Any]]:
    """Pour qui et quand, situation par situation : ce que la porte d'offre lui donne des outils de ce service
    (celle de « Ce qu'elle peut faire », les règles des opérateurs comprises) ; sinon, pourquoi pas."""
    port, registry, policies = ui.kernel.ports.get("mcp"), ui.kernel.registry, ui.kernel.runner.policies
    specs = [registry.tools[t.name] for t in port.offered() if t.server == key and t.name in registry.tools]
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
            if s.kind in (Kind.STEP, Kind.WORK):
                how = ", ".join(filter(None, (how, "si le but ou le projet a pris ce service")))
            row = {"yes": True, "said": f"{len(got)} outil{'s' if len(got) > 1 else ''}", "how": how}
        else:
            why = catalog.why_not(specs[0], policies[s.kind], s, ruled) if specs else "aucun outil servi"
            row = {"yes": False, "said": "non", "how": why}
        out[-1]["rows"].append({"label": s.short, "title": s.label, **row})
    return out


class ServerOverview(Overview):
    """« En bref » : le premier onglet de la fiche d'un service branché ; l'onglet « État » du plugin, qu'il
    résume, passe au bout de la barre."""

    slug = "ensemble"
    title = "En bref"
    #: pas de phrase sous l'en-tête : la page se lit d'elle-même
    description = ""
    styles = ("handmade/tools.css",)
    folded = ("etat",)

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
                (f"avec {who_said(st, frame)}", "info"), (genre_of(st)[1], "owner")]
        if review:
            tags.append((f"{review} outil{'s' if review > 1 else ''} à revoir", "warn"))
        return Markup(env.get_template("handmade/outils/serveur_tete.html").render(
            name=st.name, purpose=_capital(st.purpose.strip()), tags=tags))

    def links(self, ui: UI, key: str) -> list[tuple[str, str]]:
        """« Modifier ses réglages » (la connexion), à côté de « Tester la connexion »."""
        port = ui.kernel.ports.get("mcp")
        if port is None or port.status(key) is None:
            return []
        return [("Modifier ses réglages", render.href(edit_server(key, fiche_url(KIND, key))))]

    def render(self, ui: UI, key: str) -> Markup | None:
        port = ui.kernel.ports.get("mcp")
        st = port.status(key) if port is not None else None
        if st is None:
            return None
        shown = render.Env(when=ui.when, now=ui.now())

        def ago(at: int) -> str:
            return render.cell(When(at), shown)["text"] if at else ""

        tools_tab = fiche_url(KIND, key, "outils")
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
        live = {t.remote: t for t in st.live}
        remotes = [t.remote for t in st.live] + [r for r in st.reviews if r not in live]
        tools = []
        for remote in remotes:
            word, tone = tool_state(st, remote)
            tool, decided = live.get(remote), st.reviews.get(remote)
            said = (decided.description if decided is not None and decided.description else "") or \
                (tool.description if tool is not None else (decided.server_description if decided else ""))
            rules = fiche_url(KIND, key, "regles") + "&" + urlencode({"outil": remote}) \
                if decided is not None and decided.enabled else ""
            tools.append({"name": remote, "what": _capital(said.strip()), "state": word, "tone": tone,
                          "rules": rules})
        technical = [
            ("le serveur dit être", f"{st.server_name} {st.server_version}".strip() or "—"),
            ("protocole", st.protocol or "—"),
            ("joint", ui.when(st.last_ok_at) if st.last_ok_at else "jamais"),
            ("dernière panne", ui.when(st.last_error_at) if st.last_error_at else "aucune"),
            ("pannes d'affilée", str(st.consecutive)),
        ]
        situations = _where(ui, key)
        rows = max(1, sum(len(g["rows"]) for g in situations))
        return Markup(env.get_template("handmade/outils/serveur.html").render(
            state=STATES.get(st.state, st.state), state_tone=STATE_TONES.get(st.state, ""),
            joined=ago(st.last_ok_at), served=served, live=len(st.live), review=review,
            calls=st.calls, failures=st.failures, alerts=alerts, genre=genre_of(st)[1],
            sentence=sentence(st, ui.kernel.mind.frame()), service_tab=fiche_url(KIND, key, "fait"),
            who=_capital(who_said(st, ui.kernel.mind.frame())), alone=_capital(WORDS.get(st.autonomy, st.autonomy)),
            keep=_capital(_word(KEEPS, st.keep)), keep_later=LATER.get(st.keep, ""),
            purpose=_capital(st.purpose.strip()), when_to_use=_capital(st.when_to_use.strip()),
            tools=tools, situations=situations, who_pager=render._pager(Pager(size=rows, total=rows), {}),
            technical=technical, log=list(st.log), instructions=st.instructions,
            local=st.kind == "local", address=st.address, settings=settings, tools_tab=tools_tab,
            calls_tab=fiche_url(KIND, key, "appels"), grid=grid))

    tabs = ("fait", "regles", "outils")

    def render_tab(self, ui: UI, key: str, tab: str, blocks: Any, query: Any, forms: Any = None) -> Any:
        """« Ce qu'elle en fait » et « Par situation et par personne », dessinés (ADR 0128) ; sans outil choisi, la
        seconde garde la liste de la console."""
        port = ui.kernel.ports.get("mcp")
        st = port.status(key) if port is not None else None
        if st is None:
            return None
        if tab == "fait":
            return self._service(ui, st, forms)
        if tab == "regles":
            return self._rules(ui, st, str(dict(query or {}).get("outil", "")), forms)
        if tab == "outils":
            return self._tools(ui, st, forms)
        return None

    @staticmethod
    def _tools(ui: UI, st: Any, forms: Any) -> Markup:
        live = {t.remote: t for t in st.live}
        remotes = [t.remote for t in st.live] + [r for r in st.reviews if r not in live]
        groups = {"lecture": [], "action": []}
        for remote in remotes:
            tool, review = live.get(remote), st.reviews.get(remote)
            word, tone = tool_state(st, remote)
            nature = review.nature if review is not None else (
                "lecture" if tool is not None and tool.read_only_hint else "action")
            said = (review.description if review is not None and review.description else "") or (
                tool.description if tool is not None else (review.server_description if review else ""))
            n = len(review.situations) + len(review.people) if review is not None else 0
            served = review is not None and review.enabled
            slot = json.dumps(remote)
            form = next((v for k, v in dict(forms or {}).items()
                         if k.startswith("mcp.regler|") and f'"outil": {slot}' in k), None)
            groups[nature].append({
                "name": remote, "what": _capital(said.strip())[:220], "state": word, "tone": tone, "form": form,
                "own": WORDS.get(review.autonomy, "") if review is not None and review.autonomy != "service" else "",
                "rules": f"{n} règle{'s' if n > 1 else ''}" if n else "",
                "rules_href": fiche_url(KIND, st.name, "regles") + "&" + urlencode({"outil": remote}) if served else ""})
        notes = []
        if not st.live:
            notes.append({"tone": "warn", "text": "La liste de ses outils n'est pas connue : « Tester la connexion » "
                                                  "la charge."})
        if st.changed:
            notes.append({"tone": "danger", "text": f"Le serveur a changé {', '.join(st.changed)} depuis ton accord : "
                                                    "suspendu jusqu'à ce que tu le relises."})
        return Markup(env.get_template("handmade/outils/outils.html").render(
            alone=_capital(WORDS.get(st.autonomy, st.autonomy)), keep=_word(KEEPS, st.keep), genre=genre_of(st)[1],
            service_tab=fiche_url(KIND, st.name, "fait"), fresh=list(st.new), serve_form=_form(forms, "mcp.servir"),
            notes=notes, groups=[
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
            people_keys=[p["key"] for p in people], people_slots=slots, autonomies=_steps(AUTONOMIES),
            autonomy=st.autonomy, keeps=_steps(KEEPS, LATER), keep=st.keep))

    @staticmethod
    def _rules(ui: UI, st: Any, remote: str, forms: Any) -> Markup | None:
        review = st.reviews.get(remote)
        if review is None:
            return None
        frame = ui.kernel.mind.frame()
        base = default_level(st, review)
        situations, said = [], dict(review.situations)
        for k, label in TOOL_SITUATIONS:
            hint = SITUATION_HINTS.get(k, "")
            if k == "compte" and not st.with_accounts and st.with_people:
                hint += " — seulement les personnes choisies du service"
            situations.append({"path": f"s_{k}", "label": _capital(label), "hint": hint, "why": _closed(st, k),
                               "locked": bool(_closed(st, k)), "value": said.get(k, AS_SERVICE),
                               "options": ((AS_SERVICE, f"comme le service ({WORDS.get(base, base)})"),
                                           *RULE_LEVELS)})
        compte = said.get("compte") or base
        slots = [{"person_path": f"p{i + 1}", "level_path": f"r{i + 1}", "person": who, "level": level}
                 for i, (who, level) in enumerate(list(review.people.items())[:PEOPLE_SLOTS])]
        if len(slots) < PEOPLE_SLOTS:
            n = len(slots) + 1
            slots.append({"person_path": f"p{n}", "level_path": f"r{n}", "person": "", "level": AS_SITUATION})
        people = _people(ui)
        summary = [("Toi", SAY.get(said.get("proprietaire") or base, base) if st.with_owner
                    else "non : le service n'est pas avec toi")]
        for who, level in review.people.items():
            inside = st.with_accounts or who in st.with_people
            summary.append((name_of(frame, who), SAY.get(level, level) if inside
                            else "rien : hors du service (à ajouter dans « Ce qu'elle en fait »)"))
        others = [p for p in st.with_people if p not in review.people]
        if st.with_accounts:
            summary.append(("Les autres comptes" if review.people else "Les comptes", SAY.get(compte, compte)))
        elif others:
            summary.append((", ".join(name_of(frame, p) for p in others), SAY.get(compte, compte)))
        summary.append(("Quand elle travaille seule", SAY.get(said.get("travail") or base, base)
                        if not _closed(st, "travail") else "non"))
        summary.append(("Une inconnue, un salon", "jamais"))
        return Markup(env.get_template("handmade/outils/regles.html").render(
            remote=remote, what=_capital((review.description or review.server_description or "").strip()),
            nature=_word(NATURES, review.nature), sentence=sentence(st, frame),
            own=WORDS.get(review.autonomy, review.autonomy), service_tab=fiche_url(KIND, st.name, "fait"),
            tools_tab=fiche_url(KIND, st.name, "outils"), form=_form(forms, "mcp.regles"), situations=situations,
            people=people, people_keys=[p["key"] for p in people], people_slots=slots,
            person_options=((AS_SITUATION, f"comme sa situation ({WORDS.get(compte, compte)})"), *RULE_LEVELS),
            summary=summary))
