"""La faculté ``memory`` : sa tranche, ses paramètres, ses réducteurs, ses faits.

La tranche ne garde que des résumés (point de contrôle, messages pas encore
relus, promesses en cours et ce qu'elle a fait pour les tenir, moments de la
vie des autres à venir ou tout juste passés, situations en cours (et quand la
personne a dit qu'elles étaient finies), dates qui reviennent chaque année (jamais
évincées par l'âge : le fait ``LIFE_EVENTS`` les rend à leur prochaine
occurrence), la dernière
fois que quelque chose de grave a touché chacun) ; les
éléments retenus vivent dans la projection T0 ``memory_items`` et leurs
vecteurs dans l'index (un cache).

Qu'un moment ait été repris ne se déduit plus de ce qu'elle avait sous les
yeux : c'est un jugement enregistré (``moment_followed``, ``life.py``).
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field, replace
from datetime import datetime, time
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

from mika.contracts import agency as agency_c
from mika.contracts import attention as attention_c
from mika.contracts import expression as expression_c
from mika.contracts import identity as identity_c
from mika.contracts import mcp as mcp_c
from mika.contracts import memory as c
from mika.contracts import others as others_c
from mika.contracts import rss as rss_c
from mika.contracts import runtime as rt
from mika.contracts import social as social_c
from mika.kernel.builtin import SUBJECT_FORGOTTEN
from mika.kernel.clock import DAY, HOUR, MINUTE, instant, local
from mika.kernel.faculty import Faculty
from mika.kernel.forms import Knob
from mika.kernel.state import FrozenDict
from mika.vocab import causes
from mika.vocab.affect import Appraisal, Declared, Emotion, emotion_of, facets_valence, valence
from mika.vocab.episodes import Kind
from mika.vocab.people import is_identifiable

PENDING_CAP = 500
#: les initiatives en cours qui tiennent une promesse (corrélation → promesse), au plus
KEEPING_KEPT = 16
#: le sujet d'une initiative qui tient une promesse : ``promise:<id>``
PROMISE_SUBJECT = "promise:"
#: les personnes que quelque chose de grave a touchées, retenues au plus (les plus récentes)
HARD_KEPT = 64


def promise_of(subject: str | None) -> int | None:
    """La promesse que tient une initiative (``promise:12``), ou ``None``."""
    if not subject or not subject.startswith(PROMISE_SUBJECT) or not subject[len(PROMISE_SUBJECT):].isdigit():
        return None
    return int(subject[len(PROMISE_SUBJECT):])


class MemoryParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # consolidation : une fenêtre mûre (assez de messages) ou calme (plus rien depuis un moment)
    min_messages: Annotated[int, Knob(
        label="Messages pour une relecture", group="Consolidation", lo=1, hi=50,
        help="La conversation se relit (le modèle en tire souvenirs, croyances et promesses) dès qu'autant de "
             "messages de personnes attendent. Plus bas : davantage d'appels, sur des fenêtres plus courtes.")] = 6
    quiet_us: Annotated[int, Knob(
        label="Calme avant relecture", group="Consolidation", lo=MINUTE, hi=2 * HOUR,
        help="Sinon, elle se relit après ce délai sans nouveau message. Une question qui attend encore sa "
             "réponse n'est jamais relue sans elle.")] = 5 * MINUTE
    max_window: Annotated[int, Knob(
        label="Messages lus par relecture", group="Consolidation", lo=10, hi=300,
        help="Au plus autant de messages par appel d'extraction ; le reste attend la relecture suivante. Trop "
             "grand : un appel long et coûteux ; trop petit : un retard qui s'accumule.")] = 80
    retry_us: Annotated[int, Knob(
        label="Délai avant de réessayer", group="Consolidation", lo=MINUTE, hi=6 * HOUR,
        help="Après un appel d'extraction qui échoue (panne, réponse illisible), pas de nouvel essai avant ce "
             "délai : aucune rafale d'appels quand le fournisseur ne répond pas.")] = 10 * MINUTE
    max_attempts: Annotated[int, Knob(
        label="Essais avant de réduire les lots", group="Consolidation", lo=1, hi=10,
        help="Après autant de réponses illisibles, les conversations sont relues en lots plus petits. Une panne "
             "du fournisseur fait attendre la fenêtre au plus autant de passages, puis la met en file. Les passages "
             "en échec restent dans une file durable, sans bloquer les conversations suivantes.")] = 3
    dedup_similarity: Annotated[float, Knob(
        label="Seuil de doublon", group="Consolidation", lo=0.5, hi=1.0, step=0.01,
        help="Seuil pour rechercher un doublon candidat. Seuls les mêmes mots, personnes et confidents "
             "peuvent ensuite se renforcer ; une ressemblance seule ne fusionne rien.")] = 0.92
    # rappel
    recall_k: Annotated[int, Knob(
        label="Candidats cherchés", group="Rappel", lo=5, hi=200,
        help="Combien d'éléments (souvenirs, croyances, échanges passés) la recherche vectorielle remonte à chaque "
             "tour de conversation, avant le tri.")] = 40
    recall_floor: Annotated[float, Knob(
        label="Pertinence minimale", group="Rappel", lo=0.0, hi=1.5, step=0.01,
        help="Sous cette pertinence avec la conversation (la similarité des vecteurs, plus jusqu'à 0,35 quand "
             "l'élément contient les mots qui portent le sujet), un candidat ne revient pas tout seul ; la recherche "
             "délibérée (outil memory_search) tolère 20 % de moins. Trop bas : des souvenirs au hasard à chaque "
             "tour.")] = 0.45
    recall_margin: Annotated[float, Knob(
        label="Écart au meilleur candidat", group="Rappel", lo=0.0, hi=1.5, step=0.01,
        help="Quand un élément colle de très près à la conversation, ce qui en reste à plus de cet écart (en "
             "pertinence) ne revient pas : le rappel suit le sujet. Trop serré : deux souvenirs du même sujet, l'un "
             "mot pour mot et l'autre en partie, ne reviennent plus ensemble.")] = 0.5
    context_messages: Annotated[int, Knob(
        label="Messages qui orientent le rappel", group="Rappel", lo=1, hi=6,
        help="Le rappel cherche d'après le dernier message, et aussi d'après les quelques précédents de la même "
             "personne (ou du salon) : « et lui, il va mieux ? » se comprend avec ce qui précède.")] = 3
    strong_cue: Annotated[float, Knob(
        label="Indice qui réveille", group="Rappel", lo=0.3, hi=1.5, step=0.01,
        help="Un souvenir endormi revient quand même si la conversation lui est au moins aussi pertinente (ses "
             "mots, presque tous) : on n'oublie pas vraiment, il faut juste le bon indice.")] = 0.75
    max_souvenirs: Annotated[int, Knob(
        label="Souvenirs rappelés", group="Rappel", lo=0, hi=30,
        help="Au plus autant de souvenirs montrés au modèle à chaque tour, les mieux classés d'abord (pertinence, "
             "ce qu'il en reste, la personne en face).")] = 5
    max_beliefs: Annotated[int, Knob(
        label="Croyances rappelées", group="Rappel", lo=0, hi=40,
        help="Au plus autant de croyances (ce qu'elle sait) montrées au modèle à chaque tour.")] = 8
    max_chunks: Annotated[int, Knob(
        label="Échanges passés rappelés", group="Rappel", lo=0, hi=15,
        help="Au plus autant d'extraits d'échanges anciens, cités mot pour mot, parmi ceux que la personne a le "
             "droit d'entendre.")] = 3
    max_unsaid: Annotated[int, Knob(
        label="Ce qu'elle sait sans pouvoir le dire", group="Rappel", lo=0, hi=5,
        help="Quand la conversation touche ce qu'une autre personne lui a confié et qui ne se dit pas ici, elle "
             "sait au moins qu'elle sait — une ligne vague, sans rien du contenu (« Alice t'a confié des choses "
             "en privé : ce n'est pas à toi d'en parler »), au plus pour autant de personnes. Jamais en public.")] = 2
    max_promises: Annotated[int, Knob(
        label="Promesses montrées", group="Promesses", lo=1, hi=20,
        help="Au plus autant de promesses en cours dans « ce que tu lui as promis », les plus proches de leur "
             "échéance d'abord.")] = 5
    promise_horizon_days: Annotated[float, Knob(
        label="Échéance d'une promesse vague (jours)", group="Promesses", lo=1, hi=90,
        help="Une promesse faite sans date (« je te dirai ») reçoit cette échéance : passée, elle y repense, "
             "puis l'abandonne si rien ne vient.")] = 14.0
    promise_drop_days: Annotated[float, Knob(
        label="Abandon après l'échéance (jours)", group="Promesses", lo=0, hi=60,
        help="Une promesse ni tenue ni abandonnée s'oublie (abandonnée) ce temps après son échéance : rien ne "
             "reste dû pour toujours.")] = 7.0
    # tenir parole au moment dit : c'est dû (``agency.OWED``)
    promise_lead_us: Annotated[int, Knob(
        label="Tenir une promesse : un peu avant l'heure dite", group="Tenir parole", lo=0, hi=3 * HOUR,
        help="« Je te demanderai jeudi à 20 h comment ça s'est passé » : l'envie de le faire monte à partir de ce "
             "délai avant l'heure dite, et elle le fait d'elle-même — c'est dû, comme un rappel : ni budget, ni "
             "retenue, ni rancune. Une promesse sans date ne déclenche rien.")] = 30 * MINUTE
    promise_day_start_min: Annotated[int, Knob(
        label="Une promesse pour un jour : à partir de", group="Tenir parole", lo=0, hi=24 * 60,
        help="« Je t'envoie ça jeudi » (un jour sans heure) se tient dans la journée, à partir de cette heure "
             "locale (minutes depuis minuit) et avant le soir.")] = 10 * 60
    promise_day_end_min: Annotated[int, Knob(
        label="Une promesse pour un jour : son échéance", group="Tenir parole", lo=12 * 60, hi=24 * 60 - 1,
        help="… et son échéance est cette heure-là (minutes depuis minuit) : l'envie de la tenir est pleine à "
             "mi-chemin entre le début ci-dessus et cette heure, et elle peut encore la tenir « au plus tard après "
             "l'heure » au-delà — quelqu'un qu'elle ne voit que le soir l'entend quand même. En conversation, ce "
             "jour-là, c'est le moment de le faire dès le matin.")] = 20 * 60
    keep_evidence: Annotated[float, Knob(
        label="Tenir une promesse : preuve pleine", group="Tenir parole", lo=0.0, hi=12.0, step=0.5,
        help="La preuve (log-odds) à l'heure dite ; elle monte depuis 2 au début de la fenêtre (elle le fait à un "
             "moment ou à un autre de la fenêtre, pas à heure fixe). Au-dessus du seuil d'initiative (9), elle "
             "écrit seule.")] = 10.5
    keep_late_us: Annotated[int, Knob(
        label="Tenir une promesse : au plus tard après l'heure", group="Tenir parole", lo=0, hi=DAY,
        help="Passé ce délai après l'heure dite, elle ne le fait plus d'elle-même : elle sait qu'elle ne l'a pas "
             "fait (une pensée, après le délai de grâce de l'attention).")] = 2 * HOUR
    keep_attempts: Annotated[int, Knob(
        label="Tenir une promesse : essais", group="Tenir parole", lo=1, hi=5,
        help="Après autant d'essais qui n'ont rien dit (un silence choisi, une panne), elle ne le refait plus "
             "d'elle-même. Une initiative devancée (la personne a écrit) n'est pas un essai.")] = 2
    keep_retry_us: Annotated[int, Knob(
        label="Tenir une promesse : délai entre essais", group="Tenir parole", lo=MINUTE, hi=2 * HOUR,
        help="Après un essai qui n'a rien dit, pas de nouvel essai avant ce délai (multiplié par le nombre "
             "d'essais).")] = 10 * MINUTE
    event_ahead_days: Annotated[float, Knob(
        label="Moments à venir montrés (jours)", group="La vie des autres", lo=1, hi=60,
        help="Ce qui va arriver à la personne à qui elle parle (un entretien, un départ) lui revient quand c'est "
             "dans moins de tant de jours.")] = 7.0
    event_recent_days: Annotated[float, Knob(
        label="Moments passés à suivre (jours)", group="La vie des autres", lo=1, hi=30,
        help="Un moment passé depuis moins de tant de jours, dont elles n'ont pas encore reparlé (ni elle en lui "
             "demandant, ni la personne en le racontant), lui revient pour qu'elle demande comment ça s'est passé ; "
             "au-delà, il n'est plus suivi.")] = 3.0
    # ce qui vient (ADR 0084)
    likely_first_hand: Annotated[float, Knob(
        label="Vraisemblance : de la bouche de la personne", group="Ce qui vient", lo=0.3, hi=1, step=0.01,
        help="Ce qu'une personne dit de sa propre vie à venir (« jeudi, mon entretien ») : sa vraisemblance quand "
             "rien d'autre n'en est dit. Ce qu'elle en dit (« c'est pas sûr ») ne peut que l'abaisser.")] = 0.9
    likely_reported: Annotated[float, Knob(
        label="Vraisemblance : rapporté par un autre", group="Ce qui vient", lo=0.2, hi=1, step=0.01,
        help="Ce qu'on lui rapporte d'un autre, ou du monde, sans date officielle.")] = 0.7
    likely_official: Annotated[float, Knob(
        label="Vraisemblance : une date officielle", group="Ce qui vient", lo=0.5, hi=1, step=0.01,
        help="Une date publique officielle (un scrutin, un jour férié) : presque sûre.")] = 0.98
    likely_prediction: Annotated[float, Knob(
        label="Vraisemblance : une prévision", group="Ce qui vient", lo=0.1, hi=0.9, step=0.01,
        help="Ce que quelqu'un s'attend à voir arriver (« Léa pense qu'elle sera prise », « les taux vont "
             "remonter »), elle comprise : au plus autant qu'une déduction, quoi qu'en dise celui qui prévoit.")] = 0.6
    # ce qu'elle lit (ADR 0085)
    reread_max_readings: Annotated[int, Knob(
        label="Relecture : lectures relues par nuit", group="Ce qu'elle lit", lo=1, hi=100,
        help="La nuit, elle relit au plus tant de ses lectures (les plus anciennes d'abord) en un seul appel ; le "
             "reste attend la nuit suivante.")] = 30
    reread_max_items: Annotated[int, Knob(
        label="Relecture : ce qu'elle en garde au plus", group="Ce qu'elle lit", lo=1, hi=100,
        help="Ce qu'une relecture peut faire naître au plus (croyances, moments du monde, prévisions).")] = 30
    opinions_from_reading: Annotated[int, Knob(
        label="Relecture : ses avis par nuit", group="Ce qu'elle lit", lo=0, hi=10,
        help="Combien d'avis à elle (sur tout — politique, science, ce qui va arriver) une nuit de relecture peut "
             "former ou réviser, au plus. 0 : ce qu'elle lit ne lui forge pas d'avis.")] = 2
    confront_max_pairs: Annotated[int, Knob(
        label="La nuit confronte : paires au plus", group="Ce qu'elle lit", lo=0, hi=60,
        help="La nuit, elle confronte au plus tant de paires de croyances sur la même personne, dites par des "
             "témoins différents (la même chose dite deux fois ? deux versions qui se contredisent ?). 0 : rien.")] = 12
    confront_days: Annotated[float, Knob(
        label="La nuit confronte : depuis combien de jours", group="Ce qu'elle lit", lo=1, hi=60,
        help="Une croyance née depuis moins de tant de jours est confrontée à ce qu'elle savait déjà de la même "
             "personne.")] = 7.0
    learned_fresh_days: Annotated[float, Knob(
        label="Ce qu'elle a appris en lisant : fraîcheur (jours)", group="Ce qu'elle lit", lo=0.5, hi=14,
        help="Ce qu'elle a appris en lisant lui revient quand elle prend d'elle-même la parole ou travaille, pendant "
             "tant de jours — jamais redit à qui l'a déjà entendu.")] = 2.0
    # voir venir, constater (ADR 0086)
    resolve_days: Annotated[float, Knob(
        label="Constater : moments passés montrés (jours)", group="Voir venir, constater", lo=1, hi=60,
        help="Quand elle relit une conversation, elle voit les moments de ces personnes passés depuis moins de tant "
             "de jours dont elle ne sait pas comment ils ont tourné : si la personne le dit (« c'était super », « ça a "
             "été annulé »), c'est constaté.")] = 14.0
    resolve_grace_days: Annotated[float, Knob(
        label="Sans nouvelles : on ne saura pas après (jours)", group="Voir venir, constater", lo=1, hi=120,
        help="Un moment passé depuis plus de tant de jours sans que personne ne dise comment il a tourné : elle ne "
             "le saura pas — ni surprise, ni leçon.")] = 21.0
    track_min_cases: Annotated[int, Knob(
        label="Ce qu'elle apprend de qui annonce : à partir de (cas)", group="Voir venir, constater", lo=1, hi=20,
        help="Au moins tant de moments annoncés par la même personne, dont on a su comment ils ont tourné, avant "
             "que ses reports et annulations ne rendent ses prochaines annonces moins sûres.")] = 3
    track_weight: Annotated[float, Knob(
        label="Ce qu'elle apprend : poids de l'a priori", group="Voir venir, constater", lo=0.5, hi=20, step=0.5,
        help="Combien de cas « comme d'habitude » pèse l'a priori face à ce qu'elle a vu d'une personne : plus haut, "
             "elle change d'avis plus lentement.")] = 2.0
    surprise_from: Annotated[float, Knob(
        label="Surprise : à partir de", group="Voir venir, constater", lo=0, hi=1, step=0.01,
        help="L'écart entre ce qu'elle attendait et ce qui est arrivé, pesé par ce que le moment compte, au-delà "
             "duquel elle est surprise.")] = 0.2
    surprise_max: Annotated[float, Knob(
        label="Surprise : au plus", group="Voir venir, constater", lo=0, hi=1, step=0.01,
        help="L'intensité la plus forte d'une surprise devant ce qui est arrivé.")] = 0.4
    disappointment_max: Annotated[float, Knob(
        label="Espoir déçu, crainte levée : au plus", group="Voir venir, constater", lo=0, hi=1, step=0.01,
        help="L'intensité la plus forte de la tristesse d'un espoir déçu (un moment qu'elle attendait avec joie, "
             "annulé), ou du soulagement d'une crainte levée.")] = 0.3
    calibration_min: Annotated[int, Knob(
        label="Prudence : à partir de (moments constatés)", group="Voir venir, constater", lo=1, hi=50,
        help="Au moins tant de moments d'une même sorte (de la bouche de la personne, rapportés, officiels) dont on "
             "a su l'issue avant de juger si ses attentes tombaient juste.")] = 5
    calibration_cautious: Annotated[float, Knob(
        label="Prudence : au-delà de cet écart moyen", group="Voir venir, constater", lo=0, hi=1, step=0.01,
        help="L'écart quadratique moyen entre ce qu'elle attendait et ce qui est arrivé (score de Brier) au-delà "
             "duquel elle parle de ce qui vient avec des mots plus prudents. Le chiffre se lit dans la console, "
             "jamais dans ses phrases.")] = 0.2
    lived_importance: Annotated[float, Knob(
        label="Vécu à travers quelqu'un : importance", group="Voir venir, constater", lo=0, hi=1, step=0.05,
        help="Un moment partagé qui a eu lieu (« je te montrerai tout ») devient un souvenir à elle, de cette "
             "importance.")] = 0.6
    lived_owner_importance: Annotated[float, Knob(
        label="Vécu à travers sa propriétaire : importance", group="Voir venir, constater", lo=0, hi=1, step=0.05,
        help="Le même, vécu à travers sa propriétaire : plus marquant, comme si elle y était allée.")] = 0.85
    upcoming_days: Annotated[float, Knob(
        label="Ce qu'elle attend : jusqu'à combien de jours", group="Voir venir, constater", lo=0.5, hi=14,
        step=0.5, help="Un moment qui approche, à moins de tant de jours, peut se faire attendre (espoir, "
                       "inquiétude) ; plus loin, il ne se ressent pas encore.")] = 3.0
    check_days: Annotated[float, Knob(
        label="Vérifier : moments du monde passés depuis (jours)", group="Voir venir, constater", lo=0.5, hi=14,
        step=0.5, help="Un moment du monde qui lui tient à cœur, passé depuis moins de tant de jours sans qu'elle "
                       "sache comment il a tourné, peut lui donner envie d'aller vérifier.")] = 3.0
    check_importance: Annotated[float, Knob(
        label="Vérifier : à partir de cette importance", group="Voir venir, constater", lo=0, hi=1, step=0.05,
        help="Ce qui lui tient à cœur : un moment au moins aussi important, ou qu'elle attendait avec un "
             "sentiment.")] = 0.7
    ahead_days: Annotated[float, Knob(
        label="Ce qui vient : jusqu'à combien de jours", group="Ce qui vient", lo=1, hi=120,
        help="Un moment du monde, ou qu'elle vivra à travers quelqu'un, lui revient (« CE QUI VIENT ») quand il "
             "commence dans moins de tant de jours, ou qu'il dure encore. Une période (« en novembre ») compte "
             "depuis son début.")] = 21.0
    recurrence_days: Annotated[float, Knob(
        label="Une situation qui recommence (jours)", group="La vie des autres", lo=1, hi=365,
        help="Une situation finie depuis moins de tant de jours, qui recommence (« il est de nouveau malade »), "
             "est la même histoire, une autre fois : elle s'en souvient et le dit (« de nouveau »). Au-delà, c'est "
             "une autre histoire.")] = 60.0
    situation_days: Annotated[float, Knob(
        label="Situations en cours suivies (jours)", group="La vie des autres", lo=1, hi=60,
        help="Une situation qui dure dans la vie de quelqu'un (« mon chat Moustache est malade ») lui revient, "
             "pour qu'elle en prenne des nouvelles, pendant tant de jours après qu'elle a commencé.")] = 14.0
    situation_reask_days: Annotated[float, Knob(
        label="Situation : redemander après (jours)", group="La vie des autres", lo=0.5, hi=30, step=0.5,
        help="Après en avoir reparlé, elle ne redemande pas des nouvelles d'une situation avant tant de jours.")] = 3.0
    hard_days: Annotated[float, Knob(
        label="Quelque chose de grave : pendant (jours)", group="La vie des autres", lo=0, hi=30, step=0.5,
        help="Après un deuil, une rupture, une maladie (ce qu'elle a lu de grave dans ses messages, ou ce qui l'a "
             "profondément attristée pour la personne), les moments banals de sa vie se taisent pendant tant de "
             "jours — ni « comment s'est passé ton dentiste ? », ni « bonne chance » pour une course — et ce qui "
             "compte passe après des nouvelles d'elle. 0 : jamais.")] = 5.0
    hard_reply_from: Annotated[float, Knob(
        label="Grave : ce qui l'attriste au moins à ce point", group="La vie des autres", lo=0.3, hi=1.0, step=0.05,
        help="Une réponse, en privé, où elle se dit triste au moins à ce point (sa balise d'émotion) dit que ce "
             "que la personne lui a confié est grave, même sans un mot qui le nomme (« Pixel est parti »).")] = 0.75
    # oubli : l'importance s'estompe à la lecture, jamais par balayage
    dormant: Annotated[float, Knob(
        label="Seuil d'endormissement", group="Oubli", lo=0.0, hi=0.5, step=0.01,
        help="Un souvenir dont l'importance restante passe sous ce seuil ne revient plus tout seul. Il n'est pas "
             "effacé : la recherche délibérée le retrouve encore.")] = 0.03
    base_half_life_days: Annotated[float, Knob(
        label="Demi-vie de base (jours)", group="Oubli", lo=0.25, hi=90,
        help="La demi-vie d'un souvenir sans importance ; s'y ajoute la part due à l'importance (ci-dessous), et "
             "chaque rappel l'allonge de 25 % (jusqu'à quatre).")] = 3.0
    importance_half_life_days: Annotated[float, Knob(
        label="Demi-vie due à l'importance (jours)", group="Oubli", lo=0, hi=365,
        help="Ce qu'un souvenir d'importance 1 gagne de demi-vie en plus de la base (proportionnellement en "
             "dessous) : ce qui a compté s'efface bien plus lentement.")] = 27.0
    belief_half_life_days: Annotated[float, Knob(
        label="Demi-vie d'une croyance (jours)", group="Oubli", lo=7, hi=3650,
        help="La confiance d'une croyance diminue de moitié en ce temps si rien ne la renforce.")] = 180.0
    self_half_life_days: Annotated[float, Knob(
        label="Demi-vie de ce qu'elle raconte d'elle (jours)", group="Oubli", lo=0.5, hi=60,
        help="Ce qu'elle improvise sur sa vie (« j'ai ressorti mon fer à souder ») est gardé comme une note "
             "anodine qui s'efface en ce temps : assez pour ne pas se contredire d'un jour à l'autre, pas "
             "assez pour s'inventer un passé.")] = 3.0
    self_durable_half_life_days: Annotated[float, Knob(
        label="Demi-vie de ses goûts et avis (jours)", group="Oubli", lo=30, hi=3650,
        help="Ce qu'elle a dit de ce qu'elle aime, de ce qu'elle pense, de sa vie (« mon plat préféré, c'est les "
             "ramen ») tient bien plus longtemps : on ne change pas de plat préféré toutes les semaines. Quand elle "
             "change d'avis, la nouvelle croyance remplace l'ancienne.")] = 365.0
    bond_memory_gain: Annotated[float, Knob(
        label="Ce qui dure avec quelqu'un à qui elle tient", group="Oubli", lo=0.0, hi=5.0, step=0.1,
        help="Un souvenir vécu avec quelqu'un à qui elle tient s'endort moins vite : sa demi-vie est multipliée par "
             "1 + ce gain × l'attachement (une proche compte au moins pour 1, une amie pour ½). 0 : comme avec "
             "n'importe qui.")] = 2.0
    charged_from: Annotated[float, Knob(
        label="Un ressenti fort : à partir de", group="Oubli", lo=0.3, hi=1.0, step=0.05,
        help="Une émotion au moins aussi intense — ce que la personne ressent ou ce qu'elle-même en ressent, jugé "
             "par la relecture — fait d'un souvenir, d'une croyance ou d'un moment quelque chose qui se garde mieux "
             "(ci-dessous) : un moment chargé reste, comme chez tout le monde (ADR 0107).")] = 0.7
    charged_importance: Annotated[float, Knob(
        label="Un ressenti fort : importance au moins", group="Oubli", lo=0.0, hi=1.0, step=0.05,
        help="L'importance minimale de ce qu'un ressenti fort accompagne (0,7 : « important ») ; l'importance que "
             "la relecture a donnée l'emporte quand elle est plus haute. 0 : l'émotion n'y change rien.")] = 0.7
    landmark_importance: Annotated[float, Knob(
        label="Importance d'un moment marquant", group="Oubli", lo=0.5, hi=1.0, step=0.01,
        help="Un souvenir au moins aussi important ne s'endort jamais tout à fait (ci-dessous) : un deuil, un "
             "mariage restent à portée.")] = 0.9
    landmark_floor: Annotated[float, Knob(
        label="Ce qui reste d'un moment marquant", group="Oubli", lo=0.0, hi=0.5, step=0.01,
        help="Ce qu'il en reste ne descend jamais sous cette valeur ; au-dessus du seuil d'endormissement, il "
             "peut toujours revenir tout seul.")] = 0.05
    min_belief_confidence: Annotated[float, Knob(
        label="Confiance minimale", group="Oubli", lo=0.0, hi=0.9, step=0.01,
        help="Une croyance dont la confiance restante passe sous ce seuil ne revient plus toute seule "
             "(elle reste trouvable par la recherche délibérée).")] = 0.3
    # au rappel : la personne en face, l'anti-répétition
    person_boost: Annotated[float, Knob(
        label="Bonus de la personne en face", group="Rappel", lo=1.0, hi=3.0, step=0.05,
        help="Au rappel, un élément qui concerne la personne en face pèse autant de fois plus. Il ne fait "
             "qu'avancer ce qui est déjà admissible : il n'ouvre rien.")] = 1.25
    repetition_us: Annotated[int, Knob(
        label="Fenêtre anti-répétition", group="Rappel", lo=0, hi=12 * HOUR,
        help="Un élément déjà rappelé depuis moins longtemps que ça est pénalisé (ci-dessous), pour que le rappel "
             "tourne au lieu de resservir les mêmes souvenirs à chaque tour.")] = 30 * MINUTE
    repetition_penalty: Annotated[float, Knob(
        label="Pénalité de répétition", group="Rappel", lo=0.0, hi=1.0, step=0.05,
        help="Le poids d'un élément rappelé récemment est multiplié par ce facteur (1 : aucune pénalité).")] = 0.6
    max_self_said: Annotated[int, Knob(
        label="Ce qu'elle a déjà dit d'elle", group="Rappel", lo=0, hi=8,
        help="Quand on lui parle d'elle (« c'est quoi ton plat préféré ? »), au plus autant de ce qu'elle a déjà "
             "dit de ses goûts, de ses avis, de sa vie lui revient (« CE QUE TU AS DÉJÀ DIT DE TOI ») — les plus "
             "proches du message : elle ne se contredit pas.")] = 3
    person_recall_days: Annotated[float, Knob(
        label="Sa vie à elle : depuis (jours)", group="Rappel", lo=1, hi=90,
        help="Au premier mot d'une conversation (« salut ! »), ou quand elle écrit d'elle-même à quelqu'un, ce que "
             "cette personne lui a raconté de sa vie depuis moins de tant de jours lui revient — « et Moustache, il "
             "va mieux ? » —, sa fiche seulement si elle est ouverte. Une politesse ne réveille rien d'autre.")] = 14.0
    max_person_items: Annotated[int, Knob(
        label="Sa vie à elle : au plus", group="Rappel", lo=0, hi=10,
        help="Au plus autant de ces éléments (les plus importants et les plus frais d'abord).")] = 3
    # la nuit
    night_after_sleep_us: Annotated[int, Knob(
        label="Tri de la nuit après", group="La nuit", lo=0, hi=10 * HOUR,
        help="Une fois par nuit, ce temps après l'endormissement, elle fusionne les souvenirs presque identiques "
             "de la journée. Plus long que son sommeil : pas de tri cette nuit-là.")] = 3 * HOUR
    night_merge_similarity: Annotated[float, Knob(
        label="Similarité pour fusionner", group="La nuit", lo=0.5, hi=1.0, step=0.01,
        help="Deux souvenirs du jour au moins aussi proches se fusionnent pendant le tri. Trop bas : des "
             "moments distincts se confondent.")] = 0.9
    night_max_joins: Annotated[int, Knob(
        label="Croyances réunies par nuit, au plus", group="La nuit", lo=0, hi=500,
        help="La nuit, la même croyance dite par deux personnes et notée deux fois (avant que chaque façon de "
             "l'apprendre ne soit un témoignage) se réunit en une seule — au plus autant par nuit.")] = 50
    night_max_merges: Annotated[int, Knob(
        label="Fusions par nuit au plus", group="La nuit", lo=0, hi=200,
        help="Au plus autant de fusions par nuit (0 : aucun tri).")] = 20
    # raconter sans nommer (ADR 0091) : à qui n'a aucun lien connu avec la personne, ce qu'elle ne peut pas dire
    # nommément ici, dit sans qu'on puisse la reconnaître — jamais un secret
    veiled_max_shown: Annotated[int, Knob(
        label="Récits sans nom par réponse, au plus", group="Raconter sans nommer", lo=0, hi=5,
        help="Ce qu'elle peut raconter d'autres sans dire de qui il s'agit, montré dans une réponse (« une amie "
             "cherche du travail ») — à qui n'a aucun lien connu avec la personne, gradué par ce qu'elle sait de qui "
             "l'écoute. 0 : jamais.")] = 2
    veiled_per_person: Annotated[int, Knob(
        label="… et par personne, pour un même auditeur", group="Raconter sans nommer", lo=1, hi=10,
        help="De la même personne, à un même auditeur, au plus autant de récits sans nom sur la période ci-dessous : "
             "trois anecdotes sans nom sur la même amie finiraient par la dessiner.")] = 2
    veiled_fresh_days: Annotated[float, Knob(
        label="« Quoi de neuf ? » : ce qu'elle a appris depuis (jours)", group="Raconter sans nommer", lo=1, hi=60,
        help="Quand on lui demande des nouvelles, ce qu'elle a appris des autres depuis tant de jours peut se "
             "raconter sans nom.")] = 14.0
    veiled_keep_days: Annotated[float, Knob(
        label="Raconté sans nom, elle le garde sans nom (jours)", group="Raconter sans nommer", lo=1, hi=180,
        help="Ce qu'elle a raconté sans nom à quelqu'un lui revient comme tel pendant tant de jours : elle ne "
             "le redit pas comme une nouvelle, et elle ne donne pas le nom ensuite.")] = 30.0
    veiled_link_depth: Annotated[int, Knob(
        label="Un lien qui ferme : jusqu'à quel degré", group="Raconter sans nommer", lo=1, hi=2,
        help="1 : ce qui relie directement qui l'écoute à la personne (un salon, un nom, une relation…). 2 : aussi "
             "quelqu'un que leurs relations relient aux deux — une amie commune reconnaîtrait l'histoire même sans "
             "nom.")] = 2
    veiled_said_share: Annotated[float, Knob(
        label="Raconté : la part de ses mots qu'elle a vraiment dite", group="Raconter sans nommer", lo=0.1, hi=1.0,
        help="Ce que son prompt lui montrait n'est pas ce qu'elle a dit : un récit sans nom ne compte comme raconté "
             "(et gardé sans nom, et dans le budget) que si sa réponse en reprend au moins cette part des mots qui "
             "le portent. Plus haut : il faut qu'elle l'ait presque redit mot pour mot.")] = 0.5


@dataclass(frozen=True, slots=True)
class Reflection:
    """Une pensée restée forte, digérée cette nuit : un souvenir à écrire."""

    thought: int
    text_ref: str
    about: tuple[str, ...]
    sensitivity: int
    emotion: str


@dataclass(frozen=True, slots=True)
class Keeping:
    """Ce qu'elle a fait pour tenir une promesse : les essais qui n'ont rien dit, et quand réessayer."""

    attempts: int = 0
    retry_at: int = 0


@dataclass(frozen=True, slots=True)
class MemoryState:
    checkpoint: int = 0
    #: le dernier passage inscrit à la file de reprises (``seq``, 0 : jamais) : la consolidation relit la file
    #: quand il change (une reprise demandée par un opérateur, un passage différé)
    deferred_seq: int = 0
    life_seen: bool = False
    life_refreshed_at: int = 0
    #: messages de personnes pas encore relus (``seq``), les plus récents
    pending: tuple[int, ...] = field(default_factory=tuple)
    #: parmi eux, ceux qui ne lui étaient pas adressés (un salon : on parle entre soi)
    unaddressed: tuple[int, ...] = field(default_factory=tuple)
    last_message_at: int = 0
    items: int = 0
    index_revision: int = 0
    chunks: int = 0
    promises: FrozenDict[int, c.PendingPromise] = field(default_factory=FrozenDict)
    #: tenir une promesse au moment dit : les initiatives en cours (corrélation → (promesse, départ)), les essais,
    #: et les promesses qu'elle vient de tenir en le disant (le règlement suit, par ``memory.promises``)
    keeping: FrozenDict[str, tuple[int, int]] = field(default_factory=FrozenDict)
    tries: FrozenDict[int, Keeping] = field(default_factory=FrozenDict)
    kept: tuple[int, ...] = ()
    #: les moments de la vie des autres, à venir ou passés depuis peu ; les situations en cours
    events: FrozenDict[int, c.LifeEvent] = field(default_factory=FrozenDict)
    #: le fil de chaque moment qui n'est pas le sien (reporté, redit, revenu : numéro → fil), et le numéro sous
    #: lequel chaque fil est noté maintenant (fil → numéro) (ADR 0079)
    threads: FrozenDict[int, int] = field(default_factory=FrozenDict)
    heads: FrozenDict[int, int] = field(default_factory=FrozenDict)
    #: personne → la dernière fois que quelque chose de grave l'a touchée (un deuil, une rupture…)
    hard: FrozenDict[str, int] = field(default_factory=FrozenDict)
    reflections: tuple[Reflection, ...] = ()
    #: ses mensonges pas encore retenus (le ``seq`` de l'énoncé) : chacun devient un souvenir (``memory.lies``)
    lies: tuple[int, ...] = ()
    sorted_night: str = ""
    #: sa dernière lecture (``seq`` : ``rss.read``, ``mcp.consulted``) et la dernière nuit relue (ADR 0085)
    readings_upto: int = 0
    reread_night: str = ""
    #: ce qu'elle a vu de chacun qui annonce des moments : (tenus, reportés ou annulés) ; et ses attentes par sorte
    #: d'annonce : (combien, somme des carrés des écarts) — ce qu'elle apprend de ce qui arrive (ADR 0086)
    track: FrozenDict[str, tuple[int, int]] = field(default_factory=FrozenDict)
    calibration: FrozenDict[str, tuple[int, float]] = field(default_factory=FrozenDict)
    #: la dernière relecture journalisée (``seq``, instant), et les fenêtres
    #: abandonnées après trop d'échecs (combien, la dernière) : pour l'inspecteur
    consolidated_seq: int = 0
    consolidated_at: int = 0
    given_up: int = 0
    given_up_seq: int = 0


#: v4 : un moment repris est un jugement enregistré (``moment_followed``), plus « elle l'avait sous les yeux » ;
#: les situations en cours ; tenir une promesse au moment dit.
#: v5 : l'importance d'un moment, ce qui se fête, et ce qui touche gravement quelqu'un (ADR 0052).
#: v6 : une situation en cours prend fin quand la personne dit qu'elle est finie (``situation_ended``).
#: v7 : une date qui revient chaque année (``yearly``) n'est jamais évincée par l'âge, et a son propre plafond.
#: v10 : la file de reprises (``deferred_seq``) ; situations et dates archivées en SQL, la tranche en est le cache.
#: v11 : ses mensonges à retenir (``lies``, ADR 0076).
#: v12 : les fils des moments (``threads``, ``heads``) : reporté, redit, revenu, un moment reste le même (ADR 0079).
#: v16 : comment un moment a tourné (``outcome``), ce qu'elle apprend de qui annonce (``track``) et de ses attentes
#: (``calibration``) (ADR 0086).
#: v17 : l'oubli d'une personne emporte ce qu'elle lui avait promis et ce qui l'a touchée de grave ; un moment déplacé
#: compte à moitié dans ses attentes (``OUTCOME_VALUE``), comme dans la surprise.
MEMORY = Faculty("memory", state=MemoryState, init=lambda p: MemoryState(), params=MemoryParams, state_version=17)
MEMORY.declare(*c.ALL)


def params(p: MemoryParams | None) -> MemoryParams:
    return p if p is not None else MemoryParams()


@MEMORY.reducer(rt.PERCEPTION_RECEIVED)
def _perceived(s: MemoryState, e, cx) -> MemoryState:
    unaddressed = s.unaddressed if e.data.addressed else (*s.unaddressed, e.seq)[-PENDING_CAP:]
    return replace(s, pending=(*s.pending, e.seq)[-PENDING_CAP:], unaddressed=unaddressed, last_message_at=e.at)


def _hard(s: MemoryState, person: str, at: int) -> MemoryState:
    """Quelque chose de grave touche cette personne, à cet instant."""
    if not is_identifiable(person) or s.hard.get(person, 0) >= at:
        return s
    hard = s.hard.set(person, at)
    if len(hard) > HARD_KEPT:
        hard = FrozenDict(sorted(hard.items(), key=lambda kv: (kv[1], kv[0]))[-HARD_KEPT:])
    return replace(s, hard=hard)


#: au plus tant de mensonges en attente d'être retenus ; la marque de leur souvenir (``call_id`` : ``mensonge:<seq>``)
LIES_KEPT, LIE_MARK = 20, "mensonge"


@MEMORY.reducer(rt.UTTERANCE, reads=[identity_c.PERSON])
def _uttered(s: MemoryState, e, cx) -> MemoryState:
    """Ce qu'elle dit : un échange de plus à indexer — et, quand c'est l'initiative qui tient une promesse, la
    promesse est tenue (dite au moment dit ; ``memory.promises`` la règle). Qu'elle ait repris un moment de la vie
    de la personne ne se lit pas ici : c'est un jugement sur ses mots (``life.py``). Quand elle répond, en privé,
    profondément triste pour quelqu'un, ce qu'il lui a confié est grave (« Pixel est parti » : aucun mot ne le
    nomme, sa peine le dit)."""
    d = e.data
    if not d.visible:
        return s
    keeping = s.keeping.get(e.correlation)
    if keeping is not None:
        s = replace(s, keeping=s.keeping.delete(e.correlation))
        if keeping[0] in s.promises and keeping[0] not in s.kept:
            s = replace(s, kept=(*s.kept, keeping[0]))
    if d.target and is_identifiable(d.target) and d.annotation(expression_c.LIE_ANNOTATION) is not None \
            and e.seq not in s.lies:
        s = replace(s, lies=(*s.lies, e.seq)[-LIES_KEPT:])  # un mensonge : il deviendra un souvenir
    if d.kind == Kind.REPLY and d.target and d.room is None and is_identifiable(d.target):
        declared = Declared.decode(d.annotation(expression_c.EMOTION_ANNOTATION))
        floor = params(cx.params).hard_reply_from
        if declared is not None and any(e_ == Emotion.SAD.value and x >= floor for e_, x in declared.all):
            s = _hard(s, cx.facts.get(identity_c.PERSON(d.target)) or d.target, e.at)
    return replace(s, last_message_at=e.at, chunks=s.chunks + (1 if d.target and d.reply_to else 0))


@MEMORY.reducer(others_c.READ)
def _read_grave(s: MemoryState, e, cx) -> MemoryState:
    """Ce qu'elle a lu de grave dans un message (un deuil, une maladie, une rupture, une perte de travail, des mots
    de détresse) touche la personne qui l'a écrit."""
    return _hard(s, e.data.person, e.at) if e.data.grave else s


