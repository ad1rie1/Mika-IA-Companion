"""Le vécu : ce que la conscience se raconte, et les deux tables qu'il remplace.

Chaque test épingle une **propriété**, pas une formulation : les phrases sont
faites pour être réécrites, la garantie ne l'est pas. Les trois propriétés qui
motivent le module :

* aucun déclencheur n'est perdu (le `elif` en gardait un sur quatre) ;
* les vingt-neuf émotions ont une dérive (la table en couvrait neuf) ;
* rien ne lève sur un chemin traversé toutes les 30 s par une boucle que
  personne ne supervise.

Aucun accès base : le module est pur, et le test l'est aussi — un test qui
aurait besoin d'une base pour mesurer une mise en forme dirait déjà que le
module a fui.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from old.backend.emotion.pad import EMOTION_ANCHORS, valence
from old.backend.emotion.types import Emotion
from old.backend.utils import phrasing
from old.backend.utils.degradation import degradations

from old.backend.conscience import vecu
from old.backend.conscience.vecu import (
    DEFAUT_TUNING,
    DETAIL_PULSION,
    VIVIERS,
    VIVIERS_REJEU,
    Declencheur,
    Motif,
    SeauPad,
    VecuTuning,
    cible_de_derive,
    composer_declencheurs,
    declencheurs_actifs,
    duree_en_mots,
    phrase_de_rejeu,
    seau_pad,
)


@pytest.fixture(autouse=True)
def tirage_neuf():
    """Isoler les tests les uns des autres.

    La mémoire d'anti-répétition du tirage partagé survit d'un appel à l'autre
    — c'est tout son intérêt, et c'est exactement ce qui ferait dépendre un
    test de celui qui l'a précédé.
    """
    phrasing.reinitialiser_tirage_partage()
    yield
    phrasing.reinitialiser_tirage_partage()


def _champs_attendus(declencheurs) -> dict[str, str]:
    """Les valeurs que la composition injectera, reconstruites à l'identique."""
    champs = {}
    for d in declencheurs:
        nom = vecu._CHAMP_DETAIL.get(d.motif)
        if nom and d.detail:
            champs[nom] = d.detail.strip()
    return champs


def _fragments_possibles(d: Declencheur, champs: dict[str, str]) -> list[str]:
    """Toutes les propositions que ce motif pourrait produire.

    Sert à vérifier qu'un motif *a été dit* sans dépendre du tirage : on ne
    teste pas quelle formulation est sortie, on teste qu'une des siennes l'est.
    L'adverbe est remplacé par un joker — sa valeur est tirée, donc inconnue.
    """
    rendus = []
    for phrase in VIVIERS[d.motif]:
        texte = phrase.texte
        nom_adv = vecu._CHAMP_ADVERBE.get(d.motif)
        if nom_adv and "{" + nom_adv + "}" in texte:
            # Découper autour de l'adverbe : on vérifiera les deux morceaux.
            avant, apres = texte.split("{" + nom_adv + "}")
            try:
                rendus.append((avant.format(**champs), apres.format(**champs)))
            except KeyError:
                continue
            continue
        try:
            rendus.append((texte.format(**champs), ""))
        except KeyError:
            continue
    return rendus


def _est_dit(d: Declencheur, sortie: str, champs: dict[str, str]) -> bool:
    # Comparaison insensible à la casse : `phrasing.assembler` capitalise la
    # première proposition de *chaque* phrase, et la pagination en produit
    # plusieurs — la variante capitalisée n'est donc pas toujours la première.
    botte = sortie.casefold()
    for avant, apres in _fragments_possibles(d, champs):
        if avant and avant.casefold() in botte and (
            not apres or apres.casefold() in botte
        ):
            return True
    return False


# ─────────────────────────────────────────────────────────────────────
# Le module est-il ce qu'il prétend être
# ─────────────────────────────────────────────────────────────────────

