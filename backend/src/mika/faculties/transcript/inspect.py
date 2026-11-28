"""Les vues de Conversations :

- **Le fil des messages** : tous les messages (servis en MCP et par leur ancienne adresse, hors du menu depuis
  l'ADR 0181), les questions sans réponse, les échanges sur la fiche d'une personne, le fil d'un moyen de
  communication sur sa fiche ; chaque message reçu dit la parole qui l'a réglé, ou pourquoi il est resté sans
  réponse ;
- **Par personne** (ADR 0181) : avec qui elle parle — une ligne par personne, tous ses moyens de communication
  réunis, la conversation la plus récente d'abord : par où, le dernier message et qui l'a écrit, combien de messages,
  les questions qui attendent sa réponse ; la ligne mène à leur conversation. Un mot cherché (``q``, là où la
  recherche de la console mène) ne garde que les conversations où il a été dit, chacune avec le dernier message qui
  le contient ;
- **Ses réponses jugées** par son opératrice (ADR 0113) : ce qu'on lui avait écrit, ce qu'elle a répondu, l'avis et
  ce qu'elle aurait dû dire — les exemples concrets de sa voix, du plus récent au plus ancien."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import case, false, func, select

from mika.contracts import identity as identity_c
from mika.contracts import runtime as rt
from mika.contracts import transcript as c
from mika.faculties.transcript.faculty import TRANSCRIPT, TranscriptState
from mika.faculties.transcript.thread import THREAD_COLUMNS, messages_of, strands_of
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    Badge,
    Block,
    Cell,
    Column,
    Disclosure,
    InspectContext,
    Nav,
    NavItem,
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
    Workspace,
    agree,
    paginate,
)
from mika.ports.delivery import TOO_LATE
from mika.ports.errors import describe_error
from mika.ports.paging import fold_text
from mika.vocab import privacy
from mika.vocab.affect import emotion_cell
from mika.vocab.people import fold, is_identifiable, is_internal

# ── Le fil des messages ───────────────────────────────────────────────────

#: Tant de messages par page (curseur « avant ») ; un texte replié au-delà de
#: tant de caractères, et jamais plus que tant envoyés à la console.
PAGE = 50
INSPECT_CHARS = 300
TEXT_CAP = 4000
FORGOTTEN = "(oublié)"
ROLES = (("user", "la personne"), ("assistant", "elle"))


def _clip(text: str | None, limit: int = INSPECT_CHARS) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _internal(r: Mapping[str, Any]) -> bool:
    """Adressé à personne (ou venu de sa propre tuyauterie) : pas un échange."""
    return not r["person"] or is_internal(r["person"])


def _who(frame: Frame, handle: str) -> Cell:
    """La personne derrière un moyen de communication, par son nom, en lien vers sa fiche : sa clé seulement quand
    elle n'a pas de nom (ADR 0042 ; sa clé reste dans le lien)."""
    return _named(frame, handle, keyed=False)


def _who_by(frame: Frame, handle: str) -> Cell:
    """La personne et le moyen de communication par lequel elle a écrit (« Béa (user_2) »), en lien vers sa fiche :
    dans le fil et ses résumés, par où chaque message est venu est l'information même."""
    return _named(frame, handle, keyed=True)


def _named(frame: Frame, handle: str, *, keyed: bool) -> Cell:
    if not handle or is_internal(handle):
        return Text("personne", "muted")
    person = frame.get(identity_c.PERSON(handle))
    name = frame.get(identity_c.IDENTITY(person)).name or frame.get(identity_c.IDENTITY(handle)).name
    shown = (f"{name} ({handle})" if keyed else name) if name else handle
    return Ref.subject("person", person, shown)


def _page(store: Any, clauses: Sequence[Any], before: int | None,
          size: int = PAGE) -> tuple[list[dict[str, Any]], Pager | None]:
    """Une page du fil, du plus récent au plus ancien, et le curseur de la suivante."""
    where = list(clauses)
    if before:
        where.append(c.thread_table().c.id < before)
    found = messages_of(store, *where, limit=size + 1)
    rows = [dict(zip(THREAD_COLUMNS, r, strict=True)) for r in found[:size]]
    more = len(found) > size and rows
    return rows, Pager(older=(("avant", str(rows[-1]["id"])),)) if more else Pager()


