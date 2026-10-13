"""La console des pièces reçues (ADR 0106) : leur liste (Mémoire › Pièces reçues), la place que chacun occupe, un
onglet « Pièces reçues » sur la fiche d'une personne, et la fiche d'une pièce — ce qu'elle y a lu, les messages qui
l'ont portée, ce qu'elle sait qui y est relié —, d'où un opérateur peut la télécharger. L'opérateur voit tout : les
règles de ce qu'elle peut rouvrir devant qui sont celles de ses outils, pas de la console."""

from __future__ import annotations

from typing import Any

from mika.contracts import attachments as c
from mika.contracts import identity as identity_c
from mika.faculties.attachments.faculty import (
    ATTACHMENTS,
    MIB,
    MISSING,
    PORT,
    AttachmentsState,
    FileRow,
    by_prefix,
    carriers,
    count,
    linked_knowledge,
    links,
    params_of,
    recent,
    row,
    usage,
)
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    Badge,
    Block,
    Cell,
    Column,
    Download,
    Fields,
    Found,
    Head,
    InspectContext,
    Meter,
    Note,
    Param,
    Prose,
    Ref,
    Row,
    Table,
    Text,
    When,
)
from mika.ports.shares import MAX_SHARE_BYTES, valid_id
from mika.vocab.people import is_internal
from mika.vocab.privacy import Sensitivity

PAGE = 25
KIND = "piece"


def size_words(n: int) -> str:
    """Une taille, pour la console (« 12,5 Ko »)."""
    if n < 1024:
        return f"{n} o"
    if n < MIB:
        return f"{n / 1024:.1f} Ko".replace(".", ",")
    if n < 1024 * MIB:
        return f"{n / MIB:.1f} Mo".replace(".", ",")
    return f"{n / (1024 * MIB):.2f} Go".replace(".", ",")
KIND_LABELS = {c.IMAGE: "photo", c.AUDIO: "vocal", c.FILE: "document"}
SENSITIVITY_LABELS = {int(Sensitivity.ANODYNE): "anodine", int(Sensitivity.PERSONAL): "personnelle",
                      int(Sensitivity.CONFIDENCE): "confidence"}
ITEM_LABELS = {"souvenir": "souvenir", "belief": "croyance", "event": "moment", "promise": "promesse"}
BY_LABELS = {c.BY_REREAD: "la relecture", c.BY_HER: "elle"}
REASON_LABELS = {c.RETENTION: "trop ancienne", c.BUDGET: "place dépassée", MISSING: "octets absents"}


def _who(frame: Frame, handle: str) -> Cell:
    if not handle or is_internal(handle):
        return Text("personne", "muted")
    person = frame.get(identity_c.PERSON(handle))
    name = frame.get(identity_c.IDENTITY(person)).name or frame.get(identity_c.IDENTITY(handle)).name
    return Ref.subject("person", person, f"{name} ({handle})" if name else handle)


def _state(r: FileRow) -> Badge:
    if r.gone:
        return Badge(f"retirée ({REASON_LABELS.get(r.reason or '', r.reason or '?')})", "muted")
    if not r.readable:
        return Badge("gardée, pas lue", "warn")
    return Badge("gardée", "ok")


def _download_link(r: FileRow) -> Cell:
    if r.gone:
        return Text("—", "muted")
    return Ref("local", f"/inspecteur/telecharger/{KIND}/{r.id}", "télécharger", (("fichier", r.name),))


def _rows(frame: Frame, store: Any, found: list[FileRow], with_who: bool = True) -> tuple[Row, ...]:
    tied = links(store, [r.id for r in found])
    out = []
    for r in found:
        cells: list[Cell] = [When(r.at), Ref.subject(KIND, r.id, r.name or "(sans nom)")]
        if with_who:
            cells.append(_who(frame, r.handle))
        cells += [KIND_LABELS.get(r.kind, r.kind), Text(size_words(r.size), "num"),
                  Text(r.seen or "—", "muted" if not r.seen else "text", clamp=140),
                  Text(str(len(tied.get(r.id, ()))), "num"), _state(r), _download_link(r)]
        out.append(Row(tuple(cells), href=Ref.subject(KIND, r.id, "")))
    return tuple(out)


def _columns(with_who: bool = True) -> tuple[Any, ...]:
    head: list[Any] = [Column("reçue", "fit"), "nom"]
    if with_who:
        head.append("de")
    return (*head, Column("sorte", "fit"), Column("taille", "num"), "ce qu'elle y a lu", Column("liens", "num"),
            Column("état", "fit"), Column("télécharger", "fit"))


_KINDS = (("", "toutes"), (c.IMAGE, "photos"), (c.FILE, "documents"), (c.AUDIO, "vocaux"))


