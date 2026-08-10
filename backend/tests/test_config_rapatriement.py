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


def _paires_personnalite():
    """Les trois textes qui doivent rester dicibles, et les huit phases.

    ``config/personality.py`` compose ses clés en f-string, donc le scanner AST
    ne les voit pas. Ce sont pourtant les replis qui comptent le plus : ils
    servent aussi quand un champ a été *vidé* depuis le formulaire, pas
    seulement quand le registre est injoignable — un nom effacé ouvrirait le
    prompt sur « Tu es , … ».
    """
    from config.personality import TEXTES_OBLIGATOIRES
    from config.personality_schema import PHASE_DEFAUTS

    # Lus sur les tables elles-mêmes : ce sont les replis réellement passés aux
    # sites d'appel, pas une recopie qui pourrait déjà avoir divergé.
    for champ, repli in TEXTES_OBLIGATOIRES.items():
        yield f"personality.{champ}", repli
    for phase, (heure, ancre) in PHASE_DEFAUTS.items():
        yield f"personality.circadian.phase_hours.{phase}", heure
        yield f"personality.circadian.phase_anchors.{phase}", ancre


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
        ("personnalite", _paires_personnalite),
    )
    for cle, repli in source()
]


def test_les_tables_indirectes_sont_bien_trouvees():
    """Même garde-fou d'inventaire : une table renommée viderait la liste."""
    familles = {nom for nom, _, _ in PAIRES_INDIRECTES}
    assert familles == {"scoring", "confiance", "pulsions", "voix",
                        "personnalite"}, familles
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


# ── Organisation de l'écran ─────────────────────────────────────────────
#
# La mise en forme est déclarative : une section dit sa famille, un groupe dit
# ce qu'il pilote, un bloc rarement touché se déclare `advanced`. Rien de tout
# cela n'est obligatoire — une section qui ne déclare rien se rend comme avant.
# Ces tests ne vérifient donc pas que le mécanisme existe, mais qu'il reste
# *appliqué* : une section ajoutée demain sans famille retomberait dans « Non
# classé », et personne ne le remarquerait avant que ce groupe ne redevienne le
# fourre-tout qu'on vient de démonter.

def _sections_avec_reglages():
    par_section: dict[str, list] = {}
    for item in registry.all_items():
        par_section.setdefault(item.section, []).append(item)
    return [(s, par_section[s.key]) for s in registry.sections()
            if par_section.get(s.key)]


@pytest.mark.parametrize(
    "cle", [s.key for s, _ in _sections_avec_reglages()])
def test_chaque_section_declare_sa_famille_et_son_resume(cle):
    from GestionSysteme.families import FAMILLE_DEFAUT, family_of

    section = next(s for s in registry.sections() if s.key == cle)
    assert family_of(section) != FAMILLE_DEFAUT, (
        f"« {cle} » n'a pas de famille : elle atterrit dans « Non classé », "
        "au bas de la barre latérale."
    )
    assert section.summary, (
        f"« {cle} » n'a pas de résumé : la barre latérale n'a rien à montrer "
        "en infobulle, et la section ne se distingue que par son titre."
    )


@pytest.mark.parametrize(
    "cle", [s.key for s, _ in _sections_avec_reglages()])