class TestPurete:
    """Rien qui touche une base, un registre ou le réseau."""

    def test_aucun_import_orm_ni_configuration(self):
        source = pathlib.Path(vecu.__file__).read_text(encoding="utf-8")
        arbre = ast.parse(source)
        importes: set[str] = set()
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Import):
                importes.update(a.name for a in noeud.names)
            elif isinstance(noeud, ast.ImportFrom) and noeud.module:
                importes.add(noeud.module)

        interdits = ("django", "configs", "conscience.models", "drives",
                     "memory", "asgiref", "GestionSysteme")
        fautifs = [m for m in importes
                   if any(m == i or m.startswith(i + ".") for i in interdits)]
        assert not fautifs, (
            f"vecu.py doit rester pur — imports interdits : {fautifs}"
        )

    def test_le_reglage_est_gele_et_reprend_les_constantes_du_module(self):
        """Contrat C1 : les défauts de la dataclasse *sont* les replis.

        Deux valeurs déclarées pour un même seuil, c'est exactement la forme
        qu'avait `env_fallback` : celle qui gagne dépend alors de l'ordre de
        lecture, pas de l'intention.
        """
        with pytest.raises(Exception):
            DEFAUT_TUNING.humeur_gate = 0.1  # type: ignore[misc]

        assert DEFAUT_TUNING.inactivite_gate_minutes == vecu.INACTIVITE_GATE_MINUTES
        assert DEFAUT_TUNING.humeur_gate == vecu.HUMEUR_GATE
        assert DEFAUT_TUNING.rumination_gate == vecu.RUMINATION_GATE
        assert DEFAUT_TUNING.pulsion_gate == vecu.PULSION_GATE
        assert DEFAUT_TUNING.pulsion_forte == vecu.PULSION_FORTE
        assert DEFAUT_TUNING.valence_marquee == vecu.VALENCE_MARQUEE
        assert DEFAUT_TUNING.eveil_marque == vecu.EVEIL_MARQUE
        assert DEFAUT_TUNING.dominance_marquee == vecu.DOMINANCE_MARQUEE

    def test_l_echelle_d_adverbes_est_celle_du_module_partage(self):
        """Un second barème serait deux façons de dire « vraiment » qui divergent."""
        assert DEFAUT_TUNING.paliers_intensite is phrasing.PALIERS_INTENSITE


# ─────────────────────────────────────────────────────────────────────
# Les viviers
# ─────────────────────────────────────────────────────────────────────

class TestViviers:

    def test_chaque_motif_a_plusieurs_formulations(self):
        """Un motif à formulation unique est un gabarit, pas une voix."""
        for motif in Motif:
            assert motif in VIVIERS, f"{motif} n'a aucun vivier"
            assert len(VIVIERS[motif]) >= 4, f"{motif} n'a qu'une poignée de phrases"

    def test_l_ordre_de_recit_couvre_exactement_les_motifs(self):
        """Un motif absent de `_ORDRE` serait dit en dernier par accident."""
        assert set(vecu._ORDRE) == set(Motif)
        assert len(vecu._ORDRE) == len(Motif)

    def test_les_phrases_sont_des_propositions_pas_des_phrases(self):
        """`assembler` capitalise et ponctue : une phrase déjà close donnerait
        « ... 42 minutes., et tu te sens ... »."""
        for motif, vivier in VIVIERS.items():
            for phrase in vivier:
                assert phrase.texte == phrase.texte.lstrip(), motif
                assert phrase.texte[0].islower() or phrase.texte[0] == "{", (
                    f"{motif}: {phrase.texte!r} commence par une majuscule"
                )
                assert phrase.texte[-1] not in ".!?…", f"{motif}: {phrase.texte!r}"

    def test_aucune_phrase_ne_dicte_la_reponse(self):
        """Défaut B3 : « Dis bonjour naturellement » se fait exécuter, pas vivre."""
        interdits = ("dis ", "mentionne", "exprime-toi", "réponds", "raconte ")
        for motif, vivier in VIVIERS.items():
            for phrase in vivier:
                bas = phrase.texte.lower()
                assert not any(bas.startswith(m) for m in interdits), (
                    f"{motif}: {phrase.texte!r} est une consigne, pas une situation"
                )

    def test_les_etiquettes_sont_derivees_des_trous(self):
        """Écrire l'étiquette à la main, c'est deux déclarations pour un fait."""
        for motif, vivier in VIVIERS.items():
            for phrase in vivier:
                trous = set(vecu._TROUS.findall(phrase.texte))
                requises = {e for e in phrase.etiquettes if not e.startswith("!")}
                assert trous <= requises, f"{motif}: {phrase.texte!r}"

    def test_les_quatre_pulsions_ont_un_detail(self):
        assert set(DETAIL_PULSION) == {"curiosity", "social", "expression", "rest"}
        assert all(v.strip() for v in DETAIL_PULSION.values())


