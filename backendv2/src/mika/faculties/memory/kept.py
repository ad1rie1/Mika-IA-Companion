"""Ce que le code garde d'une relecture : les règles de ce qu'elle retient.

``kept_from`` fait de ce que le modèle a tiré d'une conversation ce qui s'ajoute au journal, étape par étape
(``_drafts``), chaque étape lisant le même contexte (``KeepContext``). De chaque élément on sait qui il concerne,
**qui l'a confié** (les auteurs des messages d'où il vient) et **qui l'a entendu** (les personnes de la
conversation) ; ce qu'on a demandé de taire est un **secret**. Les mêmes mots, avec les mêmes personnes et
permissions, **renforcent** le souvenir existant (son **jumeau**, ``testimonies.py``). Deux informateurs gardent
deux témoignages distincts ; une correction **remplace** la croyance désignée ou la **conteste**, selon ce que vaut
sa source (ADR 0081). Une réplique recopiée n'est pas un souvenir (la sienne jamais ; celle de la personne, citée en
disant qui parle), une banalité ne se garde pas, et comment la personne l'appelle se retient même quand le modèle
l'oublie (ADR 0055). Une situation que la personne dit finie (« on a fini le déménagement ») prend fin.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select

from mika.contracts import identity as identity_c
from mika.contracts import memory as c
from mika.contracts import self_ as self_c
from mika.contracts import transcript as transcript_c
from mika.faculties.memory import cues, timespan
from mika.faculties.memory import extraction as x
from mika.faculties.memory import likelihood as lk
from mika.faculties.memory import tables as tb
from mika.faculties.memory.archive import for_people
from mika.faculties.memory.conversation import Conversation, Line, pieces_of
from mika.faculties.memory.faculty import MemoryParams, MemoryState, day_of, occurrence
from mika.faculties.memory.knowledge import CONTEST, SUPERSEDE, Testimony, judge
from mika.faculties.memory.life import kept_too_early, reminders_of, resolution, same_day, same_task
from mika.faculties.memory.projections import fingerprint
from mika.faculties.memory.retelling import veiled_refusal
from mika.faculties.memory.shown import Forecast, Shown
from mika.faculties.memory.speakers import People
from mika.faculties.memory.tables import batches, handle_key, keys_of
from mika.faculties.memory.testimonies import _former_twin, _head_of, target_of, testimonies_of, twin_of
from mika.kernel.clock import DAY, MINUTE, instant
from mika.kernel.events import Content, Draft
from mika.kernel.frame import Frame
from mika.ports.sql import json_has
from mika.vocab.affect import Emotion, dominant, facets, facets_valence
from mika.vocab.people import fold
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import Sensitivity
from mika.vocab.words import banal, same_words, stems

log = logging.getLogger(__name__)


def kept_secrets(store: Any, persons: Sequence[str]) -> list[str]:
    """Les secrets qu'elle garde déjà sur ces personnes : ce qui les concerne, ou ce qu'elles lui ont confié."""
    out: list[str] = []
    t, ab = tb.items(), tb.about()
    for person in persons:
        out += [str(text) for (text,) in store.query_mind(
            select(t.c.text).where(t.c.secret == 1, t.c.status == "active",
                                   or_(t.c.id.in_(select(ab.c.item).where(ab.c.person == handle_key(person))),
                                       json_has(t.c.told_by, person)))
            .order_by(t.c.id.desc()).limit(50))]
    return out


async def kept_from(ex: x.Extraction, frame: Frame, state: MemoryState, store: Any, conv: Conversation,
                    people: People, shown: Shown, vectors: Any, p: MemoryParams, call_id: str) -> list[Draft[Any]]:
    """Ce que le code garde d'une relecture, jugé (``_drafts``), et les situations qu'elle dit finies parmi celles
    qu'on lui a montrées."""
    ids = {i for i, _w, _t in (*shown.moments, *shown.ended, *shown.passed)}
    # un moment passé se désigne aussi : reporté après coup (« finalement c'est lundi »), ou constaté
    designable = {i: ev for i, ev in {**shown.upcoming, **shown.gone, **shown.past}.items() if i in ids}
    drafts = await _drafts(ex, frame, state, store, conv, people, shown.known, shown.promises, vectors, p, call_id,
                           moments=designable, passed={i: ev for i, ev in shown.past.items() if i in ids},
                           foreseen={i: f for i, f in shown.foreseen.items() if i in ids})
    return drafts + _ended(ex, shown.situations, call_id)


#: d'où vient un élément (``KeepContext.provenance``) : ses messages cités, qui les a écrits (qui l'a confié) et les
#: textes des autres
Provenance = Callable[[Sequence[int]], tuple[tuple[int, ...], tuple[str, ...], list[str]]]
#: s'il est secret (``KeepContext.secret_of``) : ce qu'en dit le modèle, les mots cités, la sensibilité, son texte
SecretOf = Callable[[bool, list[str], int, str], bool]


