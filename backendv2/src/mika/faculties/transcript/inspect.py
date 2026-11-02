"""Deux vues de Conversations, à côté du fil des messages :

- **Par personne** (ADR 0181) : avec qui elle parle — une ligne par personne, tous ses moyens de communication
  réunis, la conversation la plus récente d'abord : par où, le dernier message et qui l'a écrit, combien de messages,
  les questions qui attendent sa réponse ; la ligne mène à leur conversation. Un mot cherché (``q``, là où la
  recherche de la console mène) ne garde que les conversations où il a été dit, chacune avec le dernier message qui
  le contient ;
- **Ses réponses jugées** par son opératrice (ADR 0113) : ce qu'on lui avait écrit, ce qu'elle a répondu, l'avis et
  ce qu'elle aurait dû dire — les exemples concrets de sa voix, du plus récent au plus ancien."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select

from mika.contracts import identity as identity_c
from mika.contracts import runtime as rt
from mika.contracts import transcript as c
from mika.faculties.transcript import (
    _COLUMNS,
    FORGOTTEN,
    HANDLE,
    INSPECT_CHARS,
    QUERY,
    TEXT_CAP,
    TRANSCRIPT,
    TranscriptState,
    _clip,
    _messages_of,
    _no_store,
    _page,
    _who,
)
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    Badge,
    Block,
    Cell,
    Column,
    InspectContext,
    Param,
    Prose,
    Ref,
    Row,
    Table,
    Text,
    When,
    paginate,
)
from mika.ports.paging import fold_text
from mika.vocab import privacy
from mika.vocab.people import fold, is_identifiable, is_internal

# ── Par personne ──────────────────────────────────────────────────────────

#: le canal d'un message, dit en mots (un autre garde son nom)
CHANNEL_WORDS = {privacy.WEB: "web", privacy.MOBILE: "téléphone", privacy.EXTERNAL: "compte extérieur",
                 "email": "courrier"}
#: le dernier message d'une conversation : au plus tant de lettres
LAST_CHARS = 160
#: tant de personnes par page (une foule se pagine : jamais toute la liste d'un coup)
PEOPLE_PAGE = 25

PEOPLE_COLUMNS = (Column("avec", role="title"), Column("par", "fit"), Column("dernier message", role="body"),
                  Column("de", "fit", detail=True), Column("le dernier", "fit"), Column("messages", "num"),
                  Column("questions", "fit"))


@dataclass(slots=True)
class _With:
    """Une personne avec qui elle parle : ses moyens de communication qui ont écrit ou reçu, leurs messages."""

    handles: list[str] = field(default_factory=list)
    channels: set[str] = field(default_factory=set)
    count: int = 0
    last: int = 0
    questions: int = 0
    #: le message montré sur sa ligne : le dernier, ou le dernier qui contient le mot cherché
    shown: int = 0


def _name(frame: Frame, person: str, handles: list[str]) -> str:
    """Son nom tel qu'elle le connaît ; à défaut, son premier moyen de communication."""
    for key in (person, *handles):
        name = frame.get(identity_c.IDENTITY(key)).name
        if name:
            return name
    return handles[0]


def _gathered(store: Any, frame: Frame) -> dict[str, _With]:
    """Les messages comptés par moyen de communication, puis réunis par la personne qui est derrière (ses
    adresses internes, celles de sa propre tuyauterie, n'en sont pas)."""
    t = c.thread_table()
    channels: dict[str, set[str]] = {}
    for handle, channel in store.query_mind(select(t.c.person, t.c.channel).distinct()):
        name = privacy.normalize_channel(channel)
        channels.setdefault(str(handle), set()).add(CHANNEL_WORDS.get(name, name or "—"))
    waiting = sorted(int(x) for x in frame.get(rt.AWAITING))
    asked = Counter(str(h) for h, in store.query_mind(select(t.c.person).where(t.c.id.in_(waiting)))) \
        if waiting else Counter()
    people: dict[str, _With] = {}
    for handle, count, last in store.query_mind(select(t.c.person, func.count(), func.max(t.c.id))
                                                .group_by(t.c.person)):
        handle = str(handle or "")
        if not handle or is_internal(handle):
            continue
        p = people.setdefault(frame.get(identity_c.PERSON(handle)) or handle, _With())
        p.handles.append(handle)
        p.channels |= channels.get(handle, set())
        p.count += int(count)
        p.last = p.shown = max(p.last, int(last))
        p.questions += asked[handle]
    return people


def _said(store: Any, people: dict[str, _With], text: str) -> dict[str, _With]:
    """Les conversations où ``text`` a été dit (casse et accents ignorés, comme le fil le replie), chacune montrant
    le dernier message qui le contient."""
    t = c.thread_table()
    hits = {str(h): int(i) for h, i in store.query_mind(
        select(t.c.person, func.max(t.c.id)).where(func.instr(t.c.folded, fold_text(text)) > 0).group_by(t.c.person))}
    found = {k: p for k, p in people.items() if any(h in hits for h in p.handles)}
    for p in found.values():
        p.shown = max(hits.get(h, 0) for h in p.handles)
    return found


