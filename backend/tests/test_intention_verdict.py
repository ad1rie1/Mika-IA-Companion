"""Lecture du verdict d'un pas de travail — ``conscience/verdict.py``.

Chaque test épingle une **propriété** du lecteur, pas une valeur choisie au
hasard. La propriété générale, celle qui justifie le module, est la dernière
classe : quelle que soit la suite d'octets rendue par le modèle, la lecture
rend un verdict et ne lève pas. Une exception ici tomberait dans une boucle de
fond que personne ne supervise.

Module pur : aucune base, aucun réseau — ce fichier n'a donc pas de
``django_db``.
"""

import math

import pytest

from conscience.verdict import (
    BLOC_MAX_CHARS,
    CONSIGNE_VERDICT,
    DELAI_DEFAUT_S,
    DELAI_MAX_S,
    EtatVerdict,
    NiveauVerdict,
    RESUME_MAX_CHARS,
    Verdict,
    VerdictTuning,
    depouiller_verdict,
    lire_verdict,
    texte_sans_verdict,
)


def bloc(corps: str) -> str:
    return f"--- VERDICT ---\n{corps}\n--- FIN VERDICT ---"


# ---------------------------------------------------------------------------
# Niveau 1 — le bloc délimité, ce que le prompt demande
# ---------------------------------------------------------------------------

class TestNiveau1BlocDelimite:

    def test_le_bloc_nominal_donne_letat_le_resume_et_son_niveau(self):
        texte = "Je regarde les flux.\n" + bloc(
            '{"etat": "continue", "resume": "trois flux lus, rien de neuf"}'
        )
        v = lire_verdict(texte)
        assert v.etat is EtatVerdict.CONTINUE
        assert v.resume == "trois flux lus, rien de neuf"
        assert v.niveau is NiveauVerdict.BLOC
        assert v.present and v.exploitable

    def test_un_json_tronque_garde_letat_encore_lisible(self):
        """La panne la plus banale d'un petit modèle : la coupure en plein
        milieu de l'objet. L'état, lui, est écrit et intact — le jeter ferait
        compter comme « sans verdict » une passe qui en avait un."""
        texte = bloc('{"etat": "bloque", "motif": "il me manque la clef API')
        v = lire_verdict(texte)
        assert v.etat is EtatVerdict.BLOQUE
        assert v.niveau is NiveauVerdict.BLOC
        assert "clef API" in v.motif_blocage

    def test_un_delimiteur_jamais_referme_reste_lisible(self):
        """Un modèle coupé par sa limite de tokens n'écrit pas la fermeture.
        Exiger les deux délimiteurs perdrait le verdict précisément quand la
        réponse a été tronquée."""
        texte = 'Bon.\n--- VERDICT ---\n{"etat": "fini", "resume": "envoyé"}'
        v = lire_verdict(texte)
        assert v.etat is EtatVerdict.FINI
        assert v.niveau is NiveauVerdict.BLOC

    def test_deux_blocs_le_dernier_fait_foi(self):
        """Deux blocs veut dire qu'elle s'est reprise (gabarit recopié, ou
        correction). Le mot final est celui de la fin."""
        texte = bloc('{"etat": "continue"}') + "\nfinalement...\n" + bloc(
            '{"etat": "fini", "resume": "c\'est bon"}'
        )
        v = lire_verdict(texte)
        assert v.etat is EtatVerdict.FINI
        assert v.resume == "c'est bon"

    def test_un_bloc_enferme_dans_une_fence_markdown_est_lu(self):
        texte = "```\n" + bloc('{"etat": "attendre", "delai_s": 120}') + "\n```"
        v = lire_verdict(texte)
        assert v.etat is EtatVerdict.ATTENDRE
        assert v.delai_s == 120.0

    def test_du_json_fence_a_linterieur_du_bloc_est_lu(self):
        texte = bloc('```json\n{"etat": "fini"}\n```')
        assert lire_verdict(texte).etat is EtatVerdict.FINI

    def test_les_accents_ne_changent_pas_letat(self):
        """« bloqué » et « bloque » sont le même état : l'accent n'est pas un
        choix que le modèle fait exprès."""
        accentue = lire_verdict(bloc('{"état": "bloqué", "motif": "clé absente"}'))
        assert accentue.etat is EtatVerdict.BLOQUE
        assert accentue.motif_blocage == "clé absente"

    def test_les_noms_de_clefs_anglais_sont_acceptes(self):
        v = lire_verdict(bloc('{"state": "in_progress", "summary": "je lis"}'))
        assert v.etat is EtatVerdict.CONTINUE
        assert v.resume == "je lis"

    def test_un_etat_invente_est_present_mais_inexploitable(self):
        """Le format est respecté, l'état ne veut rien dire. Les deux
        compteurs sont distincts : traduire l'inconnu en « continue » ferait
        tourner pour toujours un travail dont personne ne comprend le
        verdict."""
        v = lire_verdict(bloc('{"etat": "peut-etre", "resume": "hmm"}'))
        assert v.etat is EtatVerdict.ILLISIBLE
        assert v.niveau is NiveauVerdict.BLOC
        assert v.present is True
        assert v.exploitable is False

    def test_un_bloc_vide_est_present_et_inexploitable(self):
        v = lire_verdict(bloc("   "))
        assert v.etat is EtatVerdict.ILLISIBLE
        assert v.niveau is NiveauVerdict.BLOC

    def test_un_bloc_illisible_laisse_sa_chance_a_un_marqueur(self):
        """Le repli ne va que dans ce sens : un marqueur ne renverse jamais un
        bloc lisible, mais il rattrape un bloc cassé."""
        texte = bloc("...") + "\n[SUITE:fini]"
        v = lire_verdict(texte)
        assert v.etat is EtatVerdict.FINI
        assert v.niveau is NiveauVerdict.MARQUEUR

    def test_un_marqueur_ne_renverse_pas_un_bloc_lisible(self):
        texte = "[SUITE:bloque:vieux marqueur]\n" + bloc('{"etat": "fini"}')
        v = lire_verdict(texte)
        assert v.etat is EtatVerdict.FINI
        assert v.niveau is NiveauVerdict.BLOC

    def test_le_corps_analyse_est_borne(self):
        """Un délimiteur ouvert capture jusqu'à la fin du texte ; sans borne,
        une réponse de 100 000 caractères deviendrait un corps de verdict."""
        t = VerdictTuning(bloc_max_chars=40)
        texte = "--- VERDICT ---\n" + "x" * 5000 + '\n{"etat": "fini"}'
        v = lire_verdict(texte, t)
        assert v.etat is EtatVerdict.ILLISIBLE
        assert len(v.brut) <= 40  # tronqué au corps analysé, jamais 5 000