@MEMORY.reducer(rt.EPISODE_STARTED)
def _started(s: MemoryState, e, cx) -> MemoryState:
    """Une initiative part pour tenir une promesse (son sujet : ``promise:<id>``)."""
    d = e.data
    promise = promise_of(d.subject) if d.kind == Kind.INITIATIVE else None
    if promise is None or promise not in s.promises:
        return s
    keeping = s.keeping.set(e.correlation, (promise, e.at))
    if len(keeping) > KEEPING_KEPT:  # des épisodes jamais réglés : les identifiants sont chronologiques
        keeping = FrozenDict(sorted(keeping.items())[-KEEPING_KEPT:])
    return replace(s, keeping=keeping)


@MEMORY.reducer(rt.EPISODE_ENDED, reads=[agency_c.RENOUNCED])
def _ended(s: MemoryState, e, cx) -> MemoryState:
    """L'initiative qui devait tenir une promesse finit sans l'avoir dite : un silence choisi, une panne sont un
    essai (réessayer plus tard, pas indéfiniment) ; devancée, interrompue, ou un murmure sans suite (elle s'est
    ravisée), ce n'en est pas un (``agency.tried``)."""
    keeping = s.keeping.get(e.correlation)
    if keeping is None:
        return s
    s = replace(s, keeping=s.keeping.delete(e.correlation))
    promise, started = keeping
    if promise not in s.promises:
        return s
    p = params(cx.params)
    t = s.tries.get(promise) or Keeping()
    renounced = cx.facts.get(agency_c.RENOUNCED(e.data.target)) if e.data.target else 0
    if agency_c.tried(e.data.outcome, started, renounced):
        n = t.attempts + 1
        t = Keeping(n, e.at + p.keep_retry_us * n)
    else:
        t = replace(t, retry_at=e.at + p.keep_retry_us)
    return replace(s, tries=s.tries.set(promise, t))


