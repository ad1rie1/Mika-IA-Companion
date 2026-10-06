"""Se faire une idée de quelqu'un (théorie de l'esprit).

Quand assez de nouveau est su d'une personne (au plus une fois par jour), le
modèle (rôle ``profile``) relit ce qu'elle en sait — seulement ce qui ne
concerne qu'elle, et seulement de **première main** (la mémoire sait qui le
lui a dit) : ce que la personne lui a dit elle-même, ou ce que Mika a vécu
avec elle. Ce qu'un tiers lui a confié sur elle n'y entre jamais : une fiche
lue à la personne ne doit pas lui répéter ce que Bob a dit d'elle. Le modèle
dit qui elle est, comment lui parler, ce qui l'intéresse, ce qui est
délicat — des textes gardés à part, que l'oubli de la personne efface. La
proximité, elle, ne se juge pas : elle se vit (``faculty.lived``).

**Une fiche n'invente pas** (ADR 0055). Ce qu'elle dit de la situation de la
personne (en couple ou non, enfants, famille, travail, âge, où et avec qui
elle vit) doit se lire dans ce que le modèle a relu : sinon la proposition
tombe (la sonde réelle du 2026-10-03 avait écrit « Sam a 30 ans, célibataire »,
que personne n'avait dit). Ce qui l'intéresse, ce sont ses goûts, pas ses
tracas du moment (« sa santé dentaire », « son anniversaire »). Les matériaux
sont choisis par importance, sans les banalités (« allez j'y vais ») ni les
répliques de Mika recopiées par une extraction ancienne ; ce qui n'appartient
qu'à elles deux (un surnom) se vit dans leur registre, pas dans la fiche.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import self_ as self_c
from mika.contracts import social as c
from mika.faculties.social.faculty import SOCIAL, SocialState, params
from mika.kernel.events import Content
from mika.kernel.faculty import CatchUp
from mika.kernel.frame import Frame
from mika.ports.llm import LLMRequest, LLMResponse, Message, ToolDecl
from mika.vocab.privacy import Sensitivity
from mika.vocab.words import banal, elided, fold

TOOL_NAME = "record_profile"


class XProfile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    resume: str = Field(min_length=3, max_length=900)
    ton: str = Field(default="", max_length=300)
    interets: list[str] = Field(default_factory=list)
    sujets_sensibles: list[str] = Field(default_factory=list)


def tool(name: str) -> ToolDecl:
    """L'outil de la fiche, au nom de celle qui la tient (celui de sa persona)."""
    return ToolDecl(TOOL_NAME, f"Enregistre ce que {name} pense de cette personne.", XProfile.model_json_schema())


def system(name: str) -> str:
    """La consigne de la fiche, au nom de celle qui la tient (celui de sa persona : jamais écrit ici)."""
    return _SYSTEM.replace(_NAME, name)


#: là où son nom s'écrit dans la consigne
_NAME = "{nom}"
_SYSTEM = """Tu aides {nom} à se faire une idée de quelqu'un qu'elle connaît, à partir de ce que cette personne lui a \
dit elle-même et de ce que {nom} a vécu avec elle. Écris comme des notes de {nom} sur cette personne, sans jamais \
nommer {nom} ni parler d'elle (ni « {nom} », ni « elle », ni « moi », ni « me ») : la personne à la troisième \
personne, avec son prénom (« C'est quelqu'un qui… »).
- resume : qui est cette personne — sa vie, ce qui compte pour elle, son caractère, et les proches qu'elle a nommés \
(« sa sœur Léa », « son chat Moustache ») — en 2 à 4 phrases ; ne répète pas les détails intimes. N'invente rien : \
rien de sa situation (en couple ou non, enfants, famille, travail, âge, où et avec qui elle vit) que ces notes ne \
disent pas. Ni chiffres, ni jugement sur votre lien (« connaissance récente », « ami proche ») : le lien, {nom} le \
vit, elle ne le note pas.
- ton : comment lui parler — une consigne de ton (« direct et taquin, il aime qu'on le charrie »), jamais une \
phrase à lui dire.
- interets : ses goûts et ses passions — ce qu'elle aime faire, regarder, écouter, lire (quelques mots chacun, au \
plus 6) ; jamais ses soucis du moment, sa santé, ses rendez-vous ni ce qui lui arrive ; aucun si rien ne le dit.
- sujets_sensibles : les sujets délicats avec cette personne (au plus 6), sinon une liste vide.
Réponds uniquement en appelant l'outil record_profile."""


