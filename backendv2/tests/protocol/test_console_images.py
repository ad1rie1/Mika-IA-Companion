"""La configuration des images dans la console (Configuration › Intelligence › Images) :

- rien de branché : la génération d'images est dite désactivée, et le port ``imaging`` du
  noyau est la passerelle vivante, sans fournisseur ;
- un fournisseur enregistré la branche aussitôt, sans redémarrer ; OpenAI sans clé est
  refusé en le disant, rien n'est gardé ;
- l'adresse et « contenu pour adultes » ne se montrent que pour un serveur (stable-diffusion.cpp, compatible) ;
- les rôles se routent, la table dit qui sert quoi et ce qu'il sait faire ;
- retirer un fournisseur emporte ses rôles et les replis qui menaient à lui ;
- la clé ne redescend jamais dans une page.
"""

from __future__ import annotations

from tests.protocol.test_console_settings import BASE, html_of, post
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée

CANARY = "sk-CANARI-images-0b9d"


def image_backend(name: str, **fields: str) -> dict:
    return {"_section": "images", "_enregistrement": "backends", "_ancienne": "", "_cle": name,
            "_champs": list(fields), **fields}


def test_images_are_off_until_a_provider_is_declared_then_live_without_restarting(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    url = f"{BASE}/images-fournisseurs"
    page = html_of(client.get(url))
    assert "Fournisseurs d'images" in page and "désactivé : aucun fournisseur" in page
    assert live.kernel.deps.ports["imaging"] is live.imaging and not live.imaging.configured

    refused = post(client, url, image_backend("oa", kind="openai", model="gpt-image-1"))
    assert refused.status_code == 400 and "pas de clé" in html_of(refused)
    assert client.portal.call(live.settings.imaging).backends == {} and not live.imaging.configured

    saved = post(client, url, image_backend("oa", kind="openai", model="gpt-image-1", api_key=CANARY))
    assert saved.status_code == 200 and "« oa » enregistré" in html_of(saved) and CANARY not in saved.text
    assert live.imaging.configured and live.imaging.serving("draw") == "oa"
    assert not live.imaging.can("draw", adult=True)

    edit = html_of(client.get(f"{url}?enregistrement=backends&cle=oa"))
    assert 'data-only="kind=openai_compatible|sdcpp"' in edit and CANARY not in edit
    post(client, url, image_backend("maison", kind="openai_compatible", model="qwen-image-2.1",
                                    base_url="http://127.0.0.1:8190/v1", adult="1"))
    kept = post(client, url, {**image_backend("oa", kind="openai", model="gpt-image-1", fallback="maison"),
                              "_ancienne": "oa"})
    assert kept.status_code == 200
    cfg = client.portal.call(live.settings.imaging)
    assert cfg.backends["oa"].api_key == CANARY and cfg.backends["oa"].fallback == "maison"  # clé gardée
    assert cfg.backends["maison"].adult and live.imaging.can("draw", adult=True)

    roles = f"{BASE}/images-roles"
    routed = post(client, roles, {"_section": "images", "_champs": ["routes"], "routes.draw": "oa",
                                  "routes.own": "maison"})
    text = html_of(routed)
    assert routed.status_code == 200 and "Ce qui sert chaque rôle" in text and "par repli (dessiner)" in text
    assert live.imaging.serving("own") == "maison" and live.imaging.serving("edit") == "oa"

    gone = post(client, url, {"_section": "images", "_supprimer": "backends", "_cle": "maison"})
    assert "« maison » retiré" in html_of(gone)
    cfg = client.portal.call(live.settings.imaging)
    assert cfg.routes == {"draw": "oa"} and cfg.backends["oa"].fallback == ""
    assert live.imaging.serving("own") == "oa"

    post(client, url, {"_section": "images", "_supprimer": "backends", "_cle": "oa"})
    assert not live.imaging.configured
    for path in (url, roles, f"{BASE}/fournisseurs"):
        assert CANARY not in client.get(path).text
