"""Les dessins, tels que la couche ``app`` les relie (ADR 0061, 0063, 0317) : leur fiche.

Une passerelle qu'un seul plugin sert est un domaine (ADR 0317). Ce dossier porte leurs réglages (``settings.py`` :
leurs fournisseurs d'images, la clé de chacun, scellée, et qui dessine quoi), leur câblage (``wiring.py`` : la
passerelle d'images vivante, qui est le port ``imaging`` du noyau, rebranchée sur leurs réglages au démarrage et à
chaque enregistrement, fermée en dernier ; la trace de chaque appel au registre des appels, commun avec celui des
modèles, sous ``image.<rôle>``), leur rubrique de réglages (``console/`` : Réglages › Intelligence › Images) et leur
commande (``cli.py`` : ``mika images``).

Restent au cadre : la passerelle des modèles, qui sert tout le moteur, et le registre des appels ; la place de leur
commande dans ``mika --help`` (``app/cli/models.py::BESIDE_MODELS``) et celle de leur ligne dans la page des plugins
(``ORDER``), deux ordres que le cadre garde en noms.
"""

from __future__ import annotations

from mika.app.domains.domain import Domain

IMAGING = Domain(
    "imaging",
    settings="mika.app.domains.imaging.settings",
    wiring="mika.app.domains.imaging.wiring",
    console="mika.app.domains.imaging.console",
    cli="mika.app.domains.imaging.cli",
)
