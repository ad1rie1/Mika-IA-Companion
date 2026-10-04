"""Le murmure de la conscience — ``conscience.murmure``.

Le défaut réparé : ``generate_inner_thought`` n'avait qu'un appelant, derrière
un test sur ``emotion_policy == "off"`` qui est le défaut d'un projet. Le
murmure ne sortait jamais. Ce module est le second appelant, et l'essentiel de
ce qu'il ajoute est un jeu de gardes — donc l'essentiel de ce fichier épingle
*quand elle se tait*, et surtout **où** ce silence est décidé : avant l'appel
au modèle, jamais après.

Aucune base de données, aucun appel LLM : la décision est pure, la génération
et la diffusion sont deux seams bouchonnés.
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from old.backend.conscience import murmure as M


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _etat_neuf():
    """Le compteur est en RAM et global au process : sans remise à zéro, un
    test hériterait du quota consommé par le précédent."""
    M.reinitialiser_etat()
    yield
    M.reinitialiser_etat()


@pytest.fixture
def contexte_favorable(monkeypatch):
    """Éveillée, un client connecté : tout ce qui n'est pas la garde qu'on
    mesure est ouvert, sinon le test passerait pour la mauvaise raison."""
    monkeypatch.setattr(M, "_phase_sommeil", lambda: "awake")
    monkeypatch.setattr(M, "_audience_presente", lambda: True)


class _Modele:
    """Bouchon de l'appel LLM : compte les appels et rend ce qu'on lui dit."""

    def __init__(self, retour: str | None = "mmm, tiens..."):
        self.retour = retour
        self.appels = 0
        self.dernier_args: tuple = ()

    async def __call__(self, intention, resultat, *, mood="neutral"):
        self.appels += 1
        self.dernier_args = (intention, resultat, mood)
        if isinstance(self.retour, Exception):
            raise self.retour
        return self.retour


@pytest.fixture
def modele(monkeypatch):
    bouchon = _Modele()
    monkeypatch.setattr(M, "_generer_pensee", bouchon)
    return bouchon


@pytest.fixture
def diffusion(monkeypatch):
    envoi = AsyncMock()
    monkeypatch.setattr(M, "_diffuser", envoi)
    return envoi


# ── La décision, pure ────────────────────────────────────────────


class TestChaqueGardeSeparement:
    """Une garde à la fois : chaque test n'en ferme qu'une, toutes les autres
    restent ouvertes. Un test qui en fermait deux ne prouverait pas laquelle
    a parlé."""

    def test_contexte_ouvert_murmure(self):
        assert M.decider_murmure(intention="écrire à Alice").murmure is True

    def test_intention_vide_ne_murmure_pas(self):
        assert M.decider_murmure(intention="   ").raison == "no_intention"

    def test_mode_professionnel_ferme(self):
        d = M.decider_murmure(intention="avancer", mode_professionnel=True)
        assert (d.murmure, d.raison) == (False, "professional_mode")

    def test_sommeil_ferme_et_nomme_la_phase(self):
        d = M.decider_murmure(intention="avancer", phase_sommeil="rem")
        assert (d.murmure, d.raison) == (False, "asleep(rem)")

    def test_sommeil_ouvrable_par_reglage(self):
        """La politique vocale, elle, laisse passer une pensée INNER endormie.
        Le silence nocturne est donc un choix de ce module, et il se règle."""
        d = M.decider_murmure(
            intention="avancer", phase_sommeil="rem",
            tuning=M.MurmureTuning(murmurer_endormie=True),
        )
        assert d.murmure is True

    def test_sans_audience_ferme(self):
        d = M.decider_murmure(intention="avancer", audience=False)
        assert (d.murmure, d.raison) == (False, "no_audience")

    def test_delai_non_ecoule_ferme(self):
        t = M.MurmureTuning()
        d = M.decider_murmure(
            intention="avancer",
            secondes_depuis_tentative=t.delai_min_secondes - 1,
        )
        assert (d.murmure, d.raison) == (False, "too_soon")

    def test_delai_ecoule_ouvre(self):
        t = M.MurmureTuning()
        d = M.decider_murmure(
            intention="avancer",
            secondes_depuis_tentative=t.delai_min_secondes,
        )
        assert d.murmure is True

    def test_jamais_tente_vaut_il_y_a_une_eternite(self):
        """``None`` veut dire « ça n'a jamais eu lieu », pas « à l'instant » :
        le tout premier murmure du process ne doit pas attendre le délai."""
        assert M.decider_murmure(
            intention="avancer", secondes_depuis_tentative=None,
        ).murmure is True

    def test_quota_epuise_ferme(self):
        t = M.MurmureTuning()
        d = M.decider_murmure(
            intention="avancer", emis_ce_jour=t.quota_quotidien,
        )
        assert (d.murmure, d.raison) == (False, "daily_quota_exhausted")

    def test_sous_le_quota_ouvre(self):
        t = M.MurmureTuning()
        d = M.decider_murmure(
            intention="avancer", emis_ce_jour=t.quota_quotidien - 1,
        )
        assert d.murmure is True


class TestGardeAntiRepetition:
    """La garde de conception. La conscience re-score le *même* contexte
    accumulé tous les 30 s : tant que rien ne consomme les observations en
    attente, l'intention qu'elles produisent est identique d'un cycle au
    suivant. Sans cette garde, le quota se dépense en huit exemplaires de la
    même pensée."""

    def test_meme_intention_dans_la_fenetre_ferme(self):
        d = M.decider_murmure(
            intention="écrire à Alice",
            intention_precedente="écrire à Alice",
            secondes_depuis_intention=10.0,
        )
        assert (d.murmure, d.raison) == (False, "same_intention")

    def test_la_casse_et_les_espaces_ne_font_pas_une_autre_intention(self):
        d = M.decider_murmure(
            intention="  Écrire   à Alice ",
            intention_precedente="écrire à alice",
            secondes_depuis_intention=10.0,
        )
        assert d.murmure is False

    def test_intention_differente_passe(self):
        d = M.decider_murmure(
            intention="relire le brouillon",
            intention_precedente="écrire à Alice",
            secondes_depuis_intention=10.0,
        )
        assert d.murmure is True

    def test_la_fenetre_expire(self):
        t = M.MurmureTuning()
        d = M.decider_murmure(
            intention="écrire à Alice",
            intention_precedente="écrire à Alice",
            secondes_depuis_intention=t.fenetre_repetition_secondes + 1,
        )
        assert d.murmure is True


# ── Le coût : rien n'est dépensé sous une garde ──────────────────


class TestAucuneGardeNePaieLAppel:
    """La propriété qui justifie l'existence du module : la conscience tourne
    2 880 fois par jour et un murmure coûte un appel de modèle. Une garde
    évaluée *après* l'appel ne protège rien — elle jette un jeton déjà payé.
    Chaque garde est donc mesurée par « le bouchon n'a pas été appelé »."""

    @pytest.mark.parametrize(
        "ferme",
        [
            {"intention": ""},
            {"mode_professionnel": True},
            {"phase": "deep_sleep"},
            {"audience": False},
        ],
        ids=["intention_vide", "professionnel", "sommeil", "sans_audience"],
    )
    async def test_gardes_de_contexte_avant_lappel(
        self, monkeypatch, modele, diffusion, ferme,
    ):
        monkeypatch.setattr(M, "_phase_sommeil", lambda: ferme.get("phase", "awake"))
        monkeypatch.setattr(
            M, "_audience_presente", lambda: ferme.get("audience", True),
        )
        sortie = await M.murmurer(
            ferme.get("intention", "écrire à Alice"),
            mode_professionnel=ferme.get("mode_professionnel", False),
        )
        assert sortie is None
        assert modele.appels == 0
        diffusion.assert_not_awaited()

    async def test_delai_avant_lappel(self, contexte_favorable, modele, diffusion):
        t = M.MurmureTuning()
        assert await M.murmurer("écrire à Alice", maintenant=1000.0) is not None
        assert modele.appels == 1

        rejete = await M.murmurer(
            "relire le brouillon",
            maintenant=1000.0 + t.delai_min_secondes - 1,
        )
        assert rejete is None
        assert modele.appels == 1, "le délai s'évalue avant l'appel, pas après"

    async def test_quota_avant_lappel(self, contexte_favorable, modele, diffusion):
        t = M.MurmureTuning()
        # On amène le compteur au plafond sans passer par le modèle.
        M._ETAT.jour = M._jour_courant()
        M._ETAT.emis_ce_jour = t.quota_quotidien

        assert await M.murmurer("écrire à Alice") is None
        assert modele.appels == 0

    async def test_repetition_avant_lappel(
        self, contexte_favorable, modele, diffusion,
    ):
        t = M.MurmureTuning()
        assert await M.murmurer("écrire à Alice", maintenant=0.0) is not None
        assert modele.appels == 1

        # Délai écoulé, quota disponible : seule la répétition ferme.
        rejete = await M.murmurer(
            "écrire à Alice", maintenant=t.delai_min_secondes,
        )
        assert rejete is None
        assert modele.appels == 1


