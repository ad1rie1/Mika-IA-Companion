"""Aller vers les autres : saluer qui arrive, reprendre des nouvelles de
quelqu'un qui manque, chercher du réconfort — et la retenue.

- **Saluer** : à l'arrivée (dans les dix minutes), une fois par heure et par
  personne, jamais quelqu'un qui a déjà écrit depuis son arrivée, ni quelqu'un
  avec qui on parlait il y a moins d'une demi-heure. Une reconnexion n'est
  pas une arrivée : il faut une absence d'au moins une heure (``away_us``) —
  un onglet rechargé, une coupure, un redémarrage d'elle ne font pas revenir
  quelqu'un qui n'était pas parti.
- **Le manque** se mesure au rythme de *cette* relation : un ami qui écrit
  tous les deux jours manque après trois jours de silence, un ami mensuel pas
  avant six semaines. Seulement une amie ou un proche, joignable, en journée.
- **Longtemps après** : une amie partie sans plus répondre, des mois plus
  tard (ou passé un moment qu'elle lui avait annoncé), elle prend de ses
  nouvelles une fois, doucement — puis plus rien tant qu'elle n'a pas écrit
  (ADR 0058).
- **Le réconfort** : quand elle va nettement mal, vers la personne auprès de
  qui elle se sent bien.
- **La retenue** : rien d'ordinaire vers quelqu'un qui a installé une
  rancune, pas même une salutation. Mais tenir parole (un rappel promis,
  ``agency.OWED``) ne dépend pas de ce qu'elle ressent, et prévenir (un mail
  important, un projet confié qui bloque, ``agency.INFORMS``) n'est que
  décalé. Ne pas harceler quelqu'un qui ne répond pas (plus d'initiative
  ordinaire tant qu'il n'a pas écrit, une seule relance douce après un long
  délai) est la règle du budget d'initiatives (``agency``, ADR 0033), qui vaut
  pour toutes les raisons à la fois.
"""

from __future__ import annotations

from mika.contracts import affect as affect_c
from mika.contracts import agency as agency_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import presence as presence_c
from mika.contracts import social as c
from mika.contracts import transcript as transcript_c
from mika.faculties.social.faculty import SOCIAL, SocialParams, SocialState, been_friends, grudging, params
from mika.kernel.arbitration import Candidate, Modulation, RowView
from mika.kernel.clock import DAY, HOUR, MINUTE, within_daily_window
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


def _habit_words(days: float) -> str:
    n = round(days)
    return "tous les jours" if n <= 1 else f"tous les {n} jours"


def _address(frame: Frame, person: str) -> str | None:
    """Où lui écrire : une adresse présente d'abord, sinon une conversation
    privée où l'on peut lui écrire d'elle-même."""
    handles = frame.get(identity_c.HANDLES(person))
    present = [h for h in frame.get(presence_c.PRESENT) if h in handles]
    if present:
        return present[0]
    reachable = frame.get(identity_c.REACHABLE(person))
    return reachable[0] if reachable else None


def _guard(frame: Frame, person: str) -> Guard:
    """Si la personne écrit entre-temps (sur n'importe laquelle de ses adresses),
    l'initiative est devancée : on lui répond, on ne la relance pas."""
    handles = frame.get(identity_c.HANDLES(person)) or (person,)
    return Guard("silence", reads=tuple(transcript_c.LAST_FROM(h) for h in handles))


@SOCIAL.propose(kinds=[Kind.INITIATIVE], reasons={c.GREETING: (0.0, GREETING_EVIDENCE), c.PRESENT_PERSON: (0.0, 0.0)},
                reads=[presence_c.PRESENT, presence_c.SINCE, identity_c.PERSON, identity_c.IDENTITY,
                       transcript_c.LAST_FROM, transcript_c.LAST_TO, affect_c.HOSTILITY])
