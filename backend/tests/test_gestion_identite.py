"""Identités dans GestionSystème — « qui parle, et ce que ça débloque ».

Portage de ``test_dashboard_identity.py`` sur l'interface rendue par le
serveur. Les endpoints JSON ont disparu avec l'application ``dashboard`` ;
les propriétés qu'ils vérifiaient, non — c'est la surface la plus sensible du
système, et elle est réimplémentée dans ``GestionSysteme/views/social.py``.

Trois propriétés font la valeur de la page, et ce sont elles qui sont épinglées :

1. elle rapporte la certitude **effective** utilisée par le prompt (relevée au
   plancher, bornée par le plafond), pas la colonne brute — les deux diffèrent
   exactement là où ça compte, sur un canal qui accorde un plancher ;
2. ``may_disclose`` suit ``trust.may_disclose_private_context``, puisque ce
   drapeau est toute la raison d'être de l'écran ;
3. chaque écriture passe par ``identity_resolver``, donc accepter une
   revendication depuis l'interface produit la même liaison, le même poids et
   le même plafond qu'un appel d'outil.

Différence de forme assumée : un refus n'est plus un code 4xx mais un message
d'erreur et une base inchangée. Depuis un navigateur, c'est ce que l'opérateur
doit voir — et « inchangée » reste vérifié, ce qui est le fond du test.
"""
from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from identity.models import Identity, IdentityClaim, IdentityHandle
from identity.trust import Certainty, ChannelTrust
from memory.models import Entity

pytestmark = pytest.mark.django_db


@pytest.fixture
def client() -> Client:
    return Client()


def _identity(*, name="", entity=None, certainty=0.0):
    return Identity.objects.create(
        display_name=name, entity=entity, certainty=certainty,
    )


def _handle(identity, *, person_id, channel="telegram", trust="account",
            ephemeral=False):
    return IdentityHandle.objects.create(
        identity=identity, person_id=person_id, channel=channel,
        trust=trust, is_ephemeral=ephemeral,
    )


def _claim(identity, handle, *, name="Thomas", kind="self_declared",
           status=IdentityClaim.Status.PENDING, channel="telegram",
           trust="account"):
    return IdentityClaim.objects.create(
        identity=identity, handle=handle, claimed_name=name, kind=kind,
        status=status, channel=channel, trust=trust,
        evidence="moi c'est Thomas",
    )


URL_LISTE = reverse("gestionsysteme:social-tab", args=["identites"])
URL_DEMANDES = reverse("gestionsysteme:social-tab", args=["demandes"])
URL_POLITIQUE = reverse("gestionsysteme:social-tab", args=["politique"])


def _lignes(client, url=URL_LISTE, **params):
    """Les lignes que la vue a réellement construites.

    On lit le contexte plutôt que le HTML : ce qui est testé ici est la
    décision de confiance, pas la mise en forme.
    """
    res = client.get(url, params)
    assert res.status_code == 200
    return res.context["page"].rows


# ── Liste ───────────────────────────────────────────────────────

