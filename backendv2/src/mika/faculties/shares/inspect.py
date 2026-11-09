"""La console des fichiers envoyés : un onglet « Fichiers » sur la fiche d'une personne, leur vue d'ensemble (Mémoire ›
Fichiers envoyés : ce qu'elle a envoyé à tout le monde), et la fiche d'un fichier, d'où un opérateur peut le
télécharger ou le retirer (ADR 0205).

Retirer (``shares.retirer``, confirmé, audité comme toute action) fait ce que fait la rétention, pour un seul
fichier : ``shares.expired``, sa raison ``operator`` ; ses octets s'effacent après le commit, sa ligne reste,
« retiré par un opérateur ». L'action est posée sur la fiche du fichier (``subject``) ; les onglets dessinés la posent
aussi sur sa ligne, le fichier pour objet."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from mika.contracts import identity as identity_c
from mika.contracts import projects as projects_c
from mika.contracts import shares as c
from mika.faculties.shares.faculty import (
    PORT,
    SHARES,
    FileRow,
    SharesState,
    count,
    holder,
    of_people,
    recent,
    row,
)
from mika.faculties.shares.tools import size_words
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    Badge,
    Block,
    Cell,
    Column,
    Download,
    Head,
    InspectContext,
    Note,
    Ref,
    Row,
    Table,
    Text,
    When,
)
from mika.kernel.operate import ActionContext, Done, Refused
from mika.ports.shares import MAX_SHARE_BYTES, valid_id
from mika.vocab.people import is_internal

PAGE = 25
KIND = "partage"
#: « Retirer » un fichier (ADR 0205) : sur sa fiche, et sur sa ligne dans les onglets dessinés
REMOVE = "shares.retirer"
#: ce que dit la ligne d'un fichier qu'un opérateur a retiré
BY_OPERATOR = "retiré par un opérateur"
KIND_LABELS = {c.FILE: "document", c.IMAGE: "image"}
GONE = "Ce fichier n'est plus là : déjà retiré, ou sa personne oubliée."
CAPTION = ("« pas parti » : un fichier préparé dont le message n'est jamais parti (une réponse supplantée, ou tue) — "
           "la rétention le retirera. « retiré » : trop vieux, ou la place de la personne dépassée ; « retiré par un "
           "opérateur » : depuis la console. Ses octets sont effacés, sa ligne reste.")


def removal_question(name: str = "") -> str:
    """La question qui confirme « Retirer » (le nom du fichier, quand la ligne le connaît)."""
    what = f"« {name} »" if name else "ce fichier"
    return (f"Retirer {what} ? Ses octets sont effacés : il ne se télécharge plus. Sa ligne reste, « retiré par un "
            "opérateur ».")


def _state(r: FileRow) -> Badge:
    if r.gone:
        return Badge(BY_OPERATOR if r.reason == c.OPERATOR else "retiré", "muted")
    if r.sent:
        return Badge("envoyé", "ok")
    return Badge("pas parti", "warn")


def _origin(r: FileRow, store: Any, frame: Frame) -> Cell:
    if r.origin == c.DRAWN:
        return "dessiné"
    if r.origin != c.PROJECT or r.project is None:
        return "écrit"
    # son titre par le contrat des projets (un projet archivé n'y est plus : son numéro suffit)
    v = next((x for x in frame.get(projects_c.LIVE) if x.id == r.project), None)
    title = store.content([v.title_ref]).get(v.title_ref, "") if v is not None and v.title_ref else ""
    return Ref.subject("project", str(r.project), f"projet « {title} »" if title else f"projet n° {r.project}")


def _who(frame: Frame, handle: str) -> Cell:
    if not handle or is_internal(handle):
        return Text("personne", "muted")
    person = frame.get(identity_c.PERSON(handle))
    name = frame.get(identity_c.IDENTITY(person)).name or frame.get(identity_c.IDENTITY(handle)).name
    return Ref.subject("person", person, f"{name} ({handle})" if name else handle)


def _download_link(r: FileRow) -> Ref:
    return Ref.download(KIND, r.id, "télécharger", r.name)


def _message(r: FileRow) -> Cell:
    return Ref.why(r.message, f"n° {r.message}") if r.message else Text("—", "muted")


@SHARES.inspect("fichiers", title="Fichiers", subject="person", order=60,
                description="Les fichiers qu'elle lui a envoyés : quand, lesquels, avec quel message, et s'ils sont "
                            "encore disponibles.")
def _files_tab(s: SharesState, frame: Frame, ctx: InspectContext) -> list[Block]:
    person = ctx.subject
    if not person:
        return [Note("Ouvre la fiche d'une personne : Personnes, puis la personne.", tone="muted")]
    store = ctx.store
    if store is None:
        return [Note("Le magasin n'est pas disponible : les fichiers ne se relisent pas.", tone="muted")]
    handles = sorted({person, *frame.get(identity_c.HANDLES(person))})
    # sa propre page : l'onglet se lit aussi à côté d'un autre (les pièces reçues, sur la fiche)
    pager = ctx.pager("page_envoyes", size=PAGE, total=count(store, handles))
    found = of_people(store, handles, pager.offset + pager.size)[pager.offset:]
    rows = tuple(Row((
        When(r.at), Ref.subject(KIND, r.id, r.name or "(sans nom)"), Text(size_words(r.size)),
        _origin(r, store, frame), _message(r), _state(r), _download_link(r) if not r.gone else Text("—", "muted"),
    ), href=Ref.subject(KIND, r.id, "")) for r in found)
    return [Table((Column("quand", "fit"), "nom", Column("taille", "num"), "origine", Column("message", "fit"),
                   Column("état", "fit"), Column("télécharger", "fit")), rows, title="Fichiers envoyés",
                  pager=pager, empty="elle ne lui a encore envoyé aucun fichier", caption=CAPTION)]


@SHARES.inspect("envoyes", title="Fichiers envoyés", section="memoire", order=26,
                description="Ce qu'elle a envoyé, à tout le monde : quand, à qui, avec quel message, et s'ils sont "
                            "encore disponibles. Un fichier se retire à l'unité, sur sa ligne ou sur sa fiche : ses "
                            "octets s'effacent, sa ligne reste.")
def _sent(s: SharesState, frame: Frame, ctx: InspectContext) -> list[Block]:
    store = ctx.store
    if store is None:
        return [Note("Le magasin n'est pas disponible : les fichiers ne se relisent pas.", tone="muted")]
    pager = ctx.pager(size=PAGE, total=count(store))
    found = recent(store, pager.offset + pager.size)[pager.offset:]
    rows = tuple(Row((
        When(r.at), Ref.subject(KIND, r.id, r.name or "(sans nom)"), _who(frame, r.person),
        KIND_LABELS.get(r.kind, r.kind), Text(size_words(r.size), "num"), _origin(r, store, frame), _message(r),
        _state(r), _download_link(r) if not r.gone else Text("—", "muted"),
    ), href=Ref.subject(KIND, r.id, "")) for r in found)
    return [Table((Column("quand", "fit"), "nom", "pour", Column("sorte", "fit"), Column("taille", "num"), "origine",
                   Column("message", "fit"), Column("état", "fit"), Column("télécharger", "fit")), rows,
                  title="Fichiers envoyés", pager=pager, empty="elle n'a encore envoyé aucun fichier",
                  caption=CAPTION)]


@SHARES.subject(KIND, label="Fichier envoyé", plural="Fichiers envoyés")
def _head(s: SharesState, frame: Frame, ctx: InspectContext, key: str) -> Head | None:
    if not valid_id(key):
        return None
    r = row(ctx.store, key) if ctx.store is not None else None
    if r is None:
        return None
    facts: list[tuple[str, Any]] = [
        ("pour", _who(frame, r.person)), ("préparé", When(r.at)), ("taille", size_words(r.size)),
        ("sorte", Text(r.mime, "mono")), ("origine", _origin(r, ctx.store, frame)), ("message", _message(r))]
    if r.path:
        facts.append(("dans l'atelier", Text(r.path, "mono")))
    if r.gone:
        facts.append(("retiré", When(r.expired_at or 0)))
    else:
        facts.append(("télécharger", _download_link(r)))
    person = frame.get(identity_c.PERSON(r.person)) if r.person else ""
    back = Ref.subject("person", person, "Ses fichiers", "fichiers") if person else None
    return Head(r.id, r.name or "(sans nom)", subtitle="Un fichier qu'elle a envoyé", badges=(_state(r),),
                facts=tuple(facts), back=back)


@SHARES.download(KIND)
async def _download(s: SharesState, frame: Frame, ctx: InspectContext, key: str, name: str) -> Download | Note:
    """Le fichier tel qu'il est parti (l'opérateur seulement : la console)."""
    r = row(ctx.store, key) if ctx.store is not None and valid_id(key) else None
    port = ctx.ports.get(PORT)
    if r is None or port is None or r.gone:
        return Note("Ce fichier n'est plus disponible.", tone="warn")
    data = await port.read(r.id, MAX_SHARE_BYTES)
    if data is None:
        return Note("Ce fichier n'est plus disponible.", tone="warn")
    return Download(r.name or "fichier", data)


# ── Retirer un fichier (ADR 0205) ─────────────────────────────────────────


class NoArgs(BaseModel):
    """Rien à remplir : la fiche (ou la ligne) dit quel fichier."""


def _removable(s: SharesState, frame: Frame, key: str) -> bool:
    """Un fichier dont les octets sont encore gardés."""
    return valid_id(key) and holder(s, key) is not None


@SHARES.action("retirer", title="Retirer un fichier envoyé", args=NoArgs, emits=[c.EXPIRED], subject=KIND,
               available=_removable, danger=True, order=90, confirm=removal_question(),
               description="Ses octets sont effacés : il ne se télécharge plus, ni ici ni par la personne. Sa ligne "
                           "reste, « retiré par un opérateur ».")
def _remove(s: SharesState, frame: Frame, args: NoArgs, ctx: ActionContext) -> Done:
    target = holder(s, ctx.subject) if valid_id(ctx.subject) else None
    r = row(ctx.store, ctx.subject) if target is not None and ctx.store is not None else None
    if target is None or r is None or r.gone:
        raise Refused(GONE)
    # le même retrait que la rétention, à l'unité : la tranche et la ligne suivent, l'effet efface les octets
    draft = c.EXPIRED.draft(files=(r.id,), target=target, reason=c.OPERATOR, dedupe_key=f"partage-retire:{r.id}")
    return Done(drafts=(draft,), message=f"« {r.name or 'fichier'} » retiré : ses octets sont effacés.")