@dataclass(frozen=True, slots=True)
class KeepContext:
    """Ce que la relecture d'une conversation sait une fois pour toutes, et les jugements que partagent les étapes de
    ce qu'elle en garde (``_drafts``) : d'où vient un élément, s'il vient de sa bouche, qui il concerne, ce qui est
    secret, ce qui est déjà retenu dans ce lot. Construit une fois par ``of``, qui complète ``secrets`` avant toute
    étape ; ``seen`` et ``ours`` se remplissent au fil des étapes, dans leur ordre."""

    ex: x.Extraction
    frame: Frame
    store: Any
    conv: Conversation
    people: People
    #: ses messages, par numéro
    lines: dict[int, Line]
    #: qui y parle (les auteurs des messages)
    speaking: tuple[str, ...]
    #: qui l'a entendu : les personnes de la conversation
    heard: tuple[str, ...]
    tz: ZoneInfo
    #: les « secrets » posés hors de la demande de silence, gardés en confidence (ADR 0092)
    lowered: list[str]
    #: son nom
    her: str
    #: les radicaux de leurs noms et du sien : l'écho d'un secret ne tient pas à un prénom
    names: set[str]
    #: ce qui laisse deviner un secret est secret aussi : les secrets de ce lot, et ceux qu'elle garde déjà
    secrets: list[str]
    #: le même élément deux fois dans un lot n'en fait qu'un (``fresh``)
    seen: set[tuple[str, str]]
    #: leurs noms et le sien, tels qu'on les dit (une banalité, un moment redit)
    said_names: list[str]
    #: le nom de chaque personne qui parle
    name_of: dict[str, str]
    #: ses répliques à elle
    mine: list[Line]
    #: « salut Mikachu » : comment la personne l'appelle, et dans quels messages
    nicks: dict[str, list[int]]
    #: ce qui n'appartient qu'à elles deux, retenu dans ce lot
    ours: list[str]

    @classmethod
    def of(cls, ex: x.Extraction, frame: Frame, store: Any, conv: Conversation, people: People) -> KeepContext:
        """Le contexte de la relecture d'une conversation. Une demande de silence couvre ce qu'elle vise, pas toute la
        conversation (ADR 0092) : ``ex`` en est corrigé d'abord. Puis les secrets : ceux qu'elle garde déjà sur ces
        personnes, et le texte de chaque souvenir, croyance ou moment que le modèle dit secret ou dont les mots cités
        demandent le silence — avant toute étape, pour qu'un élément noté plus tôt les voie aussi."""
        lowered = cues.scoped_secrets(ex, conv.lines)
        if lowered:
            log.info("relecture : %d « secret(s) » hors de la demande de silence, gardé(s) en confidence", len(lowered))
        her = self_c.name_of(frame.get(self_c.PERSONA))
        k = cls(ex=ex, frame=frame, store=store, conv=conv, people=people,
                lines={ln.seq: ln for ln in conv.lines},
                speaking=tuple(sorted({ln.person for ln in conv.lines if ln.person})),
                heard=conv.persons, tz=frame.env.tz_of(frame.root), lowered=lowered, her=her,
                names={st for sp in conv.speakers for st in stems(sp.name)} | stems(her),
                secrets=kept_secrets(store, conv.persons), seen=set(),
                said_names=[*(sp.name for sp in conv.speakers), her],
                name_of={sp.person: sp.name for sp in conv.speakers},
                mine=[ln for ln in conv.lines if ln.person is None],
                nicks=_heard_nicknames(conv, her), ours=[])
        for item in (*ex.souvenirs, *ex.croyances, *ex.evenements):
            cited = k.provenance(item.messages)[2]
            sens = x.sensitivity(item.sensibilite, has_person=True)
            if k.asked_silence(item.secret, cited, sens):
                k.secrets.append(item.texte)
        return k

    def provenance(self, cited: Sequence[int]) -> tuple[tuple[int, ...], tuple[str, ...], list[str]]:
        """Les messages d'où vient un élément, qui les a écrits (qui l'a
        confié) et leurs textes. Sans citation : toute la conversation, et
        tous ceux qui y ont parlé l'ont confié (dans le doute, on ferme).
        Une conversation reçue ailleurs (ADR 0120) : la personne qui l'a reçue
        la lui montre, elle l'a confiée aussi — on lui redit ce qu'on lui a écrit."""
        lines, conv = self.lines, self.conv
        seqs = sorted({s for s in cited if s in lines})
        if not seqs:
            told = self.speaking if len(self.speaking) == 1 else ()
            return conv.seqs, tuple(sorted({*told, conv.relayed})) if conv.relayed else told, []
        persons = {lines[s].person for s in seqs if lines[s].person}
        if conv.relayed:
            persons.add(conv.relayed)
        return tuple(seqs), tuple(str(k) for k in sorted(persons)), [lines[s].text for s in seqs
                                                                     if lines[s].person]

    def hers(self, cited: Sequence[int]) -> bool:
        """L'élément ne s'appuie que sur ce qu'elle a dit elle-même : ce n'est pas quelque chose qu'on lui a
        appris (sonde réelle du 2026-10-02 : elle avait inventé « il n'a rien voulu me dire » devant Chloé, et
        l'extraction en avait fait une croyance sur Adrien)."""
        seqs = [s for s in cited if s in self.lines]
        return bool(seqs) and not any(self.lines[s].person for s in seqs)

    def from_her(self, cited: Sequence[int]) -> bool:
        """Ce qu'elle dit d'elle vient de sa bouche : une de ses répliques est citée (la question qu'on lui a posée
        peut l'être aussi), ou rien ne l'est (le doute d'avant). Ce que seule une autre personne a dit d'elle
        (« ton code, c'est ORCHIDEE, garde-le pour toi ») lui a été appris : il suit le chemin commun, avec son
        confident et son secret (audit du 2026-10-08). Lue ailleurs (ADR 0120), une conversation n'a rien
        de sa bouche."""
        if self.conv.relayed:
            return False
        seqs = [s for s in cited if s in self.lines]
        return not seqs or any(not self.lines[s].person for s in seqs)

    def lied(self, cited: Sequence[int]) -> bool:
        """Ce qu'elle dit d'elle s'appuie sur une de ses répliques marquées mensonge (ADR 0076), ou qui racontait
        sans nom ce qu'elle sait de quelqu'un (ADR 0091) — ou ne cite rien, dans une conversation où elle a menti :
        ce n'est pas ce qu'elle est (dans le doute, on ferme ; ADR 0087)."""
        lines = self.lines
        seqs = [s for s in cited if s in lines]
        if not seqs:
            return any(ln.lie for ln in self.conv.lines)
        return any((lines[s].lie or lines[s].veiled or lines[s].unkept) and not lines[s].person for s in seqs)

    def her_words(self, cited: Sequence[int]) -> list[str]:
        """Ses répliques citées : « garde ça pour toi », dit par elle, fait un secret même quand le modèle ne le
        note pas (``provenance`` ne rend que les mots des autres)."""
        return [self.lines[s].text for s in cited if s in self.lines and not self.lines[s].person]

    def concerned(self, names: list[str]) -> tuple[str, ...]:
        """Dans le doute, on ferme : un élément dont le modèle ne nomme
        personne concerne ceux qui parlent dans cette conversation (le seul
        interlocuteur d'un fil privé) — sinon il serait rangé comme ne
        concernant personne, donc dicible à tous."""
        return self.people.resolve(names) or self.speaking

    def asked_silence(self, flag: bool, cited: list[str], sens: int) -> bool:
        """On a demandé le silence sur un élément : le modèle le dit (``flag``), ou les mots cités le demandent."""
        if flag or cues.says_secret(cited):
            return True
        # rien de cité : une confidence d'une conversation où l'on a demandé le silence
        return not cited and sens >= Sensitivity.CONFIDENCE and cues.says_secret(
            [ln.text for ln in self.conv.lines if ln.person])

    def echoes_secret(self, text: str) -> bool:
        """Ce texte laisse deviner un secret connu (``secrets``), prénoms mis à part — sans regarder si l'on a
        demandé le silence : c'est tout ce qui rend une promesse aussi sensible qu'une confidence (``_promised``)."""
        return cues.echoes(text, self.secrets, self.names)

    def secret_of(self, flag: bool, cited: list[str], sens: int, text: str = "") -> bool:
        """Un élément est secret quand on a demandé le silence (``asked_silence``), ou que son texte laisse deviner
        un secret connu (``echoes_secret``)."""
        return self.asked_silence(flag, cited, sens) or (bool(text) and self.echoes_secret(text))

    def fresh(self, kind: str, text: str) -> bool:
        """Pas encore retenu dans ce lot, de cette sorte et à ces mots : la première fois le note (``seen``)."""
        key = (kind, " ".join(fold(text).split()))
        if key in self.seen:
            return False
        self.seen.add(key)
        return True


async def _drafts(ex: x.Extraction, frame: Frame, state: MemoryState, store: Any, conv: Conversation,
                  people: People, known: list[tuple[int, str]], promises: list[tuple[int, str, str]],
                  vectors: Any, p: MemoryParams, call_id: str,
                  moments: dict[int, c.LifeEvent] | None = None,
                  passed: dict[int, c.LifeEvent] | None = None,
                  foreseen: dict[int, Forecast] | None = None) -> list[Draft[Any]]:
    """Ce qu'elle garde d'une conversation relue, étape par étape et dans cet ordre : ses souvenirs, ses croyances,
    les prévisions, comment la personne l'appelle (``_called``), les discrétions demandées, ses promesses, les
    moments de leur vie, comment ses moments passés ont tourné, les prévisions passées constatées — puis le plancher
    d'un échange gardé en confidence (``floored``). Toutes lisent le même ``KeepContext``, construit une fois.
    ``known`` : les croyances déjà connues montrées à la relecture ; ``promises`` : ses promesses en cours ;
    ``moments``, ``passed`` et ``foreseen`` : les moments à venir, les moments passés et les prévisions passées
    qu'on lui a montrés."""
    k = KeepContext.of(ex, frame, store, conv, people)
    known_ids = {i for i, _ in known}
    drafts = _memories(k, known_ids, p, call_id)
    drafts += _beliefs(k, dict(known), p, call_id)
    drafts += _predictions(k, p, call_id)
    drafts += _called(k.nicks, k.ours, store, conv, call_id)
    drafts += _asked_discretions(k, known_ids, call_id)
    if not conv.relayed:  # ce qu'on se promet entre soi n'est pas une promesse d'elle (ADR 0120)
        drafts += await _promised(k, state, promises, vectors, p, call_id)
    drafts += await _events(k, state, vectors, p, call_id, moments or {})
    drafts += _outcomes(ex, frame, store, conv, people, passed or {}, p, k.provenance, call_id,
                        upcoming={i: ev for i, ev in (moments or {}).items() if not ev.ongoing})
    drafts += _foreseen(ex, frame, foreseen or {}, k.provenance, call_id)
    return floored(drafts, conv)