# ─────────────────────────────────────────────────────────────────────
# La réparation du elif
# ─────────────────────────────────────────────────────────────────────

class TestCompositionDitTout:

    def test_tous_les_declencheurs_sont_dits(self):
        """LA propriété. La chaîne de `elif` en gardait un sur quatre."""
        actifs = [
            Declencheur(Motif.MATIN),
            Declencheur(Motif.INACTIVITE, 0.5, "42 minutes"),
            Declencheur(Motif.HUMEUR, 0.81, "agacée"),
            Declencheur(Motif.RUMINATION, 0.4, "cette question restée en l'air"),
        ]
        champs = _champs_attendus(actifs)
        sortie = composer_declencheurs(actifs, graine=7)
        for d in actifs:
            assert _est_dit(d, sortie, champs), (
                f"{d.motif} n'a pas été dit : {sortie!r}"
            )

    def test_au_dela_de_la_coupe_rien_n_est_perdu(self):
        """`phrasing.composer` coupe à trois ; on pagine au lieu de jeter.

        C'est le point où la réparation aurait pu réintroduire son propre
        défaut : déléguer l'assemblage sans regarder la coupe, c'était perdre
        les motifs 4 et 5 exactement comme le `elif` perdait les motifs 2 à 4.
        """
        actifs = [
            Declencheur(Motif.NUIT),
            Declencheur(Motif.INACTIVITE, 0.6, "1 h 12"),
            Declencheur(Motif.HUMEUR, 0.9, "à cran"),
            Declencheur(Motif.PULSION, 0.9, DETAIL_PULSION["social"]),
            Declencheur(Motif.RUMINATION, 0.5, "ce qu'il a dit hier"),
        ]
        assert len(actifs) > phrasing.REGLAGE_PAR_DEFAUT.max_declencheurs
        champs = _champs_attendus(actifs)
        sortie = composer_declencheurs(actifs, graine=21)
        for d in actifs:
            assert _est_dit(d, sortie, champs), f"{d.motif} perdu : {sortie!r}"

    def test_la_pagination_produit_des_phrases_pas_une_liste(self):
        """Une énumération de cinq propositions n'est plus une phrase."""
        actifs = [
            Declencheur(Motif.NUIT),
            Declencheur(Motif.INACTIVITE, 0.6, "1 h 12"),
            Declencheur(Motif.HUMEUR, 0.9, "à cran"),
            Declencheur(Motif.PULSION, 0.9, DETAIL_PULSION["social"]),
            Declencheur(Motif.RUMINATION, 0.5, "ce qu'il a dit hier"),
        ]
        sortie = composer_declencheurs(actifs, graine=21)
        assert sortie.count(".") + sortie.count("!") + sortie.count("?") >= 2

    def test_l_ordre_est_celui_du_recit_pas_celui_de_l_entree(self):
        """Situer, puis confier : l'heure avant l'humeur, l'humeur avant la pensée."""
        matin = Declencheur(Motif.MATIN)
        humeur = Declencheur(Motif.HUMEUR, 0.8, "agacée")
        rumination = Declencheur(Motif.RUMINATION, 0.5, "ce truc de tout à l'heure")
        actifs = [rumination, humeur, matin]  # entrée volontairement à l'envers
        champs = _champs_attendus(actifs)
        sortie = composer_declencheurs(actifs, graine=3)

        assert _est_dit(matin, sortie, champs)
        assert sortie.index("agacée") < sortie.index("ce truc de tout à l'heure")
        # Le matin ouvre : sa proposition commence à l'indice 0.
        debuts = [a.casefold() for a, _ in _fragments_possibles(matin, champs) if a]
        assert any(sortie.casefold().startswith(a) for a in debuts), sortie

    def test_l_intensite_n_ordonne_pas(self):
        """Le poids porte le rang narratif ; une humeur à 1.0 ne double pas l'heure."""
        actifs = [
            Declencheur(Motif.NUIT),
            Declencheur(Motif.HUMEUR, 1.0, "furieuse"),
        ]
        sortie = composer_declencheurs(actifs, graine=9)
        assert sortie.index("nuit") < sortie.index("furieuse") or \
            sortie.index("tard") < sortie.index("furieuse")

    def test_un_motif_repete_n_est_dit_qu_une_fois(self):
        """Deux ruminations actives ne donnent pas deux phrases collées."""
        actifs = [
            Declencheur(Motif.RUMINATION, 0.4, "la première"),
            Declencheur(Motif.RUMINATION, 0.9, "la seconde"),
        ]
        sortie = composer_declencheurs(actifs, graine=2)
        assert "la première" in sortie
        assert "la seconde" not in sortie

    def test_aucun_declencheur_donne_une_chaine_vide(self):
        """Un bloc vide se retire du prompt ; un bloc à moitié écrit, non."""
        assert composer_declencheurs([]) == ""


