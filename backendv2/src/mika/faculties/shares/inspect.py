"""La console des fichiers envoyés : un onglet « Fichiers » sur la fiche d'une personne, et la fiche d'un fichier
(d'où un opérateur peut le télécharger)."""

from __future__ import annotations

from typing import Any

from mika.contracts import identity as identity_c
from mika.contracts import projects as projects_c
from mika.contracts import shares as c
from mika.faculties.shares.faculty import PORT, SHARES, FileRow, SharesState, of_people, row
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
from mika.ports.shares import MAX_SHARE_BYTES, valid_id
from mika.vocab.people import is_internal

PAGE = 25
KIND = "partage"


def _state(r: FileRow) -> Badge:
    if r.gone:
        return Badge("retiré", "muted")
    if r.sent:
        return Badge("envoyé", "ok")
    return Badge("pas parti", "warn")


def _origin(r: FileRow, store: Any, frame: Frame) -> Cell:
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
    return Ref("local", f"/inspecteur/telecharger/{KIND}/{r.id}", "télécharger", (("fichier", r.name),))


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
    marks = ",".join("?" * len(handles))
    total = int(store.query_mind(f"SELECT COUNT(*) FROM {c.TABLE} WHERE person IN ({marks})", tuple(handles))[0][0])
    pager = ctx.pager(size=PAGE, total=total)
    found = of_people(store, handles, pager.offset + pager.size)[pager.offset:]
    rows = tuple(Row((
        When(r.at), Ref.subject(KIND, r.id, r.name or "(sans nom)"), Text(size_words(r.size)),
        _origin(r, store, frame), _message(r), _state(r), _download_link(r) if not r.gone else Text("—", "muted"),
    ), href=Ref.subject(KIND, r.id, "")) for r in found)
    return [Table((Column("quand", "fit"), "nom", Column("taille", "num"), "origine", Column("message", "fit"),
                   Column("état", "fit"), Column("télécharger", "fit")), rows, title="Fichiers envoyés",
                  pager=pager, empty="elle ne lui a encore envoyé aucun fichier",
                  caption="« pas parti » : un fichier préparé dont le message n'est jamais parti (une réponse "
                          "supplantée, ou tue) — la rétention le retirera. « retiré » : trop vieux, ou la place de "
                          "la personne dépassée ; ses octets sont effacés.")]


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