def _episodes(ctx: InspectContext, rows: Sequence[Mapping[str, Any]]) -> dict[int, str]:
    """L'épisode de chaque réponse (sa corrélation) — et, par elle, celui de la
    question qu'elle règle."""
    out: dict[int, str] = {}
    for r in rows:
        if r["role"] != "assistant":
            continue
        found = ctx.events((rt.UTTERANCE,), 1, before=int(r["id"]) + 1)
        if found and found[0].seq == r["id"]:
            out[int(r["id"])] = found[0].correlation
            if r["reply_to"] is not None:
                out.setdefault(int(r["reply_to"]), found[0].correlation)
    return out


#: l'étiquette d'un message écrit en mode pro (ADR 0116) : ses réponses s'y lisent en Markdown, comme le chat les rend
#: (ADR 0241)
PRO = "mode pro"
MESSAGE_COLUMNS = (Column("n°", "fit", detail=True), Column("quand", "fit"), Column("qui parle", role="title"), "avec",
                   Column("où", detail=True), Column("texte", role="body"), Column("émotion", detail=True),
                   "réponse", Column("épisode", detail=True), Column("mode", "fit", detail=True))


def _answers(ctx: InspectContext, rows: Sequence[Mapping[str, Any]]) -> dict[int, int]:
    """Pour chaque message reçu de la page, la parole qui l'a réglé (son n°) : celle qui y répond, ou celle qui
    répond au dernier message de sa rafale et l'a lu avec (``Utterance.answers``). Absent : encore en attente, ou
    réglé sans parole (``_silences`` dit pourquoi)."""
    store = ctx.store
    asked = [r for r in rows if r["role"] == "user" and not _internal(r)]
    if store is None or not asked:
        return {}
    ids = [int(r["id"]) for r in asked]
    t = c.thread_table()
    # par numéro : deux paroles qui répondent au même message, la dernière l'emporte (sur les deux moteurs)
    out = {int(q): int(a) for a, q in store.query_mind(
        select(t.c.id, t.c.reply_to).where(t.c.role == "assistant", t.c.reply_to.in_(ids)).order_by(t.c.id))}
    for r in asked:
        q = int(r["id"])
        if q in out:
            continue
        # le premier énoncé vers la même adresse, au même endroit, qui répond à un message d'après : il a peut-être
        # lu celui-ci avec (une rafale reçoit une seule réponse, à son dernier message)
        later = store.query_mind(
            select(t.c.id).where(t.c.person == r["person"], t.c.role == "assistant", t.c.id > q, t.c.reply_to > q,
                                 func.coalesce(t.c.room, "") == (r["room"] or "")).order_by(t.c.id).limit(1))
        if not later:
            continue
        seq = int(later[0][0])
        found = ctx.events((rt.UTTERANCE,), 1, before=seq + 1)
        if found and found[0].seq == seq and q in found[0].data.answers:
            out[q] = seq
    return out


#: une rafale dont le dernier message est sur une autre page : sa fin se cherche parmi tant de messages suivants
BURST_LOOKUP = 5
#: comment se dit une fin qui laisse un message sans réponse (le détail d'une panne suit)
SILENCES = {"abstained": "s'est tue", "failed": "panne", "timeout": "panne : délai dépassé",
            "interrupted": "interrompue par un arrêt", "superseded": "supplantée", "preempted": "a cédé la place",
            "cancelled": "annulée"}
#: une cause tient en tant de caractères dans la colonne « réponse » (sa page la dit en entier)
CAUSE_CHARS = 80


def _ended_leaving(ctx: InspectContext, reply_to: int, q: int) -> Any | None:
    """La dernière fin d'épisode qui répondait à ``reply_to``, si elle laisse le message ``q`` sans réponse."""
    found = ctx.events((rt.EPISODE_ENDED,), 1, where=("reply_to", reply_to))
    return found[0] if found and found[0].data.leaves_unanswered(q) else None