def test_chaque_reglage_est_range_dans_un_bloc_decrit(cle):
    """Deux exigences en une : un groupe pour chaque réglage, et une
    description pour chaque groupe.

    Un réglage sans ``group`` tombe dans un bloc anonyme en tête de page —
    c'est ce qui faisait ressembler une section de soixante réglages à un tas.
    Un groupe sans ``ConfigGroup`` n'est qu'un titre : il ne peut ni être
    ordonné, ni être replié, ni dire ce qu'il pilote.

    Les ``record_list`` sont exclus : ils se rendent dans leur propre bloc
    (un tableau avec ses actions), jamais parmi les champs d'un formulaire.
    """
    items = [i for i in registry.all_items()
             if i.section == cle and i.type != "record_list"]
    sans_groupe = sorted(i.key for i in items if not i.group)
    assert not sans_groupe, f"réglages sans bloc dans « {cle} » : {sans_groupe}"

    declares = {g.key for g in registry.groups_for(cle)}
    orphelins = sorted({i.group for i in items} - declares)
    assert not orphelins, (
        f"blocs sans ConfigGroup dans « {cle} » : {orphelins}. "
        "Sans déclaration, le bloc n'a ni ordre, ni description, ni repli."
    )
    for groupe in registry.groups_for(cle):
        if groupe.key in {i.group for i in items}:
            assert groupe.description, (
                f"« {cle} / {groupe.key} » n'explique pas ce qu'il pilote."
            )


def test_les_grosses_sections_replient_une_partie_de_leurs_blocs():
    """Au-delà d'une trentaine de réglages, tout laisser ouvert redonne le tas.

    Le seuil est haut exprès : il ne prescrit pas une proportion, il attrape le
    cas où quelqu'un ajoute quarante réglages à une section sans se demander
    lesquels s'ouvrent en diagnostic seulement.
    """
    manquants = []
    for section, items in _sections_avec_reglages():
        if len(items) < 30:
            continue
        if not any(g.advanced for g in registry.groups_for(section.key)):
            manquants.append(f"{section.key} ({len(items)} réglages)")
    assert not manquants, (
        "sections volumineuses dont aucun bloc n'est replié : "
        f"{manquants}"
    )


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


# ── Mise en page d'un champ ─────────────────────────────────────────────
#
# La grille aligne les champs d'une même ligne en donnant à chaque piste la
# hauteur du plus grand. L'ORDRE des pistes décide donc où tombe le vide quand
# les champs sont inégaux : description au milieu, un champ qui n'en a pas
# héritait du trou creusé par son voisin — libellé en haut, saisie en bas,
# et un blanc entre les deux. Toute la prose est en dernière piste.

_PAGES_ECHANTILLON = ("emotion", "memory", "conscience", "personnalite_traits",
                      "ai_providers", "projects")


@pytest.mark.django_db
@pytest.mark.parametrize("section", _PAGES_ECHANTILLON)
def test_la_prose_dun_champ_vient_apres_sa_saisie(section):
    """Libellé, puis saisie, puis notes — dans cet ordre, dans chaque champ."""
    from django.test import Client

    import re

    html = Client().get(f"/gestion/configuration/{section}/").content.decode()
    # Le conteneur seul : ``class="field "`` ou ``class="field"``. Découper sur
    # ``class="field`` tout court attraperait aussi ``field-label`` et
    # ``field-notes``, et chaque fragment ne contiendrait plus qu'une piste —
    # le test passerait alors sans jamais rien comparer.
    champs = re.split(r'<div class="field[ "]', html)[1:]
    assert champs, f"aucun champ rendu dans « {section} »"

    vus = 0
    for champ in champs:
        i_ctl = champ.find('class="field-control"')
        i_not = champ.find('class="field-notes"')
        if min(i_ctl, i_not) < 0:
            continue

        # Une case à cocher porte son libellé À CÔTÉ d'elle, donc dans la piste
        # du contrôle : elle laisse un emplacement vide dans celle du libellé.
        # C'est le seul champ où le libellé suit le contrôle, et c'est voulu —
        # rangée dans la piste du libellé, la case flottait au-dessus des
        # saisies de sa rangée.
        case_a_cocher = champ.lstrip().startswith("field-check")
        i_lab = champ.find(
            'class="field-slot"' if case_a_cocher else 'class="field-label"')
        assert i_lab >= 0, f"emplacement de libellé absent dans « {section} »"
        assert i_lab < i_ctl < i_not, (
            f"pistes dans le désordre dans « {section} » : la description doit "
            "suivre la saisie, sinon un champ sans prose hérite du vide de son "
            "voisin."
        )
        # Et pas seulement les conteneurs : AUCUNE prose ne doit précéder la
        # saisie. Sans cette seconde assertion, réinsérer une description entre
        # le libellé et le contrôle laissait le test vert — l'ordre des trois
        # conteneurs restait bon, et le vide revenait quand même.
        for classe in ("field-desc", "field-hint", "secret-state"):
            avant = champ.find(f'class="{classe}"')
            assert avant < 0 or avant > i_ctl, (
                f"« {classe} » rendu avant la saisie dans « {section} » : "
                "toute la prose d'un champ va sous le contrôle."
            )
        # La piste du contrôle ne porte QUE la saisie. Sa hauteur est celle du
        # plus grand contrôle de la rangée : y glisser du texte — c'était le
        # cas de l'état d'un champ secret — allongeait la piste pour tous, et
        # les champs voisins voyaient leur saisie suivie de plusieurs dizaines
        # de pixels de vide avant leur propre description.
        controle = champ[i_ctl:i_not]
        for classe in ("field-desc", "field-hint", "secret-state"):
            assert f'class="{classe}"' not in controle, (
                f"« {classe} » est dans la piste du contrôle de « {section} » : "
                "elle en fixerait la hauteur pour toute la rangée."
            )
        vus += 1
    assert vus, f"aucun champ complet analysé dans « {section} »"


