"""La vie pulsionnelle en français — propriétés, pas formulations.

Ce fichier n'épingle aucune phrase : une variante peut être réécrite sans que
la suite bronche, c'est le point d'avoir un vivier. Ce qu'il épingle, ce sont
les quatre propriétés que la forme précédente — douze phrases figées — ne
tenait pas :

* les quatre pulsions ont de vraies variantes, à chaque palier ;
* la saturation verbale n'existe qu'au *vrai* plafond, jamais avant — c'était
  la promesse du passage en log-temps, restée verbalement lettre morte tant
  que l'adverbe saturait à 0.75 ;
* le silence est une sortie valide quand tout est bas ;
* une journée simulée ne redit pas la même chose.

Aucune base, aucune boucle : le module est pur.
"""

from __future__ import annotations

import math
import random

import pytest

from drives.phrasing import (
    DEFAULT_PHRASING,
    LEXIQUE_SATURATION,
    MAX_PULSIONS_DITES,
    PREFIXE_PROMPT,
    REPLI_STATIQUE,
    Palier,
    Phraseur,
    ReglagePhrasing,
    VIVIERS,
    composer_ligne_pulsions,
    palier_pour,
    pulsions_saillantes,
)
from drives.state import DEFAULT_PARAMS, DriveKind, log_growth
from utils.degradation import degradations

PALIERS_SOUS_PLAFOND = (Palier.FREMISSEMENT, Palier.NET, Palier.INSISTANT)


def _rendu(kind: DriveKind, tension: float, graine: int = 1) -> str:
    return Phraseur(graine=graine).phrase(kind, tension)


def _tensions(**kwargs: float) -> dict[DriveKind, float]:
    """Toutes les pulsions à zéro, sauf celles nommées."""
    base = {kind: 0.0 for kind in DriveKind}
    for nom, valeur in kwargs.items():
        base[DriveKind(nom)] = valeur
    return base


# ---------------------------------------------------------------------------
# Le vivier existe vraiment
# ---------------------------------------------------------------------------

class TestLeVivierEstUnVivier:

    def test_les_quatre_pulsions_couvrent_les_quatre_paliers(self):
        """Une pulsion sans variante à un palier retomberait sur un KeyError
        au moment exact où elle a quelque chose à dire."""
        for kind in DriveKind:
            for palier in Palier:
                assert VIVIERS[kind][palier], f"{kind.value}/{palier.value} vide"

    def test_chaque_palier_offre_assez_de_variantes_pour_ne_pas_se_repeter(self):
        """Le défaut réparé est la répétition, donc le seuil est sur le
        *nombre de textes distincts*, pas sur la présence d'une liste."""
        for kind in DriveKind:
            for palier in Palier:
                textes = {p.texte for p in VIVIERS[kind][palier]}
                assert len(textes) >= 5, f"{kind.value}/{palier.value}: {len(textes)}"

    def test_aucune_variante_n_est_partagee_entre_deux_paliers(self):
        """Deux paliers qui se partagent une phrase rendent le palier
        inobservable : c'est la façon la moins visible de re-saturer."""
        for kind in DriveKind:
            vus: dict[str, Palier] = {}
            for palier in Palier:
                for phrase in VIVIERS[kind][palier]:
                    assert phrase.texte not in vus, (
                        f"{kind.value}: « {phrase.texte} » en "
                        f"{vus.get(phrase.texte)} et {palier.value}"
                    )
                    vus[phrase.texte] = palier

    def test_le_repli_statique_couvre_les_quatre_pulsions(self):
        """Le pire cas du module doit être l'ancien comportement, pas un vide."""
        for kind in DriveKind:
            assert REPLI_STATIQUE[kind].strip()


# ---------------------------------------------------------------------------
# La désaturation
# ---------------------------------------------------------------------------

