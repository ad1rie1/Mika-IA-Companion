"""La fiche d'un agenda, dessinée (ADR 0309, lot 5 ; la maquette : ``output/maquette-agenda-console/agenda-perso*.html``)
: la vue d'un objet — son nom et sa couleur, son état en étiquettes (sa synchro, sa sorte, à qui il est, ses partages,
masqué), ses faits sur une ligne — et ses quatre onglets :

- **Événements** : un seul bandeau quand son compte est à reconnecter ou en panne, une bande de chiffres (cette
  semaine, à venir, ce qu'elle propose d'y ajouter, ses partages), puis ses événements, paginés, à venir ou passés
  (le bouton à choix de la vue) — un événement privé d'une autre personne reste « Occupé · privé » ;
- **Partages** : avec qui il est partagé ici, à quel niveau, ce qu'elle en fait avec chacune ; « Retirer » (le geste de
  Réglages › Droits › Partages, ADR 0210 : confirmé, audité) — le donner reste à son propriétaire ;
- **Droits** : son tableau, lu ; « Détail des accès » mène à Réglages › Droits, où un opérateur le règle ;
- **Synchronisation** : comment il se relit, sa cadence, sa fenêtre, ses pannes, et son historique.

Ses actions (en haut à droite) sont celles du plugin (``plugins/agenda/inspect/views.py``) : « Synchroniser maintenant » ; et,
selon son état, « Reconnecter » (un compte à toi seulement), « Déconnecter le compte », « Supprimer de Mika ». Aucune
n'écrit dans l'agenda : la console ne crée, ne modifie ni ne répond à la place de personne.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlencode

from markupsafe import Markup

from mika.app.domains.agenda.console.reads import Read, read
from mika.app.handmade.subjects.parts import STYLES as FICHE_STYLES
from mika.inspector import render
from mika.inspector.pages.subjects import subject_url
from mika.inspector.ui import PREFIX, UI, Overview, env
from mika.kernel.clock import DAY
from mika.kernel.inspect import Pager
from mika.plugins.agenda import CREATE, WAITING, params_of
from mika.plugins.agenda.inspect.views import (
    KIND,
    KIND_SHORT,
    NOTE_WORDS,
    PAST,
    PERIOD,
    REMINDER_WORDS,
    SYNC_MODE,
    YOURS,
    Shown,
    account_label,
    count_events,
    event_rows,
    rule_words,
    synced,
    title_of,
    week_of,
)
from mika.plugins.agenda.rights import table_of
from mika.ports.agenda import BY_HER, KIND_WORDS, NEEDS, SYNC_FAILED, SYSTEM
from mika.vocab.access import PERSON, SHARES
from mika.vocab.rights import rights_of

TABS = ("evenements", "partages", "droits", "synchro")
#: « Retirer » un partage : le geste de Réglages › Droits › Partages (``app/handmade/rights.py``, ADR 0210)
UNSHARE = f"{PREFIX}/reglages/droits/partages"
DAYS = ("lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim.")
MONTHS = ("janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc.")
LONG_MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
               "novembre", "décembre")
#: par page : ses événements, son historique
EVENTS_PAGE, NOTES_PAGE = 10, 25


def shared(s: Any) -> str:
    """Où mène un de ses agendas, partagé (Réglages › Droits › Partages, la fiche d'une personne) : sa fiche (ADR 0309,
    lot 5)."""
    return subject_url("agenda", s.key)


#: une valeur d'une case du tableau de droits → sa classe et son mot (la maquette)
VALUES = {"oui": ("oui", "Oui"), "non": ("non", "Non"), "avec ton accord": ("accord", "Ton accord"),
          "seule": ("seule", "Seule")}
#: ce qu'un partage permet à Mika avec la personne, en mots
SHARE_DOES = {"lire": "le lire avec elle", "preparer": "le lire avec elle, y ajouter avec l'accord du propriétaire",
              "servir": "le lire avec elle, y écrire et répondre avec son accord à elle"}
STYLES = (*FICHE_STYLES, "handmade/agendas.css", "handmade/person.css", "handmade/droits.css")


def _draw(template: str, **context: Any) -> Markup:
    return Markup(env.get_template(f"handmade/fiches/{template}").render(**context))


def _pages(query: Mapping[str, str], total: int, size: int) -> tuple[int, Any]:
    """La page demandée d'une liste (``?page=``), et sa pagination telle que la console la dessine."""
    try:
        number = max(1, int(str(query.get("page") or "1")))
    except ValueError:
        number = 1
    pager = Pager(number=min(number, max(1, -(-total // size))), size=size, total=total)
    return pager.offset, render.pager_ctx(pager, dict(query))


class AgendaFiche(Overview):
    """La fiche d'un agenda : son en-tête et ses quatre onglets, dessinés."""

    slug = ""
    title = "Événements"
    styles = STYLES
    tabs = TABS

    def render(self, ui: UI, key: str) -> Markup | None:
        return None

    @staticmethod
    def _of(ui: UI, key: str) -> tuple[Read, Shown] | None:
        r = read(ui)
        c = r.calendar(key)
        return (r, c) if c is not None else None

    def head(self, ui: UI, key: str) -> Markup | None:
        got = self._of(ui, key)
        if got is None:
            return None
        r, c = got
        said = synced(r.ports, r.frame, c, lambda t: r.look.day(t) if t else "jamais")
        tags = [(said.label, said.tone), (KIND_SHORT.get(c.kind, c.kind), ""),
                ("à toi" if c.who == YOURS else f"à {r.look.name(c.who)}", "owner")]
        if c.shares:
            tags.append((f"partagé · {len(c.shares)}", "info"))
        if c.hidden:
            tags.append(("masqué", ""))
        if not c.followed:
            tags.append(("plus suivi", "warn"))
        facts = [("fournisseur", KIND_WORDS.get(c.kind, c.kind)), ("compte", account_label(c)),
                 ("propriétaire", r.whose(c.who))]
        if not c.system:
            facts.append(("dernière synchro" if said.tone != "warn" else "dernière synchro réussie", said.when))
        facts.append(("événements", str(count_events(r.ports, [c.key]).get(c.key, 0))))
        return _draw("agenda_tete.html", name=c.name, color=r.colors.get(c.key, "ardoise"), tags=tags, facts=facts)

    def counts(self, ui: UI, key: str) -> Mapping[str, int]:
        got = self._of(ui, key)
        if got is None:
            return {}
        r, c = got
        return {"evenements": len(event_rows(r.ports, r.frame, c, False, None)), "partages": len(c.shares),
                "droits": len(table_of(params_of(r.frame), rights_of(r.frame.env), c.key).lines)}

    def render_tab(self, ui: UI, key: str, tab: str, blocks: Sequence[Any], query: Mapping[str, str],
                   forms: Mapping[str, Any] | None = None) -> Any:
        got = self._of(ui, key)
        if got is None or tab not in TABS:
            return None
        r, c = got
        if tab == "evenements":
            return self._events(r, c, query)
        if tab == "partages":
            return self._shares(r, c, forms)
        if tab == "droits":
            return self._rights(r, c)
        return self._sync(r, c, query)

    # ── Événements ──
    @staticmethod
    def _events(r: Read, c: Shown, query: Mapping[str, str]) -> Markup:
        past = query.get(PERIOD) == PAST
        found = event_rows(r.ports, r.frame, c, past, None)
        upcoming = found if not past else event_rows(r.ports, r.frame, c, False, None)
        today = r.frame.local(r.now).date()
        start, end = week_of(today), week_of(today) + timedelta(days=7)
        this_week = sum(1 for o in upcoming if start <= r.frame.local(o.span.start).date() < end)
        st = r.state
        proposed = [w for w in (st.writes.values() if st is not None else ()) if w.calendar == c.key
                    and w.status == WAITING and w.op == CREATE]
        said = synced(r.ports, r.frame, c, lambda t: r.look.day(t) if t else "jamais")
        offset, pager = _pages(query, len(found), EVENTS_PAGE)
        writes = [w for w in (st.writes.values() if st is not None else ()) if w.calendar == c.key and w.uid]
        rows = []
        for o in found[offset:offset + EVENTS_PAGE]:
            e = o.event
            did = []
            if e.added is not None and e.added.by == BY_HER:
                did.append("ajouté par elle")
            if e.response == NEEDS:
                did.append("invitation sans réponse")
            if any(w.uid == e.uid and w.status == WAITING for w in writes):
                did.append("elle y propose quelque chose : attend un accord")
            hidden = e.private and not e.title
            people = ", ".join(p.name or p.address for p in e.participants if not p.me) or ""
            rows.append({"when": _when(r, o), "title": title_of(e), "by_her": "ajouté par elle" in did,
                         "recurring": e.recurring, "place": "" if hidden else e.location,
                         "people": "" if hidden else people, "did": " · ".join(did), "warn": e.response == NEEDS})
        tiles = [{"label": "Cette semaine", "value": str(this_week), "sub": "à venir d'ici dimanche", "href": "",
                  "tone": ""},
                 {"label": "À venir", "value": str(len(upcoming)),
                  "sub": f"jusqu'au {_day_year(r.frame.local(r.now + params_of(r.frame).ahead_us).date())}",
                  "href": "", "tone": ""},
                 {"label": "Proposé par elle", "value": str(len(proposed)), "sub": "attend un accord" if proposed else
                  "rien en attente", "href": f"{PREFIX}/approbations/en_attente" if proposed else "",
                  "tone": "warn" if proposed else ""},
                 {"label": "Partagé avec", "value": str(len(c.shares)), "sub": ", ".join(
                     r.look.name(w[len(PERSON):]) for w in c.shares) or "personne ici",
                  "href": subject_url(KIND, c.key, "partages"), "tone": ""}]
        banner = None
        if said.tone == "warn":
            banner = {"title": said.error or f"Son compte est {said.label}.",
                      "text": f"Ses événements sont figés : {said.when}. Rien n'est perdu, la synchro reprend dès que "
                              "c'est réglé. Seul son propriétaire peut se reconnecter : ici pour un compte à toi, sinon "
                              "dans son espace (Paramètres › Agendas)."}
        return _draw("agenda_evenements.html", rows=rows, tiles=tiles, banner=banner, pager=pager, past=past,
                     total=len(found))

    # ── Partages ──
    @staticmethod
    def _shares(r: Read, c: Shown, forms: Mapping[str, Any] | None) -> Markup:
        levels = dict(SHARES)
        back = subject_url(KIND, c.key, "partages")
        rows = []
        for who, level in sorted(c.shares.items()):
            person = who[len(PERSON):]
            name = r.look.name(person)
            rows.append({"name": name, "href": subject_url("person", person, "agendas"),
                         "level": levels.get(level, level), "does": SHARE_DOES.get(level, ""), "person": person,
                         "ask": f"Retirer à {name} son accès à l'agenda « {c.name} » ? Il disparaît de son espace ; "
                                "seul son propriétaire peut le lui redonner."})
        return _draw("agenda_partages.html", rows=rows, key=c.key, kind=c.kind, owner=r.whose(c.who),
                     pager=_one(len(rows)),
                     unshare=UNSHARE, csrf=getattr(forms, "csrf", ""), back=back,
                     provider=KIND_SHORT.get(c.kind, c.kind), system=c.kind == SYSTEM)

    # ── Droits ──
    @staticmethod
    def _rights(r: Read, c: Shown) -> Markup:
        table = table_of(params_of(r.frame), rights_of(r.frame.env), c.key)
        stored = c.key in rights_of(r.frame.env).agendas

        def cells(line: Any) -> dict[str, Any]:
            words = rule_words(r.frame, line)
            return {"who": words[0], "canal": words[1], "when": words[2],
                    "cells": [VALUES.get(v, ("na", v)) for v in words[3:6]], "keep": words[6]}

        rows = [cells(line) for line in table.lines]
        default = cells(table.default)
        detail = f"{PREFIX}/reglages/droits?" + urlencode({"detail": f"agenda:{c.key}"})
        return _draw("agenda_droits.html", name=c.name, rows=rows, default=default, stored=stored, detail=detail,
                     pager=_one(len(rows) + 1),
                     edit=f"{PREFIX}/reglages/droits?" + urlencode({"detail": f"agenda:{c.key}", "regler": "1"}),
                     owner=r.whose(c.who))

    # ── Synchronisation ──
    @staticmethod
    def _sync(r: Read, c: Shown, query: Mapping[str, str]) -> Markup:
        p = params_of(r.frame)
        store = r.ports.get("agenda")
        said = synced(r.ports, r.frame, c, lambda t: r.look.day(t) if t else "jamais")
        cadence = {"google": p.google_every_us, "microsoft": p.microsoft_every_us, "caldav": p.caldav_every_us,
                   "ical": p.ical_every_us}.get(c.kind, 0)
        total = store.sync_notes_count(c.cal.account, c.key) if store is not None and not c.system else 0
        offset, pager = _pages(query, total, NOTES_PAGE)
        notes = store.sync_notes(c.cal.account, c.key, limit=NOTES_PAGE, offset=offset) \
            if store is not None and total else []
        history = [{"when": f"{r.look.day(n.at)}", "what": NOTE_WORDS.get(n.what, (n.what, ""))[0],
                    "tone": NOTE_WORDS.get(n.what, (n.what, ""))[1],
                    "changed": f"{n.changed} événement{'s' if n.changed > 1 else ''}" if n.changed else "—",
                    "detail": n.detail or ("tout le compte" if not n.calendar else "—"),
                    "warn": n.what == SYNC_FAILED} for n in notes]
        facts = [("Comment", SYNC_MODE.get(c.kind, "—"))]
        if not c.system:
            facts += [("Cadence", f"toutes les {_every(cadence)}" if cadence else "—"),
                      ("Fenêtre", f"{p.past_us // DAY} jours derrière, {p.ahead_us // DAY} jours devant"),
                      ("État", f"{said.label} · {said.when}"), ("Pannes d'affilée", str(c.state.failures if c.state
                                                                                         else 0)),
                      ("Une écriture", "part tout de suite chez son fournisseur, puis l'agenda se relit")]
            if said.error:
                facts.append(("L'erreur", said.error))
        facts.append(("Rappel d'office", REMINDER_WORDS.get(c.reminder, c.reminder)))
        return _draw("agenda_synchro.html", facts=facts, history=history, pager=pager, total=total,
                     keep=_every(p.history_us), system=c.system, settings=f"{PREFIX}/agendas/parametres#synchro")

    def links(self, ui: UI, key: str) -> list[tuple[str, str]]:
        return []


def _day_year(d: date) -> str:
    return f"{d.day} {LONG_MONTHS[d.month - 1]} {d.year}"


def _one(rows: int) -> Any:
    """La pagination d'un tableau qui tient en une page, dite comme partout."""
    return render.pager_ctx(Pager(size=max(1, rows), total=max(1, rows)), {})


def _when(r: Read, o: Any) -> str:
    """Quand a lieu une occurrence, court : « jeu. 26 · 10:00 – 11:30 », « sam. 5 déc. · journée »."""
    d = date.fromisoformat(o.span.first_day) if o.span.all_day else r.frame.local(o.span.start).date()
    today = r.frame.local(r.now).date()
    day = f"{DAYS[d.weekday()]} {d.day}" + (f" {MONTHS[d.month - 1]}" if d.month != today.month else "") + \
        (f" {d.year}" if d.year != today.year else "")
    if o.span.all_day:
        return f"{day} · journée"
    return f"{day} · {r.frame.local(o.span.start).strftime('%H:%M')} – {r.frame.local(o.span.end).strftime('%H:%M')}"


def _every(us: int) -> str:
    minutes = us // 60_000_000
    if minutes % (24 * 60) == 0:
        days = minutes // (24 * 60)
        return f"{days} jour{'s' if days > 1 else ''}"
    if minutes % 60 == 0:
        return f"{minutes // 60} h"
    return f"{minutes} min"


__all__ = ["KIND", "AgendaFiche"]