def _silences(ctx: InspectContext, rows: Sequence[Mapping[str, Any]], pending: set[int],
              answers: Mapping[int, int]) -> dict[int, Any]:
    """Pour chaque message reçu de la page réglé sans parole, la fin d'épisode qui l'a laissé sans réponse
    (``EpisodeEnded.leaves_unanswered``) ; ``None`` : il ne lui était pas adressé (dans un salon, elle entend tout
    mais ne répond qu'à ce qui lui parle). Les plus récents d'abord : la fin d'une rafale porte sur son dernier
    message et règle aussi ceux d'avant. Absent : sa fin n'est pas retrouvée."""
    store = ctx.store
    out: dict[int, Any] = {}
    asked = [r for r in rows if r["role"] == "user" and not _internal(r)
             and int(r["id"]) not in pending and int(r["id"]) not in answers]
    for r in sorted(asked, key=lambda r: int(r["id"]), reverse=True):
        q = int(r["id"])
        if q in out:
            continue
        got = ctx.events((rt.PERCEPTION_RECEIVED,), 1, before=q + 1)
        if got and got[0].seq == q and not got[0].data.addressed:
            out[q] = None
            continue
        ended = _ended_leaving(ctx, q, q)
        if ended is None and store is not None:
            # une rafale dont la fin porte sur un message d'après, de la même adresse au même endroit
            t = c.thread_table()
            for (later,) in store.query_mind(
                    select(t.c.id).where(t.c.person == r["person"], t.c.role == "user", t.c.id > q,
                                         func.coalesce(t.c.room, "") == (r["room"] or ""))
                    .order_by(t.c.id).limit(BURST_LOOKUP)):
                ended = _ended_leaving(ctx, int(later), q)
                if ended is not None:
                    break
        if ended is not None:
            for seq in ended.data.unanswered or (q,):
                out.setdefault(int(seq), ended)
    return out


def _cause(outcome: str, detail: str) -> str:
    """Pourquoi un message est resté sans réponse, en quelques mots : un silence (« s'est tue », ou ce qui l'a fait
    taire — « s'est ravisée », « allait redire son dernier message »), « trop tard », une panne et son détail
    (« panne : délai dépassé »)."""
    detail = " ".join((detail or "").split())
    if detail.startswith(TOO_LATE):
        return "trop tard"
    if outcome == "abstained" and detail:
        # un silence que le modèle n'a pas rendu se dit en une phrase sur elle (« elle s'est ravisée »)
        return _clip(detail.removeprefix("elle "), CAUSE_CHARS)
    head = SILENCES.get(outcome, outcome or "fin inconnue")
    return _clip(f"{head} : {describe_error(detail)}", CAUSE_CHARS) if detail else head


def _answer_cell(r: Mapping[str, Any], pending: set[int], answers: Mapping[int, int],
                 silences: Mapping[int, Any]) -> Cell:
    """La colonne « réponse » d'un message reçu : en attente, la parole qui l'a réglé, ou sans réponse — et
    pourquoi, en mots, avec un lien vers l'explication (« Pourquoi n'a-t-elle pas répondu ? »)."""
    if r["role"] != "user" or _internal(r):
        return ""
    q = int(r["id"])
    if q in pending:
        return Badge("en attente", "warn")
    if q in answers:
        return Ref.why(answers[q], f"répondue → n° {answers[q]}")
    if q not in silences:
        return Text("sans réponse", "muted")
    ended = silences[q]
    if ended is None:
        return Text("sans réponse : ne lui était pas adressé", "muted")
    return Ref.why(q, f"sans réponse : {_cause(ended.data.outcome, ended.data.detail)}")