@MEMORY.reducer(c.MOMENT_FOLLOWED)
def _followed(s: MemoryState, e, cx) -> MemoryState:
    """Un moment repris en mots, une fois passé : elle lui en a demandé des nouvelles, ou la personne lui en a
    parlé d'elle-même. Redit entre-temps (le même jour), le moment garde le suivi ; déplacé à une autre date, ce
    n'est plus l'occurrence reprise (ADR 0079)."""
    d = e.data
    ev = s.events.get(d.event)
    if ev is None:
        head = s.heads.get(d.thread or thread_of(s, d.event))
        ev = s.events.get(head) if head is not None else None
        if ev is None or (d.occurrence and ev.when != d.occurrence and not ev.yearly):
            return s
    return replace(s, events=s.events.set(ev.id, replace(ev, followed_at=e.at)))


def thread_of(s: MemoryState, item: int) -> int:
    """Le fil d'un moment, d'après l'un de ses numéros."""
    ev = s.events.get(item)
    if ev is not None and ev.thread:
        return ev.thread
    return s.threads.get(item, item)


def moment_thread(s: MemoryState, cx, item: int) -> int:
    return thread_of(s, int(item))


MEMORY.fact(c.MOMENT_THREAD)(moment_thread)


@MEMORY.reducer(c.RESOLVED)
def _moment_resolved(s: MemoryState, e, cx) -> MemoryState:
    """Comment un moment a tourné (ADR 0086) : il le garde ; et elle en apprend — de qui l'avait annoncé (un report,
    une annulation de plus, ou un moment tenu) et de ce qu'elle en attendait (sa calibration). Un moment dont on n'a
    jamais su l'issue n'apprend rien ; un moment déjà tranché ne se retranche pas."""
    d = e.data
    ev = s.events.get(d.event)
    if ev is None and d.thread:
        head = s.heads.get(d.thread)
        ev = s.events.get(head) if head is not None else None
    if ev is not None and ev.outcome:
        return s
    events = s.events.set(ev.id, replace(ev, outcome=d.outcome, resolved_at=e.at)) if ev is not None else s.events
    if d.outcome == c.UNKNOWN:
        return replace(s, events=events)
    track = s.track
    if d.teller:
        kept, missed = track.get(d.teller, (0, 0))
        track = track.set(d.teller, (kept + 1, missed) if d.outcome == c.HAPPENED else (kept, missed + 1))
    calibration = s.calibration
    if d.likelihood is not None and d.nature:
        n, squares = calibration.get(d.nature, (0, 0.0))
        # ce qui est arrivé, comme pour la surprise : déplacé, il aura lieu — à moitié
        happened = c.OUTCOME_VALUE[d.outcome]
        calibration = calibration.set(d.nature, (n + 1, round(squares + (d.likelihood - happened) ** 2, 6)))
    return replace(s, events=events, track=track, calibration=calibration)


