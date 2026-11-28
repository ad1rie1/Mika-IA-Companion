"""Les morceaux des pages du téléphone (ADR 0120, 0123) : une conversation, ses messages en bulles jour par jour
(``conversation_of``), les textes qu'elles citent, lus d'un coup au magasin (``reader_of``), et les réponses qu'elle a
proposées, avec leur sort (``offers_of``). Deux pages les dessinent, sur les morceaux de gabarit que l'inspecteur garde
(``handmade/sens/macros.html``) : Ses sens › Messages du téléphone (``app/domains/senses/console/tabs.py``, qui les lit
ici) et l'onglet Son téléphone de la fiche d'une personne (``person.py``). Ils se lisent dans la tranche du plugin
``phone``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from mika.app.handmade import Look, moment_fr, person_link
from mika.contracts import phone as phone_c
from mika.kernel.inspect import FORGOTTEN
from mika.plugins.phone.inspect import APPS, PER_THREAD, STATES


def conversation_of(look: Look, msgs: Sequence[Any], text: Any, owner: str) -> dict[str, Any]:
    """Une conversation : avec qui, l'appli, son dernier message ; ses messages en bulles, jour par jour. ``owner`` :
    le nom de la personne dont c'est le téléphone (ce qu'elle a écrit elle-même)."""
    last = msgs[0]
    if last.group:
        label = text(last.title_ref) or "un groupe"
    else:
        other = next((m for m in msgs if not m.own and m.name_ref), None)
        label = text(other.name_ref) if other is not None else "—"
    days: list[dict[str, Any]] = []
    for m in reversed(msgs[:PER_THREAD]):  # dans l'ordre où ils ont été écrits
        day = look.date(m.at)
        if not days or days[-1]["day"] != day:
            days.append({"day": day, "messages": []})
        days[-1]["messages"].append({"mine": m.own, "text": text(m.text_ref) or FORGOTTEN, "time": look.hm(m.at),
                                     "who": "" if m.own or not m.group else text(m.name_ref)})
    said = owner if last.own else (text(last.name_ref) or "—")
    return {"label": label, "group": last.group, "app": APPS.get(last.source, last.source),
            "preview": f"{said} : {text(last.text_ref) or FORGOTTEN}", "when": moment_fr(look, last.at),
            "count": len(msgs), "cut": max(0, len(msgs) - PER_THREAD), "days": days}


def reader_of(look: Look, msgs: Sequence[Any], offers: Sequence[Any]) -> Any:
    refs = [r for m in msgs for r in (m.text_ref, m.name_ref, m.title_ref) if r] + [o.body_ref for o in offers]
    texts = look.texts(refs)

    def text(ref: str) -> str:
        return texts.get(ref, FORGOTTEN) if ref else ""
    return text


def offers_of(look: Look, offers: Sequence[Any], text: Any) -> list[dict[str, Any]]:
    return [{"who": person_link(look, o.person), "app": APPS.get(o.source, o.source), "text": text(o.body_ref),
             "state": STATES.get(o.state, o.state) + (f" ({o.reason})" if o.reason else ""),
             "tone": "ok" if o.state == "sent" else "warn" if o.state == phone_c.OFFERED else
             "danger" if o.state == "failed" else "", "when": moment_fr(look, o.at)} for o in offers]