# ---------------------------------------------------------------------------
# Niveau 2 — le marqueur court
# ---------------------------------------------------------------------------

class TestNiveau2Marqueur:

    def test_le_marqueur_nu_donne_letat_et_son_niveau(self):
        v = lire_verdict("j'ai regardé, rien à signaler.\n[SUITE:continue]")
        assert v.etat is EtatVerdict.CONTINUE
        assert v.niveau is NiveauVerdict.MARQUEUR

    def test_le_marqueur_dattente_porte_son_delai(self):
        v = lire_verdict("[SUITE:attendre:600]")
        assert v.etat is EtatVerdict.ATTENDRE
        assert v.delai_s == 600.0
        # Le délai n'est pas aussi recopié en résumé : un nombre nu n'a rien à
        # faire dans le journal de travail.
        assert v.resume == ""

    def test_le_marqueur_de_blocage_porte_son_motif(self):
        v = lire_verdict("[SUITE:bloque:il me manque la clef API]")
        assert v.etat is EtatVerdict.BLOQUE
        assert v.motif_blocage == "il me manque la clef API"

    def test_la_forme_sans_crochets_en_debut_de_ligne_est_acceptee(self):
        v = lire_verdict("bla bla\nSUITE: fini\n")
        assert v.etat is EtatVerdict.FINI
        assert v.niveau is NiveauVerdict.MARQUEUR

    def test_le_mot_suite_en_pleine_prose_nest_pas_un_verdict(self):
        """Sinon « on verra la suite : demain » deviendrait un verdict, et
        serait au passage retiré de ce qu'elle dit."""
        texte = "On verra la suite : demain, quand j'aurai le temps."
        v = lire_verdict(texte)
        assert v.niveau is NiveauVerdict.ABSENT
        assert texte_sans_verdict(texte) == texte

    def test_le_dernier_marqueur_fait_foi(self):
        v = lire_verdict("[SUITE:continue]\npuis\n[SUITE:fini]")
        assert v.etat is EtatVerdict.FINI

    def test_un_marqueur_a_letat_invente_est_present_et_inexploitable(self):
        v = lire_verdict("[SUITE:bof]")
        assert v.etat is EtatVerdict.ILLISIBLE
        assert v.niveau is NiveauVerdict.MARQUEUR
        assert v.present and not v.exploitable

    def test_un_crochet_jamais_referme_navale_pas_la_reponse(self):
        v = lire_verdict("[SUITE:continue\net puis j'ai encore parlé longtemps")
        assert v.niveau is NiveauVerdict.ABSENT


