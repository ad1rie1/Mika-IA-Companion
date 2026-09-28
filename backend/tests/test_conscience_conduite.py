"""Ce que ``conscience/conduite.py`` promet, règle par règle.

Le module est **pur** : pas de base, pas de registre, pas d'horloge implicite.
Ce fichier n'a donc besoin ni de ``django_db`` ni de fixture — et c'est
volontaire : les seuils qu'il mesure sont ceux *déclarés* dans le module, pas
ceux que contient la base de la machine qui exécute la suite.

Chaque test épingle une propriété et son nom la dit. Les valeurs numériques
qui apparaissent viennent d'ailleurs (``interpreter.py`` pour les pertinences
du chemin heuristique) ou sont volontairement prises de part et d'autre d'une
porte : elles ne sont jamais choisies pour faire passer le test.
"""

from datetime import datetime, timedelta

import pytest

from conscience.conduite import (
    Conduite,
    ConduiteTuning,
    Decision,
    Diffusion,
    Graine,
    TravailEnCours,
    choisir_conduite,
    decider_diffusion,
    envie_courante,
    est_essouffle,
    facturer_envie,
    recolter_graines,
    travail_a_poursuivre,
)

T0 = datetime(2026, 3, 14, 15, 0, 0)


class _Obs:
    """Double d'``Observation`` : ce module ne doit rien savoir de l'ORM.

    S'il exigeait autre chose que des attributs, ce double le révélerait.
    """

    def __init__(self, pertinence, summary="quelque chose", pk=1, event_type="x"):
        self.pertinence = pertinence
        self.summary = summary
        self.pk = pk
        self.event_type = event_type


def _travail(**kw) -> TravailEnCours:
    base = dict(identifiant=1, titre="un travail", envie=0.8, ancre_envie=T0)
    base.update(kw)
    return TravailEnCours(**base)


# ---------------------------------------------------------------------------
# 1. La porte de récolte — la raison d'être du module
# ---------------------------------------------------------------------------

class TestPorteDeRecolte:

    def test_un_rss_apparie_franchit_la_porte(self):
        """0.55 est le plafond du chemin heuristique (`PERTINENCE_RSS_MATCHED`) :
        un signal extérieur réellement apparié à ses thèmes doit pouvoir
        ouvrir un chantier, sinon la porte ne laisse rien passer du tout."""
        from conscience.interpreter import PERTINENCE_RSS_MATCHED

        graines = recolter_graines(
            observations=[_Obs(PERTINENCE_RSS_MATCHED, "un article sur les VRM")],
        )
        assert [g.origine for g in graines] == ["observation"]
        assert graines[0].intitule == "un article sur les VRM"

    def test_un_message_telegram_est_refuse(self):
        """0.40 : chaque phrase qu'on lui adresse. À 0.35 de porte, elle
        ouvrirait un travail au lieu de répondre à la conversation en cours."""
        from conscience.interpreter import PERTINENCE_TELEGRAM_MESSAGE

        assert recolter_graines(observations=[_Obs(PERTINENCE_TELEGRAM_MESSAGE)]) == []

    def test_un_message_de_chat_est_refuse(self):
        from conscience.interpreter import PERTINENCE_CHAT_MESSAGE

        assert recolter_graines(observations=[_Obs(PERTINENCE_CHAT_MESSAGE)]) == []

    def test_la_porte_est_bien_calee_entre_les_deux(self):
        """La propriété, énoncée sans passer par le module : le trafic
        conversationnel est sous la porte, le RSS apparié au-dessus."""
        from conscience.conduite import GRAINE_OBS_PERTINENCE
        from conscience.interpreter import (
            PERTINENCE_CHAT_MESSAGE,
            PERTINENCE_RSS_MATCHED,
            PERTINENCE_TELEGRAM_MESSAGE,
        )

        assert PERTINENCE_CHAT_MESSAGE < GRAINE_OBS_PERTINENCE
        assert PERTINENCE_TELEGRAM_MESSAGE < GRAINE_OBS_PERTINENCE
        assert PERTINENCE_RSS_MATCHED > GRAINE_OBS_PERTINENCE

    def test_la_porte_est_inclusive(self):
        """Une valeur pile sur la porte passe : une porte exclusive rend le
        seuil déclaré différent du seuil effectif."""
        from conscience.conduite import GRAINE_OBS_PERTINENCE

        assert len(recolter_graines(observations=[_Obs(GRAINE_OBS_PERTINENCE)])) == 1


