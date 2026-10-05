"""Ce que ``social`` montre à un opérateur : ses liens, un par personne, et
l'onglet « Lien » de la fiche d'une personne.

Lecture seule. La proximité et le rythme sont ceux que la faculté lit (faits
``CLOSENESS`` et ``CONTACT``) ; « Pourquoi ce niveau » déroule la trace du
calcul même qui fait la proximité (``closeness_trace``), jamais un calcul à
part. Un profil dont le texte a été oublié s'affiche comme oublié. La seule
écriture — fixer la proximité — est une action d'opérateur (``actions.py``),
posée en place sur l'onglet.
"""

from __future__ import annotations

from dataclasses import replace

from mika.contracts import identity as identity_c
from mika.contracts import social as c
from mika.faculties.social.faculty import (
    BOND,
    DAYS,
    GRUDGE,
    HISTORY,
    MESSAGES,
    REGARD,
    SOCIAL,
    ClosenessTrace,
    Criterion,
    SocialParams,
    SocialState,
    closeness_trace,
    params,
)
from mika.faculties.social.profile import lines_of
from mika.faculties.social.sections import refs_of
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    ActionSlot,
    Badge,
    Block,
    Cell,
    Column,
    Fields,
    InspectContext,
    Meter,
    Note,
    Param,
    Prose,
    Ref,
    Row,
    Stat,
    Stats,
    Table,
    Text,
    When,
    paginate,
)
from mika.vocab.people import fold, is_identifiable

#: Au plus tant de personnes par page ; un résumé replié au-delà de tant de caractères.
PAGE = 50
SUMMARY_CHARS = 300
#: La proximité « automatique » (vécue) dans les formulaires : aucune déclaration.
AUTO = "auto"

#: Sans genre imposé : la console parle aussi d'Adrien.
CLOSENESS_FR = {c.STRANGER: "pas encore de lien", c.ACQUAINTANCE: "connaissance", c.FRIEND: "amitié",
                c.CLOSE: "proche"}
CLOSENESS_TONE = {c.STRANGER: "muted", c.ACQUAINTANCE: "", c.FRIEND: "info", c.CLOSE: "ok"}
FORGOTTEN = "(oublié)"
#: les critères d'un niveau, en mots ; ceux que l'affect décide (non lus sans l'histoire d'une amie)
CRITERION_FR = {DAYS: "jours de contact", MESSAGES: "messages reçus", HISTORY: "histoire vécue (jours)",
                REGARD: "chaleur", BOND: "attachement", GRUDGE: "hostilité"}
_COUNTED = frozenset({DAYS, MESSAGES, HISTORY})
_AFFECT = frozenset({REGARD, BOND, GRUDGE})


def _known(s: SocialState) -> set[str]:
    return {*s.contacts.keys(), *s.profiles.keys(), *s.declared.keys(), *s.greeted.keys()}


def _name(frame: Frame, person: str) -> str:
    if person.startswith("name:"):
        return person[5:].title()
    return frame.get(identity_c.IDENTITY(person)).name or person


def _ref(frame: Frame, person: str, tab: str = "") -> Ref:
    return Ref.subject("person", person, _name(frame, person), tab)


def _closeness_text(s: SocialState, frame: Frame, person: str) -> str:
    level = frame.get(c.CLOSENESS(person))
    text = CLOSENESS_FR.get(level, level)
    if person in s.declared:
        return f"{text} (déclarée)"
    return f"{text} (vécue, plancher « propriétaire »)" if frame.get(identity_c.IS_OWNER(person)) else f"{text} (vécue)"


def _closeness(s: SocialState, frame: Frame, person: str) -> Badge:
    return Badge(_closeness_text(s, frame, person), CLOSENESS_TONE.get(frame.get(c.CLOSENESS(person)), ""))


def _rhythm(reading: c.ContactReading) -> str:
    n = round(reading.rhythm_days)
    every = "tous les jours" if n <= 1 else f"tous les {n} jours"
    return f"{every} — {'mesuré' if reading.measured else 'repli selon la proximité'}"


