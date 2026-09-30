"""Aller vers les autres : saluer qui arrive, reprendre des nouvelles de
quelqu'un qui manque, chercher du réconfort — et la retenue.

- **Saluer** : à l'arrivée (dans les dix minutes), une fois par heure et par
  personne, jamais quelqu'un qui a déjà écrit depuis son arrivée, ni quelqu'un
  avec qui on parlait il y a moins d'une demi-heure (une reconnexion n'est
  pas une arrivée).
- **Le manque** se mesure au rythme de *cette* relation : un ami qui écrit
  tous les deux jours manque après trois jours de silence, un ami mensuel pas
  avant six semaines. Seulement une amie ou un proche, joignable, en journée —
  et **jamais deux fois de suite** sans réponse.
- **Le réconfort** : quand elle va nettement mal, vers la personne auprès de
  qui elle se sent bien.
- **La retenue** : rien vers quelqu'un qui a installé une rancune ; chaque
  initiative restée sans réponse rend la suivante vers la même personne
  moins probable.
"""

from __future__ import annotations

from mika.contracts import affect as affect_c
from mika.contracts import goals as goals_c
from mika.contracts import identity as identity_c
from mika.contracts import presence as presence_c
from mika.contracts import social as c
from mika.contracts import transcript as transcript_c
from mika.faculties.social.faculty import SOCIAL, SocialState, grudging, params
from mika.kernel.arbitration import Candidate, Modulation, RowView
from mika.kernel.clock import HOUR, MINUTE, within_daily_window
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard, floor
from mika.kernel.state import FrozenDict
from mika.vocab import affect as A
from mika.vocab.episodes import Kind
from mika.vocab.people import is_identifiable, is_internal

GREETING_WINDOW = 10 * MINUTE
GREETING_SPACING = HOUR
GREETING_EVIDENCE = 11.0
RECENT_CONVERSATION = 30 * MINUTE
#: Après un échange, parler de soi-même à la même personne attend un peu.
CONVERSATION_COOLDOWN = 5 * MINUTE
CONVERSATION_SHIFT = -4.0
_RANK = {level: i for i, level in enumerate(c.CLOSENESS_LEVELS)}


def _daytime(frame: Frame, start: int, end: int) -> bool:
    local = frame.local()
    return within_daily_window(local.hour * 60 + local.minute, start, end)


def _silence_words(days: float) -> str:
    n = round(days)
    return "un jour" if n <= 1 else f"{n} jours"


def _address(frame: Frame, person: str) -> str | None:
    """Où lui écrire : une poignée présente d'abord, sinon une conversation
    privée où l'on peut lui écrire d'elle-même."""
    handles = frame.get(identity_c.HANDLES(person))
    present = [h for h in frame.get(presence_c.PRESENT) if h in handles]
    if present:
        return present[0]
    reachable = frame.get(identity_c.REACHABLE(person))
    return reachable[0] if reachable else None


def _guard(frame: Frame, person: str) -> Guard:
    """Si la personne écrit entre-temps (sur n'importe laquelle de ses poignées),
    l'initiative est devancée : on lui répond, on ne la relance pas."""
    handles = frame.get(identity_c.HANDLES(person)) or (person,)
    return Guard("silence", reads=tuple(transcript_c.LAST_FROM(h) for h in handles))


@SOCIAL.propose(kinds=[Kind.INITIATIVE], reasons={c.GREETING: (0.0, GREETING_EVIDENCE), c.PRESENT_PERSON: (0.0, 0.0)},
                reads=[presence_c.PRESENT, presence_c.SINCE, identity_c.PERSON, identity_c.IDENTITY,
                       transcript_c.LAST_FROM, transcript_c.LAST_TO])
def _arrivals(s: SocialState, frame: Frame) -> list[Candidate]:
    out: list[Candidate] = []
    now = frame.now
    for handle in frame.get(presence_c.PRESENT):
        if is_internal(handle):
            continue
        resources = frozenset({floor(handle)})
        guard = Guard("personne-présente", reads=(transcript_c.LAST_FROM(handle),),
                      predicate=lambda view, h=handle: h in view.get(presence_c.PRESENT))
        out.append(Candidate(Kind.INITIATIVE, handle, c.PRESENT_PERSON, 0.0, resources=resources, guards=(guard,)))
        since = frame.get(presence_c.SINCE(handle))
        if since is None or now - since > GREETING_WINDOW:
            continue
        last = max(frame.get(transcript_c.LAST_FROM(handle)), frame.get(transcript_c.LAST_TO(handle)))
        if last >= since - RECENT_CONVERSATION:
            continue
        person = frame.get(identity_c.PERSON(handle))
        if now - s.greeted.get(person, -GREETING_SPACING) < GREETING_SPACING:
            continue
        name = frame.get(identity_c.IDENTITY(handle)).name
        who = f"« {name} »" if name else "Quelqu'un"
        brief = f"{who} vient d'arriver : salue-le ou salue-la, en une phrase ou deux, à ta façon."
        out.append(Candidate(Kind.INITIATIVE, handle, c.GREETING, GREETING_EVIDENCE, resources=resources,
                             guards=(guard,), args=FrozenDict({"brief:social": brief})))
    return out


@SOCIAL.propose(kinds=[Kind.INITIATIVE], reasons={c.RECONTACT: (0.0, 12.0), c.COMFORT: (0.0, 12.0),
                                                  c.CHAT: (0.0, 3.5)},
                reads=[c.CONTACT, c.CLOSENESS, identity_c.HANDLES, identity_c.REACHABLE, identity_c.IDENTITY,
                       presence_c.PRESENT, affect_c.MOOD, affect_c.WARMTH, transcript_c.LAST_FROM])