class TestPhrasesATrou:

    def test_une_phrase_a_trou_n_est_jamais_servie_avec_un_trou_vide(self):
        """« Personne ne t'a parlé depuis . » est une phrase fausse."""
        assert composer_declencheurs(
            [Declencheur(Motif.INACTIVITE, 0.5, "")], graine=4,
        ) == ""

    def test_un_motif_muet_ne_mange_pas_la_place_d_un_autre(self):
        """Sinon un détail manquant ferait taire les motifs suivants."""
        actifs = [
            Declencheur(Motif.MATIN),
            Declencheur(Motif.INACTIVITE, 0.5, ""),      # muet
            Declencheur(Motif.HUMEUR, 0.9, "pensive"),
            Declencheur(Motif.PULSION, 0.9, DETAIL_PULSION["rest"]),
            Declencheur(Motif.RUMINATION, 0.5, "l'histoire du café"),
        ]
        sortie = composer_declencheurs(actifs, graine=6)
        assert "pensive" in sortie
        assert DETAIL_PULSION["rest"] in sortie
        assert "l'histoire du café" in sortie

    def test_aucune_sortie_ne_contient_de_trou_non_bouche(self):
        """Un `{detail}` visible partirait tel quel au modèle."""
        for motif in Motif:
            sortie = composer_declencheurs(
                [Declencheur(motif, 0.7, "un détail plausible")], graine=13,
            )
            assert "{" not in sortie and "}" not in sortie, f"{motif}: {sortie!r}"

    def test_une_accolade_dans_un_resume_ne_devient_pas_un_gabarit(self):
        """Le résumé d'une rumination est écrit par le modèle : il peut tout contenir."""
        sortie = composer_declencheurs(
            [Declencheur(Motif.RUMINATION, 0.5, "le dict {a: 1} qu'il m'a montré")],
            graine=15,
        )
        assert "{a: 1}" in sortie


