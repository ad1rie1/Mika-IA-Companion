"""Son caractère, écrit par le modèle d'après sa matrice (ADR 0100, 0139).

La matrice de personnalité règle la physique de ses émotions (chaque faculté en dérive ses paramètres) ; mais c'est
le modèle qui écrit ses mots et choisit sa balise d'émotion. Sans le lui dire, une Mika anxieuse ou tsundere aurait
les balises et les répliques d'une Mika au milieu partout. Ses 29 mesures, chacune avec ce qu'elle veut dire chez
elle (``told`` : « Introspection : 90 % — tu repenses longuement… », les phrases de ``self.temperament`` dans
``persona/voix.yaml``), ne vont plus au modèle qui parle : elles vont à celui qui **écrit son caractère** — six à
huit phrases, à la deuxième personne, qui disent ce que ses traits font ensemble (``self.character.system``). En
listes chiffrées, elle jouait ses traits un à un ; en phrases toutes faites, « anxieuse et sociable » restait la somme
de deux phrases. Le texte est journalisé (``self.character_written``) avec l'empreinte du tempérament qu'il décrit :
le processus ``self.character`` le réécrit dès que le tempérament change (un enregistrement dans la console, un
profil appliqué), et jamais autrement. Tant qu'il n'est pas écrit, sa persona ne dit rien de son caractère (pas de
repli : demandé par l'utilisateur le 2026-10-26). Ce que ses traits changent à sa façon d'écrire dans un chat reste
dit à part, en phrases toutes faites, dans « TA RÉPONSE » (``expression.marked_traits``) : des consignes mesurées au
banc, pas une description.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from mika.contracts import self_ as c
from mika.faculties.self.faculty import SELF, SelfState
from mika.kernel import forms
from mika.kernel.clock import DAY, MINUTE
from mika.kernel.events import VoiceProvenance
from mika.kernel.faculty import CatchUp
from mika.kernel.frame import Frame
from mika.ports.llm import LLMRequest, Message
from mika.vocab import temperament as T
from mika.vocab.affect import FR
from mika.vocab.phrasebook import phrase

#: un trait se dit avec sa phrase du bas à 40 % ou moins, du haut à 60 % ou plus ; entre les deux, comme la plupart
#: des gens. À 15 % ou moins, à 85 % ou plus, il est très marqué et le dit (le banc du tempérament : sans cela, le
#: modèle adoucissait les archétypes)
LOW, HIGH = 0.4, 0.6
VERY_LOW, VERY_HIGH = 0.15, 0.85
#: nettement marqué (0,3 ou moins, 0,7 ou plus) : ce que la console montre comme « ce qui la marque le plus »
CLEARLY = 0.2
_EPS = 1e-9
#: les familles de la matrice et le nom de leur titre (``self.temperament.family.*``)
FAMILIES = {T.FEEL: "feel", T.SHOW: "show", T.ACT: "act", T.OTHERS: "others", T.SELF: "self", T.BODY: "body"}
#: ses traits dans l'ordre de la matrice (famille, puis rang dans la famille) — ses précisions mises à part
_FIELDS = tuple(f for f in forms.describe(T.Temperament) if f.group in FAMILIES)
#: le texte écrit : au plus tant de caractères ; en dessous de tant, ce n'est pas un caractère (une balise, un refus)
CHARACTER_MAX, CHARACTER_MIN = 2000, 40
#: après un appel qui n'a rien donné (ou aucun modèle), le prochain essai : une minute, puis le double à chaque fois,
#: jusqu'à une fois par jour — un modèle qui répond mal ne se rappelle pas 1 440 fois par jour
RETRY_US, RETRY_MAX_US = MINUTE, DAY


def _lower(sentence: str) -> str:
    return sentence[:1].lower() + sentence[1:]


def _with(line: str, note: str) -> str:
    """Une ligne et la précision de son trait (« En particulier : … ») à sa suite."""
    note = note.strip().rstrip(".")
    return f"{line} {phrase('self.temperament.precisely', note=note)}" if note else line


def sentence(slider: str, value: float) -> str:
    """Ce que veut dire ce trait chez elle, à cette mesure."""
    if value <= LOW + _EPS:
        said = phrase(f"self.temperament.trait.{slider}.low")
    elif value >= HIGH - _EPS:
        said = phrase(f"self.temperament.trait.{slider}.high")
    else:
        return phrase("self.temperament.middle")
    if value <= VERY_LOW + _EPS or value >= VERY_HIGH - _EPS:
        said = f"{said} {phrase('self.temperament.marked')}"
    return said


def told(t: T.Temperament) -> list[str]:
    """Son tempérament ligne par ligne, dans l'ordre de la matrice : le titre de chaque famille, puis chacun de ses
    traits avec sa mesure et sa phrase, son humeur de fond, sa réaction, sa défense — chacun suivi de sa précision
    s'il y en a une (``notes``). Ce que lit le modèle qui écrit son caractère."""
    out: list[str] = []
    family = ""
    for field in _FIELDS:
        if field.group != family:
            family = field.group
            out.append(phrase(f"self.temperament.family.{FAMILIES[family]}"))
        key = field.path
        value = getattr(t, key)
        if key == "background":
            line = phrase("self.temperament.background", feeling=FR[value])
        elif key in ("reaction", "defense"):
            line = phrase(f"self.temperament.trait.{key}.{value or 'none'}")
        else:
            line = phrase("self.temperament.line", name=phrase(f"self.temperament.name.{key}"),
                          pct=round(float(value) * 100), sentence=_lower(sentence(key, float(value))))
        out.append(f"- {_with(line, t.notes.get(key, ''))}")
    return out