class TestAucuneSaturationAvantLePlafond:

    def test_le_lexique_saturant_n_apparait_qu_au_plafond(self):
        """La garde qui empêche la prochaine variante écrite à la main de
        remettre « fortement » au milieu de l'échelle."""
        for kind in DriveKind:
            for palier in PALIERS_SOUS_PLAFOND:
                for phrase in VIVIERS[kind][palier]:
                    fautifs = [m for m in LEXIQUE_SATURATION if m in phrase.texte]
                    assert not fautifs, (
                        f"{kind.value}/{palier.value} sature avec {fautifs} : "
                        f"« {phrase.texte} »"
                    )

    def test_toute_variante_de_plafond_est_etiquetee_saturation(self):
        for kind in DriveKind:
            for phrase in VIVIERS[kind][Palier.PLAFOND]:
                assert "saturation" in phrase.etiquettes, phrase.texte

    def test_aucune_variante_sous_le_plafond_n_est_etiquetee_saturation(self):
        for kind in DriveKind:
            for palier in PALIERS_SOUS_PLAFOND:
                for phrase in VIVIERS[kind][palier]:
                    assert "saturation" not in phrase.etiquettes, phrase.texte

    def test_toute_variante_de_plafond_porte_un_mot_saturant(self):
        """Symétrique du test précédent : le plafond doit *s'entendre*, sinon
        l'échelle a quatre paliers dont le dernier ne dit rien de plus."""
        for kind in DriveKind:
            for phrase in VIVIERS[kind][Palier.PLAFOND]:
                assert any(m in phrase.texte for m in LEXIQUE_SATURATION), phrase.texte

    def test_une_ligne_composee_ne_sature_jamais_sous_le_plafond(self):
        """Balayage réel, adverbe substitué compris : c'est l'adverbe qui
        saturait avant, et il est injecté après coup."""
        phraseur = Phraseur(graine=7)
        tension = DEFAULT_PHRASING.fremissement
        while tension < DEFAULT_PHRASING.plafond:
            for kind in DriveKind:
                for _ in range(6):
                    rendu = phraseur.phrase(kind, tension)
                    if not rendu:
                        continue
                    fautifs = [m for m in LEXIQUE_SATURATION if m in rendu]
                    assert not fautifs, f"{tension:.2f} {kind.value}: {fautifs} — {rendu}"
            tension += 0.01

    def test_au_plafond_la_ligne_sature(self):
        phraseur = Phraseur(graine=11)
        for kind in DriveKind:
            for _ in range(12):
                rendu = phraseur.phrase(kind, 0.96)
                assert any(m in rendu for m in LEXIQUE_SATURATION), rendu


class TestLesPaliersExploitentLeLogTemps:

    def _tension_curiosite(self, secondes: float) -> float:
        p = DEFAULT_PARAMS[DriveKind.CURIOSITY]
        return log_growth(secondes, p.growth_tau, p.growth_horizon)

    def test_une_heure_et_six_heures_ne_disent_pas_la_meme_chose(self):
        """La courbe log-temps distingue l'heure de la demi-journée. Si le
        vocabulaire ne suit pas, la désaturation numérique est invisible."""
        une_heure = self._tension_curiosite(3600)
        six_heures = self._tension_curiosite(6 * 3600)
        assert palier_pour(une_heure) != palier_pour(six_heures)

    def test_ce_que_l_ancienne_echelle_confondait_est_desormais_separe(self):
        """L'ancien ``_describe_drive`` disait « fortement » dès 0.75. Trois
        heures et huit heures de curiosité franchissaient tous deux cette
        barre : même adverbe, même phrase, pendant cinq heures. Ils tombent
        maintenant dans deux paliers différents."""
        trois_heures = self._tension_curiosite(3 * 3600)
        huit_heures = self._tension_curiosite(8 * 3600)
        assert trois_heures >= 0.75 and huit_heures >= 0.75  # ancien « fortement »
        assert palier_pour(trois_heures) is Palier.INSISTANT
        assert palier_pour(huit_heures) is Palier.PLAFOND

    def test_le_plafond_verbal_demande_des_heures_pas_des_minutes(self):
        """Vingt minutes de silence ne sont pas trois semaines : c'est
        exactement ce que l'ancienne échelle affirmait."""
        assert palier_pour(self._tension_curiosite(20 * 60)) is not Palier.PLAFOND
        assert palier_pour(self._tension_curiosite(12 * 3600)) is Palier.PLAFOND

    def test_les_paliers_sont_monotones(self):
        ordre = [None, Palier.FREMISSEMENT, Palier.NET, Palier.INSISTANT, Palier.PLAFOND]
        rang = -1
        tension = 0.0
        while tension <= 1.0:
            courant = ordre.index(palier_pour(tension))
            assert courant >= rang, tension
            rang = courant
            tension += 0.005