# ---------------------------------------------------------------------------
# Niveau 3 — l'absence, rendue comme un fait
# ---------------------------------------------------------------------------

class TestNiveau3Absence:

    def test_une_reponse_sans_verdict_est_absente_pas_en_erreur(self):
        """C'est le point du module : l'appelant doit pouvoir *compter* les
        passes sans verdict pour finir par bloquer un travail qui n'en produit
        jamais, au lieu de boucler."""
        v = lire_verdict("J'ai bien avancé sur le sujet, c'était intéressant.")
        assert v.etat is EtatVerdict.ILLISIBLE
        assert v.niveau is NiveauVerdict.ABSENT
        assert v.present is False
        assert v.exploitable is False

    def test_un_texte_vide_est_absent(self):
        for vide in ("", "   \n\t ", None):
            v = lire_verdict(vide)
            assert v.niveau is NiveauVerdict.ABSENT

    def test_absent_et_illisible_se_distinguent(self):
        """Deux pannes différentes : « elle n'a rien écrit » appelle un rappel
        de format, « j'ai un bloc que je ne sais pas lire » est un défaut du
        lecteur ou un état inventé."""
        rien = lire_verdict("bonjour")
        casse = lire_verdict(bloc('{"etat": "zzz"}'))
        assert rien.etat is casse.etat is EtatVerdict.ILLISIBLE
        assert rien.niveau is not casse.niveau


# ---------------------------------------------------------------------------
# Délais
# ---------------------------------------------------------------------------

class TestDelais:

    def test_le_delai_nexiste_que_pour_lattente(self):
        """Sinon l'appelant ne pourrait pas distinguer « elle a dit d'attendre
        0 s » de « elle n'a pas parlé d'attente »."""
        assert lire_verdict(bloc('{"etat": "fini", "delai_s": 60}')).delai_s is None
        assert lire_verdict(bloc('{"etat": "attendre", "delai_s": 0}')).delai_s == 0.0

    def test_une_attente_sans_delai_prend_le_defaut(self):
        v = lire_verdict(bloc('{"etat": "attendre"}'))
        assert v.delai_s == DELAI_DEFAUT_S

    def test_un_delai_negatif_devient_tout_de_suite(self):
        v = lire_verdict(bloc('{"etat": "attendre", "delai_s": -42}'))
        assert v.delai_s == 0.0

    def test_un_delai_absurde_est_ramene_dans_le_domaine(self):
        """`604800` n'est pas une attente dans une session de veille : c'est
        une action programmée, qui a son propre modèle."""
        for absurde in ("999999999", "1e12"):
            v = lire_verdict(bloc(f'{{"etat": "attendre", "delai_s": {absurde}}}'))
            assert v.delai_s == DELAI_MAX_S

    def test_un_delai_non_fini_ne_traverse_pas_la_lecture(self):
        """``json.loads`` accepte ``Infinity`` et ``NaN``, et un ``NaN``
        traverse silencieusement ``min``/``max`` pour ressortir intact dans un
        calcul d'échéance."""
        for pathologique in ("Infinity", "-Infinity", "NaN"):
            v = lire_verdict(bloc(f'{{"etat": "attendre", "delai_s": {pathologique}}}'))
            assert v.delai_s is not None
            assert math.isfinite(v.delai_s)
            assert 0.0 <= v.delai_s <= DELAI_MAX_S

    def test_un_delai_textuel_est_lu_quand_il_contient_un_nombre(self):
        assert lire_verdict(bloc('{"etat": "attendre", "delai_s": "600 s"}')).delai_s == 600.0
        assert lire_verdict(bloc('{"etat": "attendre", "delai_s": "bientot"}')).delai_s == DELAI_DEFAUT_S

    def test_un_booleen_nest_pas_une_seconde(self):
        v = lire_verdict(bloc('{"etat": "attendre", "delai_s": true}'))
        assert v.delai_s == DELAI_DEFAUT_S