@pytest.mark.django_db
def test_une_description_absente_ne_rend_aucune_balise():
    """Une piste vide doit être vide, pas contenir un conteneur vide.

    L'ancien gabarit émettait ``<div class="field-desc"></div>`` même sans
    description, pour garder les trois emplacements. La piste étant désormais
    en dernier, le conteneur ne sert plus à rien : ce qui tient l'alignement,
    c'est ``field-notes``, toujours émis.
    """
    from django.test import Client

    for section in _PAGES_ECHANTILLON:
        html = Client().get(f"/gestion/configuration/{section}/").content.decode()
        assert '<div class="field-desc"></div>' not in html, section


@pytest.mark.django_db
@pytest.mark.parametrize("section", _PAGES_ECHANTILLON)
def test_la_grille_suit_le_nombre_de_champs(section):
    """Un bloc de deux réglages ne réserve pas une troisième colonne vide.

    La grille par défaut est en ``auto-fill`` : elle crée autant de colonnes
    que la largeur en accepte, occupées ou non. Sur une carte large ça fait
    trois colonnes, donc un bloc de deux réglages en laissait une vide et un
    bloc d'un seul en laissait deux — un vide qui se lit comme un défaut
    d'alignement plutôt que comme un choix. Le gabarit déclare donc
    ``cols-1`` / ``cols-2`` à partir du compte que la vue connaît déjà.
    """
    import re

    from django.test import Client

    html = Client().get(f"/gestion/configuration/{section}/").content.decode()
    blocs = re.split(r'<details class="card cfg-bloc', html)[1:]
    assert blocs, f"aucun bloc rendu dans « {section} »"

    for bloc in blocs:
        grille = re.search(r'<div class="form-grid([^"]*)"', bloc)
        if not grille:
            continue
        champs = bloc.count('name="__champ"')
        classe = grille.group(1).strip()
        attendu = {1: "cols-1", 2: "cols-2"}.get(champs, "")
        titre = re.search(r"<h3>([^<]+)</h3>", bloc)
        assert classe == attendu, (
            f"« {section} / {titre.group(1) if titre else '?'} » a {champs} "
            f"réglage(s) mais une grille {classe or 'automatique'} — attendu "
            f"{attendu or 'automatique'}."
        )


# ── Pages d'ajout / modification d'une ligne ────────────────────────────