# ---------------------------------------------------------------------------
# Le silence
# ---------------------------------------------------------------------------

class TestLeSilenceEstUneSortieValide:

    def test_rien_a_dire_quand_toutes_les_tensions_sont_nulles(self):
        assert composer_ligne_pulsions(_tensions()) == ""

    def test_rien_a_dire_juste_sous_les_seuils_de_saillance(self):
        seuils = DEFAULT_PHRASING.saillance
        tensions = {kind: seuils[kind] - 0.01 for kind in DriveKind}
        assert composer_ligne_pulsions(tensions) == ""

    def test_un_dictionnaire_vide_ne_dit_rien(self):
        assert composer_ligne_pulsions({}) == ""

    def test_le_plancher_du_module_prime_sur_un_seuil_nul(self):
        """Un appelant qui résout ses seuils depuis la configuration peut y
        lire zéro (clé absente, base illisible). Une pulsion à 0.02 ne doit
        pas se mettre à parler pour autant."""
        reglage = ReglagePhrasing(saillance={kind: 0.0 for kind in DriveKind})
        assert composer_ligne_pulsions(_tensions(curiosity=0.02), reglage=reglage) == ""
        assert composer_ligne_pulsions(_tensions(curiosity=0.60), reglage=reglage)


# ---------------------------------------------------------------------------
# Ce que la ligne dit
# ---------------------------------------------------------------------------

class TestCompositionDeLaLigne:

    def test_une_pulsion_saillante_produit_une_ligne_prefixee(self):
        ligne = composer_ligne_pulsions(_tensions(social=0.70))
        assert ligne.startswith(PREFIXE_PROMPT)
        assert ligne[len(PREFIXE_PROMPT):].strip()

    def test_plusieurs_pulsions_saillantes_sont_toutes_dites(self):
        """Le défaut inverse de la répétition : une seule pulsion dite alors
        que trois poussent, et la conscience score sur des tensions dont le
        prompt ne parle pas."""
        ligne = composer_ligne_pulsions(
            _tensions(social=0.70, curiosity=0.65, expression=0.60),
            phraseur=Phraseur(graine=3),
        )
        assert ligne.count(".") >= 3

    def test_au_plus_trois_pulsions_dans_une_ligne(self):
        """Au-delà, la ligne cesse d'être un état et devient un inventaire."""
        ligne = composer_ligne_pulsions(
            {kind: 0.95 for kind in DriveKind}, phraseur=Phraseur(graine=5),
        )
        assert ligne.count(".") <= MAX_PULSIONS_DITES

    def test_le_tri_suit_l_exces_au_dessus_du_seuil_pas_la_tension_brute(self):
        """Les seuils diffèrent (SOCIAL 0.25, REST 0.50) : trier sur la
        tension brute faisait passer une fatigue naissante devant une
        solitude installée, et désaccordait la ligne du score, qui pondère
        déjà par l'excès."""
        retenues = pulsions_saillantes(_tensions(social=0.60, rest=0.62))
        assert [ligne[0] for ligne in retenues] == [DriveKind.SOCIAL, DriveKind.REST]

    def test_l_ordre_est_stable_a_egalite(self):
        premier = pulsions_saillantes(_tensions(curiosity=0.60, expression=0.60))
        second = pulsions_saillantes(_tensions(expression=0.60, curiosity=0.60))
        assert [l[0] for l in premier] == [l[0] for l in second]

    def test_un_drive_state_est_accepte_comme_une_tension_nue(self):
        """``engine.states`` porte des ``DriveState``, pas des flottants :
        l'appelant ne doit pas avoir à recopier le dictionnaire pour appeler."""

        class _Etat:
            def __init__(self, tension):
                self.tension = tension

        ligne = composer_ligne_pulsions({DriveKind.SOCIAL: _Etat(0.70)})
        assert ligne.startswith(PREFIXE_PROMPT)

    def test_les_cles_textuelles_sont_acceptees(self):
        assert composer_ligne_pulsions({"social": 0.70}).startswith(PREFIXE_PROMPT)