class TestRecolteDesPensees:

    def test_une_pensee_vive_devient_une_amorce(self):
        """Une pensée qui persiste est littéralement un travail non fait."""
        lignes = [{"id": 7, "summary": "je n'ai jamais répondu à Alice",
                   "themes": ["alice"], "intensity": 0.6, "emotion": "anxious"}]
        graines = recolter_graines(pensees=lignes)
        assert len(graines) == 1
        assert graines[0].reference == 7
        assert graines[0].themes == ("alice",)

    def test_une_pensee_qui_s_eteint_ne_seme_rien(self):
        """La demi-vie de 6 h fait descendre les ruminations ; on n'ouvre pas
        un chantier sur ce qui est en train de disparaître."""
        lignes = [{"id": 7, "summary": "vieux truc", "themes": [],
                   "intensity": 0.2, "emotion": ""}]
        assert recolter_graines(pensees=lignes) == []

    def test_des_themes_malformes_ne_tuent_pas_la_recolte(self):
        """`themes` est un JSONField : rien ne garantit une liste de chaînes,
        et une boucle de fond que personne ne supervise ne doit pas mourir
        d'une ligne mal écrite."""
        lignes = [{"id": 7, "summary": "ok", "themes": {"pas": "une liste"},
                   "intensity": 0.9}]
        graines = recolter_graines(pensees=lignes)
        assert len(graines) == 1 and graines[0].themes == ()


class TestRecolteDesPulsions:

    def test_la_curiosite_saillante_seme(self):
        """H1 : la curiosité montait, poussait le score, produisait une phrase,
        et rien ne choisissait un sujet."""
        graines = recolter_graines(pulsions=[("curiosity", 0.7)])
        assert [g.reference for g in graines] == ["curiosity"]

    def test_le_repos_ne_seme_jamais(self):
        """Ouvrir un chantier parce qu'elle est fatiguée serait l'inverse de
        ce que REST demande."""
        assert recolter_graines(pulsions=[("rest", 0.99)]) == []

    def test_le_social_peut_preparer_un_contact_hors_chat(self):
        graines = recolter_graines(pulsions=[("social", 0.99)])
        assert len(graines) == 1 and graines[0].reference == "social"
        assert graines[0].modules == ("email", "identity_tools")

    def test_une_pulsion_sous_la_porte_ne_seme_pas(self):
        assert recolter_graines(pulsions=[("curiosity", 0.3)]) == []


class TestRecolteGlobale:

    def test_les_amorces_sortent_par_poids_decroissant(self):
        graines = recolter_graines(
            observations=[_Obs(0.5, pk=1), _Obs(0.9, pk=2)],
            pulsions=[("curiosity", 0.7)],
        )
        assert [g.poids for g in graines] == sorted(
            [g.poids for g in graines], reverse=True
        )

    def test_la_recolte_est_plafonnee(self):
        """Au-delà, la liste n'est plus un choix mais un inventaire."""
        tuning = ConduiteTuning(graines_max=2)
        graines = recolter_graines(
            observations=[_Obs(0.9, pk=i) for i in range(10)], tuning=tuning,
        )
        assert len(graines) == 2

    def test_une_ligne_illisible_ne_perd_pas_les_autres(self):
        """Une source malformée est comptée et sautée ; les autres sources
        sont peut-être saines, et la boucle doit survivre."""
        class Cassee:
            @property
            def pertinence(self):
                raise RuntimeError("colonne absente")

        graines = recolter_graines(
            observations=[Cassee(), _Obs(0.9, "sain")],
        )
        assert [g.intitule for g in graines] == ["sain"]

    def test_une_recolte_vide_est_une_liste_vide(self):
        assert recolter_graines() == []


