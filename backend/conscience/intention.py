"""Ce qu'elle s'apprête à faire, et pourquoi — dit en une phrase.

Deux consommateurs lisent la même chose : le murmure (l'intention, avant
l'acte) et le prompt de l'acte (le vécu, tous les motifs à la fois). Ils
partagent ``declencheurs`` pour ne pas diverger — elle murmurerait sinon une
intention que le prompt ne mentionne pas.

Sorti de ``engine.py`` sur le modèle de ``travaux.py`` : des fonctions de
module prenant le moteur (pour ``_salutation_en_attente``, attribut de
classe lu sur des moteurs construits par ``__new__``) et orchestrant à
travers sa surface (``moteur._declencheurs``), si bien qu'un patch posé sur
le moteur continue de porter.
"""

from __future__ import annotations

import logging

from conscience.reglages import vecu_tuning
from conscience.types import DecisionContext
from conscience.vecu import composer_declencheurs, declencheurs_actifs
from drives.engine import drive_engine
from utils.degradation import degradations

logger = logging.getLogger(__name__)

#: Ce qu'un motif donne comme intention, à l'infinitif. Sept entrées pour
#: sept motifs — pas un gabarit par situation.
_INTENTION_PAR_MOTIF: dict[str, str] = {
    "matin": "dire bonjour",
    "soir": "dire un mot sur la soirée",
    "nuit": "faire remarquer qu'il est tard",
    "inactivite": "relancer la conversation",
    "humeur": "dire ce que je ressens",
    "pulsion": "aller voir quelque chose de nouveau",
    "rumination": "reparler de ce qui me trotte dans la tête",
}
#: Le motif « pulsion » se spécialise par la pulsion dominante : « aller
#: voir quelque chose de nouveau » convient à la curiosité et pas du tout
#: au manque de contact — le murmure d'un débordement SOCIAL disait une
#: envie d'explorer au moment précis où elle voulait quelqu'un. Membres
#: d'énumération, donc stables : la garde anti-répétition du murmure
#: compare ces chaînes d'un tour à l'autre.
_INTENTION_PAR_PULSION: dict[str, str] = {
    "curiosity": "aller voir quelque chose de nouveau",
    "social": "reprendre des nouvelles de quelqu'un",
    "expression": "raconter ou fabriquer quelque chose",
    "rest": "",
}


def _texte(valeur, limite: int) -> str:
    return " ".join(str(valeur or "").split())[:limite]


def decrire_observation(obs) -> str:
    """L'intention « réagir à » une observation, **avec d'où elle vient**.

    Le résumé seul ne suffisait pas au modèle de la voix intérieure. Pour un
    titre France Info (`[France Info] "Une dangerosité particulière": au cœur
    du transfert…`, coupé à 140 caractères), il ne savait ni que c'était une
    actualité ni ce qu'elle racontait. Il a lu la citation entre guillemets
    comme un surnom et murmuré « "dangerosité particulière", c'est qui ça ? ».

    La description nomme donc la nature du signal (actualité, email, message)
    et sa provenance, avec le titre complet et le chapô tirés de `raw_data`.
    La chaîne reste stable d'un cycle à l'autre pour une même observation,
    ce dont dépend la garde anti-répétition du murmure.
    """
    source = str(getattr(obs, "source", "") or "")
    brut = getattr(obs, "raw_data", None)
    brut = brut if isinstance(brut, dict) else {}
    resume = _texte(getattr(obs, "summary", ""), 140)

    if source == "rss":
        flux = _texte(brut.get("feed_name"), 60)
        titre = _texte(brut.get("title"), 200) or resume
        if not titre:
            return ""
        origine = f"du flux « {flux} »" if flux else "d'un flux RSS"
        texte = f"réagir à un titre d'actualité lu {origine} : « {titre} »"
        chapo = _texte(brut.get("summary"), 220)
        if chapo:
            texte += f" — l'article dit : {chapo}"
        return texte

    if source == "email":
        expediteur = _texte(brut.get("from"), 80)
        sujet = _texte(brut.get("subject"), 160)
        if sujet or expediteur:
            de = f" de {expediteur}" if expediteur else ""
            objet = f" : « {sujet} »" if sujet else ""
            return f"réagir à un email reçu{de}{objet}"

    if not resume:
        return ""
    if source:
        return f"réagir à ce que j'ai perçu via {source} : {resume}"
    return f"réagir à : {resume}"