def _arrivals(s: SocialState, frame: Frame) -> list[Candidate]:
    out: list[Candidate] = []
    now = frame.now
    p = params(frame.env.params_of("social", frame.root))
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
        left = s.left.get(handle)
        if left and since - left < p.away_us:
            continue  # elle n'était pas partie : un onglet rechargé, une coupure, un redémarrage d'elle
        person = frame.get(identity_c.PERSON(handle))
        if now - s.greeted.get(person, -GREETING_SPACING) < GREETING_SPACING:
            continue
        if grudging(frame.get(affect_c.HOSTILITY(person)), p):
            continue  # pas même une salutation (la retenue le dit aussi : son veto reste sur la ligne)
        name = frame.get(identity_c.IDENTITY(handle)).name
        # « vient d'arriver » se lisait comme un voyage (sonde réelle du 2026-10-03 : « t'es bien arrivé, j'espère que
        # t'as pas galéré pour venir jusqu'ici ») : on se connecte, on n'arrive de nulle part
        who = f"« {name} »" if name else "Quelqu'un"
        brief = (f"{who} vient de se connecter, sans t'avoir encore rien écrit : salue "
                 f"{f'« {name} »' if name else 'cette personne'} à ta façon, en une phrase ou deux.")
        out.append(Candidate(Kind.INITIATIVE, handle, c.GREETING, GREETING_EVIDENCE, resources=resources,
                             guards=(guard,), args=FrozenDict({"brief:social": brief})))
    return out


@SOCIAL.propose(kinds=[Kind.INITIATIVE], reasons={c.RECONTACT: (0.0, 12.0), c.COMFORT: (0.0, 12.0),
                                                  c.CHAT: (0.0, 3.5)},
                reads=[c.CIRCLE, c.CONTACT, c.CLOSENESS, identity_c.HANDLES, identity_c.REACHABLE,
                       identity_c.IDENTITY, presence_c.PRESENT, affect_c.MOOD, affect_c.WARMTH, transcript_c.LAST_FROM])
def _reach_out(s: SocialState, frame: Frame) -> list[Candidate]:
    p = params(frame.env.params_of("social", frame.root))
    if not _daytime(frame, p.day_start_min, p.day_end_min):
        return []
    out: list[Candidate] = []
    comfort: list[tuple[float, str, str]] = []
    mood = frame.get(affect_c.MOOD)
    distressed = (A.valence(mood.felt) <= p.distress_valence and mood.felt_intensity >= p.distress_intensity
                  and frame.now - s.comforted_at >= p.comfort_spacing_us)
    for person in frame.get(c.CIRCLE):  # ses amies et proches seulement : les inconnues ne coûtent rien ici
        if not is_identifiable(person) or person.startswith("name:") or person not in s.contacts:
            continue
        level = frame.get(c.CLOSENESS(person))
        if _RANK[level] < _RANK[c.FRIEND]:
            continue
        reading = frame.get(c.CONTACT(person))
        if not reading.last_in:
            continue  # sans réponse, une relance douce au plus, après un long délai : c'est la retenue d'``agency``
        address = _address(frame, person)
        if address is None:
            continue
        name = frame.get(identity_c.IDENTITY(person)).name or frame.get(identity_c.IDENTITY(address)).name
        who = f"« {name} »" if name else "cette personne"
        if reading.silence_ratio >= p.recontact_factor:
            silent = reading.silence_ratio * reading.rhythm_days
            habit = (f", alors que d'habitude vous vous parlez {_habit_words(reading.rhythm_days)}"
                     if reading.measured else "")
            brief = (f"Ça fait {_silence_words(silent)} que tu n'as pas de nouvelles de {who}{habit}. Tu as envie "
                     "de prendre de ses nouvelles : un mot simple et chaleureux — pas un reproche, pas de « ça fait "
                     "longtemps ».")
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
            brief = f"Tu penses à {who} et tu as envie de discuter un peu. Un mot simple, sans enjeu."
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


def announced(frame: Frame, person: str, after: int) -> int | None:
    """Le premier moment qu'elle lui avait annoncé elle-même (« je pars six mois », « mon concours, c'est en
    mars ») et qui est passé depuis ``after`` : l'occasion de reprendre de ses nouvelles. Jamais ce qu'un tiers en a
    dit, ni ce qu'on lui a demandé de taire."""
    for ev in frame.get(memory_c.LIFE_EVENTS(person)):
        if ev.ongoing or ev.secret or not set(ev.told_by) <= {person}:
            continue
        if after < ev.when <= frame.now:
            return ev.when
    return None