# ---------------------------------------------------------------------------
# 2. L'envie — une ancre en temps réel, pas un compteur de tours
# ---------------------------------------------------------------------------

class TestEnvie:

    def test_l_envie_decroit_de_moitie_par_demi_vie(self):
        travail = _travail(envie=0.8, ancre_envie=T0)
        plus_tard = T0 + timedelta(seconds=ConduiteTuning().envie_demi_vie_s)
        assert envie_courante(travail, plus_tard) == pytest.approx(0.4)

    def test_la_decroissance_suit_le_temps_pas_le_nombre_d_appels(self):
        """C'est LA propriété. `Rumination` décroissait de 0.95 par cycle de
        30 s : sa durée de vie dépendait de la cadence de la boucle et elle
        s'éteignait en 22 min quand tous ses lecteurs raisonnaient en heures.
        Ici, mille lectures au même instant valent une seule."""
        travail = _travail(envie=0.8, ancre_envie=T0)
        instant = T0 + timedelta(hours=1)
        valeurs = {envie_courante(travail, instant) for _ in range(1000)}
        assert len(valeurs) == 1

    def test_lire_ne_facture_rien(self):
        """L'ancre n'avance qu'à l'écriture : une lecture ne modifie pas le
        travail, qui est gelé."""
        travail = _travail(envie=0.8, ancre_envie=T0)
        envie_courante(travail, T0 + timedelta(hours=3))
        assert travail.envie == 0.8 and travail.ancre_envie == T0

    def test_facturer_rend_la_valeur_et_l_ancre_ensemble(self):
        """Les deux moitiés du geste ne doivent pas pouvoir se séparer :
        écrire la valeur sans l'ancre re-facturerait le même temps, écrire
        l'ancre sans la valeur effacerait la décroissance."""
        travail = _travail(envie=0.8, ancre_envie=T0)
        plus_tard = T0 + timedelta(hours=6)
        envie, ancre = facturer_envie(travail, plus_tard)
        assert envie == pytest.approx(0.4) and ancre == plus_tard

    def test_facturer_puis_refacturer_ne_double_pas_la_decroissance(self):
        """Le temps déjà facturé ne l'est pas deux fois — le défaut exact de
        `Connaissance`, ancrée sur un `auto_now` que Django ne rafraîchissait
        pas sous `update_fields`."""
        travail = _travail(envie=0.8, ancre_envie=T0)
        t1 = T0 + timedelta(hours=6)
        envie1, ancre1 = facturer_envie(travail, t1)
        travail2 = _travail(envie=envie1, ancre_envie=ancre1)
        envie2, _ = facturer_envie(travail2, t1 + timedelta(hours=6))
        assert envie2 == pytest.approx(0.2)

    def test_un_retour_d_horloge_n_augmente_jamais_l_envie(self):
        """NTP, changement d'heure, ligne écrite dans le futur : facturer un
        temps négatif *ressusciterait* un travail mort."""
        travail = _travail(envie=0.5, ancre_envie=T0)
        assert envie_courante(travail, T0 - timedelta(hours=10)) == 0.5

    def test_sans_ancre_l_envie_est_celle_ecrite(self):
        """Une ligne d'avant la migration n'a pas d'ancre ; la lire comme
        « infiniment vieille » abandonnerait tous les travaux existants."""
        assert envie_courante(_travail(envie=0.7, ancre_envie=None), T0) == 0.7

    def test_un_travail_tombe_sous_le_plancher_est_essouffle(self):
        travail = _travail(envie=0.8, ancre_envie=T0)
        assert not est_essouffle(travail, T0)
        assert est_essouffle(travail, T0 + timedelta(hours=24))


# ---------------------------------------------------------------------------
# 3. Le choix d'un travail à poursuivre
# ---------------------------------------------------------------------------