def intention_de_lacte(moteur, ctx: DecisionContext) -> str:
    """Ce qu'elle s'apprête à faire, en une phrase, pour le murmure.

    **Jamais construite sur `reason`**, et c'est la contrainte qui décide
    de la forme. La sixième garde du murmure compare l'intention normalisée
    d'un tour à l'autre pour ne pas répéter la même pensée ; or `reason` et
    `ctx.drive_summary` embarquent des flottants (« curiosity:0.87 ») qui
    bougent à chaque cycle. S'appuyer dessus dépenserait le quota du jour
    en huit variantes d'une seule et même pensée.

    Un membre d'énumération, lui, ne dérive pas. La préférence va donc au
    plus concret : une action programmée nomme son objet, une observation
    porte son résumé, et à défaut le motif dominant donne un infinitif.

    Rendre `""` est une sortie valide : la garde « pas d'intention » du
    murmure coupe alors avant toute dépense.
    """
    try:
        if ctx.scheduled_actions:
            prompt = getattr(ctx.scheduled_actions[0], "prompt", "")
            if prompt:
                return str(prompt)[:160]

        if ctx.pending_observations:
            meilleure = max(
                ctx.pending_observations,
                key=lambda o: getattr(o, "pertinence", 0.0),
            )
            decrite = decrire_observation(meilleure)
            if decrite:
                return decrite

        declencheurs = moteur._declencheurs(ctx)
        if declencheurs:
            motif = getattr(declencheurs[0].motif, "value", "")
            if motif == "pulsion":
                pulsion = drive_engine.pulsion_saillante()
                nom = getattr(pulsion, "value", "")
                if nom in _INTENTION_PAR_PULSION:
                    return _INTENTION_PAR_PULSION[nom]
            return _INTENTION_PAR_MOTIF.get(motif, "")
        return ""
    except Exception as exc:
        degradations.record("conscience: intention de l'acte", exc)
        return ""


async def mode_professionnel(intention: str) -> bool:
    """Cet acte tombe-t-il dans le cadre d'un projet en mode professionnel ?

    Le trou que ceci referme : `gather_context` calcule bien
    `project_suppresses_emotion`, mais **saute la détection pour les
    `person_id` internes** — et `conscience_mika` en est un. Un acte
    spontané n'était donc jamais reconnu comme professionnel, et le murmure
    marmonnait affectivement au milieu d'un projet dont toute la raison
    d'être est qu'elle n'en fait rien de tel.

    La détection se fait sur l'**intention**, pas sur un message : c'est le
    seul texte que la conscience produise avant d'agir, et il décrit
    précisément ce qu'elle s'apprête à faire. Il est déjà calculé pour le
    murmure, donc rien n'est fait deux fois.

    Une requête par acte — jamais par tick, et jamais quand l'intention est
    vide. Fail-open : sans réponse, on suppose qu'elle n'est pas au travail,
    parce que se taire par erreur est plus coûteux que murmurer de trop.
    """
    if not intention:
        return False
    try:
        from projects.detection import (
            detect_project_for_message,
            load_project_for_prompt,
        )

        match = await detect_project_for_message(intention)
        if not match:
            return False
        data = await load_project_for_prompt(match.project_id)
        return bool(data) and data.get("emotion_policy") == "off"
    except Exception as exc:
        degradations.record("conscience: mode professionnel", exc)
        return False


def declencheurs(moteur, ctx: DecisionContext) -> list:
    """Les motifs actifs de ce cycle, dans l'ordre où ils se disent.

    Extrait de `composer_vecu` parce que deux appelants en ont besoin :
    la phrase du prompt, et l'intention du murmure. Les recalculer
    séparément les ferait diverger — elle murmurerait une intention que le
    prompt ne mentionne pas.
    """
    from emotion.state import EMOTION_PROMPT_FR

    ligne = ctx.rumination_lignes[0] if ctx.rumination_lignes else {}
    pulsion = drive_engine.pulsion_saillante()
    return declencheurs_actifs(
        salutation=moteur._salutation_en_attente,
        idle_seconds=ctx.idle_seconds,
        # Le libellé français vit dans la couche d'émotion, jamais dans
        # `GestionSysteme.formatting` : là-bas `bored` vaut « s'ennuie »,
        # un verbe, qui donnerait « tu es vraiment s'ennuie » — et ce
        # serait le sens de dépendance inversé.
        humeur=EMOTION_PROMPT_FR.get(ctx.global_mood, ""),
        humeur_intensite=ctx.global_intensity,
        rumination_pression=ctx.rumination_pressure,
        rumination_resume=str(ligne.get("summary", ""))[:160],
        pulsion=pulsion.value if pulsion else "",
        pulsion_tension=(
            drive_engine.states[pulsion].tension if pulsion else 0.0
        ),
        tuning=vecu_tuning(),
    )


def composer_vecu(moteur, ctx: DecisionContext) -> str:
    """Ce qui la pousse à parler, dit en une phrase — tous les motifs.

    Remplace une chaîne de quatre `elif` sur des sous-chaînes de `reason` :
    un cycle qui cumulait salutation ET débordement d'humeur n'en gardait
    qu'un, et l'inactivité comme les pulsions faisaient monter le score
    sans qu'aucune phrase ne les nomme.

    Ne lève jamais : on est sur le chemin de l'acte, dans une boucle que
    personne ne supervise.
    """
    try:
        return composer_declencheurs(moteur._declencheurs(ctx))
    except Exception as exc:
        degradations.record("conscience: composition du vecu", exc)
        return ""
