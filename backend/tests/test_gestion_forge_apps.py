"""Espace « Forge apps » — les mini-modules que Mika écrit à l'exécution.

Fichier séparé, et ``transaction=True`` pour tout le module, pour la même
raison que ``test_forge_host`` : les handlers forgés tournent dans des threads
workers du bac à sable, qui ne verraient pas une transaction de test non
commitée — et dont les écritures dans ``ForgeLog`` verrouilleraient la table.
Comme ce mode vide la base en fin de test, il est cantonné ici plutôt que
glissé au milieu des 180 tests de ``test_gestion_systeme``.
"""
from __future__ import annotations

import pytest
from asgiref.sync import sync_to_async
from django.urls import reverse

pytestmark = pytest.mark.django_db(transaction=True)

# Ce que ces tests protègent :
#
# Les apps forgées sont écrites **à l'exécution** par Mika : aucune destination
# ne peut être déclarée dans ``nav.py`` pour chacune. D'où une entrée de menu
# unique, une page qui les liste, et un espace par app.
#
# Ce que ces tests protègent : que leur configuration ne réapparaisse pas dans
# la Configuration du cœur (elle y était, créée à chaud entre les clés d'API et
# les seuils de la conscience), et qu'une app arrêtée reste configurable.
#
# Tout est **asynchrone** ici, et ce n'est pas un détail de forme : l'hôte Forge
# planifie ses handlers sur la boucle vivante au moment du chargement. Un
# fixture qui ferme sa boucle (``asyncio.run``) laisse ``_loop`` fermée, et
# rendre une page d'app échoue alors sur « Event loop is closed » — ce que le
# vrai serveur ne fait jamais. ``transaction=True`` pour la même raison que
# ``test_forge_host`` : les handlers tournent dans des threads workers, qui ne
# verraient pas une transaction de test non commitée.


@pytest.fixture
async def app_forgee(tmp_path, settings):
    """Une app forgée réelle, chargée par un vrai hôte Forge.

    ``FORGE_DIR`` pointe sur un répertoire temporaire : les tests ne lisent
    jamais les apps de l'installation qui les exécute.
    """
    from unittest.mock import AsyncMock

    settings.FORGE_DIR = str(tmp_path / "forge_modules")
    from modules.manager import module_manager
    from modules.plugins.forge.module import ForgeModule

    hote = ForgeModule()
    hote.set_notify_ai(AsyncMock())
    await hote.instantiate()

    resultat = await hote.write_module("appli_test", code=(
        "def on_tick(api):\n"
        "    api.storage.set('c', 'n', 1)\n\n"
        "def view_stats(api, params):\n"
        "    return {'columns': [{'key': 'k', 'label': 'Clé'}],\n"
        "            'rows': [{'id': 'n', 'k': 'valeur-visible'}]}\n"
    ), manifest_patch={
        "title": "Appli de test",
        "description": "Écrite par le test",
        "schedule": "interval:5s",
        "views": [{"key": "stats", "label": "Stats"}],
        "config": [{"key": "ville", "label": "Ville", "type": "str",
                    "default": "Paris"}],
        "context": False,
    })
    assert resultat["ok"], resultat

    # Les vues résolvent l'hôte par ``module_manager.get_registered`` : on
    # substitue l'instance de test, puis on rend l'originale — sans quoi les
    # tests suivants verraient un hôte pointant sur un tmp_path effacé.
    registre = module_manager.registry
    ancien = registre._registered.get("forge")
    ancien_actif = registre._active.get("forge")
    registre._registered["forge"] = hote
    registre._active["forge"] = hote
    try:
        yield hote
    finally:
        await hote.shutdown()
        for cible, valeur in ((registre._registered, ancien),
                              (registre._active, ancien_actif)):
            if valeur is None:
                cible.pop("forge", None)
            else:
                cible["forge"] = valeur
        from configs.registry import registry
        registry.unregister(key_prefix="forge.appli_test.",
                            section_key="forge_appli_test")
        # Sous ``transaction=True`` les écritures des threads workers sont
        # réellement commitées : elles fuiteraient dans les tests suivants.
        from modules.plugins.forge.models import ForgeLog, ForgeRecord
        await sync_to_async(
            ForgeRecord.objects.filter(module_name="appli_test").delete,
        )()
        await sync_to_async(
            ForgeLog.objects.filter(module_name="appli_test").delete,
        )()


async def _page(client, url):
    """GET dans un thread — c'est ce que fait uvicorn d'une vue synchrone."""
    return await sync_to_async(client.get)(url)


