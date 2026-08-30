"""Quels outils accompagnent un acte de conscience — et ce que le prompt en dit.

Remplace ``ConscienceEngine._pick_relevant_modules``, qui dérivait la trousse
de ``{obs.source for obs in ctx.pending_observations}``. Trois défauts mesurés,
que ce module répare ensemble parce qu'ils n'en font qu'un :

**B1 — l'acte endogène partait sans aucun outil.** Inactivité, salutation,
débordement d'humeur, pression de pulsion et rumination sont les cinq raisons
qui déclenchent le plus souvent un acte, et *aucune* ne crée d'``Observation``.
L'ensemble de sources était donc vide, la trousse aussi, et la seule branche
qui ajoutait quelque chose (``wake`` + ``conscience_tools``) exigeait soit une
action programmée due, soit une observation à pertinence > 0.6 — c'est-à-dire
exactement les cas où il y avait déjà des sources. Un socle inconditionnel
règle ça : se souvenir et se programmer une suite sont les deux gestes dont
un acte spontané a besoin quoi qu'il arrive.

**B2 — les sources ne sont pas des noms de modules.** ``Observation.source``
vaut ``event.source_module``, et les émetteurs les plus bavards sont
``frontend``, ``telegram``, ``pipeline`` : aucun n'est un module enregistré.
``ModuleCollectors.tools_for`` filtre sur des noms qu'il ne trouve pas et rend
une liste vide **sans rien dire**. La table ci-dessous est explicite, y compris
— et surtout — pour les entrées qui traduisent vers *rien* : le silence était
le bug, l'écrire est le correctif.

**B3 — le prompt annonçait tout pendant que la trousse était vide.**
``_build_action_prompt`` collait le ``capabilities_summary`` des dix modules
sous « Ce que tu peux faire (utilise les outils si pertinent) », alors que le
``ConversationContext`` monté juste après ne portait souvent aucun outil. Le
modèle faisait la seule chose cohérente avec ce qu'on lui disait : il
*racontait* l'action. D'où deux blocs, jamais un : ce qu'elle a en main, et
ce qui existe ailleurs et qu'elle ne peut pas toucher ce tour-ci.

Ce module est **pur** : il ne lit ni base, ni registre de configuration, ni
``module_manager``. Le poids d'un module lui est injecté sous forme de
callable, et le plafond vit dans une dataclass gelée sur le modèle de
``conscience/scoring.py::ScoringTuning`` — la résolution depuis la
configuration se fera au bord, dans le moteur. C'est ce qui rend les tests
mesurables : ils épinglent la calibration *déclarée*, pas ce que contient la
base de la machine qui les exécute.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Sequence

from utils.degradation import degradations

# ── Le socle et les deux extensions ───────────────────────────────────────
#
# Des **listes** et non des tuples, volontairement : ces trois valeurs SONT
# les replis des `ConfigItem` de type `list` (`conscience.trousse.socle` /
# `.curiosite` / `.social`, lus par `ConscienceEngine._trousse_tuning` via
# `cfg_list`), et la garde AST de `tests/test_config_rapatriement.py`
# compare `item.default == repli` — or `["a"] != ("a",)`. Un tuple ici
# ferait échouer la suite, très loin de sa cause.

#: Ce qu'un acte endogène a besoin d'avoir en main, toujours.
#:
#: `memory_tools` parce qu'un acte spontané part d'un souvenir ou n'a pas de
#: raison d'être ; `conscience_tools` parce que « je reviendrai là-dessus »
#: n'est une intention que si `schedule_action` existe — sans lui la phrase
#: est un mensonge poli, et c'est précisément la forme que prenaient les actes
#: mesurés. Les deux pèsent ~2 919 caractères de déclaration (~834 jetons),
#: contre ~20 559 pour les dix modules : le socle n'est pas un compromis de
#: budget, il tient largement.
SOCLE: list[str] = ["conscience_tools", "memory_tools"]

#: Ce qu'on ajoute quand CURIOSITY est saillante.
#:
#: H1 : la pulsion monte, pousse le score, produit une phrase — et rien ne
#: choisit jamais de *sujet*. `rss` et `files` sont les deux seules surfaces
#: du dépôt où quelque chose de nouveau peut être trouvé plutôt qu'inventé
#: (`memory_search` est déjà dans le socle, mais il ne rend que du déjà-vécu :
#: une curiosité assouvie par sa propre mémoire n'est pas de la curiosité).
CURIOSITE: list[str] = ["rss", "files"]

#: Ce qu'on ajoute quand SOCIAL est saillante.
#:
#: `email` est le seul canal sortant qu'elle peut ouvrir d'elle-même — le
#: frontend et Telegram ne s'atteignent qu'en répondant à quelqu'un, ce qui
#: n'est pas ce qu'est un acte endogène. `identity_tools` va avec : joindre
#: quelqu'un suppose de savoir de qui on parle, et la couche d'identité est
#: la seule qui réponde à cette question sans deviner par égalité de nom.
SOCIAL: list[str] = ["email", "identity_tools"]


# ── Réglages ──────────────────────────────────────────────────────────────

#: Plafond du poids des déclarations d'outils, en caractères.
#:
#: Exprimé en caractères et pas en jetons parce que c'est ce qu'on sait
#: mesurer sans appeler un tokeniseur (`ai/budget.py::tools_prompt_chars`
#: compte nom + description + schéma JSON, la charge réellement re-postée à
#: *chaque* itération de la boucle d'outils). Mesures : socle 2 919, dix
#: modules 20 559, soit ~2 056 par module. 8 000 laisse donc passer le socle
#: avec près de trois fois sa taille de marge, et refuse la trousse complète —
#: qui, derrière un modèle local, coûtait 76 s pour un simple bonjour.
PLAFOND_CARACTERES = 8000

#: Tension à partir de laquelle une pulsion élargit la trousse.
#:
#: Alignée sur `drives/engine.py::_OBSERVATION_CURIOSITY_GATE` (0.50) : la
#: même saillance qui fait qu'une observation nourrit la curiosité fait qu'on
#: lui donne de quoi la nourrir. Volontairement **sous** le plafond du chemin
#: heuristique de l'interprète (`PERTINENCE_RSS_MATCHED = 0.55`) : une porte
#: qu'aucun signal heuristique ne peut franchir est une porte fermée.
PORTE_PULSION = 0.50


@dataclass(frozen=True)
class TrousseTuning:
    """Les réglages de la trousse, avec les constantes du module pour défauts.

    ``TrousseTuning()`` sans argument reproduit le comportement déclaré, ce
    qui laisse leur sens aux tests : ils mesurent la calibration écrite ici,
    jamais celle de la base locale.

    Les trois listes sont ICI et plus en lecture directe des constantes :
    leurs clés (`conscience.trousse.socle` / `.curiosite` / `.social`)
    étaient déclarées au registre et lues par personne — une configuration
    que l'opérateur modifiait sans aucun effet, en silence : la forme exacte
    du bug `env_fallback`. Le moteur les résout dans `_trousse_tuning()`.
    """

    plafond_caracteres: int = PLAFOND_CARACTERES
    porte_pulsion: float = PORTE_PULSION
    socle: tuple[str, ...] = tuple(SOCLE)
    curiosite: tuple[str, ...] = tuple(CURIOSITE)
    social: tuple[str, ...] = tuple(SOCIAL)


DEFAULT_TUNING = TrousseTuning()


# ── Sources → modules ─────────────────────────────────────────────────────

#: Traduction explicite d'un ``Observation.source`` vers des noms de modules.
#:
#: Les entrées vides sont le cœur du correctif B2 : ce sont des émetteurs
#: d'événements qui ne sont pas des modules, et les laisser passer tels quels
#: revenait à demander au registre des outils pour « frontend ». Les nommer
#: ici avec un tuple vide dit « on connaît cette source, elle ne donne accès
#: à rien », ce qui n'est pas la même chose que « on ne la connaît pas » —
#: cette seconde catégorie remonte dans ``Trousse.inconnus``.
_SOURCES_VERS_MODULES: dict[str, tuple[str, ...]] = {
    # Canaux d'entrée. `frontend`/`telegram` viennent de `emit_communication_event`
    # et du routeur de perceptions ; `web_connect` est le tour de salutation.
    "frontend": (),
    "telegram": (),
    "web_connect": (),
    # Plomberie interne. `pipeline` émet `_turn.completed`, `conscience` est
    # sa propre source quand elle agit : se donner des outils parce qu'on a
    # parlé au tour d'avant est une boucle, pas une raison.
    "pipeline": (),
    "conscience": (),
    # `wake` EST un module enregistré, et c'est justement pourquoi il est
    # listé : son unique outil (`trigger_wake`) déclenche le cycle de réveil
    # à l'intérieur duquel on se trouve déjà, et la vie des actions différées
    # (programmer, lister, annuler) a déménagé dans `conscience_tools`, qui
    # est au socle. Le charger ne donnait rien d'autre que de quoi se
    # re-réveiller.
    "wake": (),
    # Modules dont l'événement rend vraiment leurs outils utiles.
    "email": ("email",),
    "rss": ("rss",),
    "camera": ("camera",),
    "files": ("files",),
    "forge": ("forge",),
    "project_tools": ("project_tools",),
    "identity_tools": ("identity_tools",),
    "memory_tools": ("memory_tools",),
    "conscience_tools": ("conscience_tools",),
}


def modules_pour_source(source: str) -> tuple[str, ...]:
    """Les modules qu'une source d'observation justifie de charger.

    Une source de la forme ``forge/<app>`` est coupée sur ``/`` : le host
    ``forge`` relaie les événements de ses modules forgés sous ce nom composé
    (``modules/plugins/forge/module.py``), et ce sont les outils du host qui
    servent à lire ou réparer l'app, pas ceux de l'app (elle n'en expose pas).

    Une source **absente de la table** est rendue telle quelle, comme
    *candidat* : un module ajouté demain garde ainsi ses outils sans qu'on
    touche à cette table. La vérification que ce nom existe appartient à
    ``preparer``, qui a le registre ; ce qui ne peut pas exister, en revanche,
    c'est qu'un nom absent de la table ET absent du registre file en silence.
    """
    # ``str(...)`` et pas ``source.strip()`` : la source vient d'une ligne de
    # base (``Observation.source``) ou d'un ``ModuleEvent`` construit par du
    # code de module — rien ne garantit une chaîne, et cette fonction tourne
    # dans une boucle que personne ne supervise.
    nom = str(source or "").strip()
    if not nom:
        return ()
    if "/" in nom:
        nom = nom.split("/", 1)[0]
    if nom in _SOURCES_VERS_MODULES:
        return _SOURCES_VERS_MODULES[nom]
    return (nom,)


# ── La trousse ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Trousse:
    """Ce qu'on charge, ce qu'on a refusé, et de quoi le dire au modèle.

    Les trois listes sont disjointes et exhaustives par construction : tout
    nom souhaité finit dans exactement une des trois. C'est ce qui permet aux
    deux blocs de prompt de ne jamais se contredire — et à un opérateur de
    lire, dans un journal, pourquoi un acte est parti les mains vides.
    """

    #: Retenus, socle en tête, ordre de priorité.
    modules: tuple[str, ...] = ()
    #: Voulus, refusés faute de place sous le plafond.
    ecartes: tuple[str, ...] = ()
    #: Nommés, mais qu'aucun module enregistré ne porte. Ce sont les trous de
    #: la table de traduction : autrefois silencieux, maintenant comptés.
    inconnus: tuple[str, ...] = ()
    #: Poids cumulé, en caractères de déclaration, de ``modules``.
    caracteres: int = 0
    #: Le plafond appliqué, gardé pour que la décision reste relisible.
    plafond: int = PLAFOND_CARACTERES

    def bloc_en_main(self, noms_outils: Sequence[str] = ()) -> str:
        """Premier bloc de prompt : ce dont elle dispose *ce tour-ci*.

        Ne rend **jamais** la chaîne vide. Une trousse vide est un fait qu'il
        faut dire : c'est exactement l'état dans lequel partaient les actes
        endogènes mesurés, et le taire est ce qui produisait des réponses où
        elle annonce un envoi de mail qui n'a jamais eu lieu.
        """
        if not self.modules:
            return (
                "--- CE QUE TU AS EN MAIN ---\n"
                "Aucun outil ce tour-ci. Tu peux penser et parler, rien de plus. "
                "N'annonce pas une action que tu ne peux pas faire maintenant."
            )
        lignes = [
            "--- CE QUE TU AS EN MAIN ---",
            "Tu peux t'en servir tout de suite : " + ", ".join(self.modules) + ".",
        ]
        outils = [str(n) for n in noms_outils if str(n).strip()]
        if outils:
            lignes.append("Outils chargés : " + ", ".join(outils) + ".")
        lignes.append(
            "Ce qui n'est pas dans cette liste, tu ne peux pas le faire "
            "pendant ce tour."
        )
        return "\n".join(lignes)


# ── Les deux fonctions publiques ──────────────────────────────────────────


def souhaits(
    sources: Iterable[str] = (),
    drives: Mapping | None = None,
    demandes: Iterable[str] = (),
    *,
    tuning: TrousseTuning = DEFAULT_TUNING,
) -> list[str]:
    """La trousse *voulue*, avant toute contrainte de place.

    Ordre du retour = ordre de priorité, parce que c'est lui que le plafond
    consomme dans ``preparer``. Il est délibérément différent de l'ordre des
    arguments :

    1. le **socle**, jamais coupé ;
    2. les **demandes** explicites — une action programmée qui nomme un module
       est une intention déjà formée, la chose la plus proche d'un ordre ;
    3. les **sources** — ce qui vient de se produire ;
    4. les **pulsions** — une humeur, donc le plus révocable des trois.

    Dédupliqué en gardant la première occurrence : un module voulu à deux
    titres garde son rang le plus fort.
    """
    voulus: list[str] = []

    def _ajouter(noms: Iterable[str]) -> None:
        for brut in noms:
            nom = str(brut or "").strip()
            if nom and nom not in voulus:
                voulus.append(nom)

    _ajouter(tuning.socle)
    _ajouter(demandes or ())

    for source in sources or ():
        _ajouter(modules_pour_source(source))

    # Les pulsions en dernier : elles élargissent, elles ne commandent pas.
    if _tension(drives, "curiosity") >= tuning.porte_pulsion:
        _ajouter(tuning.curiosite)
    if _tension(drives, "social") >= tuning.porte_pulsion:
        _ajouter(tuning.social)

    return voulus


def preparer(
    sources: Iterable[str] = (),
    drives: Mapping | None = None,
    demandes: Iterable[str] = (),
    *,
    poids: Callable[[str], int],
    disponibles: Iterable[str] | None = None,
    tuning: TrousseTuning = DEFAULT_TUNING,
) -> Trousse:
    """Applique le registre puis le plafond à ce que ``souhaits`` a voulu.

    ``poids`` rend le poids en caractères de déclaration d'un module — côté
    moteur, ``tools_prompt_chars(module_manager.get_tools_for_modules([nom]))``.
    Il est **injecté** et non importé : ce module doit rester testable sans
    registre d'applications Django, et surtout sans que la mesure du budget
    dépende de quels modules tournent sur la machine qui exécute les tests.

    ``disponibles`` à ``None`` signifie « je ne sais pas qui est enregistré » :
    tout nom est alors accepté et ``inconnus`` reste vide. Passé, il filtre —
    et c'est là que B2 devient visible plutôt que silencieux.

    Le plafond se consomme **module par module, jamais outil par outil** :
    une demi-trousse d'un module est un piège, le modèle voyant
    ``send_email`` sans ``list_recent_emails`` conclut qu'il peut écrire à
    l'aveugle. Le socle passe quoi qu'il arrive, même s'il dépasse à lui seul
    — le couper reviendrait à revenir au défaut B1 par une autre porte.

    Un module refusé n'arrête pas le tri : un petit module derrière un gros
    refusé entre quand même. Sans ça, un seul module obèse (la forge et ses
    six outils) affamait silencieusement tout ce qui était en dessous de lui.

    Ne lève jamais : ceci s'exécute dans la boucle de décision, que personne
    ne supervise.
    """
    voulus = souhaits(sources, drives, demandes, tuning=tuning)

    connus: set[str] | None = None
    if disponibles is not None:
        connus = {str(n).strip() for n in disponibles if str(n or "").strip()}

    socle = [n for n in tuning.socle if str(n).strip()]
    retenus: list[str] = []
    ecartes: list[str] = []
    inconnus: list[str] = []
    total = 0
    plafond = max(0, int(tuning.plafond_caracteres))

    for nom in voulus:
        est_socle = nom in socle
        if connus is not None and nom not in connus:
            # Ni traduit par la table, ni porté par un module : autrefois
            # `tools_for` le jetait sans un mot. Même le socle y passe — un
            # `memory_tools` absent du registre est une panne d'installation,
            # pas quelque chose à charger de force.
            inconnus.append(nom)
            continue

        cout = _poids_de(poids, nom)
        if est_socle:
            retenus.append(nom)
            total += max(0, cout)
            continue
        if cout < 0:
            # Poids illisible (le callable a levé) : on refuse plutôt que de
            # garantir un plafond qu'on ne sait pas tenir.
            ecartes.append(nom)
            continue
        if total + cout > plafond:
            ecartes.append(nom)
            continue
        retenus.append(nom)
        total += cout

    return Trousse(
        modules=tuple(retenus),
        ecartes=tuple(ecartes),
        inconnus=tuple(inconnus),
        caracteres=total,
        plafond=plafond,
    )


def resume_capacites(
    trousse: Trousse,
    capacites: Mapping | None = None,
    *,
    disponibles: Iterable[str] = (),
) -> str:
    """Second bloc de prompt : ce qui existe, et qu'elle n'a pas sous la main.

    Nomme des **modules**, jamais des outils individuels. Deux raisons, et la
    seconde est un piège qu'il faut garder en tête à chaque retouche :

    1. un nom d'outil est un nom appelable ; le poser dans le prompt sans
       fournir la déclaration correspondante, c'est inviter le modèle à
       inventer un appel qui échouera en silence (M2 : la boucle d'outils ne
       remonte que ``block.name``, sans résultat ni ``is_error``) ;
    2. **on ne nomme aucun moyen d'« ouvrir » ces modules**, parce qu'aucun
       n'existe : il n'y a pas d'outil d'intention dans le dépôt aujourd'hui.
       Annoncer « demande-les et tu les auras » serait B3 d'un cran au-dessus —
       on ne remplacerait plus une capacité inexistante par un récit, on
       fabriquerait le récit d'une capacité de second ordre. La seule sortie
       honnête est celle qu'elle a vraiment : le dire à voix haute.

    ``capacites`` accepte indifféremment ``{module: "phrase"}`` ou le
    ``{module: [ModuleCapability, ...]}`` que rend ``collect_capabilities()``,
    pour que le branchement côté moteur soit une ligne.
    """
    en_main = set(trousse.modules)
    ailleurs: list[str] = []
    for nom in list(trousse.ecartes) + [str(n).strip() for n in (disponibles or ())]:
        if nom and nom not in en_main and nom not in ailleurs:
            ailleurs.append(nom)

    if not ailleurs:
        return ""

    lignes = []
    for nom in ailleurs:
        libelle = _libelle_capacite(capacites, nom)
        lignes.append(f"- {nom} : {libelle}" if libelle else f"- {nom}")

    return (
        "--- CE QUI EXISTE AILLEURS ---\n"
        "Ces parties de toi existent mais ne sont pas ouvertes pendant ce "
        "tour :\n"
        + "\n".join(lignes)
        + "\nTu ne peux pas t'en servir maintenant. Si c'est de l'une d'elles "
        "que tu as besoin, dis-le franchement plutôt que de raconter que tu "
        "l'as fait."
    )


# ── Détails défensifs ─────────────────────────────────────────────────────


def _tension(drives: Mapping | None, nom: str) -> float:
    """La tension d'une pulsion, quelle que soit la forme du dictionnaire.

    Accepte les clés ``DriveKind`` comme les chaînes, et les valeurs
    ``DriveState`` comme les flottants — le moteur peut donc passer
    ``drive_engine.states`` sans conversion, ce qui évite une transcription
    de plus entre ce qui est mesuré et ce qui décide.
    """
    if not drives:
        return 0.0
    for cle, valeur in drives.items():
        etiquette = getattr(cle, "value", cle)
        if str(etiquette).strip().lower() != nom:
            continue
        try:
            return float(getattr(valeur, "tension", valeur))
        except (TypeError, ValueError) as exc:
            # Une pulsion illisible vaut « au repos » : elle n'élargit rien.
            # L'inverse (élargir dans le doute) coûte du prompt sur le chemin
            # le plus cher du moteur.
            degradations.record("conscience: trousse — tension de pulsion", exc)
            return 0.0
    return 0.0


def _poids_de(poids: Callable[[str], int], nom: str) -> int:
    """Le poids d'un module, ou ``-1`` si la mesure a échoué.

    Le sentinel négatif est délibéré : ``0`` voudrait dire « ne coûte rien »
    et ferait passer sous le plafond un module dont on ne sait précisément
    rien. La mesure traverse le registre de modules, donc elle peut lever
    (module arrêté, ``return_tools`` cassé) — et la boucle de décision n'a
    aucun superviseur.
    """
    try:
        return int(poids(nom))
    except Exception as exc:
        degradations.record("conscience: trousse — poids d'un module", exc)
        return -1


def _libelle_capacite(capacites: Mapping | None, nom: str) -> str:
    """Une ligne lisible pour un module, depuis l'une ou l'autre des formes."""
    if not capacites:
        return ""
    try:
        valeur = capacites.get(nom)
    except Exception as exc:
        degradations.record("conscience: trousse — libellé de capacité", exc)
        return ""
    if valeur is None:
        return ""
    if isinstance(valeur, str):
        return valeur.strip()[:120]
    try:
        descriptions = [
            str(getattr(cap, "description", cap)).strip()
            for cap in valeur
        ]
    except TypeError as exc:
        degradations.record("conscience: trousse — capacité non itérable", exc)
        return ""
    return ", ".join(d for d in descriptions if d)[:120]