# ---------------------------------------------------------------------------
# Nettoyage du texte dit à voix haute
# ---------------------------------------------------------------------------

class TestNettoyageDuTexte:

    def test_le_bloc_ne_reste_pas_dans_ce_quelle_dit(self):
        """Sa comptabilité partirait sinon en TTS, dans l'historique relu au
        tour suivant et dans l'extraction nocturne — le défaut que
        ``strip_prosody`` répare pour les jetons de prosodie."""
        texte = "J'ai lu les trois flux.\n" + bloc('{"etat": "continue"}')
        propre = texte_sans_verdict(texte)
        assert propre == "J'ai lu les trois flux."
        assert "VERDICT" not in propre

    def test_les_deux_blocs_partent_pas_seulement_celui_qui_a_ete_lu(self):
        texte = bloc('{"etat": "continue"}') + "\nvoilà.\n" + bloc('{"etat": "fini"}')
        assert texte_sans_verdict(texte) == "voilà."

    def test_le_marqueur_part_aussi(self):
        assert texte_sans_verdict("c'est fait. [SUITE:fini]") == "c'est fait."

    def test_la_fence_devenue_vide_ne_reste_pas_orpheline(self):
        texte = "voilà.\n```json\n" + bloc('{"etat": "fini"}') + "\n```"
        propre = texte_sans_verdict(texte)
        assert propre == "voilà."
        assert "```" not in propre

    def test_un_bloc_non_referme_est_retire_jusqua_la_fin(self):
        texte = 'Bon.\n--- VERDICT ---\n{"etat": "fini"'
        assert texte_sans_verdict(texte) == "Bon."

    def test_un_texte_sans_verdict_est_rendu_intact(self):
        texte = "Rien de spécial à signaler aujourd'hui."
        assert texte_sans_verdict(texte) == texte

    def test_depouiller_rend_les_deux_lectures_daccord(self):
        """Les séparer invite à n'en faire qu'une, et un verdict lu mais pas
        retiré du texte est prononcé à voix haute."""
        texte = "fini pour moi.\n" + bloc('{"etat": "fini"}')
        dit, v = depouiller_verdict(texte)
        assert dit == "fini pour moi."
        assert v.etat is EtatVerdict.FINI


# ---------------------------------------------------------------------------
# Bornes de recopie
# ---------------------------------------------------------------------------

class TestBornesDeRecopie:

    def test_le_resume_est_borne(self):
        """Il finit dans un journal puis sous les yeux du modèle au tour
        suivant : une hallucination de dix mille caractères ne doit pas
        devenir un bloc de prompt."""
        long = "a" * 10_000
        v = lire_verdict(bloc(f'{{"etat": "continue", "resume": "{long}"}}'))
        assert len(v.resume) <= RESUME_MAX_CHARS

    def test_lextrait_brut_est_borne(self):
        v = lire_verdict(bloc("z" * 9_000))
        assert len(v.brut) <= BLOC_MAX_CHARS
        assert len(v.brut) < 1_000

    def test_un_resume_non_textuel_ne_fait_pas_tomber_la_lecture(self):
        v = lire_verdict(bloc('{"etat": "fini", "resume": ["a", "b"]}'))
        assert v.etat is EtatVerdict.FINI
        assert isinstance(v.resume, str)


