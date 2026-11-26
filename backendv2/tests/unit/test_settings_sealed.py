"""Les champs secrets d'une fiche que les réglages d'un domaine rangent (un compte, un serveur, une clé d'API) se
scellent et se rouvrent par une seule aide de sa part (``app/settings.py::SettingsPart._sealed``, ``_opened``) :
chacun est rangé sous ``<champ>_sealed`` — le nom des réglages déjà gardés —, jamais en clair ; le reste de la fiche
passe tel quel ; un scellé absent, ou qui ne s'ouvre plus (``secret.key`` changée), se relit vide ; la fiche donnée
n'est pas changée."""

from __future__ import annotations

from types import SimpleNamespace

from cryptography.fernet import Fernet

from mika.app.settings import SecretBox, SettingsPart


def _part(key: bytes | None = None) -> SettingsPart:
    door = SimpleNamespace(box=SecretBox(key or Fernet.generate_key()), writing=None)
    return SettingsPart(door)  # type: ignore[arg-type]


def test_the_secret_fields_of_a_card_are_sealed_under_their_name_and_nothing_else_moves():
    part = _part()
    card = {"address": "adrien@example.test", "password": "mdp-imap", "smtp_password": "", "port": 993}
    sealed = part._sealed(card, ("password", "smtp_password"))
    assert card == {"address": "adrien@example.test", "password": "mdp-imap", "smtp_password": "", "port": 993}
    assert set(sealed) == {"address", "port", "password_sealed", "smtp_password_sealed"}
    assert sealed["address"] == "adrien@example.test" and sealed["port"] == 993
    assert sealed["password_sealed"] and "mdp-imap" not in sealed["password_sealed"]
    assert sealed["smtp_password_sealed"] == ""  # vide reste vide
    assert part.box.open(sealed["password_sealed"]) == "mdp-imap"
    opened = part._opened(sealed, ("password", "smtp_password"))
    assert opened == card and "password_sealed" in sealed


def test_a_seal_missing_or_that_no_longer_opens_reads_empty():
    key = Fernet.generate_key()
    sealed = _part(key)._sealed({"token": "jeton", "user": "moi"}, ("token",))
    assert _part()._opened(sealed, ("token",)) == {"user": "moi", "token": ""}  # une autre clé
    assert _part(key)._opened({"user": "moi"}, ("token",)) == {"user": "moi", "token": ""}
    assert _part(key)._opened({"token_sealed": None}, ("token",)) == {"token": ""}