# ── Quota et délai ne comptent pas la même chose ─────────────────


class TestQuotaEtDelai:

    async def test_un_none_du_modele_ne_consomme_pas_le_quota(
        self, contexte_favorable, modele, diffusion,
    ):
        """Le quota compte des murmures *entendus*. Un appel qui n'aboutit
        pas a coûté un appel et n'a rien produit : le décompter reviendrait à
        payer deux fois le même silence."""
        modele.retour = None
        assert await M.murmurer("écrire à Alice", maintenant=0.0) is None
        assert modele.appels == 1
        assert M.etat_murmure()["emis_ce_jour"] == 0
        diffusion.assert_not_awaited()

    async def test_un_none_du_modele_consomme_le_delai(
        self, contexte_favorable, modele, diffusion,
    ):
        """…mais il consomme le délai, sinon un modèle en échec serait
        rappelé à chacun des tours de conscience."""
        modele.retour = None
        await M.murmurer("écrire à Alice", maintenant=0.0)
        await M.murmurer("relire le brouillon", maintenant=30.0)
        assert modele.appels == 1

    async def test_un_murmure_emis_consomme_le_quota(
        self, contexte_favorable, modele, diffusion,
    ):
        await M.murmurer("écrire à Alice", maintenant=0.0)
        assert M.etat_murmure()["emis_ce_jour"] == 1

    async def test_le_quota_se_rouvre_au_jour_suivant(
        self, monkeypatch, contexte_favorable, modele, diffusion,
    ):
        t = M.MurmureTuning()
        monkeypatch.setattr(M, "_jour_courant", lambda: date(2026, 8, 10))
        M._rouler_le_jour()
        M._ETAT.emis_ce_jour = t.quota_quotidien
        assert await M.murmurer("écrire à Alice", maintenant=0.0) is None

        monkeypatch.setattr(M, "_jour_courant", lambda: date(2026, 8, 11))
        assert await M.murmurer("écrire à Alice", maintenant=0.0) is not None
        assert M.etat_murmure()["emis_ce_jour"] == 1

    async def test_la_raison_du_silence_est_lisible(
        self, monkeypatch, modele, diffusion,
    ):
        """« Elle n'a pas murmuré » et « elle n'a pas pu » sont deux faits
        différents, et seul le second se répare."""
        monkeypatch.setattr(M, "_phase_sommeil", lambda: "awake")
        monkeypatch.setattr(M, "_audience_presente", lambda: False)
        await M.murmurer("écrire à Alice")
        assert M.etat_murmure()["derniere_raison"] == "no_audience"