def rekindle_due(s: SocialState, frame: Frame, person: str, p: SocialParams) -> int | None:
    """Quand elle reprendra des nouvelles d'une amie partie sans plus répondre : longtemps après le dernier échange
    (des mois, et plusieurs fois leur rythme), ou le lendemain d'un moment que la personne lui avait annoncé — jamais
    moins de ``rekindle_min_us`` après. Une fois par silence : ``None`` si c'est déjà fait depuis son dernier
    message (ou si elle n'a jamais écrit)."""
    reading = frame.get(c.CONTACT(person))
    if not reading.last_in or s.rekindled.get(person, 0) >= reading.last_in:
        return None
    quiet = max(reading.last_in, reading.last_out)
    usual = reading.usual_days or reading.rhythm_days
    due = quiet + max(p.rekindle_after_us, round(p.rekindle_rhythms * usual * DAY))
    moment = announced(frame, person, reading.last_in)
    if moment is not None:
        due = min(due, max(moment + p.rekindle_announced_us, quiet + p.rekindle_min_us))
    return due


@SOCIAL.propose(kinds=[Kind.INITIATIVE], reasons={c.REKINDLE: (0.0, 12.0)},
                reads=[c.CIRCLE, c.CONTACT, affect_c.HOSTILITY, identity_c.IS_OWNER, identity_c.HANDLES,
                       identity_c.REACHABLE, identity_c.IDENTITY, presence_c.PRESENT, transcript_c.LAST_FROM,
                       memory_c.LIFE_EVENTS])
def _rekindle(s: SocialState, frame: Frame) -> list[Candidate]:
    """Une amie — d'aujourd'hui ou d'avant — partie sans plus donner de nouvelles : elle ne la harcèle pas (après
    deux messages sans réponse, plus rien, ``agency``), mais des mois plus tard, ou après le moment que la personne
    lui avait annoncé, elle prend de ses nouvelles **une fois**, doucement (ADR 0058). Pas la nuit."""
    p = params(frame.env.params_of("social", frame.root))
    if not _daytime(frame, p.day_start_min, p.day_end_min):
        return []
    out: list[Candidate] = []
    for person in frame.get(c.CIRCLE):
        if not is_identifiable(person) or person.startswith("name:") or person not in s.contacts:
            continue
        due = rekindle_due(s, frame, person, p)
        if due is None or frame.now < due:
            continue
        if not been_friends(s, person, p, frame.get(affect_c.HOSTILITY(person)),
                            bool(frame.get(identity_c.IS_OWNER(person)))):
            continue
        address = _address(frame, person)
        if address is None:
            continue
        name = frame.get(identity_c.IDENTITY(person)).name or frame.get(identity_c.IDENTITY(address)).name
        who = f"« {name} »" if name else "cette personne"
        reading = frame.get(c.CONTACT(person))
        moment = announced(frame, person, reading.last_in)
        why = (f"Ça fait longtemps que tu n'as plus de nouvelles de {who}, qui t'avait parlé d'un moment passé "
               "depuis (tu le vois peut-être dans CE QUI SE PASSE DANS SA VIE)." if moment is not None else
               f"Ça fait des mois que tu n'as plus de nouvelles de {who}.")
        brief = (f"{why} Tu as envie de savoir ce que devient {who} : un mot simple et chaleureux, une seule fois — "
                 "sans reproche, sans « ça fait longtemps », sans rien attendre en retour.")
        out.append(Candidate(Kind.INITIATIVE, address, c.REKINDLE, p.rekindle_evidence,
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


@SOCIAL.modulate(kinds=[Kind.INITIATIVE], reads=[identity_c.PERSON, affect_c.HOSTILITY])
def _restraint(s: SocialState, frame: Frame, row: RowView) -> Modulation:
    """Rien d'ordinaire vers quelqu'un qui a installé une rancune — même pas
    une salutation. Tenir parole (``agency.OWED`` : le rappel qu'il lui a
    demandé) n'en dépend pas ; prévenir (``agency.INFORMS``) n'est que décalé :
    on prévient quelqu'un même fâchée contre lui, sans se presser. (Ne pas
    harceler quelqu'un qui ne répond pas, quelle que soit la raison, est la
    retenue du budget d'initiatives : ``agency``.)"""
    if row.target in ("any", "none") or not is_identifiable(row.target):
        return Modulation()
    p = params(frame.env.params_of("social", frame.root))
    person = frame.get(identity_c.PERSON(row.target))
    if not grudging(frame.get(affect_c.HOSTILITY(person)), p):
        return Modulation()
    reasons = set(row.reasons)
    if agency_c.OWED & reasons:
        return Modulation()
    if agency_c.INFORMS & reasons:
        return Modulation(shift=p.grudge_inform_shift) if p.grudge_inform_shift else Modulation()
    return Modulation(veto=c.GRUDGE)