@ATTACHMENTS.inspect("recues", title="Pièces reçues", section="memoire", order=25,
                     params=(Param("q", "chercher (nom, ce qu'elle y a lu)"),
                             Param("sorte", "sorte", kind="select", choices=_KINDS)),
                     description="Ce qu'on lui a envoyé dans les conversations — photos, documents, vocaux — : gardé, "
                                 "lu de près, relié à ce qu'elle sait. Ses outils la laissent les retrouver et les "
                                 "rouvrir ; devant qui, c'est la règle de sa mémoire.")
def _pieces(s: AttachmentsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    store = ctx.store
    if store is None:
        return [Note("Le magasin n'est pas disponible : les pièces ne se relisent pas.", tone="muted")]
    words = [w for w in ctx.param("q").split() if w][:6]
    kind = str(ctx.value("sorte") or "")
    total = count(store, kind=kind, words=words)
    pager = ctx.pager(size=PAGE, total=total)
    found = recent(store, kind=kind, words=words, limit=pager.offset + pager.size)[pager.offset:]
    blocks: list[Block] = []
    if s.pending:
        blocks.append(Note(f"{len(s.pending)} pièce(s) reçue(s) en cours de lecture (elles apparaissent ici une fois "
                           "lues).", tone="info"))
    blocks.append(Table(_columns(), _rows(frame, store, found), title="Pièces reçues", pager=pager,
                        empty="aucune pièce reçue" if not words and not kind else "aucune pièce ne correspond",
                        caption="« liens » : les souvenirs, croyances et moments qui s'appuient sur la pièce — en "
                                "plus de leurs messages sources. « gardée, pas lue » : ses octets sont là, mais "
                                "rien n'a pu en être lu (un format illisible, pas de modèle qui voit)."))
    return blocks


def _people_usage(frame: Frame, store: Any) -> list[tuple[str, int, int]]:
    """(personne, pièces gardées, octets), toutes ses adresses réunies, de la plus chargée à la moins chargée."""
    per: dict[str, list[int]] = {}
    for handle, (n, size) in usage(store).items():
        person = frame.get(identity_c.PERSON(handle)) or handle
        got = per.setdefault(person, [0, 0])
        got[0] += n
        got[1] += size
    return sorted(((p, n, size) for p, (n, size) in per.items()), key=lambda x: (-x[2], x[0]))


@ATTACHMENTS.inspect("place", title="Place des pièces", section="memoire", order=26,
                     description="Ce que les pièces de chacun occupent (toutes ses adresses réunies), face à sa place : "
                                 "au-delà, les plus anciennes sont retirées — leurs octets s'effacent, ce qu'elle en "
                                 "avait lu reste.")
def _place(s: AttachmentsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    store = ctx.store
    if store is None:
        return [Note("Le magasin n'est pas disponible.", tone="muted")]
    budget = params_of(frame).per_person_mb * MIB
    people = _people_usage(frame, store)
    pager = ctx.pager(size=PAGE, total=len(people))
    rows_ = []
    for person, n, size in people[pager.offset:pager.offset + pager.size]:
        ratio = size / budget if budget else 0.0
        tone = "danger" if ratio >= 1 else "warn" if ratio >= 0.8 else ""
        rows_.append(Row((_who(frame, person), Text(str(n), "num"), Text(size_words(size), "num"),
                          Meter(ratio, f"{round(ratio * 100)} %", tone=tone)),
                         href=Ref.subject("person", person, "", "pieces")))
    total = sum(size for _p, _n, size in people)
    return [Fields((("place par personne", size_words(budget)), ("en tout", size_words(total)),
                    ("personnes", str(len(people)))), title="Place"),
            Table(("personne", Column("pièces", "num"), Column("occupé", "num"), "de sa place"), tuple(rows_),
                  title="Par personne", pager=pager, empty="aucune pièce gardée")]


@ATTACHMENTS.inspect("pieces", title="Pièces reçues", subject="person", order=62,
                     description="Ce que cette personne lui a envoyé dans les conversations, et la place que ça occupe.")
def _person_tab(s: AttachmentsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    person = ctx.subject
    if not person:
        return [Note("Ouvre la fiche d'une personne : Personnes, puis la personne.", tone="muted")]
    store = ctx.store
    if store is None:
        return [Note("Le magasin n'est pas disponible.", tone="muted")]
    handles = sorted({person, *frame.get(identity_c.HANDLES(person))})
    total = count(store, handles=handles)
    pager = ctx.pager(size=PAGE, total=total)
    found = recent(store, handles=handles, limit=pager.offset + pager.size)[pager.offset:]
    used = sum(size for h, (_n, size) in usage(store).items() if h in handles)
    budget = params_of(frame).per_person_mb * MIB
    ratio = used / budget if budget else 0.0
    return [Fields((("occupé", size_words(used)), ("sa place", size_words(budget)),
                    ("", Meter(ratio, f"{round(ratio * 100)} %", tone="warn" if ratio >= 0.8 else ""))),
                   title="Sa place"),
            Table(_columns(with_who=False), _rows(frame, store, found, with_who=False), title="Pièces reçues",
                  pager=pager, empty="elle ne lui a encore rien envoyé")]


@ATTACHMENTS.subject(KIND, label="Pièce reçue", plural="Pièces reçues", icon="⧉")
def _head(s: AttachmentsState, frame: Frame, ctx: InspectContext, key: str) -> Head | None:
    if not valid_id(key):
        return None
    r = row(ctx.store, key) if ctx.store is not None else None
    if r is None:
        return None
    facts: list[tuple[str, Cell]] = [
        ("de", _who(frame, r.handle)), ("reçue", When(r.at)), ("taille", size_words(r.size)),
        ("sorte", Text(r.mime, "mono")), ("sensibilité", SENSITIVITY_LABELS.get(r.sensitivity, str(r.sensitivity))),
        ("où", Text(f"salon {r.room}", "mono") if r.room else "en privé")]
    if r.gone:
        facts.append(("retirée", When(r.expired_at or 0)))
    else:
        facts.append(("télécharger", _download_link(r)))
    person = frame.get(identity_c.PERSON(r.handle)) if r.handle else ""
    back = Ref.subject("person", person, "Ses pièces", "pieces") if person else None
    return Head(r.id, r.name or "(sans nom)", subtitle="Une pièce qu'on lui a envoyée", badges=(_state(r),),
                facts=tuple(facts), back=back)


@ATTACHMENTS.inspect("lu", title="Ce qu'elle y a lu", subject=KIND, order=10,
                     description="Ce qu'elle a lu de la pièce en la regardant de près : la description d'une photo et "
                                 "son texte visible, le texte d'un document, la transcription d'un vocal.")
def _seen_tab(s: AttachmentsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    r = row(ctx.store, ctx.subject) if ctx.store is not None and valid_id(ctx.subject) else None
    if r is None:
        return [Note("Cette pièce n'est pas (ou plus) connue.", tone="muted")]
    if not r.seen:
        return [Note("Rien n'a pu en être lu : un format illisible, ou pas de modèle qui voit (Réglages › "
                     "Fournisseurs, « décrire une image »).", tone="muted")]
    return [Prose(r.seen, title="Ce qu'elle y a lu", reading=True)]


@ATTACHMENTS.inspect("liens", title="Liens", subject=KIND, order=20,
                     description="Ce qu'elle sait qui s'appuie sur cette pièce — en plus de ses messages sources —, et "
                                 "les messages qui l'ont portée.")
def _links_tab(s: AttachmentsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    store = ctx.store
    r = row(store, ctx.subject) if store is not None and valid_id(ctx.subject) else None
    if r is None:
        return [Note("Cette pièce n'est pas (ou plus) connue.", tone="muted")]
    tied = links(store, [r.id]).get(r.id, [])
    known = linked_knowledge(store, [i for i, _by in tied])
    items = tuple(Row((ITEM_LABELS.get(known[i].kind, known[i].kind) if i in known else "—",
                       Text(known[i].text, clamp=300) if i in known else Text("(plus active, ou oubliée)", "muted"),
                       BY_LABELS.get(by, by), Ref("event", str(i), f"n° {i}"))) for i, by in tied)
    carried = tuple(Row((When(at), Ref("event", str(seq), f"n° {seq}"), Text(f"salon {room}", "mono") if room
                         else "en privé")) for seq, at, room in carriers(store, r.id))
    return [Table(("ce que c'est", "ce qu'elle sait", Column("relié par", "fit"), Column("élément", "fit")), items,
                  title="Ce qu'elle sait qui va avec", empty="rien n'y est encore relié"),
            Table((Column("quand", "fit"), Column("message", "fit"), "où"), carried, title="Les messages qui l'ont "
                  "portée", empty="aucun message connu")]


@ATTACHMENTS.search(KIND)
def _search(s: AttachmentsState, frame: Frame, ctx: InspectContext, text: str, limit: int) -> list[Found]:
    store = ctx.store
    wanted = text.strip().lower().lstrip("#")
    found = by_prefix(store, wanted, limit) if len(wanted) >= 6 else []
    if not found:
        found = recent(store, words=[w for w in text.split() if w][:6], limit=limit)
    return [Found(r.id, r.name or "(sans nom)", f"{KIND_LABELS.get(r.kind, r.kind)}, {size_words(r.size)}")
            for r in found[:limit]]


@ATTACHMENTS.download(KIND)
async def _download(s: AttachmentsState, frame: Frame, ctx: InspectContext, key: str, name: str) -> Download | Note:
    """La pièce telle qu'elle est arrivée (l'opérateur seulement : la console)."""
    r = row(ctx.store, key) if ctx.store is not None and valid_id(key) else None
    port = ctx.ports.get(PORT)
    if r is None or port is None or r.gone:
        return Note("Cette pièce n'est plus disponible.", tone="warn")
    data = await port.read(r.id, MAX_SHARE_BYTES)
    if data is None:
        return Note("Cette pièce n'est plus disponible.", tone="warn")
    return Download(r.name or "piece", data)