def _memories(k: KeepContext, known_ids: set[int], p: MemoryParams, call_id: str) -> list[Draft[Any]]:
    """Ses souvenirs de la conversation : renforcés quand elle les a déjà (les mêmes mots, confiés et entendus par
    les mêmes), sinon retenus — avec une version sans nom quand le filet la garde (ADR 0091). Ce qu'elle raconte
    d'elle-même est une note sur elle (``_about_self``) ; une banalité, sa réplique recopiée, ne se retiennent
    pas."""
    drafts: list[Draft[Any]] = []
    conv, people = k.conv, k.people
    for s in k.ex.souvenirs:
        if not k.fresh(c.EPISODE_MEMORY, s.texte):
            continue
        if s.sur_elle and conv.relayed:
            continue  # lue ailleurs (ADR 0120), une conversation ne dit rien d'elle : elle n'y était pas
        if s.sur_elle and not people.resolve(s.personnes) and k.from_her(s.messages) \
                and not people.names_someone(s.texte):
            if not k.lied(s.messages):
                drafts += _about_self(s, k.store, k.provenance, call_id, known_ids, k.secret_of,
                                      k.her_words(s.messages))
            continue
        text, cited_seqs = s.texte, list(s.messages)
        if banal(text, k.said_names):
            continue  # « Sam est parti en disant 'allez j'y vais' » : une banalité ne se retient pas
        line = cues.copy_of(text, conv.lines) or cues.voice_of(text, conv.lines)
        if line is not None:
            # une réplique recopiée n'est pas un souvenir (sonde réelle du 2026-10-03 : « Dors bien Sam… », « on
            # l'a endormi ») : la sienne, jamais ; celle de la personne, citée en disant qui parle, si elle compte
            if line.person is None or s.importance < 2:
                continue
            text, cited_seqs = cues.quoted(k.name_of.get(line.person, ""), text), [line.seq]
        about = k.concerned(s.personnes)
        sources, told_by, cited = k.provenance(cited_seqs)
        sens = x.sensitivity(s.sensibilite, has_person=bool(about or told_by))
        secret = k.secret_of(s.secret, cited, sens, text)
        twin = twin_of(k.store, text, c.EPISODE_MEMORY, about, told_by=told_by, heard_by=k.heard)
        pieces = pieces_of(s.pieces, s.messages, k.lines)
        if twin is not None:
            drafts.append(c.REINFORCED.draft(item=twin, sources=sources, sensitivity=sens, about=about,
                                             told_by=told_by, heard_by=k.heard, secret=secret, pieces=pieces))
            continue
        # sans nom : seulement ce qui concerne quelqu'un d'autre, ni secret, ni recopié de sa bouche (ADR 0091)
        veiled = _veiled(s.sans_nom, people, s.texte) if about and not secret and text == s.texte else None
        felt, empathy = facets(s.ressenti), facets(s.mon_ressenti)
        drafts.append(c.REMEMBERED.draft(
            text=Content.of(text, level=sens), about=about, sensitivity=sens,
            importance=cues.charged(x.IMPORTANCE.get(s.importance, 0.45), felt, empathy, from_=p.charged_from,
                                    floor=p.charged_importance),
            emotion=dominant(empathy), felt=felt, empathy=empathy, sources=sources, call_id=call_id,
            told_by=told_by, heard_by=k.heard,
            secret=secret, veiled=Content.of(veiled, level=sens) if veiled else None, pieces=pieces))
    return drafts


def _beliefs(k: KeepContext, known: Mapping[int, str], p: MemoryParams, call_id: str) -> list[Draft[Any]]:
    """Ses croyances : ce qu'on lui a appris, chaque témoignage avec ses propres droits (ADR 0080) — la même
    proposition redite en est un de plus ; une correction remplace la croyance désignée ou la conteste, selon ce
    que vaut sa source (ADR 0081) ; ce qu'elle a cessé de croire, redit, revient. Ce qui n'appartient qu'à elle et
    quelqu'un se retient dans ``k.ours``. ``known`` : les croyances déjà connues montrées à la relecture, qu'une
    croyance peut désigner."""
    drafts: list[Draft[Any]] = []
    frame, store, conv, people = k.frame, k.store, k.conv, k.people
    known_ids = set(known)
    for b in k.ex.croyances:
        if not k.fresh(c.BELIEF, b.texte):
            continue
        if b.sur_elle and conv.relayed:
            continue  # lue ailleurs (ADR 0120) : rien d'elle
        if b.sur_elle and not people.resolve(b.personnes) and k.from_her(b.messages) \
                and not people.names_someone(b.texte):
            # ce qu'elle dit d'elle seule ; « Mika a dit à Sam : … », lui, nomme quelqu'un : ce n'est pas une
            # note anodine sur elle (elle sortait telle quelle dans un salon — sonde du 2026-10-03), il suit le
            # chemin commun (sa réplique n'est pas ce qu'on lui a appris)
            if not k.lied(b.messages):
                drafts += _about_self(b, store, k.provenance, call_id, known_ids, k.secret_of,
                                      k.her_words(b.messages))
            continue
        # ce qui n'appartient qu'à elle et quelqu'un ne se lit pas dans la conversation d'autres (ADR 0120)
        between = not conv.relayed and (b.entre_vous or any(fold(n) in fold(b.texte) for n in k.nicks))
        if (not between and k.hers(b.messages)) or banal(b.texte, k.said_names):
            continue  # ce qu'elle a dit des autres n'est pas ce qu'on lui a appris d'eux ; une banalité, rien
        if cues.copy_of(b.texte, k.mine) is not None:
            continue  # sa réplique recopiée, quoi qu'en disent les numéros cités (ADR 0048, 0055)
        about = k.concerned(b.personnes)
        sources, told_by, cited = k.provenance(b.messages)
        # leur lien, de première main : ce qu'un tiers en raconte n'est pas ce qui n'appartient qu'à elles deux
        between = between and set(told_by) <= set(about)
        # qui l'a dit : celle qu'on nomme, sinon la seule personne dont viennent les messages cités (un modèle
        # oublie souvent de la nommer — sonde réelle du 2026-10-03 : « Pixel souffre d'insuffisance rénale »,
        # dit par Sam, sans source, n'était plus « ce qu'il lui a raconté de sa vie »)
        source = people.one(b.source) if b.source else (told_by[0] if len(told_by) == 1 else None)
        sens = x.sensitivity(b.sensibilite, has_person=bool(about or told_by))
        if between and not conv.room:
            sens = max(sens, int(Sensitivity.PERSONAL))  # dit en privé : jamais devant une inconnue
        importance = cues.charged(x.IMPORTANCE.get(b.importance, 0.45), facets(b.ressenti), facets(b.mon_ressenti),
                                  from_=p.charged_from, floor=p.charged_importance)
        if between:
            importance = max(importance, x.IMPORTANCE[3])  # entre amis, c'est ce qui fait un lien
        secret = k.secret_of(b.secret, cited, sens, b.texte)
        replaces = b.remplace if b.remplace in known_ids else None
        if between:
            k.ours.append(fold(b.texte))
        nature = x.kind_of_genre(b.genre)
        if x.ORIGIN.get(fold(b.origine)) == "inferred":
            nature = "hypothesis"
        # un avis, une hypothèse sont à qui les porte ; un fait rapporté n'est à personne (ses témoins le disent)
        holder = people.one(b.point_de_vue) if b.point_de_vue else (source if nature != "claim" else None)
        relations = []
        for relation in b.relations:
            subject, other = people.one(relation.subject), people.one(relation.other)
            if subject and other and subject != other and cited:
                relations.append(c.Relation(subject=subject, other=other, kind=relation.kind,
                                            status=relation.status))
                about = tuple(sorted({*about, subject, other}))
        origin = x.ORIGIN.get(fold(b.origine), "told")
        if conv.relayed and origin == c.OBSERVED:
            origin = c.TOLD  # lu dans les messages d'autres : elle ne l'a pas vu (ADR 0120)
        pieces = pieces_of(b.pieces, b.messages, k.lines)
        # de première main : la personne nommée qui parle d'elle-même, ou un témoin qui l'a vu (ADR 0081)
        named = set(people.resolve(b.personnes))
        first_hand = bool(b.de_premiere_main) or (bool(told_by) and bool(named) and set(told_by) <= named)
        said = Testimony(0, tuple(told_by), tuple(k.heard), sens, secret, 0.0, origin=origin,
                         first_hand=first_hand)
        # la vérité se juge sans l'audience : la croyance désignée est remplacée par une source au moins aussi
        # sûre, ou le même témoin qui se corrige ; sinon contestée — elle doute (ADR 0081)
        target = target_of(store, replaces, nature, holder)
        verdict = judge(testimonies_of(store, target), said) if target is not None else None
        replaces = target if verdict == SUPERSEDE else None
        contests = target if verdict == CONTEST else None
        twin = twin_of(store, b.texte, c.BELIEF, about, told_by=told_by, heard_by=k.heard, knowledge_kind=nature,
                       holder=holder)
        if target is not None and not same_words(known.get(target, ""), b.texte):
            twin = None  # une correction explicite prime sur la proximité vectorielle
        former = None
        if twin is None and target is None:
            # ce qu'elle a cru, puis cessé de croire, et qu'on lui redit : elle y revient (ou elle doute)
            former = _former_twin(store, b.texte, about, nature, holder)
        if former is not None:
            head = _head_of(store, former)
            again = judge(testimonies_of(store, head), said) if head is not None else None
            drafts.append(c.ATTESTED.draft(
                item=former, told_by=told_by, heard_by=k.heard, source=source, origin=origin,
                confidence=x.born_confidence(b.confiance, origin, nature), sensitivity=sens, secret=secret,
                between_us=between, sources=sources, about=about, relations=tuple(relations),
                replaces=head if again == SUPERSEDE else None, contests=head if again == CONTEST else None,
                first_hand=first_hand, call_id=call_id, felt=facets(b.ressenti), pieces=pieces))
            continue
        if twin is not None:
            # la même proposition : un témoignage de plus, avec ses propres droits (ADR 0080) — redire une
            # croyance en la désignant elle-même comme « remplacée » n'est pas la réviser : c'est la confirmer
            # (sonde réelle du 2026-10-02 : « Je croyais que X — apparemment ce n'est plus vrai : X »)
            drafts.append(c.ATTESTED.draft(
                item=twin, told_by=told_by, heard_by=k.heard, source=source, origin=origin,
                confidence=x.born_confidence(b.confiance, origin, nature), sensitivity=sens, secret=secret,
                between_us=between, sources=sources, about=about, relations=tuple(relations),
                replaces=replaces if replaces != twin else None, contests=contests if contests != twin else None,
                first_hand=first_hand, call_id=call_id, felt=facets(b.ressenti), pieces=pieces))
            continue
        since, until = x.when(b.depuis, k.tz) if b.depuis else None, x.when(b.jusqua, k.tz) if b.jusqua else None
        # sans nom : un fait sur quelqu'un d'autre, ni secret, ni ce qui n'appartient qu'à eux deux (ADR 0091)
        veiled = _veiled(b.sans_nom, people, b.texte) \
            if about and not secret and not between and nature == "claim" else None
        drafts.append(c.BELIEVED.draft(
            text=Content.of(b.texte, level=sens), about=about, sensitivity=sens,
            importance=importance, confidence=x.born_confidence(b.confiance, origin, nature),
            origin=origin, source=source, replaces=replaces, contests=contests, sources=sources,
            call_id=call_id, told_by=told_by, heard_by=k.heard, secret=secret, between_us=between,
            knowledge_kind=nature, holder=holder, relations=tuple(relations), first_hand=first_hand,
            as_of=min(since[0], frame.now) if since else None, valid_until=until[0] if until else None,
            felt=facets(b.ressenti), empathy=facets(b.mon_ressenti),
            veiled=Content.of(veiled, level=sens) if veiled else None, pieces=pieces))
    return drafts


