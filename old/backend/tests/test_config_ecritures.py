"""Deux écritures de configuration qui mentaient — par omission.

* **Le journal des lignes ne disait rien.** ``delete_row`` écrivait
  ``row_id=None, before=None`` : une suppression sans dire quoi. ``add_row``
  et ``update_row`` jetaient l'identifiant aussi, et la modification ne
  gardait pas l'état d'avant. Une piste d'audit qui ne permet pas de
  retrouver ce qui a été effacé n'en est pas une.
* **Un champ vide contournait les bornes.** ``_coerce`` rendait ``None`` pour
  un ``int``/``float``/``select`` vide, ``_validate`` laissait passer
  ``None``, et la base retenait NULL — sous le ``min`` déclaré, hors des
  ``choices``, servi tel quel par ``get()`` à tout appelant direct.
"""
from __future__ import annotations

import uuid

import pytest

from old.backend.configs.registry import registry
from old.backend.configs.service import ValidationError, config_service
from old.backend.configs.types import ConfigItem, ConfigRecord, ConfigSection, record_item

pytestmark = pytest.mark.django_db

SECTION = "test_ecritures"
LISTE = f"{SECTION}.liste"
ENTIER = f"{SECTION}.entier"
REEL = f"{SECTION}.reel"
CHOIX = f"{SECTION}.choix"
TEXTE = f"{SECTION}.texte"


@pytest.fixture
def cles_de_test():
    entries = (
        ConfigSection(key=SECTION, label="Test écritures"),
        ConfigItem(
            key=LISTE, type="record_list", section=SECTION, label="Lignes",
            record=ConfigRecord(
                name="ligne", label="Ligne",
                fields=(
                    record_item(key="nom", type="str", label="Nom"),
                    record_item(key="jeton", type="secret", label="Jeton", sensitive=True),
                ),
            ),
        ),
        ConfigItem(key=ENTIER, type="int", section=SECTION, label="Entier",
                   default=30, min=5, max=3600),
        ConfigItem(key=REEL, type="float", section=SECTION, label="Réel",
                   default=0.5, min=0.0, max=1.0),
        ConfigItem(key=CHOIX, type="select", section=SECTION, label="Choix",
                   default="a", choices=("a", "b")),
        ConfigItem(key=TEXTE, type="str", section=SECTION, label="Texte",
                   default="défaut"),
    )
    registry.register(entries)
    yield
    from old.backend.configs.models import ConfigChangeLog, ConfigRecordItem, ConfigValue
    ConfigValue.objects.filter(key__startswith=f"{SECTION}.").delete()
    ConfigRecordItem.objects.filter(parent_key=LISTE).delete()
    ConfigChangeLog.objects.filter(key__startswith=f"{SECTION}.").delete()
    registry.unregister(key_prefix=f"{SECTION}.", section_key=SECTION)
    config_service.invalidate_cache()


def _dernier_journal(action: str):
    from old.backend.configs.models import ConfigChangeLog
    return ConfigChangeLog.objects.filter(key=LISTE, action=action).order_by("-id").first()


# ── Journal des lignes ────────────────────────────────────────────


class TestJournalDesLignes:

    def test_ajouter_une_ligne_journalise_son_identifiant(self, cles_de_test):
        result = config_service.add_row(LISTE, {"nom": "première"}, actor="test")

        journal = _dernier_journal("row_add")
        assert journal is not None
        assert journal.row_id == uuid.UUID(result["row_id"])
        assert journal.after["nom"] == "première"

    def test_modifier_une_ligne_garde_l_etat_d_avant(self, cles_de_test):
        row_id = config_service.add_row(LISTE, {"nom": "ancien"})["row_id"]

        config_service.update_row(LISTE, row_id, {"nom": "nouveau"}, actor="test")

        journal = _dernier_journal("row_update")
        assert journal.row_id == uuid.UUID(row_id)
        assert journal.before["nom"] == "ancien"
        assert journal.after["nom"] == "nouveau"

    def test_supprimer_une_ligne_garde_ce_qui_a_ete_efface(self, cles_de_test):
        """Le cas qui a motivé le correctif : ``before=None, row_id=None``."""
        row_id = config_service.add_row(LISTE, {"nom": "effacée", "jeton": "sk-secret-1234"})["row_id"]

        config_service.delete_row(LISTE, row_id, actor="test")

        journal = _dernier_journal("row_delete")
        assert journal is not None
        assert journal.row_id == uuid.UUID(row_id)
        assert journal.before["nom"] == "effacée"
        assert journal.after is None

    def test_le_secret_d_une_ligne_effacee_reste_masque(self, cles_de_test):
        row_id = config_service.add_row(LISTE, {"nom": "x", "jeton": "sk-secret-1234"})["row_id"]
        config_service.delete_row(LISTE, row_id)

        journal = _dernier_journal("row_delete")
        assert journal.before["jeton"] == "***redacted***"
        assert "sk-secret-1234" not in str(journal.before)

    def test_un_identifiant_qui_n_est_pas_un_uuid_laisse_la_colonne_vide(self):
        """Les comptes d'accès identifient leurs lignes par clé primaire : la
        colonne UUID ne peut pas le porter, et l'écriture ne doit pas lever."""
        from old.backend.configs.service import _row_uuid

        assert _row_uuid("3") is None
        assert _row_uuid(None) is None
        u = uuid.uuid4()
        assert _row_uuid(str(u)) == u
        assert _row_uuid(u) == u


# ── Un champ vide n'est pas une valeur ────────────────────────────


class TestValeurVideRefusee:

    @pytest.mark.parametrize("cle,defaut", [(ENTIER, 30), (REEL, 0.5), (CHOIX, "a")])
    @pytest.mark.parametrize("vide", ["", None])
    def test_un_vide_est_refuse_et_rien_n_est_ecrit(self, cles_de_test, cle, defaut, vide):
        from old.backend.configs.models import ConfigValue

        with pytest.raises(ValidationError, match="réinitialiser"):
            config_service.set(cle, vide, actor="test")

        assert not ConfigValue.objects.filter(key=cle).exists()
        assert config_service.get(cle) == defaut

    def test_un_vide_ne_remplace_pas_une_valeur_deja_reglee(self, cles_de_test):
        config_service.set(ENTIER, 120, actor="test")
        with pytest.raises(ValidationError):
            config_service.set(ENTIER, "", actor="test")
        assert config_service.get(ENTIER) == 120

    def test_le_min_reste_appliquee_a_une_vraie_valeur(self, cles_de_test):
        with pytest.raises(ValidationError, match="≥"):
            config_service.set(ENTIER, 1, actor="test")

    def test_revenir_au_defaut_passe_par_la_reinitialisation(self, cles_de_test):
        config_service.set(ENTIER, 120, actor="test")
        config_service.unset(ENTIER, actor="test")
        assert config_service.get(ENTIER) == 30

    def test_un_texte_vide_reste_une_valeur(self, cles_de_test):
        """Le refus vise les types où le vide n'a pas de sens ; une chaîne
        vide en est une, et ``personality.name`` s'efface ainsi."""
        config_service.set(TEXTE, "", actor="test")
        assert config_service.get(TEXTE) == ""