def _messages(frame: Frame, ctx: InspectContext, rows: Sequence[Mapping[str, Any]]) -> tuple[Row, ...]:
    pending = {int(x) for x in frame.get(rt.AWAITING)}
    episodes = _episodes(ctx, rows)
    answers = _answers(ctx, rows)
    silences = _silences(ctx, rows, pending, answers)
    out = []
    for r in rows:
        mine = r["role"] == "assistant"
        corr = episodes.get(int(r["id"]))
        if corr is None and silences.get(int(r["id"])) is not None:
            corr = silences[int(r["id"])].correlation  # l'épisode qui l'a laissé sans réponse
        out.append(Row((
            Ref("event", str(r["id"]), str(r["id"])), When(r["at"]),
            Badge("elle", "info") if mine else Badge("la personne"), _who_by(frame, r["person"]),
            f"salon « {r['room']} »" if r["room"] else "en privé",
            Text((r["text"] or "")[:TEXT_CAP], clamp=INSPECT_CHARS),
            emotion_cell(r["emotion"], r["emotion_intensity"]) if mine and r["emotion"] else "",
            _answer_cell(r, pending, answers, silences),
            Ref("episode", corr, "épisode") if corr else "—",
            Badge(PRO, "info", key="pro") if r["mode"] == "pro" else "",
        ), tone="muted" if _internal(r) else "", href=Ref.why(int(r["id"])) if mine and corr else None,
            detail=(Prose(r["text"] or FORGOTTEN, title="Message", reading=True),)))
    return tuple(out)


def _summaries(store: Any, s: TranscriptState, frame: Frame, handles: Sequence[str] | None) -> Block | None:
    folded = [(p, v) for p, v in sorted(s.summaries.items()) if handles is None or p in handles]  # le rendu pagine
    if not folded:
        return None
    texts = store.content([ref for _p, (_upto, ref) in folded if ref])
    rows = tuple((_who_by(frame, p), Ref("event", str(upto), str(upto)),
                  Text(_clip(texts[ref], TEXT_CAP), clamp=INSPECT_CHARS) if texts.get(ref) else FORGOTTEN)
                 for p, (upto, ref) in folded)
    return Disclosure(f"Débuts de fil repliés en résumé ({len(rows)})", (
        Table(("avec", "replié jusqu'au message", "résumé"), rows, title="Fils repliés", empty="aucun fil replié"),))


def _no_store() -> list[Block]:
    return [Note("Le magasin n'est pas disponible : le fil ne peut pas être relu.", tone="muted")]


HANDLE = Param("handle", "Personne ou identifiant", placeholder="Alice…")
QUERY = Param("q", "texte", placeholder="un mot…")
ROLE = Param("role", "qui parle", kind="select", choices=ROLES)


# hors de la console (ADR 0181) : Conversations s'ouvre sur les personnes, chaque conversation est sur sa fiche ; la
# console en MCP la sert encore par son nom, et son ancienne adresse mène à Par personne
@TRANSCRIPT.inspect("messages", title="Messages", section="fil", order=10, params=[HANDLE, QUERY, ROLE], hidden=True,
                    description="Tout ce qui a été dit, du plus récent au plus ancien.")
def _all_messages(s: TranscriptState, frame: Frame, ctx: InspectContext) -> list[Block]:
    store = ctx.store
    if store is None:
        return _no_store()
    handle, q, role = str(ctx.value("handle") or ""), str(ctx.value("q") or ""), str(ctx.value("role") or "")
    t = c.thread_table()
    clauses: list[Any] = []
    matched = None
    if handle:
        known_handles = sorted({str(r[0]) for r in store.query_mind(select(t.c.person).distinct())} |
                               set(s.summaries))
        exact = [h for h in known_handles if h == handle]
        # dans le nom et dans la clé (« Béa (user_2) ») : « user_7 » trouve encore user_7
        matched = exact or [h for h in known_handles if handle.casefold() in _who_by(frame, h).text.casefold()]
        clauses.append(t.c.person.in_(matched) if matched else false())
    if q:
        # le texte replié à l'écriture, comparé en binaire : casse et accents ignorés, pareil sur les deux moteurs
        clauses.append(func.instr(t.c.folded, fold_text(q)) > 0)
    if role:
        clauses.append(t.c.role == role)
    before = ctx.int_param("avant", 0) or None
    rows, pager = _page(store, clauses, before)
    known = bool(matched) or handle in s.last_from or handle in s.last_to or handle in s.summaries
    if handle and not rows and not known and not before:
        return [Note(f"Aucun message avec « {handle} ».", tone="muted")]
    awaiting = frame.get(rt.AWAITING)
    scope = f" avec « {handle} »" if handle else ""
    found = f" contenant « {q} »" if q else ""
    blocks: list[Block] = [
        Table(MESSAGE_COLUMNS, _messages(frame, ctx, rows), title=f"Messages{scope}{found}", pager=pager,
              layout="feed", link_label="Pourquoi cette réponse ?",
              empty="aucun message ne correspond" if handle or q or role else "aucun message"),
    ]
    if awaiting and not (handle or q or role):
        blocks.insert(0, Stats((Stat("Questions sans réponse", len(awaiting), tone="warn",
                                     href=Ref.view("transcript", "questions", "questions")),)))
    folded = _summaries(store, s, frame, matched) if not (q or role) else None
    if folded is not None:
        blocks.append(folded)
    return blocks


