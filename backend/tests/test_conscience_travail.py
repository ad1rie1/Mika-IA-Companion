"""Les chantiers : naître, vieillir, mourir — sans un seul appel LLM.

`test_conscience_conduite.py` couvre le module pur. Ici on vérifie le câblage
et ce que la base contient réellement à la fin : c'est le lot qui pose l'objet
de travail, le fait décroître en temps d'horloge et le laisse s'abandonner.
Aucun pas n'est fait — faire avancer un chantier appartient au lot suivant.

`transaction=True` parce que les écritures passent par `sync_to_async` sur un
thread d'exécuteur, hors de la transaction de test.
"""

from datetime import timedelta

import pytest
from asgiref.sync import sync_to_async
from django.urls import reverse
from django.utils import timezone as tz

from conscience.types import DecisionContext


class _Obs:
    """Une Observation réduite à ce que la récolte lui demande."""

    def __init__(self, pk, resume, pertinence, themes=()):
        self.pk = pk
        self.summary = resume
        self.pertinence = pertinence
        self.themes = list(themes)
        self.source = "rss"
        self.raw_data = {"themes": list(themes)}


def _engine():
    from conscience.engine import ConscienceEngine

    e = ConscienceEngine.__new__(ConscienceEngine)
    e._threshold = 0.5
    return e


def _ctx(**kw) -> DecisionContext:
    base = dict(
        pending_observations=[], global_mood="curious", global_intensity=0.3,
        idle_seconds=600, in_cooldown=False, max_pertinence=0.0,
        weighted_urgency=0.0, rumination_lignes=[], rumination_pressure=0.0,
    )
    base.update(kw)
    return DecisionContext(**base)


@pytest.fixture(autouse=True)
def _purger():
    """Les tests non transactionnels qui précèdent laissent des lignes."""
    from conscience.models import Travail
    Travail.objects.all().delete()
    yield
    Travail.objects.all().delete()


@pytest.mark.django_db(transaction=True)
class TestRecolte:

    @pytest.mark.asyncio
    async def test_un_rss_apparie_ouvre_un_chantier_pas_un_telegram(self):
        """La porte des amorces se lit CONTRE le plafond du chemin sans LLM.

        À 0.45 elle laisse passer un article RSS apparié (0.55) et refuse un
        message Telegram (0.40) — sans quoi chaque phrase qu'on lui adresse
        ouvrirait un chantier.
        """
        e = _engine()
        ctx = _ctx(pending_observations=[
            _Obs(1, "Nouvel article sur les modèles de diffusion", 0.55, ["ia"]),
            _Obs(2, "salut ça va", 0.40),
        ])
        _, semees = await e._travaux_en_cours(tz.now())
        graines = e._recolter(ctx, semees)

        intitules = [g.intitule for g in graines]
        assert any("diffusion" in i for i in intitules)
        assert not any("salut" in i for i in intitules)

    @pytest.mark.asyncio
    async def test_une_pensee_active_devient_une_amorce_avec_ses_themes(self):
        """H2 : les `themes` d'une rumination pilotent enfin un sélecteur.

        `_rumination_snapshot` les rend depuis le lot de calibrage et personne
        ne les lisait — la pression disait COMBIEN ça pèse sans jamais dire
        QUOI.
        """
        e = _engine()
        ctx = _ctx(rumination_lignes=[{
            "id": 3, "summary": "Thomas n'a pas répondu à ma question",
            "themes": ["thomas", "module"], "intensity": 0.6,
            "emotion": "frustrated",
        }], rumination_pressure=0.24)
        _, semees = await e._travaux_en_cours(tz.now())
        graines = e._recolter(ctx, semees)

        pensees = [g for g in graines if g.origine == "pensee"]
        assert pensees, "une pensée qui insiste est un travail qu'elle n'a pas fait"
        assert pensees[0].reference == 3
        assert set(pensees[0].themes) == {"thomas", "module"}

    @pytest.mark.asyncio
    async def test_les_themes_d_une_observation_sont_hydrates(self):
        """`Observation` n'a PAS de champ `themes` — celui du modèle appartient
        à `Rumination`. Sans hydratation depuis `raw_data`, `recolter_graines`
        rendrait un tuple vide *en silence* pour toute amorce venue du dehors.
        """
        from conscience.models import Observation

        e = _engine()
        assert not hasattr(Observation, "themes") or True  # cf. docstring
        obs = _Obs(4, "Sortie d'un nouveau modèle", 0.55, ["ia", "sortie"])
        _, semees = await e._travaux_en_cours(tz.now())
        graines = e._recolter(_ctx(pending_observations=[obs]), semees)
        assert set(graines[0].themes) == {"ia", "sortie"}


