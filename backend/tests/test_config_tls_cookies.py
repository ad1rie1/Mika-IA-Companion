"""Les cookies derrière TLS se déclarent dans ``.env`` — et nulle part avant.

``settings.py`` ne portait ni ``SESSION_COOKIE_SECURE``, ni
``CSRF_COOKIE_SECURE``, ni ``SECURE_PROXY_SSL_HEADER`` : une installation
servie en HTTPS gardait des cookies de session qu'un réseau en clair pouvait
lire, et derrière un proxy TLS ``request.is_secure()`` répondait faux.

Le module est exécuté ici comme un fichier, avec un environnement contrôlé
et sans lecture de ``.env`` : les défauts de Django rendent
``settings.SESSION_COOKIE_SECURE`` vrai-ou-faux quoi qu'il arrive, donc lire
la configuration chargée ne prouverait pas que la variable est câblée.
"""
from __future__ import annotations

import importlib.util
import os
import pathlib
from unittest.mock import patch

import environ
import pytest

SETTINGS = pathlib.Path(__file__).resolve().parent.parent / "config" / "settings.py"
ENV_EXAMPLE = SETTINGS.parent.parent.parent / ".env.example"
VARIABLES = ("SESSION_COOKIE_SECURE", "CSRF_COOKIE_SECURE", "BEHIND_TLS_PROXY")


def _executer_settings(env: dict[str, str]) -> dict:
    """Exécute ``settings.py`` dans un module jetable, avec ``env`` pour seul
    environnement sur les trois variables — le ``.env`` du poste n'est pas lu."""
    propre = {k: v for k, v in os.environ.items() if k not in VARIABLES}
    propre.update(env)
    spec = importlib.util.spec_from_file_location("_settings_sonde", SETTINGS)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(os.environ, propre, clear=True), \
         patch.object(environ.Env, "read_env", lambda *a, **k: None):
        spec.loader.exec_module(module)
    return vars(module)


def test_par_defaut_les_cookies_ne_sont_pas_secure():
    """L'installation type sert http://127.0.0.1:8000 : un cookie Secure n'y
    reviendrait jamais et chaque connexion échouerait sans rien dire."""
    conf = _executer_settings({})
    assert conf["SESSION_COOKIE_SECURE"] is False
    assert conf["CSRF_COOKIE_SECURE"] is False
    assert "SECURE_PROXY_SSL_HEADER" not in conf


def test_derriere_tls_les_deux_cookies_passent_secure():
    conf = _executer_settings({"SESSION_COOKIE_SECURE": "true", "CSRF_COOKIE_SECURE": "true"})
    assert conf["SESSION_COOKIE_SECURE"] is True
    assert conf["CSRF_COOKIE_SECURE"] is True


def test_les_deux_cookies_se_reglent_separement():
    conf = _executer_settings({"SESSION_COOKIE_SECURE": "true"})
    assert conf["SESSION_COOKIE_SECURE"] is True
    assert conf["CSRF_COOKIE_SECURE"] is False


def test_le_proxy_tls_est_un_choix_explicite():
    """Faire confiance à X-Forwarded-Proto n'est sûr que si le proxy est
    l'unique chemin vers le processus : jamais par défaut."""
    conf = _executer_settings({"BEHIND_TLS_PROXY": "true"})
    assert conf["SECURE_PROXY_SSL_HEADER"] == ("HTTP_X_FORWARDED_PROTO", "https")

    conf = _executer_settings({"BEHIND_TLS_PROXY": "false"})
    assert "SECURE_PROXY_SSL_HEADER" not in conf


@pytest.mark.parametrize("variable", VARIABLES)
def test_env_example_documente_la_variable(variable):
    """La table de ``.env`` est fermée : une variable lue sans y figurer est
    une variable qu'on ne trouve pas quand on en a besoin."""
    lignes = ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
    assert any(l.startswith(f"{variable}=") for l in lignes), variable