def request_for(doc: c.PersonaDoc, call_id: str) -> LLMRequest:
    """L'appel qui écrit son caractère : la consigne, puis ses traits mesurés."""
    return LLMRequest(role="character", call_id=call_id,
                      system_stable=phrase("self.character.system", name=c.name_of(doc)),
                      messages=(Message("user", phrase("self.character.message",
                                                       lines="\n".join(told(doc.temperament)))),),
                      max_tokens=700, lane="background", priority=2)


def written(raw: str | None) -> str:
    """Le caractère tel qu'il se garde : le texte seul, coupé avant une balise qu'un modèle de voix aurait ajoutée
    par habitude ; « » si ce n'en est pas un (vide, une balise, un refus en un mot)."""
    text = (raw or "").strip()
    cut = text.find("\n[")
    if cut > 0:
        text = text[:cut].rstrip()
    if len(text) < CHARACTER_MIN or text[0] in "[{":
        return ""
    return text[:CHARACTER_MAX]


@SELF.reducer(c.CHARACTER_WRITTEN)
def _written(s: SelfState, e, cx) -> SelfState:
    d = e.data
    return replace(s, character=d.text, character_hash=d.temperament, character_at=e.at, character_model=d.voice.model)


@SELF.fact(c.CHARACTER)
def _character(s: SelfState, cx) -> str:
    """Son caractère écrit, s'il décrit le tempérament courant ; sinon rien."""
    return s.character if s.character and s.character_hash == c.temperament_hash(s.persona.temperament) else ""


@SELF.process("self.character", wake_on=[c.PERSONA_REVISED], priority=10, lane="background", catch_up=CatchUp.ONCE,
              max_quantum_s=600)
class WriteCharacter:
    """Écrit son caractère dès que son tempérament n'a pas le sien : au démarrage d'une vie, après un enregistrement
    dans la console, un profil appliqué. Un appel qui ne donne rien (ou qui lève, ou aucun modèle) se retente en
    reculant : une minute, deux, quatre… jusqu'à une fois par jour ; un tempérament qui change remet le compte à
    zéro."""

    def __init__(self) -> None:
        self.retry_at = 0
        self.tries = 0
        self.tried_for = ""  # l'empreinte du tempérament que les essais visent

    def next_due(self, state: SelfState, frame: Frame, last_run: int | None) -> int | None:
        wanted = c.temperament_hash(state.persona.temperament)
        if state.character_hash == wanted and state.character:
            return None
        if wanted != self.tried_for:
            self.tried_for, self.tries, self.retry_at = wanted, 0, 0
        return max(frame.now, self.retry_at)

    def _back_off(self, now: int) -> None:
        self.tries += 1
        self.retry_at = now + min(RETRY_US * 2 ** (self.tries - 1), RETRY_MAX_US)

    async def run(self, ctx: Any) -> None:
        self._back_off(ctx.frame.now)  # si l'appel lève ou ne donne rien : pas de rafale
        serving = getattr(ctx.llm, "serving", None)
        if ctx.llm is None or (callable(serving) and not serving("character")):
            return  # aucun modèle ne sert ce rôle (ni par repli) : rien à tenter, la console le dit
        state: SelfState = ctx.state
        doc = state.persona
        request = request_for(doc, f"{ctx.run_id}#0")
        response = await ctx.llm.call(request)
        text = written(response.text)
        if not text:
            return
        self.tries, self.retry_at = 0, 0
        # écrit sans persona (le rôle n'en porte pas) : ``persona_hash`` reste vide
        await ctx.emit(c.CHARACTER_WRITTEN.draft(
            text=text, temperament=c.temperament_hash(doc.temperament),
            voice=VoiceProvenance(call_id=request.call_id, persona_hash="", role="character", model=response.model)))