class TestListe:

    def test_liste_handles_et_entite(self, client):
        entity = Entity.objects.create(name="Thomas", entity_type="person")
        identity = _identity(name="Thomas", entity=entity, certainty=0.85)
        _handle(identity, person_id="tg_1")

        lignes = _lignes(client)
        assert len(lignes) == 1
        ligne = lignes[0]
        assert ligne["obj"].entity.name == "Thomas"
        assert ligne["handle"].person_id == "tg_1"
        assert ligne["decision"].level.name.lower() == "bound"

    def test_certitude_effective_et_non_la_colonne_stockee(self, client):
        """Un handle authentifié vaut VERIFIED même à certitude 0.

        ``resolve_context`` relève la valeur stockée au plancher du canal
        avant toute décision. Une page lisant la colonne brute afficherait une
        session fraîchement liée comme « inconnu » — en laissant croire que sa
        mémoire de cette personne est fermée — alors que le prompt la traite
        comme certaine.
        """
        identity = _identity(name="Alice", certainty=0.0)
        _handle(identity, person_id="user_7", channel="web",
                trust=ChannelTrust.AUTHENTICATED.value)

        ligne = _lignes(client)[0]
        assert ligne["stored"] == 0.0
        assert ligne["decision"].certainty == pytest.approx(float(Certainty.VERIFIED))
        assert ligne["decision"].may_disclose is True

    def test_un_handle_public_ne_franchit_jamais_le_seuil(self, client):
        identity = _identity(name="?", certainty=1.0)
        _handle(identity, person_id="tg_group_9", channel="telegram",
                trust=ChannelTrust.PUBLIC.value)

        ligne = _lignes(client)[0]
        assert ligne["decision"].may_disclose is False

    def test_may_disclose_suit_la_politique(self, client):
        """Le drapeau n'est pas recalculé ici — ce test vérifie que ça dure."""
        from identity import trust as trust_policy

        for trust, certitude in [
            (ChannelTrust.ACCOUNT.value, 0.85),
            (ChannelTrust.ACCOUNT.value, 0.45),
            (ChannelTrust.PUBLIC.value, 0.70),
            (ChannelTrust.AUTHENTICATED.value, 0.0),
        ]:
            Identity.objects.all().delete()
            identity = _identity(certainty=certitude)
            _handle(identity, person_id=f"h_{trust}_{certitude}", trust=trust)

            decision = _lignes(client)[0]["decision"]
            assert decision.may_disclose == trust_policy.may_disclose_private_context(
                decision.certainty, ChannelTrust(trust),
            ), (trust, certitude)

    def test_les_identites_ephemeres_sont_masquees_par_defaut(self, client):
        identity = _identity(name="anon")
        _handle(identity, person_id="anon_abc", channel="web", ephemeral=True)

        assert _lignes(client) == []
        assert len(_lignes(client, ephemeres="oui")) == 1

    def test_le_resume_compte_la_meme_portee_que_le_tableau(self, client):
        """Mesuré sur la base de développement : 86 sockets pour 9 réelles.

        Une carte annonçant « 95 identités » au-dessus d'un tableau de 9 se lit
        comme un filtre cassé, pas comme deux questions différentes.
        """
        durable = _identity(name="Thomas")
        _handle(durable, person_id="tg_2")
        socket = _identity(name="anon")
        _handle(socket, person_id="anon_zz", channel="web", ephemeral=True)

        res = client.get(URL_LISTE)
        assert res.context["summary"]["total"] == 1
        assert len(res.context["page"].rows) == 1

    def test_une_identite_sans_handle_reste_listee(self, client):
        """Une ligne orpheline est un fait sur la base, pas du bruit."""
        _identity(name="orpheline")
        assert len(_lignes(client)) == 1

    def test_filtres_liees_et_non_liees(self, client):
        entity = Entity.objects.create(name="Bob", entity_type="person")
        liee = _identity(name="Bob", entity=entity, certainty=0.85)
        _handle(liee, person_id="tg_bound")
        non_liee = _identity(name="?")
        _handle(non_liee, person_id="tg_unbound")

        assert len(_lignes(client, portee="liees")) == 1
        assert len(_lignes(client, portee="non_liees")) == 1

    def test_la_recherche_trouve_par_person_id(self, client):
        """Chercher par handle est le point : c'est ce que montrent les logs."""
        identity = _identity(name="Thomas")
        _handle(identity, person_id="tg_998877")

        assert len(_lignes(client, q="998877")) == 1
        assert _lignes(client, q="zzz") == []


class TestFiche:

    def test_la_fiche_porte_la_phrase_du_prompt_et_le_registre(self, client):
        identity = _identity(name="Thomas", certainty=0.45)
        h = _handle(identity, person_id="tg_5")
        _claim(identity, h)

        res = client.get(
            reverse("gestionsysteme:identity-detail", args=[identity.pk]),
        )
        assert res.status_code == 200
        # La description est ce que ``resolve_context`` remet au constructeur
        # de prompt : c'est elle qui doit être affichée, pas une paraphrase.
        assert "Thomas" in res.context["decision"].description
        assert len(res.context["claims"]) == 1

    def test_une_identite_inconnue_donne_404(self, client):
        assert client.get(
            reverse("gestionsysteme:identity-detail", args=[999999]),
        ).status_code == 404


# ── Revendications ──────────────────────────────────────────────