class TestSituation:

    def test_une_envie_forte_ne_se_dit_pas_comme_une_petite(self):
        """L'intensité d'une pulsion change la phrase, pas un adverbe collé.

        « tu as complètement envie de » n'est pas du français : ici la
        graduation passe par une étiquette de situation.
        """
        faible = Declencheur(Motif.PULSION, 0.65, DETAIL_PULSION["curiosity"])
        forte = Declencheur(Motif.PULSION, 0.95, DETAIL_PULSION["curiosity"])
        rendus_faibles = {composer_declencheurs([faible], graine=g)
                          for g in range(12)}
        rendus_forts = {composer_declencheurs([forte], graine=g)
                        for g in range(12)}
        petite = "il te trotte une petite envie"
        demange = "ça te démange"
        assert any(petite in r.lower() for r in rendus_faibles)
        assert not any(petite in r.lower() for r in rendus_forts)
        assert any(demange in r.lower() for r in rendus_forts)
        assert not any(demange in r.lower() for r in rendus_faibles)


# ─────────────────────────────────────────────────────────────────────
# Le tirage
# ─────────────────────────────────────────────────────────────────────

class TestTirage:

    def test_une_graine_rend_la_composition_reproductible(self):
        actifs = [Declencheur(Motif.MATIN),
                  Declencheur(Motif.HUMEUR, 0.9, "excitée")]
        a = composer_declencheurs(actifs, graine=42)
        b = composer_declencheurs(actifs, graine=42)
        assert a == b and a

    def test_la_formulation_change_d_un_cycle_a_l_autre(self):
        """Une conscience qui redit la même phrase se lit comme un gabarit."""
        d = [Declencheur(Motif.INACTIVITE, 0.5, "42 minutes")]
        sorties = {composer_declencheurs(d) for _ in range(12)}
        assert len(sorties) > 1

    def test_le_gabarit_reste_stable_quand_le_detail_bouge(self):
        """La mémoire d'anti-répétition prend les `Phrase` pour clés.

        Formater avant le tirage aurait donné une clé neuve à chaque minute de
        silence écoulée, donc une anti-répétition qui ne retient jamais rien.
        """
        for phrase in VIVIERS[Motif.INACTIVITE]:
            assert "{duree}" in phrase.texte or "duree" not in phrase.etiquettes
            assert "42 minutes" not in phrase.texte


# ─────────────────────────────────────────────────────────────────────
# Rien ne lève sur le chemin chaud (C4)
# ─────────────────────────────────────────────────────────────────────

class TestJamaisFatal:

    def test_un_motif_inconnu_est_compte_et_saute(self):
        degradations.reset()
        bancal = Declencheur("motif_qui_n_existe_pas", 0.5, "x")  # type: ignore[arg-type]
        bon = Declencheur(Motif.MATIN)
        sortie = composer_declencheurs([bancal, bon], graine=8)
        assert _est_dit(bon, sortie, {})
        assert degradations.count_for("vecu: motif sans vivier") == 1

    def test_une_entree_qui_explose_ne_tue_pas_le_cycle(self):
        """Une boucle de fond n'a pas de superviseur : une exception la termine."""
        degradations.reset()

        def source_cassee():
            yield Declencheur(Motif.MATIN)
            raise RuntimeError("état corrompu en amont")

        assert composer_declencheurs(source_cassee()) == ""
        assert degradations.count_for("vecu: composition des déclencheurs") == 1

    def test_une_emotion_hors_table_derive_quand_meme(self):
        degradations.reset()

        class FausseEmotion:
            pass

        assert cible_de_derive(FausseEmotion()) is Emotion.THINKING  # type: ignore[arg-type]
        assert degradations.count_for("vecu: émotion sans ancre PAD") == 1


# ─────────────────────────────────────────────────────────────────────
# Les portes
# ─────────────────────────────────────────────────────────────────────