# ---------------------------------------------------------------------------
# La consigne et le lecteur ne peuvent pas diverger
# ---------------------------------------------------------------------------

class TestConsigneEtLecteurSaccordent:

    def test_lexemple_de_la_consigne_est_relu_par_le_lecteur(self):
        """Un format décrit dans un fichier de prompt et analysé dans un autre
        finit par diverger d'un délimiteur ou d'un nom de clef, et la
        divergence est silencieuse : le lecteur rend « illisible », la boucle
        tourne, personne ne voit pourquoi."""
        v = lire_verdict(CONSIGNE_VERDICT)
        assert v.niveau is NiveauVerdict.BLOC
        assert v.etat is EtatVerdict.CONTINUE

    def test_les_marqueurs_cites_par_la_consigne_sont_lisibles(self):
        """Même exigence pour le niveau 2 : ce que la consigne montre en
        exemple doit être exactement ce que le lecteur sait relire."""
        consigne = " ".join(CONSIGNE_VERDICT.split())
        for exemple, attendu in (
            ("[SUITE:continue]", EtatVerdict.CONTINUE),
            ("[SUITE:attendre:600]", EtatVerdict.ATTENDRE),
            ("[SUITE:bloque:il me manque la clef API]", EtatVerdict.BLOQUE),
        ):
            assert exemple in consigne
            assert lire_verdict(exemple).etat is attendu


# ---------------------------------------------------------------------------
# La propriété qui justifie le module : rien ne lève, jamais
# ---------------------------------------------------------------------------

HOSTILES = [
    "",
    "   ",
    None,
    b"des octets bruts",
    b"\xff\xfe\x00 invalide",
    12345,
    ["pas une chaine"],
    bloc('{"etat": '),                       # JSON coupé au deux-points
    bloc('{"etat": "continue"'),             # accolade jamais refermée
    "--- VERDICT ---",                       # délimiteur seul
    "--- FIN VERDICT ---",                   # fermeture orpheline
    "--- VERDICT --- --- VERDICT --- --- FIN VERDICT ---",
    bloc(bloc('{"etat": "fini"}')),          # bloc dans un bloc
    "```" + bloc('{"etat": "fini"}'),        # fence jamais refermée
    "[SUITE:",
    "[SUITE::]",
    "[SUITE:attendre:-1]",
    "[SUITE:attendre:999999999999]",
    "[SUITE:attendre:pas un nombre]",
    bloc('{"etat": "attendre", "delai_s": {"nested": 1}}'),
    bloc('{"etat": null, "resume": null}'),
    bloc('["une", "liste"]'),
    bloc('{"ETAT": "FINI"}'),
    "é" * 5_000,
    "\x00\x01\x02" + bloc('{"etat": "fini"}'),
    "x" * 100_000,
    "x" * 100_000 + bloc('{"etat": "fini"}'),
    bloc('{"etat": "continue"}') * 50,
]


class TestAucuneEntreeNeLeve:

    @pytest.mark.parametrize("entree", HOSTILES, ids=range(len(HOSTILES)))
    def test_la_lecture_rend_toujours_un_verdict_defendable(self, entree):
        v = lire_verdict(entree)
        assert isinstance(v, Verdict)
        assert isinstance(v.etat, EtatVerdict)
        assert isinstance(v.niveau, NiveauVerdict)
        assert isinstance(v.resume, str) and isinstance(v.motif_blocage, str)
        # Un délai n'existe que pour une attente, et il est toujours fini et
        # dans le domaine : c'est lui qui part dans un calcul d'échéance.
        if v.etat is EtatVerdict.ATTENDRE:
            assert v.delai_s is not None
            assert math.isfinite(v.delai_s)
            assert 0.0 <= v.delai_s <= DELAI_MAX_S
        else:
            assert v.delai_s is None
        # Un état inexploitable ne porte jamais de décision déguisée.
        if not v.exploitable:
            assert v.etat is EtatVerdict.ILLISIBLE

    @pytest.mark.parametrize("entree", HOSTILES, ids=range(len(HOSTILES)))
    def test_le_nettoyage_rend_toujours_une_chaine(self, entree):
        propre = texte_sans_verdict(entree)
        assert isinstance(propre, str)
        # Ce qui est lu comme un verdict ne doit jamais rester dans ce qu'elle
        # dit : la réciproque du test précédent.
        if lire_verdict(entree).niveau is NiveauVerdict.BLOC:
            assert "--- VERDICT ---" not in propre

    @pytest.mark.parametrize("entree", HOSTILES, ids=range(len(HOSTILES)))
    def test_depouiller_ne_leve_pas_non_plus(self, entree):
        dit, v = depouiller_verdict(entree)
        assert isinstance(dit, str) and isinstance(v, Verdict)


