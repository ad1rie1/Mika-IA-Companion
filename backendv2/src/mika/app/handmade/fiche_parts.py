"""Ce que partagent les fiches dessinées des objets (``fiches.py``, ADR 0121) : leur en-tête, leur feuille, les blocs
d'un onglet rendus comme la console les numérote, et le dessin d'un gabarit.

Une fiche dessinée reprend les formulaires que la console a préparés pour l'onglet (``Forms``, par emplacement) : ses
blocs, rendus ici dans le même ordre et sur la même requête, retrouvent chacun le sien. Ce qu'un dessin n'a pas de
forme à lui (le détail complet, un repli de la faculté) se rend bloc par bloc (``one``, ``shared/drawn.html``).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from markupsafe import Markup

from mika.app.handmade import blocks as drawn_blocks
from mika.inspector import render
from mika.inspector.ui import UI, env
from mika.kernel.inspect import Head
from mika.runtime.boundary import Failed, call

#: la feuille des fiches dessinées des objets (en plus de ``handmade/base.css``, chargée partout)
STYLES = ("handmade/fiches.css",)
#: les tons qu'une étiquette sait dire (``now-tag``) ; les autres se disent sans couleur
TONES = frozenset({"ok", "info", "warn", "danger"})


def tone(value: str) -> str:
    return value if value in TONES else ""


def tag(text: str, value: str = "") -> dict[str, str]:
    """Une étiquette de l'en-tête ou d'une carte : son texte, son ton."""
    return {"text": text, "tone": tone(value)}


def fact(label: str, text: str, href: str = "") -> dict[str, str]:
    """Un fait de l'en-tête (« pour qui · Adrien ») ; ``href`` : il mène quelque part."""
    return {"label": label, "text": text, "href": href}


def draw(template: str, **context: Any) -> Markup:
    """Un gabarit des fiches (``handmade/fiches/``), rendu par la console : son HTML est déjà échappé."""
    return Markup(env.get_template(f"handmade/fiches/{template}").render(**context))


def head(title: str, *, kicker: str = "", lede: str = "", tags: Sequence[dict[str, str]] = (),
         facts: Sequence[dict[str, str]] = ()) -> Markup:
    """L'en-tête d'une fiche, sur tous ses onglets : de quelle sorte d'objet il s'agit, son nom, une ligne qui le dit,
    ses étiquettes et quelques faits ; la console y ajoute ses actions, à droite."""
    return draw("tete.html", title=title, kicker=kicker, lede=lede, tags=list(tags), facts=list(facts))


def faculty_head(ui: UI, kind: str, key: str) -> Head | None:
    """L'en-tête que la faculté déclare pour cet objet (``None`` : inconnu, ou son en-tête a échoué), ses instants dits
    court (« 30/09 19:41 »)."""
    got = ui.inspection.head(kind, key, ui.when)
    return got if isinstance(got, Head) else None


def head_of(ui: UI, got: Head, *, kicker: str, tags: Sequence[dict[str, str]] = (),
            facts: Sequence[dict[str, str]] = ()) -> Markup:
    """L'en-tête de la faculté, dessiné : son titre, sa ligne, ses étiquettes et ses faits (un lien reste un lien),
    puis ce que la fiche y ajoute."""
    shown = render.Env(when=ui.when, now=ui.now())
    said = []
    for label, value in got.facts:
        c = render.cell(value, shown)
        said.append(fact(label, str(c.get("text", "")), str(c.get("href", ""))))
    return head(got.title, kicker=kicker, lede=got.subtitle,
                tags=[*(tag(b.text, b.tone) for b in got.badges), *tags], facts=[*said, *facts])


def side_view(ui: UI, owner: str, name: str, key: str, namespace: str) -> list[dict[str, Any]]:
    """Un autre onglet de la fiche, lu pour une carte de côté (sa première page, ses listes numérotées à part) : ce
    qu'il dit reste celui de la faculté."""
    spec = ui.inspection.find(owner, name)
    if spec is None:
        return []
    got = safely(lambda: ui.inspection.run(spec, {}, ui.when_long, subject=key), f"onglet {owner}/{name}", [])
    return [shaped(d) for d in render.blocks(got, ui.env(), {}, namespace=namespace)]


def rendered(ui: UI, blocks: Sequence[Any], query: Mapping[str, str]) -> list[dict[str, Any]]:
    """Les blocs d'un onglet, rendus et numérotés comme la console les a rendus pour préparer leurs formulaires : un
    dessin qui en reprend un (une action, un repli) y retrouve le sien. Alignés sur ``blocks``, un pour un."""
    return render.blocks(blocks, ui.env(), dict(query))


def shaped(item: dict[str, Any]) -> dict[str, Any]:
    """Un bloc rendu, prêt pour le vocabulaire des pages dessinées (une liste en cartes)."""
    return drawn_blocks.shape(item)


def whole(ui: UI, blocks: Sequence[Any], query: Mapping[str, str], forms: Mapping[str, Any] | None) -> Any:
    """Un onglet de la faculté, dessiné bloc par bloc (rien à lui : un onglet secondaire de la fiche)."""
    return drawn_blocks.page(ui, blocks, query, forms=forms)


def texts(ui: UI, refs: Sequence[str]) -> dict[str, str]:
    """Des textes gardés, relus d'un coup (un texte oublié manque : « (oublié) » à qui le dit)."""
    wanted = [r for r in dict.fromkeys(refs) if r]
    if not wanted:
        return {}
    got = call(ui.kernel.ports["store"].content, wanted, label="textes d'une fiche")
    return {} if isinstance(got, Failed) else dict(got)


def safely(read: Callable[[], Any], label: str, empty: Any = None) -> Any:
    """Une lecture d'appoint (le journal, un port) : son échec tait sa carte, jamais la fiche."""
    got = call(read, label=label)
    return empty if isinstance(got, Failed) else got