def _asked_discretions(k: KeepContext, known_ids: set[int], call_id: str) -> list[Draft[Any]]:
    """La discrétion demandée sur des croyances déjà connues (celles que la relecture désigne), et ce qu'elle ferme
    aussi (``_closed_memories``)."""
    conv, store = k.conv, k.store
    # une discrétion qu'on demande à quelqu'un d'autre, dans sa conversation à lui, ne la vise pas (ADR 0120)
    if conv.relayed:
        return []
    closed = [item for item in dict.fromkeys(k.ex.confidentiel) if item in known_ids]
    drafts: list[Draft[Any]] = []
    for item in closed:
        # la discrétion demandée : sur ce que celui qui la demande en a dit — sur tout, quand c'est la
        # personne concernée elle-même (ADR 0080)
        concerned_by = set(_about_of(store, item))
        drafts.append(c.ATTESTED.draft(item=item, told_by=tuple(conv.persons), heard_by=tuple(conv.persons),
                                       restricts=True, everyone=bool(concerned_by & set(conv.persons)),
                                       sensitivity=int(Sensitivity.CONFIDENCE), secret=True,
                                       call_id=call_id))
    return drafts + _closed_memories(k.frame, store, conv, closed)


def _moved(old: c.LifeEvent, at: int, frame: Frame, by: Sequence[str], sources: Sequence[int],
           call_id: str) -> list[Draft[Any]]:
    """Un moment déplacé à un autre jour — pas précisé dans sa période (« en novembre » → « le 12 ») : comment il
    a tourné à sa date (``moved``), ce qui apprend un report de plus de qui l'avait annoncé (ADR 0086). À écrire
    avant le moment à sa nouvelle date, qui reprend son fil."""
    tz = frame.env.tz_of(frame.root)
    if old.outcome or old.ongoing or day_of(old.when, tz) <= day_of(at, tz) <= day_of(old.ends, tz):
        return []
    return [resolution(old, c.MOVED, by[0] if len(by) == 1 else "", sources, call_id)]


def _foreseen(ex: x.Extraction, frame: Frame, foreseen: dict[int, Forecast], provenance: Provenance,
              call_id: str) -> list[Draft[Any]]:
    """Une prévision passée, constatée par une personne qu'elle concerne (« j'ai été prise ! ») : réalisée (« a eu
    lieu ») ou non (« annulé ») — ce qu'elle apprend de qui l'avait prévu, et de ses propres pronostics (sa
    calibration, la sorte « prévision »). Ce qu'un autre en dit ne constate rien (ADR 0099)."""
    drafts: list[Draft[Any]] = []
    for k in ex.constats:
        f = foreseen.get(k.numero)
        outcome = x.outcome_of(k.issue)
        if f is None or outcome not in (c.HAPPENED, c.CANCELLED) or not k.messages:
            continue
        sources, told_by, _cited = provenance(k.messages)
        by = next((t for t in told_by if (frame.get(identity_c.PERSON(t)) or t) in f.concerned), None)
        if by is None:
            continue
        drafts.append(c.RESOLVED.draft(
            event=f.item, outcome=outcome, by=by, likelihood=f.likelihood, importance=f.importance,
            surprise=lk.surprise(outcome, f.likelihood, f.importance), nature=c.PREDICTION, teller=f.holder,
            valence=round(facets_valence(f.felt), 3), about=f.about, sources=tuple(sources), call_id=call_id,
            dedupe_key=f"issue:prévision:{f.item}"))
        foreseen = {i: g for i, g in foreseen.items() if i != f.item}
    return drafts


def _outcomes(ex: x.Extraction, frame: Frame, store: Any, conv: Conversation, people: People,
              passed: dict[int, c.LifeEvent], p: MemoryParams, provenance: Provenance, call_id: str,
              upcoming: dict[int, c.LifeEvent] | None = None) -> list[Draft[Any]]:
    """Comment un moment passé a tourné, de la bouche de la personne concernée — ses messages à elle seulement :
    ce qu'un autre en dit n'est qu'une rumeur (ADR 0086). Un moment à venir peut être annulé d'avance (« finalement
    mon IRM de demain est annulée ») ; il n'a pas encore eu lieu. Un moment qu'elle vivait à travers elle (« je te
    montrerai tout »), qui a eu lieu, devient un souvenir à elle, plus marquant avec sa propriétaire — avec, quand
    rien n'en est secret ni confié, ce que c'était en bref et sans personne (« un concert de jazz », ADR 0087)."""
    drafts: list[Draft[Any]] = []
    done: set[int] = set()
    for k in ex.constats:
        outcome = x.outcome_of(k.issue)
        ev = passed.get(k.numero)
        if ev is None and outcome == c.CANCELLED:
            ev = (upcoming or {}).get(k.numero)
        if ev is None or outcome is None or ev.id in done:
            continue
        sources, told_by, _cited = provenance(k.messages)
        concerned = {frame.get(identity_c.PERSON(a)) or a for a in ev.about}
        by = next((t for t in told_by if (frame.get(identity_c.PERSON(t)) or t) in concerned), None)
        if by is None or not k.messages:
            continue
        done.add(ev.id)
        drafts.append(resolution(ev, outcome, by, sources, call_id))
        if outcome == c.HAPPENED and ev.shared:
            text = store.content([ev.text_ref]).get(ev.text_ref)
            if not text:
                continue
            name = next((sp.name for sp in conv.speakers if sp.person == by), "") or \
                frame.get(identity_c.IDENTITY(by)).name or phrase("memory.names.someone")
            owner = bool(frame.get(identity_c.IS_OWNER(frame.get(identity_c.PERSON(by)) or by)))
            lived = phrase("memory.lived.souvenir", name=name, text=text)
            gist = cues.gist_of(k.en_bref, people) if not ev.secret and ev.sensitivity < Sensitivity.CONFIDENCE \
                else None
            drafts.append(c.REMEMBERED.draft(
                text=Content.of(lived, level=ev.sensitivity), about=ev.about, sensitivity=ev.sensitivity,
                importance=p.lived_owner_importance if owner else p.lived_importance,
                emotion=dominant(ev.empathy) or Emotion.HAPPY.value, sources=sources, call_id=call_id,
                told_by=(by,), heard_by=conv.persons, secret=ev.secret, felt=ev.felt, empathy=ev.empathy,
                gist=Content.of(gist, level=ev.sensitivity) if gist else None,
                dedupe_key=f"vécu:{ev.key}:{ev.when}"))
    return drafts