#: les questions (les plus récentes) dont le badge lit qui les a posées
AWAITING_READ = 500


def _awaiting(s: TranscriptState, frame: Frame, ports: Mapping[str, Any] | None = None) -> tuple[int, str]:
    """Le badge des questions sans réponse, et de qui elles viennent (C1-10) : « de Béa et Léa », « d'une personne
    inconnue » — l'accueil le dit après le nombre, plutôt qu'un « à regarder » ; lu dans le fil."""
    waiting = sorted((int(x) for x in frame.get(rt.AWAITING)), reverse=True)
    store = (ports or {}).get("store")
    if not waiting or store is None:
        return len(waiting), ""
    t = c.thread_table()
    rows = store.query_mind(select(t.c.id, t.c.person).where(t.c.id.in_(waiting[:AWAITING_READ])))
    asked = dict((int(r[0]), str(r[1] or "")) for r in rows)
    return len(waiting), _from_whom(frame, [asked[x] for x in waiting if x in asked])


def _from_whom(frame: Frame, handles: Sequence[str]) -> str:
    """« de Béa, Léa et une personne inconnue » : les personnes derrière ces adresses, la plus récente d'abord, trois
    nommées au plus ; celles qu'elle ne connaît pas, comptées."""
    known: list[str] = []
    unknown: set[str] = set()
    for handle in dict.fromkeys(h for h in handles if h and not is_internal(h)):
        person = frame.get(identity_c.PERSON(handle)) or handle
        name = frame.get(identity_c.IDENTITY(person)).name or frame.get(identity_c.IDENTITY(handle)).name
        if not name:
            unknown.add(person)
        elif name not in known:
            known.append(name)
    more = len(known) - 3
    words = known[:3] + ([f"{more} {agree(more, 'autre', 'autres')}"] if more > 0 else [])
    if unknown:
        words.append("une personne inconnue" if len(unknown) == 1 else f"{len(unknown)} personnes inconnues")
    if not words:
        return ""
    said = words[0] if len(words) == 1 else ", ".join(words[:-1]) + " et " + words[-1]
    return ("d'" if said[:1].lower() in "aeiouyhàâéèêëîïôûü" else "de ") + said


@TRANSCRIPT.inspect("questions", title="Questions sans réponse", section="fil", order=20, badge=_awaiting,
                    description="Ce qu'on lui a demandé et à quoi elle n'a pas encore répondu.")
def _questions(s: TranscriptState, frame: Frame, ctx: InspectContext) -> list[Block]:
    store = ctx.store
    if store is None:
        return _no_store()
    waiting = sorted((int(x) for x in frame.get(rt.AWAITING)), reverse=True)
    page, pager = paginate(waiting, ctx.pager(size=PAGE))
    t = c.thread_table()
    found = {int(r[0]): r for r in store.query_mind(
        select(t.c.id, t.c.at, t.c.person, t.c.text).where(t.c.id.in_(list(page))))} if page else {}
    rows = []
    for seq in page:
        r = found.get(seq)
        link = Ref("event", str(seq), str(seq))
        if r is None:
            rows.append(Row((link, "—", Text("—", "muted"), Text(FORGOTTEN, "muted")), href=link))
            continue
        rows.append(Row((link, When(r[1]), _who(frame, r[2]), Text(_clip(r[3], TEXT_CAP), clamp=INSPECT_CHARS)),
                        href=link))
    return [Table((Column("n°", "fit", detail=True), Column("reçue", "fit"), Column("de", role="title"), Column("texte", role="body")), tuple(rows), pager=pager,
                  layout="feed", link_label="Voir le message source",
                  title="Questions sans réponse", empty="aucune question en attente",
                  caption="Une question reste ici tant qu'aucune réponse ne l'a réglée ; « reçue » dit depuis quand "
                          "elle attend.")]


