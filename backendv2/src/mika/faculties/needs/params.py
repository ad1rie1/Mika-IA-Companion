"""Les réglages de ``needs`` : l'horizon de chaque besoin, ce que comble chaque chose et qui la donne, l'envie de
prendre la parole, de quoi parler, le vide ressenti — et ce que le tempérament en dérive (``derive``)."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict

from mika.contracts import social as social_c
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.forms import Knob
from mika.vocab.temperament import Temperament, around, geometric, lerp


class NeedsParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tau_social_h: Annotated[float, Knob(
        label="Horizon du besoin de compagnie", group="Horizons", lo=0.5, hi=24,
        help="Constante de temps de la montée du besoin de compagnie vers son maximum : plus courte, elle a vite "
             "envie de parler à quelqu'un. Dérivée de la sociabilité.")] = 4.0
    tau_expression_h: Annotated[float, Knob(
        label="Horizon du besoin de s'exprimer", group="Horizons", lo=0.5, hi=48,
        help="Constante de temps de la montée du besoin de s'exprimer : plus courte, elle a vite des choses à "
             "dire.")] = 6.0
    tau_curiosity_h: Annotated[float, Knob(
        label="Horizon de la curiosité", group="Horizons", lo=0.5, hi=48,
        help="Constante de temps de la montée de l'envie d'apprendre : plus courte, elle a vite envie de "
             "découvrir. Dérivée de la curiosité.")] = 8.0
    # ce que comble chaque chose (le niveau est multiplié par ce facteur)
    received_social: Annotated[float, Knob(
        label="Message reçu → compagnie", group="Ce qui comble", lo=0, hi=1, step=0.05,
        help="Un message qui lui est adressé multiplie son besoin de compagnie par ce facteur (0 : comblé d'un "
             "coup ; 1 : rien).")] = 0.3
    received_curiosity: Annotated[float, Knob(
        label="Message reçu → curiosité", group="Ce qui comble", lo=0, hi=1, step=0.05,
        help="Un message qui lui est adressé multiplie sa curiosité par ce facteur (0 : comblée d'un coup ; "
             "1 : rien).")] = 0.85
    said_social: Annotated[float, Knob(
        label="Parler à quelqu'un → compagnie", group="Ce qui comble", lo=0, hi=1, step=0.05,
        help="Chaque parole adressée à quelqu'un (réponse ou initiative) multiplie son besoin de compagnie par "
             "ce facteur.")] = 0.7
    # qui comble la compagnie : une amie ou une proche pleinement, les autres d'une part seulement (le facteur
    # effectif est ``1 − (1 − facteur) × part``)
    acquaintance_company: Annotated[float, Knob(
        label="Compagnie d'une connaissance", group="Ce qui comble", lo=0, hi=1, step=0.05,
        help="La part de ce que comble un échange (message reçu, parole dite) quand c'est avec quelqu'un qu'elle "
             "connaît un peu. Une amie ou une proche comble pleinement.")] = 0.6
    stranger_company: Annotated[float, Knob(
        label="Compagnie d'une inconnue", group="Ce qui comble", lo=0, hi=1, step=0.05,
        help="La même part, avec quelqu'un qu'elle ne connaît pas : un après-midi avec des inconnus ne remplace "
             "pas une amie.")] = 0.3
    hostile_company: Annotated[float, Knob(
        label="Compagnie de qui elle en veut", group="Ce qui comble", lo=0, hi=1, step=0.05,
        help="La même part, au plus, avec quelqu'un envers qui elle garde une hostilité installée (seuil "
             "ci-dessous) : se faire chahuter ne tient pas compagnie.")] = 0.1
    hostile_from: Annotated[float, Knob(
        label="Hostilité qui ne tient plus compagnie", group="Ce qui comble", lo=0.05, hi=1, step=0.05,
        help="À partir de cette hostilité installée envers la personne (affect, du même ordre que le seuil de "
             "rancune), ses échanges ne comblent plus que la part ci-dessus.")] = 0.2
    reply_expression: Annotated[float, Knob(
        label="Répondre → expression", group="Ce qui comble", lo=0, hi=1, step=0.05,
        help="Une réponse multiplie son besoin de s'exprimer par ce facteur.")] = 0.6
    initiative_expression: Annotated[float, Knob(
        label="Prendre la parole → expression", group="Ce qui comble", lo=0, hi=1, step=0.05,
        help="Une initiative (parler d'elle-même) multiplie son besoin de s'exprimer par ce facteur : bien plus "
             "qu'une réponse.")] = 0.2
    worked_expression: Annotated[float, Knob(
        label="Travailler → expression", group="Ce qui comble", lo=0, hi=1, step=0.05,
        help="Une séance sur un but, ou une exécution de projet dans son mode à elle, multiplie son besoin de "
             "s'exprimer par ce facteur : ce qu'elle y fait l'occupe et la dit un peu.")] = 0.8
    learned_curiosity: Annotated[float, Knob(
        label="Apprendre → curiosité", group="Ce qui comble", lo=0, hi=1, step=0.05,
        help="Une croyance nouvelle en mémoire, ou un pas d'exploration mené avec des outils, multiplie sa "
             "curiosité par ce facteur.")] = 0.8
    explored_curiosity: Annotated[float, Knob(
        label="Exploration aboutie → curiosité", group="Ce qui comble", lo=0, hi=1, step=0.05,
        help="Mener une exploration à bout (but atteint) multiplie sa curiosité par ce facteur.")] = 0.4
    occupied_expression: Annotated[float, Knob(
        label="S'occuper → expression", group="Ce qui comble", lo=0, hi=1, step=0.05,
        help="Une occupation dans sa chambre qui nourrit l'envie de s'exprimer (dessiner), menée au moins le temps "
             "ci-dessous, multiplie ce besoin par ce facteur quand elle s'arrête ; plus courte, au prorata du temps "
             "passé.")] = 0.6
    occupied_curiosity: Annotated[float, Knob(
        label="S'occuper → curiosité", group="Ce qui comble", lo=0, hi=1, step=0.05,
        help="La même chose pour une occupation qui nourrit sa curiosité (feuilleter un livre, regarder dehors) : "
             "deux minutes à la fenêtre ne la comblent presque pas.")] = 0.8
    occupied_full_us: Annotated[int, Knob(
        label="Une occupation comble tout ce qu'elle peut après", group="Ce qui comble", lo=5 * MINUTE, hi=8 * HOUR,
        help="Le temps passé à une occupation au-delà duquel elle comble pleinement (les deux facteurs ci-dessus) ; "
             "en deçà, au prorata.")] = HOUR
    # preuves d'initiative (log-odds) : de rien au seuil à tout à ``full``
    social_floor: Annotated[float, Knob(
        label="Envie de compagnie à partir de", group="Envie de prendre la parole", lo=0, hi=1, step=0.05,
        help="En dessous de ce niveau, le besoin de compagnie n'apporte aucune preuve d'initiative ; au-dessus, "
             "elle croît jusqu'au niveau « plein ».")] = 0.35
    social_evidence: Annotated[float, Knob(
        label="Preuve de l'envie de compagnie", group="Envie de prendre la parole", lo=0, hi=6, step=0.1,
        help="Preuve d'initiative (log-odds), vers quiconque est là, d'un besoin de compagnie plein. Plafonnée "
             "à 6 par l'arbitrage : elle s'ajoute aux autres raisons.")] = 6.0
    expression_floor: Annotated[float, Knob(
        label="Envie de s'exprimer à partir de", group="Envie de prendre la parole", lo=0, hi=1, step=0.05,
        help="Le même seuil pour le besoin de s'exprimer.")] = 0.3
    expression_evidence: Annotated[float, Knob(
        label="Preuve de l'envie de s'exprimer", group="Envie de prendre la parole", lo=0, hi=3, step=0.1,
        help="Preuve d'initiative (log-odds) d'un besoin de s'exprimer plein. Plafonnée à 3 par "
             "l'arbitrage.")] = 3.0
    full: Annotated[float, Knob(
        label="Niveau « plein »", group="Envie de prendre la parole", lo=0.05, hi=1, step=0.05,
        help="Le niveau d'un besoin (compagnie, expression) à partir duquel sa preuve d'initiative est "
             "maximale. À garder au-dessus des deux seuils.")] = 0.8
    # de quoi parler
    matterless_factor: Annotated[float, Knob(
        label="Sans matière, la preuve ne vaut plus que", group="De quoi parler", lo=0, hi=1, step=0.05,
        help="Une initiative que seule l'envie de compagnie ou de s'exprimer pousse, sans rien de concret à "
             "dire à cette personne (une pensée, ce qu'elle a fait, ce que la personne lui a raconté), ne garde "
             "que cette part de leur preuve : on n'écrit pas « pour rien ».")] = 0.4
    matter_thought_from: Annotated[float, Knob(
        label="Une pensée fait une matière dès", group="De quoi parler", lo=0, hi=1, step=0.05,
        help="Une pensée encore au moins aussi vive peut lancer une conversation.")] = 0.2
    matter_done_us: Annotated[int, Knob(
        label="Ce qu'elle a fait, pendant", group="De quoi parler", lo=HOUR, hi=7 * DAY,
        help="Ce qu'elle a fini (un but, un objectif de projet) ou une exécution de projet récente reste une "
             "matière pendant cette durée.")] = DAY
    matter_told_us: Annotated[int, Knob(
        label="Ce qu'on lui a raconté, pendant", group="De quoi parler", lo=HOUR, hi=30 * DAY,
        help="Ce que la personne lui a raconté d'elle (un souvenir, une croyance la concernant) reste une "
             "matière avec elle pendant cette durée.")] = 3 * DAY
    # le vide ressenti
    # ADR 0160 : quatre heures au milieu, rien d'inventé n'interrompt plus une journée calme
    idle_before_empty_us: Annotated[int, Knob(
        label="Inactivité avant le vide", group="Le vide", lo=15 * MINUTE, hi=DAY,
        help="Éveillée, sans message reçu, ni parole dite, ni travail depuis cette durée, elle ressent un vide : "
             "de l'ennui, ou de la solitude. Dérivée de l'optimisme : quatre heures au milieu ; rien d'inventé "
             "n'interrompt plus une journée calme.")] = 4 * HOUR
    empty_every_us: Annotated[int, Knob(
        label="Le vide se ressent toutes les", group="Le vide", lo=MINUTE, hi=6 * HOUR,
        help="Tant que le vide dure, il se ressent à nouveau à cet intervalle : un état tenu, pas une dent de "
             "scie.")] = 15 * MINUTE
    empty_intensity: Annotated[float, Knob(
        label="Intensité du vide, au début", group="Le vide", lo=0, hi=1, step=0.05,
        help="L'intensité de l'ennui ou de la solitude ressentis la première fois, sur son humeur générale. "
             "Dérivée de l'optimisme.")] = 0.15
    empty_growth_per_h: Annotated[float, Knob(
        label="Le vide se creuse de, par heure", group="Le vide", lo=0, hi=0.5, step=0.01,
        help="Chaque heure de vide de plus ajoute cette intensité (la solitude s'aggrave avec la durée), jusqu'au "
             "plafond.")] = 0.05
    empty_max: Annotated[float, Knob(
        label="Intensité du vide au plus", group="Le vide", lo=0, hi=1, step=0.05,
        help="Le vide ne dépasse jamais cette intensité : une longue solitude pèse, sans la faire sombrer.")] = 0.35
    lonely_from: Annotated[float, Knob(
        label="Solitude à partir de", group="Le vide", lo=0, hi=1, step=0.05,
        help="Si son besoin de compagnie atteint ce niveau, le vide se ressent comme de la solitude plutôt que "
             "de l'ennui.")] = 0.8
    reunited_gain: Annotated[float, Knob(
        label="Retrouver une amie après le vide", group="Le vide", lo=0, hi=2, step=0.05,
        help="Après un vide ressenti, le premier message de quelqu'un qu'elle connaît lui fait du bien : un "
             "soulagement (après la solitude) ou de la joie (après l'ennui), d'autant plus que le vide pesait — "
             "son intensité multipliée par ce facteur, et par sa proximité (ci-dessous). 0 : ça ne lui fait "
             "rien.")] = 0.8
    reunited_by_closeness: Annotated[social_c.ByCloseness, Knob(
        label="Retrouver quelqu'un, selon la proximité", group="Le vide", keys=social_c.CLOSENESS_NAMES,
        help="Ce que garde ce bien-être à chaque cran de leur lien, de 0 (rien) à 1 (entier) : une inconnue ne "
             "comble pas une solitude, une connaissance un peu.")] = {
        social_c.STRANGER: 0.0, social_c.ACQUAINTANCE: 0.5, social_c.FRIEND: 1.0, social_c.CLOSE: 1.0}
    matter_moment_ahead_us: Annotated[int, Knob(
        label="Ce qui va lui arriver, dans les", group="De quoi parler", lo=0, hi=7 * DAY,
        help="Un moment de sa vie qu'une personne lui a annoncé (un entretien, un départ) devient une matière "
             "pour lui écrire (un mot d'encouragement) dans cette durée avant qu'il arrive — et jusqu'à « ce "
             "qu'on lui a raconté, pendant » après. Jamais ce qu'un tiers lui en a dit.")] = 2 * DAY
    absence_paused: Annotated[bool, Knob(
        label="Ses absences ne creusent rien", group="Le vide",
        help="Le temps où son serveur était arrêté ne fait monter ni ses besoins ni le vide : à son retour, elle "
             "les retrouve là où elle les avait laissés. Décoché : ce silence compte comme vécu.")] = True


def derive(t: Temperament, overrides: Any = None) -> NeedsParams:
    """La sociabilité raccourcit l'horizon du besoin de compagnie ; la
    curiosité, celui d'apprendre ; l'optimisme repousse le vide et l'adoucit
    (au milieu : quatre heures, 0,15 au début) ; la timidité (ADR 0100) fait qu'une inconnue, une connaissance la
    comblent moins (au milieu : 0,3 et 0,6, les valeurs d'avant)."""
    values = {"tau_social_h": 4.0 * (1.5 - t.sociability), "tau_curiosity_h": 8.0 * (1.5 - t.curiosity),
              "idle_before_empty_us": round(geometric(2.0, 8.0, t.optimism) * HOUR),
              "empty_intensity": round(lerp(0.2, 0.1, t.optimism), 3),
              "stranger_company": around(t.shyness, 0.3, 0.5),
              "acquaintance_company": around(t.shyness, 0.6, 1 / 1.4)}
    values.update(dict(overrides or {}))
    return NeedsParams(**values)


def params(p: NeedsParams | None) -> NeedsParams:
    return p if p is not None else NeedsParams()