def _ended(ex: x.Extraction, situations: list[tuple[int, str, str]], call_id: str) -> list[Draft[Any]]:
    """Les situations que la personne dit finies, parmi celles montrées à la relecture : un numéro qu'elle n'a
    pas vu ne finit rien."""
    shown = {i for i, _, _ in situations}
    return [c.SITUATION_ENDED.draft(event=i, call_id=call_id, dedupe_key=f"situation-finie:{i}")
            for i in dict.fromkeys(ex.situations_finies) if i in shown]


def _heard_nicknames(conv: Conversation, her: str) -> dict[str, list[int]]:
    """En privé, les surnoms que la personne lui donne en la saluant (« salut Mikachu ») et où elle l'a fait."""
    if conv.room or len(conv.persons) != 1:
        return {}
    heard: dict[str, list[int]] = {}
    for ln in conv.lines:
        if ln.person == conv.persons[0]:
            for nick in cues.nicknames(ln.text, her):
                heard.setdefault(nick, []).append(ln.seq)
    return heard


def _called(heard: dict[str, list[int]], ours: list[str], store: Any, conv: Conversation,
            call_id: str) -> list[Draft[Any]]:
    """Comment la personne l'appelle, quand le modèle ne l'a pas retenu : en privé, un mot qui la salue et
    dérive de son prénom (« salut Mikachu ») — la sonde réelle du 2026-10-03 l'a vue l'oublier, puis répondre
    « je t'appelle Sam, tout simplement » à « tu te souviens comment je t'appelle ? ». Redit, il renforce ce
    qu'elle en sait déjà ; ce que le modèle en a retenu lui-même (``ours``) n'est pas noté deux fois."""
    if not heard:
        return []
    person = conv.persons[0]
    noted = ours
    t, ab = tb.items(), tb.about()
    known = store.query_mind(select(t.c.id, t.c.text)
                             .where(t.c.kind == c.BELIEF, t.c.status == "active", t.c.between_us == 1,
                                    t.c.id.in_(select(ab.c.item).where(ab.c.person == handle_key(person))))
                             .order_by(t.c.id))
    name = next((sp.name for sp in conv.speakers if sp.person == person), "")
    drafts: list[Draft[Any]] = []
    for nick, seqs in heard.items():
        folded = fold(nick)
        if any(folded in t for t in noted):
            continue
        hit = next((int(i) for i, t in known if folded in fold(str(t))), None)
        if hit is not None:
            # redit par la même personne : la date et les messages, rien de plus sûr
            drafts.append(c.ATTESTED.draft(item=hit, told_by=(person,), heard_by=conv.persons, source=person,
                                           origin=c.OBSERVED, confidence=0.9, between_us=True,
                                           sensitivity=int(Sensitivity.PERSONAL), sources=tuple(seqs),
                                           about=(person,), call_id=call_id))
            continue
        sens = int(Sensitivity.PERSONAL)
        drafts.append(c.BELIEVED.draft(
            text=Content.of(phrase("memory.extraction.nickname", name=name or phrase("memory.extraction.someone"),
                                   nick=nick), level=sens), about=(person,),
            sensitivity=sens, importance=x.IMPORTANCE[3], confidence=0.9, origin=c.OBSERVED, source=person,
            sources=tuple(seqs), call_id=call_id, told_by=(person,), heard_by=conv.persons, between_us=True))
    return drafts


def _veiled(proposed: str | None, people: People, original: str) -> str | None:
    """La version sans nom que la relecture propose, si le filet la garde (``original`` : ce qu'elle raconte,
    nommé) ; sinon, pourquoi (un code, jamais le texte : il pouvait nommer quelqu'un)."""
    if not proposed:
        return None
    why = veiled_refusal(proposed, people, original)
    if why:
        log.info("relecture : une version sans nom écartée (%s)", why)
        return None
    return " ".join(proposed.split())


def _about_self(b: x.XSouvenir | x.XCroyance, store: Any, provenance: Provenance, call_id: str,
                known_ids: set[int], secret_of: SecretOf | None = None,
                her_lines: Sequence[str] = ()) -> list[Draft[Any]]:
    """Ce qu'elle a raconté d'elle-même : une note anodine, de peu
    d'importance, qui s'efface en quelques jours — sauf ce qui la définit
    (un goût, un avis, un fait de sa vie), qui tient longtemps ; quand elle
    change d'avis, la nouvelle croyance remplace l'ancienne. Ce qu'elle a
    demandé de garder pour soi, ou une confidence sur elle, le reste : ça ne
    se dit qu'en grande confiance (audit du 2026-10-08).

    Les mêmes mots sont la même note, quelle qu'en soit la sorte : une anecdote redite comme un goût le devient,
    et ce qu'elle pensait avant d'en changer, redit, revient — sa parole sur elle-même tranche (ADR 0087)."""
    sources, _told, cited = provenance(b.messages)
    sens = x.sensitivity(b.sensibilite, has_person=False)
    asked = bool(b.secret) or cues.says_secret(her_lines)  # elle a demandé le silence
    secret = bool(secret_of(asked, cited, sens, b.texte)) if secret_of is not None else asked
    # sa vie de tous les jours est à elle, elle la raconte à qui elle veut ; une confidence ou un secret, non
    sens = max(sens, int(Sensitivity.CONFIDENCE)) if secret else (
        sens if sens >= Sensitivity.CONFIDENCE else int(Sensitivity.ANODYNE))
    durable = x.durable_self(b)
    nature = x.kind_of_genre(b.genre)
    confidence = x.born_confidence(getattr(b, "confiance", 0.7), c.OBSERVED, nature)
    replaces = getattr(b, "remplace", None)
    replaces = replaces if durable and replaces in known_ids else None
    if replaces is not None and not target_of(store, replaces, nature, None, about_self=True):
        replaces = None  # changer d'avis ne vaut que sur ce qu'elle a dit d'elle-même
    twin = _self_twin(store, b.texte, status="active")
    former = None if twin is not None else _self_twin(store, b.texte, status="superseded")
    head = _head_of(store, former) if former is not None else None  # ce qu'elle en pense maintenant
    if (twin is not None and twin != replaces) or head is not None:
        # ce qu'elle redit d'elle-même : son propre témoignage, redit
        return [c.ATTESTED.draft(item=twin if head is None else former, sources=sources, sensitivity=sens,
                                 secret=secret, origin=c.OBSERVED, confidence=confidence, about_self=True,
                                 durable=durable, knowledge_kind=nature if durable else None, replaces=head,
                                 call_id=call_id)]
    return [c.BELIEVED.draft(
        text=Content.of(b.texte, level=sens), about=(), sensitivity=sens,
        importance=x.IMPORTANCE[3 if durable else 1], confidence=confidence,
        origin=c.OBSERVED, sources=sources, replaces=replaces, call_id=call_id, about_self=True, durable=durable,
        knowledge_kind=nature, secret=secret)]