def parse(resp: LLMResponse) -> XProfile | None:
    raw: Any = None
    for call in resp.tool_calls:
        if call.name == TOOL_NAME:
            raw = dict(call.args)
            break
    if raw is None:
        match = re.search(r"\{.*\}", resp.text or "", re.DOTALL)
        if not match:
            return None
        try:
            raw = json.loads(match.group(0))
        except ValueError:
            return None
    try:
        return XProfile.model_validate(raw)
    except ValidationError:
        return None


def _short(values: list[str], limit: int = 6) -> tuple[str, ...]:
    out = []
    for v in values:
        v = " ".join(str(v).split())[:60]
        if v and v not in out:
            out.append(v)
    return tuple(out[:limit])


def _lines(values: Sequence[str]) -> Content | None:
    """Une liste courte, un élément par ligne, gardée à part (``None`` : vide)."""
    return Content.of("\n".join(values), level=int(Sensitivity.PERSONAL)) if values else None


def lines_of(text: str | None) -> tuple[str, ...]:
    return tuple(x.strip() for x in (text or "").splitlines() if x.strip())


#: ce qu'une fiche dit de la situation de quelqu'un, par domaine (replié) : un domaine que ses notes n'abordent pas,
#: la fiche n'en dit rien
SITUATION = {
    "couple": re.compile(r"\b(?:celibataire|en couple|mariee?s?|divorcee?s?|separee?s?|veuf|veuve|fiancee?s?|"
                         r"copain|copine|petite? amie?|compagnon|compagne|conjointe?|mari|epoux|epouse|sa femme|"
                         r"son homme|rupture|relation amoureuse)\b"),
    "enfants": re.compile(r"\b(?:enfants?|fils|bebes?|enceinte|grossesse)\b"),
    "famille": re.compile(r"\b(?:parents?|pere|mere|papa|maman|freres?|soeurs?|grands?-?parents?|"
                          r"grand-?(?:pere|mere))\b"),
    "travail": re.compile(r"\b(?:metier|emploi|chomage|etudiante?s?|etudes|retraitee?|salariee?|profession\w*|"
                          r"travail\w*|boulot|bosse\w*|job|taf|collegues?|patron|bureau)\b"),
    "logement": re.compile(r"\b(?:vit (?:seule?|avec|en|a|chez)|habite\w*|appartement|appart|maison|colocation|"
                           r"coloc|demenag\w*|loge\w*)\b"),
}
#: un âge, qui doit être celui que ses notes disent (« 30 ans » ; pas « la trentaine » qu'elles ne disent pas)
_AGE = re.compile(r"\b(?:\d{1,3} ans|trentaine|quarantaine|vingtaine|cinquantaine|soixantaine|trentenaire|"
                  r"quarantenaire|cinquantenaire|jeune adulte)\b")
#: un intérêt qui n'est pas un goût : un tracas, un rendez-vous, un moment de sa vie (replié)
_WORRY = re.compile(r"\b(?:sante|dentaire|dentiste|medec\w*|medic\w*|docteur|veto|veterinaire|rendez|rdv|maladie|"
                    r"malade|hopital|operation|soins?|traitement|anniversaire|deuil|perte|examen|entretien|"
                    r"inquietude|soucis?|problemes?|stress|age)\b")
#: tu, toi, ton… hors d'une citation : une réplique recopiée, pas une note sur la personne
_SECOND_PERSON = re.compile(r"\b(?:tu|toi|ton|ta|tes)\b|\bt'")
_QUOTE = re.compile(r"«[^»]*»|\"[^\"]*\"")
_SENTENCE = re.compile(r"(?<=[.!?…])\s+")
_CLAUSE = re.compile(r",\s+|;\s+|\s+[—–-]\s+")


def _folded(text: str) -> str:
    return " ".join(fold(text).replace("’", "'").split())


def supported(clause: str, notes: str) -> bool:
    """Ce que cette proposition dit de sa situation, ses notes l'abordent-elles ? (``notes`` : replié)"""
    said = _folded(clause)
    for found in _AGE.finditer(said):
        if found.group(0) not in notes:
            return False
    return all(pattern.search(notes) for pattern in SITUATION.values() if pattern.search(said))


