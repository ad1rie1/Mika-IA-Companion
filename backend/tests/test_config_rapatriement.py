"""Un seul défaut déclaré par réglage — le vérifier, plutôt que l'espérer.

Rapatrier une constante en configuration laisse deux valeurs en place : le
``default`` du ``ConfigItem`` et la constante d'origine, devenue le repli passé
à ``cfg_int``/``cfg_float``/… Cette redondance est voulue (le repli sert quand
le registre est hors d'atteinte : import avant ``migrate``, base verrouillée,
collecte des tests) mais elle rejoue exactement la configuration qui a coûté
cher à nettoyer — ``env_fallback``, où le second défaut gagnait silencieusement
et où celui qu'un lecteur regarde était décoratif et libre de dériver.

La différence tient à une seule propriété : **les deux valeurs doivent être
égales**. Tant qu'elles le sont, il n'y a qu'un défaut déclaré, écrit deux fois.
Dès qu'elles divergent, une installation neuve et une installation dont la base
est illisible ne se comportent plus pareil, et rien ne le dit.

Le test lit les sites d'appel à la source (AST), résout le repli dans son propre
module, et le compare au ``default`` du registre. Il attrape aussi bien la
constante modifiée sans toucher au schéma que le schéma modifié sans toucher à
la constante.
"""
from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

from configs.registry import registry

BACKEND = Path(__file__).resolve().parent.parent
LECTEURS = {"cfg_int", "cfg_float", "cfg_bool", "cfg_str", "cfg_list"}

#: Les fichiers dont on n'exige rien : le helper lui-même (il *définit* les
#: lecteurs) et les tests (un repli y est souvent une valeur de scénario).
IGNORES = ("configs/runtime.py", "tests/")


def _modules_python():
    for chemin in sorted(BACKEND.rglob("*.py")):
        rel = chemin.relative_to(BACKEND).as_posix()
        if any(rel.startswith(p) or f"/{p}" in rel for p in IGNORES):
            continue
        if "/migrations/" in rel:
            continue
        yield rel, chemin


def _nom_module(rel: str) -> str:
    return rel[:-3].replace("/", ".").removesuffix(".__init__")


def _appels_avec_repli():
    """Chaque ``cfg_*("clé", REPLI)`` du backend, avec de quoi le résoudre.

    Un repli qui n'est pas un simple nom ou littéral (une expression calculée,
    un attribut) est ignoré : le test vérifie une égalité de valeurs déclarées,
    pas le résultat d'un calcul.
    """
    for rel, chemin in _modules_python():
        try:
            arbre = ast.parse(chemin.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover — un fichier illisible se voit ailleurs
            continue
        for noeud in ast.walk(arbre):
            if not isinstance(noeud, ast.Call):
                continue
            fn = noeud.func
            nom = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)
            if nom not in LECTEURS or len(noeud.args) < 2:
                continue
            cle, repli = noeud.args[0], noeud.args[1]
            if not (isinstance(cle, ast.Constant) and isinstance(cle.value, str)):
                continue
            yield rel, cle.value, repli, noeud.lineno


def _valeur_repli(rel: str, repli: ast.expr):
    """La valeur du repli, ou ``_INCONNU`` s'il n'est pas déclarativement lisible."""
    if isinstance(repli, ast.Constant):
        return repli.value
    if isinstance(repli, ast.UnaryOp) and isinstance(repli.op, ast.USub) \
            and isinstance(repli.operand, ast.Constant):
        return -repli.operand.value
    if isinstance(repli, ast.Name):
        module = importlib.import_module(_nom_module(rel))
        return getattr(module, repli.id, _INCONNU)
    return _INCONNU


_INCONNU = object()


def _cas():
    """``(fichier, ligne, clé, repli)`` pour chaque site vérifiable."""
    vus = []
    for rel, cle, repli, ligne in _appels_avec_repli():
        valeur = _valeur_repli(rel, repli)
        if valeur is _INCONNU:
            continue
        vus.append((rel, ligne, cle, valeur))
    return vus


CAS = _cas()


def test_des_sites_dappel_sont_bien_trouves():
    """Garde-fou d'inventaire : un test qui ne mesure rien passe toujours.

    Le seuil est délibérément bas — il ne dit pas « tout est rapatrié », il dit
    « le scanner AST voit encore quelque chose ». Un refactor qui renommerait
    les lecteurs viderait ``CAS`` et rendrait vert le test principal.
    """
    assert len(CAS) > 100, f"seulement {len(CAS)} sites lus — le scanner AST a décroché"