def _stats(store: Any, handles: Sequence[str]) -> Stats:
    t = c.thread_table()
    total, received = store.query_mind(
        select(func.count(), func.coalesce(func.sum(case((t.c.role == "user", 1), else_=0)), 0))
        .where(t.c.person.in_(list(handles))))[0]
    return Stats((Stat("messages", int(total)), Stat("reçus", int(received)),
                  Stat("envoyés", int(total) - int(received))))


# ── Une conversation : le fil avec elle, ou un de ses fils de travail (ADR 0164, 0241) ──

#: le paramètre qui choisit un fil de travail ; absent, le fil avec elle (salons compris)
STRAND = "travail"
#: le nom du fil avec elle, dans la navigation d'Échanges et de Fil ; le titre de ses fils de travail
ORDINARY, STRANDS_TITLE = "Leur conversation", "Fils du mode pro"
#: un fil de travail sans titre se nomme par le début de son premier message, en tant de lettres — comme le chat
#: (``strandLabel``, ``frontend/Web/src/ui/strands.ts``)
STRAND_LABEL = 48
ARCHIVED = "archivé"


def strand_label(item: Mapping[str, Any]) -> str:
    """Le nom d'un fil de travail : son titre, sinon le début de son premier message, sinon « Nouveau fil »."""
    title = " ".join(str(item.get("title") or "").split())
    if title:
        return title
    opener = " ".join(str(item.get("opener") or "").split())
    if not opener:
        return "Nouveau fil"
    return opener if len(opener) <= STRAND_LABEL else opener[:STRAND_LABEL - 1].rstrip() + "…"


def _strands(store: Any, handles: Sequence[str]) -> list[dict[str, Any]]:
    """Les fils de travail de ces moyens de communication (``strands_of``, un même fil réuni), le plus récemment actif
    d'abord, ceux qu'on a archivés à la fin."""
    merged: dict[str, dict[str, Any]] = {}
    for handle in handles:
        for item in strands_of(store, handle):
            got = merged.setdefault(item["id"], {**item, "count": 0})
            got["count"] += item["count"]
            got["last_at"] = max(got["last_at"], item["last_at"])
            for name in ("title", "description", "opener"):
                got[name] = got[name] or item[name]
    return sorted(merged.values(), key=lambda x: (x["archived"], -x["last_at"], x["id"]))


def _conversation(s: TranscriptState, frame: Frame, ctx: InspectContext, *, kind: str, key: str, tab: str,
                  handles: Sequence[str], title: str, empty: str) -> list[Block]:
    """Ce qu'ils se sont dit, une conversation à la fois : le fil avec elle (tout ce qui n'est pas d'un fil de
    travail), ou le fil de travail que nomme ``travail``, chacun avec son contexte. Dès qu'il y a un fil de travail,
    une navigation à côté les liste, chacun avec son nombre de messages ; les chiffres en tête comptent tout."""
    store = ctx.store
    t = c.thread_table()
    chosen = ctx.param(STRAND)
    strands = _strands(store, handles)
    rows, pager = _page(store, [t.c.person.in_(list(handles)), t.c.strand == chosen if chosen else t.c.strand.is_(None)],
                        ctx.int_param("avant", 0) or None)
    if kind == "handle" and not rows and not strands and not ctx.int_param("avant", 0) \
            and not (key in s.last_from or key in s.last_to):
        return [Note(f"Aucun message avec « {key} ».", tone="muted")]
    stats = _stats(store, handles)
    shown: list[Block] = []
    current = next((x for x in strands if x["id"] == chosen), None) if chosen else None
    if current is not None and current["description"]:
        shown.append(Note(current["description"], title=strand_label(current)))
    shown.append(Table(MESSAGE_COLUMNS, _messages(frame, ctx, rows), pager=pager, title=title, layout="feed",
                       link_label="Pourquoi cette réponse ?", empty="aucun message dans ce fil" if chosen else empty))
    folded = None if chosen else _summaries(store, s, frame, handles)  # les résumés sont ceux du fil avec elle
    if folded is not None:
        shown.append(folded)
    if not strands:
        return [stats, *shown]
    ordinary = store.query_mind(select(func.count()).select_from(t)
                                .where(t.c.person.in_(list(handles)), t.c.strand.is_(None)))[0][0]
    side = (Nav((NavItem(ORDINARY, Ref.subject(kind, key, ORDINARY, tab=tab), count=int(ordinary), active=not chosen),)),
            Nav(tuple(NavItem(strand_label(x) + (f" · {ARCHIVED}" if x["archived"] else ""),
                              Ref("subject", f"{kind}/{key}", strand_label(x), (("onglet", tab), (STRAND, x["id"]))),
                              count=x["count"] or None, active=x["id"] == chosen) for x in strands),
                title=STRANDS_TITLE))
    return [stats, Workspace(side, tuple(shown))]