class TestPurete:

    def test_le_module_ne_lit_ni_base_ni_configuration(self):
        """Le motif de ``ScoringTuning`` : les réglages sont une dataclasse
        gelée résolue au bord. Un ``cfg_*`` ici ferait mesurer aux tests la
        base de la machine qui les exécute, et non la calibration déclarée."""
        import ast
        import pathlib

        source = pathlib.Path(
            pathlib.Path(__file__).resolve().parents[1] / "conscience" / "verdict.py"
        ).read_text(encoding="utf-8")
        arbre = ast.parse(source)
        importes = set()
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Import):
                importes.update(a.name for a in noeud.names)
            elif isinstance(noeud, ast.ImportFrom) and noeud.module:
                importes.add(noeud.module)
        assert not any(
            m.startswith(("django", "configs", "conscience.models", "memory"))
            for m in importes
        ), importes
        assert "cfg_" not in source

    def test_le_reglage_par_defaut_reproduit_les_constantes(self):
        t = VerdictTuning()
        assert t.delai_defaut_s == DELAI_DEFAUT_S
        assert t.delai_max_s == DELAI_MAX_S
        assert t.resume_max_chars == RESUME_MAX_CHARS
        assert t.bloc_max_chars == BLOC_MAX_CHARS

    def test_le_verdict_est_immuable(self):
        """Il voyage jusque dans un journal et un prompt : personne ne doit
        pouvoir le retoucher en chemin."""
        v = lire_verdict("[SUITE:fini]")
        with pytest.raises(Exception):
            v.etat = EtatVerdict.CONTINUE  # type: ignore[misc]


class TestNotabilite:
    """Le champ `notable` : l'auto-évaluation qui décide QUOI diffuser,
    pas seulement quand. `None` = non prononcé — l'appelant choisit son
    défaut, et l'absence reproduit le comportement d'avant."""

    def test_notable_lu_dans_le_bloc(self):
        from conscience.verdict import lire_verdict

        v = lire_verdict(
            '--- VERDICT ---\n'
            '{"etat": "fini", "resume": "ok", "notable": 0.9}\n'
            '--- FIN VERDICT ---'
        )
        assert v.notable == 0.9

    def test_absent_vaut_none_jamais_zero(self):
        from conscience.verdict import lire_verdict

        v = lire_verdict(
            '--- VERDICT ---\n{"etat": "fini", "resume": "ok"}\n--- FIN VERDICT ---'
        )
        assert v.notable is None

    def test_hors_domaine_ramene_dans_la_borne(self):
        from conscience.verdict import lire_verdict

        v = lire_verdict(
            '--- VERDICT ---\n{"etat": "fini", "notable": 3}\n--- FIN VERDICT ---'
        )
        assert v.notable == 1.0

    def test_illisible_vaut_none(self):
        from conscience.verdict import lire_verdict

        v = lire_verdict(
            '--- VERDICT ---\n{"etat": "fini", "notable": "beaucoup"}\n--- FIN VERDICT ---'
        )
        assert v.notable is None

    def test_la_consigne_produit_toujours_un_bloc_lisible(self):
        """L'exemple de la consigne — champ notable compris — se relit."""
        from conscience.verdict import CONSIGNE_VERDICT, NiveauVerdict, lire_verdict

        v = lire_verdict(CONSIGNE_VERDICT)
        assert v.niveau is NiveauVerdict.BLOC
        assert v.notable == 0.3