@MEMORY.appraisal(c.RESOLVED, reads=[social_c.WEIGHT])
def _moment_resolved_felt(e, cx) -> list[Appraisal] | None:
    """Ce que l'issue d'un moment lui fait (ADR 0086) : surprise quand elle s'écarte de ce qu'elle attendait (pesée
    par ce que le moment compte) ; un espoir déçu attriste, une crainte levée soulage, une attente comblée réjouit
    un peu — davantage quand c'est un moment de sa propriétaire (``social.WEIGHT``). Ne pas savoir ne fait rien."""
    d = e.data
    if d.outcome == c.UNKNOWN:
        return None
    p = params(cx.params)
    out: list[Appraisal] = []
    # le moment de quelqu'un (pas du monde) : ce que vivent les autres suit la contagion du tempérament (ADR 0100)
    rel = bool(d.about)
    if d.surprise >= p.surprise_from:
        out.append(Appraisal(Emotion.SURPRISED, round(min(p.surprise_max, d.surprise), 3), reason=causes.TURNED_OUT,
                             relational=rel))
    counts = max((cx.facts.get(social_c.WEIGHT(person)) for person in d.about), default=1.0)
    weight = round(min(p.disappointment_max, abs(d.valence) * d.importance * counts), 3)
    if weight > 0 and d.valence > 0 and d.outcome in (c.CANCELLED, c.MOVED):
        out.append(Appraisal(Emotion.SAD, weight, reason=causes.LET_DOWN, relational=rel))
    elif weight > 0 and d.valence < 0 and d.outcome == c.CANCELLED:
        out.append(Appraisal(Emotion.RELIEVED, weight, reason=causes.FEAR_LIFTED, relational=rel))
    elif weight > 0 and d.valence > 0 and d.outcome == c.HAPPENED:
        out.append(Appraisal(Emotion.HAPPY, round(weight / 2, 3), reason=causes.AWAITED, relational=rel))
    return out or None