class TestPortes:

    def test_le_silence_ordinaire_ne_se_raconte_pas(self):
        """Sous la barre du scoring, l'inactivité est le régime normal."""
        sous = declencheurs_actifs(idle_seconds=9 * 60)
        assert not any(d.motif is Motif.INACTIVITE for d in sous)
        au_dessus = declencheurs_actifs(idle_seconds=42 * 60)
        assert any(d.motif is Motif.INACTIVITE for d in au_dessus)

    def test_les_portes_reprennent_celles_du_scoring(self):
        """Un motif qui n'a pas fait monter le score n'a pas à figurer au prompt.

        C'est là que la divergence commencerait : une phrase annonçant un
        débordement d'humeur que le facteur 3 n'a jamais compté.
        """
        from old.backend.conscience.scoring import DEFAULT_TUNING as SCORING

        assert DEFAUT_TUNING.humeur_gate == SCORING.mood_gate
        assert DEFAUT_TUNING.rumination_gate == SCORING.rumination_gate
        assert DEFAUT_TUNING.inactivite_gate_minutes == SCORING.idle_gate_minutes

    def test_une_humeur_tiede_ne_deborde_pas(self):
        assert not declencheurs_actifs(humeur="agacée", humeur_intensite=0.5)
        assert declencheurs_actifs(humeur="agacée", humeur_intensite=0.9)

    def test_une_pulsion_faible_n_est_pas_nommee(self):
        """Nommer la pulsion à 0.15 la ferait passer pour un besoin."""
        assert not declencheurs_actifs(pulsion="curiosity", pulsion_tension=0.2)
        actifs = declencheurs_actifs(pulsion="curiosity", pulsion_tension=0.8)
        assert actifs[0].detail == DETAIL_PULSION["curiosity"]

    def test_une_rumination_sans_resume_ne_produit_rien(self):
        assert not declencheurs_actifs(rumination_pression=0.9, rumination_resume="")

    def test_les_trois_salutations_sont_exclusives(self):
        for cle, motif in (("morning", Motif.MATIN), ("evening", Motif.SOIR),
                           ("night", Motif.NUIT)):
            actifs = declencheurs_actifs(salutation=cle)
            assert [d.motif for d in actifs] == [motif]
        assert declencheurs_actifs(salutation=None) == []

    def test_un_cycle_charge_produit_tous_ses_motifs(self):
        actifs = declencheurs_actifs(
            salutation="night",
            idle_seconds=95 * 60,
            humeur="frustrée", humeur_intensite=0.82,
            pulsion="expression", pulsion_tension=0.77,
            rumination_pression=0.44, rumination_resume="ce qu'il a dit hier",
        )
        assert {d.motif for d in actifs} == {
            Motif.NUIT, Motif.INACTIVITE, Motif.HUMEUR,
            Motif.PULSION, Motif.RUMINATION,
        }
        champs = _champs_attendus(actifs)
        sortie = composer_declencheurs(actifs, graine=17)
        for d in actifs:
            assert _est_dit(d, sortie, champs), f"{d.motif} perdu : {sortie!r}"


# ─────────────────────────────────────────────────────────────────────
# Mise en mots des grandeurs
# ─────────────────────────────────────────────────────────────────────

class TestGrandeurs:

    def test_une_duree_se_dit_comme_on_la_dit(self):
        """`int(idle/60)` annonçait « depuis 512 minutes » après une nuit."""
        assert duree_en_mots(30) == "moins d'une minute"
        assert duree_en_mots(60) == "1 minute"
        assert duree_en_mots(42 * 60) == "42 minutes"
        assert duree_en_mots(60 * 60) == "1 heure"
        assert duree_en_mots(72 * 60) == "1 h 12"
        assert duree_en_mots(30 * 3600) == "1 jour"
        assert "minute" not in duree_en_mots(512 * 60)

    def test_une_duree_negative_ne_casse_pas(self):
        assert duree_en_mots(-10) == "moins d'une minute"

    def test_l_adverbe_gradue_reste_dans_l_echelle_partagee(self):
        """Le vécu ne redéclare pas son barème ; il en tire les mots."""
        tous = {mot for p in phrasing.PALIERS_INTENSITE for mot in p.formulations}
        for valeur in (0.05, 0.3, 0.5, 0.75, 0.95):
            assert phrasing.adverbe(valeur, DEFAUT_TUNING.paliers_intensite) in tous

    def test_l_adverbe_qualifie_un_adjectif_pas_un_verbe_d_envie(self):
        """« tu as complètement envie de » : le barème ne tient pas partout.

        D'où la règle : l'adverbe n'apparaît que devant un adjectif (humeur) ou
        derrière « ça t'occupe » (rumination), jamais dans la pulsion.
        """
        assert Motif.PULSION not in vecu._CHAMP_ADVERBE
        for phrase in VIVIERS[Motif.PULSION]:
            assert "adv_" not in phrase.texte