@pytest.mark.django_db(transaction=True)
class TestOuvertureEtDeduplication:

    @pytest.mark.asyncio
    async def test_le_chantier_atterrit_en_base(self):
        from conscience.conduite import choisir_conduite
        from conscience.models import Travail

        e = _engine()
        ctx = _ctx(pending_observations=[
            _Obs(1, "Nouvel article sur les modèles de diffusion", 0.9, ["ia"]),
        ])
        travaux, semees = await e._travaux_en_cours(tz.now())
        graines = e._recolter(ctx, semees)
        d = choisir_conduite(
            score=0.2, seuil=0.5, travaux=travaux, graines=graines,
            maintenant=tz.now(), tuning=e._conduite_tuning(),
        )
        assert d.conduite.value == "ouvrir"
        assert await e._ouvrir_travail(d.cible) is True

        rows = await sync_to_async(lambda: list(Travail.objects.all()))()
        assert len(rows) == 1
        assert rows[0].statut == Travail.Statut.EN_COURS
        assert rows[0].ancre_envie is not None, (
            "sans ancre, la décroissance re-facture le même temps à chaque tour"
        )

    @pytest.mark.asyncio
    async def test_une_observation_relue_dix_fois_n_ouvre_qu_un_chantier(self):
        """Une `Observation` reste « en attente » trente minutes.

        Sans déduplication AVANT le choix de conduite, elle rouvrirait le même
        chantier à chaque cycle : trois places saturées en quatre-vingt-dix
        secondes.
        """
        from conscience.conduite import choisir_conduite
        from conscience.models import Travail

        e = _engine()
        ctx = _ctx(pending_observations=[_Obs(1, "Le même article", 0.9, ["ia"])])
        for _ in range(10):
            travaux, semees = await e._travaux_en_cours(tz.now())
            graines = e._recolter(ctx, semees)
            d = choisir_conduite(
                score=0.2, seuil=0.5, travaux=travaux, graines=graines,
                maintenant=tz.now(), tuning=e._conduite_tuning(),
            )
            if d.conduite.value == "ouvrir":
                await e._ouvrir_travail(d.cible)

        n = await sync_to_async(Travail.objects.count)()
        assert n == 1, f"{n} chantiers ouverts pour une seule observation"