@pytest.mark.parametrize(
    "rel,ligne,cle,repli",
    CAS,
    ids=[f"{c[2]}@{c[0]}:{c[1]}" for c in CAS],
)
def test_le_repli_vaut_le_defaut_declare(rel, ligne, cle, repli):
    item = registry.get(cle)
    assert item is not None, (
        f"{rel}:{ligne} lit « {cle} », que le registre ne déclare pas. "
        "Sans ConfigItem la clé n'apparaît dans aucun écran et ne peut pas "
        "être réglée : le repli est alors la seule valeur, en dur."
    )
    assert item.default == repli, (
        f"{rel}:{ligne} — « {cle} » a deux défauts qui ne sont pas d'accord : "
        f"le schéma déclare {item.default!r}, le site d'appel se replie sur "
        f"{repli!r}. Une installation neuve tournerait sur le premier, une "
        "installation dont la base est illisible sur le second."
    )


@pytest.mark.parametrize(
    "cle", sorted({c[2] for c in CAS}),
)
def test_le_defaut_declare_tient_dans_ses_propres_bornes(cle):
    """Un défaut hors bornes est refusé à la première écriture du formulaire.

    Le cas se produit sans bruit : on resserre un ``max`` en relisant un
    réglage, le défaut passe dessous, et l'écran devient impossible à
    enregistrer sans changer une valeur qu'on ne voulait pas toucher.
    """
    item = registry.get(cle)
    if item is None or not isinstance(item.default, (int, float)) \
            or isinstance(item.default, bool):
        pytest.skip("pas un réglage numérique borné")
    if item.min is not None:
        assert item.default >= item.min, f"{cle}: défaut {item.default} < min {item.min}"
    if item.max is not None:
        assert item.default <= item.max, f"{cle}: défaut {item.default} > max {item.max}"


# ── Les replis que l'AST ne sait pas lire ───────────────────────────────
#
# Quatre familles de réglages ne passent pas par un ``cfg_*("clé", CONSTANTE)``
# lisible statiquement : la clé y est une f-string (``f"drives.{kind}.weight"``)
# et le repli un attribut (``d.sleep_penalty``). Le scanner ci-dessus les
# ignore, et un défaut de schéma qu'on y changerait seul passerait inaperçu —
# vérifié par mutation : modifier ``conscience.sleep_penalty`` dans le schéma
# ne rendait aucun test rouge tant que ces quatre tables n'étaient pas
# couvertes.
#
# Le repli est ici une **table déclarée** (une dataclass, un dict), donc la
# même propriété se vérifie plus simplement : champ par champ, la table doit
# valoir le défaut du registre. On lit la table, jamais ``config_service`` —
# son cache est amorcé sur la vraie ``data/vtuber.db``, et un test qui la
# consulterait mesurerait les réglages de la machine qui l'exécute.

def _paires_scoring():
    from conscience.scoring import ScoringTuning
    d = ScoringTuning()
    for champ in d.__dataclass_fields__:
        # Deux préfixes possibles : les onze facteurs sont rangés sous
        # ``factor.``, le reste directement sous ``conscience.``.
        for cle in (f"conscience.{champ}", f"conscience.factor.{champ}"):
            if registry.get(cle) is not None:
                yield cle, getattr(d, champ)
                break


def _paires_confiance():
    from identity.trust import DEFAULT_TUNING as d
    yield "identity.private_context_threshold", d.private_context_threshold
    yield "identity.confident_threshold", d.confident_threshold
    yield "identity.pending_claim_ttl_days", d.pending_claim_ttl_days
    for kind, poids in d.evidence_weights.items():
        yield f"identity.evidence_weight.{kind}", poids
    for kind, poids in d.counter_evidence_weights.items():
        yield f"identity.counter_weight.{kind}", poids


def _paires_pulsions():
    from drives.state import DEFAULT_PARAMS
    for kind, base in DEFAULT_PARAMS.items():
        prefixe = f"drives.{kind.value}."
        yield prefixe + "growth_rate", base.growth_rate
        yield prefixe + "decay_on_satisfy", base.decay_on_satisfy
        yield prefixe + "weight", base.weight
        yield prefixe + "satisfy_threshold", base.satisfy_threshold
        if base.growth_horizon:
            yield prefixe + "growth_tau", base.growth_tau
            # Déclaré en jours, stocké en secondes.
            yield prefixe + "growth_horizon_days", base.growth_horizon / 86400.0


