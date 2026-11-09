"""Les actions d'opérateur : leurs formulaires (en tête de page, sur une ligne, sur leur propre page), leur exécution,
et les approbations de la file."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from urllib.parse import quote, urlencode

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from mika.inspector import render
from mika.inspector.catalog import Panel
from mika.inspector.formview import action_view, prefilled, visible_fields
from mika.inspector.ui import PREFIX
from mika.kernel.forms import RENDERED, describe
from mika.kernel.inspect import Note
from mika.runtime.operations import dynamic_fields, fixed_values, initial_values, offered, perform

#: une action à plus de champs s'ouvre sur sa propre page, pas en panneau
PANEL_FIELDS_MAX = 2
#: un champ « sujet » propose au plus tant d'objets connus
SUBJECT_CHOICES = 300


def per_row(spec: Any) -> bool:
    """Une action qui porte sur une ligne précise (une tâche, une demande) : un champ caché requis que
    seule la vue qui la pose sait remplir. Elle ne se propose pas en tête de page."""
    if spec.fields is not None:
        return False
    return any(f.kind == "hidden" and f.required for f in describe(spec.args))


def safe_back(target: str) -> str:
    """Un retour dans la console seulement (jamais une autre adresse)."""
    if target.startswith(PREFIX + "/") and "//" not in target and "\\" not in target and len(target) < 2000:
        return target
    return PREFIX + "/"


class Actions:
    """Les actions de la console, une part de ``Pages`` (``routes.py``), qui leur apporte ``ui``, ``back``,
    ``render_page`` et ``action_trail``."""

    def slot_forms(self, request: Request, blocks: Sequence[Any], subject: str) -> dict[str, Any]:
        """Les formulaires des actions posées dans les blocs (``ActionSlot``), même
        dans le détail d'une ligne."""
        out: dict[str, Any] = {}
        csrf, back = self.ui.csrf(request), self.back(request)

        def walk(items: Sequence[Any]) -> None:
            for b in items:
                if b["t"] == "action":
                    spec = self.ui.inspection.action(b["key"])
                    if spec is not None and offered(self.ui.kernel, spec, subject):
                        initial = b["initial"]
                        dynamic = dynamic_fields(self.ui.kernel, spec, subject, initial) if spec.fields else None
                        # l'état d'abord, puis ce que la vue pose (une tâche précise, un statut visé)
                        view = action_view(spec, csrf=csrf, back=back, subject=subject,
                                           initial={**initial_values(self.ui.kernel, spec, subject), **initial},
                                           dynamic=dynamic, subjects=self.subject_choices)
                        if b["title"]:
                            view["title"] = b["title"]
                            view["button"] = initial.get("_bouton") or b["title"]
                        out[b["slot"]] = view
                elif b["t"] in ("grid", "section", "disclosure", "workspace", "toolbar"):
                    walk(b.get("sidebar", []) + b["items"])
                elif b["t"] == "table":
                    walk([x for r in b["rows"] for x in r["detail"]])

        walk(blocks)
        return out

    def subject_choices(self, kind: str) -> list[tuple[str, str]]:
        """Les objets connus d'un type (une personne, un but) : ce qu'un champ « sujet » propose."""
        return [(f.key, f"{f.title} — {f.subtitle}" if f.subtitle else f.title)
                for f in self.ui.inspection.search(kind, "", SUBJECT_CHOICES, when=self.ui.when)]

    def head_actions(self, request: Request, *, section: str = "", kind: str = "", subject: str = "") -> list[Any]:
        """Les actions d'une page : une action courte s'ouvre en panneau ; une action à plus de deux champs a
        sa propre page (``/action/<clé>``), qui ramène ici."""
        specs = self.ui.inspection.actions_for(section=section) if section else \
            self.ui.inspection.actions_for(subject=kind)
        csrf, back = self.ui.csrf(request), self.back(request)
        out = []
        for a in specs:
            if a.inline or per_row(a) or not offered(self.ui.kernel, a, subject):
                continue
            view = action_view(a, csrf=csrf, back=back, subject=subject, subjects=self.subject_choices,
                               values=initial_values(self.ui.kernel, a, subject))
            if visible_fields(view) > PANEL_FIELDS_MAX:
                view["page"] = f"{PREFIX}/action/{quote(a.key, safe='')}?" + urlencode(
                    {"retour": back, **({"sujet": subject} if subject else {})})
            out.append(view)
        return out

    async def action_page(self, request: Request) -> Response:
        """Une action sur sa propre page : son formulaire en entier, chaque champ expliqué."""
        key = request.path_params["key"]
        spec = self.ui.inspection.action(key)
        subject = request.query_params.get("sujet", "")[:300]
        back = safe_back(request.query_params.get("retour", ""))
        if spec is None:
            return self.render_page(request, title="Action inconnue", active="", status=404,
                                    blocks=[Note("Cette action n'existe pas.", "warn")])
        home, crumbs, returning = self.action_trail(spec, back)
        if not offered(self.ui.kernel, spec, subject):
            return self.render_page(request, title=spec.title, active=home.key if home else "", status=409,
                                    crumbs=crumbs, crumbs_back=returning,
                                    blocks=[Note("Cette action n'est pas possible maintenant (l'objet a changé ?).",
                                                 "warn")])
        dynamic = dynamic_fields(self.ui.kernel, spec, subject, {}) if spec.fields else None
        # l'état d'abord, puis ce que l'adresse demande (le bouton d'une ligne : « la démentir »)
        asked = prefilled(dynamic if dynamic is not None else describe(spec.args), request.query_params)
        form = action_view(spec, csrf=self.ui.csrf(request), back=back, subject=subject, dynamic=dynamic,
                           subjects=self.subject_choices,
                           values={**initial_values(self.ui.kernel, spec, subject), **asked})
        form["description"] = ""  # dite en sous-titre de la page
        return self.render_page(request, title=spec.title, heading=spec.title, subtitle=spec.description,
                                active=home.key if home else "", crumbs=crumbs, crumbs_back=returning, blocks=[],
                                panel=Panel("handmade/shared/action.html", {"form": form}))

    async def act(self, request: Request) -> Response:
        """Exécuter une action déclarée : valider, exécuter, revenir (ou remontrer
        le formulaire avec ses erreurs)."""
        key = request.path_params["key"]
        spec = self.ui.inspection.action(key)
        got = await self.ui.form_lists(request)
        account = self.ui.operator(request)
        if spec is None:
            return self.render_page(request, title="Action inconnue", active="", status=404,
                                    blocks=[Note("Cette action n'existe pas.", "warn")])
        if got is None or account is None:
            return self.render_page(request, title=spec.title, active="", status=403,
                                    blocks=[Note("Jeton de formulaire invalide : recharge la page.", "danger")])
        single, lists = got
        back = safe_back(single.get("_retour", ""))
        subject = single.get("_sujet", "")
        outcome = await perform(self.ui.kernel, key, lists, by=account.handle, subject=subject,
                                nonce=single.get("_op", ""))
        if not outcome.ok and outcome.errors:
            fixed = fixed_values(lists)
            dynamic = dynamic_fields(self.ui.kernel, spec, subject, fixed) if spec.fields else None
            values = {k: v for k, v in single.items() if not k.startswith("_") and k not in fixed}
            # un champ affiché mais absent de l'envoi est une case décochée : vide, pas son défaut
            values.update({path: "" for path in lists.get(RENDERED, []) if path not in values and path not in fixed})
            form = action_view(spec, csrf=self.ui.csrf(request), back=back, subject=subject, initial=fixed,
                               values=values, errors=outcome.errors, dynamic=dynamic, subjects=self.subject_choices)
            home, crumbs, returning = self.action_trail(spec, back)
            return self.render_page(request, title=spec.title, active=home.key if home else "", status=400,
                                    crumbs=crumbs, crumbs_back=returning,
                                    blocks=[], head_actions=[], messages=[("danger", outcome.message)],
                                    panel=Panel("handmade/shared/action.html", {"form": form}))
        if outcome.show:
            home, crumbs, returning = self.action_trail(spec, back)
            return self.render_page(request, title=spec.title, active=home.key if home else "", crumbs=crumbs,
                                    crumbs_back=returning, blocks=list(outcome.show),
                                    messages=[(outcome.tone, outcome.message)])
        token = single.get("_op", "") or key
        self.ui.flash(token, outcome.tone if outcome.ok else "danger", outcome.message)
        target = render.href(outcome.go, self.ui.env()) if outcome.go else back
        sep = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{sep}flash={quote(token, safe='')}", status_code=303)

    async def approve(self, request: Request) -> Response:
        data = await self.ui.form(request)
        account = self.ui.operator(request)
        target = f"{PREFIX}/approbations"
        if data is None or account is None:
            return RedirectResponse(target + "?fait=jeton", status_code=303)
        try:
            proposal = int(data.get("proposal", "0"))
        except ValueError:
            proposal = 0
        approved = data.get("decision") == "approve"
        status = await self.ui.deps.port.resolve_effect(proposal, approved, by=account.handle,
                                                        note=data.get("note", "")[:500], seen=data.get("seen", ""))
        if status in ("approved", "rejected") and self.ui.deps.after_decision is not None:
            await self.ui.deps.after_decision()
        outcome = {"approved": "oui", "rejected": "non", "changed": "change", "blocked": "bloque"}.get(status,
                                                                                                    "inconnu")
        # décidée : la suivante de la file s'ouvre ; à relire (l'aperçu a changé, bloquée) : la même
        again = status in ("changed", "blocked")
        follow = str(proposal) if again else data.get("suivante", "")
        query = {"fait": outcome, **({"demande": follow} if follow.isdigit() else {}),
                 **({"sorte": kind} if (kind := data.get("sorte", "")[:200]) else {})}
        # l'onglet de la file d'où l'on décide (« Courriers à envoyer ») : on y revient
        tab = data.get("file", "")
        if tab and len(tab) <= 40 and tab.replace("_", "").isalnum():
            target = f"{target}/{tab}"
        return RedirectResponse(f"{target}?{urlencode(query)}", status_code=303)
