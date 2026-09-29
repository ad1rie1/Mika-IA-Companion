"""Les vues d'inspection du soi : l'estime (maintenant, et vers où elle va),
le récit d'elle-même, la persona et le tempérament ; ses nuits (journaux,
rêves).

Lecture seule, bornée ; un texte effacé par l'oubli se montre comme tel.
"""

from __future__ import annotations

from mika.contracts import identity as identity_c
from mika.contracts import self_ as c
from mika.faculties.self import SELF, SelfState, esteem, params
from mika.kernel.clock import HOUR
from mika.kernel.frame import Frame
from mika.kernel.inspect import Block, Cell, Fields, InspectContext, Note, Prose, Ref, Table
from mika.vocab import affect as A

SHOWN = 14
TEXT_MAX = 400
FORGOTTEN = "(oublié)"

TEMPERAMENT_FR = {
    "reactivity": "réactivité", "resilience": "résilience", "contagion": "contagion", "optimism": "optimisme",
    "sociability": "sociabilité", "curiosity": "curiosité", "perseverance": "persévérance",
    "chronotype": "chronotype (0 lève-tôt, 1 oiseau de nuit)",
}
DREAM_FR = {c.NIGHTMARE: "cauchemar", c.PLEASANT: "doux", c.ASSOCIATIVE: "étrange", c.MUNDANE: "banal"}


def number(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def clip(text: str, n: int = TEXT_MAX) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def feeling(name: str) -> str:
    e = A.emotion_of(name)
    return A.FR.get(e, name) if e is not None else (name or "—")


def names(frame: Frame, keys: tuple[str, ...]) -> str:
    out = [k[5:].title() if k.startswith("name:") else (frame.get(identity_c.IDENTITY(k)).name or k) for k in keys]
    return ", ".join(out) or "personne"


# ── Soi ───────────────────────────────────────────────────────────────────


def _esteem(s: SelfState, frame: Frame, ctx: InspectContext) -> Fields:
    p = params(frame.env.params_of("self", frame.root))
    now = esteem(s, frame.now, p)
    if now < p.doubt_below:
        word = "elle doute un peu d'elle"
    elif now > p.assured_above:
        word = "sûre d'elle"
    else:
        word = "ni doute ni assurance"
    if not s.esteem_at:
        trend = "au repos : jamais bousculée"
    elif abs(now - 0.5) < 0.005:
        trend = "revenue au repos"
    else:
        trend = "remonte vers 0,50" if now < 0.5 else "redescend vers 0,50"
    return Fields((
        ("maintenant", f"{number(now)} — {word}"),
        ("tendance", trend),
        ("au dernier coup", f"{number(s.esteem)}, le {ctx.when(s.esteem_at)}" if s.esteem_at else "—"),
        ("demi-vie du retour au repos", f"{p.esteem_half_life_us / HOUR:g} h"),
        ("bornes", f"{number(p.esteem_min)} – {number(p.esteem_max)}"),
    ), title="L'estime")


def _narrative(s: SelfState, frame: Frame, ctx: InspectContext) -> list[Block]:
    p = params(frame.env.params_of("self", frame.root))
    lived = s.souvenirs - s.narrated_souvenirs
    facts = Fields((
        ("écrit le", ctx.when(s.narrated_at) if s.narrated_at else "jamais"),
        ("souvenirs vécus depuis", f"{lived} (il en faut {p.narrative_min_souvenirs} pour le réécrire, "
                                   f"au plus une fois toutes les {p.narrative_every_us / HOUR:g} h)"),
    ), title="Son récit d'elle-même")
    if not s.narrative_ref:
        return [facts, Note("Elle ne s'est pas encore racontée.", tone="mut")]
    text = ctx.store.content([s.narrative_ref]).get(s.narrative_ref)
    return [facts, Prose(text if text else FORGOTTEN, title="« Je suis quelqu'un qui… »")]


def _persona(s: SelfState) -> list[Block]:
    doc = s.persona
    t = doc.temperament
    persona = Fields((
        ("nom", doc.name),
        ("révisions de la persona", s.revisions),
        ("langue", doc.language),
        ("fuseau", doc.timezone),
        ("ton", doc.tone or "—"),
    ), title="La persona")
    sliders = [(TEMPERAMENT_FR.get(name, name), number(float(getattr(t, name))))
               for name in type(t).model_fields if name != "background"]
    temperament = Table(("curseur", "valeur"), (*sliders, ("humeur de fond", feeling(t.background.value))),
                        title="Le tempérament (0,5 = comme la plupart des gens)")
    return [persona, temperament]


@SELF.inspect("soi", title="Soi")
def _inspect_self(s: SelfState, frame: Frame, ctx: InspectContext) -> list[Block]:
    return [_esteem(s, frame, ctx), *_narrative(s, frame, ctx), *_persona(s)]


# ── Nuits ─────────────────────────────────────────────────────────────────


@SELF.inspect("nuits", title="Nuits")
def _inspect_nights(s: SelfState, frame: Frame, ctx: InspectContext) -> list[Block]:
    journals = [j for _, j in sorted(s.journals.items(), reverse=True)][:SHOWN]
    dreams = sorted(s.dreams, key=lambda d: -d.id)[:SHOWN]
    texts = ctx.store.content([r for r in [*(j.text_ref for j in journals), *(d.text_ref for d in dreams)] if r])
    journal_rows: list[tuple[Cell, ...]] = [
        (j.day, clip(texts[j.text_ref]) if j.text_ref in texts else FORGOTTEN, feeling(j.dominant),
         names(frame, j.about), ctx.when(j.at)) for j in journals]
    dream_rows: list[tuple[Cell, ...]] = [
        (Ref("event", str(d.id), f"#{d.id}"), d.night, DREAM_FR.get(d.kind, d.kind), feeling(d.emotion),
         number(d.vividness), "oui" if d.recalled else "non", names(frame, d.about),
         clip(texts[d.text_ref]) if d.text_ref in texts else FORGOTTEN) for d in dreams]
    blocks: list[Block] = [
        Table(("journée", "journal", "dominante", "concerne", "écrit le"), tuple(journal_rows),
              title="Son journal", empty="pas encore de journal"),
    ]
    if journals:
        latest = journals[0]
        blocks.append(Prose(texts.get(latest.text_ref) or FORGOTTEN, title=f"Journal du {latest.day}, en entier"))
    blocks.append(Table(("n°", "nuit", "sorte", "couleur", "vivacité", "revenu au réveil", "concerne", "rêve"),
                        tuple(dream_rows), title="Ses rêves", empty="pas encore de rêve"))
    return blocks