# ─────────────────────────────────────────────────────────────────────
# La dérive : vingt-neuf, pas neuf
# ─────────────────────────────────────────────────────────────────────

class TestCibleDeDerive:

    def test_les_vingt_neuf_emotions_ont_une_cible(self):
        """LA propriété. `_AUDIT_EMOTIONS` en couvrait neuf ; vingt restaient muettes."""
        assert len(list(Emotion)) == 29
        for emotion in Emotion:
            cible = cible_de_derive(emotion)
            assert isinstance(cible, Emotion)
            assert cible in EMOTION_ANCHORS

    def test_le_rejeu_n_est_jamais_plus_vif_que_la_scene(self):
        """Se rejouer une scène ne l'agite pas davantage qu'elle ne l'était.

        Énoncé sur le seau et non sur l'éveil brut : `sad → melancholic`
        descend l'éveil de −0.3 à −0.5 (plus calme, mais de valeur absolue plus
        grande) et `disgusted → embarrassed` le monte de 0.3 à 0.4 sans sortir
        du calme. Ce qui doit tenir, c'est qu'aucune dérive ne fasse *passer*
        dans le registre vif une scène qui ne l'était pas — une micro-rumination
        plus agitée que le tour qui l'a produite serait une machine à s'exciter
        toute seule, sur une boucle qui tourne toutes les 30 s.
        """
        for emotion in Emotion:
            source_vif = seau_pad(
                EMOTION_ANCHORS[emotion]).value.endswith("_vif")
            cible_vif = seau_pad(
                EMOTION_ANCHORS[cible_de_derive(emotion)]).value.endswith("_vif")
            assert not (cible_vif and not source_vif), emotion

    def test_la_derive_ne_change_jamais_de_camp(self):
        """Rien ne doit faire dériver la colère vers la joie."""
        for emotion in Emotion:
            p = valence(emotion)
            if abs(p) < DEFAUT_TUNING.valence_marquee:
                continue
            cible = valence(cible_de_derive(emotion))
            assert (p > 0) == (cible > 0), emotion

    def test_un_tour_neutre_ne_se_rejoue_pas(self):
        """L'origine n'a ni camp ni éveil : il n'y a rien à reprendre."""
        assert cible_de_derive(Emotion.NEUTRAL) is Emotion.NEUTRAL

    def test_la_dominance_distingue_la_gene_de_l_inquietude(self):
        """Avoir poussé (`angry`, `disgusted`) ≠ avoir été secouée (`scared`)."""
        assert cible_de_derive(Emotion.ANGRY) is Emotion.EMBARRASSED
        assert cible_de_derive(Emotion.DISGUSTED) is Emotion.EMBARRASSED
        assert cible_de_derive(Emotion.SCARED) is Emotion.ANXIOUS
        assert cible_de_derive(Emotion.FRUSTRATED) is Emotion.ANXIOUS

    def test_l_ancienne_table_reste_largement_reproduite(self):
        """La dérivation n'est pas une refonte du sens, seulement de la forme.

        Huit des neuf lignes de `_AUDIT_EMOTIONS` sont retrouvées sans qu'aucune
        ne soit écrite. La neuvième (`embarrassed → anxious`) devient
        `embarrassed → melancholic` : son ancre est peu éveillée (0.4) et peu
        dominante (−0.5), donc la règle la range avec ce qui s'installe plutôt
        qu'avec ce qui tend. Divergence assumée, pas oubli.
        """
        ancienne = {
            Emotion.ANGRY: Emotion.EMBARRASSED,
            Emotion.FRUSTRATED: Emotion.ANXIOUS,
            Emotion.PROUD: Emotion.PROUD,
            Emotion.EXCITED: Emotion.HOPEFUL,
            Emotion.SCARED: Emotion.ANXIOUS,
            Emotion.DISGUSTED: Emotion.EMBARRASSED,
            Emotion.LOVE: Emotion.GRATEFUL,
            Emotion.JEALOUS: Emotion.MELANCHOLIC,
        }
        for source, cible in ancienne.items():
            assert cible_de_derive(source) is cible, source
        assert cible_de_derive(Emotion.EMBARRASSED) is Emotion.MELANCHOLIC

    def test_un_reglage_different_change_la_derive(self):
        """Non-vacuité : les seuils sont lus, pas décoratifs."""
        tout_dominant = VecuTuning(dominance_marquee=-1.0)
        assert cible_de_derive(Emotion.SAD, tout_dominant) is Emotion.EMBARRASSED
        assert cible_de_derive(Emotion.SAD) is Emotion.MELANCHOLIC


