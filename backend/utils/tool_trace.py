"""Journal d'appels d'outils — savoir ce qu'un outil a *réellement* donné.

La boucle d'outils (``ai/providers/_tool_loop.py``) remonte ``calls``, une
liste de noms d'outils. C'est tout ce que le reste du moteur apprend d'un tour
outillé. Or ``_executer`` sait déjà distinguer trois issues — outil
inconnu, handler qui lève, handler qui répond ``isError`` — et les trois
repartent vers le modèle sous forme de ``tool_result`` marqué ``is_error``,
puis **s'effacent** : en sortie de boucle, trois outils qui plantent et trois
outils qui réussissent produisent le même ``["memory_search", …]``.

Ce que ça casse en aval, mesuré : la curiosité est soulagée par le *nom* de
l'outil appelé, pas par ce qu'il a rendu, donc trois échecs consécutifs
apaisent exactement comme trois réussites — et l'acte suivant est reporté
d'autant. Un outil cassé depuis le boot est indiscernable d'un outil qui
tourne. C'est la même maladie que le registre de dégradations soigne pour les
échecs avalés, ici pour les échecs *rendus au modèle*.

Ce module est donc le carnet : le site d'exécution y note une ligne par
appel, et l'appelant, tout en haut de la pile, lit le carnet.

**Zéro import du projet**, au même titre que ``utils/eventbus.py`` n'importe
jamais ``modules`` : ``modules/collectors.py`` devra importer ceci, et une
dépendance vers ``conscience`` ou ``configs`` retournerait le sens des
flèches. Conséquence assumée, sur le modèle de l'``EventBus`` : le module
compte ses propres ratés (``notes_perdues``) au lieu d'appeler
``degradations.record`` — un compteur local vaut mieux qu'une dépendance
inversée, et l'information reste lisible au même endroit que le reste.

Transport : un ``ContextVar``. La raison est précise. Le journal doit
traverser un ``await`` (la boucle d'outils est asynchrone), rester séparé
entre deux tâches concurrentes (les six boucles de fond appellent des outils
pendant qu'un tour de conversation en appelle), et survivre à un saut vers un
thread d'exécuteur (``asyncio.to_thread`` recopie le contexte courant). Une
variable de module échouerait sur les deux derniers points, un paramètre
explicite obligerait à réécrire la signature de tout ce qui sépare la boucle
d'outils de son appelant.

Le journal lui-même est **mutable et partagé** : ce que le thread d'exécuteur
y ajoute revient à l'appelant, alors qu'un ``ContextVar`` réaffecté dans la
copie de contexte, lui, ne remonterait jamais.
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator

logger = logging.getLogger(__name__)

#: Nombre d'appels dont on garde le détail dans un journal.
#:
#: Borne de mémoire, pas de comptabilité : au-delà, les *compteurs*
#: continuent (voir ``JournalOutils.total``). Un tour outillé pathologique —
#: le modèle qui rappelle le même outil à chaque itération jusqu'à
#: ``max_turns`` — ne doit pas faire grossir un objet qui vit le temps d'un
#: tour, mais il doit rester visible dans le résumé.
MAX_APPELS_RETENUS = 32

#: Taille maximale d'un extrait conservé (caractères).
#:
#: Un extrait sert à *reconnaître* l'échec, pas à le rejouer : un
#: ``memory_search`` qui rend 40 ko de souvenirs n'a aucune raison d'être
#: recopié dans un journal que trois écrans vont afficher. La trace complète,
#: elle, part déjà au modèle dans le ``tool_result``.
MAX_EXTRAIT = 240

#: Extrait affiché *dans la ligne de résumé* — plus court encore, parce que
#: cette ligne-là finit dans un log ou dans une cellule de tableau.
MAX_EXTRAIT_RESUME = 120

#: Nombre d'outils nommés dans la ligne de résumé.
MAX_NOMMES_RESUME = 3

#: Ce que dit un journal ouvert où rien ne s'est passé. Distinct de la chaîne
#: vide, qui est ce que rend un *absence* de journal : « elle n'a appelé aucun
#: outil » et « personne ne regardait » ne sont pas le même fait.
AUCUN_APPEL = "aucun appel d'outil"


def borne_extrait(valeur: Any, maxi: int = MAX_EXTRAIT) -> str:
    """Rend ``valeur`` en une ligne d'au plus ``maxi`` caractères. Ne lève pas.

    Deux normalisations, toutes deux motivées par la destination : les blancs
    sont écrasés parce qu'un extrait finit dans une ligne de log (un ``\\n``
    au milieu casse le grep autant que la lecture), et la coupe est marquée
    par « … » parce qu'un extrait tronqué muet se lit comme une réponse
    complète — exactement le genre de confusion que ce module existe pour
    supprimer.
    """
    try:
        texte = valeur if isinstance(valeur, str) else str(valeur)
        texte = " ".join(texte.split())
        borne = maxi if maxi > 0 else 0
        if len(texte) > borne:
            return texte[: max(borne - 1, 0)] + "…"
        return texte
    except Exception:  # pragma: no cover - un __str__ hostile ne casse rien
        return "<extrait illisible>"


def _flottant(valeur: Any) -> float:
    """Coercition totale vers un flottant positif. Ne lève pas."""
    try:
        nombre = float(valeur)
    except (TypeError, ValueError):
        return 0.0
    if nombre != nombre or nombre in (float("inf"), float("-inf")):  # NaN / inf
        return 0.0
    return round(nombre, 1) if nombre > 0.0 else 0.0


@dataclass(frozen=True)
class AppelOutil:
    """Une ligne de journal : ce qu'un appel d'outil a donné.

    Gelée parce qu'une ligne de journal est un *constat* : une fois notée,
    elle décrit un appel terminé, et rien en aval n'a de raison de la
    réécrire. Les deux consommateurs prévus (le résumé, un panneau) lisent.

    """

    nom: str
    ok: bool = True
    extrait: str = ""
    ms: float = 0.0

    def __post_init__(self) -> None:
        # La borne est appliquée à la *construction*, pas à l'écriture dans
        # le journal : sinon un appelant qui garde l'objet (le site
        # d'exécution veut souvent le relire) tiendrait les 40 ko que le
        # journal a refusés, et la borne ne bornerait que l'affichage.
        object.__setattr__(self, "nom", borne_extrait(self.nom, 120))
        object.__setattr__(self, "ok", bool(self.ok))
        object.__setattr__(self, "extrait", borne_extrait(self.extrait))
        object.__setattr__(self, "ms", _flottant(self.ms))

    def as_dict(self) -> dict[str, Any]:
        return {
            "nom": self.nom,
            "ok": self.ok,
            "extrait": self.extrait,
            "ms": self.ms,
        }

    def ligne(self) -> str:
        """Une ligne lisible : ``memory_search ✗ (12 ms) base verrouillée``."""
        marque = "✓" if self.ok else "✗"
        morceaux = [f"{self.nom} {marque}"]
        if self.ms:
            morceaux.append(f"({self.ms:g} ms)")
        extrait = borne_extrait(self.extrait, MAX_EXTRAIT_RESUME)
        if extrait:
            morceaux.append(extrait)
        return " ".join(morceaux)


class JournalOutils:
    """Ce qu'une portion d'exécution a appelé, et ce que ça a donné.

    Verrouillé, parce que le producteur et le lecteur ne sont pas forcément
    sur le même thread : un handler d'outil synchrone tourne volontiers dans
    un exécuteur (``sync_to_async`` sérialise sur *un* thread partagé) pendant
    que la boucle d'événements, elle, lit le journal pour le poser dans un
    log. Un ``list.append`` est atomique sous le GIL mais les compteurs qui
    l'accompagnent ne le sont pas ensemble, et c'est précisément la cohérence
    entre « combien » et « lesquels » qui fait la valeur du carnet.
    """

    def __init__(self, *, max_appels: int = MAX_APPELS_RETENUS) -> None:
        self._max_appels = max(0, int(max_appels))
        self._appels: list[AppelOutil] = []
        self._lock = threading.Lock()
        self._total = 0
        self._ok = 0
        self._echecs = 0
        self._ms = 0.0
        self._tronques = 0
        #: Notes perdues faute d'objet exploitable. Compté ici plutôt que
        #: renvoyé vers le registre de dégradations, qui obligerait ce module
        #: à importer le projet (voir l'en-tête).
        self.notes_perdues = 0

    # ── Écriture ──────────────────────────────────────────────────

    def noter(self, appel: AppelOutil) -> bool:
        """Enregistre ``appel``. Ne lève jamais ; rend s'il a été retenu.

        « Retenu » veut dire *dans le détail* : au-delà de la borne, les
        compteurs bougent quand même. La borne limite la mémoire, jamais
        l'arithmétique — un résumé qui dirait « 32 appels » alors qu'il y en a
        eu 200 mentirait sur le seul chiffre pour lequel on le lit.
        """
        try:
            with self._lock:
                self._total += 1
                if appel.ok:
                    self._ok += 1
                else:
                    self._echecs += 1
                self._ms += appel.ms
                if len(self._appels) < self._max_appels:
                    self._appels.append(appel)
                    return True
                self._tronques += 1
                return False
        except Exception as exc:  # pragma: no cover - instrumentation muette
            self.notes_perdues += 1
            logger.debug("tool_trace: note perdue (%s)", exc)
            return False

    # ── Lecture ───────────────────────────────────────────────────

    @property
    def appels(self) -> tuple[AppelOutil, ...]:
        with self._lock:
            return tuple(self._appels)

    @property
    def total(self) -> int:
        """Appels notés, bornage compris."""
        with self._lock:
            return self._total

    @property
    def reussites(self) -> int:
        with self._lock:
            return self._ok

    @property
    def echecs(self) -> int:
        with self._lock:
            return self._echecs

    @property
    def tronques(self) -> int:
        """Appels comptés dont le détail n'a pas été gardé."""
        with self._lock:
            return self._tronques

    @property
    def ms(self) -> float:
        with self._lock:
            return round(self._ms, 1)

    def __len__(self) -> int:
        return self.total

    def __bool__(self) -> bool:
        # Sans ça, ``if journal:`` suivrait ``__len__`` et un journal ouvert
        # mais vide passerait pour absent — la distinction que ce module
        # tient à garder (voir AUCUN_APPEL).
        return True

    def rate(self) -> bool:
        """A-t-elle appelé au moins un outil qui a échoué ?"""
        return self.echecs > 0

    def resume(self) -> str:
        """Une ligne : les compteurs, puis ce qu'il faut savoir.

        Les échecs sont nommés en premier et avec leur extrait, parce que
        c'est la seule chose qu'on vient chercher ici. Quand tout est passé,
        la ligne nomme quand même les outils : « elle a cherché en mémoire »
        et « elle n'a rien fait » se lisent alors différemment dans un log,
        ce qui est le second usage du carnet.
        """
        with self._lock:
            total, ok, echecs = self._total, self._ok, self._echecs
            appels = list(self._appels)
            tronques, ms = self._tronques, self._ms
        if total == 0:
            return AUCUN_APPEL

        tete = f"{total} appel{'s' if total > 1 else ''}"
        tete += f" : {ok} ok, {echecs} échec{'s' if echecs > 1 else ''}"
        if ms:
            tete += f" en {round(ms, 1):g} ms"
        if tronques:
            tete += f" ({tronques} non détaillé{'s' if tronques > 1 else ''})"

        if echecs:
            details = [a.ligne() for a in appels if not a.ok][:MAX_NOMMES_RESUME]
        else:
            vus: list[str] = []
            for appel in appels:
                if appel.nom not in vus:
                    vus.append(appel.nom)
            details = vus[:MAX_NOMMES_RESUME]
        if not details:
            return tete
        return f"{tete} — {', '.join(details)}"

    def as_dict(self) -> dict[str, Any]:
        """Forme destinée à un écran (panneau de module, page santé)."""
        with self._lock:
            appels = [a.as_dict() for a in self._appels]
            charge = {
                "total": self._total,
                "ok": self._ok,
                "echecs": self._echecs,
                "tronques": self._tronques,
                "ms": round(self._ms, 1),
                "notes_perdues": self.notes_perdues,
            }
        charge["appels"] = appels
        charge["resume"] = self.resume()
        return charge


