"""Propriétés du phrasage varié (``utils/phrasing.py``).

Aucune base, aucun Django : le module est pur, ses tests doivent l'être aussi
— sinon ils mesureraient la base de la machine qui les exécute plutôt que la
politique déclarée.

Chaque test épingle une **propriété**, pas une valeur de sortie : une suite qui
fige « la phrase numéro 3 » se casse au premier ajout de variante, ce qui est
exactement l'inverse de ce qu'un module de variété doit encourager.
"""

from __future__ import annotations

import ast
import math
from collections import Counter
from pathlib import Path

from utils.phrasing import (
    AMORTISSEMENT,
    LIANTS,
    MEMOIRE_TIRAGE,
    PALIERS_INTENSITE,
    Declencheur,
    Palier,
    Phrase,
    ReglagePhrasing,
    TirageAmorti,
    adverbe,
    assembler,
    composer,
    eligibles,
    formuler,
)

VIVIER_5 = tuple(Phrase(f"option {i}") for i in range(5))


def _tirage(graine: int = 1234, **reglages) -> TirageAmorti:
    return TirageAmorti(reglage=ReglagePhrasing(**reglages), graine=graine)


# ── Reproductibilité ─────────────────────────────────────────────────────────


class TestReproductibilite:
    def test_meme_graine_meme_suite(self):
        """Deux tirages de même graine rendent la même suite.

        C'est la propriété qui rend tout le reste testable : sans elle, un
        échec de calibration serait indiscernable d'un tirage malchanceux.
        """
        a = _tirage(7)
        b = _tirage(7)
        suite_a = [a.tirer(VIVIER_5).texte for _ in range(60)]
        suite_b = [b.tirer(VIVIER_5).texte for _ in range(60)]
        assert suite_a == suite_b

    def test_graines_differentes_divergent(self):
        """Le déterminisme vient de la graine, pas d'un tirage dégénéré."""
        a = [_tirage(1).tirer(VIVIER_5).texte for _ in range(30)]
        b = [_tirage(2).tirer(VIVIER_5).texte for _ in range(30)]
        assert a != b

    def test_deux_instances_ne_partagent_pas_leur_memoire(self):
        """Chaque instance porte sa propre mémoire d'anti-répétition.

        Une mémoire de classe ferait qu'un module bavard amortirait les phrases
        d'un autre — le vivier des ruminations rendu muet par celui des
        salutations, sans que rien ne le dise.
        """
        a = _tirage(7)
        b = _tirage(7)
        for _ in range(4):
            a.tirer(VIVIER_5)
        assert b.derniers == ()


# ── Couverture et anti-répétition ────────────────────────────────────────────


class TestAntiRepetition:
    def test_toutes_les_options_sortent_sur_200_tirages(self):
        """Amortir n'est pas bannir : aucune option ne disparaît du vivier."""
        t = _tirage(11)
        vus = {t.tirer(VIVIER_5).texte for _ in range(200)}
        assert vus == {p.texte for p in VIVIER_5}

    def test_les_repetitions_immediates_sont_rares(self):
        """Le doublon immédiat reste possible, mais devient marginal.

        Chiffre attendu : sur cinq options équipondérées, mémoire 4 et
        amortissement 0.15, les quatre derniers choix pèsent respectivement
        0.15, 0.36, 0.575 et 0.7875 contre 1.0 pour le cinquième, soit une
        probabilité de répétition de 0.15 / 2.875 ≈ **5.2 %** au régime
        stationnaire — contre 20 % pour un tirage uniforme nu. On borne à 10 %
        pour laisser à la marche aléatoire (mémoire contenant des doublons) le
        droit d'exister, tout en restant deux fois sous le tirage nu.
        """
        t = _tirage(3)
        suite = [t.tirer(VIVIER_5).texte for _ in range(2000)]
        doublons = sum(1 for i in range(1, len(suite)) if suite[i] == suite[i - 1])
        taux = doublons / (len(suite) - 1)
        assert taux <= 0.10, f"taux de répétition immédiate {taux:.3f}"
        assert taux < 0.5 * (1 / len(VIVIER_5))

    def test_le_doublon_immediat_reste_possible(self):
        """Un penchant, pas une règle : la répétition n'est jamais interdite.

        L'interdiction pure produit une alternance mécanique sur un petit
        vivier, motif aussi reconnaissable que la répétition qu'elle corrige.
        """
        t = _tirage(3)
        suite = [t.tirer(VIVIER_5).texte for _ in range(2000)]
        assert any(suite[i] == suite[i - 1] for i in range(1, len(suite)))

    def test_un_vivier_a_une_seule_option_ne_boucle_pas(self):
        """Une option seule sort toujours, quel que soit l'amortissement.

        C'est le cas limite où « interdire ce qui vient de sortir » n'aurait
        aucune sortie ; il doit rendre la phrase, pas None, pas une boucle.
        """
        seule = (Phrase("la seule"),)
        for amortissement in (0.15, 0.0, 1.0):
            t = _tirage(5, amortissement=amortissement)
            assert [t.tirer(seule).texte for _ in range(50)] == ["la seule"] * 50

    def test_une_option_martelee_reste_tirable(self):
        """Saturer la mémoire d'une seule option ne la retire pas du vivier.

        Le facteur d'une occurrence multiple est celui de la plus récente, et
        non le produit : 0.15⁴ ≈ 5e-4 serait un bannissement de fait, et la
        propriété « jamais interdit » deviendrait fausse sans qu'un test de
        moyenne longue s'en aperçoive.

        Mesure : mémoire saturée de « a », le tirage suivant sur (a, b) doit
        rendre « a » avec p = 0.15 / 1.15 ≈ **13 %** — donc ni 0 (bannissement)
        ni 50 % (amortissement inopérant).
        """
        a, b = Phrase("a"), Phrase("b")
        sorties = Counter()
        for graine in range(400):
            t = _tirage(graine)
            for _ in range(MEMOIRE_TIRAGE + 2):
                t.tirer((a,))  # mémoire saturée de « a »
            assert set(t.derniers) == {a}
            sorties[t.tirer((a, b)).texte] += 1
        taux_a = sorties["a"] / 400
        assert 0.05 < taux_a < 0.25, taux_a

    def test_memoire_nulle_desactive_l_amortissement(self):
        """Mémoire 0 = tirage pondéré nu, sans exception ni division par zéro."""
        t = _tirage(4, memoire=0)
        assert [t.tirer(VIVIER_5) is not None for _ in range(50)] == [True] * 50
        assert t.derniers == ()


