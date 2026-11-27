"""Les vues d'inspection de la mémoire : ses souvenirs, ses croyances, ses
promesses (la projection ``memory_items``) et les moments de la vie des autres
(lus dans l'archive, ``memory_life``) ; ce qu'elle voit venir (ce qu'elle
attendait des moments annoncés, et qui tient ce qu'il annonce, ADR 0086) ; la
relecture et les nuits qui les produisent (la tranche et le journal : la
consolidation des conversations et ses passages à reprendre, le tri de la
nuit, ses lectures relues la nuit) ; et l'onglet « Mémoire » de la fiche d'une
personne.

Une action, ``reprendre`` : relire un passage de la file des reprises avec le
modèle configuré. Les corrections de l'opératrice sont dans ``actions.py``.

Les vues sont en lecture seule, paginées, bornées ; un texte effacé par
l'oubli se montre comme tel. Les filtres sont typés : une valeur inconnue est
dite, jamais devinée.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Annotated, Any

from pydantic import BaseModel, Field
from sqlalchemy import func, select

from mika.contracts import identity as identity_c
from mika.contracts import memory as c
from mika.faculties.memory import likelihood as lk
from mika.faculties.memory import tables as tb
from mika.faculties.memory.faculty import MEMORY, PENDING_CAP, MemoryParams, MemoryState, occurrence, params
from mika.faculties.memory.hearing import names_of
from mika.faculties.memory.life_archive import decode
from mika.faculties.memory.salience import Item, dormant, salience
from mika.faculties.memory.tables import ITEM_COLUMNS
from mika.kernel.clock import MINUTE
from mika.kernel.events import Content
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    ActionSlot,
    Badge,
    Block,
    Cell,
    Column,
    Disclosure,
    Fields,
    InspectContext,
    Meter,
    Note,
    Pager,
    Param,
    Prose,
    Ref,
    Row,
    Stat,
    Stats,
    Table,
    Text,
    When,
    agree,
    num_fr,
    pct_fr,
    plural,
    relative_fr,
)
from mika.kernel.operate import ActionContext, Done, Refused
from mika.vocab.affect import emotion_cell
from mika.vocab.people import fold
from mika.vocab.privacy import Sensitivity

FORGOTTEN = "(oublié)"
#: au-delà, le texte d'une ligne se replie (« lire la suite »)
CLAMP = 360
#: par page (les listes), par sorte (la fiche d'une personne)
PAGE = 50
PER_KIND = 20
#: les sources d'un élément montrées dans son détail
SOURCES_SHOWN = 20
#: une personne tapée dans un filtre : au plus tant de clés
PEOPLE_MAX = 200
#: l'historique de la relecture, des tris de la nuit et de ses lectures relues la nuit, par page (tout le journal) ;
#: chacun son curseur
RUNS_PAGE = 25
RUNS_CURSOR = "avant"
NIGHTS_CURSOR = "avant_nuits"
REREADS_CURSOR = "avant_lectures"
#: ce qu'une nuit a réuni ou confronté, au plus (une jointure du tri, une de la relecture, une confrontation)
NIGHT_LINKS = 10

KIND_FR = {c.EPISODE_MEMORY: "souvenir", c.BELIEF: "croyance", c.PROMISE: "promesse", c.EVENT: "moment de sa vie"}
#: chaque statut que la projection écrit (``projections.py``), en mots, et son ton ; une situation finie
#: (``ended``) et une prévision constatée (``resolved``) ont une étiquette discrète, mais ne sont pas des statuts
#: d'avant (``c.FORMER_STATUSES``, dont la liste estompe toute la ligne)
STATUS_FR = {c.ACTIVE_STATUS: "actif", c.SUPERSEDED_STATUS: "remplacée", c.MERGED_STATUS: "fondu dans un autre", c.JOINED_STATUS: "jointe à une autre", c.PENDING_STATUS: "en cours",
             c.HONORED: "tenue", c.DROPPED: "abandonnée", c.ENDED_STATUS: "finie", c.RESOLVED_STATUS: "constatée",
             c.RETRACTED_STATUS: "démenti(e) par l'opératrice"}
STATUS_TONE = {c.ACTIVE_STATUS: "ok", c.SUPERSEDED_STATUS: "muted", c.MERGED_STATUS: "muted", c.JOINED_STATUS: "muted", c.PENDING_STATUS: "info", c.HONORED: "ok",
               c.DROPPED: "muted", c.ENDED_STATUS: "muted", c.RESOLVED_STATUS: "muted", c.RETRACTED_STATUS: "muted"}
#: d'où elle tient une croyance (``Item.origin``), en une phrase (la colonne « origine ») ; la seule table de ces
#: mots — ``ORIGIN_SHORT`` en est la forme courte (la fiche d'une personne). Un souvenir né d'un mensonge
#: (``LIED``) n'est pas une croyance : il a sa mention à lui (``_text``)
ORIGIN_FR = {c.TOLD: "on le lui a dit", c.OBSERVED: "elle l'a vu", c.INFERRED: "elle le déduit",
             c.READ: "elle l'a lu"}
ORIGIN_SHORT = {c.TOLD: "dit", c.OBSERVED: "vu", c.INFERRED: "déduit", c.READ: "lu"}
#: comment un moment a tourné (ADR 0086), et son ton
OUTCOME_FR = {c.HAPPENED: ("a eu lieu", "ok"), c.CANCELLED: ("annulé", ""), c.MOVED: ("reporté", "warn"),
              c.UNKNOWN: ("sans nouvelles", "")}
SENSITIVITY_FR = {int(Sensitivity.NONE): "rien d'autrui", int(Sensitivity.ANODYNE): "anodin",
                  int(Sensitivity.PERSONAL): "personnel", int(Sensitivity.CONFIDENCE): "confidence"}
SENSITIVITY_TONE = {int(Sensitivity.NONE): "muted", int(Sensitivity.ANODYNE): "",
                    int(Sensitivity.PERSONAL): "info", int(Sensitivity.CONFIDENCE): "warn"}
#: les clés d'étiquettes (``Badge.key``, que lisent les onglets dessinés) qui ne sont ni un statut gardé, ni une
#: sensibilité, ni une origine, ni une issue : un élément actif qui dort, un secret ; une situation qui dure encore,
#: ou finie de la bouche de la personne
DORMANT, SECRET = "dormant", "secret"
ONGOING, ENDED = "ongoing", "ended"

SEARCH = Param("q", "recherche", placeholder="un mot du texte")
PERSON = Param("person", "personne", placeholder="un nom")
READING_HELP = {
    c.EPISODE_MEMORY: "Un souvenir raconte ce qu’elle a retenu. Sa sensibilité et son état restent visibles ; "
                "les détails donnent le texte complet et les messages d’origine.",
    c.BELIEF: "Une croyance est ce qu’elle tient pour vrai, pas une preuve. La confiance est son estimation actuelle ; "
              "l’origine distingue ce qu’on lui a dit, ce qu’elle a observé et ce qu’elle déduit.",
    c.PROMISE: "Une promesse peut être en cours, tenue ou abandonnée. Son échéance et les messages d’origine "
               "permettent de comprendre l’engagement.",
    c.EVENT: "Les moments à suivre concernent la vie des autres. Une date annuelle indique sa prochaine occurrence.",
}


def _p(frame: Frame) -> MemoryParams:
    return params(frame.env.params_of("memory", frame.root))


def _table_exists(store: Any) -> bool:
    return tb.has_table(store, tb.items())


# ── Une ligne de la projection ────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Kept:
    """Un élément retenu, avec ce que ``Item`` ne garde pas (d'où il vient)."""

    item: Item
    sources: tuple[int, ...]
    replaces: int | None
    life: c.LifeEvent | None = None


def _kept(row: Sequence[Any]) -> Kept:
    d = dict(zip(ITEM_COLUMNS, row, strict=True))
    try:
        sources = tuple(int(x) for x in json.loads(d["sources"] or "[]"))
    except (ValueError, TypeError):
        sources = ()
    return Kept(Item.of(d), sources, None if d["replaces"] is None else int(d["replaces"]))


def _select(store: Any, where: Sequence[Any], limit: int, offset: int = 0) -> list[Kept]:
    t = tb.items()
    rows = store.query_mind(select(*(t.c[n] for n in ITEM_COLUMNS)).where(*where).order_by(t.c.id.desc())
                            .limit(limit).offset(offset))
    kept = [_kept(r) for r in rows]
    ids = [k.item.id for k in kept if k.item.kind == c.EVENT]
    life = tb.life()
    archive = {decode(raw).id: decode(raw) for (raw,) in store.query_mind(
        select(life.c.payload).where(life.c.id.in_(ids)))} if ids else {}
    return [replace(k, life=archive.get(k.item.id)) for k in kept]


def _count(store: Any, where: Sequence[Any]) -> int:
    return int(store.query_mind(select(func.count()).select_from(tb.items()).where(*where))[0][0])


def _about_clause(keys: Sequence[str]) -> Any:
    """L'élément concerne l'une de ces clés (``memory_about`` : les clés de ``about``, une par ligne)."""
    ab = tb.about()
    return tb.items().c.id.in_(select(ab.c.item).where(ab.c.person.in_(sorted({tb.handle_key(k) for k in keys}))))


# ── Les personnes ─────────────────────────────────────────────────────────


def person_keys(frame: Frame, key: str) -> set[str]:
    """Toutes les clés sous lesquelles cette personne peut figurer : la clé
    donnée, la personne pour laquelle elle parle, et ses adresses."""
    resolve, _ = identity_c.resolvers(frame.get)
    person = resolve(key)
    return {key, person, *frame.get(identity_c.HANDLES(person)), *frame.get(identity_c.HANDLES(key))}


def _matching(frame: Frame, store: Any, text: str) -> list[str]:
    """Les personnes de sa mémoire qui répondent à ce qui a été tapé (une clé,
    une adresse, un nom ou un morceau de nom)."""
    ab = tb.about()
    # les clés de ``about`` de tous les éléments : ``memory_about`` les tient une par ligne
    known = [str(r[0]) for r in store.query_mind(select(ab.c.person).distinct().order_by(ab.c.person))]
    exact = person_keys(frame, text)
    names = names_of(frame, set(known))
    wanted = fold(text)
    return sorted(k for k in known if k in exact or fold(k) == wanted or wanted in fold(names.get(k, k)))[:PEOPLE_MAX]


def _person_ref(frame: Frame, key: str, names: dict[str, str]) -> Cell:
    """Un lien vers la fiche d'une personne qu'elle connaît ; sinon son nom."""
    name = names.get(key, key)
    if key.startswith("name:") or not frame.get(identity_c.IDENTITY(key)).known:
        return Text(name, hint="connue seulement de nom")
    return Ref.subject("person", key, name, "memoire")


def _about(frame: Frame, about: tuple[str, ...], names: dict[str, str]) -> Cell:
    if not about:
        return Text("personne", kind="muted")
    if len(about) == 1:
        return _person_ref(frame, about[0], names)
    return Text(", ".join(names.get(a, a) for a in about), hint="plusieurs personnes : voir le détail")


# ── Cellules communes ─────────────────────────────────────────────────────


def _n(k: Kept) -> Ref:
    return Ref("event", str(k.item.id), f"#{k.item.id}")


def _text(item: Item) -> Text:
    return Text(item.text, clamp=CLAMP) if item.text else Text(FORGOTTEN, kind="muted")


def _sensitivity(item: Item) -> Badge:
    """Sa sensibilité, sous sa clé (le niveau, en chiffre ; un mensonge et un secret, les leurs)."""
    if item.origin == c.LIED:  # ce qu'elle a affirmé de faux : il ne ressort que devant la personne
        return Badge("mensonge", "danger", key=c.LIED)
    if item.secret:
        return Badge("secret", "danger", key=SECRET)  # on lui a demandé de ne pas le répéter
    return Badge(SENSITIVITY_FR.get(item.sensitivity, str(item.sensitivity)),
                 SENSITIVITY_TONE.get(item.sensitivity, ""), key=str(item.sensitivity))


def _status(item: Item, frame: Frame, p: MemoryParams) -> Badge:
    """Son statut en mots, sous sa clé (le statut gardé) ; un élément actif qui dort, sous ``DORMANT`` : un onglet qui
    tait l'état ordinaire le dit encore."""
    listing = LISTINGS.get(item.kind)
    label = dict(listing.statuses).get(item.status) if listing else None
    label = label or STATUS_FR.get(item.status, item.status)
    if item.status == c.ACTIVE_STATUS and item.kind in (c.EPISODE_MEMORY, c.BELIEF) and dormant(item, frame.now, p):
        return Badge(f"{label} (dort)", "muted", key=DORMANT)
    return Badge(label, STATUS_TONE.get(item.status, ""), key=item.status)


def _meter(value: float | None) -> Cell:
    return None if value is None else Meter(value, pct_fr(value))


def _detail(k: Kept, frame: Frame, names: dict[str, str]) -> tuple[Block, ...]:
    item = k.item
    pairs: list[tuple[str, Cell]] = [("sorte", KIND_FR.get(item.kind, item.kind))]
    pairs += [("concerne", _person_ref(frame, a, names)) for a in item.about] or [("concerne", "personne")]
    if item.kind != c.PROMISE:
        pairs += [("confié par", _person_ref(frame, a, names)) for a in item.told_by] or [
            ("confié par", Text("personne : elle l'a vécu, vu ou raconté d'elle-même", kind="muted"))]
        pairs += [("entendu par", _person_ref(frame, a, names)) for a in item.heard_by]
        if item.origin == c.LIED:
            pairs.append(("mensonge", "ce qu'elle a affirmé de faux à cette personne (sa marque de mensonge) — il "
                                      "ne ressort que devant elle, en privé, pour ne pas se contredire ou avouer"))
        elif item.secret:
            pairs.append(("secret", "oui : on lui a demandé de ne pas le répéter (ou ça laisse deviner un secret) — "
                                    "il ne ressort que devant qui l'a confié"))
        if item.about_self:
            pairs.append(("sur elle", "ce qui la définit (un goût, un avis, un fait de sa vie) : tient des mois"
                          if item.durable_self else "ce qu'elle a raconté de sa vie : s'efface en quelques jours"))
        if item.between_us:
            pairs.append(("leur lien", "n'appartient qu'à elle et à cette personne (un surnom, une blague) : "
                                       "revient quand on lui en parle et, avec une amie, dans leur ton"))
    if item.kind != c.PROMISE:
        pairs += [("touché pour la dernière fois", When(item.touched_at)),
                  ("rappels", f"{item.recalls}" + (f", le dernier {relative_fr(item.recalled_at, frame.now)}"
                                                   if item.recalled_at else ""))]
    if item.kind == c.BELIEF:
        pairs += [("confiance déclarée", pct_fr(item.confidence)),
                  ("dite par", names.get(item.source, item.source) if item.source else "—")]
        if k.replaces is not None:
            pairs.append(("remplace", Ref("event", str(k.replaces), f"la croyance n° {k.replaces}")))
    if item.kind == c.PROMISE:
        pairs.append(("échéance", When(item.due, relative=False) if item.due else "sans échéance"))
    if item.kind == c.EVENT and item.due:
        pairs.append(("quand", When(item.due, relative=False)))
    if item.emotion and item.kind != c.EPISODE_MEMORY:
        pairs.append(("émotion", emotion_cell(item.emotion)))
    pairs += [("vient du message", Ref("event", str(s), f"message n° {s}")) for s in k.sources[:SOURCES_SHOWN]]
    if len(k.sources) > SOURCES_SHOWN:
        pairs.append(("et encore", f"{len(k.sources) - SOURCES_SHOWN} autres messages"))
    if not k.sources:
        pairs.append(("vient du message", Text("aucun message relié", kind="muted")))
    return (Prose(item.text or FORGOTTEN, title="En entier", reading=True), Fields(tuple(pairs), title="Détail"))


# ── Les quatre listes ─────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Listing:
    kind: str
    title: str
    nothing: str
    statuses: tuple[tuple[str, str], ...]
    columns: tuple[Column, ...]
    cells: Callable[[Kept, Frame, dict[str, str], MemoryParams], tuple[Cell, ...]]


def _episode_memory(k: Kept, frame: Frame, names: dict[str, str], p: MemoryParams) -> tuple[Cell, ...]:
    it = k.item
    return (_n(k), _text(it), _about(frame, it.about, names), _sensitivity(it), _meter(it.importance),
            _meter(salience(it, frame.now, p)), emotion_cell(it.emotion) if it.emotion else None,
            _status(it, frame, p), When(it.born_at))


def _belief(k: Kept, frame: Frame, names: dict[str, str], p: MemoryParams) -> tuple[Cell, ...]:
    it = k.item
    said = ORIGIN_FR.get(it.origin or "", it.origin or "—")
    if it.source:
        said += f" ({names.get(it.source, it.source)})"
    # sous sa clé (``told``…) : qui l'a dite, l'onglet dessiné la lit au détail (« dite par »), jamais dans ces mots
    origin: Cell = Badge(said, key=it.origin) if it.origin else said
    return (_n(k), _text(it), _about(frame, it.about, names), _sensitivity(it), _meter(salience(it, frame.now, p)),
            _meter(it.importance), origin, _status(it, frame, p), When(it.born_at))


def _event(k: Kept, frame: Frame, names: dict[str, str], p: MemoryParams,
           s: MemoryState | None = None) -> tuple[Cell, ...]:
    """Un moment ; une date qui revient chaque année (la tranche le sait) se montre à sa prochaine occurrence."""
    it = k.item
    ev = k.life or (s.events.get(it.id) if s is not None else None)
    yearly = ev is not None and ev.yearly
    when = occurrence(ev, frame.now, frame.env.tz_of(frame.root), p).when if ev is not None and yearly else it.due
    return (_n(k), _text(it), _about(frame, it.about, names), _sensitivity(it),
            When(when) if when else "—", Badge("chaque année", "info") if yearly else None,
            _lasting(ev), _outcome(ev), Badge("se fête", "info") if ev is not None and ev.festive else None,
            _status(it, frame, p), When(it.born_at))


def _lasting(ev: c.LifeEvent | None) -> Badge | None:
    """Une situation qui dure (depuis « quand »), ou finie de la bouche de la personne ; rien pour un moment daté."""
    if ev is None or not ev.ongoing:
        return None
    return Badge("finie", "muted", key=ENDED) if ev.ended_at else Badge("dure encore", "info", key=ONGOING)


def _outcome(ev: c.LifeEvent | None) -> Badge | None:
    """Comment un moment a tourné (ADR 0086), lu dans l'archive : il le dit encore une fois sorti de la tranche."""
    if ev is None or not ev.outcome:
        return None
    word, tone = OUTCOME_FR.get(ev.outcome, (ev.outcome, ""))
    return Badge(word, tone, key=ev.outcome)


def _promise(k: Kept, frame: Frame, names: dict[str, str], p: MemoryParams) -> tuple[Cell, ...]:
    it = k.item
    return (_n(k), _text(it), _about(frame, it.about, names), _sensitivity(it),
            When(it.due) if it.due else Text("sans échéance", kind="muted"), _status(it, frame, p),
            When(it.born_at))


N = Column("n°", "fit", detail=True)
EPISODE_MEMORIES = Listing(c.EPISODE_MEMORY, "Ses souvenirs", "pas encore de souvenir",
                           ((c.ACTIVE_STATUS, "actif"), (c.MERGED_STATUS, "fondu dans un autre"), (c.RETRACTED_STATUS, "démenti")),
                           (N, Column("souvenir", role="body"), Column("concerne"), Column("sensibilité", "fit", role="badge"), Column("importance", detail=True),
                            Column("ce qu'il en reste", hint="l'importance, estompée depuis la dernière fois qu'il a été "
                                                             "touché ; sous le seuil, il dort", detail=True),
                            Column("émotion", detail=True), Column("statut", "fit", role="badge"), Column("né", "fit")), _episode_memory)
BELIEFS = Listing(c.BELIEF, "Ses croyances", "pas encore de croyance",
                  ((c.ACTIVE_STATUS, "active"), (c.SUPERSEDED_STATUS, "remplacée"), (c.JOINED_STATUS, "jointe à une autre"),
                   (c.RESOLVED_STATUS, "constatée"), (c.RETRACTED_STATUS, "démentie")),
                  (N, Column("croyance", role="body"), Column("concerne"), Column("sensibilité", "fit", role="badge"),
                   Column("confiance", hint="effective : elle baisse lentement avec le temps"), Column("importance", detail=True),
                   Column("origine"), Column("statut", "fit", role="badge"), Column("née", "fit", detail=True)), _belief)
PROMISES = Listing(c.PROMISE, "Ses promesses", "pas encore de promesse",
                   ((c.PENDING_STATUS, "en cours"), (c.HONORED, "tenue"), (c.DROPPED, "abandonnée")),
                   (N, Column("promesse", role="body"), Column("à qui"), Column("sensibilité", "fit", role="badge"), Column("échéance", "fit"),
                    Column("statut", "fit", role="badge"), Column("faite", "fit", detail=True)), _promise)
EVENTS = Listing(c.EVENT, "Ce qui se passe dans la vie des autres", "pas encore de moment noté",
                 ((c.ACTIVE_STATUS, "à suivre"), (c.SUPERSEDED_STATUS, "remplacé"), (c.ENDED_STATUS, "finie")),
                 (N, Column("moment", role="body"), Column("de qui"), Column("sensibilité", "fit", role="badge"), Column("quand", "fit"),
                  Column("chaque année", "fit", hint="une date qui revient chaque année (un anniversaire, la date "
                                                     "d'un deuil) : « quand » est sa prochaine occurrence"),
                  Column("situation", "fit", role="badge", hint="une situation qui dure, depuis « quand » ; finie "
                                                                 "quand la personne l'a dit"),
                  Column("issue", "fit", role="badge", hint="comment il a tourné : a eu lieu, annulé, reporté, ou "
                                                             "sans nouvelles bien après sa date"),
                  Column("se fête", "fit", role="badge", hint="un moment qu'elle souhaite le jour même"),
                  Column("statut", "fit", role="badge"), Column("noté", "fit", detail=True)), _event)
LISTINGS = {x.kind: x for x in (EPISODE_MEMORIES, BELIEFS, PROMISES, EVENTS)}


def _events_of(s: MemoryState) -> Listing:
    """La liste des moments, lus dans l'archive, qui garde tout (l'issue d'un moment passé depuis longtemps
    comprise) ; la tranche ne sert qu'au moment que l'archive n'a pas encore."""
    return replace(EVENTS, cells=lambda k, frame, names, p: _event(k, frame, names, p, s))


def _rows(listing: Listing, kept: Sequence[Kept], frame: Frame) -> tuple[Row, ...]:
    p = _p(frame)
    names = names_of(frame, {a for k in kept for a in (*k.item.about, *k.item.told_by, *k.item.heard_by)}
                     | {k.item.source for k in kept if k.item.source})
    # estompée : une ligne que l'oubli a vidée, ou un élément d'avant (remplacé, fondu, joint, démenti)
    return tuple(Row(listing.cells(k, frame, names, p), detail=_detail(k, frame, names), href=_n(k),
                     tone="muted" if not k.item.text or k.item.status in c.FORMER_STATUSES else "") for k in kept)


def _list(listing: Listing, frame: Frame, ctx: InspectContext) -> list[Block]:
    if not _table_exists(ctx.store):
        return [Note("Rien n'est encore rangé : la table des éléments retenus n'existe pas.", tone="muted")]
    t = tb.items()
    where: list[Any] = [t.c.kind == listing.kind]
    q, status, person = ctx.value("q") or "", ctx.value("status") or "", ctx.value("person") or ""
    notes: list[Block] = []
    if q:
        where.append(tb.searched(t.c.folded, q))
    if status:
        where.append(t.c.status == status)
    if person:
        keys = _matching(frame, ctx.store, person)
        if not keys:
            notes.append(Note(f"Personne dans sa mémoire ne répond à « {person} ».", tone="muted"))
            keys = ["\x00"]
        where.append(_about_clause(keys))
    total = _count(ctx.store, where)
    pager = ctx.pager(size=PAGE, total=total)
    kept = _select(ctx.store, where, pager.size, pager.offset)
    filtered = bool(q or status or person)
    return [*notes, Table(listing.columns, _rows(listing, kept, frame), title=f"{listing.title} ({total})",
                          empty="aucun résultat pour ces filtres" if filtered else listing.nothing, pager=pager,
                          layout="list", link_label="Voir l’origine", caption=READING_HELP[listing.kind])]


def _params(listing: Listing) -> list[Param]:
    return [SEARCH, Param("status", "statut", "select", listing.statuses), PERSON]


@MEMORY.inspect("souvenirs", title="Souvenirs", section="memoire", order=10, params=_params(EPISODE_MEMORIES),
                description="Ce qu'elle retient de ses échanges. Cherche un souvenir ou une personne, puis "
                            "ouvre ses détails pour lire le texte entier et retrouver les messages d'origine.")
def _memories(s: MemoryState, frame: Frame, ctx: InspectContext) -> list[Block]:
    return _list(EPISODE_MEMORIES, frame, ctx)


@MEMORY.inspect("croyances", title="Croyances", section="memoire", order=20, params=_params(BELIEFS),
                description="Ce qu'elle tient pour vrai, sur quelqu'un ou sur le monde : sa confiance, qui le lui "
                            "a dit, ce qu'une croyance a remplacé.")
def _beliefs(s: MemoryState, frame: Frame, ctx: InspectContext) -> list[Block]:
    return _list(BELIEFS, frame, ctx)


@MEMORY.inspect("promesses", title="Promesses", section="memoire", order=30, params=_params(PROMISES),
                description="Ce qu'elle a promis, à qui, pour quand — et si elle l'a tenu.")
def _promises(s: MemoryState, frame: Frame, ctx: InspectContext) -> list[Block]:
    return _list(PROMISES, frame, ctx)


@MEMORY.inspect("moments", title="La vie des autres", section="memoire", order=35, params=_params(EVENTS),
                description="Ce qui va arriver aux gens qu'elle connaît (un entretien, un examen, un départ) : elle "
                            "y pense quand c'est proche, et leur en demande des nouvelles après. Une date qui revient "
                            "chaque année (un anniversaire, la date d'un deuil) se montre à sa prochaine fois.")
def _moments(s: MemoryState, frame: Frame, ctx: InspectContext) -> list[Block]:
    return _list(_events_of(s), frame, ctx)


# ── La consolidation ──────────────────────────────────────────────────────


def _consolidation_state(s: MemoryState, frame: Frame) -> Fields:
    """Où en sont la relecture des conversations et la nuit : le point de contrôle, la file, le dernier tri et la
    dernière nuit où elle a relu ses lectures (``memory.reread``, à ne pas confondre avec la relecture des
    conversations)."""
    p = _p(frame)
    pending = f"{len(s.pending)} ou plus" if len(s.pending) >= PENDING_CAP else str(len(s.pending))
    pairs: list[tuple[str, Cell]] = [
        ("relu jusqu'au message", Ref("event", str(s.checkpoint), f"n° {s.checkpoint}") if s.checkpoint else "rien"),
        ("messages pas encore relus", pending),
        ("le plus ancien en attente", Ref("event", str(s.pending[0]), f"n° {s.pending[0]}") if s.pending else "—"),
        ("dernier message", When(s.last_message_at) if s.last_message_at else "—"),
        ("dernière relecture", Ref("event", str(s.consolidated_seq), relative_fr(s.consolidated_at, frame.now))
         if s.consolidated_seq else "jamais"),
        ("fenêtres avec un passage différé", s.given_up),
        ("la dernière différée", Ref("event", str(s.given_up_seq), f"n° {s.given_up_seq}") if s.given_up_seq
         else "—"),
        ("règle de relecture", f"{p.min_messages} messages, ou {p.quiet_us // MINUTE} min de calme ; "
                               "reprises isolées avec délai croissant"),
        ("éléments retenus", s.items),
        ("promesses en cours", len(s.promises)),
        ("réflexions de la nuit à écrire", len(s.reflections)),
        ("dernière nuit triée", s.sorted_night or "—"),
        ("dernière nuit relue", s.reread_night or "—"),
        ("sa dernière lecture", Ref("event", str(s.readings_upto), f"n° {s.readings_upto}") if s.readings_upto
         else "aucune"),
    ]
    return Fields(tuple(pairs), title="La consolidation", columns=2)


def _volumes(ctx: InspectContext) -> Stats | None:
    if not _table_exists(ctx.store):
        return None
    t = tb.items()
    counts = {(str(k), str(st)): int(n) for k, st, n in ctx.store.query_mind(
        select(t.c.kind, t.c.status, func.count()).group_by(t.c.kind, t.c.status))}

    def of(kind: str, *statuses: str) -> int:
        return sum(n for (k, st), n in counts.items() if k == kind and (not statuses or st in statuses))

    return Stats((
        Stat("Souvenirs", of(c.EPISODE_MEMORY),
             plural(of(c.EPISODE_MEMORY, c.MERGED_STATUS), "fondu dans un autre", "fondus dans un autre")),
        Stat("Croyances", of(c.BELIEF), plural(of(c.BELIEF, c.SUPERSEDED_STATUS), "remplacée", "remplacées")),
        Stat("Promesses en cours", of(c.PROMISE, c.PENDING_STATUS),
             f"{plural(of(c.PROMISE, c.HONORED), 'tenue', 'tenues')}, "
             f"{plural(of(c.PROMISE, c.DROPPED), 'abandonnée', 'abandonnées')}"),
    ), title="Ce qu'elle garde")


def _history(ctx: InspectContext, event_type: Any, cursor: str) -> tuple[list[Any], Pager]:
    """Une page du journal pour ce type (``?<curseur>=`` : la suite, plus ancienne)."""
    found = ctx.events([event_type], RUNS_PAGE + 1, before=ctx.int_param(cursor, 0) or None)
    page = found[:RUNS_PAGE]
    older = ((cursor, str(page[-1].seq)),) if len(found) > RUNS_PAGE else ()
    return page, Pager(param=cursor, size=RUNS_PAGE, older=older)


def _runs(ctx: InspectContext) -> Table:
    rows = []
    found, pager = _history(ctx, c.CONSOLIDATED, RUNS_CURSOR)
    for e in found:
        d = e.data
        rows.append(Row((When(e.at), Ref("event", str(d.upto), f"n° {d.upto}") if d.upto else "—", d.produced,
                         Badge("partielle / différée", "warn") if d.failed else Badge("faite", "ok"), d.model or "—"),
                        href=Ref("event", str(e.seq), f"n° {e.seq}"), tone="danger" if d.failed else ""))
    return Table((Column("quand", "fit"), Column("relu jusqu'au"), Column("retenus", "num"), Column("issue", "fit"),
                  Column("modèle")), tuple(rows), title="Les dernières relectures",
                 empty="pas encore de relecture", pager=pager)


def _nights(ctx: InspectContext) -> Table:
    rows: list[Row] = []
    found, pager = _history(ctx, c.NIGHT_SORTED, NIGHTS_CURSOR)
    for e in found:
        merges = e.data.merges
        # au-delà de six, la cellule s'abrège : le détail de la ligne les donne toutes
        every = (Table((Column("fondu"), Column("gardé")),
                       tuple((Ref("event", str(drop), f"n° {drop}"), Ref("event", str(keep), f"n° {keep}"))
                             for keep, drop in merges), title=f"Les {len(merges)} fusions de cette nuit"),) \
            if len(merges) > 6 else ()
        rows.append(Row((e.data.night, len(merges), ", ".join(f"n° {drop} → n° {keep}" for keep, drop in merges[:6])
                         + (" …" if len(merges) > 6 else "") or "—", When(e.at)),
                        href=Ref("event", str(e.seq), f"n° {e.seq}"), detail=every))
    return Table((Column("nuit", "fit"), Column("fusions", "num"), Column("fondu → gardé"), Column("quand", "fit")),
                 tuple(rows), title="Les tris de la nuit", empty="pas encore de nuit triée", pager=pager)


def _pair(first: int, said: str, second: int) -> tuple[Cell, ...]:
    return Ref("event", str(first), f"n° {first}"), said, Ref("event", str(second), f"n° {second}")


def _linked(ctx: InspectContext, night: str) -> tuple[Block, ...]:
    """Ce que la nuit a réuni ou confronté (``memory.joined`` : du tri ou de la relecture ; ``memory.confronted``),
    paire par paire, vers les deux croyances."""
    rows: list[tuple[Cell, ...]] = []
    for e in reversed(ctx.events([c.JOINED, c.CONFRONTED], NIGHT_LINKS, where=("night", night))):
        d = e.data
        if e.type.name == c.JOINED.name:
            said = ("gardée, l'autre s'y joint : jugées la même chose par la relecture, sans être les mêmes mots"
                    if d.mute else "gardée, l'autre s'y joint")
            rows += [_pair(keep, said, joined) for keep, joined in d.pairs]
        else:
            rows += [_pair(new, "l'emporte sur", old) for new, old in d.supersedes]
            rows += [_pair(old, "elle doute entre les deux", new) for old, new in d.contests]
    if not rows:
        return ()
    return (Table((Column("croyance"), Column("ce que la nuit en fait"), Column("autre croyance")),
                  tuple(Row(r) for r in rows),
                  title=f"Les {len(rows)} paires de cette nuit" if len(rows) > 1 else "La paire de cette nuit"),)


def _rereads(ctx: InspectContext) -> Table:
    """La nuit, elle relit ses lectures (``memory.reread``) : une ligne par nuit, et en détail ce que la même nuit a
    réuni ou confronté."""
    rows: list[Row] = []
    found, pager = _history(ctx, c.REREAD, REREADS_CURSOR)
    for e in found:
        d = e.data
        rows.append(Row((d.night, d.readings, d.pairs, "—" if d.produced is None else d.produced,
                         Ref("event", str(d.upto), f"n° {d.upto}") if d.upto else "—", d.model or "—", When(e.at)),
                        href=Ref("event", str(e.seq), f"n° {e.seq}"), detail=_linked(ctx, d.night)))
    return Table((Column("nuit", "fit"), Column("lectures", "num"), Column("paires", "num"),
                  Column("retenus", "num"), Column("relues jusqu'au"), Column("modèle"), Column("quand", "fit")),
                 tuple(rows), title="Ses lectures relues la nuit", empty="pas encore de nuit relue", pager=pager)


@MEMORY.inspect("consolidation", title="Consolidation", section="memoire", order=50,
                description="La relecture : ce qui a été relu, ce qui attend, ce qui a échoué ; les nuits "
                            "où les souvenirs presque identiques se fondent ; et ses lectures relues la nuit, avec "
                            "les croyances qu'elle y réunit ou confronte.")
def _consolidation(s: MemoryState, frame: Frame, ctx: InspectContext) -> list[Block]:
    volumes = _volumes(ctx)
    return [*([volumes] if volumes else []),
            Note("Les passages à reprendre n’ont pas pu être entièrement traités. Ouvre leur détail pour comprendre "
                 "la cause et demander une nouvelle lecture avec le modèle configuré.", "info"),
            _queue(ctx), Disclosure("État détaillé de la consolidation", (_consolidation_state(s, frame),)),
            _runs(ctx), Disclosure("Historique des tris de la nuit", (_nights(ctx),)),
            Disclosure("Historique des lectures relues la nuit", (_rereads(ctx),))]


# ── Voir venir ────────────────────────────────────────────────────────────


#: la sorte d'une annonce (``likelihood.nature_of``), en mots
NATURE_FR = {c.FIRST_HAND: "de la bouche de la personne", c.REPORTED: "rapporté par un autre",
             c.OFFICIAL: "une date officielle", c.PREDICTION: "une prévision"}


def _calibration(s: MemoryState, p: MemoryParams) -> Table:
    """Ses attentes, d'une sorte d'annonce à l'autre : combien de moments constatés, l'écart quadratique moyen
    (Brier : 0, toujours juste ; 0,25, comme à pile ou face), et si elle en parle désormais plus prudemment."""
    rows = []
    for nature, cal in sorted(s.calibration.items()):
        b = lk.brier(cal)
        rows.append(Row((NATURE_FR.get(nature, nature), cal[0], "—" if b is None else num_fr(b, 3),
                         Badge("plus prudente", "warn") if lk.cautious(cal, p) else
                         Badge("assez de cas", "ok") if cal[0] >= p.calibration_min else
                         Badge(f"{cal[0]}/{p.calibration_min} cas", "muted"))))
    return Table((Column("sorte d'annonce"), Column("constatés", "num"), Column("écart moyen (Brier)", "num"),
                  Column("ce qu'elle en fait", role="badge")), tuple(rows), title="Ce qu'elle attendait",
                 empty="aucun moment constaté encore")


def _tellers(s: MemoryState, frame: Frame, p: MemoryParams) -> Table:
    """Ce qu'elle apprend de qui annonce : ses moments tenus, reportés ou annulés, et ce que vaut désormais une de
    ses annonces (sur sa propre vie), au regard de l'a priori."""
    prior = lk.prior_of(c.FIRST_HAND, p)
    names = names_of(frame, set(s.track))
    rows = []
    for teller, (kept, missed) in sorted(s.track.items(), key=lambda kv: (-sum(kv[1]), kv[0])):
        worth = lk.learned(prior, (kept, missed), p)
        rows.append(Row((names.get(teller) or teller, kept, missed,
                         Meter(worth, text=f"{pct_fr(worth)} (a priori {pct_fr(prior)})"))))
    return Table((Column("qui annonce"), Column("tenus", "num"), Column("reportés ou annulés", "num"),
                  Column("ce que vaut son annonce")), tuple(rows), title="Ce qu'elle apprend de qui annonce",
                 empty="personne encore")


@MEMORY.inspect("voir-venir", title="Voir venir", section="memoire", order=38,
                description="Ce qu'elle attendait des moments annoncés, et ce qu'elle en apprend : ses attentes "
                            "tombent-elles juste, et qui tient ce qu'il annonce.")
def _seeing_ahead(s: MemoryState, frame: Frame, ctx: InspectContext) -> list[Block]:
    """Ses attentes sur les moments annoncés et qui tient ce qu'il annonce (ADR 0086)."""
    p = params(frame.env.params_of("memory", frame.root))
    return [_calibration(s, p), _tellers(s, frame, p)]


# ── Les passages à reprendre ──────────────────────────────────────────────


class RetryExtractionArgs(BaseModel):
    key: Annotated[int, Knob(widget="hidden")] = Field(gt=0)


@MEMORY.action("reprendre", title="Reprendre cette extraction", args=RetryExtractionArgs,
               emits=[c.EXTRACTION_DEFERRED], section="memoire", inline=True,
               confirm="Relire ce passage avec le modèle actuellement configuré ?",
               description="Relit les messages sources avec le fournisseur actuellement configuré.")
def _retry_extraction(s: MemoryState, frame: Frame, args: RetryExtractionArgs, ctx: ActionContext) -> Done:
    q = tb.deferred()
    rows = ctx.store.query_mind(select(q.c.source, q.c.messages, q.c.about, q.c.attempts, q.c.aside)
                                .where(q.c.key == args.key))
    if not rows:
        raise Refused("Ce passage a déjà été traité ou oublié.")
    source, messages, about, attempts, aside = rows[0]
    # sa source le suit : une conversation reçue ailleurs se reprend par ``memory.relayed``, pas par la consolidation
    draft = c.EXTRACTION_DEFERRED.draft(key=args.key, source=source, messages=tuple(json.loads(messages)),
        aside=tuple(json.loads(aside)), about=tuple(json.loads(about)), attempts=attempts, retry_at=frame.now,
        status=c.RETRY_QUEUED, failure_code=c.OPERATOR_RETRY, detail=Content.of("Reprise demandée par l'opérateur", level=3))
    return Done(drafts=(draft,), message="Le passage sera relu.")


#: pourquoi un passage attend une reprise, en mots
DEFERRAL_REASONS = {c.INVALID_OUTPUT: "Réponse du modèle illisible", c.INVALID_ITEMS: "Éléments extraits invalides",
                    c.PROVIDER_ERROR: "Erreur du fournisseur", c.BUDGET_EXCEEDED: "Budget atteint",
                    c.OPERATOR_RETRY: "Reprise demandée"}


def _deferred_detail(text: str | None) -> Block:
    """Le détail d'un passage : une phrase se lit telle quelle ; la trace d'un échec du modèle se lit en deux temps,
    ce qui n'allait pas, en mots, puis sa réponse brute — un détail technique (« mono »), gardé tel quel
    (« [EMOTION:happy:0.7] » n'est pas un nombre à traduire)."""
    try:
        got = json.loads(text) if text else None
    except ValueError:
        got = None
    if not isinstance(got, dict):
        return Prose(text or FORGOTTEN, title="Détail du passage", reading=True)
    issues = ", ".join(DEFERRAL_REASONS.get(str(i), str(i)) for i in got.get("issues") or ()) or "—"
    return Fields((("ce qui n'allait pas", issues),
                   ("réponse du modèle", Text(str(got.get("output") or "—"), kind="mono", clamp=CLAMP))),
                  title="Détail du passage")


#: un passage à reprendre, selon d'où viennent ses messages (ADR 0224)
PASSAGE_OF = {c.FROM_THREAD: "message n° {key}",
              c.FROM_RELAYED: "conversation reçue sur le téléphone, message n° {key}"}


def _queue(ctx: InspectContext) -> Table | Note:
    q = tb.deferred()
    if not tb.has_table(ctx.store, q):
        return Note("La file de reprises n'existe pas encore.", tone="muted")
    total = int(ctx.store.query_mind(select(func.count()).select_from(q))[0][0])
    pager = ctx.pager("reprises", size=20, total=total)
    rows = ctx.store.query_mind(select(q.c.key, q.c.attempts, q.c.retry_at, q.c.status, q.c.reason, q.c.detail_ref,
                                       q.c.since, q.c.source)
                                .order_by(q.c.since, q.c.key).limit(pager.size).offset(pager.offset))
    details = ctx.store.content([row[5] for row in rows])
    return Table((Column("passage", role="title"), Column("depuis"), Column("essais"), Column("état", role="badge"),
                  Column("prochaine reprise"), Column("cause", role="body")),
        tuple(Row((Ref("event", str(key), PASSAGE_OF.get(source, PASSAGE_OF[c.FROM_THREAD]).format(key=key)),
                   When(since), attempts,
                   Badge("à examiner" if status == c.RETRY_REVIEW else "reprise prévue", "warn" if status == c.RETRY_REVIEW else "info"),
                   When(retry) if retry else "manuelle" if status == c.RETRY_REVIEW else "dès que possible",
                   DEFERRAL_REASONS.get(reason, reason)),
                  detail=(_deferred_detail(details.get(ref)),
                          ActionSlot("memory.reprendre", (("key", str(key)),))))
              for key, attempts, retry, status, reason, ref, since, source in rows),
        title=f"Passages à reprendre ({total})", empty="aucun passage en attente", pager=pager, layout="cards")


# ── La fiche d'une personne ───────────────────────────────────────────────


#: ce que l'onglet Mémoire de la fiche d'une personne liste (``_person``) : une carte par sorte
PERSON_KINDS = tuple(LISTINGS)


def _about_person(frame: Frame, key: str) -> Any:
    """L'élément concerne cette personne, sous l'une de ses clés (``person_keys``, bornées)."""
    return _about_clause(sorted(person_keys(frame, key))[:PEOPLE_MAX])


def person_total(store: Any, frame: Frame, key: str) -> int:
    """Combien l'onglet Mémoire de sa fiche liste en tout, sans recherche (``_person`` : ses quatre sortes, tous
    statuts) — un seul ``COUNT``, le compte de l'onglet dans la barre de sa fiche (``PersonOverview.counts``) ; sans
    table, il échoue (l'appelant le tait)."""
    return _count(store, [_about_person(frame, key), tb.items().c.kind.in_(PERSON_KINDS)])


@MEMORY.inspect("memoire", title="Mémoire", subject="person", order=50, params=[SEARCH],
                description="Ce qu'elle garde de cette personne : souvenirs, croyances et promesses qui la "
                            "concernent, sous l'un de ses moyens de communication.")
def _person(s: MemoryState, frame: Frame, ctx: InspectContext) -> list[Block]:
    if not ctx.subject:
        return [Note("Choisissez une personne : cet onglet se lit sur sa fiche.", tone="muted")]
    if not _table_exists(ctx.store):
        return [Note("Rien n'est encore rangé : la table des éléments retenus n'existe pas.", tone="muted")]
    keys = sorted(person_keys(frame, ctx.subject))[:PEOPLE_MAX]
    t, said = tb.items(), tb.told()
    base = [_about_person(frame, ctx.subject)]
    q = ctx.value("q") or ""
    if q:
        base.append(tb.searched(t.c.folded, q))
    told = int(ctx.store.query_mind(select(func.count()).select_from(said)
                                    .where(said.c.handle.in_(sorted({tb.handle_key(k) for k in keys}))))[0][0]) \
        if _told_exists(ctx.store) else 0
    sections: list[Block] = []
    totals: dict[str, int] = {}
    for listing in (EPISODE_MEMORIES, BELIEFS, PROMISES, _events_of(s)):
        where = [*base, t.c.kind == listing.kind]
        total = _count(ctx.store, where)
        totals[listing.kind] = total
        pager = ctx.pager(f"page_{listing.kind}", size=PER_KIND, total=total)
        kept = _select(ctx.store, where, pager.size, pager.offset)
        sections.append(Table(listing.columns, _rows(listing, kept, frame), title=f"{listing.title} ({total})",
                              empty="aucun résultat pour cette recherche" if q else listing.nothing, pager=pager,
                              layout="list", link_label="Voir l’origine", caption=READING_HELP[listing.kind]))
    stats = Stats((
        # chaque libellé s'accorde à sa valeur, qui dit déjà le nombre (« 1 moment de sa vie »)
        Stat(agree(totals[c.EPISODE_MEMORY], "Souvenir", "Souvenirs"), totals[c.EPISODE_MEMORY]),
        Stat(agree(totals[c.BELIEF], "Croyance", "Croyances"), totals[c.BELIEF]),
        Stat(agree(totals[c.PROMISE], "Promesse", "Promesses"), totals[c.PROMISE],
             f"{sum(1 for x in s.promises.values() if x.to in keys)} en cours"),
        Stat(agree(totals[c.EVENT], "Moment de sa vie", "Moments de sa vie"), totals[c.EVENT]),
        Stat("Ce qu'elle avait en tête en lui parlant", told,
             "éléments de sa mémoire que son prompt lui montrait pour parler à cette personne (pas forcément dits)"),
    ))
    return [stats, *sections]


def _told_exists(store: Any) -> bool:
    return tb.has_table(store, tb.told())