def _ratio(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def _silence(reading: c.ContactReading, p: SocialParams) -> Cell:
    """Le silence rapporté à son rythme : la jauge est à moitié pleine au seuil
    où elle lui manque (une fois et demie son rythme, par défaut)."""
    if not reading.last_in:
        return Text("jamais écrit", "muted")
    full = 2 * p.recontact_factor
    missed = reading.silence_ratio >= p.recontact_factor
    return Meter(min(1.0, reading.silence_ratio / full) if full > 0 else 0.0, f"×{_ratio(reading.silence_ratio)}",
                 "warn" if missed else "")


def _number(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def _amount(key: str, value: float) -> str:
    return str(round(value)) if key in _COUNTED else _number(value)


def _criterion(cr: Criterion, days: int, settled: bool, p: SocialParams) -> str:
    """Un critère tel que le calcul l'a lu : la valeur, le seuil, ✓ ou ✗ (``days`` : ses jours de contact)."""
    label, value, bar = CRITERION_FR.get(cr.key, cr.key), _amount(cr.key, cr.value), _amount(cr.key, cr.threshold)
    if cr.key == GRUDGE:
        if cr.held:
            return f"sans rancune : {label} {value} < {bar} ✓" + (" (amitié installée)" if settled else "")
        return (f"rancune : {label} {value} ≥ {bar} ✗"
                + (" (assez lourde pour défaire une amitié installée)" if settled else
                   " (une amitié naissante ne la passe pas)"))
    if cr.key == BOND and not cr.held and cr.value <= 0.0:
        text = f"{label} nul ✗ (il en faut un)"
    else:
        text = f"{label} {value} {'≥' if cr.held else '<'} {bar} {'✓' if cr.held else '✗'}"
    if cr.key == BOND and p.close_long_bond < p.close_bond:
        if days >= p.close_long_days:
            text += f" (longue histoire : {days} jours de contact)"
        elif not cr.held:
            text += f" ({_number(p.close_long_bond)} suffirait après {p.close_long_days} jours de contact : {days})"
    return text


def _criteria(level: tuple[Criterion, ...], days: int, settled: bool, affect: bool, p: SocialParams) -> str:
    """Les critères d'un niveau : « ; » entre ceux qu'il faut tous, « ou » devant celui qui suffit à la place."""
    parts: list[str] = []
    for cr in level:
        if not affect and cr.key in _AFFECT:
            continue  # pas lu : il n'y changerait rien
        text = _criterion(cr, days, settled, p)
        if cr.either and parts:
            parts[-1] = f"{parts[-1]} ou {text}"
        else:
            parts.append(text)
    return " ; ".join(parts)


def _steps(trace: ClosenessTrace, p: SocialParams) -> list[tuple[str, str, str]]:
    """Ce que le calcul de la proximité vécue a lu et tranché, dans l'ordre : les critères du niveau atteint et du
    suivant (sur la fenêtre), le silence, le plancher d'histoire, celui de la propriétaire."""
    steps: list[tuple[str, str, str]] = []
    window, everything = trace.window, trace.everything
    if window is None or everything is None:
        steps.append(("leur histoire", "aucune", "cette personne ne lui a jamais écrit"))
    else:
        settled = everything.days >= p.friendship_settled_days
        if not trace.affect:
            steps.append(("affect", "pas lu",
                          f"pas l'histoire d'une amie ({everything.days} jours de contact pour {p.friend_days}, "
                          f"{everything.messages} messages pour {p.friend_messages}) : ni la chaleur, ni "
                          "l'attachement, ni la rancune n'y changeraient rien"))
        for rank in (window.rank, window.rank + 1):
            if 0 < rank < len(c.CLOSENESS_LEVELS):
                steps.append((CLOSENESS_FR[c.CLOSENESS_LEVELS[rank]],
                              "atteint ✓" if rank <= window.rank else "pas atteint ✗",
                              _criteria(window.criteria[rank], window.days, settled, trace.affect, p)))
        ratio = trace.silent / trace.rhythm_days if trace.rhythm_days > 0 else 0.0
        lost = ("un cran perdu" if window.rank > 0 else "rien à perdre") if trace.lost else "aucun cran perdu"
        steps.append(("silence", lost,
                      f"{trace.silent} jour(s) depuis leur dernier jour de contact, ×{_ratio(ratio)} le rythme "
                      f"qu'elles avaient ({_ratio(trace.rhythm_days)} j) ; un cran se perd à "
                      f"{_ratio(trace.silence_bar)} j (×{_ratio(p.closeness_silence_factor)} son rythme, jamais "
                      f"avant {p.closeness_silence_min_days} j)"))
        if trace.floor > 0:
            was = CLOSENESS_FR[c.CLOSENESS_LEVELS[everything.rank]]
            why = (f"un cran sous ce qu'elles ont été sur toute leur histoire : {was} ({everything.days} jours de "
                   f"contact, {everything.messages} messages)")
            if trace.short and everything.rank - 1 > trace.floor:
                why = (f"une histoire courte ({everything.days} jours de contact, moins de {p.lasting_days}) que "
                       f"son silence a dépassée ({trace.silent} j de silence pour {trace.history} j vécus "
                       "ensemble) : connaissance au plus")
            elif everything.days >= p.lasting_days:
                why += (f" — une longue amitié ({p.lasting_days} jours de contact ou plus) le garde, quel que soit "
                        "le silence")
            if trace.floor > window.rank - (1 if trace.lost else 0):
                why += " ; c'est lui qui tient le niveau"
            steps.append(("plancher d'histoire", CLOSENESS_FR[c.CLOSENESS_LEVELS[trace.floor]], why))
    if trace.owner:
        if trace.level != trace.lived_level:
            steps.append(("plancher de la propriétaire", CLOSENESS_FR.get(trace.level, trace.level),
                          f"sa propriétaire reconnue : au moins {CLOSENESS_FR.get(p.owner_floor, p.owner_floor)} "
                          "d'office — jamais « proche » : ça se vit"))
        else:
            steps.append(("plancher de la propriétaire", "levé",
                          f"une rancune lourde (hostilité {_number(trace.hostility)} ≥ {_number(p.grudge_demote)}) "
                          "le lève, comme elle défait une amitié installée"))
    return steps


def _why(trace: ClosenessTrace, lived: ClosenessTrace, p: SocialParams) -> Table:
    """Pourquoi ce niveau : la trace du calcul même qui fait la proximité (``lived`` : sans la déclaration)."""
    steps: list[tuple[str, str, str]] = []
    if trace.declared:
        steps.append(("déclarée", CLOSENESS_FR.get(trace.level, trace.level),
                      "fixée par un opérateur : elle l'emporte ; ce qui suit est ce que leur histoire en ferait"))
    steps += _steps(lived, p)
    if trace.declared:
        steps.append(("vécue, elle serait", CLOSENESS_FR.get(lived.level, lived.level),
                      "sans la déclaration (« automatique »)"))
    steps.append(("niveau retenu", CLOSENESS_FR.get(trace.level, trace.level), "celui que lit la faculté"))
    window = lived.window
    caption = (f"Jours de contact et messages : ceux des {p.closeness_window_days} derniers jours ({window.days} "
               f"jours de contact, {window.messages} messages reçus) ; l'histoire vécue va de leur premier à leur "
               "dernier jour de contact ; l'histoire plus ancienne fait le plancher."
               if window is not None else "")
    return Table(("étape", "valeur", "pourquoi"), tuple(steps), title="Pourquoi ce niveau", caption=caption)


def _texts(s: SocialState, people: list[str], ctx: InspectContext) -> dict[str, str] | None:
    refs = [r for p in people if p in s.profiles for r in refs_of(s.profiles[p])]
    if ctx.store is None:
        return None
    return ctx.store.content(refs) if refs else {}


def _part(ref: str, legacy: str, texts: dict[str, str] | None) -> str:
    """Un texte du profil : gardé à part (« (oublié) » s'il a été oublié), ou en clair (profil ancien)."""
    if not ref:
        return legacy or "—"
    if texts is None:
        return "(magasin indisponible)"
    return texts.get(ref) or FORGOTTEN


def _listed(ref: str, legacy: tuple[str, ...], texts: dict[str, str] | None) -> str:
    if not ref:
        return ", ".join(legacy) or "—"
    if texts is None:
        return "(magasin indisponible)"
    got = texts.get(ref)
    return ", ".join(lines_of(got)) if got is not None else FORGOTTEN


def _summary(s: SocialState, person: str, texts: dict[str, str] | None) -> str:
    profile = s.profiles.get(person)
    if profile is None:
        return "pas encore de profil"
    if texts is None:
        return "(magasin indisponible)"
    text = texts.get(profile.summary_ref) if profile.summary_ref else None
    return FORGOTTEN if text is None else text


def _when(at: int, never: str = "jamais") -> Cell:
    return When(at) if at else Text(never, "muted")


def settable(frame: Frame, person: str) -> bool:
    """Peut-on déclarer la proximité de cette clé ? Une personne durable, par sa
    clé canonique, qui a au moins une adresse."""
    if not is_identifiable(person) or person.startswith("name:"):
        return False
    return frame.get(identity_c.PERSON(person)) == person and bool(frame.get(identity_c.HANDLES(person)))


def _detail(s: SocialState, frame: Frame, ctx: InspectContext, person: str, *, on_fiche: bool = False) -> list[Block]:
    p = params(frame.env.params_of("social", frame.root))
    reading = frame.get(c.CONTACT(person))
    profile = s.profiles.get(person)
    texts = _texts(s, [person], ctx)
    missed = dict(frame.get(c.MISSED))
    today = frame.local().date().toordinal()
    trace = closeness_trace(s, person, p, today, frame.get)
    # déclarée : ce que leur histoire en ferait, par le même calcul sans la déclaration
    lived = (closeness_trace(replace(s, declared=s.declared.delete(person)), person, p, today, frame.get)
             if trace.declared else trace)
    window = lived.window
    recent = f" sur les {p.closeness_window_days} derniers jours"
    blocks: list[Block] = [
        Stats((Stat("proximité", _closeness(s, frame, person),
                    "déclarée par un opérateur" if person in s.declared else "née de leur histoire"),
               Stat("rythme", _rhythm(reading)),
               Stat("silence ÷ rythme", _silence(reading, p), f"lui manque au-delà de ×{_ratio(p.recontact_factor)}",
                    tone="warn" if person in missed else ""),
               Stat("dernier message reçu", _when(reading.last_in)),
               Stat("ses initiatives sans réponse", reading.unanswered))),
        Fields((
            *((() if on_fiche else (("personne", _ref(frame, person)),))),  # sur sa fiche : pas de lien vers elle-même
            ("jours de contact", f"{reading.days} en tout, {window.days}{recent}" if window else reading.days),
            ("messages reçus", f"{reading.inbound} en tout, {window.messages}{recent}" if window else reading.inbound),
            ("qui ouvre leurs conversations",
             f"elle {reading.her_starts} fois, la personne {reading.their_starts} fois"
             + (" — c'est presque toujours elle" if reading.one_sided else "")),
            ("premier message reçu", _when(reading.first_in)),
            ("dernier message envoyé", _when(reading.last_out)),
            ("dernière salutation", _when(s.greeted.get(person, 0))),
            ("éléments de mémoire la concernant", s.mentions.get(person, 0)),
            ("dernier réconfort cherché (auprès de quiconque)", _when(s.comforted_at)),
        ), title="Le lien", columns=2),
        _why(trace, lived, p),
    ]
    if person in missed:
        blocks.append(Note(f"Elle lui manque : un silence de ×{_ratio(missed[person])} son rythme habituel.",
                           tone="warn"))
    if profile is None:
        blocks.append(Note("Pas encore de profil : elle n'en sait pas assez pour s'en faire une idée.", tone="muted"))
    else:
        blocks.append(Fields((
            ("relu le", _when(profile.revised_at)),
            ("comment lui parler", _part(profile.tone_ref, profile.tone, texts)),
            ("ce qui l'intéresse", _listed(profile.interests_ref, profile.interests, texts)),
            ("sujets délicats", _listed(profile.sensitive_ref, profile.sensitive, texts)),
            ("mémoire relue jusqu'à l'élément", profile.upto),
        ), title="Ce qu'elle en pense", columns=2))
        blocks.append(Prose(_summary(s, person, texts), title="Ce qu'elle en sait", clamp=1200))
    return blocks


@SOCIAL.inspect("lien", title="Lien", subject="person", order=30,
                description="Leur proximité et pourquoi ce niveau, le rythme de leurs échanges, ce qu'elle en pense.")
def _link(s: SocialState, frame: Frame, ctx: InspectContext) -> list[Block]:
    person = ctx.subject
    if not person:
        return [Note("Ouvre la fiche d'une personne : Personnes, puis la personne.", tone="muted")]
    if not is_identifiable(person):
        return [Note("Une connexion de passage : aucun lien durable ne s'y attache.", tone="muted")]
    blocks: list[Block] = (_detail(s, frame, ctx, person, on_fiche=True) if person in _known(s) else
                           [Note("Aucun lien pour l'instant : cette personne ne lui a jamais écrit, et rien n'a été "
                                 "déclaré.", tone="muted")])
    if settable(frame, person):
        blocks.append(ActionSlot("social.proximite", initial=(("closeness", s.declared.get(person) or AUTO),),
                                 title="Fixer la proximité"))
    return blocks


SEARCH = Param("q", "nom", placeholder="Alice…")
LEVEL = Param("proximite", "proximité", kind="select", choices=tuple(CLOSENESS_FR.items()))
LEGACY = Param("person", "personne", kind="hidden")


@SOCIAL.inspect("liens", title="Liens", section="personnes", order=20, params=[SEARCH, LEVEL, LEGACY],
                description="Chaque lien : sa proximité, son rythme, le silence ; une ligne mène à la fiche.")
def _links(s: SocialState, frame: Frame, ctx: InspectContext) -> list[Block]:
    person = str(ctx.value("person") or "")
    if person:  # l'ancien lien vers le détail d'une personne
        if person not in _known(s):
            return [Note(f"Aucun lien avec « {person} » pour l'instant.", tone="muted")]
        return [Fields((("fiche", _ref(frame, person, "lien")),), title="Ce lien vit désormais sur la fiche"),
                *_detail(s, frame, ctx, person)]
    p = params(frame.env.params_of("social", frame.root))
    q, level = fold(str(ctx.value("q") or "")), str(ctx.value("proximite") or "")
    people = sorted(_known(s), key=lambda k: (-(s.contacts[k].last_in if k in s.contacts else 0), k))
    shown = [k for k in people if (not q or q in fold(_name(frame, k)) or q in fold(k))
             and (not level or frame.get(c.CLOSENESS(k)) == level)]
    page, pager = paginate(shown, ctx.pager(size=PAGE))
    texts = _texts(s, list(page), ctx)
    rows: list[Row] = []
    for k in page:
        reading = frame.get(c.CONTACT(k))
        rows.append(Row((_ref(frame, k), _closeness(s, frame, k), _rhythm(reading), _silence(reading, p),
                         _when(reading.last_in), reading.unanswered,
                         Text(_summary(s, k, texts), clamp=SUMMARY_CHARS)), href=_ref(frame, k, "lien")))
    missed = frame.get(c.MISSED)
    return [
        Stats((Stat("personnes", len(people)),
               Stat("qui lui manquent", len(missed),
                    (", ".join(f"{_name(frame, k)} (×{_ratio(r)})" for k, r in missed[:5])
                     + (f" et {len(missed) - 5} autre(s)" if len(missed) > 5 else "")) or "personne",
                    tone="warn" if missed else ""),
               Stat("dernier réconfort cherché", _when(s.comforted_at)))),
        Table(("personne", "proximité", Column("rythme", detail=True), Column("silence ÷ rythme", hint="la moitié de la jauge : elle "
                                                         "lui manque"), "dernier message reçu",
               Column("initiatives sans réponse", "num", detail=True), "ce qu'elle en sait"), tuple(rows), pager=pager,
              title="Liens", filters=("q", "proximite"),
              empty="aucun lien ne correspond" if q or level else "aucun lien pour l'instant"),
    ]