def _person_row(frame: Frame, person: str, p: _With, last: dict[str, Any] | None) -> Row:
    name = _name(frame, person, p.handles)
    mine = bool(last) and last["role"] == "assistant"
    # une inconnue de passage n'a pas de fiche de personne : son moyen de communication, et son fil
    who = Ref.subject("person", person, name) if is_identifiable(person) else Ref.subject("handle", p.handles[0], name)
    to = Ref.subject("person", person, "Leur conversation", tab="echanges") if is_identifiable(person) \
        else Ref.subject("handle", p.handles[0], "Leur conversation", tab="fil")
    cells: tuple[Cell, ...] = (
        who, " · ".join(sorted(p.channels)) or "—",
        Text(_clip(last["text"], LAST_CHARS) or FORGOTTEN) if last else Text("—", "muted"),
        Badge("elle", "info") if mine else Badge("la personne"),
        When(last["at"]) if last else "—", p.count,
        Badge(f"{p.questions} sans réponse", "warn") if p.questions else "—",
    )
    return Row(cells, tone="warn" if p.questions else "", href=to)


# les filtres sont ceux de l'ancien fil de tous les messages (``handle``, ``q``) : ses liens d'avant y mènent
# (ADR 0181)
@TRANSCRIPT.inspect("conversations", title="Par personne", section="fil", order=5, params=[HANDLE, QUERY],
                    description="Avec qui elle parle : une ligne par personne, la conversation la plus récente "
                                "d'abord.")
def _conversations(s: TranscriptState, frame: Frame, ctx: InspectContext) -> list[Block]:
    store = ctx.store
    if store is None:
        return _no_store()
    people = _gathered(store, frame)
    asked = str(ctx.value("handle") or "").strip()
    wanted = fold(asked)
    if wanted:
        # un moyen de communication nommé tel quel (« user_1 ») : sa personne seule, pas « user_10 »
        people = {k: p for k, p in people.items() if asked in p.handles} or {
            k: p for k, p in people.items()
            if wanted in fold(_name(frame, k, p.handles)) or any(wanted in fold(h) for h in p.handles)}
    text = str(ctx.value("q") or "").strip()
    if text:
        people = _said(store, people, text)
    page, pager = paginate(sorted(people.items(), key=lambda kv: -kv[1].shown), ctx.pager(size=PEOPLE_PAGE))
    t = c.thread_table()
    shown = {int(r[0]): dict(zip(_COLUMNS, r, strict=True))
             for r in _messages_of(store, t.c.id.in_([p.shown for _k, p in page]))} if page else {}
    rows = tuple(_person_row(frame, k, p, shown.get(p.shown)) for k, p in page)
    empty = (f"« {text} » n'a été dit dans aucune conversation" if text
             else f"personne ne s'appelle « {asked} »" if wanted else "aucune conversation pour l'instant")
    return [Table(PEOPLE_COLUMNS, rows, title=f"Ses conversations où « {text} » a été dit" if text
                  else "Ses conversations", pager=pager, link_label="Leur conversation", empty=empty)]


# ── Ses réponses jugées ───────────────────────────────────────────────────

VERDICT = Param("avis", "avis", kind="select", choices=(("", "tous"), (c.VERDICT_KO, "pas adaptées"),
                                                        (c.VERDICT_OK, "adaptées")))

COLUMNS = (Column("quand", "fit"), Column("avis", "fit"), "avec", Column("on lui avait écrit", role="body"),
           Column("sa réponse", role="body"), Column("ce qu'elle aurait dû dire", role="body"),
           Column("n°", "fit", detail=True))


def _heard(store: Any, rows: list[dict[str, Any]]) -> dict[int, str]:
    """Pour chaque réponse, le message auquel elle répondait (son texte)."""
    t = c.thread_table()
    asked = sorted({int(r["reply_to"]) for r in rows if r["reply_to"] is not None})
    if not asked:
        return {}
    return {int(i): str(text or "") for i, text in store.query_mind(select(t.c.id, t.c.text).where(t.c.id.in_(asked)))}


@TRANSCRIPT.inspect("jugees", title="Ses réponses jugées", section="fil", order=15, params=[VERDICT],
                    description="Ses réponses que tu as jugées depuis le chat, avec ce qu'elle aurait dû dire.")
def _judged(s: TranscriptState, frame: Frame, ctx: InspectContext) -> list[Block]:
    store = ctx.store
    if store is None:
        return _no_store()
    t = c.thread_table()
    wanted = str(ctx.value("avis") or "")
    clauses: list[Any] = [t.c.role == "assistant", t.c.verdict.is_not(None)]
    if wanted:
        clauses.append(t.c.verdict == wanted)
    rows, pager = _page(store, clauses, ctx.int_param("avant", 0) or None)
    heard = _heard(store, rows)
    out = []
    for r in rows:
        ok = r["verdict"] == c.VERDICT_OK
        asked = heard.get(int(r["reply_to"])) if r["reply_to"] is not None else None
        out.append(Row((
            When(r["at"]), Badge("adaptée", "ok") if ok else Badge("pas adaptée", "warn"), _who(frame, r["person"]),
            Text((asked or "—")[:TEXT_CAP], clamp=INSPECT_CHARS),
            Text((r["text"] or FORGOTTEN)[:TEXT_CAP], clamp=INSPECT_CHARS),
            Text(r["verdict_note"] or "—", clamp=INSPECT_CHARS),
            Ref("event", str(r["id"]), str(r["id"])),
        ), href=Ref.why(int(r["id"])), detail=(Prose(r["text"] or FORGOTTEN, title="Sa réponse", reading=True),)))
    return [Table(COLUMNS, tuple(out), title="Ses réponses jugées", pager=pager, layout="feed",
                  link_label="Pourquoi cette réponse ?",
                  empty="aucune réponse jugée : dans le chat, 👍 ou 👎 sous une de ses réponses")]