class TestTravailAPoursuivre:

    def test_un_travail_vif_et_espace_merite_un_pas(self):
        travail = _travail(dernier_pas_le=T0 - timedelta(hours=2))
        assert travail_a_poursuivre([travail], T0) is travail

    def test_un_pas_trop_recent_est_refuse(self):
        """La boucle tourne toutes les 30 s : sans espacement, un travail
        brûlerait tous ses pas en quelques minutes — l'inverse exact de
        « aller au bout de quelque chose »."""
        travail = _travail(dernier_pas_le=T0 - timedelta(minutes=2))
        assert travail_a_poursuivre([travail], T0) is None

    def test_un_travail_jamais_visite_est_immediatement_du(self):
        assert travail_a_poursuivre([_travail(dernier_pas_le=None)], T0) is not None

    def test_un_travail_bloque_sur_quelqu_un_est_saute(self):
        """Un pas de plus ne ferait que reposer la même question."""
        travail = _travail(dernier_pas_le=None, en_attente_de_reponse=True)
        assert travail_a_poursuivre([travail], T0) is None

    def test_un_travail_au_bout_de_ses_pas_est_saute(self):
        travail = _travail(dernier_pas_le=None, pas_effectues=5, pas_max=5)
        assert travail_a_poursuivre([travail], T0) is None

    def test_pas_max_a_zero_veut_dire_sans_plafond(self):
        travail = _travail(dernier_pas_le=None, pas_effectues=99, pas_max=0)
        assert travail_a_poursuivre([travail], T0) is not None

    def test_une_envie_trop_faible_ne_merite_plus_de_pas(self):
        travail = _travail(envie=0.1, ancre_envie=T0, dernier_pas_le=None)
        assert travail_a_poursuivre([travail], T0) is None

    def test_le_plus_desire_passe_devant(self):
        mou = _travail(identifiant="mou", envie=0.3, dernier_pas_le=None)
        vif = _travail(identifiant="vif", envie=0.9, dernier_pas_le=None)
        assert travail_a_poursuivre([mou, vif], T0).identifiant == "vif"

    def test_a_envie_egale_le_plus_ancien_passe_devant(self):
        """Sinon un travail jamais visité serait indéfiniment doublé par son
        jumeau, et « aller au bout » redeviendrait un tirage au sort."""
        recent = _travail(
            identifiant="recent", envie=0.9,
            dernier_pas_le=T0 - timedelta(hours=1),
        )
        ancien = _travail(
            identifiant="ancien", envie=0.9,
            dernier_pas_le=T0 - timedelta(hours=9),
        )
        assert travail_a_poursuivre([recent, ancien], T0).identifiant == "ancien"


# ---------------------------------------------------------------------------
# 4. La conduite
# ---------------------------------------------------------------------------