@pytest.mark.django_db
def test_une_ligne_neuve_ne_montre_pas_de_pastille_modifie():
    """« Modifié » compare une valeur à un défaut déclaré. Une ligne de liste
    — un compte, un flux, un modèle — est une donnée : elle n'en a pas.

    Le défaut était silencieux et total : ``RecordField`` ne définissait pas
    ``is_default``, Django résout un attribut manquant en chaîne vide, donc
    ``{% if not f.is_default %}`` valait vrai et la pastille s'affichait sur
    TOUS les champs de TOUTES les lignes.
    """
    from django.test import Client

    html = Client().get(
        "/gestion/configuration/accounts/accounts.users/nouveau/"
    ).content.decode()
    assert 'class="field-mod"' not in html


@pytest.mark.django_db
def test_un_champ_attribue_par_le_serveur_est_masque_a_la_creation():
    """``person_id`` est en lecture seule et attribué à la création du compte.

    Sur la ligne qui n'existe pas encore il n'a aucune valeur à montrer et
    aucune saisie à recevoir — c'était une case vide et grisée que rien ne
    remplira. Sur une ligne existante il redevient utile : c'est là qu'on lit
    sous quelle identité Mika connaît la personne.
    """
    from django.contrib.auth import get_user_model
    from django.test import Client

    client = Client()
    creation = client.get(
        "/gestion/configuration/accounts/accounts.users/nouveau/"
    ).content.decode()
    assert "person_id" not in creation

    compte = get_user_model().objects.create_user("essai", password="Xk9!vbQ2mzPl")
    edition = client.get(
        f"/gestion/configuration/accounts/accounts.users/{compte.pk}/"
    ).content.decode()
    assert "person_id" in edition


def test_aucune_page_ne_bride_sa_largeur_en_style_en_ligne():
    """Les formulaires d'ajout et de modification occupent la carte.

    Deux d'entre eux portaient un ``max-width`` en style en ligne (62rem pour
    une ligne de liste, 68rem pour un projet), ce qui laissait un tiers de
    l'écran vide. La grille interne borne déjà chaque colonne ; brider le
    conteneur par-dessus ne fait que déplacer le vide.

    Les ``min-width`` sont épargnés : ce sont des indications de colonne de
    tableau, qui empêchent une cellule de texte de s'écraser.
    """
    gabarits = (BACKEND / "GestionSysteme" / "templates").rglob("*.html")
    fautifs = [
        chemin.name for chemin in gabarits
        if "max-width" in chemin.read_text(encoding="utf-8")
    ]
    assert not fautifs, (
        f"largeur bridée en style en ligne : {fautifs}. La largeur se décide "
        "dans la feuille de style, pas gabarit par gabarit."
    )


# ── Panneaux d'une section ──────────────────────────────────────────────
#
# Une section mêle deux natures : des réglages (un formulaire qu'on enregistre
# d'un bloc) et des listes (un tableau de lignes, chacune créée et supprimée
# séparément). Empilées, elles donnaient un formulaire suivi sans transition
# d'un tableau avec ses boutons. Le découpage ne se déclare pas — il découle de
# ce que la section contient, donc un module qui ajoute un `record_list` gagne
# son onglet sans que l'interface connaisse son nom.

@pytest.mark.django_db
def test_une_section_a_liste_se_decoupe_en_onglets():
    """Le module Email : « Réglages » d'un côté, « Comptes email » de l'autre."""
    import re

    from django.test import Client

    client = Client()
    base = "/gestion/modules/email/p/configuration/"
    html = client.get(base).content.decode()

    onglets = re.findall(r'<a class="cfg-panneau" href="[^"]*\?panneau=([^"]+)"', html)
    assert onglets == ["reglages", "email-accounts"], onglets

    # Le premier panneau montre le formulaire, pas le tableau.
    assert 'class="cfg-bar' in html
    assert "Ajouter" not in html

    # Le second montre le tableau, pas le formulaire.
    liste = client.get(f"{base}?panneau=email-accounts").content.decode()
    assert "Ajouter" in liste
    assert 'class="cfg-bar' not in liste


