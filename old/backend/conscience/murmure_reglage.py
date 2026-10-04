"""Le réglage du murmure, résolu depuis le registre de configuration.

Ce module existe parce que `murmure.py` doit rester **pur** — il expose une
`MurmureTuning` gelée et ne lit ni base ni registre, pour que ses tests
mesurent la calibration déclarée et non celle de la machine qui les exécute.
La résolution se fait donc au bord.

Mais elle ne peut pas vivre en méthode d'un consommateur, à la façon de
`ConscienceEngine._trousse_tuning` : il y a **deux** consommateurs, dans deux
applications différentes — la conscience avant chaque acte, et le lanceur de
projets après chaque avancée — et `projects/` n'a aucune raison d'importer le
moteur de conscience pour murmurer. Un fichier à part est le seul endroit
qu'ils peuvent partager sans se coupler l'un à l'autre.

Les replis sont importés **par leur nom** depuis `murmure` : la garde AST de
`test_config_rapatriement` résout un repli `ast.Name` en attribut du module et
ignore silencieusement un attribut d'instance — un `self._X` passerait sans
être confronté au défaut déclaré, ce qui est précisément la divergence que la
garde existe pour empêcher.
"""

from __future__ import annotations

from old.backend.configs.runtime import cfg_bool, cfg_float, cfg_int
from old.backend.conscience.murmure import (
    MURMURE_DELAI_MIN_SECONDES,
    MURMURE_ENDORMIE,
    MURMURE_FENETRE_REPETITION_SECONDES,
    MURMURE_LONGUEUR_MAX,
    MURMURE_QUOTA_QUOTIDIEN,
    MurmureTuning,
)


def tuning() -> MurmureTuning:
    """Les bornes configurées, ou celles du module si le registre est muet.

    Ne lève jamais : `cfg_*` rend le repli sur un registre injoignable — un
    import avant `migrate`, une base verrouillée, une collecte de tests. Le
    murmure est un ornement appelé depuis des boucles sans superviseur ; il
    doit dégrader vers le comportement de référence, pas vers une exception.
    """
    return MurmureTuning(
        quota_quotidien=cfg_int(
            "conscience.murmure.quota_quotidien",
            MURMURE_QUOTA_QUOTIDIEN, mini=0,
        ),
        delai_min_secondes=cfg_float(
            "conscience.murmure.delai_min_secondes",
            MURMURE_DELAI_MIN_SECONDES, mini=0.0,
        ),
        longueur_max=cfg_int(
            "conscience.murmure.longueur_max",
            MURMURE_LONGUEUR_MAX, mini=1,
        ),
        fenetre_repetition_secondes=cfg_float(
            "conscience.murmure.fenetre_repetition_secondes",
            MURMURE_FENETRE_REPETITION_SECONDES, mini=0.0,
        ),
        murmurer_endormie=cfg_bool(
            "conscience.murmure.endormie", MURMURE_ENDORMIE,
        ),
    )
