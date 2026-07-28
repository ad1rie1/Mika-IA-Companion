"""Le tempérament est un réglage du tableau de bord, plus un bloc de YAML.

Il vivait dans ``personality.yaml`` et s'affichait en lecture seule sur la page
« Vie intérieure » : cinq curseurs qui décident du point de repos de
l'oscillateur et de sa façon d'y revenir, montrés à côté de l'humeur qu'ils
gouvernent, mais modifiables uniquement en éditant un fichier puis en
redémarrant. Ce sont pourtant des valeurs qu'on n'obtient pas en réfléchissant :
on les essaie en regardant l'humeur bouger.

Ce que ces tests protègent, dans l'ordre d'importance :

1. **Une seule déclaration.** Le YAML ne doit pas garder un second bloc
   ``temperament:``. C'est le mode de panne que le retrait du pont
   ``env_fallback`` a déjà coûté à ranger : deux défauts pour un même réglage,
   l'un des deux gagnant silencieusement, l'autre décoratif et libre de
   diverger.
2. **Aucun changement de comportement au passage.** Les défauts du registre
   sont exactement les valeurs que le YAML portait.
3. **Le rechargement à chaud atteint la physique**, pas seulement le
   dataclass : c'est ``_recompute_params`` qui produit ce que la boucle lit.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from configs.registry import registry
from configs.service import ValidationError, config_service
from emotion.config_schema import MOOD_CHOICES
from emotion.state import TEMPERAMENT_PREFIX, Temperament, load_temperament
from emotion.types import Emotion

KEYS = (
    "default_mood", "volatility", "intensity_base",
    "recovery_speed", "global_bleed",
)

#: Ce que ``personality.yaml`` déclarait avant le déplacement. Recopié en dur :
#: le fichier ne les porte plus, donc il n'y a plus rien à lire pour comparer —
#: et c'est précisément la comparaison qui a du sens.
VALEURS_YAML = {
    "default_mood": "happy",
    "volatility": 0.7,
    "intensity_base": 0.6,
    "recovery_speed": 0.5,
    "global_bleed": 0.3,
}


@pytest.fixture
def temperament_propre():
    """Rend au registre son état par défaut après un test qui écrit."""
    yield
    for name in KEYS:
        cle = f"{TEMPERAMENT_PREFIX}{name}"
        config_service.unset(cle, actor="test")
        config_service.invalidate_cache(cle)


# ── Une seule source ────────────────────────────────────────────────────

def test_le_yaml_ne_declare_plus_de_temperament():
    """Deux déclarants pour un même curseur, c'est deux valeurs qui divergent."""
    from django.conf import settings

    data = yaml.safe_load(Path(settings.PERSONALITY_PATH).read_text("utf-8")) or {}
    assert "temperament" not in data, (
        "le bloc temperament: doit avoir quitté personality.yaml — sinon le "
        "fichier et le tableau de bord annoncent deux tempéraments"
    )


def test_les_cinq_reglages_sont_declares_au_registre():
    for name in KEYS:
        item = registry.get(f"{TEMPERAMENT_PREFIX}{name}")
        assert item is not None, f"{name} n'est pas déclaré"
        assert item.section == "emotion"
        assert item.group, "un curseur sans groupe se noie dans la section"
        assert item.hot_reload, (
            "ces valeurs se règlent en regardant l'humeur bouger : les relire "
            "au seul démarrage vide l'exercice de son sens"
        )


def test_les_defauts_reproduisent_exactement_l_ancien_yaml():
    """Déplacer un réglage ne doit pas le changer au passage."""
    for name, attendu in VALEURS_YAML.items():
        item = registry.get(f"{TEMPERAMENT_PREFIX}{name}")
        assert item.default == attendu, f"{name}: {item.default!r} ≠ {attendu!r}"


def test_les_bornes_encadrent_le_defaut():
    """Un défaut hors bornes serait refusé au premier enregistrement."""
    for name in KEYS:
        item = registry.get(f"{TEMPERAMENT_PREFIX}{name}")
        if item.type != "float":
            continue
        assert item.min is not None and item.max is not None
        assert item.min <= item.default <= item.max


# ── Les choix d'humeur ──────────────────────────────────────────────────

def test_les_choix_d_humeur_couvrent_exactement_les_29_emotions():
    """La liste est recopiée dans le schéma (chargé avant les apps Django) —
    donc rien ne la rattache aux émotions réelles à part ce test."""
    declarees = [value for value, _ in MOOD_CHOICES]
    assert declarees == [e.value for e in Emotion]


