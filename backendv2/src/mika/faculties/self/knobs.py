"""Les réglages de ``self`` : l'estime, ce qu'elle mène à bout, ce qu'on lui dit d'elle, ce qu'elle sait d'elle, le
récit, son journal, ses rêves, ses absences."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict

from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.forms import Knob


class SelfParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # l'estime : elle revient vers 0,5, bousculée par de petits coups ; elle ne touche jamais l'arbitrage
    esteem_half_life_us: Annotated[int, Knob(
        label="Demi-vie de l'estime", group="L'estime", lo=6 * HOUR, hi=30 * DAY,
        help="Son estime revient vers 0,5 en perdant la moitié de son écart en ce temps. Plus court : les coups "
             "s'oublient dans la journée ; plus long : un doute s'installe.")] = 72 * HOUR
    esteem_min: Annotated[float, Knob(
        label="Estime plancher", group="L'estime", lo=0.0, hi=0.5, step=0.01,
        help="Jamais sous ce plancher, quels que soient les coups : un échec n'est pas une dépression.")] = 0.05
    esteem_max: Annotated[float, Knob(
        label="Estime plafond", group="L'estime", lo=0.5, hi=1.0, step=0.01,
        help="Jamais au-dessus de ce plafond, quels que soient les succès.")] = 0.95
    ignored_knock: Annotated[float, Knob(
        label="Initiative ignorée", group="L'estime", lo=-0.3, hi=0.0, step=0.01,
        help="Ce que coûte à son estime une initiative restée sans réponse dans le délai attendu.")] = -0.03
    heard_again_knock: Annotated[float, Knob(
        label="Réponse après des ignorées", group="L'estime", lo=0.0, hi=0.3, step=0.01,
        help="Ce que lui rend une réponse qui rompt une série d'initiatives ignorées (« je compte "
             "encore »).")] = 0.04
    achieved_base: Annotated[float, Knob(
        label="But mené à bout : au moins", group="Ce qu'elle mène à bout", lo=0.0, hi=0.1, step=0.005,
        help="Ce que lui rend un but mené à bout même sans effort (un rappel dit ne compte pas).")] = 0.01
    achieved_effort: Annotated[float, Knob(
        label="But mené à bout : selon l'effort", group="Ce qu'elle mène à bout", lo=0.0, hi=0.3, step=0.005,
        help="En plus, selon ce que ça lui a demandé (ses séances de travail) et seulement s'il est prouvé "
             "(quelque chose a réellement été produit) : au plus autant.")] = 0.04
    achieved_full_steps: Annotated[int, Knob(
        label="Effort plein à partir de (séances)", group="Ce qu'elle mène à bout", lo=1, hi=20,
        help="À partir de tant de séances de travail, l'effort compte en entier ; une chose faite en une séance "
             "n'en compte qu'une part.")] = 4
    achieved_daily_cap: Annotated[float, Knob(
        label="Ce qu'elle mène à bout : au plus par jour", group="Ce qu'elle mène à bout", lo=0.0, hi=0.3,
        step=0.01, help="Ses réussites d'une même journée ne lui rendent pas plus que ça : dix petites choses "
                        "faites ne font pas une semaine de fierté.")] = 0.06
    stuck_knock: Annotated[float, Knob(
        label="But bloqué", group="Ce qu'elle mène à bout", lo=-0.3, hi=0.0, step=0.01,
        help="Ce que lui coûte un but sur lequel elle bloque ; renoncer par manque d'envie ne coûte rien.")] = -0.04
    broken_promise_knock: Annotated[float, Knob(
        label="Promesse non tenue", group="L'estime", lo=-0.3, hi=0.0, step=0.01,
        help="Ce que lui coûte une promesse dont l'échéance passe sans qu'elle l'ait tenue.")] = -0.03
    # le sociomètre : ce que les autres lui disent d'elle
    thanked_knock: Annotated[float, Knob(
        label="Un merci ou un compliment", group="Ce qu'on lui dit d'elle", lo=0.0, hi=0.1, step=0.005,
        help="Ce que lui rend un merci ou un compliment qui la vise, venant d'une amie ou d'une proche (moins "
             "venant de quelqu'un qu'elle connaît peu).")] = 0.02
    insulted_knock: Annotated[float, Knob(
        label="Une insulte qui la vise", group="Ce qu'on lui dit d'elle", lo=-0.1, hi=0.0, step=0.005,
        help="Ce que lui coûte une insulte qui la vise (« t'es nulle ») ; une moquerie qui rit ne compte pas.")] = \
        -0.02
    social_daily_cap: Annotated[float, Knob(
        label="Par personne et par jour : au plus", group="Ce qu'on lui dit d'elle", lo=0.0, hi=0.2, step=0.01,
        help="Ce que les mots d'une même personne font à son estime dans une journée, dans un sens ou dans "
             "l'autre : un troll qui insiste ne la démolit pas, une amie qui remercie dix fois ne la gonfle "
             "pas.")] = 0.04
    acquaintance_weight: Annotated[float, Knob(
        label="Venant d'une connaissance", group="Ce qu'on lui dit d'elle", lo=0.0, hi=1.0, step=0.05,
        help="La part qui compte quand ça vient de quelqu'un qu'elle connaît un peu.")] = 0.6
    stranger_weight: Annotated[float, Knob(
        label="Venant d'une inconnue", group="Ce qu'on lui dit d'elle", lo=0.0, hi=1.0, step=0.05,
        help="La part qui compte quand ça vient de quelqu'un qu'elle ne connaît pas.")] = 0.3
    apology_mend: Annotated[float, Knob(
        label="Des excuses adoucissent", group="Ce qu'on lui dit d'elle", lo=0.0, hi=1.0, step=0.05,
        help="Des excuses sincères (une fois par jour et par personne) lui rendent cette part de ce que les mots "
             "de cette personne avaient coûté à son estime ce jour-là. Des excuses qui rient (« pardon mdr ») ne "
             "comptent pas.")] = 0.5
    doubt_below: Annotated[float, Knob(
        label="Elle doute sous", group="L'estime", lo=0.0, hi=0.5, step=0.01,
        help="Sous ce seuil, son prompt lui dit qu'elle doute un peu d'elle-même (un ressenti, jamais un "
             "nombre).")] = 0.35
    assured_above: Annotated[float, Knob(
        label="Sûre d'elle au-dessus de", group="L'estime", lo=0.5, hi=1.0, step=0.01,
        help="Au-dessus de ce seuil, son prompt lui dit qu'elle se sent sûre d'elle, à sa place.")] = 0.7
    # le récit : « Je suis quelqu'un qui… », réécrit par sa propre voix
    narrative_every_us: Annotated[int, Knob(
        label="Réécrire le récit au plus toutes les", group="Le récit", lo=HOUR, hi=30 * DAY,
        help="Le paragraphe qu'elle écrit sur qui elle devient n'est pas réécrit plus souvent (un appel au "
             "modèle à chaque fois).")] = DAY
    narrative_stale_after_us: Annotated[int, Knob(
        label="Récit : réécrire après un changement, au plus tôt", group="Le récit", lo=MINUTE, hi=DAY,
        help="Quand un souvenir qu'il reprenait devient secret ou est remplacé, le récit se tait ou vieillit, et se "
             "réécrit sans le reprendre — au plus tôt tant après le précédent.")] = HOUR
    narrative_min_souvenirs: Annotated[int, Knob(
        label="Autant de souvenirs neufs valent un changement", group="Le récit", lo=1, hi=100,
        help="Pour réécrire son récit, ses souvenirs neufs comptent par paquets de cette taille ; ce qu'elle a dit "
             "d'elle qui la définit, un changement d'avis, un moment vécu à travers quelqu'un comptent un chacun ; ce "
             "qu'elle sait d'elle et ce qui la passionne, deux.")] = 5
    narrative_min_changes: Annotated[float, Knob(
        label="Réécrire le récit à partir de … changements", group="Le récit", lo=0.2, hi=20.0, step=0.1,
        help="Combien elle doit avoir changé depuis son dernier récit pour le réécrire (au plus une fois par "
             "période, ci-dessus). 1 : autant de souvenirs neufs qu'au-dessus suffisent, comme avant.")] = 1.0
    narrative_max_souvenirs: Annotated[int, Knob(
        label="Souvenirs relus pour le récit", group="Le récit", lo=5, hi=200,
        help="Les souvenirs anodins les plus marquants (importance, émotion) montrés à sa voix pour réécrire le récit "
             "— pas les plus récents : « allez j'y vais » ne dit rien de qui elle devient. Il est montré à tout le "
             "monde. Plus : un appel plus long.")] = 30
    narrative_lookback_us: Annotated[int, Knob(
        label="Le récit relit ce qu'elle a vécu depuis", group="Le récit", lo=DAY, hi=90 * DAY,
        help="Les souvenirs de cette période parmi lesquels le récit choisit les plus marquants ; ce qui l'a marquée "
             "sans pouvoir se raconter (une confidence, la peine d'une amie) n'y entre que par ce que ça lui a fait, "
             "sans qui ni quoi.")] = 14 * DAY
    # son journal
    heavy_day_from: Annotated[float, Knob(
        label="Une journée se dit « un peu lourde » à partir de", group="Son journal", lo=0.2, hi=5.0, step=0.1,
        help="Ce qu'elle raconte de sa journée à n'importe qui dit son ton, sans dire pourquoi : « un peu lourde » "
             "quand ce qui a pesé (ses émotions déclarées en parlant et ses pensées du jour, chacune de son "
             "intensité) atteint ce poids — même entre deux sourires ; « bonne » quand le léger l'atteint sans "
             "rien de lourd.")] = 1.0
    # les rêves
    dream_chance: Annotated[float, Knob(
        label="Rêver, à chaque sommeil paradoxal", group="Les rêves", lo=0.0, hi=1.0, step=0.05,
        help="La chance qu'un cycle de sommeil paradoxal donne un rêve (deux par nuit au plus).")] = 0.35
    dream_recall: Annotated[float, Knob(
        label="S'en souvenir au réveil", group="Les rêves", lo=0.0, hi=1.0, step=0.05,
        help="Au réveil, elle se souvient du rêve le plus vif de la nuit avec une chance de autant × sa "
             "vivacité — le double s'il vient de finir quand elle se réveille, ou si c'est un cauchemar. "
             "0,45 : une ou deux fois par semaine.")] = 0.45
    dream_recent_us: Annotated[int, Knob(
        label="Un rêve « tout frais » s'il finit moins de … avant le réveil", group="Les rêves", lo=0,
        hi=3 * HOUR, help="Un rêve de la fin de nuit, juste avant de se réveiller, se retient mieux.")] = \
        45 * MINUTE
    # ses absences : son serveur arrêté, de quand à quand
    absence_told_us: Annotated[int, Knob(
        label="Elle se sait revenue d'une absence, pendant", group="Ses absences", lo=0, hi=2 * DAY,
        help="Après un arrêt du serveur assez long pour compter (réglage du noyau), son prompt lui dit de quand à "
             "quand elle n'était pas là, pendant ce temps après son retour : elle n'a pas vécu ce silence, et rien "
             "de ce qui s'y est passé ne lui est parvenu. 0 : jamais.")] = 6 * HOUR

    # ce qu'elle sait d'elle (ADR 0088) : des tendances, d'après ses réussites et ses ratés récents ; jamais un nombre
    know_window_us: Annotated[int, Knob(
        label="Ce qu'elle sait d'elle se lit sur", group="Ce qu'elle sait d'elle", lo=7 * DAY, hi=90 * DAY,
        help="Tenir parole, mener au bout : elle juge sur ses promesses et ses buts de cette période.")] = 30 * DAY
    know_kept_from: Annotated[int, Knob(
        label="« Tu tiens parole » à partir de … promesses tenues", group="Ce qu'elle sait d'elle", lo=1, hi=20,
        help="Autant de promesses tenues à temps sur la période, et aucune laissée filer : une seule échue "
             "l'efface.")] = 3
    know_slipped_from: Annotated[int, Knob(
        label="« Tu laisses filer des promesses » à partir de", group="Ce qu'elle sait d'elle", lo=1, hi=20,
        help="Autant de promesses laissées filer (échues, ou tenues en retard) sur la période, et plus que de "
             "tenues.")] = 2
    know_done_from: Annotated[int, Knob(
        label="« Tu mènes au bout » à partir de … buts aboutis", group="Ce qu'elle sait d'elle", lo=1, hi=20,
        help="Autant de buts ou d'objectifs menés au bout sur la période, pour au plus la moitié de blocages "
             "(une rêverie, un rappel, un abandon ne comptent pas).")] = 3
    know_stuck_from: Annotated[int, Knob(
        label="« Tu bloques souvent » à partir de … blocages", group="Ce qu'elle sait d'elle", lo=1, hi=20,
        help="Autant de buts ou d'objectifs bloqués sur la période, et plus que d'aboutis.")] = 2
    foresight_window_us: Annotated[int, Knob(
        label="Ce qu'elle voit venir se juge sur", group="Ce qu'elle sait d'elle", lo=14 * DAY, hi=180 * DAY,
        help="Les moments dont elle a su comment ils ont tourné, sur cette période (ni les dates officielles, ni "
             "ce qu'elle n'a jamais su).")] = 60 * DAY
    foresight_min: Annotated[int, Knob(
        label="Il faut au moins … moments pour juger ce qu'elle voit venir", group="Ce qu'elle sait d'elle",
        lo=2, hi=50, help="En deçà, elle n'en sait rien.")] = 5
    foresight_right_below: Annotated[float, Knob(
        label="« Ce que tu vois venir tombe juste » sous l'écart", group="Ce qu'elle sait d'elle", lo=0.0, hi=0.3,
        step=0.01, help="L'écart moyen (au carré) entre ce qu'elle attendait et ce qui est arrivé : en deçà, ses "
                        "attentes tombent souvent juste.")] = 0.12
    foresight_off_above: Annotated[float, Knob(
        label="« Ce que tu vois venir tombe à côté » dès l'écart", group="Ce qu'elle sait d'elle", lo=0.1, hi=1.0,
        step=0.01, help="Au-delà, ses attentes tombent souvent à côté : elle le sait.")] = 0.30
    change_shown_us: Annotated[int, Knob(
        label="Un changement d'avis lui reste présent", group="Ce qu'elle sait d'elle", lo=0, hi=60 * DAY,
        help="Pendant ce temps après qu'elle a changé d'avis sur elle-même (un goût, un avis), son prompt le lui "
             "rappelle — avant, maintenant —, devant qui peut l'entendre. 0 : jamais.")] = 14 * DAY

    # ce qui la passionne (ADR 0089) : ses centres d'intérêt s'avivent et s'endorment ; d'autres naissent
    interest_half_life_us: Annotated[int, Knob(
        label="Un intérêt s'endort de moitié en", group="Ce qui la passionne", lo=2 * DAY, hi=120 * DAY,
        help="Sans rien qui le nourrisse (l'explorer, ce que ses flux en disent, ce qui s'y rattache), un centre "
             "d'intérêt perd la moitié de sa vivacité en ce temps.")] = 14 * DAY
    persona_glow: Annotated[float, Knob(
        label="Vivacité d'un intérêt de sa persona à son arrivée", group="Ce qui la passionne", lo=0.1, hi=1.0,
        step=0.05, help="Un centre d'intérêt écrit dans sa persona commence là.")] = 0.5
    persona_floor: Annotated[float, Knob(
        label="Plancher d'un intérêt de sa persona", group="Ce qui la passionne", lo=0.0, hi=0.5, step=0.01,
        help="Un centre d'intérêt de sa persona s'endort, il ne disparaît jamais : il ne descend pas sous ce "
             "plancher.")] = 0.12
    born_glow: Annotated[float, Knob(
        label="Vivacité d'un intérêt qui naît", group="Ce qui la passionne", lo=0.1, hi=1.0, step=0.05,
        help="Un sujet né de ce qu'elle a vécu commence là : un intérêt neuf est vif (au-dessus du seuil « vif »), "
             "quelques jours durant si rien ne le nourrit.")] = 0.75
    lived_drop_below: Annotated[float, Knob(
        label="Un intérêt vécu s'éteint sous", group="Ce qui la passionne", lo=0.0, hi=0.3, step=0.01,
        help="Un intérêt né de ce qu'elle a vécu, qui ne la nourrit plus, s'en va sous cette vivacité.")] = 0.05
    vivid_from: Annotated[float, Knob(
        label="Un intérêt est vif dès", group="Ce qui la passionne", lo=0.3, hi=1.0, step=0.05,
        help="Vif : il pèse double dans ce qu'elle choisit d'explorer.")] = 0.6
    asleep_below: Annotated[float, Knob(
        label="Un intérêt est endormi sous", group="Ce qui la passionne", lo=0.05, hi=0.5, step=0.01,
        help="Endormi : il pèse quatre fois moins dans ce qu'elle choisit d'explorer, et ses mots, moitié moins "
             "dans ce qu'elle remarque de ses flux.")] = 0.25
    explored_feed: Annotated[float, Knob(
        label="L'explorer l'avive de", group="Ce qui la passionne", lo=0.0, hi=1.0, step=0.01,
        help="Une exploration menée au bout (ou une rêverie) sur ce centre d'intérêt.")] = 0.25
    lead_feed: Annotated[float, Knob(
        label="Une piste qui s'y rattache l'avive de", group="Ce qui la passionne", lo=0.0, hi=0.5, step=0.01,
        help="La nuit, ce qu'elle a lu, trouvé, médité, qui revient à un de ses intérêts.")] = 0.1
    touch_feed: Annotated[float, Knob(
        label="Un titre qui le touche l'avive de", group="Ce qui la passionne", lo=0.0, hi=0.2, step=0.005,
        help="Un titre de ses flux qui en parle.")] = 0.03
    touch_daily_cap: Annotated[float, Knob(
        label="Ses flux l'avivent au plus de … par journée", group="Ce qui la passionne", lo=0.0, hi=0.5,
        step=0.01, help="Quarante titres sur le même sujet ne font pas une passion.")] = 0.1
    lead_keep_us: Annotated[int, Knob(
        label="Une piste se garde", group="Ce qui la passionne", lo=2 * DAY, hi=90 * DAY,
        help="Une piste qui ne s'est rattachée à rien, et n'a rien fait naître, s'en va passé ce temps.")] = 30 * DAY
    birth_min_leads: Annotated[int, Knob(
        label="Réfléchir à ce qui la passionne : au moins … pistes neuves", group="Ce qui la passionne", lo=2,
        hi=20, help="La nuit, elle ne se demande ce qui est en train de la passionner (un appel au modèle) qu'avec "
                    "autant de pistes neuves.")] = 3
    birth_min_days: Annotated[int, Knob(
        label="… venues d'au moins … journées", group="Ce qui la passionne", lo=1, hi=7,
        help="Une seule journée ne fait pas une passion : les pistes, et les preuves d'un sujet qui naît, doivent "
             "venir d'autant de journées.")] = 2
    birth_every_us: Annotated[int, Knob(
        label="Au plus un intérêt neuf tous les", group="Ce qui la passionne", lo=DAY, hi=60 * DAY,
        help="Un sujet qui naît par semaine, pas plus.")] = 7 * DAY
    lived_max: Annotated[int, Knob(
        label="Intérêts vécus, au plus", group="Ce qui la passionne", lo=0, hi=10,
        help="Combien d'intérêts nés de ce qu'elle a vécu vivent à la fois (ceux de sa persona en plus). 0 : aucun "
             "ne naît.")] = 3


def params(p: SelfParams | None) -> SelfParams:
    return p if p is not None else SelfParams()
