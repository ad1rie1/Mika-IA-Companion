"""Les vues d'inspection de la mémoire : ses souvenirs, ses croyances, ses
promesses (la projection ``memory_items``), la relecture qui les produit (la
tranche et le journal), et l'onglet « Mémoire » de la fiche d'une personne.

Lecture seule, paginée, bornée ; un texte effacé par l'oubli se montre comme
tel. Les filtres sont typés : une valeur inconnue est dite, jamais devinée.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from mika.contracts import identity as identity_c
from mika.contracts import memory as c
from mika.faculties.memory.faculty import MEMORY, PENDING_CAP, MemoryParams, MemoryState, params
from mika.faculties.memory.projections import ITEM_COLUMNS
from mika.faculties.memory.recall import names_of
from mika.faculties.memory.salience import Item, dormant, salience
from mika.kernel.clock import MINUTE
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    Badge,
    Block,
    Cell,
    Column,
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
)
from mika.vocab.affect import emotion_cell
from mika.vocab.people import fold
from mika.vocab.privacy import Sensitivity

FORGOTTEN = "(oublié)"
#: au-delà, le texte d'une ligne se replie (« lire la suite »)
CLAMP = 160
#: par page (les listes), par sorte (la fiche d'une personne)
PAGE = 50
PER_KIND = 20
#: les sources d'un élément montrées dans son détail
SOURCES_SHOWN = 20
#: une personne tapée dans un filtre : au plus tant de clés
PEOPLE_MAX = 200
#: l'historique de la relecture et des tris de la nuit, par page (tout le journal) ; chacun son curseur
RUNS_PAGE = 25
RUNS_CURSOR = "avant"
NIGHTS_CURSOR = "avant_nuits"

KIND_FR = {c.SOUVENIR: "souvenir", c.BELIEF: "croyance", c.PROMISE: "promesse"}
STATUS_FR = {"active": "actif", "superseded": "remplacée", "merged": "fondu dans un autre", "pending": "en cours",
             c.HONORED: "tenue", c.DROPPED: "abandonnée"}
STATUS_TONE = {"active": "ok", "superseded": "muted", "merged": "muted", "pending": "info", c.HONORED: "ok",
               c.DROPPED: "muted"}
ORIGIN_FR = {c.TOLD: "on le lui a dit", c.OBSERVED: "elle l'a vu", c.INFERRED: "elle le déduit"}
SENSITIVITY_FR = {int(Sensitivity.NONE): "rien d'autrui", int(Sensitivity.ANODYNE): "anodin",
                  int(Sensitivity.PERSONAL): "personnel", int(Sensitivity.CONFIDENCE): "confidence"}
SENSITIVITY_TONE = {int(Sensitivity.NONE): "muted", int(Sensitivity.ANODYNE): "",
                    int(Sensitivity.PERSONAL): "info", int(Sensitivity.CONFIDENCE): "warn"}

SEARCH = Param("q", "recherche", placeholder="un mot du texte")
PERSON = Param("person", "personne", placeholder="un nom ou une poignée")


def number(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}".replace(".", ",")


def clip(text: str, n: int = 300) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _p(frame: Frame) -> MemoryParams:
    return params(frame.env.params_of("memory", frame.root))


def _table_exists(store: Any) -> bool:
    return bool(store.query_mind("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (c.ITEMS_TABLE,)))


# ── Une ligne de la projection ────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Kept:
    """Un élément retenu, avec ce que ``Item`` ne garde pas (d'où il vient)."""

    item: Item
    sources: tuple[int, ...]
    replaces: int | None


def _kept(row: Sequence[Any]) -> Kept:
    d = dict(zip(ITEM_COLUMNS, row, strict=True))
    try:
        sources = tuple(int(x) for x in json.loads(d["sources"] or "[]"))
    except (ValueError, TypeError):
        sources = ()
    return Kept(Item.of(d), sources, None if d["replaces"] is None else int(d["replaces"]))


def _select(store: Any, where: Sequence[str], args: Sequence[Any], limit: int, offset: int = 0) -> list[Kept]:
    clause = f" WHERE {' AND '.join(where)}" if where else ""
    rows = store.query_mind(f"SELECT {','.join(ITEM_COLUMNS)} FROM {c.ITEMS_TABLE}{clause} ORDER BY id DESC "
                            "LIMIT ? OFFSET ?", (*args, limit, offset))
    return [_kept(r) for r in rows]


def _count(store: Any, where: Sequence[str], args: Sequence[Any]) -> int:
    clause = f" WHERE {' AND '.join(where)}" if where else ""
    return int(store.query_mind(f"SELECT COUNT(*) FROM {c.ITEMS_TABLE}{clause}", tuple(args))[0][0])


def _about_clause(keys: Sequence[str]) -> str:
    return f"EXISTS (SELECT 1 FROM json_each(about) WHERE json_each.value IN ({','.join('?' * len(keys))}))"


# ── Les personnes ─────────────────────────────────────────────────────────


def person_keys(frame: Frame, key: str) -> set[str]:
    """Toutes les clés sous lesquelles cette personne peut figurer : la clé
    donnée, la personne pour laquelle elle parle, et ses poignées."""
    person = frame.get(identity_c.PERSON(key)) or key
    return {key, person, *frame.get(identity_c.HANDLES(person)), *frame.get(identity_c.HANDLES(key))}


def _matching(frame: Frame, store: Any, text: str) -> list[str]:
    """Les personnes de sa mémoire qui répondent à ce qui a été tapé (une clé,
    une poignée, un nom ou un morceau de nom)."""
    known = [str(r[0]) for r in store.query_mind(
        f"SELECT DISTINCT json_each.value FROM {c.ITEMS_TABLE}, json_each({c.ITEMS_TABLE}.about)")]
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
    return Badge(SENSITIVITY_FR.get(item.sensitivity, str(item.sensitivity)),
                 SENSITIVITY_TONE.get(item.sensitivity, ""))


def _status(item: Item, frame: Frame, p: MemoryParams) -> Badge:
    listing = LISTINGS.get(item.kind)
    label = dict(listing.statuses).get(item.status) if listing else None
    label = label or STATUS_FR.get(item.status, item.status)
    if item.status == "active" and item.kind in (c.SOUVENIR, c.BELIEF) and dormant(item, frame.now, p):
        return Badge(f"{label} (dort)", "muted")
    return Badge(label, STATUS_TONE.get(item.status, ""))


def _meter(value: float | None) -> Cell:
    return None if value is None else Meter(value, number(value))


def _detail(k: Kept, frame: Frame, names: dict[str, str], ctx: InspectContext) -> tuple[Block, ...]:
    item = k.item
    pairs: list[tuple[str, Cell]] = [("l'événement", Ref("event", str(item.id), f"n° {item.id}")),
                                     ("sorte", KIND_FR.get(item.kind, item.kind))]
    pairs += [("concerne", _person_ref(frame, a, names)) for a in item.about] or [("concerne", "personne")]
    if item.kind != c.PROMISE:
        pairs += [("importance", number(item.importance)),
                  ("touché pour la dernière fois", When(item.touched_at)),
                  ("rappels", f"{item.recalls}" + (f", le dernier {ctx.when(item.recalled_at)}"
                                                   if item.recalled_at else ""))]
    if item.kind == c.BELIEF:
        pairs += [("confiance déclarée", number(item.confidence)),
                  ("origine", ORIGIN_FR.get(item.origin or "", item.origin or "—")),
                  ("dite par", names.get(item.source, item.source) if item.source else "—")]
        if k.replaces is not None:
            pairs.append(("remplace", Ref("event", str(k.replaces), f"la croyance n° {k.replaces}")))
    if item.kind == c.PROMISE:
        pairs.append(("échéance", When(item.due, relative=False) if item.due else "sans échéance"))
    if item.emotion:
        pairs.append(("émotion", emotion_cell(item.emotion)))
    pairs += [("vient du message", Ref("event", str(s), f"message n° {s}")) for s in k.sources[:SOURCES_SHOWN]]
    if len(k.sources) > SOURCES_SHOWN:
        pairs.append(("et encore", f"{len(k.sources) - SOURCES_SHOWN} autres messages"))
    if not k.sources:
        pairs.append(("vient du message", Text("aucun message relié", kind="muted")))
    return (Fields(tuple(pairs), title="Détail"), Prose(item.text or FORGOTTEN, title="En entier"))


# ── Les trois listes ──────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Listing:
    kind: str
    title: str
    nothing: str
    statuses: tuple[tuple[str, str], ...]
    columns: tuple[Column, ...]
    cells: Callable[[Kept, Frame, dict[str, str], MemoryParams], tuple[Cell, ...]]


def _souvenir(k: Kept, frame: Frame, names: dict[str, str], p: MemoryParams) -> tuple[Cell, ...]:
    it = k.item
    return (_n(k), _text(it), _about(frame, it.about, names), _sensitivity(it), _meter(it.importance),
            _meter(salience(it, frame.now, p)), emotion_cell(it.emotion) if it.emotion else None,
            _status(it, frame, p), When(it.born_at))


def _belief(k: Kept, frame: Frame, names: dict[str, str], p: MemoryParams) -> tuple[Cell, ...]:
    it = k.item
    origin = ORIGIN_FR.get(it.origin or "", it.origin or "—")
    if it.source:
        origin += f" ({names.get(it.source, it.source)})"
    return (_n(k), _text(it), _about(frame, it.about, names), _sensitivity(it), _meter(salience(it, frame.now, p)),
            _meter(it.importance), origin, _status(it, frame, p), When(it.born_at))


def _promise(k: Kept, frame: Frame, names: dict[str, str], p: MemoryParams) -> tuple[Cell, ...]:
    it = k.item
    return (_n(k), _text(it), _about(frame, it.about, names), _sensitivity(it),
            When(it.due) if it.due else Text("sans échéance", kind="muted"), _status(it, frame, p),
            When(it.born_at))


N = Column("n°", "fit")
SOUVENIRS = Listing(c.SOUVENIR, "Ses souvenirs", "pas encore de souvenir",
                    (("active", "actif"), ("merged", "fondu dans un autre")),
                    (N, Column("souvenir"), Column("concerne"), Column("sensibilité", "fit"), Column("importance"),
                     Column("ce qu'il en reste", hint="l'importance, estompée depuis la dernière fois qu'il a été "
                                                      "touché ; sous le seuil, il dort"),
                     Column("émotion"), Column("statut", "fit"), Column("né", "fit")), _souvenir)
BELIEFS = Listing(c.BELIEF, "Ses croyances", "pas encore de croyance",
                  (("active", "active"), ("superseded", "remplacée")),
                  (N, Column("croyance"), Column("concerne"), Column("sensibilité", "fit"),
                   Column("confiance", hint="effective : elle baisse lentement avec le temps"), Column("importance"),
                   Column("origine"), Column("statut", "fit"), Column("née", "fit")), _belief)
PROMISES = Listing(c.PROMISE, "Ses promesses", "pas encore de promesse",
                   (("pending", "en cours"), (c.HONORED, "tenue"), (c.DROPPED, "abandonnée")),
                   (N, Column("promesse"), Column("à qui"), Column("sensibilité", "fit"), Column("échéance", "fit"),
                    Column("statut", "fit"), Column("faite", "fit")), _promise)
LISTINGS = {x.kind: x for x in (SOUVENIRS, BELIEFS, PROMISES)}


def _rows(listing: Listing, kept: Sequence[Kept], frame: Frame, ctx: InspectContext) -> tuple[Row, ...]:
    p = _p(frame)
    names = names_of(frame, {a for k in kept for a in k.item.about} | {k.item.source for k in kept
                                                                        if k.item.source})
    return tuple(Row(listing.cells(k, frame, names, p), detail=_detail(k, frame, names, ctx),
                     tone="muted" if not k.item.text else "") for k in kept)


def _list(listing: Listing, frame: Frame, ctx: InspectContext) -> list[Block]:
    if not _table_exists(ctx.store):
        return [Note("Rien n'est encore rangé : la table des éléments retenus n'existe pas.", tone="muted")]
    where: list[str] = ["kind=?"]
    args: list[Any] = [listing.kind]
    q, status, person = ctx.value("q") or "", ctx.value("status") or "", ctx.value("person") or ""
    notes: list[Block] = []
    if q:
        where.append("text LIKE ? ESCAPE '\\'")
        args.append(_like(q))
    if status:
        where.append("status=?")
        args.append(status)
    if person:
        keys = _matching(frame, ctx.store, person)
        if not keys:
            notes.append(Note(f"Personne dans sa mémoire ne répond à « {person} ».", tone="muted"))
            keys = ["\x00"]
        where.append(_about_clause(keys))
        args += keys
    total = _count(ctx.store, where, args)
    pager = ctx.pager(size=PAGE, total=total)
    kept = _select(ctx.store, where, args, pager.size, pager.offset)
    filtered = bool(q or status or person)
    return [*notes, Table(listing.columns, _rows(listing, kept, frame, ctx), title=f"{listing.title} ({total})",
                          empty="aucun résultat pour ces filtres" if filtered else listing.nothing, pager=pager,
                          filters=("q", "status", "person"))]


def _params(listing: Listing) -> list[Param]:
    return [SEARCH, Param("status", "statut", "select", listing.statuses), PERSON]


@MEMORY.inspect("souvenirs", title="Souvenirs", section="memoire", order=10, params=_params(SOUVENIRS),
                description="Les épisodes qu'elle a vécus, à la première personne, tels que la relecture les a "
                            "gardés. La v2 n'extrait ni thèmes ni entités : un souvenir porte seulement les "
                            "personnes qu'il concerne, sa sensibilité et les messages d'où il vient.")
def _souvenirs(s: MemoryState, frame: Frame, ctx: InspectContext) -> list[Block]:
    return _list(SOUVENIRS, frame, ctx)


@MEMORY.inspect("croyances", title="Croyances", section="memoire", order=20, params=_params(BELIEFS),
                description="Ce qu'elle tient pour vrai, sur quelqu'un ou sur le monde : sa confiance, qui le lui "
                            "a dit, ce qu'une croyance a remplacé.")
def _beliefs(s: MemoryState, frame: Frame, ctx: InspectContext) -> list[Block]:
    return _list(BELIEFS, frame, ctx)


@MEMORY.inspect("promesses", title="Promesses", section="memoire", order=30, params=_params(PROMISES),
                description="Ce qu'elle a promis, à qui, pour quand — et si elle l'a tenu.")
def _promises(s: MemoryState, frame: Frame, ctx: InspectContext) -> list[Block]:
    return _list(PROMISES, frame, ctx)


# ── La relecture ──────────────────────────────────────────────────────────


def _rereading(s: MemoryState, frame: Frame, ctx: InspectContext) -> Fields:
    p = _p(frame)
    pending = f"{len(s.pending)} ou plus" if len(s.pending) >= PENDING_CAP else str(len(s.pending))
    pairs: list[tuple[str, Cell]] = [
        ("relu jusqu'au message", Ref("event", str(s.checkpoint), f"n° {s.checkpoint}") if s.checkpoint else "rien"),
        ("messages pas encore relus", pending),
        ("le plus ancien en attente", Ref("event", str(s.pending[0]), f"n° {s.pending[0]}") if s.pending else "—"),
        ("dernier message", When(s.last_message_at) if s.last_message_at else "—"),
        ("dernière relecture", Ref("event", str(s.consolidated_seq), ctx.when(s.consolidated_at))
         if s.consolidated_seq else "jamais"),
        ("fenêtres abandonnées", s.given_up),
        ("la dernière abandonnée", Ref("event", str(s.given_up_seq), f"n° {s.given_up_seq}") if s.given_up_seq
         else "—"),
        ("règle de relecture", f"{p.min_messages} messages, ou {p.quiet_us // MINUTE} min de calme ; "
                               f"abandon après {p.max_attempts} échecs sur la même fenêtre"),
        ("éléments retenus", s.items),
        ("promesses en cours", len(s.promises)),
        ("réflexions de la nuit à écrire", len(s.reflections)),
        ("dernière nuit triée", s.sorted_night or "—"),
    ]
    return Fields(tuple(pairs), title="La relecture", columns=2)


def _volumes(ctx: InspectContext) -> Stats | None:
    if not _table_exists(ctx.store):
        return None
    counts = {(str(k), str(st)): int(n) for k, st, n in ctx.store.query_mind(
        f"SELECT kind, status, COUNT(*) FROM {c.ITEMS_TABLE} GROUP BY kind, status")}

    def of(kind: str, *statuses: str) -> int:
        return sum(n for (k, st), n in counts.items() if k == kind and (not statuses or st in statuses))

    return Stats((
        Stat("Souvenirs", of(c.SOUVENIR), f"{of(c.SOUVENIR, 'merged')} fondus dans un autre"),
        Stat("Croyances", of(c.BELIEF), f"{of(c.BELIEF, 'superseded')} remplacées"),
        Stat("Promesses en cours", of(c.PROMISE, "pending"),
             f"{of(c.PROMISE, c.HONORED)} tenues, {of(c.PROMISE, c.DROPPED)} abandonnées"),
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
                         Badge("abandonnée", "danger") if d.failed else Badge("faite", "ok"), d.model or "—"),
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


@MEMORY.inspect("consolidation", title="Consolidation", section="memoire", order=40,
                description="La relecture : ce qui a été relu, ce qui attend, ce qui a échoué ; et les nuits "
                            "où les souvenirs presque identiques se fondent.")
def _consolidation(s: MemoryState, frame: Frame, ctx: InspectContext) -> list[Block]:
    volumes = _volumes(ctx)
    return [*([volumes] if volumes else []), _rereading(s, frame, ctx), _runs(ctx), _nights(ctx)]


# ── La fiche d'une personne ───────────────────────────────────────────────

#: le type d'objet « personne » (déclaré par l'identité) : l'onglet se range sur sa fiche
PERSON_KIND = "person"


@MEMORY.inspect("memoire", title="Mémoire", subject=PERSON_KIND, hidden=not PERSON_KIND, order=50, params=[SEARCH],
                description="Ce qu'elle garde de cette personne : souvenirs, croyances et promesses qui la "
                            "concernent, sous l'une de ses poignées.")
def _person(s: MemoryState, frame: Frame, ctx: InspectContext) -> list[Block]:
    if not ctx.subject:
        return [Note("Choisissez une personne : cet onglet se lit sur sa fiche.", tone="muted")]
    if not _table_exists(ctx.store):
        return [Note("Rien n'est encore rangé : la table des éléments retenus n'existe pas.", tone="muted")]
    keys = sorted(person_keys(frame, ctx.subject))[:PEOPLE_MAX]
    base = [_about_clause(keys)]
    args: list[Any] = list(keys)
    q = ctx.value("q") or ""
    if q:
        base.append("text LIKE ? ESCAPE '\\'")
        args.append(_like(q))
    told = int(ctx.store.query_mind(f"SELECT COUNT(*) FROM {c.TOLD_TABLE} WHERE handle IN "
                                    f"({','.join('?' * len(keys))})", tuple(keys))[0][0]) \
        if _told_exists(ctx.store) else 0
    sections: list[Block] = []
    totals: dict[str, int] = {}
    for listing in (SOUVENIRS, BELIEFS, PROMISES):
        where, wargs = [*base, "kind=?"], [*args, listing.kind]
        total = _count(ctx.store, where, wargs)
        totals[listing.kind] = total
        pager = ctx.pager(f"page_{listing.kind}", size=PER_KIND, total=total)
        kept = _select(ctx.store, where, wargs, pager.size, pager.offset)
        sections.append(Table(listing.columns, _rows(listing, kept, frame, ctx), title=f"{listing.title} ({total})",
                              empty="aucun résultat pour cette recherche" if q else listing.nothing, pager=pager))
    stats = Stats((
        Stat("Souvenirs", totals[c.SOUVENIR]),
        Stat("Croyances", totals[c.BELIEF]),
        Stat("Promesses", totals[c.PROMISE], f"{sum(1 for x in s.promises.values() if x.to in keys)} en cours"),
        Stat("Ce qu'elle lui a raconté", told, "éléments de sa mémoire déjà dits à cette personne"),
    ))
    return [stats, *sections]


def _told_exists(store: Any) -> bool:
    return bool(store.query_mind("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (c.TOLD_TABLE,)))