# ── Le piège : jamais de person_id ───────────────────────────────


class TestJamaisDePersonId:
    """Un ``person_id`` fait résoudre une cible de présence, ce qui bascule
    ``persona_for_source(..., addressed=True)`` en SPEAKING — et SPEAKING sur
    un canal porteur d'un ``VOICE_SINK`` (Telegram) veut dire *note vocale
    envoyée sur le téléphone de quelqu'un*. Une pensée n'est adressée à
    personne."""

    async def test_la_diffusion_reelle_ne_porte_aucun_person_id(
        self, contexte_favorable, modele,
    ):
        with patch(
            "pipeline.broadcast.broadcast_to_websocket", new_callable=AsyncMock,
        ) as envoi:
            assert await M.murmurer("écrire à Alice", maintenant=0.0) is not None

        envoi.assert_awaited_once()
        args, kwargs = envoi.await_args
        assert "person_id" not in kwargs
        assert len(args) == 1, "seule la sortie est passée en positionnel"
        assert kwargs["source"] == M.SOURCE_MURMURE
        assert args[0].text == "mmm, tiens..."

    def test_la_source_est_celle_qui_donne_la_persona_inner(self):
        """La valeur de ``SOURCE_MURMURE`` n'est pas décorative : c'est son
        appartenance à ``INNER_SOURCES`` qui produit le profil murmuré."""
        from old.backend.pipeline import voice

        assert M.SOURCE_MURMURE in voice.INNER_SOURCES
        assert (
            voice.persona_for_source(M.SOURCE_MURMURE)
            == voice.VoicePersona.INNER
        )

    def test_addressed_bascule_en_speaking(self):
        """Le piège lui-même, épinglé côté politique vocale : c'est bien le
        fait d'avoir une cible qui transformerait le murmure en parole."""
        from old.backend.pipeline import voice

        assert (
            voice.persona_for_source(M.SOURCE_MURMURE, addressed=True)
            == voice.VoicePersona.SPEAKING
        )


# ── Rien ne s'échappe ────────────────────────────────────────────