class TestRevendications:

    def _accepter(self, client, claim, **extra):
        data = {"action": "accepter"}
        data.update(extra)
        return client.post(
            reverse("gestionsysteme:claim-action", args=[claim.pk]),
            data, follow=True,
        )

    def test_accepter_lie_via_le_resolveur(self, client):
        """Même résultat qu'un appel d'outil : entité créée, certitude relevée."""
        identity = _identity(name="?")
        h = _handle(identity, person_id="tg_7")
        claim = _claim(identity, h, name="Thomas")

        res = self._accepter(client, claim, reason="il a redit le concert")
        assert res.status_code == 200

        identity.refresh_from_db()
        claim.refresh_from_db()
        assert identity.entity is not None
        assert identity.entity.name == "Thomas"
        assert claim.status == IdentityClaim.Status.ACCEPTED
        assert identity.certainty == pytest.approx(0.20)

    def test_accepter_avec_corroboration_atteint_le_seuil(self, client):
        """La calibration pour laquelle les poids existent, de bout en bout."""
        identity = _identity(name="?")
        h = _handle(identity, person_id="tg_8")
        claim = _claim(identity, h, name="Alice")

        self._accepter(client, claim, evidence_kind="shared_memory")
        identity.refresh_from_db()
        assert identity.certainty == pytest.approx(float(Certainty.CORROBORATED))

    def test_accepter_reste_borne_par_un_canal_public(self, client):
        identity = _identity(name="?")
        h = _handle(identity, person_id="tg_pub", trust=ChannelTrust.PUBLIC.value)
        claim = _claim(identity, h, name="Alice", trust=ChannelTrust.PUBLIC.value)

        self._accepter(client, claim, evidence_kind="shared_memory")
        identity.refresh_from_db()
        assert identity.certainty <= float(Certainty.CORROBORATED)

    def test_rejeter_enregistre_le_doute_sans_supprimer(self, client):
        identity = _identity(name="?")
        h = _handle(identity, person_id="tg_9")
        claim = _claim(identity, h)

        res = client.post(
            reverse("gestionsysteme:claim-action", args=[claim.pk]),
            {"action": "rejeter", "reason": "il s'est trompé sur la date"},
            follow=True,
        )
        assert res.status_code == 200
        claim.refresh_from_db()
        assert claim.status == IdentityClaim.Status.REJECTED
        assert "date" in claim.resolution_note

    def test_resoudre_deux_fois_est_refuse_visiblement(self, client):
        """Le résolveur répond ``{"ok": false}`` aux appelants LLM.

        L'interface doit le montrer : une écriture refusée qui passerait pour
        un succès est exactement la façon dont un écran affiche un changement
        qui n'a pas eu lieu.
        """
        identity = _identity(name="?")
        h = _handle(identity, person_id="tg_10")
        claim = _claim(identity, h)

        url = reverse("gestionsysteme:claim-action", args=[claim.pk])
        client.post(url, {"action": "rejeter"}, follow=True)
        second = client.post(url, {"action": "rejeter"}, follow=True)

        messages = [m.level_tag for m in second.context["messages"]]
        assert "error" in messages


# ── Liaison / preuve / révocation ───────────────────────────────

