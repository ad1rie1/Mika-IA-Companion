"""Connexions extérieures › Messages du téléphone et Localisation, dessinées (ADR 0121, 0123), et leurs onglets sur la
fiche d'une personne (« Son téléphone », « Sa position »).

Les messages : personne par personne, conversation par conversation (un contact, un groupe), ses messages en bulles
comme dans les Échanges ; les réponses qu'elle a proposées et leur sort. La localisation : une ligne par personne (ses
téléphones réunis), puis ce que les téléphones lui ont dit. Lus dans la tranche de leur plugin et leurs textes au
magasin, comme leurs vues, qui restent leur source pour la console en MCP et le repli (un dessin qui échoue rend la
main à leurs blocs).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlencode

from markupsafe import Markup

from mika.app.handmade import Look
from mika.contracts import location as location_c
from mika.contracts import phone as phone_c
from mika.inspector.pages.subjects import fiche_url
from mika.inspector.ui import UI, env
from mika.kernel.clock import DAY
from mika.plugins.location.inspect import PAGE as POSITIONS
from mika.plugins.location.inspect import SHOWN as SAID
from mika.plugins.location.inspect import by_person
from mika.plugins.phone.inspect import APPS, FORGOTTEN, PER_PERSON, PER_THREAD, STATES, threads
from mika.plugins.phone.inspect import PAGE as MESSAGES
from mika.vocab.people import is_internal

#: le paramètre qui ne garde qu'une personne (le même que celui des vues des plugins)
WHO = "personne"


def _slice(look: Look, owner: str) -> Any:
    try:
        return look.frame.state(owner)
    except KeyError:  # ce plugin n'est pas composé ici
        return None


def _person(look: Look, person: str) -> dict[str, str]:
    if not person or is_internal(person):
        return {"name": "personne", "href": ""}
    return {"name": look.name(person), "href": look.href(person)}


def _when(look: Look, at: int) -> str:
    """Quand : « aujourd'hui à 14:02 », « hier à 9:10 », sinon « mardi 14 oct. à 18:30 »."""
    said = look.day(at)
    return said if said.startswith(("aujourd'hui", "hier")) else f"{look.date(at)} à {look.hm(at)}"


def _link(page: str, **params: Any) -> str:
    """Une page, et ces paramètres en plus de ceux qu'elle a."""
    return page + ("&" if "?" in page else "?") + urlencode(params) if params else page


def _chips(look: Look, page: str, people: Mapping[str, int], chosen: str) -> list[dict[str, Any]]:
    """Le filtre par personne : tout le monde, puis chacune (son compte)."""
    if len(people) < 2:
        return []
    return [{"text": "Tout le monde", "href": page, "on": not chosen, "count": len(people)},
            *({"text": look.name(p), "href": f"{page}?" + urlencode({WHO: p}), "on": p == chosen, "count": n}
              for p, n in people.items())]


# ── le téléphone ──

def _conversation(look: Look, msgs: Sequence[Any], text: Any, owner: str) -> dict[str, Any]:
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
            "preview": f"{said} : {text(last.text_ref) or FORGOTTEN}", "when": _when(look, last.at),
            "count": len(msgs), "cut": max(0, len(msgs) - PER_THREAD), "days": days}


def _reader(look: Look, msgs: Sequence[Any], offers: Sequence[Any]) -> Any:
    refs = [r for m in msgs for r in (m.text_ref, m.name_ref, m.title_ref) if r] + [o.body_ref for o in offers]
    texts = look.texts(refs)

    def text(ref: str) -> str:
        return texts.get(ref, FORGOTTEN) if ref else ""
    return text


def _offers(look: Look, offers: Sequence[Any], text: Any) -> list[dict[str, Any]]:
    return [{"who": _person(look, o.person), "app": APPS.get(o.source, o.source), "text": text(o.body_ref),
             "state": STATES.get(o.state, o.state) + (f" ({o.reason})" if o.reason else ""),
             "tone": "ok" if o.state == "sent" else "warn" if o.state == phone_c.OFFERED else
             "danger" if o.state == "failed" else "", "when": _when(look, o.at)} for o in offers]


def messages(ui: UI, items: Sequence[Any], query: Mapping[str, str]) -> Markup | None:
    """Connexions extérieures › Messages du téléphone : le téléphone de chaque personne, ses conversations."""
    look = Look.of(ui, DAY)
    s = _slice(look, "phone")
    if s is None:
        return None
    if not s.messages and not s.offers:
        return Markup(env.get_template("handmade/sens/messages.html").render(empty=True))
    people: dict[str, list[Any]] = {}
    for m in sorted(s.messages.values(), key=lambda m: -m.seq):
        people.setdefault(m.person, []).append(m)
    chosen = str(query.get(WHO, ""))
    chosen = chosen if chosen in people else ""
    cut = not chosen and len(people) > 1  # tout le monde : quelques conversations par personne
    shown = {chosen: people[chosen]} if chosen else people
    convs = {p: threads(msgs) for p, msgs in shown.items()}
    offers = sorted((o for o in s.offers.values() if not chosen or o.person == chosen), key=lambda o: -o.seq)[:60]
    text = _reader(look, [m for ts in convs.values() for t in (ts[:PER_PERSON] if cut else ts)
                          for m in t[:PER_THREAD]], offers)
    phones = [{**_person(look, p), "count": len(people[p]),
               "conversations": [_conversation(look, t, text, look.name(p)) for t in (ts[:PER_PERSON] if cut else ts)],
               "more": len(ts) - PER_PERSON if cut and len(ts) > PER_PERSON else 0, "total": len(ts),
               "only": f"{MESSAGES}?" + urlencode({WHO: p})} for p, ts in convs.items()]
    return Markup(env.get_template("handmade/sens/messages.html").render(
        chips=_chips(look, MESSAGES, {p: len(m) for p, m in people.items()}, chosen), phones=phones,
        offers=_offers(look, offers, text), who=not chosen))