@MEMORY.reducer(c.SITUATION_ENDED)
def _situation_ended(s: MemoryState, e, cx) -> MemoryState:
    """Une situation qui durait est finie, de la bouche de la personne (« on a fini le déménagement », « on a dû
    l'endormir ») : elle reste notée, mais n'est plus « en ce moment ». La première fin dite compte."""
    ev = s.events.get(e.data.event)
    if ev is None or not ev.ongoing or ev.ended_at:
        return s
    return replace(s, events=s.events.set(ev.id, replace(ev, ended_at=e.at)))


@MEMORY.reducer(c.EXTRACTION_DEFERRED)
def _deferred(s: MemoryState, e, cx) -> MemoryState:
    return replace(s, deferred_seq=e.seq)


@MEMORY.reducer(c.CONSOLIDATED)
def _consolidated(s: MemoryState, e, cx) -> MemoryState:
    upto = max(s.checkpoint, e.data.upto)
    s = replace(s, checkpoint=upto, pending=tuple(q for q in s.pending if q > upto),
                unaddressed=tuple(q for q in s.unaddressed if q > upto), consolidated_seq=e.seq, consolidated_at=e.at)
    return replace(s, given_up=s.given_up + 1, given_up_seq=e.seq) if e.data.failed else s


@MEMORY.reducer(c.EVENT_NOTED)
def _noted(s: MemoryState, e, cx) -> MemoryState:
    """Un moment de la vie de quelqu'un : gardé tant qu'il est à venir ou passé
    depuis peu ; une situation en cours jusqu'à sa fin explicite ; une date qui
    revient chaque année, toujours. Le même
    moment renoté à la même date (la personne l'a dit elle-même après un tiers)
    reste repris s'il l'était ; une date qui change repart de zéro. Une
    situation finie, renotée, reste finie."""
    d = e.data
    p = params(cx.params)
    old = s.events.get(d.replaces) if d.replaces is not None else None
    followed = old.followed_at if old is not None and old.when == d.when else 0
    ended = old.ended_at if old is not None and old.ongoing and d.ongoing else 0
    events = s.events.delete(d.replaces) if d.replaces is not None else s.events
    # le fil : celui de ce qu'il remplace (reporté, redit) ou de la situation qu'il rouvre ; sinon le sien
    origin = d.replaces if d.replaces is not None else d.recurs
    thread = thread_of(s, origin) if origin is not None else e.seq
    events = events.set(e.seq, c.life_event_of(e.seq, d, followed_at=followed, ended_at=ended, thread=thread))
    if d.recurs is not None:
        events = events.delete(d.recurs)  # la situation finie laisse la place à celle qui recommence
    threads = s.threads.set(e.seq, thread) if thread != e.seq else s.threads
    s = replace(s, threads=_newest(threads, THREADS_KEPT), heads=_newest(s.heads.set(thread, e.seq), THREADS_KEPT))
    for i in [ev.id for ev in events.values() if not cached(ev, e.at, p)]:
        events = events.delete(i)
    return replace(s, items=s.items + 1, life_seen=True, events=life_cache(events))