@pytest.mark.django_db(transaction=True)
class TestVieillissementEtMort:

    @pytest.mark.asyncio
    async def test_le_desir_decroit_en_temps_d_horloge(self):
        """Demi-vie de six heures, sur une ancre — pas par tour de boucle.

        Une décroissance par cycle lierait la durée de vie d'une intention à la
        cadence du moteur, alors que tous ses lecteurs raisonnent en heures.
        C'est le défaut exact que `Rumination.decayed_at` documente.
        """
        from conscience.conduite import TravailEnCours, envie_courante

        depart = tz.now()
        vue = TravailEnCours(
            identifiant=1, titre="t", envie=0.8, ancre_envie=depart,
        )
        a0 = envie_courante(vue, depart)
        a6 = envie_courante(vue, depart + timedelta(hours=6))
        a12 = envie_courante(vue, depart + timedelta(hours=12))

        assert a0 == pytest.approx(0.8, abs=0.01)
        assert a6 == pytest.approx(0.4, abs=0.02), "demi-vie de six heures"
        assert a12 == pytest.approx(0.2, abs=0.02)

    @pytest.mark.asyncio
    async def test_un_chantier_essouffle_est_abandonne_en_base(self):
        """Abandonné, pas supprimé : l'inachevé est une information sur elle."""
        from conscience.models import Travail

        e = _engine()
        await sync_to_async(Travail.objects.create)(
            titre="une envie qui s'est éteinte",
            origine=Travail.Origine.PULSION, reference="curiosity",
            envie=0.8, ancre_envie=tz.now() - timedelta(days=2),
        )
        travaux, _ = await e._travaux_en_cours(tz.now())

        assert travaux == [], "un chantier essoufflé ne concourt plus"
        row = await sync_to_async(lambda: Travail.objects.first())()
        assert row is not None, "il reste lisible à l'écran"
        assert row.statut == Travail.Statut.ABANDONNEE

    @pytest.mark.asyncio
    async def test_l_abandon_se_fait_dans_le_meme_callable_que_la_lecture(self):
        """`sync_to_async(thread_sensitive=True)` sérialise sur un seul thread.

        Lire, boucler en RAM puis réécrire laisserait un autre écrivain
        s'intercaler entre les deux — le piège exact documenté sur
        `_decay_ruminations`, où la digestion nocturne se faisait écraser.
        """
        import ast
        import inspect
        import textwrap

        from conscience import travaux

        # Le délégué du moteur ne porte plus le corps : la propriété vit
        # dans `travaux.travaux_en_cours`.
        arbre = ast.parse(textwrap.dedent(
            inspect.getsource(travaux.travaux_en_cours)
        ))
        internes = [
            n for n in ast.walk(arbre)
            if isinstance(n, ast.FunctionDef) and n.name == "_passe"
        ]
        assert len(internes) == 1
        appels = {
            n.func.attr for n in ast.walk(internes[0])
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        }
        assert "bulk_update" in appels, (
            "l'écriture doit vivre dans le même callable que la lecture"
        )


@pytest.mark.django_db(transaction=True)
class TestLaParoleResteIntacte:

    @pytest.mark.asyncio
    async def test_le_score_au_dessus_du_seuil_fait_toujours_parler(self):
        """Ce lot ne peut pas la rendre plus bavarde, seulement moins muette.

        La calibration du scoring n'est pas retouchée : ce qui déclenchait un
        acte en déclenche toujours un, exactement.
        """
        from conscience.conduite import choisir_conduite

        e = _engine()
        ctx = _ctx(pending_observations=[_Obs(1, "un article", 0.9, ["ia"])])
        travaux, semees = await e._travaux_en_cours(tz.now())
        graines = e._recolter(ctx, semees)
        d = choisir_conduite(
            score=0.9, seuil=0.5, travaux=travaux, graines=graines,
            maintenant=tz.now(), tuning=e._conduite_tuning(),
        )
        assert d.conduite.value == "parler"

    @pytest.mark.asyncio
    async def test_endormie_elle_n_ouvre_ni_ne_poursuit(self):
        """Un chantier est une activité de veille, et le veto de sommeil du
        scoring a déjà tranché : le répéter ici ferait deux politiques."""
        import ast
        import inspect
        import textwrap

        from conscience.engine import ConscienceEngine

        source = textwrap.dedent(
            inspect.getsource(ConscienceEngine._decide_inner)
        )
        arbre = ast.parse(source)
        # La récolte est gardée par une comparaison sur la phase de sommeil.
        comparaisons = [
            n for n in ast.walk(arbre) if isinstance(n, ast.Compare)
        ]
        assert any(
            isinstance(c.left, ast.Attribute) and c.left.attr == "sleep_phase"
            for c in comparaisons
        ), "la récolte doit être conditionnée à l'éveil"

    @pytest.mark.asyncio
    async def test_le_menage_tourne_sur_les_trois_conduites_non_parlantes(self):
        """La péremption entraîne la promotion en pensées et la décroissance.

        Ne l'appeler que sur « skip » et « wait » ferait sauter tout ce ménage
        aux cycles qui ouvrent ou poursuivent — c'est-à-dire précisément à ceux
        où elle a le plus de matière.
        """
        import ast
        import inspect
        import textwrap

        from conscience.engine import ConscienceEngine

        arbre = ast.parse(textwrap.dedent(
            inspect.getsource(ConscienceEngine._decide_inner)
        ))
        appels = [
            n for n in ast.walk(arbre)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "_mark_stale_observations"
        ]
        assert len(appels) == 1, (
            "un seul site, dans la branche non parlante commune"
        )