async def test_la_config_d_une_app_forgee_n_est_plus_dans_le_coeur(client, app_forgee):
    """Le symptôme d'origine : la Configuration du système s'allongeait toute
    seule, une app venant se ranger entre les clés d'API et les seuils de la
    conscience — sous un intitulé qu'aucun schéma déclaré ne contient."""
    from GestionSysteme.views import config as config_view

    assert config_view.is_forge_section("forge_appli_test")
    cles = await sync_to_async(lambda: {s.key for s in config_view.core_sections()})()
    assert "forge_appli_test" not in cles

    page = await _page(client, reverse("gestionsysteme:config-section", args=["accounts"]))
    assert b"forge_appli_test" not in page.content


async def test_l_ancienne_url_de_section_mene_a_l_app(client, app_forgee):
    """Un favori d'avant le déménagement doit atterrir, pas donner un 404."""
    reponse = await _page(
        client, reverse("gestionsysteme:config-section", args=["forge_appli_test"]),
    )
    assert reponse.status_code == 302
    assert reponse["Location"] == reverse(
        "gestionsysteme:forge-app-config", args=["appli_test"],
    )


async def test_la_liste_des_apps_nomme_l_app_et_mene_a_son_espace(client, app_forgee):
    page = await _page(client, reverse("gestionsysteme:forge-apps"))
    assert page.status_code == 200
    assert b"Appli de test" in page.content
    assert reverse("gestionsysteme:forge-app",
                   args=["appli_test"]).encode() in page.content


async def test_l_espace_d_une_app_porte_etat_config_et_pages(client, app_forgee):
    """La demande, en un test : on sélectionne une app et on a sa
    configuration et ses pages, au même endroit que son état."""
    page = await _page(client, reverse("gestionsysteme:forge-app", args=["appli_test"]))
    assert page.status_code == 200
    for url in (
        reverse("gestionsysteme:forge-app-config", args=["appli_test"]),
        reverse("gestionsysteme:forge-app-panel", args=["appli_test", "stats"]),
    ):
        assert url.encode() in page.content, url
    assert b"manifest.yaml" in page.content

    config = await _page(
        client, reverse("gestionsysteme:forge-app-config", args=["appli_test"]))
    assert config.status_code == 200
    assert b"forge.appli_test.ville" in config.content

    vue = await _page(
        client, reverse("gestionsysteme:forge-app-panel", args=["appli_test", "stats"]))
    assert vue.status_code == 200
    assert b"valeur-visible" in vue.content


async def test_une_app_desactivee_reste_configurable(client, app_forgee):
    """Le piège que ce dépôt a déjà corrigé pour les modules : les réglages
    d'une app arrêtée doivent rester atteignables, puisque c'est souvent une
    valeur manquante ici qui l'empêche de démarrer. La config est déclarée par
    le **manifeste**, pas par le code — elle survit donc au déchargement."""
    resultat = await app_forgee.command("appli_test", "disable")
    assert resultat["ok"], resultat
    assert "appli_test" not in app_forgee._loaded

    config = await _page(
        client, reverse("gestionsysteme:forge-app-config", args=["appli_test"]))
    assert config.status_code == 200
    assert b"forge.appli_test.ville" in config.content

    # Sans section enregistrée, ``config_service.set`` refuserait la clé : la
    # page s'afficherait mais n'écrirait rien.
    from configs.registry import registry
    assert registry.get("forge.appli_test.ville") is not None


async def test_les_pages_d_une_app_ne_sont_plus_greffees_sur_l_hote(app_forgee):
    """Greffées dans l'espace du module Forge, dix apps donnaient trente
    onglets à un module qui n'en déclare que trois."""
    assert {p.key for p in app_forgee.get_panels()} == {"modules", "journal", "stockage"}


async def test_une_app_inconnue_donne_un_404(client, app_forgee):
    reponse = await _page(client, reverse("gestionsysteme:forge-app",
                                          args=["nexiste_pas"]))
    assert reponse.status_code == 404


async def test_une_commande_inventee_est_refusee(client, app_forgee):
    """Le formulaire n'est pas la seule source de la commande : une valeur
    forgée à la main ne doit pas atteindre ``ForgeModule.command``."""
    reponse = await sync_to_async(client.post)(
        reverse("gestionsysteme:forge-app-command", args=["appli_test"]),
        {"commande": "rm -rf"},
    )
    assert reponse.status_code == 302
    assert "appli_test" in app_forgee._loaded


async def test_le_menu_place_forge_apps_juste_apres_forge(app_forgee):
    """L'ordre est la seule chose qui dise ce que sont ces apps : ce que la
    Forge produit. Rangée ailleurs dans la liste alphabétique, l'entrée ne
    porterait plus cette information."""
    from GestionSysteme import shell

    liens = await sync_to_async(lambda: [s.key for s in shell.sidebar_spaces()])()
    assert "forge" in liens, liens
    assert liens[liens.index("forge") + 1] == "forge_apps", liens