#: Le journal de la portion d'exécution courante, s'il y en a un.
#:
#: ``default=None`` et pas un journal jetable : « personne ne regarde » doit
#: rester observable, sinon un site qui note hors de tout journal croit avoir
#: tracé quelque chose que personne ne lira jamais.
_journal_courant: ContextVar[JournalOutils | None] = ContextVar(
    "tool_trace_journal", default=None,
)


def journal_courant() -> JournalOutils | None:
    """Le journal ouvert le plus proche, ou ``None``."""
    try:
        return _journal_courant.get()
    except Exception:  # pragma: no cover - un ContextVar ne lève pas ici
        return None


@contextmanager
def journal_outils(*, max_appels: int = MAX_APPELS_RETENUS) -> Iterator[JournalOutils]:
    """Ouvre un journal pour la durée du bloc, et rend le précédent en sortie.

    La restauration passe par le **jeton** de ``ContextVar.set`` et non par un
    ``set(None)`` : un appel imbriqué (la boucle d'outils rentre dans un outil
    qui rappelle le modèle — ``files_analyze_image`` le fait) doit rendre son
    journal à son appelant, pas éteindre la trace pour tout le tour. Le
    ``set(None)`` marchait tant qu'il n'y avait qu'un niveau, ce qui est
    exactement la forme de bug qu'on ne voit qu'en production.
    """
    journal = JournalOutils(max_appels=max_appels)
    jeton = _journal_courant.set(journal)
    try:
        yield journal
    finally:
        try:
            _journal_courant.reset(jeton)
        except ValueError:  # pragma: no cover - sortie dans un autre contexte
            # Le jeton appartient au contexte où le ``set`` a eu lieu ; si le
            # bloc se termine ailleurs (une tâche qui a hérité du contexte),
            # le restaurer n'a pas de sens. On efface plutôt que de laisser
            # remonter une exception depuis un ``finally``.
            _journal_courant.set(None)