class TestChoisirConduite:

    def test_le_silence_est_atteignable(self):
        """Sur 2 880 tours quotidiens, tout le reste est l'exception."""
        d = choisir_conduite(score=0.1, seuil=0.5)
        assert d.conduite is Conduite.SE_TAIRE and d.cible is None and d.motif

    def test_le_silence_est_l_issue_d_un_etat_totalement_vide(self):
        d = choisir_conduite(
            score=0.0, seuil=0.5, travaux=[], graines=[], maintenant=T0,
        )
        assert d.conduite is Conduite.SE_TAIRE

    def test_le_score_au_seuil_fait_parler(self):
        """La comparaison est `>=`, comme dans `_decide_inner` : la
        calibration du scoring n'est pas retouchée par ce module."""
        assert choisir_conduite(score=0.5, seuil=0.5).conduite is Conduite.PARLER

    def test_parler_prime_sur_un_travail_du(self):
        """Ce qui déclenchait un acte en déclenche toujours un, exactement :
        les conduites nouvelles ne vivent que dans l'ancien silence."""
        d = choisir_conduite(
            score=0.9, seuil=0.5,
            travaux=[_travail(dernier_pas_le=None)], maintenant=T0,
        )
        assert d.conduite is Conduite.PARLER

    def test_sous_le_seuil_un_travail_du_prend_la_main(self):
        """L'espace gagné est *exactement* celui qui s'appelait « wait »."""
        d = choisir_conduite(
            score=0.1, seuil=0.5,
            travaux=[_travail(identifiant=42, dernier_pas_le=None)],
            maintenant=T0,
        )
        assert d.conduite is Conduite.POURSUIVRE and d.cible == 42

    def test_poursuivre_prime_sur_ouvrir(self):
        """Finir ce qui est commencé avant d'entamer autre chose : c'est
        l'ouverture sans fin qui produit les travaux zombies."""
        d = choisir_conduite(
            score=0.1, seuil=0.5,
            travaux=[_travail(dernier_pas_le=None)],
            graines=[Graine("observation", 1, "une piste", 0.9)],
            maintenant=T0,
        )
        assert d.conduite is Conduite.POURSUIVRE

    def test_une_amorce_forte_ouvre_un_travail(self):
        graine = Graine("pensee", 3, "reprendre le sujet des VRM", 0.9)
        d = choisir_conduite(
            score=0.1, seuil=0.5, graines=[graine], maintenant=T0,
        )
        assert d.conduite is Conduite.OUVRIR and d.cible is graine

    def test_une_amorce_tiede_n_ouvre_rien(self):
        """Récolter est bon marché, ouvrir engage une des trois places pendant
        des heures : une amorce peut exister sans mériter un chantier. Ce test
        est ce qui a fait remonter les deux portes à des valeurs distinctes —
        égales, la seconde ne décidait rien."""
        d = choisir_conduite(
            score=0.1, seuil=0.5,
            graines=[Graine("observation", 1, "bof", 0.47)],
            maintenant=T0,
        )
        assert d.conduite is Conduite.SE_TAIRE

    def test_un_rss_apparie_va_de_la_recolte_a_l_ouverture(self):
        """Les deux portes doivent rester cohérentes : si celle d'ouverture
        passait au-dessus du plafond du chemin heuristique (0.55), le dehors
        pourrait être récolté mais plus jamais amorcer quoi que ce soit."""
        from conscience.interpreter import PERTINENCE_RSS_MATCHED

        graines = recolter_graines(
            observations=[_Obs(PERTINENCE_RSS_MATCHED, "un article apparié")],
        )
        d = choisir_conduite(
            score=0.1, seuil=0.5, graines=graines, maintenant=T0,
        )
        assert d.conduite is Conduite.OUVRIR

    def test_la_file_de_travaux_est_plafonnee(self):
        """Un quatrième travail ne serait plus jamais visité : à un pas par
        quart d'heure, la file se viderait plus lentement qu'elle ne se
        remplit."""
        pleins = [
            _travail(identifiant=i, dernier_pas_le=T0 - timedelta(minutes=1))
            for i in range(ConduiteTuning().travaux_actifs_max)
        ]
        d = choisir_conduite(
            score=0.1, seuil=0.5, travaux=pleins,
            graines=[Graine("observation", 1, "une piste", 0.9)],
            maintenant=T0,
        )
        assert d.conduite is Conduite.SE_TAIRE

    def test_un_travail_essouffle_libere_sa_place(self):
        """Sinon trois abandons suffiraient à interdire toute ouverture pour
        le reste de la vie de l'installation."""
        morts = [
            _travail(identifiant=i, envie=0.8, ancre_envie=T0,
                     dernier_pas_le=T0)
            for i in range(ConduiteTuning().travaux_actifs_max)
        ]
        d = choisir_conduite(
            score=0.1, seuil=0.5, travaux=morts,
            graines=[Graine("observation", 1, "une piste", 0.9)],
            maintenant=T0 + timedelta(hours=48),
        )
        assert d.conduite is Conduite.OUVRIR

    def test_ne_pas_pouvoir_parler_n_interdit_pas_de_travailler(self):
        """« Personne n'est joignable » et « elle dort » sont deux vetos
        distincts ; les confondre replongerait la conduite dans le binaire
        qu'elle sort."""
        d = choisir_conduite(
            score=0.9, seuil=0.5, peut_parler=False,
            travaux=[_travail(dernier_pas_le=None)], maintenant=T0,
        )
        assert d.conduite is Conduite.POURSUIVRE

    def test_ne_pas_pouvoir_travailler_rend_muette(self):
        """Le veto de sommeil ferme les deux conduites de travail : dormir
        n'est pas travailler en silence."""
        d = choisir_conduite(
            score=0.1, seuil=0.5, peut_travailler=False,
            travaux=[_travail(dernier_pas_le=None)],
            graines=[Graine("observation", 1, "une piste", 0.9)],
            maintenant=T0,
        )
        assert d.conduite is Conduite.SE_TAIRE

    def test_toute_decision_porte_un_motif_lisible(self):
        """`motif` finit dans `ConscienceLog.reason` et sur les écrans : une
        décision sans explication est un log qu'on n'ouvre jamais."""
        cas = [
            choisir_conduite(score=0.9, seuil=0.5),
            choisir_conduite(score=0.1, seuil=0.5,
                             travaux=[_travail(dernier_pas_le=None)],
                             maintenant=T0),
            choisir_conduite(score=0.1, seuil=0.5,
                             graines=[Graine("pensee", 1, "x", 0.9)],
                             maintenant=T0),
            choisir_conduite(score=0.1, seuil=0.5),
        ]
        assert {d.conduite for d in cas} == set(Conduite)
        assert all(isinstance(d, Decision) and d.motif.strip() for d in cas)