# ---------------------------------------------------------------------------
# La variété, mesurée
# ---------------------------------------------------------------------------

class TestVarieteSurUneJournee:

    def test_vingt_tirages_au_meme_palier_ne_redisent_pas_la_meme_chose(self):
        """Le cas exact du défaut : la tension ne bouge pas pendant vingt
        cycles de conscience et le prompt répétait la même phrase vingt fois."""
        phraseur = Phraseur(graine=42)
        rendus = [phraseur.phrase(DriveKind.CURIOSITY, 0.60) for _ in range(20)]
        assert len(set(rendus)) >= 5

    def test_la_repetition_immediate_est_rare_sans_etre_interdite(self):
        """L'amortissement est un *penchant*, mesuré contre un tirage nu.

        La version précédente de ce test exigeait qu'une variante ne sorte
        JAMAIS deux fois de suite. C'était la garantie du repli local, qui
        excluait de son vivier ce qu'il venait de tirer — et c'est précisément
        la politique que ``utils.phrasing.TirageAmorti`` refuse : une
        interdiction pure produit, sur un petit vivier, une alternance
        mécanique aussi reconnaissable que la répétition qu'elle corrige. Le
        module partagé amortit (le dernier choix garde un poids, simplement
        plus faible), donc un doublon reste possible et doit rester rare.

        On mesure donc un taux, sur 300 graines plutôt que sur une — une seule
        suite ne peut pas établir une fréquence — et on le compare au tirage nu
        pondéré **calculé ici**, sur le même vivier. Le comparatif est ce qui
        rend l'assertion non tautologique : un tirage dégénéré qui rendrait
        toujours la même phrase, ou un tirage uniforme sans mémoire, échouent
        tous les deux.
        """
        vivier = VIVIERS[DriveKind.EXPRESSION][Palier.NET]
        poids = [p.poids for p in vivier]

        repetitions = transitions = 0
        for graine in range(300):
            phraseur = Phraseur(graine=graine)
            precedent = ""
            for _ in range(40):
                rendu = phraseur.phrase(DriveKind.EXPRESSION, 0.55)
                if precedent:
                    transitions += 1
                    repetitions += rendu == precedent
                precedent = rendu
        taux_amorti = repetitions / transitions

        nues = nues_total = 0
        for graine in range(300):
            alea = random.Random(graine)
            precedent = None
            for _ in range(40):
                choix = alea.choices(vivier, weights=poids, k=1)[0]
                if precedent is not None:
                    nues_total += 1
                    nues += choix is precedent
                precedent = choix
        taux_nu = nues / nues_total

        # Rare dans l'absolu…
        assert taux_amorti < 0.10
        # …et franchement sous ce que coûterait l'absence d'amortissement.
        assert taux_amorti < taux_nu / 2
        # Mais pas interdit : la propriété est un penchant, et un vivier de
        # sept variantes tiré 11 700 fois doit en produire quelques-uns.
        assert repetitions > 0

    def test_une_journee_de_curiosite_ne_se_repete_pas(self):
        """Douze heures de croissance log-temps échantillonnées au quart
        d'heure : 48 lignes, dont on exige qu'elles ne tiennent pas dans une
        poignée de gabarits."""
        p = DEFAULT_PARAMS[DriveKind.CURIOSITY]
        phraseur = Phraseur(graine=2024)
        lignes = []
        for pas in range(48):
            tension = log_growth((pas + 1) * 900, p.growth_tau, p.growth_horizon)
            ligne = composer_ligne_pulsions(
                _tensions(curiosity=tension), phraseur=phraseur,
            )
            if ligne:
                lignes.append(ligne)

        assert len(lignes) >= 40
        assert len(set(lignes)) >= 15
        # Aucune ligne ne doit occuper plus d'un cinquième de la journée : la
        # forme précédente en aurait produit exactement trois, dont une seule
        # au-delà de la vingtième minute.
        plus_frequente = max(lignes.count(l) for l in set(lignes))
        assert plus_frequente <= len(lignes) // 5

    def test_une_graine_rend_le_tirage_reproductible(self):
        a = [Phraseur(graine=8).phrase(DriveKind.REST, 0.65) for _ in range(1)]
        b = [Phraseur(graine=8).phrase(DriveKind.REST, 0.65) for _ in range(1)]
        assert a == b

    def test_deux_phraseurs_ne_partagent_pas_leur_memoire(self):
        """L'amortissement est porté par l'instance : un test qui graîne la
        sienne ne doit pas décaler la production réelle."""
        seul = Phraseur(graine=4)
        attendu = [seul.phrase(DriveKind.SOCIAL, 0.55) for _ in range(6)]

        autre = Phraseur(graine=4)
        parasite = Phraseur(graine=77)
        obtenu = []
        for _ in range(6):
            parasite.phrase(DriveKind.SOCIAL, 0.55)
            obtenu.append(autre.phrase(DriveKind.SOCIAL, 0.55))

        assert obtenu == attendu