@pytest.mark.django_db
def test_un_panneau_unique_ne_se_presente_pas_comme_un_choix():
    """Une section sans ``record_list`` n'a rien à onglet-er."""
    from django.test import Client

    html = Client().get("/gestion/configuration/memory/").content.decode()
    assert "cfg-panneaux" not in html


@pytest.mark.django_db
def test_un_panneau_inconnu_retombe_sur_le_premier():
    """Un favori d'avant un renommage doit atterrir, pas rendre une page vide."""
    from django.test import Client

    html = Client().get(
        "/gestion/modules/email/p/configuration/?panneau=nexistepas"
    ).content.decode()
    assert 'class="cfg-bar' in html


@pytest.mark.django_db
@pytest.mark.parametrize("url", [
    "/gestion/configuration/personnalite_traits/",   # 3 blocs
    "/gestion/modules/email/p/configuration/",       # 2 blocs
    "/gestion/configuration/memory/",                # beaucoup
])
def test_une_section_annonce_toujours_ses_sous_categories(url):
    """Le sommaire apparaît dès DEUX blocs, et liste tous ceux affichés.

    Le seuil était à trois : la page Caractère annonçait ses trois
    sous-catégories sous le filtre, la page Email n'annonçait pas les deux
    siennes. Un écran dont le sommaire va et vient selon le nombre de blocs
    laisse croire que certaines sections n'ont pas de sous-catégories — on ne
    devine pas ce que rien ne nomme.
    """
    import re

    from django.test import Client

    html = Client().get(url).content.decode()
    blocs = html.count('class="card cfg-bloc')
    pastilles = re.findall(r'class="cfg-toc-item"', html)
    assert blocs >= 2, f"{url} n'a pas assez de blocs pour ce test"
    assert len(pastilles) == blocs, (
        f"{url} : {blocs} blocs mais {len(pastilles)} entrées de sommaire."
    )


def test_la_grille_de_formulaire_ne_depasse_pas_trois_colonnes():
    """Un formulaire n'est pas une galerie.

    ``auto-fill`` créait autant de colonnes que la largeur en acceptait. Tant
    que les cartes étaient bridées à 62rem ça faisait trois ; la bride retirée,
    la même règle en fabriquait cinq, et six champs tombaient en 5 + 1 avec une
    rangée presque vide. Au-delà de trois colonnes l'œil ne rattache plus une
    saisie à son étiquette.
    """
    css = (BACKEND / "GestionSysteme" / "static" / "gestion" / "css"
           / "components.css").read_text(encoding="utf-8")
    assert "repeat(auto-fill" not in css, (
        "`auto-fill` refait dépendre le nombre de colonnes de la largeur "
        "disponible : le nombre se déclare."
    )
    assert "repeat(3, minmax(0, 1fr))" in css


@pytest.mark.django_db
def test_une_case_a_cocher_est_a_hauteur_des_saisies():
    """La case EST le contrôle : sa place est dans la piste des contrôles.

    Rangée dans la piste du libellé, elle se retrouvait à hauteur des libellés
    voisins — donc flottant au-dessus de leurs saisies, comme oubliée en haut
    de la colonne. Elle laisse maintenant un ``field-slot`` vide à sa place,
    pour que le champ garde ses trois pistes.
    """
    import re

    from django.test import Client

    html = Client().get(
        "/gestion/configuration/accounts/accounts.users/nouveau/"
    ).content.decode()

    vues = 0
    for champ in re.split(r'<div class="field[ "]', html)[1:]:
        if not champ.lstrip().startswith("field-check"):
            continue
        i_slot = champ.index('class="field-slot"')
        i_ctl = champ.index('class="field-control"')
        i_case = champ.index('type="checkbox"')
        i_notes = champ.index('class="field-notes"')
        assert i_slot < i_ctl < i_case < i_notes
        vues += 1
    assert vues >= 2, vues
