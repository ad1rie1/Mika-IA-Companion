"""Résumé d'un épisode à partir du journal ; les traces complètes gardent leurs onglets."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from mika.contracts import runtime as rt
from mika.inspector import names
from mika.kernel.clock import US
from mika.kernel.forms import show_duration
from mika.kernel.inspect import (
    Badge,
    Column,
    Fields,
    Nav,
    NavItem,
    Note,
    Prose,
    Ref,
    Row,
    Section,
    Stat,
    Stats,
    Table,
    Text,
    When,
)
from mika.ports.journal import JournalEvent

PREVIEW_SPEECHES = 3


def overview(ui: Any, corr: str, info: dict[str, Any]) -> list[Any]:
    started, ended = info["started"], info["ended"]
    store = ui.kernel.mind.store
    e = JournalEvent
    counts = dict(store.query_mind(select(e.type, func.count()).where(e.correlation == corr).group_by(e.type)))
    speeches = counts.get(rt.UTTERANCE.name, 0)

    def tab(slug: str, label: str) -> Ref:
        return Ref("episode", corr, label, (("onglet", slug),))

    out: list[Any] = []
    if ended:
        label, tone = names.outcome(ended.data.outcome, ended.data.kind)
        out.append(Note(names.detail(ended.data.detail or ended.data.guard) or f"Issue enregistrée : {label}.", tone,
                        title="Résultat de l’épisode"))
    else:
        out.append(Note("Aucune fin n’est enregistrée. Cet épisode peut être encore en cours ou avoir été coupé ; "
                        "consulte l’activité actuelle pour vérifier.", "info", title="Épisode ouvert"))
        out.append(Nav((NavItem("Vérifier l’activité actuelle", Ref("local", "/inspecteur/decisions/en_cours", "")),)))
    duration = show_duration(max(0, ended.at - started.at)) if started and ended else "—"
    if started and ended and ended.at - started.at < US:
        duration = "< 1 s"
    out.append(Stats((Stat("Durée enregistrée", duration, "du début à la fin" if started and ended else "fin ou début absent"),
                      Stat("Paroles produites", speeches, "dans le journal", href=tab("dit", "Paroles")),
                      Stat("Événements", sum(counts.values()), "dans cet épisode", href=tab("deroule", "Déroulé")))))
    context: list[Any] = []
    if started and started.data.reply_to:
        seq = started.data.reply_to
        stored = store.get_events([seq])
        asked = ui.decode(stored[0]) if stored else None
        content = getattr(getattr(asked, "data", None), "text", None)
        message = getattr(content, "text", None)
        context.append(Prose(message if message is not None else "Le texte de ce message n’est plus disponible.",
                             "Message déclencheur", reading=True))
        context.append(Fields((("Reçu de", ui.names.who_cell(getattr(getattr(asked, "data", None), "handle", None)
                                                               or started.data.target)),
                               ("Source", Ref("event", str(seq), f"Message n° {seq}"))), columns=2))
    elif started:
        d = started.data
        by_arbiter = bool(d.selected or str(d.trigger).startswith(("selected:", "prélude:")))
        context.append(Note("Elle a démarré cet épisode à la suite d’un choix de l’arbitre." if by_arbiter else
                            "Cet épisode n’est pas lié à un message reçu. Son déclencheur est détaillé dans Décision.", "muted"))
    else:
        context.append(Note("Le début de cet épisode n’est pas au journal : son déclencheur ne peut pas être retrouvé.", "warn"))
    context.append(Nav((NavItem("Comprendre le déclenchement", tab("decision", "Décision")),)))
    out.append(Section("Ce qui l’a déclenché", tuple(context)))

    latest = ui.inspection.context().events([rt.UTTERANCE], PREVIEW_SPEECHES, correlations=[corr])
    if latest:
        rows = tuple(Row((Badge("elle", "info"), ui.names.who_cell(e.data.target), When(e.at),
                          Badge("dans le fil" if e.data.visible else "hors du fil", "muted"),
                          Text(e.data.text.text if e.data.text.text is not None else "(oublié)", clamp=600)),
                         href=Ref.why(e.seq)) for e in reversed(latest))
        out.append(Table((Column("Qui parle", role="title"), "À", "Quand", Column("Visibilité", role="badge"), Column("Texte", role="body")),
                         rows, title="Dernières paroles produites", layout="feed", link_label="Expliquer cette parole",
                         caption=f"Les {min(speeches, PREVIEW_SPEECHES)} dernières paroles sur {speeches}. "
                                 "Le journal décrit leur production ; leur livraison se vérifie dans la file de sortie."))
        out.append(Nav((NavItem("Lire toutes les paroles", tab("dit", "Paroles")),
                        NavItem("Vérifier les sorties", Ref("local", "/inspecteur/systeme/sorties", "")))))
    else:
        out.append(Note("Aucune parole n’est enregistrée pour cet épisode.", "muted", title="Paroles produites"))
    out.append(Nav((NavItem("Outils utilisés", tab("outils", "Outils")),
                    NavItem("Appels de modèle", tab("appels", "Appels")),
                    NavItem("Contexte transmis", tab("prompt", "Prompt"))), title="Pour aller plus loin"))
    return out