# ---------------------------------------------------------------------------
# 5. La diffusion — fermée par défaut
# ---------------------------------------------------------------------------

class TestDiffusion:

    def test_un_pas_de_travail_est_muet_par_defaut(self):
        """4 travaux × 5 pas = 20 monologues par jour, et ces vingt-là
        passeraient hors du frein quotidien des initiatives, qui ne compte
        que les actes."""
        d = decider_diffusion(Conduite.POURSUIVRE, maintenant=T0)
        assert isinstance(d, Diffusion) and d.diffuser is False and d.motif

    def test_une_ouverture_est_muette_par_defaut(self):
        assert decider_diffusion(Conduite.OUVRIR, maintenant=T0).diffuser is False

    def test_parler_diffuse_par_definition(self):
        assert decider_diffusion(Conduite.PARLER, maintenant=T0).diffuser is True

    def test_se_taire_ne_diffuse_jamais(self):
        d = decider_diffusion(
            Conduite.SE_TAIRE, adresse_a_quelqu_un=True,
            resultat_notable=1.0, maintenant=T0,
        )
        assert d.diffuser is False

    def test_un_pas_destine_a_quelqu_un_se_dit(self):
        """Ce n'est pas un monologue, c'est une livraison."""
        d = decider_diffusion(
            Conduite.POURSUIVRE, adresse_a_quelqu_un=True, maintenant=T0,
        )
        assert d.diffuser is True

    def test_un_resultat_juste_interessant_ne_se_dit_pas(self):
        """Le juge de la notabilité est le modèle qui vient de produire le
        résultat, et un juge qui note son propre travail note haut."""
        d = decider_diffusion(
            Conduite.POURSUIVRE, resultat_notable=0.75, maintenant=T0,
        )
        assert d.diffuser is False

    def test_un_resultat_vraiment_notable_se_dit(self):
        d = decider_diffusion(
            Conduite.POURSUIVRE, resultat_notable=0.9, maintenant=T0,
        )
        assert d.diffuser is True

    def test_une_diffusion_trop_recente_referme_la_porte(self):
        """Même ouverte par une raison valable, la parole spontanée reste
        espacée : c'est ce qui borne le total quotidien."""
        d = decider_diffusion(
            Conduite.POURSUIVRE, adresse_a_quelqu_un=True,
            derniere_diffusion_le=T0 - timedelta(minutes=10), maintenant=T0,
        )
        assert d.diffuser is False

    def test_l_espacement_finit_par_rouvrir(self):
        d = decider_diffusion(
            Conduite.POURSUIVRE, adresse_a_quelqu_un=True,
            derniere_diffusion_le=T0 - timedelta(hours=5), maintenant=T0,
        )
        assert d.diffuser is True

    def test_une_journee_de_travail_ne_produit_pas_vingt_monologues(self):
        """La propriété que l'ensemble des règles doit garantir, mesurée
        plutôt que déduite : vingt pas silencieux sur une journée."""
        diffusions = [
            decider_diffusion(Conduite.POURSUIVRE, maintenant=T0 + timedelta(minutes=15 * i))
            for i in range(20)
        ]
        assert sum(1 for d in diffusions if d.diffuser) == 0


