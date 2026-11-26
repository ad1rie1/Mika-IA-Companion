"""L'agenda dans la console (ADR 0309, lot 3a) : le tableau de droits de chaque agenda, une sorte de tableau de plus
sur la page « Droits » (Réglages › Droits, ADR 0133–0134) — ses lignes en mots, ce qu'aucune ligne n'ouvre, et ce
qu'il accorde à qui est en face. Échanges › Agendas, la fiche d'un agenda et l'onglet « Agendas » de la fiche d'une
personne sont dans ``views`` (lot 5).
"""

from __future__ import annotations

from typing import Any

from mika.contracts import identity as identity_c
from mika.contracts.agenda import RIGHTS_SORT, WRITE_WORDS, AgendaRule
from mika.kernel.frame import Frame
from mika.kernel.rights import Grant, RuleTable
from mika.plugins.agenda import AGENDA, AgendaState, owner, params_of
from mika.plugins.agenda.rights import here, policy_of, table_of
from mika.ports.agenda import KIND_WORDS, Calendar, split_calendar_key
from mika.vocab.access import (
    KEEP_WORDS,
    NO,
    PERSON,
    canal_words,
    when_words,
    who_words,
)
from mika.vocab.rights import closeness_of, rights_of

#: ses colonnes, dans l'ordre de la maquette
COLUMNS = ("qui", "par où", "quand", "lire", "ajouter, modifier, supprimer", "répondre aux invitations",
           "ce qu'elle en garde")
#: ce qu'aucune ligne n'ouvre
FLOORS = ("rien dans un salon (des témoins), rien pour une inconnue, rien sans personne hors du travail",
          "un agenda sert à son propriétaire et à qui il le partage, à son niveau : « lire » n'écrit jamais, « lire "
          "et préparer » écrit sur l'accord du propriétaire",
          "masqué, ou sous un compte décoché, il ne sert plus")


def _name(frame: Frame | None, person: str) -> str:
    view = frame.get(identity_c.IDENTITY(person)) if frame is not None and person else None
    return str(getattr(view, "name", "") or person)


def _row(line: AgendaRule, frame: Frame) -> tuple[str, ...]:
    return (who_words(line.who, lambda p: _name(frame, p)) if line.who else "—", canal_words(line.canal),
            when_words(line.when), "oui" if line.read else "non", WRITE_WORDS[line.write], WRITE_WORDS[line.respond],
            KEEP_WORDS[line.keep])


def _title(frame: Frame, cal: Calendar, holder: str, kind: str) -> str:
    whose = f"à {_name(frame, holder[len(PERSON):])}" if holder.startswith(PERSON) else "à toi"
    return f"L'agenda « {cal.name or cal.key} » ({KIND_WORDS.get(kind, kind)}, {whose})"


def _calendars(ctx: Any) -> list[Calendar]:
    store = ctx.ports.get("agenda")
    return list(store.calendars()) if store is not None else []


def _kind(ctx: Any, calendar: str) -> str:
    store = ctx.ports.get("agenda")
    got = store.account(split_calendar_key(calendar)[0]) if store is not None else None
    return got.kind if got is not None else ""


def _agenda_grants(s: AgendaState, frame: Frame, ctx: Any, audience: Any, kind: str) -> list[Grant]:
    """Ce qu'elle fait de chaque agenda devant cette audience, à ce moment, et la ligne qui en décide."""
    p, rights, close = params_of(frame), rights_of(frame.env), closeness_of(frame.env, frame)
    out = []
    for cal in _calendars(ctx):
        holder = owner(p, split_calendar_key(cal.key)[0])
        got = here(p, rights, cal.key, audience, kind, close)
        title = _title(frame, cal, holder, _kind(ctx, cal.key))
        if got is None:
            out.append(Grant(f"agenda:{cal.key}", title, (("lit", "non"),), "rien ne le lui ouvre ici", closed=True))
            continue
        out.append(Grant(f"agenda:{cal.key}", title,
                         (("lit", "oui"), ("écrit", WRITE_WORDS[policy_of(got.write)]),
                          ("répond", WRITE_WORDS[policy_of(got.respond)]), ("garde", KEEP_WORDS[got.keep])),
                         got.allowance.why + ("" if got.owned else f" — partagé : {got.reach}")))
    return out


@AGENDA.rights(RIGHTS_SORT, title="Agendas", order=25, grants=_agenda_grants,
               description="Qui peut lire chaque agenda par elle, y faire ajouter, modifier ou supprimer un "
                           "rendez-vous, répondre à ses invitations, et ce qu'elle en garde (ADR 0309) : réglé par son "
                           "propriétaire, ou ici par un opérateur ; un partage ajoute la ligne de la personne.")
def _agenda_tables(s: AgendaState, frame: Frame, ctx: Any) -> list[RuleTable]:
    p, rights = params_of(frame), rights_of(frame.env)
    out = []
    for cal in _calendars(ctx):
        table = table_of(p, rights, cal.key)
        holder = owner(p, split_calendar_key(cal.key)[0])
        note = "" if cal.key in rights.sort(RIGHTS_SORT) else "tableau par défaut (son propriétaire et ses partages)"
        out.append(RuleTable(f"agenda:{cal.key}", _title(frame, cal, holder, _kind(ctx, cal.key)), COLUMNS,
                             tuple(_row(line, frame) for line in table.lines), _row(table.default, frame),
                             floors=FLOORS, note=note))
    return out


from mika.plugins.agenda.inspect import views as views  # noqa: E402 — Échanges › Agendas, la fiche d'un agenda (lot 5)

__all__ = ["COLUMNS", "FLOORS", "NO"]
