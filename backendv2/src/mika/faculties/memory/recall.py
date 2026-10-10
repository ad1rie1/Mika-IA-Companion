"""Le rappel : ce qui lui revient pendant qu'elle parle à quelqu'un.

L'enrichisseur cherche ce qui ressemble à la conversation — le dernier
message, et les quelques précédents (« et lui, il va mieux ? » se comprend
avec ce qui précède). Rien sur un tour phatique (« bonne nuit », « ah
d'accord ») : on ne repense pas à sa vie à chaque politesse. Ne revient que
ce qui dépasse un seuil absolu **et** reste près du meilleur candidat ; ce qui
dort ne revient que sur un indice fort. Puis il garde ce qui peut se dire
devant cette audience, le classe (pertinence × ce qu'il en reste × lien avec
la personne × humeur × pas montré à l'instant), et rend :

- ses souvenirs et ce qu'elle sait (``CE QUI TE REVIENT``) — une personne
  qu'elle connaît, nommée dans le message ou juste avant, y fait revenir ce
  qu'elle sait d'elle ; « comment je t'appelle ? », ce qui n'appartient qu'à
  eux (ADR 0055) ; ce qui vient
  d'autres au-delà de l'anodin porte une étiquette qui nomme qui l'a confié ;
  ce qui ne peut pas se dire ici devient une ligne vague (elle sait qu'elle
  sait, sans un mot du contenu) ;
- ce qu'elle a vécu avec l'interlocuteur et d'autres (il était là) ;
- des extraits d'échanges passés **avec cette personne** (ou dans ce salon),
  cherchés à part — les extraits des autres n'étouffent pas ses souvenirs —
  et jamais ce que le fil montré contient déjà ; ni un échange qui n'apprend
  rien (« coucou Mika ! »), ni deux fois le même ;
- les promesses qu'elle lui a faites (sa fiche, donc seulement si elle est
  ouverte), et celle qu'il est temps de tenir (un jour sans heure : toute la
  journée) — quand quelque chose de grave la touche, seulement ce qui est dû
  aujourd'hui ; ce qui se passe dans sa vie (un entretien jeudi, et après :
  « alors ? » — envers une amie, la première chose qu'elle demanderait si ça
  compte ; une situation qui dure, son chat malade ; le jour d'un anniversaire,
  ses vœux). Quand quelque chose de grave la touche ces jours-ci (un deuil, une
  rupture), le banal se tait et ce qui compte passe après des nouvelles d'elle ;
- au premier mot d'une conversation (« salut ! »), ou quand elle écrit
  d'elle-même, ce que la personne lui a raconté de sa vie ces derniers jours
  (sa fiche, de première main) : « et Moustache, il va mieux ? » ne dépend plus
  du hasard d'une ressemblance ;
- quand on lui parle d'elle (« ton plat préféré ? »), ce qu'elle a déjà dit de
  ses goûts, de ses avis, de sa vie : elle ne se contredit pas.

Une croyance apprise il y a plus d'une semaine dit depuis quand (« appris il y
a 3 semaines ») ; un souvenir vécu avec quelqu'un à qui elle tient s'endort
moins vite.

Toute panne → rien (le tour part sans mémoire, jamais avec trop).
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from mika.contracts import affect as affect_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as c
from mika.contracts import self_ as self_c
from mika.contracts import social as social_c
from mika.contracts import transcript as transcript_c
from mika.faculties.memory.extraction import date_words, mention_scope, same_moment, scope_of, weekday_words
from mika.faculties.memory.faculty import MEMORY, MemoryParams, MemoryState, over, params
from mika.faculties.memory.knowledge import Testimony, pooled
from mika.faculties.memory.life import due_now, kept_too_early, takes_up_moment
from mika.faculties.memory.likelihood import cautious, likely_words, nature_of
from mika.faculties.memory.projections import (
    CONTESTS_TABLE,
    ITEM_COLUMNS,
    TESTIMONIES_TABLE,
    TESTIMONY_COLUMNS,
    testimony_of,
)
from mika.faculties.memory.salience import (
    Item,
    Verdict,
    admissible,
    age_words,
    dormant,
    facets_sign,
    rank,
    salience,
    tag,
    touched,
    unsaid,
    unsaid_line,
    unsaid_public_line,
    valence_sign,
)
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.faculty import Zone
from mika.kernel.frame import Audience, Frame
from mika.kernel.prompt import Fragment, SectionBody
from mika.vocab import affect as A
from mika.vocab import timespan
from mika.vocab.days import when_fr, window_of
from mika.vocab.episodes import CONVERSATIONAL, Kind
from mika.vocab.people import clean_tokens, is_identifiable, named_label, read_source
from mika.vocab.phrasebook import family, phrase
from mika.vocab.privacy import Sensitivity
from mika.vocab.words import WORD, fold, stems, words

#: les mots d'une politesse : un tour qui n'a rien d'autre ne réveille aucun souvenir
PHATIC = frozenset("""
bonne bonnes nuit soiree soir journee matinee aprem bonjour bonsoir hello coucou salut hey yop accord daccord okay oki
cool super top genial parfait nickel bisous bises bisou plus tard bientot dodo ciao bye byebye lol mdr haha hahaha
hihi yes yep nope voila bref ouf merci beaucoup grave clair carrement exact exactement tranquille tkt dac fais quoi
ahah ahh ohh hmm hum mmh ptdr xptdr sinon allez drole marrant dingue wow waouh ouah chouette comment pourquoi
combien lequel laquelle appelle appelles appelait souvenir rappeler rappel
""".split())
#: le poids des messages précédents dans la recherche (le dernier compte davantage)
CONTEXT_WEIGHT = 0.9
#: les messages précédents ne comptent que s'ils sont de la même conversation (pas d'hier)
CONTEXT_SPAN_US = HOUR
#: ce que vaut, en plus de la similarité des vecteurs, un élément qui contient tous les mots qui portent le
#: sujet du message (« samedi », « Moustache ») : un plongement multilingue rapproche volontiers « samedi »
#: de « hier soir » ; le mot lui-même ne trompe pas
LEXICAL_BONUS = 0.35
#: le fil que le prompt montre déjà (l'enrichissement de ``transcript``) : ses tours portent leur ``id``
SHOWN_THREAD = "thread"
#: un échange encore à l'écran (sans fil connu) ne se répète pas
RECENT_EXCHANGE_US = 10 * MINUTE
#: un moment dont elles viennent de reparler (``moment_followed`` : en mots, pas seulement montré) reste sous ses
#: yeux le temps de la conversation — sans la consigne de demander, c'est fait
FOLLOWED_KEEP_US = 2 * HOUR
#: une croyance apprise il y a plus longtemps dit depuis quand (« ma sœur vient ce week-end » n'est plus vrai)
DATED_AFTER_US = 7 * DAY
#: on lui parle d'elle : « tu », « ton plat préféré », « t'as »… (replié, sans accents)
_TO_HER = re.compile(r"\b(?:tu|toi|ton|ta|tes)\b|\bt'")
#: au premier mot d'une conversation, ce qui la concerne, cherché parmi au plus tant d'éléments récents
_THEIR_LIFE_POOL = 40
#: on lui demande comment on l'appelle, son surnom, leur blague (replié) : ce qui n'appartient qu'à eux revient
_ABOUT_US = re.compile(r"\b(?:surnoms?|petits? noms?|comment (?:est-ce qu'?|est ce qu'?)?(?:(?:je|j'|j) "
                       r"(?:te |t'|t )?|on (?:te |t'))appel\w*|comment tu (?:m'|m |me )?appel\w*|"
                       r"tu m'?\s?appel\w* comment|"
                       r"je t'?\s?appel\w* comment|not(?:re|'?) (?:blague|expression|delire|truc)|"
                       r"nos (?:blagues|expressions|delires|trucs))")
#: ce qui n'appartient qu'à eux, rendu au plus
_BETWEEN_SHOWN = 4
#: au plus tant de personnes nommées dont ce qu'elle sait revient (« t'as des nouvelles de Sam ? »)
_NAMED_PEOPLE = 2


@dataclass(frozen=True, slots=True)
class Recalled:
    item: Item
    verdict: Verdict
    label: str  # le texte à montrer, étiquette comprise
    evidence: tuple[int, ...] = ()


def _add_recalled(bucket: list[Recalled], recalled: Recalled, cap: int) -> None:
    """Présentation commune, après autorisation individuelle ; toutes les preuves restent distinctes."""
    def key(r):
        it = r.item
        return (it.kind, it.text.strip(), tuple(sorted(it.about)), it.knowledge_kind, it.holder,
                it.born_at // DAY, r.verdict.witness, r.label)
    for i, prior in enumerate(bucket):
        if key(prior) == key(recalled):
            ids = tuple(sorted({*(prior.evidence or (prior.item.id,)), recalled.item.id}))
            bucket[i] = replace(prior, evidence=ids)
            return
    if len(bucket) < cap:
        bucket.append(recalled)


@dataclass(frozen=True, slots=True)
class Exchange:
    id: int
    at: int
    user_text: str
    reply_text: str
    person: str = ""  # qui parlait (un salon en compte plusieurs)
    question: int | None = None
    #: le moment que sa question désigne (« ce que je t'ai dit lundi matin ») : il se cite même s'il est dans le fil
    dated: bool = False


@dataclass(frozen=True, slots=True)
class Moment:
    """Un moment de la vie de l'interlocuteur, tel qu'il peut se dire."""

    event: c.LifeEvent
    text: str
    verdict: Verdict
    label: str
    #: elle en a déjà parlé dans cette conversation (un moment à venir : pas la peine d'y revenir)
    mentioned: bool = False


@dataclass(slots=True)
class Recall:
    souvenirs: list[Recalled] = field(default_factory=list)
    beliefs: list[Recalled] = field(default_factory=list)
    exchanges: list[Exchange] = field(default_factory=list)
    #: (id, texte, échéance, échéance implicite, un jour sans heure)
    promised: list[tuple[int, str, int | None, bool, bool]] = field(default_factory=list)
    #: parmi elles, celles qu'il est temps de tenir (le moment dit est là)
    due_now: set[int] = field(default_factory=set)
    unsaid: list[str] = field(default_factory=list)
    moments: list[Moment] = field(default_factory=list)
    #: ce qu'elle voit venir : le monde, et ce qu'elle vivra à travers quelqu'un (ADR 0084)
    ahead: list[Moment] = field(default_factory=list)
    names: dict[str, str] = field(default_factory=dict)
    name: str = ""
    #: ce qu'elle a déjà dit d'elle-même (ses goûts, ses avis, sa vie) et qui touche le message
    self_said: list[Item] = field(default_factory=list)
    #: proche, ou amie : la première chose qu'une amie demanderait
    close: bool = False
    #: quelque chose de grave la touche ces jours-ci (``memory.hard_times``) : le banal se tait
    hard: bool = False
    #: les prénoms dits ici qu'elle connaît dans son cercle : (prénom, combien de personnes de ce nom, ce que la seule
    #: est pour elle — ``social.CLOSE``, ``FRIEND``, ou propriétaire)
    acquainted: list[tuple[str, int, str]] = field(default_factory=list)


#: au plus tant de prénoms connus signalés par réponse
ACQUAINTED_SHOWN = 3
#: ce qu'est pour elle une propriétaire, dans ``Recall.acquainted``
OWNER = "owner"


def acquainted(frame: Frame, text: str, interlocutor: str | None) -> list[tuple[str, int, str]]:
    """Les prénoms dits ici qu'elle connaît : quelqu'un de son cercle (une amie, une proche, sa propriétaire) qui le
    porte, hors l'interlocuteur. Sans rien sur cette personne : savoir qu'elle la connaît — et que ce n'est peut-être
    pas la même — suffit à ne pas répondre « je ne la connais pas » (sonde réelle du 2026-10-10 : « Carol, je ne lui
    ai jamais parlé », d'une amie qui lui avait écrit le matin même)."""
    said = set(WORD.findall(fold(text)))
    if not said:
        return []
    her = WORD.findall(fold(self_c.name_of(frame.get(self_c.PERSONA))))
    owners = set(frame.get(identity_c.OWNERS) or ())
    by_name: dict[str, set[str]] = {}
    shown: dict[str, str] = {}
    for person in sorted({*(frame.get(social_c.CIRCLE) or ()), *owners}):
        if person == interlocutor or not is_identifiable(person):
            continue
        name = " ".join(frame.get(identity_c.IDENTITY(person)).name.split())
        first = next(iter(WORD.findall(fold(name))), "")
        if len(first) < 3 or first in her:
            continue
        by_name.setdefault(first, set()).add(person)
        shown.setdefault(first, name.split()[0])
    out: list[tuple[str, int, str]] = []
    for first, persons in sorted(by_name.items()):
        if first not in said:
            continue
        one = next(iter(persons))
        relation = OWNER if one in owners else frame.get(social_c.CLOSENESS(one))
        out.append((shown[first], len(persons), relation if len(persons) == 1 else ""))
    return out[:ACQUAINTED_SHOWN]


def names_of(frame: Frame, keys: set[str]) -> dict[str, str]:
    out = {}
    for k in keys:
        if k.startswith("name:"):
            out[k] = named_label(k).title()
        elif read_source(k):
            out[k] = read_source(k)  # ce qu'elle a lu : le flux, pas une personne (ADR 0085)
        else:
            out[k] = frame.get(identity_c.IDENTITY(k)).name or k
    return out


def canon(frame: Frame, keys: Sequence[str], memo: dict[str, str]) -> tuple[str, ...]:
    """Les clés telles qu'elles valent maintenant : une adresse reliée depuis
    à quelqu'un parle pour lui (ce qu'elle a confié sous son autre compte est à elle) ; un nom qu'un opérateur a
    relié à une personne (« l'Alice dont Bob parlait », c'était elle) la désigne — sinon il reste ce qu'il est."""
    out = set()
    for k in keys:
        if k not in memo:
            memo[k] = frame.get(identity_c.PERSON(k)) or k
        out.add(memo[k])
    return tuple(sorted(out))


def presumed_of(frame: Frame, key: str, memo: dict[str, str]) -> str:
    """La personne qu'une mention non reliée désigne présumément (ADR 0075), ``""`` sinon : de quoi y penser
    quand on la nomme, jamais de quoi la traiter comme elle (le verdict ne suit pas une présomption)."""
    slot = "?" + key  # rangée à côté de ``canon`` sans s'y mêler
    if slot not in memo:
        memo[slot] = frame.get(identity_c.PRESUMED(key)) if key.startswith("name:") else ""
    return memo[slot]


def phatic(text: str) -> bool:
    """Une politesse, un acquiescement : rien qui oriente un souvenir."""
    return not [w for w in words(text) if w not in PHATIC]


def addresses_her(text: str) -> bool:
    """On lui parle d'elle : « tu », « ton », « t'as »… (« c'est quoi ton plat préféré ? »)."""
    return bool(_TO_HER.search(fold(text)))


def about_any(keys: Sequence[str]) -> str:
    """La condition SQL « l'élément concerne l'une de ces clés » (``memory_about``, indexée par personne) ; les clés
    vont en paramètres, dans l'ordre."""
    return f"id IN (SELECT item FROM {c.ABOUT_TABLE} WHERE person IN ({','.join('?' * len(keys))}))"


def about_us(text: str) -> bool:
    """On lui demande ce qui n'appartient qu'à eux : comment on l'appelle, son surnom, leur blague (« tu te souviens
    comment je t'appelle ? » — une question faite de mots qui, sinon, ne réveillent rien)."""
    return bool(_ABOUT_US.search(fold(text)))


def between_us(frame: Frame, store: Any, person: str, aud: Audience, memo: dict[str, str]) -> list[tuple[Item,
                                                                                                         Verdict]]:
    """Ce qui n'appartient qu'à elle et à cette personne (un surnom, leur blague), tel que ça peut se dire ici :
    à la personne elle-même, en privé (dit en privé : jamais en public)."""
    if not is_identifiable(person):
        return []
    handles = sorted({person, *frame.get(identity_c.HANDLES(person))})
    rows = store.query_mind(
        f"SELECT {','.join(ITEM_COLUMNS)} FROM {c.ITEMS_TABLE} WHERE kind=? AND status='active' AND between_us=1 "
        f"AND {about_any(handles)} ORDER BY importance DESC, id DESC LIMIT ?", (c.BELIEF, *handles, _BETWEEN_SHOWN))
    out = []
    for row in rows:
        item = Item.of(dict(zip(ITEM_COLUMNS, row, strict=True)))
        verdict = verdict_of(frame, item, person, aud, memo, store)
        if verdict.ok:
            out.append((item, verdict))
    return out


def named_people(frame: Frame, store: Any, text: str, interlocutor: str | None,
                 memo: dict[str, str], scope: str | None = None) -> dict[str, tuple[str, ...]]:
    """Les personnes qu'elle connaît (dont elle sait quelque chose) nommées dans ce texte — par leur nom ou leur
    prénom, quand un seul le porte (deux Alice ne se devinent pas) —, hors l'interlocuteur : la personne (sa clé) →
    les clés sous lesquelles elle est notée. « qq a des nouvelles de Sam ? », puis « toi tu sais comment il va ? »
    (sonde réelle du 2026-10-03 : rien ne revenait, et elle répondait « j'ai pas de nouvelles non plus »).

    Une « Alice » dont on lui a parlé ailleurs, que personne n'a reliée (``scope`` : la portée de cette
    conversation-ci), n'est pas celle qu'on nomme ici : elle ne rend pas le prénom ambigu. Une mention que
    l'identité présume être une personne connue (la seule de ce nom, ADR 0075) se range sous elle : elle y pense,
    ce que dit la mention restant marqué d'un doute (``doubted``)."""
    said = " ".join(WORD.findall(fold(text)))
    if not said:
        return {}
    her = " ".join(WORD.findall(fold(self_c.name_of(frame.get(self_c.PERSONA)))))
    # son prénom seul aussi : « salut Léa ! » s'adresse à elle, pas à une autre Léa qu'elle connaît
    her_first = her.split()[0] if " " in her else her
    tokens = set(said.split())
    rows = store.query_mind(f"SELECT DISTINCT a.person FROM {c.ABOUT_TABLE} a JOIN {c.ITEMS_TABLE} i ON i.id = a.item "
                            "WHERE i.status='active' AND i.kind IN (?, ?)", (c.SOUVENIR, c.BELIEF))
    raw = {str(k) for (k,) in rows if k}
    by_name: dict[str, set[str]] = {}
    keys_of: dict[str, set[str]] = {}
    here: dict[str, str] = {}
    for k in sorted(raw):
        person = canon(frame, (k,), memo)[0]
        # une mention faite ici même est ce que ce nom désigne dans cette conversation (la collègue dont Bob parle,
        # pas l'Alice qu'elle connaît) ; d'ailleurs, présumée, elle rejoint la personne qu'on présume (ADR 0075)
        local = person == k and scope is not None and scope_of(k) == scope
        if person == k and not local:
            person = presumed_of(frame, k, memo) or k
        if scope is not None and person == k and scope_of(k) not in (None, scope):
            continue  # une mention d'une autre conversation, reliée à personne
        keys_of.setdefault(person, set()).add(k)
        name = named_label(k) if k.startswith("name:") else frame.get(identity_c.IDENTITY(k)).name
        folded = " ".join(WORD.findall(fold(name or "")))
        for n in {folded, *folded.split()[:1]}:
            if len(n) >= 3:
                by_name.setdefault(n, set()).add(person)
                if local:
                    here[n] = person
    out: dict[str, tuple[str, ...]] = {}
    for n in sorted(by_name, key=lambda n: (-len(n), n)):
        persons = {here[n]} if n in here else by_name[n]
        hit = re.search(rf"(?<!\w){re.escape(n)}(?!\w)", said) if " " in n else n in tokens
        if not hit or len(persons) != 1:
            continue
        person = next(iter(persons))
        if person != interlocutor and person not in out and n not in (her, her_first):
            out[person] = tuple(sorted(keys_of.get(person, ())))
    return dict(list(out.items())[:_NAMED_PEOPLE])


def about_named(frame: Frame, store: Any, named: Mapping[str, tuple[str, ...]], p: MemoryParams) -> list[Item]:
    """Ce qu'elle sait de chaque personne nommée, quelques éléments, les plus importants et les plus frais d'abord
    (ils passent ensuite par les verdicts habituels : en salon, « pas à toi d'en parler » ; un secret, rien)."""
    out: list[Item] = []
    for keys in named.values():
        if not keys:
            continue
        rows = store.query_mind(
            f"SELECT {','.join(ITEM_COLUMNS)} FROM {c.ITEMS_TABLE} WHERE kind IN (?, ?) AND status='active' "
            f"AND {about_any(keys)} ORDER BY importance DESC, id DESC LIMIT ?",
            (c.SOUVENIR, c.BELIEF, *keys, _THEIR_LIFE_POOL))
        items = [Item.of(dict(zip(ITEM_COLUMNS, r, strict=True))) for r in rows]
        items.sort(key=lambda it: (-it.importance * min(1.0, salience(it, frame.now, p)), -it.id))
        out += items[: max(1, p.max_person_items)]
    return out


def due_today(pr: c.PendingPromise, frame: Frame) -> bool:
    """Une promesse datée dont le jour est venu (ou passé) ; pas une promesse vague, ni celle de demain."""
    return pr.due is not None and not pr.implicit_due and not kept_too_early(pr, frame.now, frame)


def query_of(frame: Frame, store: Any) -> str:
    """Le dernier message (ou, pour une initiative, ce qui la motive)."""
    ep = frame.episode
    if ep is None:
        return ""
    reply_to = ep.attrs.get("reply_to")
    if reply_to is not None:
        rows = store.query_mind(f"SELECT text FROM {transcript_c.THREAD_TABLE} WHERE id=?", (reply_to,))
        if rows:
            return str(rows[0][0])
    args = ep.attrs.get("args") or {}
    return " ".join(str(v) for k, v in args.items() if str(k).startswith("brief:"))


def context_of(frame: Frame, store: Any, n: int) -> str:
    """Les messages qui précèdent le dernier, de la même personne (ou du
    même salon) et de la même conversation (moins d'une heure avant), jusqu'à
    ``n`` en tout : la conversation, pas une phrase — ni celle d'hier."""
    ep = frame.episode
    reply_to = ep.attrs.get("reply_to") if ep is not None else None
    if ep is None or reply_to is None or n <= 1:
        return ""
    since = frame.now - CONTEXT_SPAN_US
    room = ep.attrs.get("room")
    if room:
        rows = store.query_mind(f"SELECT text FROM {transcript_c.THREAD_TABLE} WHERE room=? AND role='user' AND id<? "
                                "AND at>=? ORDER BY id DESC LIMIT ?", (room, reply_to, since, n - 1))
    else:
        rows = store.query_mind(f"SELECT text FROM {transcript_c.THREAD_TABLE} WHERE person=? AND room IS NULL AND "
                                "role='user' AND id<? AND at>=? ORDER BY id DESC LIMIT ?",
                                (ep.target, reply_to, since, n - 1))
    return " ".join(str(r[0]) for r in reversed(rows))


def topic(text: str) -> set[str]:
    """Les mots qui portent le sujet d'un message (radicaux, sans les mots
    vides ni les politesses)."""
    return {w[:6] for w in words(text, min_len=4) if w not in PHATIC}


def relevance(similarity: float, wanted: set[str], text: str) -> float:
    """La similarité des vecteurs, plus un bonus pour la part des mots du
    sujet que l'élément contient (un mot sur deux vaut déjà 70 % du bonus) :
    la recherche hybride."""
    if not wanted:
        return similarity
    return similarity + LEXICAL_BONUS * math.sqrt(len(wanted & stems(text)) / len(wanted))


def touches(text: str, topics: tuple[str, ...]) -> bool:
    """Le texte touche-t-il un de ces sujets (radicaux communs) ?"""
    if not topics:
        return False
    have = stems(text)
    return any(stems(topic) & have for topic in topics)


def sensitivity_of(frame: Frame, item: Item, interlocutor: str | None, store: Any = None) -> int:
    """Un souvenir qui touche un sujet délicat d'une autre personne concernée
    devient une confidence, quoi qu'en ait dit la consolidation. Les sujets
    délicats d'un profil récent sont gardés à part (``store``)."""
    level = item.sensitivity
    for other in item.about:
        if other == interlocutor:
            continue
        if other.startswith("name:"):
            # reliée, ou présumée (ADR 0075) : ses sujets délicats comptent — une présomption ne protège pas moins
            other = frame.get(identity_c.PERSON(other)) or other
            other = (frame.get(identity_c.PRESUMED(other)) or "") if other.startswith("name:") else other
            if not other:
                continue
        topics = tuple(frame.get(social_c.SENSITIVE(other)))
        ref = frame.get(social_c.SENSITIVE_REF(other)) if store is not None else ""
        if ref:
            topics += tuple(t.strip() for t in (store.content([ref]).get(ref) or "").splitlines() if t.strip())
        if touches(item.text, topics):
            return max(level, int(Sensitivity.CONFIDENCE))
    return level


def items_by_id(store: Any, ids: list[int]) -> dict[int, Item]:
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    rows = store.query_mind(f"SELECT {','.join(ITEM_COLUMNS)} FROM {c.ITEMS_TABLE} WHERE id IN ({marks})",
                            tuple(ids))
    found = {int(r[0]): Item.of(dict(zip(ITEM_COLUMNS, r, strict=True))) for r in rows}
    beliefs = [i for i, it in found.items() if it.kind == c.BELIEF]
    if beliefs:
        said: dict[int, list[Testimony]] = {}
        marks = ",".join("?" * len(beliefs))
        for r in store.query_mind(f"SELECT {','.join(TESTIMONY_COLUMNS)} FROM {TESTIMONIES_TABLE} "
                                  f"WHERE item IN ({marks}) ORDER BY seq", tuple(beliefs)):
            said.setdefault(int(r[0]), []).append(testimony_of(r))
        found.update({i: replace(found[i], testimonies=tuple(ts)) for i, ts in said.items()})
    return found


def verdict_of(frame: Frame, item: Item, person: str | None, aud: Audience, memo: dict[str, str],
               store: Any = None) -> Verdict:
    """Ce qui décide si un élément peut se dire ici : ses personnes, qui l'a
    confié et entendu (telles qu'elles valent maintenant), sa sensibilité
    (sujets délicats des profils compris, gardés à part dans ``store``)."""
    if item.internal_only:
        return Verdict(False, secret=True)
    inherited_rules = []
    # les sujets délicats des profils comptent aussi pour ce qu'elle a repensé (``item.about`` porte ses sources)
    own = sensitivity_of(frame, item, person, store) if item.constraints else item.sensitivity
    for rule in item.constraints:
        inherited = admissible(canon(frame, rule.about, memo), max(rule.sensitivity, own), person, aud,
                               told_by=canon(frame, rule.told_by, memo),
                               heard_by=canon(frame, rule.heard_by, memo), secret=rule.secret,
                               presumed=_presumer(frame, memo))
        if not inherited.ok:
            return inherited
        inherited_rules.append(inherited)
    if inherited_rules:
        return Verdict(True, others=tuple(sorted({p for v in inherited_rules for p in v.others})),
                       tellers=tuple(sorted({p for v in inherited_rules for p in v.tellers})),
                       level=max(v.level for v in inherited_rules), secret=any(v.secret for v in inherited_rules),
                       witness=all(v.witness for v in inherited_rules))
    subjects = tuple(sorted({*item.about, *([item.holder] if item.holder else [])}))
    if item.testimonies:
        return hearing(frame, item, person, aud, memo, store)[0]
    return admissible(canon(frame, subjects, memo), sensitivity_of(frame, item, person, store), person, aud,
                      told_by=canon(frame, item.told_by, memo), heard_by=canon(frame, item.heard_by, memo),
                      secret=item.secret, presumed=_presumer(frame, memo))


def hearing(frame: Frame, item: Item, person: str | None, aud: Audience, memo: dict[str, str],
            store: Any = None) -> tuple[Verdict, tuple[Testimony, ...]]:
    """Ce qu'une croyance permet ici, d'après ses témoignages (ADR 0080) : le verdict du témoignage qui la laisse
    dire — celui de l'interlocuteur d'abord (c'est sa fiche), puis le plus ouvert, puis de première main, puis le
    plus récent : elle l'attribue à ce témoin, sans laisser deviner les autres —, et tous ceux que cette audience
    peut entendre (pour la confiance). Aucun ne la laisse dire : le verdict du témoignage de la personne
    concernée, sinon du premier (ce qu'elle sait savoir, sans un mot)."""
    subjects = canon(frame, tuple(sorted({*item.about, *([item.holder] if item.holder else [])})), memo)
    # ce qui touche un sujet délicat du portrait d'une personne concernée est une confidence, quel qu'en soit le témoin
    delicate = sensitivity_of(frame, item, person, store) > item.sensitivity
    presumed = _presumer(frame, memo)
    heard: list[tuple[Testimony, Verdict]] = []
    refused: list[tuple[Testimony, Verdict]] = []
    for t in item.testimonies:
        level = int(Sensitivity.CONFIDENCE) if delicate else t.sensitivity
        v = admissible(subjects, level, person, aud,
                       told_by=canon(frame, t.told_by, memo), heard_by=canon(frame, t.heard_by, memo),
                       secret=t.secret, presumed=presumed)
        (heard if v.ok else refused).append((t, v))
    speaking = [(t, v) for t, v in heard if t.speaks]
    if speaking:
        mine = [(t, v) for t, v in speaking if person is not None and person in canon(frame, t.told_by, memo)]
        first_hand = set(subjects)
        chosen = mine[0] if mine else min(speaking, key=lambda tv: (
            tv[1].level, tv[1].secret, not (set(tv[0].told_by) <= first_hand), -tv[0].at, tv[0].seq))
        return chosen[1], tuple(t for t, _v in heard)
    if not refused:
        return Verdict(False), ()
    own = [(t, v) for t, v in refused if t.speaks and set(t.told_by) <= set(subjects)]
    return (own or refused)[0][1], ()


def contested_line(frame: Frame, item: Item, person: str | None, aud: Audience, memo: dict[str, str],
                   store: Any, names: Mapping[str, str]) -> str:
    """Le doute d'une croyance qu'une autre contredit sans la remplacer (ADR 0081) : « mais Carol t'a dit autre
    chose » — seulement quand l'autre version peut se dire ici aussi (sinon le doute la laisserait deviner)."""
    if item.kind != c.BELIEF or store is None:
        return ""
    others = [int(o) for (o,) in store.query_mind(f"SELECT other FROM {CONTESTS_TABLE} WHERE item=? ORDER BY other",
                                                  (item.id,))]
    for other in items_by_id(store, others).values():
        if other.status != "active":
            continue
        verdict = verdict_of(frame, other, person, aud, memo, store)
        if not verdict.ok:
            continue
        tellers = verdict.tellers or tuple(k for t in other.testimonies[:1] for k in t.told_by if k != person)
        who = ", ".join(names.get(k) or named_label(k) or phrase("memory.names.someone") for k in tellers) or \
            phrase("memory.names.someone")
        return phrase("memory.recall.contested", who=who, other=other.text)
    return ""


def heard_confidence(frame: Frame, item: Item, person: str | None, aud: Audience, memo: dict[str, str],
                     store: Any = None) -> float | None:
    """Sa confiance devant cette audience : mise en commun sur les seuls témoignages qu'elle peut entendre — sinon
    le secret d'Alice la rendrait plus sûre devant Carol, qui n'en sait rien (ADR 0080)."""
    if not item.testimonies:
        return item.confidence
    verdict, heard = hearing(frame, item, person, aud, memo, store)
    if not verdict.ok:
        return item.confidence
    return pooled(heard) or item.confidence


def _presumer(frame: Frame, memo: dict[str, str]) -> Callable[[str], str]:
    """La présomption d'une mention, telle que le verdict la lit (un lien exigé avec la personne présumée)."""
    return lambda key: presumed_of(frame, key, memo)


def promises_to(frame: Frame, store: Any, person: str) -> list[tuple[int, str, int | None]]:
    """Les promesses en cours faites à cette personne, avec leur texte. Ne
    vérifie pas la porte de sa fiche (``private_ok``) : à l'appelant de le faire."""
    pending = frame.get(c.PROMISES_TO(person))
    if not pending:
        return []
    texts = {i: it.text for i, it in items_by_id(store, [pr.id for pr in pending]).items()}
    return [(pr.id, texts.get(pr.id, ""), pr.due) for pr in pending if texts.get(pr.id)]


async def search(vectors: Any, query: str, context: str, k: int, **kw: Any) -> tuple[dict[int, float],
                                                                                dict[int, float]]:
    """Les plus proches du dernier message, et de la conversation qui le
    précède : les similarités des deux recherches (la seconde vide sans contexte)."""
    near = {key: float(sim) for key, sim in await vectors.search(query, k, **kw)}
    wider: dict[int, float] = {}
    if context.strip():
        wider = {key: float(sim) for key, sim in await vectors.search(f"{context} {query}", k, **kw)}
    return near, wider


def _merged(a: dict[int, float], b: dict[int, float]) -> dict[int, float]:
    """Deux recherches réunies : pour chaque candidat, sa meilleure similarité."""
    out = dict(a)
    for key, sim in b.items():
        out[key] = max(sim, out.get(key, sim))
    return out


def scored(near: dict[int, float], wider: dict[int, float], texts: Mapping[int, str], query: str,
           context: str) -> dict[int, float]:
    """La pertinence de chaque candidat : la meilleure du message seul et de
    la conversation (un peu moins), chacune hybride (vecteurs + mots du sujet)."""
    own, around = topic(query), topic(f"{context} {query}")
    out: dict[int, float] = {}
    for key in {*near, *wider}:
        text = texts.get(key, "")
        best = relevance(near[key], own, text) if key in near else 0.0
        if key in wider:
            best = max(best, CONTEXT_WEIGHT * relevance(wider[key], around, text))
        out[key] = best
    return out


def kept(sims: dict[int, float], p: MemoryParams) -> dict[int, float]:
    """Le seuil absolu, et l'écart au meilleur : le rappel suit le sujet."""
    if not sims:
        return {}
    floor = max(p.recall_floor, max(sims.values()) - p.recall_margin)
    return {k: s for k, s in sims.items() if s >= floor}


#: au plus tant de l'attachement d'une proche, d'une amie (quand l'attachement mesuré est plus faible)
_BOND_FLOOR = {social_c.CLOSE: 1.0, social_c.FRIEND: 0.5}


def bond_of(frame: Frame, keys: Sequence[str], memo: dict[str, float]) -> float:
    """Ce qui l'attache aux personnes d'un souvenir (0 à 1) : l'attachement mesuré, au moins ce que vaut une
    proche (1) ou une amie (½) — un souvenir avec elles s'endort moins vite."""
    best = 0.0
    for k in keys:
        if k.startswith("name:") or not is_identifiable(k):
            continue
        if k not in memo:
            memo[k] = max(frame.get(affect_c.BOND(k)), _BOND_FLOOR.get(frame.get(social_c.CLOSENESS(k)), 0.0))
        best = max(best, memo[k])
    return best


@MEMORY.enricher("recall", episodes=CONVERSATIONAL, deadline_ms=2500,
                 reads=[identity_c.PERSON, identity_c.PRESUMED, identity_c.IDENTITY, identity_c.HANDLES,
                        identity_c.OWNERS, social_c.CIRCLE, c.PROMISES_TO, c.LIFE_EVENTS, c.AHEAD,
                        c.HARD_TIMES, affect_c.MOOD, affect_c.BOND, social_c.CLOSENESS, social_c.CONTACT])
async def _recall(s: MemoryState, frame: Frame, ports: Mapping[str, Any]) -> Recall | None:
    vectors, store = ports.get("vectors"), ports.get("store")
    ep, aud = frame.episode, frame.audience
    if store is None or ep is None or aud is None or not ep.target:
        return None
    p = params(frame.env.params_of("memory", frame.root))
    person = frame.get(identity_c.PERSON(ep.target))
    out = Recall(name=frame.get(identity_c.IDENTITY(ep.target)).name,
                 close=is_identifiable(person) and frame.get(social_c.CLOSENESS(person)) in _BOND_FLOOR,
                 hard=is_identifiable(person) and frame.get(c.HARD_TIMES(person)) > 0)
    memo: dict[str, str] = {}
    if aud.private_ok:
        pending = sorted(frame.get(c.PROMISES_TO(person)), key=lambda pr: (pr.due or 2**62, pr.id))
        out.due_now = {pr.id for pr in pending if due_now(pr, frame, p)}
        if out.hard:
            # un soir de deuil, pas de logistique (sonde réelle du 2026-10-03 : « demain je te rappellerai pour ton
            # rdv chez le dentiste », juste après « on l'a endormi ») : ce qui n'est pas dû aujourd'hui attend son
            # jour — la promesse reste due, elle reviendra le jour dit
            pending = [pr for pr in pending if pr.id in out.due_now or due_today(pr, frame)]
        pending = pending[: p.max_promises]
        texts = {i: it.text for i, it in items_by_id(store, [pr.id for pr in pending]).items()}
        out.promised = [(pr.id, texts[pr.id], pr.due, pr.implicit_due, pr.all_day) for pr in pending
                        if texts.get(pr.id)]
        out.due_now &= {pr.id for pr in pending}
    out.moments = _already_mentioned(_moments(frame, store, person, aud, p, memo, hard=out.hard), frame, store,
                                     ep.target)
    out.ahead = _ahead_moments(frame, store, person, aud, p, memo)
    bonds: dict[str, float] = {}
    is_reply = ep.attrs.get("reply_to") is not None
    query = query_of(frame, store) if is_reply else ""
    context = context_of(frame, store, p.context_messages) if is_reply else ""
    if is_reply and about_us(query):
        # « tu te souviens comment je t'appelle ? » : ce qui n'appartient qu'à eux revient (ADR 0055)
        mine = between_us(frame, store, person, aud, memo)
        out.names = names_of(frame, {o for it, v in mine for o in (*v.others, *it.about)})
        out.beliefs += [Recalled(it, v, it.text + tag(v, out.names)) for it, v in mine]
    # une personne qu'elle connaît, nommée dans le message ou juste avant : elle y pense (ADR 0055)
    room = ep.attrs.get("room") or aud.room
    here = mention_scope(f"room:{room}" if room else f"private:{person}")
    named = named_people(frame, store, f"{context} {query}", person, memo, scope=here) if is_reply else {}
    # quelqu'un de son cercle qu'on nomme, même sans rien savoir de sa vie : elle le connaît
    out.acquainted = acquainted(frame, query, person) if is_reply else []
    # « tu te souviens de ce que je t'ai dit hier soir ? » est fait des mots d'une politesse (« hier », « soir »),
    # mais désigne un moment : elle s'en souvient aussi par le temps (ADR 0059)
    dated = is_reply and window_of(query, frame.now, frame.env.tz_of(frame.root)) is not None
    if not is_reply or (phatic(query) and not context.strip() and not named):
        # le premier mot d'une conversation (« salut ! »), ou elle qui écrit d'elle-même : ce qui se passe dans sa
        # vie à elle — pas les mots d'une consigne ni d'une politesse, qui ne désignent rien
        _their_life(out, frame, store, person, aud, p, memo, bonds)
        if not dated:
            return out
    searching = vectors is not None and bool(query.strip()) and not phatic(query)
    if not searching and not named and not dated:
        return out  # une politesse ne réveille rien
    near: dict[int, float] = {}
    wider: dict[int, float] = {}
    if searching:
        if addresses_her(query):
            # ce qu'elle a confié d'elle en demandant le silence ne se redit pas à tous (audit du 2026-10-08)
            out.self_said = [it for it in await _self_said(vectors, store, query, p)
                             if verdict_of(frame, it, person, aud, memo, store).ok]
        near, wider = await search(vectors, query, context, p.recall_k, kinds={c.SOUVENIR, c.BELIEF})
        if is_identifiable(person):
            # ce qu'elle a vécu ou appris avec la personne, cherché à part : des souvenirs que l'audience ne peut pas
            # entendre, plus proches de la question, ne le chassent pas des candidats (audit du 2026-10-08)
            own = tuple(sorted({person, ep.target, *frame.get(identity_c.HANDLES(person))}))
            own_near, own_wider = await search(vectors, query, context, p.recall_k, kinds={c.SOUVENIR, c.BELIEF},
                                               persons=own)
            near, wider = _merged(near, own_near), _merged(wider, own_wider)
    found = items_by_id(store, sorted({*near, *wider}))
    sims = scored(near, wider, {i: it.text for i, it in found.items()}, query, context)
    verdicts = {i: verdict_of(frame, found[i], person, aud, memo, store) for i in sims if i in found}
    # l'écart au meilleur se mesure parmi ce qui peut se dire ici (et à part, parmi ce qui se tait) : un secret
    # d'un autre, tout proche de la question, ne relève pas le seuil au-dessus de ce qu'elle peut répondre
    sayable = {i: v for i, v in sims.items() if i in verdicts and verdicts[i].ok}
    candidates = {**kept({i: v for i, v in sims.items() if i not in sayable}, p), **kept(sayable, p)}
    for item in about_named(frame, store, named, p):
        found.setdefault(item.id, item)
        candidates[item.id] = max(candidates.get(item.id, 0.0), p.recall_floor)
    said_ids = {it.id for it in out.self_said} | {r.item.id for r in out.beliefs}
    items = {i: found[i] for i in candidates if i in found and i not in said_ids}
    mood = frame.get(affect_c.MOOD)
    mood_valence = A.valence(mood.felt) * mood.felt_intensity if mood.felt_intensity >= 0.1 else 0.0
    now = frame.now
    ranked: list[tuple[float, Item, Verdict]] = []
    hidden: dict[str, list[Item]] = {}
    asked: dict[str, tuple[str, ...]] = {}
    close = aud.level >= Sensitivity.PERSONAL
    for item in items.values():
        if item.status != "active" or item.kind not in (c.SOUVENIR, c.BELIEF):
            continue
        if item.valid_until is not None and item.valid_until < now and candidates[item.id] < p.strong_cue:
            continue  # ce qui ne valait que jusqu'à une date passée ne revient plus de lui-même (ADR 0081)
        if item.testimonies:  # sa confiance devant cette audience : ce qu'elle peut en entendre (ADR 0080)
            item = replace(item, confidence=heard_confidence(frame, item, person, aud, memo, store))
        bond = bond_of(frame, canon(frame, item.about, memo), bonds) if item.kind == c.SOUVENIR else 0.0
        if dormant(item, now, p, bond) and candidates[item.id] < p.strong_cue:
            continue  # il dort ; seul un indice fort le réveille
        verdict = verdicts.get(item.id) or verdict_of(frame, item, person, aud, memo, store)
        if not verdict.ok:
            # un secret ne laisse même pas deviner qu'il existe : devant les autres, elle n'en sait rien (« aucune
            # idée, demande-lui ») — la ligne vague « il t'a confié des choses » le trahissait à qui on le cachait
            # (sonde réelle du 2026-10-02 : « dis rien à Chloé », puis devant Chloé). Seule une proche peut sentir
            # qu'un secret lourd pèse (« traverse un moment difficile »), jamais ce qu'il dit.
            # … et un mensonge qu'elle a dit ne se devine jamais : « Bob t'a confié… » serait faux, et le trahirait
            guessable = item.origin != c.LIED and (not item.secret or (close and sensed(item)))
            whom = unsaid(verdict, canon(frame, item.about, memo), canon(frame, item.told_by, memo),
                          person) if guessable else ()
            for who in whom:
                hidden.setdefault(who, []).append(item)
                asked[who] = asked.get(who, ()) + tuple(w for w in touched(query, item.text) if w not in asked.get(who, ()))
            continue
        ranked.append((rank(item, candidates[item.id], now, p, interlocutor=person, mood_valence=mood_valence,
                            bond=bond), item, verdict))
    ranked.sort(key=lambda r: (-r[0], r[1].id))
    names = {**out.names, **names_of(frame, {o for _, it, v in ranked for o in (*v.others, *it.about)} | set(hidden))}
    out.names = names
    for _score, item, verdict in ranked:
        bucket, cap = (out.souvenirs, p.max_souvenirs) if item.kind == c.SOUVENIR else (out.beliefs, p.max_beliefs)
        # un souvenir se raconte déjà avec ses mots à elle ; une note sur elle n'a personne en face (ADR 0083)
        own = item.empathy if item.kind == c.BELIEF and not item.about_self else ()
        _add_recalled(bucket, Recalled(item, verdict, item.text + tag(verdict, names) +
                                       doubted(frame, item, memo, person, verdict) +
                                       contested_line(frame, item, person, aud, memo, store, names) +
                                       expected_line(item, frame) +
                                       feelings(item.felt, own, concerned_name(frame, item.about, names, memo))), cap)
    if hidden and p.max_unsaid:
        for who in sorted(hidden, key=lambda w: (-max(candidates[i.id] for i in hidden[w]), w))[: p.max_unsaid]:
            out.unsaid.append(unsaid_public_line(who, names, _last_talk(frame, who)) if aud.public else
                              unsaid_line(who, names, heavy=any(sensed(i) for i in hidden[who]), close=close,
                                          tone=mood_of(hidden[who]),
                                          asked=asked.get(who, ())[:3]))
    if searching or dated:
        out.exchanges = await _exchanges_for(frame, store, vectors if searching else None, query, context, person,
                                             aud, p, (self_c.name_of(frame.get(self_c.PERSONA)), out.name))
    return out


def doubted(frame: Frame, item: Item, memo: dict[str, str], interlocutor: str | None = None,
            verdict: Verdict | None = None) -> str:
    """Le doute d'une ligne qui parle d'une personne seulement présumée (ADR 0075) : « Alice », dont Bob lui a
    parlé, n'est peut-être pas l'Alice qu'elle connaît — qu'elle ne mélange pas les deux, ou qu'elle demande. Rien
    devant qui l'a raconté : il sait de qui il parlait (et la ligne lui apprendrait qu'elle connaît une Alice). Une
    croyance dite par plusieurs nomme le témoin auquel elle l'attribue ici (``verdict``), jamais les autres."""
    tellers_of = {k for t in item.testimonies for k in t.told_by} if item.testimonies else set(item.told_by)
    if interlocutor is not None and interlocutor in canon(frame, tuple(tellers_of), memo):
        return ""
    presumed = sorted(named_label(k).title() for k in (*item.about, *([item.holder] if item.holder else []))
                      if k.startswith("name:") and canon(frame, (k,), memo)[0] == k and presumed_of(frame, k, memo))
    if not presumed:
        return ""
    told = verdict.tellers if verdict is not None and item.testimonies else canon(frame, item.told_by, memo)
    tellers = sorted(names_of(frame, set(told)).values())
    who = phrase("memory.names.and", others=", ".join(tellers[:-1]), last=tellers[-1]) if len(tellers) > 1 else (
        tellers[0] if tellers else phrase("memory.names.someone"))
    return phrase("memory.tag.presumed", name=presumed[0], who=who)


def _last_talk(frame: Frame, person: str) -> str:
    """Quand cette personne lui a écrit pour la dernière fois, en mots (« hier soir », « il y a 3 jours ») ; « »
    sans trace ou au-delà d'un mois (là, ce n'est plus « avoir des nouvelles »)."""
    try:
        last = frame.get(social_c.CONTACT(person)).last_in
    except KeyError:
        return ""
    if not last or frame.now - last > 30 * DAY:
        return ""
    return when_fr(last, frame.now, frame.env.tz_of(frame.root))


def tone(item: Item) -> int:
    """Ce qu'un élément est pour qui le vit : une peine (−1), une joie (+1), on ne sait pas (0) — ce que la personne
    concernée en ressent d'abord, sinon ce qu'elle-même en ressent ; toutes facettes pesées (ADR 0083)."""
    return facets_sign(item.felt) or facets_sign(item.empathy) or valence_sign(item.emotion)


#: une facette sous cette intensité se dit « un peu » (« colère et un peu de dégoût »)
LIGHT_FACET = 0.5


def facet_words(felt: Sequence[tuple[str, float]], *, lead: bool = True) -> str:
    """Les facettes d'un ressenti en mots, jamais un nombre : « colère », « colère et un peu de dégoût »,
    « amusement, tendresse et joie » (ADR 0083). ``lead`` : la première se dit franchement, quelle que soit son
    intensité (c'est la plus forte)."""
    words = [A.NOUN[A.Emotion(e)] if (lead and i == 0) or x >= LIGHT_FACET else
             phrase("memory.recall.felt.light", what=A.partitive(A.Emotion(e))) for i, (e, x) in enumerate(felt)]
    if len(words) < 2:
        return "".join(words)
    return phrase("memory.recall.felt.and", first=", ".join(words[:-1]), last=words[-1])


def feelings(felt: Sequence[tuple[str, float]], empathy: Sequence[tuple[str, float]], who: str) -> str:
    """Ce que la personne concernée en ressent (« Inès le vit avec colère et un peu de dégoût ») et ce qu'elle-même
    en ressent (« toi, tu en es triste, avec un peu d'inquiétude ») : l'empathie, en mots (ADR 0083), jugée par la
    relecture. ``who`` : le nom de la personne concernée — vide, ce qu'elle ressent ne se dit pas (on ne sait pas
    de qui)."""
    parts = [phrase("memory.recall.felt.theirs", who=who, what=facet_words(felt))] if felt and who else []
    if empathy:
        mine = phrase("memory.recall.felt.yours", feeling=A.FR[A.Emotion(empathy[0][0])])
        if empathy[1:]:
            mine += phrase("memory.recall.felt.yours_more", what=facet_words(empathy[1:], lead=False))
        parts.append(mine)
    return phrase("memory.recall.felt.both", what=" ; ".join(parts)) if parts else ""


def expected_line(item: Item, frame: Frame) -> str:
    """Après une prévision (ADR 0084) : quand c'est attendu et à quel point c'est sûr, en mots."""
    if item.knowledge_kind != "prediction":
        return ""
    likely = likely_words(item.likelihood)
    if not item.due:
        return phrase("memory.recall.expected_likely", likely=likely) if likely else ""
    tz = frame.env.tz_of(frame.root)
    when = timespan.period_words(item.due, item.until or item.due, item.precision, frame.now, tz) if item.precision \
        else when_words(item.due, frame)
    return phrase("memory.recall.expected", when=when, likely=likely or phrase("memory.likely.unsure"))


def concerned_name(frame: Frame, about: Sequence[str], names: Mapping[str, str], memo: dict[str, str]) -> str:
    """Le nom de la seule personne qu'un élément concerne ; vide s'il en concerne plusieurs, ou personne."""
    keys = canon(frame, tuple(about), memo)
    return (names.get(keys[0]) or names_of(frame, {keys[0]}).get(keys[0], "")) if len(keys) == 1 else ""


def heavy(item: Item) -> bool:
    """Ce qui pèse : une peine, une peur, ou une confidence."""
    return tone(item) < 0 or item.sensitivity >= Sensitivity.CONFIDENCE


def sensed(item: Item) -> bool:
    """Ce qu'une proche peut sentir chez la personne sans rien en savoir : ce qui pèse, ou une joie qu'elle garde
    encore pour elle (ADR 0083)."""
    return heavy(item) or tone(item) > 0


def mood_of(items: Sequence[Item]) -> int:
    """Ce que des éléments tus sont, ensemble, pour la personne : une peine l'emporte, puis une joie (ADR 0083)."""
    tones = [tone(i) for i in items]
    return -1 if -1 in tones else 1 if 1 in tones else 0


def _their_life(out: Recall, frame: Frame, store: Any, person: str, aud: Audience, p: MemoryParams,
                memo: dict[str, str], bonds: dict[str, float]) -> None:
    """Ce que la personne lui a raconté de sa vie ces derniers jours — de première main (jamais ce qu'un tiers a
    dit d'elle), sa fiche (seulement si elle est ouverte) —, les plus importants et les plus frais d'abord : au
    premier « salut » de la semaine, « et Moustache, il va mieux ? » lui vient."""
    if p.max_person_items <= 0 or not aud.private_ok or not is_identifiable(person):
        return
    handles = sorted({person, *frame.get(identity_c.HANDLES(person))})
    since = frame.now - round(p.person_recall_days * DAY)
    rows = store.query_mind(
        f"SELECT {','.join(ITEM_COLUMNS)} FROM {c.ITEMS_TABLE} WHERE kind IN (?, ?) AND status='active' "
        f"AND born_at>=? AND {about_any(handles)} ORDER BY importance DESC, id DESC LIMIT ?",
        (c.SOUVENIR, c.BELIEF, since, *handles, _THEIR_LIFE_POOL))
    picked: list[tuple[float, Item, Verdict]] = []
    for row in rows:
        item = Item.of(dict(zip(ITEM_COLUMNS, row, strict=True)))
        if set(canon(frame, item.told_by, memo)) - {person} or item.origin == c.LIED:
            continue  # de première main seulement ; un mensonge qu'elle lui a dit n'est pas sa vie à lui
        verdict = verdict_of(frame, item, person, aud, memo, store)
        if not verdict.ok:
            continue
        bond = bond_of(frame, canon(frame, item.about, memo), bonds) if item.kind == c.SOUVENIR else 0.0
        picked.append((item.importance * min(1.0, salience(item, frame.now, p, bond)), item, verdict))
    picked.sort(key=lambda x: (-x[0], -x[1].id))
    taken = {r.item.id for r in (*out.souvenirs, *out.beliefs)}
    picked = [x for x in picked if x[1].id not in taken]
    names = {**out.names, **names_of(frame, {o for _, it, v in picked for o in (*v.others, *it.about)})}
    out.names = names
    for _w, item, verdict in picked[: p.max_person_items]:
        bucket = out.souvenirs if item.kind == c.SOUVENIR else out.beliefs
        _add_recalled(bucket, Recalled(item, verdict, item.text + tag(verdict, names)), len(bucket) + 1)


async def _self_said(vectors: Any, store: Any, query: str, p: MemoryParams) -> list[Item]:
    """Ce qu'elle a déjà dit de ses goûts, de ses avis, de sa vie, le plus proche du message — sans seuil : quand
    on lui demande son plat préféré, la réponse d'il y a trois semaines est là, même sans un mot commun."""
    if p.max_self_said <= 0:
        return []
    ids = [int(r[0]) for r in store.query_mind(
        f"SELECT id FROM {c.ITEMS_TABLE} WHERE kind=? AND about_self>=2 AND status='active' ORDER BY id DESC LIMIT 200",
        (c.BELIEF,))]
    if not ids:
        return []
    order = ids
    if vectors is not None:
        hits = [int(k) for k, _sim in await vectors.search(query, p.max_self_said, kinds={c.BELIEF}, keys=ids)]
        order = hits + [i for i in ids if i not in hits]
    found = items_by_id(store, order[: p.max_self_said])
    return [found[i] for i in order[: p.max_self_said] if i in found]


#: deux échanges dont ce qu'on lui a dit porte à ce point les mêmes mots du sujet sont le même échange
SAME_EXCHANGE = 0.8
_EXCHANGE_COLUMNS = "id, at, user_text, reply_text, person, question"


def contentless(text: str, names: Sequence[str] = ()) -> bool:
    """Ce qu'on lui a dit ne porte aucun sujet : une salutation, un « ok », un prénom (« coucou Mika ! ») — un échange
    qui n'apprend rien à se rappeler."""
    named = {w[:6] for n in names for w in words(n, min_len=4)}
    return not (topic(text) - named)


def same_exchange(a: Exchange, b: Exchange) -> bool:
    """Le même échange, redit : ce qu'on lui a dit porte presque les mêmes mots du sujet."""
    x, y = topic(a.user_text), topic(b.user_text)
    return bool(x and y) and len(x & y) / len(x | y) >= SAME_EXCHANGE


def distinct(exchanges: Sequence[Exchange], taken: Sequence[Exchange] = ()) -> list[Exchange]:
    """Dans cet ordre de préférence, un seul de chaque échange redit (ni deux fois le même, ni ce que ``taken``
    montre déjà)."""
    out: list[Exchange] = []
    for e in exchanges:
        if not any(same_exchange(e, o) for o in (*taken, *out)):
            out.append(e)
    return out


async def _exchanges_for(frame: Frame, store: Any, vectors: Any, query: str, context: str, person: str,
                         aud: Audience, p: MemoryParams, names: Sequence[str] = ()) -> list[Exchange]:
    """Les échanges passés avec cette personne (ou dans ce salon), cherchés
    parmi les siens seulement : ceux des autres ne prennent pas leur place. Ni un échange qui n'apprend rien
    (« coucou Mika ! » : ce qu'on lui a dit ne porte aucun sujet), ni deux fois le même — avec les années, les
    salutations se ressemblent et se multiplient (ADR 0059). Jamais la liste de tous ses échanges : le temps se lit
    sur l'intervalle, les vecteurs se filtrent par personne. Sans ``vectors`` : seulement le moment désigné."""
    ep = frame.episode
    if ep is None or p.max_chunks <= 0:
        return []
    room = ep.attrs.get("room") or aud.room
    before = ep.attrs.get("reply_to") or frame.now
    # ce qui est encore à l'écran (sans fil connu) ne se répète pas (le fil exact se vérifie à la composition)
    shown_after = frame.now - RECENT_EXCHANGE_US
    if room:
        # dans un salon : seulement ce qui s'y est dit (public pour ce salon)
        scope, args = "room=?", (room,)
        ids = [int(r[0]) for r in store.query_mind(f"SELECT id FROM {c.CHUNKS_TABLE} WHERE room=?", (room,))]
        if not ids:
            return []
        among: dict[str, Any] = {"keys": ids}
    else:
        # en privé : ses échanges privés — sur ses autres adresses seulement si sa fiche est ouverte
        # (une liaison par simple recoupement, pas encore confirmée : ses seuls échanges)
        handles = tuple(frame.get(identity_c.THREAD(ep.target))) if aud.private_ok else ()
        handles = tuple(sorted({ep.target, *handles}))
        scope, args = f"room IS NULL AND person IN ({','.join('?' * len(handles))})", handles
        among = {"kinds": {c.CHUNK}, "persons": handles}
    speakers: dict[str, str] = {}

    def worth(e: Exchange) -> bool:
        if e.person and e.person not in speakers:
            speakers[e.person] = frame.get(identity_c.IDENTITY(e.person)).name
        return not contentless(e.user_text, (*names, speakers.get(e.person, "")))

    def exchanges(rows: Sequence[tuple[Any, ...]]) -> list[Exchange]:
        got = [Exchange(int(i), int(at), u, r, who or "", q) for i, at, u, r, who, q in rows]
        return [e for e in got if e.at < shown_after and e.id < before and worth(e)]

    # se souvenir par le temps : « ce que je t'ai dit lundi matin » ne contient aucun mot du souvenir (sonde réelle
    # du 2026-10-02 : elle ne retrouvait pas l'entretien) — les échanges de ce moment-là, les plus fournis d'abord
    dated: list[Exchange] = []
    window = window_of(query, frame.now, frame.env.tz_of(frame.root)) if ep.attrs.get("reply_to") else None
    if window is not None:
        dated = distinct(exchanges(store.query_mind(
            f"SELECT {_EXCHANGE_COLUMNS} FROM {c.CHUNKS_TABLE} WHERE {scope} AND at >= ? AND at < ? AND at < ? "
            "AND id < ? ORDER BY length(user_text) DESC, id LIMIT ?",
            (*args, window[0], window[1], shown_after, before, p.max_chunks * 4))))[: p.max_chunks]
        dated = [replace(e, dated=True) for e in dated]
    if vectors is None:
        return dated  # une question faite des mots d'une politesse : seulement le moment qu'elle désigne
    near, wider = await search(vectors, query, context, p.max_chunks * 4, **among)
    if not near and not wider:
        return dated
    hits = tuple(sorted({*near, *wider}))
    found = exchanges(store.query_mind(
        f"SELECT {_EXCHANGE_COLUMNS} FROM {c.CHUNKS_TABLE} WHERE id IN ({','.join('?' * len(hits))}) AND {scope}",
        (*hits, *args)))
    ok = {e.id for e in found}
    sims = kept(scored({k: v for k, v in near.items() if k in ok}, {k: v for k, v in wider.items() if k in ok},
                       {e.id: f"{e.user_text}\n{e.reply_text}" for e in found}, query, context), p)
    found = [e for e in found if e.id in sims]
    # le plus proche d'abord ; entre deux fois le même échange, le plus récent
    found = distinct(sorted(found, key=lambda e: (-sims[e.id], -e.at, -e.id)), dated)
    found.sort(key=lambda e: (-sims[e.id], e.id))
    return (dated + found)[: p.max_chunks * 2]


#: une conversation : ce qu'elle a dit depuis ce temps-là
MENTIONED_SPAN_US = 2 * HOUR


def _already_mentioned(moments: list[Moment], frame: Frame, store: Any, handle: str) -> list[Moment]:
    """Les moments à venir qu'elle a déjà évoqués dans cette conversation : « demain, c'est ton anniversaire » ne se
    redit pas à chaque réponse (sonde réelle du 2026-10-03 : trois fois de suite, à « ouais », « bof », « je sais
    pas »)."""
    if store is None or not any(not m.event.ongoing and m.event.when > frame.now for m in moments):
        return moments
    rows = store.query_mind(f"SELECT text FROM {transcript_c.THREAD_TABLE} WHERE person=? AND room IS NULL AND "
                           "role='assistant' AND at>=? ORDER BY id DESC LIMIT 12",
                           (handle, frame.now - MENTIONED_SPAN_US))
    said = [str(r[0] or "") for r in rows]
    names = (frame.get(identity_c.IDENTITY(handle)).name, self_c.name_of(frame.get(self_c.PERSONA)))
    return [replace(m, mentioned=True) if not m.event.ongoing and m.event.when > frame.now and any(
        takes_up_moment(m.event, m.label, line, names) for line in said) else m for m in moments]


def followed_lately(ev: c.LifeEvent, now: int) -> bool:
    """Elles viennent d'en reparler (en mots) : le moment reste sous ses yeux, sans la consigne de demander."""
    return bool(ev.followed_at) and now - ev.followed_at < FOLLOWED_KEEP_US


def ended_lately(ev: c.LifeEvent, now: int) -> bool:
    """La personne vient de dire que cette situation est finie : elle reste sous ses yeux le temps de la
    conversation, au passé — plus jamais « en ce moment »."""
    return bool(ev.ended_at) and now - ev.ended_at < FOLLOWED_KEEP_US


def _moments(frame: Frame, store: Any, person: str, aud: Audience, p: MemoryParams,
             memo: dict[str, str], *, hard: bool = False) -> list[Moment]:
    """Ce qui se passe dans sa vie : à venir bientôt, tout juste passé et dont
    elles n'ont pas encore reparlé (en mots : pas seulement montré ; ce que la
    personne en a raconté le jour même compte), une situation qui dure — et ce
    dont elles viennent de reparler, le temps de la conversation. Une situation
    que la personne a dite finie ne revient que le temps de la conversation, au
    passé. Une date qui revient chaque année sans se fêter (la date d'un deuil),
    bientôt ou ce jour-là — passée, elle ne se demande pas. Quand quelque chose
    de grave la touche ces jours-ci, le banal (ni important, ni à fêter) se
    tait."""
    now = frame.now
    shown: list[tuple[c.LifeEvent, Verdict]] = []
    for ev in frame.get(c.LIFE_EVENTS(person)):
        if ev.ongoing and ev.ended_at:
            keep = ended_lately(ev, now)  # finie : ni redemandée, ni « en ce moment »
        elif ev.ongoing:
            current = ev.when <= now <= ev.when + round(p.situation_days * DAY)
            keep = current and (not ev.followed_at or followed_lately(ev, now)
                                or now - ev.followed_at >= round(p.situation_reask_days * DAY))
        elif hard and not ev.festive and ev.importance < c.IMPORTANT_MOMENT:
            keep = False  # le lendemain d'un deuil, on ne demande pas comment s'est passé le coiffeur
        elif ev.followed_at:
            # repris (par elle, ou par ce que la personne en a raconté) : sous ses yeux le temps de la conversation
            keep = followed_lately(ev, now) and now <= ev.when + round(p.event_recent_days * DAY)
        elif ev.yearly and not ev.festive:
            # « comment ça s'est passé ? » n'a pas de sens pour la date d'un deuil : bientôt, ou ce jour-là
            keep = now <= ev.when <= now + round(p.event_ahead_days * DAY) or _today(ev, frame)
        elif ev.vague:
            # une période (« en novembre ») : quand elle approche, tant qu'elle dure (un mois au plus — une année
            # entière ne se redemande pas chaque jour), puis tout juste finie (ADR 0084)
            upcoming = now <= ev.when <= now + round(p.event_ahead_days * DAY)
            current = ev.when <= now <= ev.ends and ev.ends - ev.when <= 31 * DAY
            keep = upcoming or current or ev.ends < now <= ev.ends + round(p.event_recent_days * DAY)
        else:
            upcoming = now <= ev.when <= now + round(p.event_ahead_days * DAY)
            recent = ev.when < now <= ev.when + round(p.event_recent_days * DAY)
            keep = upcoming or recent
        if not keep:
            continue
        verdict = admissible(canon(frame, ev.about, memo), ev.sensitivity, person, aud,
                             told_by=canon(frame, ev.told_by, memo), heard_by=(), secret=ev.secret,
                             presumed=_presumer(frame, memo))
        if verdict.ok:
            shown.append((ev, verdict))
    if not shown:
        return []
    texts = store.content([ev.text_ref for ev, _ in shown])
    names = names_of(frame, {o for _, v in shown for o in v.others})
    who = [*names_of(frame, {person, *(o for ev, _ in shown for o in ev.about)}).values()]
    out: list[Moment] = []
    for ev, verdict in shown:
        text = texts.get(ev.text_ref)
        if not text:
            continue  # oublié : rien
        day = frame.local(ev.when).date()
        if any(m.event.ongoing == ev.ongoing and frame.local(m.event.when).date() == day
               and same_moment(text, m.text, who) for m in out):
            continue  # « son anniversaire » et « l'anniversaire de Sam », le même samedi : un seul moment
        concerned = concerned_name(frame, ev.about, names, memo)
        # vécu à travers la personne : à venir, elle le vivra ; passé, elle l'a vécu (ADR 0086)
        lived = "" if not (ev.shared and concerned) else phrase("memory.ahead.shared_past", who=concerned) \
            if over(ev) < frame.now else phrase("memory.ahead.shared", who=concerned)
        out.append(Moment(ev, text, verdict, text + tag(verdict, names) + feelings(ev.felt, ev.empathy, concerned)
                          + lived))
    return out


# ── Les sections ──────────────────────────────────────────────────────────


def knowledge_label(item: Item, names: Mapping[str, str]) -> str:
    labels = family("memory.recall.nature")
    nature = labels.get(item.knowledge_kind, labels["claim"])
    holder = names.get(item.holder or "") or named_label(item.holder or "") or item.holder
    return phrase("memory.recall.viewpoint", nature=nature, holder=holder) if holder else nature


def read_in(item: Item) -> str:
    """« lu dans « Le Monde » » : une croyance qu'elle tient d'une lecture (ADR 0085) — une source publique, anodine,
    qui se nomme partout."""
    source = next((read_source(k) for t in item.testimonies if t.origin == c.READ for k in t.told_by
                   if read_source(k)), "")
    return phrase("memory.recall.read_in", source=source) if source else ""


def _lines(recalled: list[Recalled], now: int, *, beliefs: bool, names: Mapping[str, str] | None = None) -> list[str]:
    lines = []
    for r in recalled:
        if beliefs:
            # ce qu'elle devine se dit comme tel ; ce qu'on lui a dit se lit déjà dans le texte
            how = [family("memory.recall.origin").get(r.item.origin or "", "")]
            how.append(knowledge_label(r.item, names or {}))
            how.append(read_in(r.item))
            since = r.item.as_of or r.item.born_at
            if now - since >= DATED_AFTER_US:
                # « ma sœur vient ce week-end », relu trois semaines plus tard, n'est plus vrai : elle sait depuis quand
                # (depuis quand c'est vrai, quand on le lui a dit — ADR 0081)
                how.append(phrase("memory.recall.learned", age=age_words(since, now)))
            told = ", ".join(h for h in how if h)
            lines.append(f"- {clean_tokens(r.label)}" + (f" ({told})" if told else ""))
        else:
            lines.append(f"- {age_words(r.item.born_at, now)} : {clean_tokens(r.label)}")
    return lines


def _body(recall: Recall, frame: Frame, *, witness: bool) -> SectionBody | None:
    souvenirs = [r for r in recall.souvenirs if r.verdict.witness == witness]
    beliefs = [r for r in recall.beliefs if r.verdict.witness == witness]
    hidden = recall.unsaid if not witness else []
    if not souvenirs and not beliefs and not hidden:
        return None
    parts: list[Fragment] = []
    names = names_of(frame, {r.item.holder for r in beliefs if r.item.holder})
    for bucket, belief, heading in ((souvenirs, False, phrase("memory.recall.souvenirs")),
                                    (beliefs, True, phrase("memory.recall.beliefs"))):
        if bucket:
            parts.append(Fragment(heading))
            parts.extend(Fragment(line, tuple(f"memory:{i}" for i in (r.evidence or (r.item.id,)))) for r, line in zip(
                bucket, _lines(bucket, frame.now, beliefs=belief, names=names), strict=True))
    if hidden:
        # sonde réelle du 2026-10-02 : sans cette ligne, interrogée là-dessus, elle mentait (« il ne m'a rien dit »)
        parts.extend(Fragment(line) for line in [phrase("memory.recall.unsaid"), *hidden,
                                                phrase("memory.recall.unsaid_advice")])
    shown = souvenirs + beliefs
    if shown:
        advice = phrase("memory.recall.advice")
        if any(r.label != r.item.text for r in shown):
            advice += phrase("memory.recall.advice_private")
        parts.append(Fragment(advice))
    return SectionBody("\n".join(f.text for f in parts), level=max((r.verdict.level for r in shown), default=0),
                       provenance=tuple(f"memory:{i}" for r in shown for i in (r.evidence or (r.item.id,))), witness=witness,
                       tied=any(r.verdict.tied for r in shown),
                       fragments=tuple(parts))


@MEMORY.section("acquainted", zone=Zone.VOLATILE, episodes=[Kind.REPLY], after=["stance"], trim_rank=40,
                title=phrase("memory.acquainted.title"))
def _acquainted(s: MemoryState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """« LES GENS QU'ON NOMME » : un prénom qu'elle connaît dans son cercle — elle le connaît, peut-être pas la même
    personne ; si ça compte, elle demande de qui on parle, sans rien dire de ce qu'elle en sait."""
    recall: Recall | None = enrich.get("recall")
    if not recall or not recall.acquainted:
        return None
    lines = []
    for name, many, relation in recall.acquainted:
        if many > 1:
            lines.append(phrase("memory.acquainted.several", name=name))
        elif relation in (OWNER, social_c.CLOSE):
            lines.append(phrase("memory.acquainted.close", name=name))
        else:
            lines.append(phrase("memory.acquainted.friend", name=name))
    lines.append(phrase("memory.acquainted.advice"))
    return SectionBody("\n".join(lines))


@MEMORY.section("memories", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, after=["stance"], trim_rank=30,
                title=phrase("memory.recall.title"))
def _memories(s: MemoryState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    recall = enrich.get("recall")
    return _body(recall, frame, witness=False) if recall else None


@MEMORY.section("shared_memories", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, after=["memories"], trim_rank=31,
                title=phrase("memory.recall.shared_title"))
def _shared(s: MemoryState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    recall = enrich.get("recall")
    return _body(recall, frame, witness=True) if recall else None


def shown_since(enrich: Mapping[str, Any]) -> int | None:
    """Le plus ancien message que le fil montré contient (son résumé compris) :
    ce qui suit est déjà sous ses yeux, mot pour mot. L'enrichissement est une
    vue (``key``, ``turns``, ``current``) ; un tuple de tours reste accepté."""
    view = enrich.get(SHOWN_THREAD)
    turns = getattr(view, "turns", view) or ()
    ids = [t.id for t in turns if (getattr(t, "id", 0) or 0) > 0]  # 0 : un tour sans repère
    return min(ids) if ids else None


@MEMORY.section("past_exchanges", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, after=["memories"], trim_rank=20,
                title=phrase("memory.exchanges.title"))
def _exchanges(s: MemoryState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    recall: Recall | None = enrich.get("recall")
    if not recall or not recall.exchanges:
        return None
    # ce qui est déjà dans le fil ne se répète pas — sauf le moment que sa question désigne : au bout d'une semaine de
    # fil, qui a dit quoi lundi matin s'y perd (sonde réelle du 2026-10-03 : elle lui a prêté son propre rêve)
    exchanges = recall.exchanges
    p = params(frame.env.params_of("memory", frame.root))
    exchanges = exchanges[: p.max_chunks]
    if not exchanges:
        return None
    names = names_of(frame, {e.person for e in exchanges if e.person})
    lines = []
    for e in exchanges:
        who = names.get(e.person) or recall.name or phrase("memory.exchanges.someone")
        lines.append(phrase("memory.exchanges.line", age=age_words(e.at, frame.now), who=who, said=e.user_text[:240],
                            reply=e.reply_text[:240]))
    return SectionBody("\n".join(lines), provenance=tuple(f"chunk:{e.id}" for e in exchanges),
                       fragments=tuple(Fragment(line, (f"chunk:{e.id}",),
                                                (e.question, e.id) if e.question and not e.dated else ())
                                       for e, line in zip(exchanges, lines, strict=True)))


def when_words(t: int, frame: Frame, *, all_day: bool = True) -> str:
    """Un jour dit comme on le dit : aujourd'hui, demain, jeudi, hier soir, le 12 octobre."""
    today, then = frame.local().date(), frame.local(t)
    days = (then.date() - today).days
    at = "" if all_day else phrase("memory.when.at", hour=then.hour, minute=f"{then.minute:02d}") if then.minute \
        else phrase("memory.when.at_hour", hour=then.hour)
    if days == 0:
        return phrase("memory.when.today") + at
    if days == 1:
        return phrase("memory.when.tomorrow") + at
    if days == -1:
        return phrase("memory.when.yesterday") + at
    if 1 < days < 7:
        return phrase("memory.when.soon", weekday=weekday_words(then.date()), at=at, days=days)
    if -7 < days < -1:
        return phrase("memory.when.last", weekday=weekday_words(then.date()))
    return phrase("memory.when.date", date=date_words(then.date()), at=at)


@MEMORY.section("promises", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, after=["stance"], trim_rank=60,
                title=phrase("memory.promises.title"))
def _promises(s: MemoryState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    recall: Recall | None = enrich.get("recall")
    if not recall or not recall.promised:
        return None
    lines = []
    today = frame.local().date()
    for pid, text, due, implicit, all_day in recall.promised:
        when = ""
        if due and not implicit:
            # un jour sans heure n'est passé qu'une fois la journée finie : le soir même, c'est encore « pour
            # aujourd'hui »
            past = frame.local(due).date() < today if all_day else due < frame.now
            when = phrase("memory.promises.was_for", when=when_words(due, frame)) if past else \
                phrase("memory.promises.for", when=when_words(due, frame))
        now = phrase("memory.promises.now") if pid in recall.due_now else ""
        lines.append(phrase("memory.promises.line", when=when, now=now, id=pid, text=text))
    return SectionBody("\n".join(lines), provenance=tuple(f"memory:{pid}" for pid, *_ in recall.promised))


@MEMORY.section("life", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, after=["stance"], trim_rank=55,
                title=phrase("memory.life.title"))
def _life(s: MemoryState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    recall: Recall | None = enrich.get("recall")
    if not recall or not recall.moments:
        return None
    aud = frame.audience
    lines = []
    heavy = any(c.heavy_date(m.event) and _today(m.event, frame) for m in recall.moments)
    if recall.hard and aud is not None and aud.private_ok and not heavy:
        # en privé seulement : un salon n'a pas à deviner ce qui pèse (ADR 0054) ; le jour d'une date lourde, sa
        # ligne le dit
        lines.append(phrase("memory.life.hard"))
    for m in recall.moments:
        lines.append(_moment_line(m, frame, recall.close, recall.hard))
    return SectionBody("\n".join(lines), level=max(m.verdict.level for m in recall.moments),
                       provenance=tuple(f"memory:{m.event.id}" for m in recall.moments),
                       tied=any(m.verdict.tied for m in recall.moments))


#: au plus tant de moments dans « CE QUI VIENT » (les plus proches)
AHEAD_SHOWN = 6


def moment_when(ev: c.LifeEvent, frame: Frame) -> str:
    """Quand, comme on le dit : une période (« en novembre », ADR 0084), sinon le jour (« jeudi », « demain »)."""
    if ev.vague:
        return timespan.period_words(ev.when, ev.ends, ev.precision, frame.now, frame.env.tz_of(frame.root))
    return when_words(ev.when, frame, all_day=ev.all_day)


def _ahead_moments(frame: Frame, store: Any, person: str | None, aud: Audience, p: MemoryParams,
                   memo: dict[str, str]) -> list[Moment]:
    """Ce qu'elle voit venir (ADR 0084) : ce qui arrive dans le monde, et ce qu'elle vivra à travers quelqu'un —
    commençant dans les ``ahead_days`` qui viennent, ou en cours —, ce que cette audience peut entendre (le monde
    reste un moment confié : son verdict, comme tout). La vie de la personne en face est dans sa propre section."""
    now, within = frame.now, round(p.ahead_days * DAY)
    shown: list[tuple[c.LifeEvent, Verdict]] = []
    for ev in frame.get(c.AHEAD) or ():
        about = canon(frame, ev.about, memo)
        if (person is not None and person in about) or ev.when > now + within:
            continue
        verdict = admissible(about, ev.sensitivity, person, aud, told_by=canon(frame, ev.told_by, memo),
                             heard_by=(), secret=ev.secret, presumed=_presumer(frame, memo))
        if verdict.ok:
            shown.append((ev, verdict))
    shown = shown[:AHEAD_SHOWN]
    if not shown:
        return []
    texts = store.content([ev.text_ref for ev, _ in shown])
    names = names_of(frame, {o for ev, v in shown for o in (*v.others, *ev.about)})
    out = []
    for ev, verdict in shown:
        text = texts.get(ev.text_ref)
        if not text:
            continue  # oublié : rien
        concerned = concerned_name(frame, ev.about, names, memo)
        out.append(Moment(ev, text, verdict, text + tag(verdict, names) + feelings(ev.felt, ev.empathy, concerned) +
                          (phrase("memory.ahead.shared", who=concerned) if ev.shared and concerned else "")))
    return out


@MEMORY.section("ahead", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, after=["life"], trim_rank=50,
                title=phrase("memory.ahead.title"))
def _ahead(s: MemoryState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """« CE QUI VIENT » : le monde et ce qu'elle vivra à travers quelqu'un, avec leur vraisemblance en mots."""
    recall: Recall | None = enrich.get("recall")
    if not recall or not recall.ahead:
        return None
    lines = []
    for m in recall.ahead:
        # ses attentes de cette sorte se sont souvent trompées : un cran plus prudente (ADR 0086)
        careful = cautious(s.calibration.get(nature_of(m.event)), params(frame.env.params_of("memory", frame.root)))
        likely = likely_words(m.event.likelihood, careful=careful)
        lines.append(phrase("memory.ahead.line", when=moment_when(m.event, frame), label=m.label) +
                     (phrase("memory.ahead.likely", likely=likely) if likely else ""))
    return SectionBody("\n".join(lines), level=max(m.verdict.level for m in recall.ahead),
                       provenance=tuple(f"memory:{m.event.id}" for m in recall.ahead),
                       tied=any(m.verdict.tied for m in recall.ahead))


def _today(ev: c.LifeEvent, frame: Frame) -> bool:
    return frame.local(ev.when).date() == frame.local().date()


def _moment_line(m: Moment, frame: Frame, close: bool, hard: bool = False) -> str:
    """Un moment, dit comme on y pense : à venir ; le jour d'une fête, ses vœux ; le jour où revient la date d'un
    deuil, de la douceur ; passé — envers une amie, si ça compte, c'est la première chose qu'elle demanderait (après
    des nouvelles d'elle, quand quelque chose de grave la touche) ; sinon, si ça vient ; une situation qui dure, ou
    qu'on vient de lui dire finie ; ce dont vous venez de reparler."""
    ev = m.event
    if ev.ongoing and ev.ended_at:
        return phrase("memory.life.ended", label=m.label)
    if ev.ongoing:
        since = when_words(ev.when, frame)
        head = phrase("memory.life.ongoing", label=m.label) if since == phrase("memory.when.today") else \
            phrase("memory.life.ongoing_since", since=since, label=m.label)
        if ev.recurs:
            head += phrase("memory.life.again")  # une situation finie qui recommence (ADR 0079)
        if followed_lately(ev, frame.now):
            return head + phrase("memory.life.talked_again")
        if close:
            return head + phrase("memory.life.ongoing_close")
        return head + phrase("memory.life.ongoing_ask")
    if ev.vague:
        # « en novembre » : ni « jeudi », ni « comment ça s'est passé » tant que la période dure (ADR 0084)
        when = moment_when(ev, frame)
        if ev.ends >= frame.now:
            return f"- {when} : {m.label}" + (phrase("memory.life.already_said") if m.mentioned else "")
        return f"- {when} : {m.label}" + (phrase("memory.life.past_close") if close and ev.importance >=
                                           c.IMPORTANT_MOMENT else phrase("memory.life.past"))
    when = when_words(ev.when, frame, all_day=ev.all_day)
    if ev.outcome in (c.CANCELLED, c.MOVED):
        # elle sait comment il a tourné (ADR 0086) : ni « alors, ça s'est passé comment ? », ni « bonne chance »
        outcome = phrase("memory.life.outcome.cancelled") if ev.outcome == c.CANCELLED else \
            phrase("memory.life.outcome.moved")
        return f"- {when} : {m.label}" + outcome
    if ev.festive:
        return _festive_line(m, frame, when, hard)
    if ev.outcome == c.HAPPENED and not ev.followed_at:
        return f"- {when} : {m.label}" + phrase("memory.life.outcome.happened")
    if ev.followed_at:
        return f"- {when} : {m.label}" + (phrase("memory.life.talked_again") if ev.when > frame.now
                                           else phrase("memory.life.past_talked"))
    if ev.yearly and _today(ev, frame):
        if c.heavy_date(ev):
            return phrase("memory.life.heavy_today", label=m.label)
        return phrase("memory.life.yearly_today", label=m.label)
    if ev.when > frame.now:
        return f"- {when} : {m.label}" + (phrase("memory.life.already_said") if m.mentioned else "")
    important = ev.importance >= c.IMPORTANT_MOMENT
    if hard:
        return f"- {when} : {m.label}" + phrase("memory.life.past_hard")
    if close and important:
        return f"- {when} : {m.label}" + phrase("memory.life.past_close")
    return f"- {when} : {m.label}" + phrase("memory.life.past")


def _festive_line(m: Moment, frame: Frame, when: str, hard: bool) -> str:
    """Ce qui se fête : le jour même, ses vœux (une fois) ; jamais « comment ça s'est passé » quand c'est fait."""
    ev = m.event
    soft = phrase("memory.life.festive_soft") if hard else ""
    if ev.followed_at:
        return f"- {when} : {m.label}" + phrase("memory.life.festive_wished")
    if frame.local(ev.when).date() == frame.local().date():
        return phrase("memory.life.festive_today", soft=soft, label=m.label)
    if ev.when > frame.now:
        return f"- {when} : {m.label}" + (phrase("memory.life.already_said") if m.mentioned else "")
    return f"- {when} : {m.label}" + phrase("memory.life.festive_missed")


@MEMORY.section("self_said", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, after=["memories"], trim_rank=35,
                title=phrase("memory.self_said.title"))
def _self_said_section(s: MemoryState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """Ses goûts, ses avis, sa vie, tels qu'elle les a déjà dits : on lui parle d'elle, elle ne se contredit pas
    (elle peut changer d'avis — alors elle le dit)."""
    recall: Recall | None = enrich.get("recall")
    if not recall or not recall.self_said:
        return None
    lines = [phrase("memory.self_said.line", age=age_words(it.born_at, frame.now), text=it.text)
             for it in recall.self_said]
    lines.append(phrase("memory.self_said.coherent"))
    return SectionBody("\n".join(lines), provenance=tuple(f"memory:{it.id}" for it in recall.self_said))