def cached(ev: c.LifeEvent, at: int, p: MemoryParams) -> bool:
    """Ce que la tranche garde d'un moment à l'instant ``at`` : une date qui revient chaque année, toujours ; une
    situation en cours, ou finie depuis moins de ``event_recent_days`` ; un moment à venir, ou passé depuis moins que
    ça (une période, à sa fin — ADR 0084). Le reste vit dans l'archive : la relecture de sa vie ne l'y remet pas, ou
    chaque nouveau moment noté l'en chasserait, et chaque message le ferait revenir dans le journal."""
    if ev.yearly:
        return True
    keep_until = at - round(p.event_recent_days * DAY)
    if ev.ongoing:
        return not ev.ended_at or ev.ended_at >= keep_until
    return ev.ends >= keep_until


# L'archive SQL conserve tout ; cette tranche est seulement la mémoire de travail.
LIFE_CACHE_CAP = 2048
#: les fils retenus au plus (les plus récents) : un moment plus ancien est son propre fil, ou l'archive le dit
THREADS_KEPT = 4096


def _newest(table: FrozenDict[int, int], cap: int) -> FrozenDict[int, int]:
    if len(table) <= cap:
        return table
    return FrozenDict(sorted(table.items(), key=lambda kv: (kv[1], kv[0]))[-cap:])


