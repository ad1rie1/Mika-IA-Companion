"""La fiche d'un projet, son onglet « Accès » dessiné (ADR 0121, 0133) : qui peut le voir, le piloter et se servir de
ses apps, et quand — un tableau de lignes lues de haut en bas, comme les règles d'un pare-feu, puis la ligne par
défaut, obligatoire.

Le reste de la fiche reste celui de la faculté (pas de vue d'ensemble à elle : ``slug`` vide). Les outils qu'une ligne
peut cocher sont ceux des apps du projet, lus dans la Forge (une app vit dans un projet, ADR 0104) ; chaque bouton
envoie tout le tableau (``projects.acces``).
"""

from __future__ import annotations

from typing import Any

from markupsafe import Markup

from mika.app.handmade.access import people_with_accounts, who_choices
from mika.faculties.projects.access import STEER_WORDS, who_named
from mika.faculties.projects.faculty import access_of, project_at
from mika.inspector import render
from mika.inspector.pages.subjects import fiche_url
from mika.inspector.ui import UI, Overview, env
from mika.kernel.inspect import Pager
from mika.plugins.forge import app_tool_names
from mika.vocab.access import MOMENTS, PERSON, when_words

KIND = "project"
#: ce qu'une ligne fait, dans un sélecteur du tableau
STEER_CHOICES = (("seule", "Seule"), ("toi", "Ton accord"), ("non", "Non"))
POLICY_CHOICES = (("seule", "Seule"), ("carte", "Demande à la personne"), ("toi", "Ton accord"), ("non", "Non"))
MOMENT_CHOICES = tuple((k, label[:1].upper() + label[1:]) for k, label in MOMENTS)


def _form(forms: Any, action: str) -> Any:
    """Le formulaire que la console a préparé pour une action de l'onglet (son jeton, son retour)."""
    return next((v for k, v in dict(forms or {}).items() if k.split("|", 1)[0] == action), None)


class ProjectFiche(Overview):
    """La fiche d'un projet : ses onglets restent ceux de la faculté, « Accès » est dessiné ici."""

    slug = ""
    title = "Accès"
    styles = ("handmade/tools.css",)
    tabs = ("acces",)

    def render(self, ui: UI, key: str) -> Markup | None:
        return None

    def render_tab(self, ui: UI, key: str, tab: str, blocks: Any, query: Any, forms: Any = None) -> Any:
        if tab != "acces":
            return None
        frame = ui.kernel.mind.frame()
        p = project_at(frame.state("projects"), key)
        if p is None:
            return None
        lines, default = access_of(p)
        people = people_with_accounts(ui)
        # les outils de ses apps (``<app>_<outil>``), ce qu'ils font ; et ceux qu'une ligne nomme encore sans qu'une
        # app les propose (une app effacée, renommée) : on les voit, on peut les décocher
        tools = app_tool_names(frame, ui.kernel.ports, p.id)
        known = list(dict.fromkeys([*(t for t, _ in tools), *(t for a in lines for t in a.tools)]))
        natures = dict(tools)
        rows = []
        for n, a in enumerate(lines, start=1):
            rows.append({
                "n": n, "who": who_choices(a.who, people, lambda person: who_named(frame, (PERSON + person,))),
                "always": not a.when,
                "when_said": "Toujours" if not a.when else (when_words(a.when).capitalize() if len(a.when) == 1
                                                             else f"{len(a.when)} moments"),
                "moments": [{"key": k, "label": label, "on": k in a.when} for k, label in MOMENT_CHOICES],
                "see": a.see, "steer": a.steer, "read": a.read, "act": a.act, "all": not a.tools,
                "said": "Tous" if not a.tools else f"{len(a.tools)} outil{'s' if len(a.tools) > 1 else ''}",
                "tools": [{"name": t, "nature": natures.get(t, ""), "on": t in a.tools} for t in known],
                "first": n == 1, "last": n == len(lines)})
        return Markup(env.get_template("handmade/projets/acces.html").render(
            rows=rows, default=default, steers=STEER_CHOICES, policies=POLICY_CHOICES, steer_words=STEER_WORDS,
            form=_form(forms, "projects.acces"), never_set=p.access is None, has_apps=bool(tools),
            pager=render._pager(Pager(size=len(rows) + 1, total=len(rows) + 1), {}),
            behaviour_tab=fiche_url(KIND, key, "comportement")))
