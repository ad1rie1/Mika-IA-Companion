"""Les réglages de ``memory`` (``MemoryParams``), en douze groupes, dans l'ordre où la console les montre : la
consolidation, le rappel, ses promesses et les tenir, la vie des autres et ce qui vient, ce qu'elle lit, ce qu'on lui
montre d'un téléphone, voir venir et constater, l'oubli, la nuit, raconter sans nommer.

``params`` rend les réglages qu'on lui donne, ou ceux par défaut s'il n'y en a pas. La faculté les déclare
(``Faculty(params=MemoryParams)``, ``faculty.py``) ; chaque module de la mémoire les lit d'ici."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict

from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.forms import Knob


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
             "délai : aucune rafale d'appels quand le fournisseur ne répond pas. Vaut pour la relecture de ses "
             "conversations et pour celle des messages reçus sur un téléphone.")] = 10 * MINUTE
    max_attempts: Annotated[int, Knob(
        label="Essais avant de réduire les lots", group="Consolidation", lo=1, hi=10,
        help="Après autant de réponses illisibles, les conversations sont relues en lots plus petits. Une panne "
             "du fournisseur fait attendre la fenêtre au plus autant de passages, puis la met en file ; de même "
             "pour les messages reçus sur un téléphone, dont les lots, eux, ne se réduisent pas. Les passages en "
             "échec restent dans une file durable, sans bloquer les conversations suivantes.")] = 3
    dedup_similarity: Annotated[float, Knob(
        label="Seuil de doublon", group="Consolidation", lo=0.5, hi=1.0, step=0.01,
        help="Seuil pour rechercher un doublon candidat (similarité centrée : 0 sans rapport, 1 identique). "
             "Seuls les mêmes mots, personnes et confidents peuvent ensuite se renforcer ; une ressemblance seule "
             "ne fusionne rien.")] = 0.9
    # rappel
    recall_k: Annotated[int, Knob(
        label="Candidats cherchés", group="Rappel", lo=5, hi=200,
        help="Combien d'éléments (souvenirs, croyances, échanges passés) la recherche vectorielle remonte à chaque "
             "tour de conversation, avant le tri.")] = 40
    recall_floor: Annotated[float, Knob(
        label="Pertinence minimale", group="Rappel", lo=0.0, hi=1.5, step=0.01,
        help="Sous cette pertinence avec la conversation (la similarité des vecteurs, centrée : 0 pour un texte "
             "sans rapport, 1 pour l'identique ; plus jusqu'à 0,35 quand l'élément contient les mots qui portent le "
             "sujet), un candidat ne revient pas tout seul ; la recherche délibérée (outil memory_search) tolère "
             "20 % de moins. Trop bas : des souvenirs au hasard à chaque tour.")] = 0.35
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
             "mots, presque tous) : on n'oublie pas vraiment, il faut juste le bon indice.")] = 0.65
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
    # ADR 0127 : la borne du texte relu par nuit, et celle d'un extrait
    reread_max_chars: Annotated[int, Knob(
        label="Relecture : texte relu par nuit", group="Ce qu'elle lit", lo=2_000, hi=400_000, step=1_000,
        help="Le texte de ses lectures (titres et extraits) qu'une nuit de relecture reprend au plus, en caractères : "
             "au-delà, le reste attend la nuit suivante. Sans cette borne, trente pages lues en entier dépassaient le "
             "contexte du modèle, et le même lot échouait chaque nuit.")] = 60_000
    reread_excerpt_chars: Annotated[int, Knob(
        label="Relecture : extrait d'une lecture", group="Ce qu'elle lit", lo=200, hi=20_000, step=100,
        help="Ce qu'elle relit au plus d'une seule lecture, en caractères : une page entière se coupe là.")] = 3_000
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
        help="Ce qu'elle a appris en lisant lui revient quand elle parle (qu'elle réponde ou prenne d'elle-même la "
             "parole) ou travaille, pendant tant de jours — jamais redit à qui l'a déjà entendu.")] = 2.0
    # ce qu'on lui montre de son téléphone (ADR 0120)
    relayed_quiet_us: Annotated[int, Knob(
        label="Messages du téléphone : relus après un calme de", group="Ce qu'on lui montre", lo=MINUTE, hi=DAY,
        help="Les messages reçus sur un téléphone se relisent quand plus rien n'est arrivé depuis ce temps : une "
             "conversation se relit posée, pas message par message.")] = 20 * MINUTE
    relayed_wait_us: Annotated[int, Knob(
        label="Messages du téléphone : attendus au plus", group="Ce qu'on lui montre", lo=10 * MINUTE, hi=3 * DAY,
        help="Un message reçu attend au plus ce temps d'être relu, même si d'autres continuent d'arriver.")] = 2 * HOUR
    relayed_per_run: Annotated[int, Knob(
        label="Messages du téléphone : conversations par passage", group="Ce qu'on lui montre", lo=1, hi=20,
        help="Au plus tant de conversations relues à chaque passage (un appel au modèle chacune) ; les autres "
             "attendent le suivant.")] = 4
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
    # ADR 0107 : un ressenti fort fait d'un élément quelque chose qui se garde mieux
    charged_from: Annotated[float, Knob(
        label="Un ressenti fort : à partir de", group="Oubli", lo=0.3, hi=1.0, step=0.05,
        help="Une émotion au moins aussi intense — ce que la personne ressent ou ce qu'elle-même en ressent, jugé "
             "par la relecture — fait d'un souvenir, d'une croyance ou d'un moment quelque chose qui se garde mieux "
             "(ci-dessous) : un moment chargé reste, comme chez tout le monde.")] = 0.7
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
        help="Deux souvenirs du jour au moins aussi proches (similarité centrée) se fusionnent pendant le tri, "
             "s'ils ont les mêmes mots et les mêmes personnes. Trop bas : des moments distincts se "
             "confondent.")] = 0.87
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


def params(p: MemoryParams | None) -> MemoryParams:
    return p if p is not None else MemoryParams()