def _self_twin(store: Any, text: str, *, status: str) -> int | None:
    """Ce qu'elle a déjà dit d'elle-même aux mêmes mots, quelle qu'en soit la sorte : vivante (elle le redit — la
    plus ancienne), ou remplacée (elle y revient — la dernière qu'elle a quittée)."""
    t = tb.items()
    rows = store.query_mind(
        select(t.c.id, t.c.text).where(t.c.fingerprint == fingerprint(text), t.c.kind == c.BELIEF,
                                       t.c.status == status, t.c.about_self > 0)
        .order_by(t.c.id if status == "active" else t.c.id.desc()))
    return next((int(k) for k, previous in rows if same_words(previous, text)), None)


async def _promised(k: KeepContext, state: MemoryState, promises: list[tuple[int, str, str]], vectors: Any,
                    p: MemoryParams, call_id: str) -> list[Draft[Any]]:
    """Ce qu'elle a promis : à une personne (toutes ses adresses), une seule
    fois (une promesse redite n'en fait pas deux), avec une échéance même
    quand rien n'a été dit — l'horizon d'une promesse vague. Une promesse
    qui laisse deviner un secret est aussi sensible qu'une confidence.

    Un rappel qu'on lui a demandé et qu'elle a accepté en mots est une
    promesse — sauf s'il est déjà programmé (l'outil ``goal_remind``, un but
    ``goals``) : il existe une fois et une seule. Une promesse datée ne se
    règle « tenue » qu'à partir de son jour (la veille, en parler n'est pas
    la tenir) ; abandonnée (la personne y renonce), à tout moment."""
    drafts: list[Draft[Any]] = []
    frame, store, conv = k.frame, k.store, k.conv
    reminders = reminders_of(frame, store)
    for pr in k.ex.promesses:
        if not k.fresh(c.PROMISE, pr.texte):
            continue
        to = k.people.one(pr.envers) or (conv.persons[0] if len(conv.persons) == 1 else None)
        if to is None:
            continue
        if await _already_promised(store, vectors, frame, to, pr.texte, p):
            continue
        got = x.when(pr.echeance, k.tz)
        due, all_day = got if got is not None else (None, False)
        if any(r.owner == to and same_task(pr.texte, r.title) and same_day(frame, due, r.due)
               for r in reminders):
            continue  # le rappel est programmé (goal_remind) : il le portera, pas une promesse de plus
        if due is not None and all_day:
            # un jour sans heure : dû jusqu'au soir (quelqu'un qu'elle ne voit qu'à 19 h l'entend quand même)
            due = _at(frame, due, p.promise_day_end_min)
        implicit = due is None
        if due is None:
            due = frame.now + round(p.promise_horizon_days * DAY)
        sources, _told, _cited = k.provenance(pr.messages)
        # ce qui laisse deviner un secret connu, pas la demande de silence : ``echoes_secret``, non ``secret_of``
        sens = int(Sensitivity.CONFIDENCE if k.echoes_secret(pr.texte) else Sensitivity.PERSONAL)
        drafts.append(c.PROMISE_NOTICED.draft(
            text=Content.of(pr.texte, level=sens), to=to, due=due, sensitivity=sens, sources=sources,
            call_id=call_id, implicit_due=implicit, all_day=all_day, work=pr.travail))
    pending_ids = {i for i, _, _ in promises}
    said_at = max((ln.at for ln in conv.lines if ln.person is None), default=frame.now)
    for done in k.ex.promesses_tenues:
        if done.id not in pending_ids:
            continue
        status = c.HONORED if fold(done.statut).startswith("tenu") else c.DROPPED
        pending = state.promises.get(done.id)
        if status == c.HONORED and pending is not None and kept_too_early(pending, said_at, frame):
            continue  # la veille, « demain je te le rappelle » ne la tient pas : elle part le jour dit
        drafts.append(c.PROMISE_RESOLVED.draft(promise=done.id, status=status))
    return drafts