class TestLiaisons:

    def _action(self, client, identity, data):
        return client.post(
            reverse("gestionsysteme:identity-action", args=[identity.pk]),
            data, follow=True,
        )

    def test_lier_une_identite_qui_n_a_jamais_revendique(self, client):
        identity = _identity(name="?")
        _handle(identity, person_id="tg_11")

        res = self._action(client, identity, {"action": "lier",
                                              "entity_name": "Camille"})
        assert res.status_code == 200
        identity.refresh_from_db()
        assert identity.entity.name == "Camille"

    def test_lier_exige_un_nom(self, client):
        identity = _identity(name="?")
        _handle(identity, person_id="tg_12")

        res = self._action(client, identity, {"action": "lier",
                                              "entity_name": "   "})
        identity.refresh_from_db()
        assert identity.entity_id is None
        assert "error" in [m.level_tag for m in res.context["messages"]]

    def test_revoquer_delie_et_garde_la_trace(self, client):
        entity = Entity.objects.create(name="Thomas", entity_type="person")
        identity = _identity(name="Thomas", entity=entity, certainty=0.85)
        _handle(identity, person_id="tg_13")

        self._action(client, identity, {"action": "revoquer",
                                        "reason": "ce n'était pas lui"})
        identity.refresh_from_db()
        assert identity.entity_id is None
        assert identity.certainty == 0.0
        # Délibérément pas une suppression : pourquoi elle a cessé de croire
        # est une ligne du registre.
        assert IdentityClaim.objects.filter(
            identity=identity, kind="revoked",
        ).exists()

    def test_un_type_de_preuve_inconnu_est_refuse(self, client):
        """Le résolveur compte un type inconnu comme 0, exprès (arguments LLM).

        Depuis une liste déroulante fermée, ce ne peut être qu'un bug — et une
        écriture qui ne change rien sans le dire est pire qu'une erreur.
        """
        identity = _identity(name="?", certainty=0.45)
        _handle(identity, person_id="tg_14")

        res = self._action(client, identity, {"action": "preuve",
                                              "kind": "vibes",
                                              "detail": "je le sens bien"})
        identity.refresh_from_db()
        assert identity.certainty == pytest.approx(0.45)   # inchangée
        assert "error" in [m.level_tag for m in res.context["messages"]]

    def test_une_contre_preuve_baisse_la_certitude(self, client):
        entity = Entity.objects.create(name="Thomas", entity_type="person")
        identity = _identity(name="Thomas", entity=entity, certainty=0.85)
        _handle(identity, person_id="tg_15")

        self._action(client, identity, {"action": "preuve",
                                        "kind": "contradicted",
                                        "detail": "faux souvenir"})
        identity.refresh_from_db()
        assert identity.certainty == pytest.approx(0.50)

    def test_une_ecriture_sur_une_identite_sans_handle_est_refusee(self, client):
        identity = _identity(name="orpheline")
        for data in (
            {"action": "lier", "entity_name": "X"},
            {"action": "preuve", "kind": "vouched", "detail": "x"},
            {"action": "revoquer"},
        ):
            res = self._action(client, identity, data)
            assert "error" in [m.level_tag for m in res.context["messages"]], data

    def test_les_ecritures_refusent_le_get(self, client):
        identity = _identity(name="?")
        assert client.get(
            reverse("gestionsysteme:identity-action", args=[identity.pk]),
        ).status_code == 405


# ── Politique ───────────────────────────────────────────────────

class TestPolitique:

    def test_la_politique_est_lue_depuis_le_module(self, client):
        """La page explique ses propres verdicts, depuis les constantes qui
        tournent. Une copie écrite à la main dans le gabarit continuerait
        d'annoncer 0,70 longtemps après que quelqu'un ait déplacé la barre."""
        from identity import trust as trust_policy

        ctx = client.get(URL_POLITIQUE).context
        assert dict(ctx["evidence_weights"]) == trust_policy.EVIDENCE_WEIGHTS
        assert dict(ctx["counter_weights"]) == trust_policy.COUNTER_EVIDENCE_WEIGHTS
        assert ctx["private_threshold"] == trust_policy.PRIVATE_CONTEXT_THRESHOLD

    def test_la_politique_expose_chaque_plafond_de_canal(self, client):
        from identity import trust as trust_policy

        par_canal = {c["trust"]: c for c in client.get(URL_POLITIQUE).context["channels"]}
        for t in ChannelTrust:
            assert par_canal[t.value]["ceiling"] == pytest.approx(
                trust_policy.ceiling_for(t),
            )

    def test_chaque_type_pese_est_un_type_de_revendication_connu(self, client):
        """La liste déroulante des preuves est bâtie là-dessus : un type non
        listé serait une option de formulaire que l'écriture refuse ensuite."""
        ctx = client.get(URL_POLITIQUE).context
        connus = {v for v, _ in ctx["claim_kinds"]}
        peses = {k for k, _ in ctx["evidence_weights"]} | {
            k for k, _ in ctx["counter_weights"]
        }
        # `revoked` n'est pas une revendication qu'on dépose, c'est une trace.
        assert peses <= connus | {"revoked"}


# ── Câblage du menu ─────────────────────────────────────────────

class TestBadgeMenu:

    def test_les_revendications_en_attente_badgent_le_menu(self, client):
        from GestionSysteme.shell import sidebar_counts

        identity = _identity(name="?")
        h = _handle(identity, person_id="tg_16")
        _claim(identity, h)

        assert sidebar_counts().get("identity") == 1

    def test_l_identite_precede_les_personnes_dans_le_menu(self):
        """Ordonné comme le prompt assemble : l'identité qualifie la fiche.

        ``--- QUI TU AS EN FACE ---`` est injecté immédiatement avant
        ``--- CE QUE TU SAIS DE CETTE PERSONNE ---`` ; un menu qui les
        inverserait suggérerait que la fiche tient toute seule.
        """
        from GestionSysteme.nav import item_for

        cles = [t.key for t in item_for("social").tabs]
        assert cles.index("identites") < cles.index("personnes")