class TestPoids:
    def test_les_poids_sont_respectes_sans_amortissement(self):
        """Le tirage reste pondéré : l'anti-répétition module, elle n'écrase pas."""
        t = _tirage(2, memoire=0)
        vivier = (Phrase("rare", poids=1.0), Phrase("frequent", poids=4.0))
        comptes = Counter(t.tirer(vivier).texte for _ in range(4000))
        ratio = comptes["frequent"] / comptes["rare"]
        assert 3.4 < ratio < 4.6, ratio

    def test_poids_invalides_valent_zero_sans_lever(self):
        """NaN, négatif et infini sont neutralisés, pas propagés.

        Un NaN traversant la roulette rend toutes les comparaisons fausses et
        fait sortir systématiquement la dernière option : un biais total,
        silencieux, sur un chemin que personne ne supervise.
        """
        t = _tirage(6, memoire=0)
        vivier = (
            Phrase("nan", poids=math.nan),
            Phrase("neg", poids=-3.0),
            Phrase("inf", poids=math.inf),
            Phrase("sain", poids=1.0),
        )
        assert {t.tirer(vivier).texte for _ in range(200)} == {"sain"}

    def test_tous_poids_nuls_retombe_sur_uniforme(self):
        """Un vivier existant ne devient pas muet parce que les poids sont faux."""
        t = _tirage(6, memoire=0)
        vivier = (Phrase("a", poids=0.0), Phrase("b", poids=0.0))
        assert {t.tirer(vivier).texte for _ in range(200)} == {"a", "b"}

    def test_vivier_vide_rend_none(self):
        """Sur le chemin chaud, « rien à dire » est une sortie, pas une erreur."""
        assert _tirage().tirer(()) is None
        assert formuler((), tirage=_tirage()) == ""


# ── Étiquettes ───────────────────────────────────────────────────────────────


class TestEtiquettes:
    def test_une_phrase_sans_etiquette_convient_partout(self):
        """Le filtre est permissif : n'étiqueter que ce qui a une condition."""
        vivier = (Phrase("générique"),)
        assert eligibles(vivier, ()) == list(vivier)
        assert eligibles(vivier, {"nuit", "seule"}) == list(vivier)

    def test_une_phrase_exige_toutes_ses_etiquettes(self):
        vivier = (Phrase("nocturne", etiquettes={"nuit"}),)
        assert eligibles(vivier, {"nuit"}) == list(vivier)
        assert eligibles(vivier, {"matin"}) == []

    def test_une_etiquette_niee_exclut(self):
        """``!x`` interdit la variante quand ``x`` est dans la situation."""
        vivier = (Phrase("intime", etiquettes={"!public"}),)
        assert eligibles(vivier, {"nuit"}) == list(vivier)
        assert eligibles(vivier, {"public"}) == []

    def test_les_etiquettes_se_declarent_avec_n_importe_quel_conteneur(self):
        """Deux phrases identiques le restent quel que soit le conteneur écrit.

        Sans normalisation, la clé de mémoire d'anti-répétition dépendrait du
        type choisi à l'écriture du vivier.
        """
        a = Phrase("x", etiquettes=["nuit"])
        b = Phrase("x", etiquettes=frozenset({"nuit"}))
        assert a == b and hash(a) == hash(b)