# ---------------------------------------------------------------------------
# 6. Pureté et repli
# ---------------------------------------------------------------------------

class TestPurete:

    def test_le_reglage_par_defaut_reproduit_les_constantes(self):
        """Le module ne lit aucune configuration : ses défauts *sont* les
        constantes, et la résolution depuis le registre se fera au bord."""
        from conscience import conduite as mod

        t = ConduiteTuning()
        assert t.graine_obs_pertinence == mod.GRAINE_OBS_PERTINENCE
        assert t.envie_demi_vie_s == mod.ENVIE_DEMI_VIE_S
        assert t.travaux_actifs_max == mod.TRAVAUX_ACTIFS_MAX
        assert t.pas_intervalle_min_s == mod.PAS_INTERVALLE_MIN_S
        assert t.diffusion_notable_min == mod.DIFFUSION_NOTABLE_MIN

    def test_le_module_ne_lit_ni_base_ni_registre(self):
        """Garde AST : une lecture de configuration ici ferait mesurer aux
        tests la base de la machine au lieu de la calibration déclarée, et
        ferait payer une requête à chacun des 2 880 tours quotidiens."""
        import ast
        import pathlib

        source = (
            pathlib.Path(__file__).resolve().parent.parent
            / "conscience" / "conduite.py"
        ).read_text(encoding="utf-8")
        arbre = ast.parse(source)
        interdits = {"cfg_int", "cfg_float", "cfg_bool", "cfg_str", "cfg_list"}
        appels = {
            n.func.id for n in ast.walk(arbre)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        assert not (appels & interdits)
        modules = {
            alias.name.split(".")[0]
            for n in ast.walk(arbre) if isinstance(n, ast.Import)
            for alias in n.names
        } | {
            (n.module or "").split(".")[0]
            for n in ast.walk(arbre) if isinstance(n, ast.ImportFrom)
        }
        assert "django" not in modules and "configs" not in modules

    def test_les_seuils_de_travail_sont_ordonnes(self):
        """Il doit exister une bande où un travail vit encore sans qu'on y
        touche : plancher d'abandon < seuil de poursuite < seuil d'ouverture.
        Les égaliser rendrait l'une des trois portes décorative."""
        t = ConduiteTuning()
        assert (
            t.envie_plancher_abandon
            < t.envie_poursuite_min
            < t.ouverture_envie_min
        )

    def test_la_porte_d_ouverture_domine_strictement_celle_de_recolte(self):
        """Récolter n'engage à rien, ouvrir engage : une amorce doit pouvoir
        exister sans mériter un chantier. À égalité, la seconde porte ne
        déciderait jamais rien — c'est la calibration d'origine, corrigée."""
        t = ConduiteTuning()
        assert t.ouverture_envie_min > t.graine_obs_pertinence

    def test_la_porte_d_ouverture_reste_sous_le_plafond_heuristique(self):
        """Au-dessus de 0.55 elle interdirait au dehors d'amorcer : aucun
        signal du chemin heuristique ne pourrait plus jamais l'atteindre."""
        from conscience.interpreter import PERTINENCE_RSS_MATCHED

        assert ConduiteTuning().ouverture_envie_min <= PERTINENCE_RSS_MATCHED