# ---------------------------------------------------------------------------
# Le chemin chaud ne lève pas
# ---------------------------------------------------------------------------

class TestNeLevePasSurLeCheminChaud:

    @pytest.mark.parametrize("tensions", [
        {"pulsion_inconnue": 0.9},
        {DriveKind.SOCIAL: None},
        {DriveKind.SOCIAL: "beaucoup"},
        {DriveKind.SOCIAL: float("nan")},
        {DriveKind.SOCIAL: -3.0},
        {DriveKind.SOCIAL: 12.0},
        {None: 0.5},
    ])
    def test_entrees_absurdes(self, tensions):
        """Les tensions viennent d'un moteur qui les restaure depuis la base :
        une ligne corrompue ne doit pas tuer l'assemblage du prompt, donc la
        boucle de conscience, qui n'a pas de superviseur."""
        composer_ligne_pulsions(tensions)  # ne lève pas

    def test_une_tension_hors_bornes_ne_produit_pas_de_ligne_absurde(self):
        assert composer_ligne_pulsions({DriveKind.SOCIAL: -3.0}) == ""
        assert composer_ligne_pulsions({DriveKind.SOCIAL: 12.0}).startswith(PREFIXE_PROMPT)

    def test_un_tirage_casse_retombe_sur_la_phrase_historique(self):
        """Le pire cas est l'ancien comportement, jamais un bloc vide — et il
        est *compté*, sans quoi une panne de vivier serait indiscernable d'une
        Mika laconique."""
        degradations.reset()
        phraseur = Phraseur(graine=1)

        def _casse(*_args, **_kwargs):
            raise RuntimeError("vivier indisponible")

        phraseur._tirage = _casse  # type: ignore[method-assign]
        rendu = phraseur.phrase(DriveKind.CURIOSITY, 0.60)

        assert rendu == REPLI_STATIQUE[DriveKind.CURIOSITY]
        assert degradations.count_for("drives.phrasing.phrase") == 1

    def test_le_nan_ne_franchit_aucun_seuil(self):
        """Une comparaison avec NaN est fausse dans les deux sens : la pulsion
        doit disparaître, pas se retrouver au plafond par défaut."""
        assert palier_pour(math.nan) is None
        assert pulsions_saillantes({DriveKind.SOCIAL: math.nan}) == []