# ── Adverbes ─────────────────────────────────────────────────────────────────


class TestAdverbe:
    def test_le_palier_suit_le_seuil(self):
        t = _tirage()
        assert adverbe(0.05, tirage=t) in PALIERS_INTENSITE[0].formulations
        assert adverbe(0.30, tirage=t) in PALIERS_INTENSITE[1].formulations
        assert adverbe(0.50, tirage=t) in PALIERS_INTENSITE[2].formulations
        assert adverbe(0.75, tirage=t) in PALIERS_INTENSITE[3].formulations
        assert adverbe(0.95, tirage=t) in PALIERS_INTENSITE[4].formulations

    def test_le_seuil_est_inclusif(self):
        """Une valeur pile sur la borne appartient au palier qu'elle ouvre."""
        t = _tirage()
        assert adverbe(0.20, tirage=t) in PALIERS_INTENSITE[1].formulations
        assert adverbe(0.88, tirage=t) in PALIERS_INTENSITE[4].formulations

    def test_une_meme_intensite_ne_rend_pas_toujours_le_meme_mot(self):
        """Le défaut réparé : « fortement » à chaque tour, pour toute la vie affective."""
        t = _tirage(8)
        mots = {adverbe(0.75, tirage=t) for _ in range(30)}
        assert len(mots) >= 2
        assert mots <= set(PALIERS_INTENSITE[3].formulations)

    def test_paliers_declares_dans_le_desordre(self):
        """Un vivier mal ordonné ne choisit pas un palier faux en silence.

        Une échelle d'adverbes fausse ne se voit pas dans un prompt : elle se
        lit comme une émotion mal jaugée.
        """
        desordre = (
            Palier(0.8, ("haut",)),
            Palier(0.0, ("bas",)),
            Palier(0.4, ("moyen",)),
        )
        t = _tirage()
        assert adverbe(0.1, desordre, tirage=t) == "bas"
        assert adverbe(0.5, desordre, tirage=t) == "moyen"
        assert adverbe(0.9, desordre, tirage=t) == "haut"

    def test_valeurs_hors_echelle_sont_ramenees_aux_extremes(self):
        t = _tirage()
        assert adverbe(-5.0, tirage=t) in PALIERS_INTENSITE[0].formulations
        assert adverbe(3.0, tirage=t) in PALIERS_INTENSITE[-1].formulations
        assert adverbe(math.nan, tirage=t) in PALIERS_INTENSITE[0].formulations
        assert adverbe("bof", tirage=t) in PALIERS_INTENSITE[0].formulations  # type: ignore[arg-type]

    def test_echelle_vide_rend_une_chaine_vide(self):
        assert adverbe(0.5, (), tirage=_tirage()) == ""


# ── Composition ──────────────────────────────────────────────────────────────


def _decl(cle: str, mot: str, poids: float = 1.0, **kw) -> Declencheur:
    return Declencheur(
        cle=cle,
        vivier=(Phrase(f"{mot} un", **kw), Phrase(f"{mot} deux", **kw)),
        poids=poids,
    )