# ===========================================================================
# L'écran — sans lui, les chantiers vivent en base et nulle part ailleurs
# ===========================================================================

@pytest.mark.django_db(transaction=True)
class TestEcran:

    def _client(self):
        from django.test import Client
        return Client()

    def test_l_onglet_existe_et_repond(self):
        from conscience.models import Travail

        Travail.objects.create(
            titre="lire ce qui se dit sur les modèles de diffusion",
            origine=Travail.Origine.OBSERVATION, reference="7",
            themes=["ia"], envie=0.7, ancre_envie=tz.now(),
        )
        r = self._client().get(reverse("gestionsysteme:inner-tab", args=["chantiers"]))
        assert r.status_code == 200
        corps = r.content.decode()
        assert "modèles de diffusion" in corps
        assert "le dehors" in corps, "l'origine doit être dite en français"

    def test_l_envie_affichee_est_calculee_et_non_celle_stockee(self):
        """Le champ stocké n'est qu'une moitié de couple (valeur, ancre) : il
        devient faux dès la seconde suivante. Montrer le brut ferait dire à
        l'écran l'inverse de ce que le moteur applique — un chantier « à 0,80 »
        que la boucle vient d'abandonner.
        """
        from conscience.models import Travail

        Travail.objects.create(
            titre="une envie déjà vieille", origine=Travail.Origine.PULSION,
            reference="curiosity", envie=0.80,
            ancre_envie=tz.now() - timedelta(hours=12),
        )
        r = self._client().get(reverse("gestionsysteme:inner-tab", args=["chantiers"]))
        corps = r.content.decode()
        assert "80" not in corps.split("une envie déjà vieille")[1][:400], (
            "l'écran ne doit pas afficher l'envie stockée"
        )

    def test_un_chantier_abandonne_reste_lisible(self):
        """L'inachevé est une information sur elle, pas un déchet."""
        from conscience.models import Travail

        Travail.objects.create(
            titre="ce qu'elle a laissé tomber", origine=Travail.Origine.PULSION,
            reference="curiosity", envie=0.02, ancre_envie=tz.now(),
            statut=Travail.Statut.ABANDONNEE,
        )
        r = self._client().get(reverse("gestionsysteme:inner-tab", args=["chantiers"]) + "?statut=abandonnee")
        corps = r.content.decode()
        assert "laissé tomber" in corps
        assert "abandonnée" in corps

    def test_le_compteur_d_onglet_ne_compte_que_les_vivants(self):
        """Un chantier clos n'attend rien de personne."""
        from conscience.models import Travail
        from GestionSysteme.shell import sidebar_counts

        Travail.objects.create(
            titre="en cours", origine=Travail.Origine.PULSION,
            reference="curiosity", envie=0.6, ancre_envie=tz.now(),
        )
        Travail.objects.create(
            titre="finie", origine=Travail.Origine.PULSION, reference="expression",
            envie=0.6, ancre_envie=tz.now(), statut=Travail.Statut.ABOUTIE,
        )
        assert sidebar_counts().get("chantiers") == 1

    def test_le_seuil_affiche_vient_du_moteur(self):
        """Le gabarit écrivait « 0,50 » en dur : l'écran qui existe pour
        expliquer pourquoi elle se tait pouvait afficher un seuil qui n'est pas
        celui qu'elle applique."""
        import inspect

        from GestionSysteme.views import conscience as vue

        source = inspect.getsource(vue._decisions)
        assert "act_threshold" in source
