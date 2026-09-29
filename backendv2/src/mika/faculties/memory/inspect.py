"""La vue d'inspection de la mémoire : ce qu'elle a retenu (la projection
``memory_items``), et où en est la relecture (la tranche).

Lecture seule, bornée aux plus récents ; un texte effacé par l'oubli se
montre comme tel. Les filtres invalides sont dits, jamais devinés.
"""

from __future__ import annotations

from typing import Any

from mika.contracts import memory as c
from mika.faculties.memory.faculty import MEMORY, PENDING_CAP, MemoryState, params
from mika.faculties.memory.projections import ITEM_COLUMNS
from mika.faculties.memory.recall import names_of
from mika.faculties.memory.salience import Item, dormant, salience
from mika.kernel.clock import MINUTE
from mika.kernel.frame import Frame
from mika.kernel.inspect import Block, Cell, Fields, InspectContext, Note, Ref, Table
from mika.vocab.people import fold
from mika.vocab.privacy import Sensitivity

SHOWN = 100
TEXT_MAX = 300
FORGOTTEN = "(oublié)"

KIND_FR = {c.SOUVENIR: "souvenir", c.BELIEF: "croyance", c.PROMISE: "promesse"}
STATUS_FR = {"active": "actif", "superseded": "remplacée", "merged": "fondu", "pending": "en cours",
             c.HONORED: "tenue", c.DROPPED: "abandonnée"}
ORIGIN_FR = {c.TOLD: "on le lui a dit", c.OBSERVED: "elle l'a vu", c.INFERRED: "elle le déduit"}
SENSITIVITY_FR = {int(Sensitivity.NONE): "rien d'autrui", int(Sensitivity.ANODYNE): "anodin",
                  int(Sensitivity.PERSONAL): "personnel", int(Sensitivity.CONFIDENCE): "confidence"}


def number(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}".replace(".", ",")


def clip(text: str, n: int = TEXT_MAX) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def choice(value: str, table: dict[str, str]) -> str | None:
    """La valeur canonique d'un filtre, donnée par son nom ou son libellé."""
    wanted = fold(value)
    return next((key for key, label in table.items() if wanted in (fold(key), fold(label))), None)


def _like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _filters(ctx: InspectContext) -> tuple[list[str], list[Any], list[str]]:
    where: list[str] = []
    args: list[Any] = []
    problems: list[str] = []
    q = ctx.param("q")
    if q:
        where.append("text LIKE ? ESCAPE '\\'")
        args.append(_like(q))
    for name, column, table in (("kind", "kind", KIND_FR), ("status", "status", STATUS_FR)):
        raw = ctx.param(name)
        if not raw:
            continue
        value = choice(raw, table)
        if value is None:
            accepted = ", ".join(sorted(table.values()))
            problems.append(f"Filtre « {name} » inconnu : « {raw} ». Valeurs possibles : {accepted}.")
            continue
        where.append(f"{column}=?")
        args.append(value)
    return where, args, problems


def _table_exists(store: Any) -> bool:
    return bool(store.query_mind("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (c.ITEMS_TABLE,)))


def _consolidation(s: MemoryState, frame: Frame, ctx: InspectContext) -> Fields:
    p = params(frame.env.params_of("memory", frame.root))
    pending = f"{len(s.pending)} ou plus" if len(s.pending) >= PENDING_CAP else str(len(s.pending))
    pairs: list[tuple[str, Cell]] = [
        ("relu jusqu'au message", Ref("event", str(s.checkpoint), f"#{s.checkpoint}") if s.checkpoint else "rien"),
        ("messages pas encore relus", pending),
        ("le plus ancien en attente", Ref("event", str(s.pending[0]), f"#{s.pending[0]}") if s.pending else "—"),
        ("dernier message", ctx.when(s.last_message_at) if s.last_message_at else "—"),
        ("dernière relecture", Ref("event", str(s.consolidated_seq), ctx.when(s.consolidated_at))
         if s.consolidated_seq else "jamais"),
        ("fenêtres abandonnées", s.given_up),
        ("la dernière abandonnée", Ref("event", str(s.given_up_seq), f"#{s.given_up_seq}") if s.given_up_seq
         else "—"),
        ("règle de relecture", f"{p.min_messages} messages, ou {p.quiet_us // MINUTE} min de calme ; "
                               f"abandon après {p.max_attempts} échecs sur la même fenêtre"),
        ("éléments retenus", s.items),
        ("promesses en cours", len(s.promises)),
        ("réflexions de la nuit à écrire", len(s.reflections)),
        ("dernière nuit triée", s.sorted_night or "—"),
    ]
    return Fields(tuple(pairs), title="La relecture")


def _row(item: Item, frame: Frame, names: dict[str, str], ctx: InspectContext) -> tuple[Cell, ...]:
    p = params(frame.env.params_of("memory", frame.root))
    status = STATUS_FR.get(item.status, item.status)
    if item.status == "active" and item.kind in (c.SOUVENIR, c.BELIEF) and dormant(item, frame.now, p):
        status += " (dort)"
    remains = salience(item, frame.now, p) if item.kind in (c.SOUVENIR, c.BELIEF) else None
    return (
        Ref("event", str(item.id), f"#{item.id}"),
        KIND_FR.get(item.kind, item.kind),
        clip(item.text) if item.text else FORGOTTEN,
        ", ".join(names.get(a, a) for a in item.about) or "personne",
        SENSITIVITY_FR.get(item.sensitivity, str(item.sensitivity)),
        number(item.importance),
        number(remains),
        number(item.confidence),
        ORIGIN_FR.get(item.origin or "", item.origin or "—"),
        status,
        ctx.when(item.born_at),
    )


@MEMORY.inspect("souvenirs", title="Mémoire",
                params=[("q", "recherche"), ("kind", "sorte (souvenir, croyance, promesse)"), ("status", "statut")])
def _inspect(s: MemoryState, frame: Frame, ctx: InspectContext) -> list[Block]:
    status = _consolidation(s, frame, ctx)
    where, args, problems = _filters(ctx)
    if problems:
        return [*(Note(text, tone="ko") for text in problems), status]
    if not _table_exists(ctx.store):
        return [status, Note("Rien n'est encore rangé : la table des éléments retenus n'existe pas.", tone="mut")]
    clause = f" WHERE {' AND '.join(where)}" if where else ""
    total = int(ctx.store.query_mind(f"SELECT COUNT(*) FROM {c.ITEMS_TABLE}{clause}", tuple(args))[0][0])
    found = ctx.store.query_mind(
        f"SELECT {','.join(ITEM_COLUMNS)} FROM {c.ITEMS_TABLE}{clause} ORDER BY id DESC LIMIT ?", (*args, SHOWN))
    items = [Item.of(dict(zip(ITEM_COLUMNS, r, strict=True))) for r in found]
    names = names_of(frame, {a for it in items for a in it.about})
    shown = f"{len(items)} sur {total}, les plus récents d'abord" if total > len(items) else f"{total}"
    table = Table(("n°", "sorte", "texte", "concerne", "sensibilité", "importance", "ce qu'il en reste",
                   "confiance", "origine", "statut", "né le"),
                  tuple(_row(it, frame, names, ctx) for it in items),
                  title=f"Ce qu'elle a retenu ({shown})",
                  empty="rien ne correspond" if where else "rien de retenu pour l'instant")
    return [status, table]