class TestSilenceEstUneSortieValide:
    """Appelée depuis des boucles que personne ne supervise : une exception
    qui s'échappe tue la boucle pour la vie du process."""

    async def test_un_modele_qui_leve_ne_propage_pas(
        self, contexte_favorable, modele, diffusion,
    ):
        modele.retour = RuntimeError("provider down")
        assert await M.murmurer("écrire à Alice", maintenant=0.0) is None
        diffusion.assert_not_awaited()

    async def test_une_diffusion_qui_leve_ne_propage_pas(
        self, contexte_favorable, modele, monkeypatch,
    ):
        async def _casse(_pensee):
            raise RuntimeError("channel layer down")

        monkeypatch.setattr(M, "_diffuser", _casse)
        assert await M.murmurer("écrire à Alice", maintenant=0.0) is None

    async def test_une_erreur_nest_jamais_diffusee_comme_pensee(
        self, contexte_favorable, modele, diffusion,
    ):
        modele.retour = RuntimeError("quota exceeded")
        await M.murmurer("écrire à Alice", maintenant=0.0)
        diffusion.assert_not_awaited()

    async def test_lecture_de_presence_cassee_ferme(self, monkeypatch, modele):
        """Repli fermé : ne pas savoir s'il y a un public n'est pas une raison
        de payer un appel pour un groupe vide."""
        monkeypatch.setattr(M, "_phase_sommeil", lambda: "awake")

        class _Registre:
            def reachable(self):
                raise RuntimeError("presence broken")

        with patch("communication.presence.presence_registry", _Registre()):
            assert M._audience_presente() is False

    async def test_lecture_de_sommeil_cassee_ouvre(self, monkeypatch):
        """Repli ouvert, à l'inverse : un sous-système absent ne doit pas
        rendre Mika muette pour la vie du process — le délai et le quota
        bornent la dépense sans dépendre de personne."""
        import old.backend.memory.sleep as sleep_mod

        class _Cycle:
            @property
            def phase(self):
                raise RuntimeError("sleep broken")

        monkeypatch.setattr(sleep_mod, "sleep_cycle", _Cycle())
        assert M._phase_sommeil() == "awake"


# ── Forme du murmure ─────────────────────────────────────────────


class TestFormeDuMurmure:

    async def test_la_longueur_est_bornee_par_le_tuning(
        self, contexte_favorable, modele, diffusion,
    ):
        """``inner_voice`` plafonne déjà, mais depuis *sa* configuration : le
        murmure ne doit pas grandir parce qu'un autre réglage a bougé."""
        modele.retour = "a" * 500
        sortie = await M.murmurer(
            "écrire à Alice", maintenant=0.0,
            tuning=M.MurmureTuning(longueur_max=40),
        )
        assert sortie is not None and len(sortie) == 40

    async def test_intention_et_resultat_atteignent_le_modele(
        self, contexte_favorable, modele, diffusion,
    ):
        await M.murmurer("écrire à Alice", "elle a répondu", mood="curious",
                         maintenant=0.0)
        assert modele.dernier_args == ("écrire à Alice", "elle a répondu",
                                       "curious")

    def test_chaque_defaut_est_une_constante_de_module(self):
        """La résolution au bord s'écrira ``cfg_int("…", MURMURE_QUOTA_…)``.
        La garde AST de ``test_config_rapatriement`` ne sait résoudre un repli
        que s'il est un nom de module : un défaut littéral dans la dataclasse
        serait ignoré en silence, et le défaut déclaré pourrait dériver de la
        valeur sur laquelle le code tourne."""
        assert M.DEFAULT_TUNING.quota_quotidien == M.MURMURE_QUOTA_QUOTIDIEN
        assert M.DEFAULT_TUNING.delai_min_secondes == M.MURMURE_DELAI_MIN_SECONDES
        assert M.DEFAULT_TUNING.longueur_max == M.MURMURE_LONGUEUR_MAX
        assert (
            M.DEFAULT_TUNING.fenetre_repetition_secondes
            == M.MURMURE_FENETRE_REPETITION_SECONDES
        )
        assert M.DEFAULT_TUNING.murmurer_endormie == M.MURMURE_ENDORMIE

    def test_aucune_lecture_de_configuration(self):
        """C2 : le module est calibré par sa dataclasse, pas par la base de la
        machine qui exécute les tests. Un ``cfg_*`` ici ferait aussi échouer la
        garde AST, puisque ce lot ne déclare aucune clé au registre."""
        import ast
        import inspect

        # AST et non recherche de sous-chaîne : le module *nomme* ``cfg_int``
        # dans un commentaire, pour dire comment la résolution au bord
        # s'écrira. Ce qu'on interdit, c'est l'appel.
        arbre = ast.parse(inspect.getsource(M))
        appels = {
            noeud.func.id
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.Call) and isinstance(noeud.func, ast.Name)
        }
        assert not {n for n in appels if n.startswith("cfg_")}

    def test_le_tuning_est_gele(self):
        """Comme ``ScoringTuning`` : une dataclasse gelée, aucune lecture de
        registre, donc les tests mesurent la calibration déclarée."""
        # `FrozenInstanceError` et non `Exception` : voir la même correction
        # côté trousse — un nom de champ erroné lèverait aussi et le gel ne
        # serait jamais éprouvé.
        with pytest.raises(FrozenInstanceError):
            M.DEFAULT_TUNING.quota_quotidien = 99  # type: ignore[misc]