def grounded(summary: str, notes: str) -> str:
    """Le portrait sans ce qu'il invente de sa situation : une proposition qui en parle sans que ses notes
    l'abordent tombe — toute la phrase quand c'est son début (le sujet), sinon la proposition seule (« Sam a 30
    ans, célibataire, vit avec son chat » → « Sam a 30 ans. »)."""
    out = []
    for sentence in _SENTENCE.split(" ".join(summary.split())):
        clauses = _CLAUSE.split(sentence)
        if not clauses or not supported(clauses[0], notes):
            continue
        kept = [c for c in clauses if supported(c, notes)]
        text = ", ".join(kept).strip()
        if text and text[-1] not in ".!?…":
            text += "."
        if text:
            out.append(text[0].upper() + text[1:])
    return " ".join(out)


def tastes(interests: Sequence[str]) -> list[str]:
    """Ses goûts seulement : « sa santé dentaire », « son anniversaire » ne sont pas des intérêts."""
    return [i for i in interests if not _WORRY.search(_folded(i))]


def note_worthy(text: str, names: Sequence[str]) -> bool:
    """Un matériau de fiche : pas une banalité (« Sam est parti en disant 'allez j'y vais' »), pas une réplique de
    Mika recopiée (« Dors bien Sam… », adressée à quelqu'un)."""
    return not banal(text, names) and not _SECOND_PERSON.search(_QUOTE.sub(" ", _folded(text)))


def _due(s: SocialState, now: int, p: Any) -> list[tuple[int, str]]:
    """Les personnes dont assez de nouveau est su (les plus en retard d'abord)."""
    out = []
    for person, count in s.mentions.items():
        if person.startswith("name:"):
            continue
        profile = s.profiles.get(person)
        new = count - (profile.mentions_at if profile else 0)
        if new < p.profile_min_items:
            continue
        if profile is not None and now - profile.revised_at < p.profile_interval_us:
            continue
        out.append((-new, person))
    return sorted(out)


@SOCIAL.process("social.profile", wake_on=[memory_c.CONSOLIDATED], lane="background", catch_up=CatchUp.ONCE,
                max_quantum_s=3600)