def life_cache(events: FrozenDict[int, c.LifeEvent], keep: frozenset[int] = frozenset()) -> FrozenDict[int, c.LifeEvent]:
    if len(events) <= LIFE_CACHE_CAP:
        return events
    return FrozenDict(sorted(events.items(), key=lambda pair: (pair[0] in keep, pair[0]))[-LIFE_CACHE_CAP:])


@MEMORY.reducer(SUBJECT_FORGOTTEN)
def _forget_life(s: MemoryState, e, cx) -> MemoryState:
    """Oublier quelqu'un : ses moments, ses réflexions, ce qu'elle a appris de ses annonces — et ce qu'elle lui
    devait (une promesse dont le texte s'efface ne se tient plus d'elle-même), et ce qui l'a touché de grave."""
    person = e.data.subject
    gone = {i for i, pr in s.promises.items() if pr.to == person}
    return replace(s, events=FrozenDict((i, item) for i, item in s.events.items()
                                        if person not in (*item.about, *item.told_by)),
                   reflections=tuple(r for r in s.reflections if person not in r.about),
                   track=s.track.delete(person) if person in s.track else s.track,
                   promises=FrozenDict((i, pr) for i, pr in s.promises.items() if i not in gone),
                   tries=FrozenDict((i, t) for i, t in s.tries.items() if i not in gone),
                   kept=tuple(k for k in s.kept if k not in gone),
                   keeping=FrozenDict((k, v) for k, v in s.keeping.items() if v[0] not in gone),
                   hard=s.hard.delete(person) if person in s.hard else s.hard)


@MEMORY.reducer(c.LIFE_RECALLED)
def _life_recalled(s: MemoryState, e, cx) -> MemoryState:
    events = s.events
    for item in e.data.items:
        events = events.delete(item.id).set(item.id, item)
        if item.thread and item.thread != item.id:
            s = replace(s, threads=s.threads.set(item.id, item.thread), heads=s.heads.set(item.thread, item.id))
    return replace(s, events=life_cache(events, frozenset(item.id for item in e.data.items)), life_refreshed_at=e.at if e.data.daily else s.life_refreshed_at)


@MEMORY.reducer(c.REMEMBERED, c.BELIEVED)
def _retained(s: MemoryState, e, cx) -> MemoryState:
    """Un élément retenu de plus. Un souvenir ou une croyance marquant et douloureux pour la personne (un deuil vécu
    avec quelqu'un, un proche à l'hôpital) dit aussi que quelque chose de grave touche les personnes qu'il
    concerne."""
    d = e.data
    reflections = tuple(r for r in s.reflections if d.call_id != f"réflexion:{r.thought}")
    lies = tuple(seq for seq in s.lies if d.call_id != f"{LIE_MARK}:{seq}")
    s = replace(s, items=s.items + 1, reflections=reflections, lies=lies)
    if d.importance >= params(cx.params).landmark_importance:
        # ce que la personne en ressent d'abord (« son père est à l'hôpital » : elle est inquiète), sinon, pour un
        # souvenir, ce qu'elle-même a ressenti en le vivant (ADR 0083)
        mine = emotion_of(d.emotion) if e.type.name == c.REMEMBERED.name else None
        weight = facets_valence(d.felt) if d.felt else (valence(mine) if mine is not None else 0.0)
        if weight < 0:
            for person in d.about:
                s = _hard(s, person, e.at)
    return s


@MEMORY.reducer(c.REINFORCED, c.NIGHT_SORTED, c.PROMISE_RESOLVED, c.SITUATION_ENDED, c.ATTESTED, c.JOINED)
def _index_changed(s: MemoryState, e, cx) -> MemoryState:
    return replace(s, index_revision=e.seq)


@MEMORY.reducer(attention_c.DIGESTED)
def _digested(s: MemoryState, e, cx) -> MemoryState:
    """Ce qui est resté fort toute la journée, repensé la nuit, devient un souvenir."""
    new = tuple(Reflection(i.thought, i.text_ref, tuple(i.about), i.sensitivity, i.emotion)
                for i in e.data.items if i.reflective and i.text_ref)
    return replace(s, reflections=(*s.reflections, *new)[-20:]) if new else s


@MEMORY.reducer(c.NIGHT_SORTED)
def _sorted(s: MemoryState, e, cx) -> MemoryState:
    return replace(s, sorted_night=e.data.night)


@MEMORY.reducer(rss_c.READ, mcp_c.CONSULTED)
def _read(s: MemoryState, e, cx) -> MemoryState:
    """Elle a lu quelque chose : la nuit le relira (ADR 0085)."""
    return replace(s, readings_upto=max(s.readings_upto, e.seq))


