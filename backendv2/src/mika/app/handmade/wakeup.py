"""La fiche d'un réveil par API, dessinée (ADR 0068, 0121) : son en-tête, et son onglet « État » — s'il reçoit (actif,
sa clé), ce qu'il lui fait faire (à quoi il sert, ses consignes, son projet, ses outils, à qui elle rend compte), ce
qu'il expose, sa clé et ses boutons, comment l'appeler, et ses derniers appels. « Appels » se dessine bloc par bloc.

Les données sont celles du plugin ``wakeup`` : le réveil tel que le port le déclare, ses appels (sa tranche) et leurs
textes ; ce qu'il expose se dit par sa règle (``risks``). Les formulaires (générer une clé, la retirer) sont ceux que la
console a préparés pour l'onglet, retrouvés dans ses blocs. Ce qu'un appel apporte est une donnée venue d'ailleurs :
montrée, jamais obéie.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from markupsafe import Markup

from mika.app.handmade import Look, excerpt
from mika.app.handmade.fiche_parts import STYLES, draw, fact, rendered, tag, texts, tone, whole
from mika.inspector import render
from mika.inspector.pages.subjects import fiche_url
from mika.inspector.ui import UI, Overview
from mika.kernel.clock import DAY, HOUR
from mika.kernel.inspect import Ref
from mika.plugins.wakeup import RUNNING, WAITING
from mika.plugins.wakeup.console import STATUS_WORDS, edit_endpoint, notify_words, project_words, risks

KIND = "reveil"
TABS = ("etat", "appels")
#: ses derniers appels, sur « État »
RECENT = 3
FORGOTTEN = "(oublié)"


def _endpoint(ui: UI, key: str) -> Any:
    port = ui.kernel.ports.get("wakeup")
    return port.endpoint(key) if port is not None else None


def _calls(ui: UI, key: str) -> list[Any]:
    """Ses appels gardés, du plus récent au plus ancien."""
    try:
        s = ui.kernel.mind.frame().state("wakeup")
    except KeyError:
        return []
    return sorted((x for x in s.calls.values() if x.endpoint == key), key=lambda x: -x.seq)


def _project(ui: UI, project: int) -> dict[str, str] | None:
    """Son projet, par son titre et sa fiche (``None`` : aucun)."""
    if not project:
        return None
    got = project_words(ui.kernel.mind.frame(), ui.inspection.context(), project)
    if isinstance(got, Ref):
        return {"text": got.text, "href": render.href(got)}
    return {"text": str(got), "href": ""}


def _status(call: Any) -> dict[str, str]:
    word, value = STATUS_WORDS.get(call.status, (call.status, ""))
    return tag(word + (", dit" if call.told else ""), value)


class WakeupFiche(Overview):
    """La fiche d'un réveil : son en-tête, « État » dessiné ; « Appels » bloc par bloc."""

    slug = ""
    title = "État"
    styles = STYLES
    tabs = TABS

    def render(self, ui: UI, key: str) -> Markup | None:
        return None

    def head(self, ui: UI, key: str) -> Markup | None:
        ep = _endpoint(ui, key)
        if ep is None:
            return None
        tags = [tag("actif", "ok") if ep.enabled else tag("désactivé"),
                tag("clé définie", "ok") if ep.key is not None else tag("sans clé", "warn"),
                tag("impersonnel", "info") if ep.plain else tag("dans son mode à elle", "info")]
        if ep.rouse:
            tags.append(tag("passe outre son sommeil", "warn"))
        if ep.signed:
            tags.append(tag("signé", "info"))
        facts = [fact("adresse", f"POST /api/wake/{key}"),
                 fact("rend compte à", notify_words(ui.kernel.mind.frame(), ep.notify))]
        if (project := _project(ui, ep.project)) is not None:
            facts.append(fact("projet", project["text"], project["href"]))
        return draw("tete.html", kicker="Réveil par API", title=key, lede=ep.label, tags=tags, facts=facts)

    def links(self, ui: UI, key: str) -> list[tuple[str, str]]:
        """« Modifier ses réglages » (Réglages › Plugins › Réveils par API), qui ramène ici."""
        if _endpoint(ui, key) is None:
            return []
        return [("Modifier ses réglages", render.href(edit_endpoint(key, fiche_url(KIND, key))))]

    def render_tab(self, ui: UI, key: str, tab: str, blocks: Sequence[Any], query: Mapping[str, str],
                   forms: Mapping[str, Any] | None = None) -> Any:
        if tab == "etat":
            return self._state(ui, key, blocks, query, forms)
        return whole(ui, blocks, query, forms) if tab in TABS else None

    @staticmethod
    def _state(ui: UI, key: str, blocks: Sequence[Any], query: Mapping[str, str],
               forms: Mapping[str, Any] | None) -> Markup | None:
        ep = _endpoint(ui, key)
        if ep is None:
            return None
        look = Look.of(ui, DAY)
        frame = look.frame
        items = rendered(ui, blocks, query)
        calls = _calls(ui, key)
        recent = calls[:RECENT]
        said = texts(ui, [r for x in recent for r in (x.text_ref, x.report_ref)])
        pending = sum(1 for x in calls if x.status in (WAITING, RUNNING))
        alerts = [{"tone": "warn", "text": r} for r in risks(ep)]
        if not ep.enabled:
            alerts.append({"tone": "", "text": "Il est désactivé : ses appels sont refusés (403)."})
        if ep.key is None:
            alerts.append({"tone": "warn", "text": "Sans clé, il ne reçoit rien (401) : génère-la ci-dessous, elle ne "
                                                   "sera montrée qu'une fois."})
        key_state = ep.key
        return draw(
            "reveil.html", forms=forms or {}, tables="cards", alerts=alerts,
            tiles=[{"label": "Il reçoit", "value": "oui" if ep.enabled and key_state is not None else "non",
                    "sub": "actif" if ep.enabled else "désactivé", "tone": "" if ep.enabled else "warn"},
                   {"label": "Sa clé", "value": f"{key_state.hint}…" if key_state is not None else "aucune",
                    "sub": f"générée {look.day(key_state.created_at)}" if key_state is not None
                    and key_state.created_at else "", "tone": "" if key_state is not None else "warn"},
                   {"label": "En attente", "value": str(pending), "sub": f"au plus {ep.max_pending}",
                    "tone": "warn" if pending >= ep.max_pending else ""},
                   {"label": "Dernier appel", "value": look.ago(calls[0].at) if calls else "jamais",
                    "sub": f"{len(calls)} gardé{'s' if len(calls) > 1 else ''}" if calls else "", "tone": ""}],
            instructions=ep.instructions, project=_project(ui, ep.project),
            mode="impersonnel : sans persona, sans affect" if ep.plain else "le sien : sa voix, son humeur",
            bundles=list(ep.bundles), notify=notify_words(frame, ep.notify),
            rouse="oui : chaque appel la réveille" if ep.rouse else "non : il attend son réveil",
            signed="oui : le corps signé par la clé (X-Hub-Signature-256), ou la clé présentée" if ep.signed else
            "non : la clé présentée (Authorization: Bearer, ou X-Gitlab-Token)",
            fields=list(ep.fields),
            limits=f"{ep.per_hour} appels par heure, {ep.max_pending} en attente, {ep.max_chars} caractères",
            lifetime=f"{max(1, ep.lifetime_us // HOUR)} h",
            key={"hint": f"{key_state.hint}…", "at": look.day(key_state.created_at) if key_state.created_at else "",
                 "by": key_state.by} if key_state is not None else None,
            actions=[d for d in items if d["t"] == "action"],
            codes=[d for d in items if d["t"] == "code"],
            notes=[d for d in items if d["t"] == "note" and d.get("tone") in ("", "muted")
                   and "désactivé" not in d.get("text", "")],
            calls=[{"status": _status(x), "when": look.ago(x.at),
                    "text": excerpt(said.get(x.text_ref), 240) if x.text_ref else FORGOTTEN,
                    "report": excerpt(said.get(x.report_ref), 280) if x.report_ref and x.report_ref in said else "",
                    "episode": x.episode, "tone": tone(STATUS_WORDS.get(x.status, ("", ""))[1])} for x in recent],
            more=len(calls) > RECENT, calls_tab=fiche_url(KIND, key, "appels"))