def phone_tab(ui: UI, key: str, blocks: Sequence[Any], query: Mapping[str, str]) -> Markup | None:
    """La fiche d'une personne › Son téléphone : ses conversations, les réponses qu'elle a proposées."""
    look = Look.of(ui, DAY)
    s = _slice(look, "phone")
    if s is None:
        return None
    convs = threads([m for m in s.messages.values() if m.person == key])
    offers = sorted((o for o in s.offers.values() if o.person == key), key=lambda o: -o.seq)[:60]
    text = _reader(look, [m for t in convs for m in t[:PER_THREAD]], offers)
    return Markup(env.get_template("handmade/person/tabs/telephone.html").render(
        conversations=[_conversation(look, t, text, look.name(key)) for t in convs], offers=_offers(look, offers, text),
        name=look.name(key)))


# ── la localisation ──

def _accuracy(m: int) -> str:
    return f"à {m} m près" if m else "précision inconnue"


def _fix(look: Look, f: Any, texts: Mapping[str, str]) -> dict[str, Any]:
    return {"place": texts.get(f.label_ref, FORGOTTEN) if f.label_ref else "", "coords": texts.get(f.coords_ref,
            FORGOTTEN), "accuracy": _accuracy(f.accuracy_m), "when": _when(look, f.fixed_at),
            "ago": look.ago(f.fixed_at), "handle": f.handle}


def _said(look: Look, query: Mapping[str, str], person: str, page: str) -> dict[str, Any]:
    """Ce que les téléphones lui ont dit (d'une personne, ou de tous), du plus récent, par pages."""
    before = int(query.get("avant", 0) or 0) if str(query.get("avant", "")).isdigit() else 0
    got = look.ui.inspection.context().events([location_c.LOCATED, location_c.CLEARED], SAID,
                                              before=before or None, where=("person", person) if person else None)
    entries = []
    for e in got:
        d = e.data
        cleared = e.type.name == location_c.CLEARED.name
        entries.append({"when": _when(look, e.at), "who": _person(look, d.person), "cleared": cleared,
                        "place": "" if cleared or d.label is None else (d.label.text or FORGOTTEN),
                        "coords": "" if cleared else (d.coords.text or FORGOTTEN),
                        "accuracy": "" if cleared else _accuracy(int(d.accuracy_m))})
    keep = {k: v for k, v in query.items() if k not in ("avant", "flash", "onglet")}
    older = _link(page, **keep, avant=got[-1].seq) if len(got) == SAID else ""
    newer = _link(page, **keep) if before else ""
    return {"entries": entries, "older": older, "newer": newer}


def positions(ui: UI, items: Sequence[Any], query: Mapping[str, str]) -> Markup | None:
    """Connexions extérieures › Localisation : où est chaque personne, puis ce que les téléphones lui ont dit."""
    look = Look.of(ui, DAY)
    s = _slice(look, "location")
    if s is None:
        return None
    if not s.fixes:
        return Markup(env.get_template("handmade/sens/positions.html").render(
            empty=True, said=_said(look, query, "", POSITIONS), who=True))
    people = by_person(s)
    chosen = str(query.get(WHO, ""))
    chosen = chosen if chosen in people else ""
    shown = {chosen: people[chosen]} if chosen else people
    texts = look.texts([r for fs in shown.values() for f in fs for r in (f.coords_ref, f.label_ref)])
    where = [{**_person(look, p), **_fix(look, fs[0], texts), "phones": len(fs),
              "others": [_fix(look, f, texts) for f in fs[1:]]} for p, fs in shown.items()]
    return Markup(env.get_template("handmade/sens/positions.html").render(
        chips=_chips(look, POSITIONS, {p: len(fs) for p, fs in people.items()}, chosen), where=where,
        said=_said(look, query, chosen, POSITIONS), who=not chosen))


def position_tab(ui: UI, key: str, blocks: Sequence[Any], query: Mapping[str, str]) -> Markup | None:
    """La fiche d'une personne › Sa position : sa dernière position, téléphone par téléphone, et son journal."""
    look = Look.of(ui, DAY)
    s = _slice(look, "location")
    if s is None:
        return None
    fixes = by_person(s).get(key, [])
    texts = look.texts([r for f in fixes for r in (f.coords_ref, f.label_ref)])
    said = _said(look, query, key, fiche_url("person", key, "position"))
    return Markup(env.get_template("handmade/person/tabs/position.html").render(
        fixes=[_fix(look, f, texts) for f in fixes], said=said, name=look.name(key)))