class TestComposition:
    def test_deux_declencheurs_sont_tous_les_deux_mentionnes(self):
        """Le correctif central : la chaîne de ``elif`` n'en gardait qu'un.

        Un cycle cumule souvent salutation ET débordement d'humeur ; n'énoncer
        que le premier écrit dans le code donnait au modèle un motif appauvri
        de sa propre situation.
        """
        phrase = composer(
            [_decl("salut", "bonjour"), _decl("humeur", "tendue")],
            tirage=_tirage(21),
        ).lower()
        assert "bonjour" in phrase
        assert "tendue" in phrase

    def test_un_seul_declencheur_ne_prend_pas_de_liant(self):
        phrase = composer([_decl("salut", "bonjour")], tirage=_tirage(21))
        assert "bonjour" in phrase.lower()
        assert not any(liant.texte.strip() in phrase for liant in LIANTS if liant.texte.strip())

    def test_la_composition_est_bornee_et_garde_les_plus_forts(self):
        """Au-delà de trois raisons, l'énumération cesse d'être une phrase.

        Et la coupe suit le **poids**, pas la position dans le code : c'était
        le critère implicite de la chaîne de ``elif``.
        """
        declencheurs = [
            _decl("faible1", "faible1", poids=0.1),
            _decl("faible2", "faible2", poids=0.1),
            _decl("fort", "fort", poids=9.0),
            _decl("moyen", "moyen", poids=5.0),
            _decl("moyen2", "moyen2", poids=4.0),
        ]
        phrase = composer(declencheurs, tirage=_tirage(21)).lower()
        assert "fort" in phrase and "moyen " in phrase and "moyen2" in phrase
        assert "faible1" not in phrase and "faible2" not in phrase

    def test_un_declencheur_filtre_ne_consomme_pas_de_place(self):
        """Une étiquette restrictive ne doit pas faire taire les suivants."""
        declencheurs = [
            _decl("nocturne", "nocturne", poids=9.0, etiquettes={"nuit"}),
            _decl("autre", "autre", poids=1.0),
        ]
        phrase = composer(declencheurs, situation={"matin"}, tirage=_tirage(21)).lower()
        assert "nocturne" not in phrase
        assert "autre" in phrase

    def test_la_phrase_est_capitalisee_et_ponctuee(self):
        phrase = composer(
            [_decl("a", "alpha"), _decl("b", "beta")], tirage=_tirage(21)
        )
        assert phrase[0].isupper()
        assert phrase.endswith(".")

    def test_une_ponctuation_deja_presente_n_est_pas_doublee(self):
        assert assembler(["ça alors !"], tirage=_tirage()).endswith("!")
        assert not assembler(["ça alors !"], tirage=_tirage()).endswith("!.")

    def test_les_fragments_vides_sont_ignores(self):
        """Un vivier filtré à zéro laisse un trou, jamais « , et  , et »."""
        phrase = assembler(["", "seul", "   "], tirage=_tirage())
        assert phrase == "Seul."

    def test_sans_declencheur_la_sortie_est_vide(self):
        assert composer([], tirage=_tirage()) == ""
        assert assembler([], tirage=_tirage()) == ""

    def test_la_composition_est_reproductible_sous_graine(self):
        declencheurs = [_decl("a", "alpha"), _decl("b", "beta"), _decl("c", "gamma")]
        t1, t2 = _tirage(33), _tirage(33)
        suite_1 = [composer(declencheurs, tirage=t1) for _ in range(20)]
        suite_2 = [composer(declencheurs, tirage=t2) for _ in range(20)]
        assert suite_1 == suite_2
        # …et elle varie d'un tour à l'autre : c'est tout l'objet du module.
        assert len(set(suite_1)) > 1

    def test_le_liant_lui_meme_varie(self):
        """Trois fragments différents cousus par un liant fixe se lisent comme
        une seule phrase à trous."""
        declencheurs = [_decl("a", "alpha"), _decl("b", "beta")]
        t = _tirage(44)
        liants_vus = set()
        for _ in range(40):
            phrase = composer(declencheurs, tirage=t)
            for liant in LIANTS:
                if liant.texte in phrase:
                    liants_vus.add(liant.texte)
        assert len(liants_vus) >= 2


# ── Garde structurelle ───────────────────────────────────────────────────────


class TestPurete:
    """Le module ne doit rien importer du projet.

    Il est appelé depuis les boucles de fond et depuis des fonctions pures
    (scoring, trust, circadian) dont les tests seraient faussés par une lecture
    de configuration : ``config_service`` amorce son cache depuis la vraie
    ``data/vtuber.db``, donc un import de projet ici ferait mesurer aux tests
    la base du développeur au lieu de la calibration déclarée.
    """

    PAQUETS_PROJET = {
        "ai", "communication", "emotion", "drives", "memory", "conscience",
        "modules", "projects", "identity", "files", "GestionSysteme", "configs",
        "config", "pipeline", "utils", "django", "channels", "asgiref",
    }

    def test_aucun_import_du_projet(self):
        source = Path(__file__).resolve().parents[1] / "utils" / "phrasing.py"
        arbre = ast.parse(source.read_text(encoding="utf-8"))
        racines = set()
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Import):
                racines |= {a.name.split(".")[0] for a in noeud.names}
            elif isinstance(noeud, ast.ImportFrom) and noeud.level == 0 and noeud.module:
                racines.add(noeud.module.split(".")[0])
            elif isinstance(noeud, ast.ImportFrom) and noeud.level:
                racines.add("<relatif>")
        interdits = racines & (self.PAQUETS_PROJET | {"<relatif>"})
        assert not interdits, f"imports interdits : {sorted(interdits)}"

    def test_les_constantes_sont_au_niveau_module(self):
        """Le repli doit être un ``ast.Name`` de module.

        La garde AST de ``test_config_rapatriement.py`` résout un repli en
        attribut du module et ignore silencieusement un ``self._X`` : une
        constante rangée en attribut de classe sortirait du champ de la
        vérification le jour où ces valeurs seront rapatriées en configuration.
        """
        defauts = ReglagePhrasing()
        assert defauts.memoire == MEMOIRE_TIRAGE
        assert defauts.amortissement == AMORTISSEMENT
