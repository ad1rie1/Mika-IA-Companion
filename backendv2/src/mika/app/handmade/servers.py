"""La fiche d'un service branché, dessinée (ADR 0121, 0123) : son premier onglet, « En bref ».

S'il marche (et ce qui attend ton regard), ce qu'elle en lit pour décider de s'en servir, ses outils et ce que tu en
as décidé, pour qui et quand ; le côté technique replié. Lu au port MCP, comme les onglets du plugin, qui restent à un
clic (« État » sous « Le détail », « Ses outils » pour les régler, « Appels »).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from markupsafe import Markup

from mika.inspector import render
from mika.inspector.pages import tools as catalog
from mika.inspector.pages.subjects import fiche_url
from mika.inspector.ui import UI, Overview, env
from mika.kernel.inspect import Pager, When
from mika.plugins.mcp.console import STATE_TONES, edit_server, tool_state
from mika.ports.mcp import AUDIENCES, STATES
from mika.runtime.tools import deferred
from mika.vocab.episodes import Kind

KIND = "serveur"


def _word(choices: tuple[tuple[str, str], ...], value: str) -> str:
    return next((label.split(" — ")[0] for key, label in choices if key == value), value)


def _capital(text: str) -> str:
    return text[:1].upper() + text[1:]


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
    description = "S'il marche, ce qu'elle en lit, ses outils et ce que tu en as décidé, pour qui et quand."
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
        tags = [(STATES.get(st.state, st.state), STATE_TONES.get(st.state, "")),
                ("sur cette machine" if st.kind == "local" else "à une adresse", "info"),
                (_word(AUDIENCES, st.audience), "info")]
        if review:
            tags.append((f"{review} outil{'s' if review > 1 else ''} à revoir", "warn"))
        return Markup(env.get_template("handmade/outils/serveur_tete.html").render(
            name=st.name, purpose=_capital(st.purpose.strip()), tags=tags,
            settings=render.href(edit_server(key, fiche_url(KIND, key)))))

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
            tools.append({"name": remote, "what": _capital(said.strip()), "state": word, "tone": tone})
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
            calls=st.calls, failures=st.failures, alerts=alerts,
            purpose=_capital(st.purpose.strip()), when_to_use=_capital(st.when_to_use.strip()),
            tools=tools, situations=situations, who_pager=render._pager(Pager(size=rows, total=rows), {}),
            technical=technical, log=list(st.log), instructions=st.instructions,
            local=st.kind == "local", address=st.address, settings=settings, tools_tab=tools_tab,
            calls_tab=fiche_url(KIND, key, "appels"), grid=grid))