def _paires_voix():
    from pipeline.voice import VOICE_PROFILES
    for persona, profil in VOICE_PROFILES.items():
        for champ in ("pitch", "rate", "gain"):
            yield f"voice.profile.{persona}.{champ}", getattr(profil, champ)


PAIRES_INDIRECTES = [
    (nom, cle, repli)
    for nom, source in (
        ("scoring", _paires_scoring), ("confiance", _paires_confiance),
        ("pulsions", _paires_pulsions), ("voix", _paires_voix),
    )
    for cle, repli in source()
]


def test_les_tables_indirectes_sont_bien_trouvees():
    """Même garde-fou d'inventaire : une table renommée viderait la liste."""
    familles = {nom for nom, _, _ in PAIRES_INDIRECTES}
    assert familles == {"scoring", "confiance", "pulsions", "voix"}, familles
    assert len(PAIRES_INDIRECTES) > 60, len(PAIRES_INDIRECTES)


@pytest.mark.parametrize(
    "famille,cle,repli", PAIRES_INDIRECTES,
    ids=[f"{p[0]}:{p[1]}" for p in PAIRES_INDIRECTES],
)
def test_la_table_de_repli_vaut_le_defaut_declare(famille, cle, repli):
    item = registry.get(cle)
    assert item is not None, (
        f"« {cle} » est lu depuis la table {famille} mais n'est déclaré nulle "
        "part : le réglage n'apparaît dans aucun écran."
    )
    assert item.default == pytest.approx(repli), (
        f"« {cle} » a deux défauts qui ne sont pas d'accord : le schéma déclare "
        f"{item.default!r}, la table {famille} se replie sur {repli!r}."
    )


def test_les_trois_plafonds_somment_au_seuil_daction():
    """L'invariant que la conscience tient depuis son correctif d'initiative.

    Inactivité (+0.30), pulsions (+0.50) et « on m'ignore » (−0.30) somment
    *exactement* au seuil, comparé avec ``>=`` : c'est ce qui fait qu'aucun
    silence ne peut la faire taire tout à fait. Rapatrier les quatre valeurs en
    configuration les rend réglables une par une, donc désaccordables — et le
    symptôme (cinq initiatives en vingt minutes, puis vingt-trois heures de
    mutisme) ne ressemble pas à un réglage.

    Le test ne verrouille pas les valeurs réglées, il verrouille les **défauts
    déclarés** : l'installation neuve part de la calibration documentée.
    """
    lire = lambda cle: registry.get(cle).default  # noqa: E731
    somme = (lire("conscience.factor.idle_cap")
             + lire("conscience.factor.drives_cap")
             - lire("conscience.factor.ignored_cap"))
    assert somme == pytest.approx(lire("conscience.act_threshold"))


def test_une_revendication_seule_ne_franchit_jamais_la_barre():
    """La calibration des preuves d'identité, sur les défauts déclarés.

    « Je suis Thomas » seul ne doit jamais suffire, « je sais un truc sur
    Thomas » seul non plus, mais les deux ensemble tombent *exactement* sur la
    barre de divulgation. C'est ce qui sépare « elle t'appelle par ton prénom »
    de « elle te lit la fiche de quelqu'un d'autre ».
    """
    lire = lambda cle: registry.get(cle).default  # noqa: E731
    barre = lire("identity.private_context_threshold")
    seule = lire("identity.evidence_weight.self_declared")
    connue = lire("identity.evidence_weight.shared_memory")
    assert seule < barre and connue < barre
    assert seule + connue == pytest.approx(barre)


def test_aucune_cle_declaree_deux_fois():
    """``registry.register`` ignore un doublon avec un simple warning.

    Le premier déclarant gagne, ce qui dépend de l'ordre de démarrage des
    applications — donc la valeur effective d'une clé déclarée deux fois n'est
    pas lisible dans le code qui la déclare.
    """
    from collections import Counter
    compte = Counter(i.key for i in registry.all_items())
    doublons = {k: n for k, n in compte.items() if n > 1}
    assert not doublons, f"clés déclarées plusieurs fois : {doublons}"


def test_chaque_item_appartient_a_une_section_declaree():
    """Une section absente s'affiche quand même, sous une étiquette inventée
    à partir de sa clé (``render_schema``) — donc un réglage rangé dans une
    section fantôme apparaît dans un écran sans titre plutôt que de manquer.
    """
    sections = {s.key for s in registry.sections()}
    orphelins = sorted({
        i.key for i in registry.all_items() if i.section not in sections
    })
    assert not orphelins, f"réglages sans section déclarée : {orphelins}"