def noter(appel: AppelOutil) -> bool:
    """Note ``appel`` dans le journal courant. Ne lève **jamais**.

    Rend ``False`` quand il n'y a pas de journal ouvert, ce qui est le cas
    normal et pas une anomalie : la boucle d'outils tourne aussi pour des
    appelants qui ne tracent rien (un tour de conversation ordinaire), et
    payer une exception — ou pire, un journal implicite qui grossit sans
    lecteur — pour ce cas-là serait absurde. C'est aussi la propriété qui rend
    l'instrumentation sûre à poser sur le chemin chaud : rien de ce qui suit
    ne peut coûter sa réponse à quelqu'un.
    """
    journal = journal_courant()
    if journal is None:
        return False
    try:
        return journal.noter(appel)
    except Exception as exc:  # pragma: no cover - ceinture et bretelles
        logger.debug("tool_trace: note ignorée (%s)", exc)
        return False


def noter_appel(
    nom: str,
    *,
    ok: bool = True,
    extrait: Any = "",
    ms: float = 0.0,
) -> bool:
    """Forme courte de ``noter`` pour un site d'exécution. Ne lève jamais.

    Existe pour que le site d'exécution ait une seule ligne à ajouter par issue
    plutôt qu'une construction d'objet dans un ``except`` — un site qui doit
    déjà rendre une erreur au modèle ne doit pas gagner une seconde raison de
    se tromper.
    """
    try:
        appel = AppelOutil(
            nom=nom, ok=ok, extrait=extrait, ms=ms,
        )
    except Exception as exc:  # pragma: no cover - __post_init__ est total
        logger.debug("tool_trace: appel non construit (%s)", exc)
        return False
    return noter(appel)