# ─────────────────────────────────────────────────────────────────────
# Les seaux PAD
# ─────────────────────────────────────────────────────────────────────

class TestSeauPad:

    def test_les_six_seaux_sont_atteints_par_les_ancres(self):
        """Un seau qu'aucune émotion n'atteint est une classe morte."""
        atteints = {seau_pad(ancre) for ancre in EMOTION_ANCHORS.values()}
        assert atteints == set(SeauPad)

    def test_le_seau_bascule_de_camp_avec_la_valence(self):
        neutralise = lambda s: s.value.replace("positif", "X").replace("negatif", "X")
        for p, a, d in EMOTION_ANCHORS.values():
            direct = seau_pad((p, a, d))
            miroir = seau_pad((-p, a, d))
            assert neutralise(direct) == neutralise(miroir)
            if abs(p) >= DEFAUT_TUNING.valence_marquee:
                assert direct is not miroir

    def test_la_dominance_ne_change_pas_le_seau(self):
        """Le seau choisit un registre de langue ; la dominance, pas un registre."""
        for d in (-1.0, 0.0, 1.0):
            assert seau_pad((0.8, 0.9, d)) is SeauPad.POSITIF_VIF

    def test_les_vingt_neuf_emotions_produisent_une_phrase(self):
        """`_AUDIT_EMOTIONS` en laissait vingt sans un mot."""
        for emotion in Emotion:
            phrase = phrase_de_rejeu(emotion, "je crois que t'as tort, franchement",
                                     graine=1)
            assert phrase, emotion
            assert "je crois que t'as tort" in phrase
            assert "{" not in phrase

    def test_un_extrait_vide_ne_produit_pas_de_rumination(self):
        """Une citation vide donnait « Tu repenses à ta réponse : « ». »"""
        assert phrase_de_rejeu(Emotion.ANGRY, "") == ""
        assert phrase_de_rejeu(Emotion.ANGRY, "   ") == ""

    def test_chaque_registre_offre_plusieurs_formulations(self):
        """La table littérale répétait une phrase unique dans chaque Rumination."""
        for seau, vivier in VIVIERS_REJEU.items():
            assert len(vivier) >= 2, seau

    def test_le_registre_suit_le_camp_de_l_emotion(self):
        vif = phrase_de_rejeu(Emotion.ANGRY, "extrait", graine=0)
        doux = phrase_de_rejeu(Emotion.GRATEFUL, "extrait", graine=0)
        possibles_vif = {p.texte.format(extrait="extrait")
                         for p in VIVIERS_REJEU[SeauPad.NEGATIF_VIF]}
        possibles_doux = {p.texte.format(extrait="extrait")
                          for p in VIVIERS_REJEU[SeauPad.POSITIF_CALME]}
        assert vif in possibles_vif
        assert doux in possibles_doux

    def test_le_rejeu_varie_d_une_fois_a_l_autre(self):
        rendus = {phrase_de_rejeu(Emotion.ANGRY, "extrait") for _ in range(12)}
        assert len(rendus) > 1