def test_chaque_choix_porte_un_libelle_francais():
    """Une liste déroulante d'administration ne peut pas proposer
    « mischievous » : la valeur reste canonique, le libellé est traduit."""
    from GestionSysteme.formatting import EMOTION_FR

    for value, label in MOOD_CHOICES:
        assert label == EMOTION_FR[value], (
            f"{value}: le schéma et l'affichage doivent dire la même chose"
        )
        assert label != value


@pytest.mark.django_db
def test_une_humeur_inconnue_est_refusee_a_l_ecriture(temperament_propre):
    """Les choix sont désormais des couples ``(valeur, libellé)`` : la
    validation doit comparer aux valeurs, pas aux couples — sinon plus rien ne
    passe, ou tout passe."""
    cle = f"{TEMPERAMENT_PREFIX}default_mood"
    with pytest.raises(ValidationError):
        config_service.set(cle, "euphorique", actor="test")

    config_service.set(cle, "melancholic", actor="test")
    assert config_service.get(cle) == "melancholic"


# ── Lecture effective ───────────────────────────────────────────────────

def test_sans_rien_ecrire_le_temperament_est_celui_du_yaml_d_avant():
    charge = load_temperament()
    defauts = Temperament()
    assert charge == defauts
    assert charge.default_mood.value == VALEURS_YAML["default_mood"]


@pytest.mark.django_db
def test_une_valeur_ecrite_est_celle_que_lit_le_moteur(temperament_propre):
    config_service.set(f"{TEMPERAMENT_PREFIX}volatility", 0.25, actor="test")
    config_service.set(f"{TEMPERAMENT_PREFIX}default_mood", "melancholic",
                       actor="test")

    charge = load_temperament()
    assert charge.volatility == pytest.approx(0.25)
    assert charge.default_mood is Emotion.MELANCHOLIC
    # Les autres n'ont pas bougé.
    assert charge.global_bleed == pytest.approx(VALEURS_YAML["global_bleed"])


@pytest.mark.django_db
def test_personality_expose_le_meme_temperament(temperament_propre):
    """L'accesseur est resté sur ``personality`` — c'est là que tous les
    appelants le cherchent — mais il ne lit plus le fichier."""
    from config.personality import personality

    config_service.set(f"{TEMPERAMENT_PREFIX}recovery_speed", 0.9, actor="test")
    assert personality.temperament.recovery_speed == pytest.approx(0.9)
    assert personality.temperament == load_temperament()


def test_une_lecture_impossible_ne_leve_pas(monkeypatch):
    """Un moteur d'émotion qui refuse de démarrer parce qu'un curseur est
    illisible coûte plus cher que le curseur par défaut."""
    def boum(*a, **kw):
        raise RuntimeError("base injoignable")

    monkeypatch.setattr(config_service, "get", boum)
    assert load_temperament() == Temperament()


# ── Rechargement à chaud ────────────────────────────────────────────────

@pytest.mark.django_db
def test_le_rechargement_atteint_les_parametres_de_l_oscillateur(temperament_propre):
    """Recharger le dataclass ne suffit pas : la boucle lit
    ``_person_params``, dérivé du tempérament, pas le tempérament."""
    from emotion.engine import emotion_engine

    avant_temperament = emotion_engine.temperament
    avant_params = emotion_engine._person_params
    try:
        config_service.set(f"{TEMPERAMENT_PREFIX}volatility", 0.2, actor="test")
        emotion_engine._reload_temperament("emotion.temperament.volatility")

        assert emotion_engine.temperament.volatility == pytest.approx(0.2)
        assert emotion_engine._person_params.mass != avant_params.mass, (
            "une volatilité plus basse doit alourdir l'oscillateur"
        )
    finally:
        emotion_engine.temperament = avant_temperament
        emotion_engine._recompute_params()


# ── L'écran ─────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_la_section_emotion_rend_les_cinq_curseurs(client):
    """Ils doivent être joignables là où l'utilisateur va les chercher."""
    reponse = client.get("/gestion/configuration/emotion/")
    assert reponse.status_code == 200

    html = reponse.content.decode()
    for name in KEYS:
        assert f"{TEMPERAMENT_PREFIX}{name}" in html, f"{name} absent du formulaire"
    assert "Tempérament" in html
    # Le libellé français doit descendre dans le <select>, pas le nom canonique
    # seul — c'est tout l'objet des choix en couples.
    assert "malicieuse" in html


@pytest.mark.django_db
def test_la_page_interieur_renvoie_vers_la_configuration(client):
    """La carte qui recopiait les valeurs est partie ; le lien reste, parce
    que c'est ce qu'on veut toucher quand l'humeur affichée ne va pas."""
    reponse = client.get("/gestion/interieur/emotions/")
    assert reponse.status_code == 200
    assert reponse.context["temperament_url"] == "/gestion/configuration/emotion/"
    assert "temperament" not in reponse.context