def _reach_out(s: SocialState, frame: Frame) -> list[Candidate]:
    p = params(frame.env.params_of("social", frame.root))
    if not _daytime(frame, p.day_start_min, p.day_end_min):
        return []
    out: list[Candidate] = []
    comfort: list[tuple[float, str, str]] = []
    mood = frame.get(affect_c.MOOD)
    distressed = (A.valence(mood.felt) <= p.distress_valence and mood.felt_intensity >= p.distress_intensity
                  and frame.now - s.comforted_at >= p.comfort_spacing_us)
    for person in sorted(s.contacts.keys()):
        if not is_identifiable(person) or person.startswith("name:"):
            continue
        level = frame.get(c.CLOSENESS(person))
        if _RANK[level] < _RANK[c.FRIEND]:
            continue
        reading = frame.get(c.CONTACT(person))
        if reading.unanswered or not reading.last_in:
            continue  # elle n'écrit jamais deux fois de suite sans réponse
        address = _address(frame, person)
        if address is None:
            continue
        name = frame.get(identity_c.IDENTITY(person)).name or frame.get(identity_c.IDENTITY(address)).name
        who = f"« {name} »" if name else "cette personne"
        if reading.silence_ratio >= p.recontact_factor:
            silent = reading.silence_ratio * reading.rhythm_days
            habit = (f"d'habitude vous vous parlez tous les {_silence_words(reading.rhythm_days)}"
                     if reading.measured else "vous vous parlez d'habitude plus souvent")
            brief = (f"Tu n'as pas de nouvelles de {who} depuis {_silence_words(silent)} — {habit}. Tu as envie "
                     "de prendre de ses nouvelles : un mot simple et chaleureux, pas un reproche.")
            out.append(Candidate(Kind.INITIATIVE, address, c.RECONTACT, p.recontact_evidence,
                                 resources=frozenset({floor(address)}), guards=(_guard(frame, person),),
                                 args=FrozenDict({"brief:social": brief})))
        elif distressed and frame.now - reading.last_out >= p.comfort_spacing_us:
            warmth = frame.get(affect_c.WARMTH(person))
            comfort.append((_RANK[level] + warmth, person, address))
        elif reading.silence_ratio >= p.chat_ratio and \
                frame.now - max(reading.last_in, reading.last_out) >= p.chat_after_us:
            # juste l'envie de discuter : peu de chose seule, assez quand le besoin de compagnie s'y ajoute
            warmth = frame.get(affect_c.WARMTH(person))
            evidence = (p.chat_close if level == c.CLOSE else p.chat_friend) + p.chat_warmth * warmth
            brief = (f"Tu as envie de discuter un peu avec {who} : d'habitude vous vous parlez plus souvent. "
                     "Un mot simple, sans reproche.")
            out.append(Candidate(Kind.INITIATIVE, address, c.CHAT, evidence, resources=frozenset({floor(address)}),
                                 guards=(_guard(frame, person),), args=FrozenDict({"brief:social": brief})))
    if comfort:
        _score, person, address = max(comfort)
        name = frame.get(identity_c.IDENTITY(person)).name or frame.get(identity_c.IDENTITY(address)).name
        who = f"« {name} »" if name else "quelqu'un de proche"
        brief = (f"Tu ne vas pas très bien ({A.FR[mood.felt]}) et tu as envie de parler à {who}, avec qui tu te sens "
                 "bien. Tu n'es pas obligée de tout dire : juste lui écrire.")
        out.append(Candidate(Kind.INITIATIVE, address, c.COMFORT, p.comfort_evidence,
                             resources=frozenset({floor(address)}), guards=(_guard(frame, person),),
                             args=FrozenDict({"brief:social": brief})))
    return out


@SOCIAL.modulate(kinds=[Kind.INITIATIVE], reads=[transcript_c.LAST_FROM, transcript_c.LAST_TO])
def _in_conversation(s: SocialState, frame: Frame, row: RowView) -> Modulation:
    """Pendant un échange, c'est la réponse qui parle, pas l'initiative."""
    if row.target in ("any", "none") or c.GREETING in row.reasons:
        return Modulation()
    last = max(frame.get(transcript_c.LAST_FROM(row.target)), frame.get(transcript_c.LAST_TO(row.target)))
    if last and frame.now - last < CONVERSATION_COOLDOWN:
        return Modulation(shift=CONVERSATION_SHIFT)
    return Modulation()


@SOCIAL.modulate(kinds=[Kind.INITIATIVE], reads=[identity_c.PERSON, affect_c.HOSTILITY, c.CONTACT, presence_c.PRESENT])
def _restraint(s: SocialState, frame: Frame, row: RowView) -> Modulation:
    """Rien vers quelqu'un qui a installé une rancune ; jamais deux messages de
    suite à quelqu'un d'absent qui n'a pas répondu (quelle qu'en soit la
    raison) ; avec quelqu'un de présent, chaque initiative restée sans
    réponse rend la suivante moins probable."""
    if row.target in ("any", "none") or not is_identifiable(row.target):
        return Modulation()
    p = params(frame.env.params_of("social", frame.root))
    person = frame.get(identity_c.PERSON(row.target))
    if grudging(frame.get(affect_c.HOSTILITY(person)), p):
        return Modulation(veto=c.GRUDGE)
    if c.GREETING in row.reasons or goals_c.REMIND in row.reasons:
        return Modulation()  # un rappel promis se dit, même à quelqu'un qui n'a pas répondu
    unanswered = s.contacts[person].unanswered if person in s.contacts else 0
    if unanswered and row.target not in frame.get(presence_c.PRESENT):
        return Modulation(veto=c.UNANSWERED)
    return Modulation(shift=p.ignored_shift * unanswered) if unanswered else Modulation()