class Revise:
    def __init__(self) -> None:
        self.retry_at = 0
        #: personne → nombre de mentions lors de la dernière tentative (rien à
        #: relire tant que ça ne bouge pas : jamais de boucle à vide)
        self.tried: dict[str, int] = {}

    def _todo(self, state: SocialState, now: int, p: Any) -> list[tuple[int, str]]:
        return [(n, person) for n, person in _due(state, now, p)
                if self.tried.get(person) != state.mentions.get(person, 0)]

    def next_due(self, state: SocialState, frame: Frame, last_run: int | None) -> int | None:
        p = params(frame.env.params_of("social", frame.root))
        if self._todo(state, frame.now, p):
            return max(frame.now, self.retry_at)
        waiting = [pr.revised_at + p.profile_interval_us for person, pr in state.profiles.items()
                   if state.mentions.get(person, 0) - pr.mentions_at >= p.profile_min_items
                   and pr.revised_at + p.profile_interval_us > frame.now]
        return min(waiting) if waiting else None

    async def run(self, ctx: Any) -> None:
        frame: Frame = ctx.frame
        state: SocialState = ctx.state
        store = ctx.ports.get("store")
        if store is None or ctx.llm is None:
            return
        p = params(frame.env.params_of("social", frame.root))
        self.retry_at = frame.now + p.profile_retry_us  # si l'appel lève : pas de rafale
        for _neg, person in self._todo(state, frame.now, p)[: p.profile_per_run]:
            self.tried[person] = state.mentions.get(person, 0)
            # ce qu'elle a dit elle-même, ou ce que Mika a vu — jamais ce qu'un autre a confié sur elle
            only = json.dumps([person], ensure_ascii=False)
            # par importance, sans banalités ni répliques recopiées ; ce qui n'appartient qu'à elles deux (un surnom)
            # vit dans leur registre, pas dans la fiche
            her = self_c.name_of(frame.get(self_c.PERSONA))
            names = [frame.get(identity_c.IDENTITY(person)).name or "", her]
            rows = store.query_mind(
                f"SELECT id, text, importance FROM {memory_c.ITEMS_TABLE} WHERE about=? AND told_by IN ('[]', ?) "
                "AND status='active' AND kind IN (?, ?) AND between_us=0 ORDER BY importance DESC, id DESC LIMIT ?",
                (only, only, memory_c.SOUVENIR, memory_c.BELIEF, p.profile_max_items * 2))
            items = [r for r in rows if note_worthy(str(r[1]), names)][: p.profile_max_items]
            if not items:
                continue
            notes = _folded(" ".join(str(t) for _i, t, _imp in items))
            prompt = self._prompt(frame, state, person, items, store, notes)
            request = LLMRequest(role="profile", call_id=f"{ctx.run_id}#{person}", system_stable=system(her),
                                 messages=(Message("user", prompt),), tools=(tool(her),), max_tokens=900,
                                 lane="background", priority=3)
            response = await ctx.llm.call(request)
            got = parse(response)
            if got is None:
                continue
            summary = grounded(got.resume, notes)
            if not summary:
                continue  # rien qui tienne : la fiche d'avant reste
            tone = got.ton.strip()[:300]
            await ctx.emit(c.PROFILE_REVISED.draft(
                person=person, summary=Content.of(summary, level=int(Sensitivity.PERSONAL)),
                tone=Content.of(tone, level=int(Sensitivity.PERSONAL)) if tone else None,
                interests=_lines(_short(tastes(got.interets))), sensitive=_lines(_short(got.sujets_sensibles)),
                upto=max(int(i) for i, _t, _imp in items), call_id=request.call_id, model=response.model))
        self.retry_at = 0

    def _prompt(self, frame: Frame, state: SocialState, person: str, items: list[tuple[Any, ...]], store: Any,
                notes: str = "") -> str:
        view = frame.get(identity_c.IDENTITY(person))
        name = view.name or "cette personne"
        # ni comptes ni ressenti : un modèle qui voit « 15 messages » ou « de la sympathie » les recopie dans la
        # fiche (sonde du 2026-10-02 : « une connaissance récente de Mika, avec qui elle échange depuis 1 jour et
        # 15 messages », sous « fait partie de tes amis ») — la proximité se vit ailleurs (``faculty.lived``)
        lines = [f"Personne : {view.name or 'sans nom connu'}."]
        previous = state.profiles.get(person)
        if previous is not None:
            text = store.content([previous.summary_ref]).get(previous.summary_ref) if previous.summary_ref else None
            # ce qu'une fiche d'avant avait inventé ne se redonne pas à recopier (« célibataire »)
            text = grounded(text, notes) if text and notes else text
            if text:
                lines.append(f"Ce qu'elle en pensait jusqu'ici : {text}")
        lines.append("")
        her = self_c.name_of(frame.get(self_c.PERSONA))
        lines.append(f"Ce {elided(name, 'que')} lui a dit, et ce que {her} a vécu avec {name} :")
        lines += [f"- {text}" for _i, text, _imp in items]
        return "\n".join(lines)


#: Le registre de chaque lien (audit HUM-15) : rien ne traduisait la proximité en manière d'être — taquiner une
#: inconnue dès son premier message, ou parler à une proche comme à une cliente.
REGISTER = {
    c.STRANGER: "Tu ne la connais pas encore : reste accueillante et chaleureuse, mais ne la taquine pas et ne la "
                "charrie pas — la complicité viendra si vous apprenez à vous connaître.",
    c.ACQUAINTANCE: "Vous vous connaissez un peu : tu peux plaisanter gentiment, sans familiarité ni taquinerie "
                    "appuyée.",
    c.FRIEND: "Entre amis, vous pouvez vous charrier gentiment, plaisanter librement.",
    c.CLOSE: "Vous êtes proches : de la complicité, vos blagues à vous, tu peux la taquiner — et tu peux aussi être "
             "vraie avec elle quand ça ne va pas.",
}


def register(level: str) -> str:
    """Comment être avec elle, selon ce qui vous lie (jamais un nombre)."""
    return REGISTER.get(level, REGISTER[c.STRANGER])


def describe_level(level: str, name: str = "") -> str:
    """Ce qu'est la personne pour elle, en français, sans genre imposé : son prénom plutôt que « elle ou lui »."""
    who = f"« {name} »" if name else "Cette personne"
    if level == c.CLOSE:
        return f"{who} compte parmi tes proches."
    if level == c.FRIEND:
        return f"{who} fait partie de tes amis."
    if level == c.ACQUAINTANCE:
        return f"{who} est une connaissance."
    if name:
        return f"Tu ne connais pas encore vraiment « {name} »."
    return "Pour toi, c'est quelqu'un que tu ne connais pas encore."