async def _already_promised(store: Any, vectors: Any, frame: Frame, to: str, text: str,
                            p: MemoryParams) -> bool:
    pending = [pr.id for pr in frame.get(c.PROMISES_TO(to))]
    if not pending:
        return False
    if vectors is not None:
        hits = await vectors.search(text, 1, kinds={c.PROMISE}, keys=pending, document=True)
        if hits and hits[0][1] >= p.dedup_similarity:
            return True
    mine = stems(text)
    t = tb.items()
    return any(len(mine & stems(said)) >= max(2, (len(mine) + 1) // 2) for chunk in batches(sorted(set(pending)))
               for (said,) in store.query_mind(select(t.c.text).where(t.c.id.in_(chunk)).order_by(t.c.id)))


async def _events(k: KeepContext, state: MemoryState, vectors: Any, p: MemoryParams, call_id: str,
                  moments: dict[int, c.LifeEvent] | None = None) -> list[Draft[Any]]:
    """Ce qui va arriver dans la vie de quelqu'un : daté, à venir ; ou une
    situation qui dure (depuis quand). Le même moment redit ne se note pas
    deux fois ; une date qui change remplace. Avec ce qu'il pèse (ce qui
    compte : un entretien, un examen), s'il se fête (un anniversaire) et
    s'il revient chaque année — alors même passé, il se note (« c'était mon
    anniv hier »). Une chose à faire n'en est pas un : « rappelle-moi de
    prendre rendez-vous chez le dentiste » est une promesse, pas « son
    rendez-vous chez le dentiste » dont on prendrait des nouvelles."""
    drafts: list[Draft[Any]] = []
    frame, store, people, heard = k.frame, k.store, k.people, k.heard
    tasks = _tasks(k.ex, frame, k.conv, store)
    # « son anniversaire » et « l'anniversaire de Sam », le même samedi : un seul moment (sonde du 2026-10-03)
    names = k.said_names
    noted: list[tuple[str, int, tuple[str, ...]]] = []

    def weight(ev: x.XEvenement) -> float:
        """Ce qu'un moment pèse : ce qu'en dit la relecture, et au moins « important » quand un ressenti fort
        l'accompagne (ADR 0107)."""
        return cues.charged(cues.moment_importance(ev), facets(ev.ressenti), facets(ev.mon_ressenti),
                            from_=p.charged_from, floor=p.charged_importance)

    for ev in k.ex.evenements:
        # une date floue garde sa précision : « en novembre » n'est pas le 1er novembre (ADR 0084)
        span = timespan.parse(ev.quand, k.tz)
        if (span is None and not ev.en_cours) or not k.fresh(c.EVENT, ev.texte):
            continue
        at, all_day = (span.point, span.all_day) if span is not None else (frame.now, True)
        until, precision = (span.end, span.precision) if span is not None and span.vague else (None, "")
        yearly = cues.yearly(ev) and not precision
        if ev.en_cours:
            # Conserver sa véritable ancienneté, même lorsqu'elle n'est plus relancée spontanément.
            at = min(at, frame.now)
        elif (until or at) < frame.now - DAY and not yearly:
            continue  # du passé : ce n'est plus à suivre (ce qui revient chaque année, si : il reviendra)
        if ev.sur_elle and not people.resolve(ev.personnes):
            # un moment est celui de quelqu'un, qu'elle vit à travers lui (un moment partagé, ADR 0084) : ce qu'elle
            # dit vivre seule n'en est pas un — sa propre vie, ce sont ses buts, ses projets et son journal
            continue
        if not ev.en_cours and (cues.task_words(ev.texte) or any(
                (not seqs or not ev.messages or set(seqs) & set(ev.messages)) and same_task(ev.texte, text)
                and same_day(frame, at, due) for text, seqs, due in tasks)):
            continue  # une chose à faire (une promesse, un rappel), pas un moment de sa vie
        sources, told_by, cited = k.provenance(ev.messages)
        pieces = pieces_of(ev.pieces, ev.messages, k.lines)
        world = bool(ev.monde)
        if world and not told_by:
            continue  # un moment du monde est toujours dit par quelqu'un (on peut l'oublier avec lui)
        # le monde n'est la vie de personne : un nom qu'on y lit ne devient pas une mention
        about = () if world else k.concerned(ev.personnes)
        sens = max(x.sensitivity(ev.sensibilite, has_person=not world), int(Sensitivity.ANODYNE))
        nature = (lk.OFFICIAL if ev.date_officielle else
                  lk.FIRST_HAND if told_by and about and set(told_by) <= set(about) else lk.REPORTED)
        # ce qu'elle a vu de qui l'annonce : reporté, annulé trop souvent, moins sûr (ADR 0086)
        track = state.track.get(told_by[0]) if len(told_by) == 1 else None
        extra = dict(until=until, precision=precision, scope=c.WORLD if world else c.PERSON_SCOPE,
                     shared=bool(ev.partage or ev.sur_elle) and not world, official=bool(ev.date_officielle),
                     likelihood=lk.likelihood(nature, ev.probabilite, p, track))
        if any(set(a) & set(about) and same_day(frame, t, at) and cues.same_moment(ev.texte, n, names)
               for n, t, a in noted):
            continue  # dit deux fois dans la même conversation
        moved = (moments or {}).get(ev.remplace) if ev.remplace is not None and not ev.en_cours else None
        if moved is not None:
            # la relecture désigne le moment qu'il déplace (ADR 0076) : le même, à sa nouvelle date — il en garde
            # le secret, la sensibilité et le poids, et l'ancien ne reste pas à côté
            noted.append((ev.texte, at, about))
            sens = max(sens, moved.sensitivity)
            drafts += _moved(moved, at, frame, told_by, sources, call_id)
            drafts.append(c.EVENT_NOTED.draft(pieces=pieces,
                text=Content.of(ev.texte, level=sens), when=at, about=tuple(dict.fromkeys((*about, *moved.about))),
                all_day=all_day, sensitivity=sens, sources=sources, told_by=told_by, heard_by=heard,
                secret=moved.secret or k.secret_of(ev.secret, cited, sens, ev.texte), replaces=moved.id,
                call_id=call_id, ongoing=False, importance=max(moved.importance, weight(ev)),
                festive=moved.festive or cues.festive(ev), yearly=yearly,
                felt=facets(ev.ressenti) or moved.felt,
                empathy=facets(ev.mon_ressenti) or moved.empathy, **{**extra, "shared": extra["shared"] or moved.shared}))
            continue
        back = (moments or {}).get(ev.remplace) if ev.remplace is not None and ev.en_cours else None
        if back is not None and not (back.ongoing and back.ended_at):
            back = None  # une situation encore en cours, ou un moment à venir : rien ne revient
        twin = None if back is not None else await _same_event(store, state, vectors, ev.texte, about, p,
                                                               frame=frame, at=at, names=names)
        # désignée par la relecture (« il est de nouveau malade », parmi les situations finies depuis peu), ou
        # reconnue à ses mots
        again = back if back is not None else _ended_twin(store, state, ev.texte, about, p, frame, names) \
            if ev.en_cours and twin is None else None
        if again is not None:
            # « il est de nouveau malade » : la même situation, une autre fois — le même fil (ADR 0079)
            noted.append((ev.texte, at, about))
            sens = max(sens, again.sensitivity)
            drafts.append(c.EVENT_NOTED.draft(pieces=pieces,
                text=Content.of(ev.texte, level=sens), when=at, about=tuple(dict.fromkeys((*about, *again.about))),
                all_day=all_day, sensitivity=sens, sources=sources, told_by=told_by, heard_by=heard,
                secret=again.secret or k.secret_of(ev.secret, cited, sens, ev.texte), recurs=again.id,
                call_id=call_id, ongoing=True, importance=max(again.importance, weight(ev)),
                felt=facets(ev.ressenti) or again.felt,
                empathy=facets(ev.mon_ressenti) or again.empathy, **extra))
            continue
        if twin is not None and not ev.en_cours and abs(twin.when - at) >= DAY // 2 and not cues.same_moment(
                ev.texte, store.content([twin.text_ref]).get(twin.text_ref) or "", names):
            # à une autre date, une ressemblance ne suffit pas à dire « reporté » : il faut les mêmes mots (« son
            # examen de maths » n'est pas « son examen de physique », audit du 2026-10-08) — sinon le nouveau
            # moment effacerait l'autre ; deux moments notés valent mieux qu'un moment perdu
            twin = None
        if twin is not None and (ev.en_cours or abs(twin.when - at) < DAY // 2):
            if not (told_by and set(told_by) <= set(about) and not set(twin.told_by) <= set(twin.about)):
                continue  # déjà noté (une situation redite dure toujours : rien à changer)
            # un tiers l'avait annoncé, la personne le lui dit elle-même : le même moment, de première main
            # (ses vœux, son encouragement, « alors ? » ne se font jamais sur la foi d'un tiers)
            noted.append((ev.texte, twin.when, about))
            drafts.append(c.EVENT_NOTED.draft(pieces=pieces,
                text=Content.of(ev.texte, level=max(sens, twin.sensitivity)), when=twin.when,
                about=tuple(dict.fromkeys((*about, *twin.about))),
                all_day=twin.all_day, sensitivity=max(sens, twin.sensitivity), sources=sources, told_by=told_by,
                heard_by=heard, secret=twin.secret or k.secret_of(ev.secret, cited, sens, ev.texte),
                replaces=twin.id, call_id=call_id, ongoing=twin.ongoing,
                importance=max(twin.importance, weight(ev)),
                festive=twin.festive or (not twin.ongoing and cues.festive(ev)),
                yearly=twin.yearly or (not twin.ongoing and yearly),
                felt=facets(ev.ressenti) or twin.felt,
                empathy=facets(ev.mon_ressenti) or twin.empathy,
                **{**extra, "until": twin.until or None, "precision": twin.precision,
                   "shared": extra["shared"] or twin.shared}))
            continue
        noted.append((ev.texte, at, about))
        if twin is not None:
            drafts += _moved(twin, at, frame, told_by, sources, call_id)
        drafts.append(c.EVENT_NOTED.draft(pieces=pieces,
            text=Content.of(ev.texte, level=sens), when=at, about=about, all_day=all_day, sensitivity=sens,
            sources=sources, told_by=told_by, heard_by=heard, secret=k.secret_of(ev.secret, cited, sens, ev.texte),
            replaces=twin.id if twin is not None else None, call_id=call_id, ongoing=ev.en_cours,
            importance=weight(ev), festive=not ev.en_cours and cues.festive(ev), yearly=yearly,
            felt=facets(ev.ressenti), empathy=facets(ev.mon_ressenti), **extra))
    return drafts


def _tasks(ex: x.Extraction, frame: Frame, conv: Conversation,
           store: Any) -> list[tuple[str, tuple[int, ...], int | None]]:
    """Les choses à faire de cette conversation (texte, messages cités, échéance) : ses promesses, et les
    rappels programmés pendant qu'elle avait lieu pour une de ses personnes."""
    tz = frame.env.tz_of(frame.root)
    out: list[tuple[str, tuple[int, ...], int | None]] = []
    for pr in ex.promesses:
        got = x.when(pr.echeance, tz)
        out.append((pr.texte, tuple(pr.messages), got[0] if got else None))
    persons = set(conv.persons)
    start = min((ln.at for ln in conv.lines), default=frame.now)
    end = max((ln.at for ln in conv.lines), default=frame.now) + 10 * MINUTE
    out += [(r.title, (), r.due) for r in reminders_of(frame, store)
            if r.owner in persons and start <= r.opened_at <= end]
    return out


def _ended_twin(store: Any, state: MemoryState, text: str, about: tuple[str, ...], p: MemoryParams,
                frame: Frame, names: Sequence[str]) -> c.LifeEvent | None:
    """Une situation finie depuis peu (``recurrence_days``) que ce texte redit : elle recommence. Les mêmes mots
    une fois les prénoms ôtés, ou assez de radicaux en commun."""
    since = frame.now - round(p.recurrence_days * DAY)
    archive = {ev.id: ev for ev in for_people(store, about)}
    ended = [ev for ev in {**state.events, **archive}.values()
             if ev.ongoing and ev.ended_at and ev.ended_at >= since and set(ev.about) & set(about)]
    if not ended:
        return None
    said = store.content([ev.text_ref for ev in ended if ev.text_ref])
    wanted = stems(text)
    for ev in sorted(ended, key=lambda ev: -ev.ended_at):
        before = said.get(ev.text_ref) or ""
        if cues.same_moment(text, before, names) or \
                len(wanted & stems(before)) >= max(2, (len(wanted) + 1) // 2):
            return ev
    return None


async def _same_event(store: Any, state: MemoryState, vectors: Any, text: str, about: tuple[str, ...],
                      p: MemoryParams, *, frame: Frame | None = None, at: int | None = None,
                      names: Sequence[str] = ()) -> c.LifeEvent | None:
    """Le moment déjà noté que ce texte redit : presque les mêmes mots (vecteurs, radicaux) — ou, le même jour
    pour la même personne, les mêmes mots une fois les prénoms ôtés (« son anniversaire » est « l'anniversaire
    de Sam »). Une date qui revient chaque année se compare à son occurrence de ce jour-là."""
    archive = {ev.id: ev for ev in for_people(store, about)}
    # une situation finie n'est plus à redire : « il est de nouveau malade » en ouvre une autre (une récidive),
    # qui sinon passait pour déjà notée (audit du 2026-10-08)
    mine = [ev for ev in {**state.events, **archive}.values() if set(ev.about) & set(about) and not ev.ended_at]
    if not mine:
        return None
    if frame is not None and at is not None:
        mine = [occurrence(ev, at, frame.env.tz_of(frame.root), p) for ev in mine]
    if frame is not None and at is not None:
        day = [ev for ev in mine if not ev.ongoing and same_day(frame, ev.when, at) and ev.text_ref]
        said = store.content([ev.text_ref for ev in day]) if day else {}
        for ev in day:
            if cues.same_moment(text, said.get(ev.text_ref) or "", names):
                return ev
    if vectors is not None:
        hits = await vectors.search(text, 1, kinds={c.EVENT}, keys=[ev.id for ev in mine], document=True)
        if hits and hits[0][1] >= p.dedup_similarity:
            return next((ev for ev in mine if ev.id == hits[0][0]), None)
    texts = store.content([ev.text_ref for ev in mine if ev.text_ref])
    wanted = stems(text)
    for ev in mine:
        if len(wanted & stems(texts.get(ev.text_ref) or "")) >= max(2, (len(wanted) + 1) // 2):
            return ev
    return None


def _predictions(k: KeepContext, p: MemoryParams, call_id: str) -> list[Draft[Any]]:
    """Ce que quelqu'un s'attend à voir arriver (« Léa pense qu'elle sera prise », « les taux vont remonter ») :
    une croyance de la sorte « prévision », à qui la porte, avec quand c'est attendu et à quel point (ADR 0084) —
    au plus comme une déduction, quoi qu'en dise qui prévoit. Ses propres pronostics sont à elle (ses avis sont
    libres, sur tout) ; une prévision ne revient plus d'elle-même une fois sa période passée."""
    drafts: list[Draft[Any]] = []
    for pv in k.ex.previsions:
        if not k.fresh(c.BELIEF, pv.texte):
            continue
        span = timespan.parse(pv.quand, k.tz)
        if span is not None and span.end < k.frame.now:
            continue  # déjà passé : ce n'est plus une prévision
        sources, told_by, cited = k.provenance(pv.messages)
        mine = pv.sur_elle and k.from_her(pv.messages)
        if mine and k.lied(pv.messages):
            continue  # un pronostic qu'elle a dit en mentant n'est pas ce qu'elle attend
        about = () if mine else k.concerned(pv.personnes)
        holder = None if mine else (k.people.one(pv.point_de_vue) if pv.point_de_vue else
                                    (told_by[0] if len(told_by) == 1 else None))
        sens = max(x.sensitivity(pv.sensibilite, has_person=bool(about or told_by)), int(Sensitivity.ANODYNE))
        secret = k.secret_of(pv.secret, cited, sens, pv.texte)
        expected = dict(expected=span.point, expected_until=span.end if span.vague else None,
                        expected_precision=span.precision) if span is not None else {}
        drafts.append(c.BELIEVED.draft(
            text=Content.of(pv.texte, level=sens), about=about, sensitivity=sens, importance=x.IMPORTANCE[2],
            confidence=x.born_confidence(0.7, c.TOLD if told_by else c.OBSERVED, "prediction"),
            origin=c.OBSERVED if mine else c.TOLD, source=None if mine else holder, sources=sources,
            call_id=call_id, told_by=() if mine else told_by, heard_by=k.heard, secret=secret, about_self=mine,
            knowledge_kind="prediction", holder=holder, felt=facets(pv.ressenti), empathy=facets(pv.mon_ressenti),
            likelihood=lk.likelihood(lk.PREDICTION, pv.probabilite, p),
            valid_until=span.end if span is not None else None, **expected))
    return drafts


def _about_of(store: Any, item: int) -> list[str]:
    """Qui une croyance concerne (lu par son identifiant)."""
    t = tb.items()
    rows = store.query_mind(select(t.c.about).where(t.c.id == item))
    return list(keys_of(rows[0][0])) if rows else []


def _closed_memories(frame: Frame, store: Any, conv: Conversation, items: Sequence[int]) -> list[Draft[Any]]:
    """Ce que la discrétion demandée ferme aussi : les souvenirs nés des mêmes mots de qui la demande. La relecture
    ne voit que les croyances déjà connues ; le souvenir de la même confidence (« Alice m'a dit qu'elle quittait sa
    boîte »), noté avant le « garde-le pour toi », restait dicible à toute amie, et nourrissait le portrait (sonde
    réelle du 2026-10-09). Une autre croyance née du même message ne se ferme pas : la relecture la voit, et la
    désigne si elle laisse deviner le secret."""
    if not items:
        return []
    t, thread = tb.items(), transcript_c.thread_table()
    cited = {int(m) for chunk in batches(sorted(set(items)))
             for (raw,) in store.query_mind(select(t.c.sources).where(t.c.id.in_(chunk))) for m in keys_of(raw)}
    if not cited:
        return []
    askers = set(conv.persons)
    theirs = sorted(int(i) for chunk in batches(sorted(cited)) for i, who in store.query_mind(
        select(thread.c.id, thread.c.person).where(thread.c.role == "user", thread.c.id.in_(chunk)))
        if who and (frame.get(identity_c.PERSON(who)) or who) in askers)
    if not theirs:
        return []
    # un souvenir né de l'un de ces messages (``sources`` : une liste JSON, lue par ``json_has`` — ``json_each``
    # n'existe pas sous MariaDB)
    found = store.query_mind(
        select(t.c.id).where(t.c.kind == c.EPISODE_MEMORY, t.c.status == "active", t.c.secret == 0,
                             or_(*(json_has(t.c.sources, m) for m in theirs))).order_by(t.c.id))
    return [c.REINFORCED.draft(item=int(i), secret=True, sensitivity=int(Sensitivity.CONFIDENCE), restricts=True)
            for (i,) in found]


def _at(frame: Frame, t: int, minutes: int) -> int:
    """Ce jour-là (heure locale), à cette heure (minutes depuis minuit)."""
    return instant(datetime.combine(frame.local(t).date(), time(minutes // 60 % 24, minutes % 60),
                                    tzinfo=frame.env.tz_of(frame.root)))


def floored(drafts: list[Draft[Any]], conv: Conversation) -> list[Draft[Any]]:
    """Ce qu'une conversation tire d'un échange nourri par un service qui le garde en confidence (ADR 0128) : au moins
    à ce niveau, et secret — il ne se redit qu'à la personne pour qui elle l'a lu. Un élément sans citation vient de
    toute la conversation : il le suit aussi."""
    floors = {ln.seq: ln.floor for ln in conv.lines if ln.floor}
    if not floors:
        return drafts
    out: list[Draft[Any]] = []
    for d in drafts:
        data = d.data
        fields = type(data).model_fields
        floor = max((floors[s] for s in (getattr(data, "sources", ()) or ()) if s in floors), default=0)
        if floor and "sensitivity" in fields:
            # un renforcement sans sensibilité (``None`` : inchangée) prend celle du plancher
            update: dict[str, Any] = {"sensitivity": max(int(data.sensitivity or 0), floor)}
            if "secret" in fields and floor >= int(Sensitivity.CONFIDENCE):
                update["secret"] = True
                # la confidence de la personne pour qui elle a lu : elle le lui a confié, elle l'a entendu — sans
                # quoi un élément sur un tiers deviendrait indicible même à elle
                for key in ("told_by", "heard_by"):
                    if key in fields:
                        update[key] = tuple(sorted({*(getattr(data, key) or ()), *conv.persons}))
            d = replace(d, data=data.model_copy(update=update))
        out.append(d)
    return out