@TRANSCRIPT.inspect("echanges", title="Échanges", subject="person", order=40,
                    description="Ce qu'ils se sont dit, tous ses moyens de communication confondus, du plus récent au "
                                "plus ancien : le fil avec elle, puis chacun de ses fils de travail du mode pro.")
def _exchanges(s: TranscriptState, frame: Frame, ctx: InspectContext) -> list[Block]:
    person = ctx.subject
    if not person:
        return [Note("Ouvre la fiche d'une personne : Personnes, puis la personne.", tone="muted")]
    if person.startswith("name:"):
        return [Note("Connue seulement de nom : elle ne lui a jamais écrit.", tone="muted")]
    if ctx.store is None:
        return _no_store()
    return _conversation(s, frame, ctx, kind="person", key=person, tab="echanges",
                         handles=sorted({person, *frame.get(identity_c.HANDLES(person))}), title="Échanges",
                         empty="aucun échange pour l'instant")


@TRANSCRIPT.inspect("fil", title="Fil", subject="handle", order=50,
                    description="Les messages de ce moyen de communication seulement : le fil avec elle, puis chacun "
                                "de ses fils de travail du mode pro.")
def _handle_thread(s: TranscriptState, frame: Frame, ctx: InspectContext) -> list[Block]:
    handle = ctx.subject or ctx.param("handle")
    if not handle:
        return [Note("Ouvre la fiche d'un moyen de communication : Identités et moyens de communication, puis le "
                     "moyen de communication.", tone="muted")]
    if ctx.store is None:
        return _no_store()
    return _conversation(s, frame, ctx, kind="handle", key=handle, tab="fil", handles=[handle], title="Messages",
                         empty="aucun message")


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
    shown = {int(r[0]): dict(zip(THREAD_COLUMNS, r, strict=True))
             for r in messages_of(store, t.c.id.in_([p.shown for _k, p in page]))} if page else {}
    rows = tuple(_person_row(frame, k, p, shown.get(p.shown)) for k, p in page)
    empty = (f"« {text} » n'a été dit dans aucune conversation" if text
             else f"personne ne s'appelle « {asked} »" if wanted else "aucune conversation pour l'instant")
    return [Table(PEOPLE_COLUMNS, rows, title=f"Ses conversations où « {text} » a été dit" if text
                  else "Ses conversations", pager=pager, link_label="Leur conversation", empty=empty)]


# ── Ses réponses jugées ───────────────────────────────────────────────────

#: l'avis toujours posé, « toutes » par défaut : un bouton à choix au bout de la barre d'onglets (ADR 0176) ; une
#: ancienne adresse ``?avis=`` (vide) retombe sur le défaut
ALL_VERDICTS = "toutes"
VERDICT = Param("avis", "avis", kind="select", default=ALL_VERDICTS,
                choices=((ALL_VERDICTS, "toutes"), (c.VERDICT_KO, "pas adaptées"), (c.VERDICT_OK, "adaptées")))

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
    if wanted and wanted != ALL_VERDICTS:
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
