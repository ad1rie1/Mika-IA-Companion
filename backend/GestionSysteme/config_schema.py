"""Config schema for access accounts.

The accounts that log into the frontend (``CONSUMER_REQUIRE_AUTH``) and
GestionSystème (``DASHBOARD_REQUIRE_AUTH``) are Django users; this section
edits them through ``UserAccountBackend``, so nothing is duplicated in
``ConfigRecordItem`` and GestionSystème never becomes a second source of
truth about who may log in.

It sits first (``order=10``) on purpose: it is the one section that
decides who gets to read every other one — GestionSystème holds the whole
conversation history and the provider API keys.
"""
from __future__ import annotations

# Importing the backend registers it — side-effect intentional.
from GestionSysteme import config_backend  # noqa: F401

from configs.types import ConfigItem, ConfigRecord, ConfigSection, record_item

CONFIG_SCHEMA = [
    ConfigSection(
        key="accounts", label="Accès · Comptes", icon="⚿", order=10,
        description=(
            "Comptes de connexion (frontend + administration). Tant que "
            "DASHBOARD_REQUIRE_AUTH est désactivé, quiconque atteint cette "
            "page peut créer un compte : garde l'administration en loopback, ou "
            "active l'authentification."
        ),
    ),
    ConfigItem(
        key="accounts.users", type="record_list", section="accounts",
        label="Comptes",
        description=(
            "Un compte = un login pour le frontend, et — si « Accès "
            "administration » est coché — pour /gestion/. Le mot de passe passe "
            "par les mêmes validateurs que la création du premier compte. "
            "Un compte désactivé ne peut plus se connecter mais garde son "
            "historique et son identité."
        ),
        record=ConfigRecord(
            name="user_account", label="Compte",
            description=(
                "Le dernier administrateur actif ne peut être ni supprimé, "
                "ni désactivé, ni rétrogradé — sinon plus personne n'entre."
            ),
            fields=(
                record_item(key="username",     type="str",    label="Nom d'utilisateur",
                            hint="Ce qui est tapé à la connexion. Unique."),
                record_item(key="display_name", type="str",    label="Nom affiché",
                            hint="Le nom que Mika utilise. Vide = nom d'utilisateur."),
                record_item(key="email",        type="str",    label="Email",
                            hint="Facultatif — jamais utilisé pour se connecter."),
                record_item(key="password",     type="secret", label="Mot de passe", sensitive=True,
                            hint="Laisser vide pour conserver l'actuel. Obligatoire à la création."),
                record_item(key="is_staff",     type="bool",   label="Accès administration", default=False,
                            hint="Requis pour /gestion/ quand DASHBOARD_REQUIRE_AUTH est actif."),
                record_item(key="is_superuser", type="bool",   label="Administrateur", default=False,
                            hint="Accès complet à /admin/."),
                record_item(key="person_id",    type="str",    label="person_id", readonly=True,
                            hint="Attribué par le serveur — c'est sous cette identité que Mika te connaît."),
            ),
        ),
    ),
]
