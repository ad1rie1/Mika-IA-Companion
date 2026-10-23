"""La nuit de la mémoire.

- **Réfléchir** : une pensée restée forte, digérée pendant la nuit, devient un
  souvenir (« Après y avoir repensé cette nuit : … ») — une fois. Ce qu'on lui
  a demandé de taire, ou ce qui laisse deviner un secret qu'elle garde déjà,
  reste un secret : la nuit ne le blanchit pas.
- **Trier** : après trois heures de sommeil, une fois par nuit, un souvenir du
  jour presque identique à un souvenir plus ancien **des mêmes personnes,
  confié et entendu par les mêmes**, s'y fond (sans modèle) : un seul
  souvenir, qui garde la plus haute des deux importances et des deux
  sensibilités (la projection).
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, select

from mika.contracts import attention as attention_c
from mika.contracts import body as body_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as c
from mika.contracts import runtime as rt
from mika.contracts import self_ as self_c
from mika.faculties.memory import extraction as x
from mika.faculties.memory.consolidation import kept_secrets
from mika.faculties.memory.faculty import MEMORY, MemoryState, Reflection, params
from mika.faculties.memory.projections import ITEM_COLUMNS
from mika.faculties.memory.salience import Item
from mika.faculties.memory.tables import items
from mika.kernel.clock import instant, local_date_of_night
from mika.kernel.events import Content
from mika.kernel.faculty import CatchUp
from mika.kernel.frame import Frame
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import Sensitivity
from mika.vocab.words import same_words, stems


@MEMORY.process("memory.reflect", wake_on=[attention_c.DIGESTED, c.REMEMBERED], lane="background",
                catch_up=CatchUp.ONCE, max_quantum_s=3600)
class Reflect:
    def __init__(self) -> None:
        self.skipped: set[int] = set()

    def next_due(self, state: MemoryState, frame: Frame, last_run: int | None) -> int | None:
        return frame.now if any(r.thought not in self.skipped for r in state.reflections) else None

    async def run(self, ctx: Any) -> None:
        state: MemoryState = ctx.state
        frame: Frame = ctx.frame
        store = ctx.ports.get("store")
        if store is None:
            return
        pending = [r for r in state.reflections if r.thought not in self.skipped]
        texts = store.content([r.text_ref for r in pending])
        drafts = []
        for r in pending:
            text = texts.get(r.text_ref)
            if not text:
                self.skipped.add(r.thought)  # effacée (oubli) : rien à repenser
                continue
            mark = f"réflexion:{r.thought}"
            constraints, internal = _disclosure(frame, store, r.thought)
            secret = self._secret(frame, store, r, text) or any(rule.secret for rule in constraints)
            # L'auteur est Mika ; les restrictions des sources restent des restrictions, pas des auteurs.
            subjects = tuple(sorted({*r.about, *(who for rule in constraints
                                                for who in (*rule.about, *rule.told_by))}))
            drafts.append(c.REMEMBERED.draft(
                text=Content.of(phrase("memory.night.reflection", text=text), level=r.sensitivity), about=subjects,
                sensitivity=r.sensitivity, importance=0.5, emotion=r.emotion, call_id=mark, dedupe_key=mark,
                sources=(r.thought,), told_by=(), heard_by=(), secret=secret,
                constraints=constraints, internal_only=internal or (secret and not any(rule.secret for rule in constraints))))
        if drafts:
            await ctx.emit(*drafts)

    @staticmethod
    def _secret(frame: Frame, store: Any, r: Reflection, text: str) -> bool:
        """Comme à la consolidation : la pensée cite qu'on lui a demandé de le taire, ou laisse deviner un secret
        qu'elle garde déjà sur ces personnes (une confidence du soir cite le message même que la consolidation a
        rangé en secret — repensée la nuit, elle ne doit pas devenir un souvenir dicible aux amies)."""
        if x.says_secret([text]):
            return True
        names = {st for person in r.about for st in stems(frame.get(identity_c.IDENTITY(person)).name or "")}
        names |= stems(self_c.name_of(frame.get(self_c.PERSONA)))
        return x.echoes(text, kept_secrets(store, r.about), names)


def _disclosure(frame: Frame, store: Any, thought: int) -> tuple[tuple[c.Disclosure, ...], bool]:
    """Remonte les preuves, jamais le contenu voisin ; une origine inconnue reste intérieure."""
    pending, seen, rules = [thought], set(), []
    unknown = False
    while pending and len(seen) < 64:
        source = pending.pop()
        if source in seen:
            continue
        seen.add(source)
        t = items()
        rows = store.query_mind(select(*(t.c[k] for k in ITEM_COLUMNS)).where(t.c.id == source))
        if rows:
            item = Item.of(dict(zip(ITEM_COLUMNS, rows[0], strict=True)))
            if item.constraints:
                rules.extend(rule.model_copy(update={"sensitivity": max(rule.sensitivity, item.sensitivity)})
                             for rule in item.constraints)
            else:
                rules.append(c.Disclosure(about=item.about, told_by=item.told_by, heard_by=item.heard_by,
                                          sensitivity=item.sensitivity, secret=item.secret))
            unknown |= item.internal_only
            continue
        events = store.get_events([source])
        if not events:
            unknown = True
            continue
        event = events[0]
        data = json.loads(event.data)
        if event.type == attention_c.THOUGHT_BORN.name:
            if data.get("origin") == attention_c.LIE:
                # « J'ai menti à Bob », repensé la nuit, reste à Bob : ailleurs il laisserait deviner ce qu'il couvrait
                about = tuple(data.get("about") or ())
                rules.append(c.Disclosure(about=about, heard_by=about, sensitivity=int(data.get("sensitivity") or 2),
                                          secret=True))
            refs = list(data.get("sources") or ())
            if data.get("source") is not None:
                refs.append(data["source"])
            if not refs and data.get("origin") not in (attention_c.MISSING, attention_c.ALONE):
                unknown = True
            pending.extend(refs)
        elif event.type == rt.PERCEPTION_RECEIVED.name:
            handle = data["handle"]
            person = frame.get(identity_c.PERSON(handle)) or handle
            ref = (data.get("text") or {}).get("ref")
            text = store.content([ref]).get(ref) if ref else None
            if text is None:
                unknown = True
                continue
            rules.append(c.Disclosure(about=(person,), told_by=(person,), heard_by=(person,),
                                      sensitivity=int(Sensitivity.ANODYNE if data.get("public") else Sensitivity.PERSONAL),
                                      secret=x.says_secret([text])))
        elif event.type == rt.UTTERANCE.name:
            floor = int(data.get("floor") or 0)
            if data.get("unkept") or floor:
                # ce qu'elle a lu pour l'écrire (ADR 0128) : une confidence de la personne pour qui elle l'a lu
                target = str(data.get("target") or "")
                person = str(frame.get(identity_c.PERSON(target)) or target) if target else ""
                who = (person,) if person else ()
                strong = bool(data.get("unkept")) or floor >= int(Sensitivity.CONFIDENCE)
                rules.append(c.Disclosure(about=who, told_by=who, heard_by=who,
                                          sensitivity=max(floor, int(Sensitivity.CONFIDENCE) if strong else 0),
                                          secret=strong))
            refs = [int(p[7:]) for p in data.get("provenance", ()) if p.startswith("memory:") and p[7:].isdigit()]
            refs += list(data.get("answers") or ())
            if data.get("reply_to"):
                refs.append(data["reply_to"])
            pending.extend(refs)
            unknown |= not bool(refs)
        else:
            unknown = True
    return tuple(dict.fromkeys(rules)), unknown or bool(pending)


@MEMORY.process("memory.night", wake_on=[*body_c.ALL], lane="night", catch_up=CatchUp.ONCE, max_quantum_s=3600)
class Sort:
    def _night(self, state: MemoryState, frame: Frame) -> str | None:
        since = frame.get(body_c.ASLEEP_SINCE)
        if not since:
            return None
        night = local_date_of_night(since, frame.env.tz_of(frame.root), 5).isoformat()
        return None if night == state.sorted_night else night

    def next_due(self, state: MemoryState, frame: Frame, last_run: int | None) -> int | None:
        if self._night(state, frame) is None:
            return None
        p = params(frame.env.params_of("memory", frame.root))
        return max(frame.now, frame.get(body_c.ASLEEP_SINCE) + p.night_after_sleep_us)

    async def run(self, ctx: Any) -> None:
        frame: Frame = ctx.frame
        night = self._night(ctx.state, frame)
        if night is None:
            return
        p = params(frame.env.params_of("memory", frame.root))
        store, vectors = ctx.ports.get("store"), ctx.ports.get("vectors")
        merges: list[tuple[int, int]] = []
        if store is not None and vectors is not None:
            merges = await self._merges(store, vectors, frame, night, p)
        drafts = [c.NIGHT_SORTED.draft(night=night, merges=tuple(merges), dedupe_key=f"tri:{night}")]
        pairs = joinable_pairs(store, p) if store is not None else ()
        if pairs:
            drafts.append(c.JOINED.draft(night=night, pairs=pairs, dedupe_key=f"jointure:{night}"))
        await ctx.emit(*drafts)

    async def _merges(self, store: Any, vectors: Any, frame: Frame, night: str, p: Any) -> list[tuple[int, int]]:
        tz = frame.env.tz_of(frame.root)
        day = date.fromisoformat(night)
        start = instant(datetime.combine(day, time(5), tzinfo=tz))
        end = instant(datetime.combine(day + timedelta(days=1), time(5), tzinfo=tz))
        t = items()
        rows = store.query_mind(select(t.c.id, t.c.text, t.c.about, t.c.told_by, t.c.heard_by)
                                .where(t.c.kind == c.SOUVENIR, t.c.status == "active", t.c.born_at >= start,
                                       t.c.born_at < end).order_by(t.c.id.desc()))
        merged: set[int] = set()
        out: list[tuple[int, int]] = []
        for item_id, text, *people in rows:
            if len(out) >= p.night_max_merges or item_id in merged:
                continue
            for hit, sim in await vectors.search(text, 4, kinds={c.SOUVENIR}, document=True):
                if hit == item_id or hit in merged or sim < p.night_merge_similarity or hit > item_id:
                    continue
                alive = store.query_mind(select(t.c.status, t.c.about, t.c.told_by, t.c.heard_by, t.c.text)
                                         .where(t.c.id == hit))
                # la fusion unit les personnes, confidents et témoins : « Bob m'a dit que son père est hospitalisé »
                # fondu dans la confidence d'Alice la rendrait « ses propres mots » pour Bob, et l'oubli de Bob
                # l'effacerait — seuls deux souvenirs des mêmes personnes, confiés et entendus par les mêmes, se fondent
                if (alive and alive[0][0] == "active" and _same_people(alive[0][1:4], people)
                        and same_words(text, alive[0][4])):
                    out.append((hit, item_id))
                    merged |= {hit, item_id}
                    break
        return out


def joinable_pairs(store: Any, p: Any) -> tuple[tuple[int, int], ...]:
    """Les croyances notées deux fois parce que deux personnes les ont dites (d'avant les témoignages, ADR 0080) :
    les mêmes mots, sur les mêmes personnes, de même nature — un avis ou une hypothèse, du même porteur — et pas un
    de ses mensonges. La plus ancienne garde ; chaque autre devient un de ses témoignages.

    La base ne groupe que par l'empreinte (une clé) ; les listes des personnes et la nature, des textes longs que
    MariaDB ne grouperait que par leur début (``max_sort_length``), se comparent ici en entier."""
    t = items()
    active = (t.c.kind == c.BELIEF, t.c.status == "active")
    twice = select(t.c.fingerprint).where(*active).group_by(t.c.fingerprint).having(func.count() > 1)
    found = [(int(i), text, about, nature, int(int(own) > 0), holder, origin, mark) for i, text, about, nature, own,
             holder, origin, mark in store.query_mind(
                 select(t.c.id, t.c.text, t.c.about, t.c.knowledge_kind, t.c.about_self, t.c.holder, t.c.origin,
                        t.c.fingerprint).where(*active, t.c.fingerprint.in_(twice)).order_by(t.c.id))]
    groups = Counter((mark, about, nature, mine) for _i, _t, about, nature, mine, _h, _o, mark in found)
    rows = [r[:7] for r in found if groups[(r[7], r[2], r[3], r[4])] > 1]
    kept: list[tuple[int, str, str, str, int, str | None]] = []
    out: list[tuple[int, int]] = []
    for item, text, about, nature, mine, holder, origin in rows:
        if len(out) >= p.night_max_joins:
            break
        if origin == c.LIED:
            continue
        keep = next((k for k, t, a, n, m, h in kept if a == about and n == nature and m == mine
                     and (nature == "claim" or (h or None) == (holder or None)) and same_words(t, text)), None)
        if keep is None:
            kept.append((int(item), str(text), str(about), str(nature), int(mine), holder))
        else:
            out.append((keep, int(item)))
    return tuple(out)


def _people(raw: Any) -> frozenset[str]:
    try:
        got = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return frozenset()
    return frozenset(str(k) for k in got) if isinstance(got, list) else frozenset()


def _same_people(a: Sequence[Any], b: Sequence[Any]) -> bool:
    """Mêmes personnes concernées, mêmes confidents, mêmes témoins (``about``, ``told_by``, ``heard_by``)."""
    return all(_people(x) == _people(y) for x, y in zip(a, b, strict=True))