@MEMORY.reducer(c.REREAD)
def _reread(s: MemoryState, e, cx) -> MemoryState:
    return replace(s, reread_night=e.data.night)


@MEMORY.reducer(c.PROMISE_NOTICED)
def _promised(s: MemoryState, e, cx) -> MemoryState:
    """Une promesse sans échéance (le journal d'avant l'horizon des promesses
    vagues) reçoit celle d'une promesse vague : rien n'est dû pour toujours."""
    due, implicit = e.data.due, e.data.implicit_due
    if due is None:
        due, implicit = e.at + round(params(cx.params).promise_horizon_days * DAY), True
    promise = c.PendingPromise(e.seq, e.data.to, due, e.at, implicit, all_day=e.data.all_day and not implicit,
                               work=e.data.work, text_ref=e.data.text.ref or "", sensitivity=e.data.sensitivity)
    return replace(s, items=s.items + 1, promises=s.promises.set(e.seq, promise))


@MEMORY.reducer(c.PROMISE_RESOLVED)
def _resolved(s: MemoryState, e, cx) -> MemoryState:
    promise = e.data.promise
    return replace(s, promises=s.promises.delete(promise), tries=s.tries.delete(promise),
                   kept=tuple(k for k in s.kept if k != promise))


@MEMORY.fact(c.CHECKPOINT)
def _checkpoint(s: MemoryState, cx) -> int:
    return s.checkpoint


def _speaks_for(cx, key: str, person: str) -> bool:
    """Une clé notée alors (une adresse, ``name:…``) désigne cette personne maintenant : une adresse reliée depuis à
    quelqu'un, un nom qu'un opérateur a relié à une personne parlent pour elle (ADR 0035, 0048)."""
    return key == person or (cx.facts.get(identity_c.PERSON(key)) or key) == person


@MEMORY.fact(c.PROMISES_TO, reads=[identity_c.PERSON])
def _promises_to(s: MemoryState, cx, person: str) -> tuple[c.PendingPromise, ...]:
    return tuple(p for p in s.promises.values() if _speaks_for(cx, p.to, person))


def day_of(t: int, tz: ZoneInfo) -> int:
    """Minuit (heure locale) du jour de cet instant."""
    return instant(datetime.combine(local(t, tz).date(), time(0, 0), tzinfo=tz))


def occurrence(ev: c.LifeEvent, now: int, tz: ZoneInfo, p: MemoryParams) -> c.LifeEvent:
    """Ce moment tel qu'il se présente à ``now`` : lui-même — sauf une date qui revient chaque année, passée depuis
    plus de ``event_recent_days`` : alors sa prochaine occurrence, le même jour à la même heure (un 29 février, le 28
    les autres années), jamais avant celle qui a été notée. L'avoir repris l'an dernier, ce n'est pas l'avoir repris
    cette année : ``followed_at`` d'avant le début de cette occurrence-là repart de zéro."""
    keep = round(p.event_recent_days * DAY)
    if not ev.yearly or now <= ev.when + keep:
        return ev
    first = local(ev.when, tz)
    for year in range(local(now, tz).year - 1, local(now, tz).year + 2):
        try:
            moment = first.replace(year=year)
        except ValueError:  # un 29 février, une année qui n'en a pas
            moment = first.replace(year=year, day=28)
        at = instant(moment)
        if at > ev.when and now <= at + keep:
            return replace(ev, when=at, followed_at=ev.followed_at if ev.followed_at >= day_of(at, tz) else 0)
    return ev


def events_at(s: MemoryState, now: int, tz: ZoneInfo, p: MemoryParams) -> list[c.LifeEvent]:
    """Les moments notés, tels qu'ils se présentent à ``now`` (une date qui revient chaque année : sa prochaine
    occurrence)."""
    return [occurrence(ev, now, tz, p) for ev in s.events.values()]


@MEMORY.fact(c.LIFE_EVENTS, reads=[identity_c.PERSON])
def _life_events(s: MemoryState, cx, person: str) -> tuple[c.LifeEvent, ...]:
    p = params(cx.params)
    events = (occurrence(ev, cx.now, cx.tz, p) for ev in s.events.values()
              if any(_speaks_for(cx, k, person) for k in ev.about))
    return tuple(sorted(events, key=lambda ev: (ev.when, ev.id)))


@MEMORY.fact(c.AHEAD)
def _ahead(s: MemoryState, cx) -> tuple[c.LifeEvent, ...]:
    """Ce qu'elle voit venir (ADR 0084) : les moments du monde et ceux qu'elle vivra à travers quelqu'un, pas finis,
    jusqu'à la fin de leur jour (ou de leur période)."""
    p = params(cx.params)
    ahead = [ev for ev in events_at(s, cx.now, cx.tz, p)
             if (ev.scope == c.WORLD or ev.shared) and not ev.ended_at and not ev.yearly and over(ev) >= cx.now
             and ev.outcome not in (c.CANCELLED, c.MOVED)]
    return tuple(sorted(ahead, key=lambda ev: (ev.when, ev.id)))


@MEMORY.fact(c.UPCOMING)
def _upcoming(s: MemoryState, cx) -> tuple[c.LifeEvent, ...]:
    """Ce qui approche (ADR 0086) : tout moment daté, pas encore tranché, qui commence d'ici ``upcoming_days`` ou se
    déroule — de quelqu'un, du monde, partagé."""
    p = params(cx.params)
    horizon = cx.now + round(p.upcoming_days * DAY)
    near = [ev for ev in s.events.values() if not ev.ongoing and not ev.ended_at and not ev.outcome
            and not ev.yearly and ev.when <= horizon and over(ev) >= cx.now]
    return tuple(sorted(near, key=lambda ev: (ev.when, ev.id)))


@MEMORY.fact(c.TO_CHECK)
def _to_check(s: MemoryState, cx) -> tuple[c.LifeEvent, ...]:
    """Ce qu'elle voudrait vérifier (ADR 0086) : un moment du monde passé depuis moins de ``check_days``, dont elle
    ne sait pas comment il a tourné, et qui lui tient à cœur — important, ou attendu avec un sentiment."""
    p = params(cx.params)
    since = cx.now - round(p.check_days * DAY)
    due = [ev for ev in s.events.values() if ev.scope == c.WORLD and not ev.outcome and not ev.yearly
           and since <= over(ev) < cx.now and (ev.importance >= p.check_importance or ev.empathy)]
    return tuple(sorted(due, key=lambda ev: (-ev.importance, -ev.when, ev.id)))


def over(ev: c.LifeEvent) -> int:
    """Quand un moment est passé : la fin de sa période ; la fin de son jour (minuit, pour un jour noté à 18 h) ; son
    heure, quand elle est dite."""
    if ev.vague:
        return ev.ends
    return ev.when + 6 * HOUR if ev.all_day else ev.when


def hard_since(s: MemoryState, keys: Collection[str], now: int, p: MemoryParams) -> int:
    """Quand quelque chose de grave a touché cette personne (l'une des clés qui la désignent), s'il y a moins de
    ``hard_days`` ; 0 sinon."""
    at = max((s.hard.get(k, 0) for k in keys), default=0)
    return at if at and 0 <= now - at <= round(p.hard_days * DAY) else 0


def heavy_day(s: MemoryState, cx, person: str, p: MemoryParams) -> int:
    """Le début de la journée, quand c'est aujourd'hui que revient une date lourde de cette personne (la date d'un
    deuil) qu'elle lui a confiée elle-même ; 0 sinon. Ce qu'un tiers en a dit ne fait pas d'elle quelqu'un de touché
    aux yeux de Mika."""
    today = day_of(cx.now, cx.tz)
    for ev in s.events.values():
        if not ev.yearly or not ev.told_by or not any(_speaks_for(cx, k, person) for k in ev.about) \
                or not all(_speaks_for(cx, t, person) for t in ev.told_by):
            continue
        this_year = occurrence(ev, cx.now, cx.tz, p)
        if c.heavy_date(this_year) and day_of(this_year.when, cx.tz) == today:
            return today
    return 0


@MEMORY.fact(c.HARD_TIMES, reads=[identity_c.PERSON])
def _hard_times(s: MemoryState, cx, person: str) -> int:
    p = params(cx.params)
    return max(hard_since(s, [k for k in s.hard if _speaks_for(cx, k, person)], cx.now, p),
               heavy_day(s, cx, person, p))
