"""Le nom affiché de tout ce que la console montre — à un seul endroit.

Une adresse devient le nom de la personne qui parle derrière (« Adrien »),
une sorte d'épisode un mot (« réponse »), un rôle, un processus, une voie, un
type d'événement, une raison de l'arbitre, un veto, une section du prompt :
une phrase française. Les clés techniques (``user_1``, ``memory.consolidate``,
``woken_at_night``) ne paraissent que dans le détail ou au survol.

Ce que déclarent les facultés est nommé par la composition (``Labels``,
``app/console.py``) ; ce qui appartient au noyau et au runtime (sortes,
issues, voies, rôles, événements du noyau) est nommé ici. Une clé sans
libellé reste lisible sous une forme générique, jamais un trou.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from mika.adapters.llm.config import ROLE_LABELS
from mika.contracts import identity as identity_c
from mika.inspector.catalog import Labels
from mika.kernel.inspect import Cell, Ref, Text, describe_error
from mika.runtime.boundary import Failed, call
from mika.vocab.episodes import GOAL_PREFIX, PROJECT_PREFIX, TASK_PREFIX, Kind, goal_of, project_of, task_of

#: les sortes d'épisodes, au singulier (« une réponse »)
KINDS: dict[str, str] = {
    Kind.REPLY: "réponse", Kind.INITIATIVE: "initiative", Kind.STEP: "séance de travail", Kind.MURMUR: "murmure",
    Kind.JOURNAL: "journal", Kind.DREAM: "rêve", Kind.NARRATIVE: "récit de soi", Kind.DECISION: "décision",
    Kind.TASK: "tâche silencieuse", Kind.WORK: "travail sur un projet", Kind.JOB: "exécution impersonnelle",
}
#: comment un épisode s'est terminé : (libellé, ton)
OUTCOMES: dict[str, tuple[str, str]] = {
    "done": ("terminé", "ok"), "abstained": ("s'est tue", "muted"), "superseded": ("supplanté", "warn"),
    "timeout": ("trop long", "danger"), "failed": ("échec", "danger"),
    "preempted": ("a cédé la place", "warn"), "interrupted": ("interrompu par un arrêt", "warn"),
    "cancelled": ("annulé", "muted"),
}
#: les voies d'exécution
LANES: dict[str, str] = {"conversation": "conversation", "background": "fond", "night": "nuit",
                         "arbitre": "arbitre"}
#: les événements du noyau et du runtime (ceux des facultés : ``Labels.events``)
EVENTS: dict[str, str] = {
    "kernel.boot": "Démarrage", "kernel.lease_acquired": "Bail pris", "kernel.lease_released": "Bail rendu",
    "kernel.params_changed": "Paramètres journalisés", "kernel.selected": "Choix de l'arbitre",
    "perception.received": "Message ou signal reçu", "episode.started": "Début d'épisode",
    "episode.utterance": "Parole", "episode.ended": "Fin d'épisode", "effect.proposed": "Demande pour sortir",
    "effect.resolved": "Décision d'un opérateur", "effect.executed": "Effet exécuté",
    "runtime.operated": "Action d'opérateur", "runtime.process_failed": "Échec d'un processus",
}
#: issues d'une action d'opérateur
OPERATED: dict[str, tuple[str, str]] = {"done": ("faite", "ok"), "refused": ("refusée", "warn"),
                                        "superseded": ("la situation avait changé", "warn"),
                                        "failed": ("échouée", "danger")}


def kind(value: str | None) -> str:
    return KINDS.get(str(value or ""), str(value or "épisode").lower())


#: les sortes d'épisodes qui, menées à bien, ont parlé (les autres ont travaillé, écrit, rêvé…)
SPEAKING: frozenset[str] = frozenset({Kind.REPLY, Kind.INITIATIVE, Kind.MURMUR})


def outcome(value: str | None, kind_: str | None = None) -> tuple[str, str]:
    """L'issue d'un épisode ; ``kind_`` donné, une parole menée à bien se dit « a parlé »."""
    if value == "done" and kind_ in SPEAKING:
        return "a parlé", "ok"
    return OUTCOMES.get(str(value or ""), (str(value or "—"), ""))


def role(value: str | None) -> str:
    return ROLE_LABELS.get(str(value or ""), str(value or "—"))


def lane(value: str | None) -> str:
    return LANES.get(str(value or ""), str(value or "—"))


def detail(text: str | None) -> str:
    """Un détail d'issue tel qu'un humain le lit : sans nom de classe Python en tête
    (« UnconfiguredRole: … », « TimeoutError() »)."""
    return describe_error((text or "").strip())


def humanize(key: str) -> str:
    """``mail_draft`` → « mail draft » : la forme générique d'une clé sans libellé."""
    return key.replace("_", " ").replace(".", " · ").strip() or key


class Names:
    """Les noms d'une console : ce qui dépend de son noyau (les personnes, ses facultés)."""

    def __init__(self, kernel: Any, labels: Labels | None = None) -> None:
        self.kernel = kernel
        self.labels = labels or Labels()
        self._frame: tuple[int, Any] | None = None

    # ── le moment ──
    def frame(self) -> Any:
        head = self.kernel.mind.head
        if self._frame is None or self._frame[0] != head:
            self._frame = (head, self.kernel.mind.frame())
        return self._frame[1]

    def _fact(self, key: Any) -> Any:
        """Un fait, ou ``None`` s'il n'existe pas dans cette composition ou si son fournisseur échoue :
        nommer ne casse jamais une page (on ouvre la console quand quelque chose ne va pas)."""
        got = call(self.frame().get, key, label="nom affiché")
        return None if isinstance(got, Failed) else got

    # ── les gens ──
    def person_of(self, handle: str) -> str:
        """La clé de la personne qui parle derrière une adresse (l'adresse elle-même sinon)."""
        got = self._fact(identity_c.PERSON(handle)) if handle else None
        return str(got or handle)

    def name_of(self, handle: str) -> str:
        """Le nom sous lequel elle connaît qui parle derrière cette adresse (vide : inconnu)."""
        if not handle:
            return ""
        person = self.person_of(handle)
        for key in dict.fromkeys((person, handle)):
            view = self._fact(identity_c.IDENTITY(key))
            name = getattr(view, "name", "") if view is not None else ""
            if name:
                return str(name)
        if person.startswith("name:"):
            return person[5:].strip().title()
        return ""

    def who(self, target: str | None) -> str:
        """À qui (ou à quoi) s'adresse un épisode, une ligne de l'arbitre : un nom, jamais une clé."""
        if not target or target == "none":
            return "personne en particulier"
        if target == "any":
            return "n'importe qui de présent"
        if target.startswith(GOAL_PREFIX):
            return f"le but n° {goal_of(target) or target[len(GOAL_PREFIX):]}"
        if target.startswith(PROJECT_PREFIX):
            return f"le projet n° {project_of(target) or target[len(PROJECT_PREFIX):]}"
        if target.startswith(TASK_PREFIX):
            got = task_of(target)
            return f"une tâche ({self.faculty(got[0])})" if got else "une tâche"
        return self.name_of(target) or target

    def who_cell(self, target: str | None) -> Cell:
        """``who`` en cellule : un lien vers la fiche (personne, but, projet), la clé au survol."""
        label = self.who(target)
        if not target or target in ("none", "any"):
            return Text(label, "muted")
        if (n := goal_of(target)) is not None:
            return Ref.subject("goal", str(n), label)
        if (n := project_of(target)) is not None:
            return Ref.subject("project", str(n), label)
        if target.startswith(TASK_PREFIX):
            return Text(label, hint=target)
        return Ref.subject("person", self.person_of(target), label)

    def handles_named(self, text: str, search: Callable[[str, str, int], Sequence[Any]] | None = None
                      ) -> tuple[str, ...]:
        """Les adresses de qui l'on désigne par un nom tapé (« Adrien ») ou par une clé exacte
        (« user_1 ») — pour un filtre « vers » ; vide : personne ne correspond."""
        text = text.strip()
        if not text:
            return ()
        found: dict[str, None] = {}
        folded = text.casefold()
        if getattr(self._fact(identity_c.IDENTITY(text)), "known", False):
            found[text] = None
        for h in self._fact(identity_c.HANDLES(text)) or ():  # une clé de personne (le lien depuis sa fiche)
            found[str(h)] = None
        for person in [f.key for f in (search("person", text, 20) if search is not None else ())]:
            name = self.name_of(person)
            if name and folded not in name.casefold() and folded != person.casefold():
                continue
            found[person] = None
            for h in self._fact(identity_c.HANDLES(person)) or ():
                found[str(h)] = None
        return tuple(found)

    # ── ce que déclarent les facultés ──
    def faculty(self, owner: str) -> str:
        return self.labels.faculties.get(owner, owner)

    def section(self, key: str) -> str:
        """Une section du prompt : ce qu'elle lui montre."""
        if key in self.labels.sections:
            return self.labels.sections[key]
        spec = next((s for f in self.kernel.registry.faculties.values() for s in f.sections if s.key == key), None)
        title = getattr(spec, "title", None) if spec is not None else None
        if title:
            return title[:1] + title[1:].lower()
        return humanize(key)

    def reason(self, owner: str, code: str) -> str:
        """Une raison de l'arbitre (une preuve) : ce qui pousse à agir."""
        return self.labels.reasons.get(code) or f"{self.faculty(owner)} · {humanize(code)}"

    def veto(self, owner: str, code: str) -> str:
        """Un veto : ce qui l'en empêche, en mots."""
        return self.labels.vetoes.get(code) or f"{self.faculty(owner)} · {humanize(code)}"

    def process(self, name: str) -> str:
        if name in self.labels.processes:
            return self.labels.processes[name]
        owner, _, rest = name.partition(".")
        return f"{self.faculty(owner)} · {humanize(rest or name)}"

    def event(self, type_name: str) -> str:
        if type_name in EVENTS:
            return EVENTS[type_name]
        if type_name in self.labels.events:
            return self.labels.events[type_name]
        owner, _, rest = type_name.partition(".")
        return f"{self.faculty(owner)} · {humanize(rest or type_name)}"

    def action(self, key: str) -> str:
        """Une action d'opérateur (« projects.creer ») : son titre, ou celle de la console."""
        spec = self.kernel.registry.actions.get(key)
        if spec is not None:
            return spec.title
        if key.startswith("cli."):  # la ligne de commande : une action de la console, ou l'oubli
            rest = key[len("cli."):]
            inner = self.kernel.registry.actions.get(rest)
            if inner is not None:
                return f"{inner.title} (ligne de commande)"
            if rest.startswith("oublier"):
                kind = self.kernel.registry.subjects.get(rest.partition(".")[2])
                return f"Oublier{' · ' + kind.label.lower() if kind is not None else ''} (ligne de commande)"
            return f"{self.action(rest)} (ligne de commande)"
        if key.startswith("console."):
            parts = key.split(".")
            what = {"oublier": "Oublier", "reglages": "Réglages", "parametres": "Paramètres",
                    "sorties": "File de sortie"}.get(parts[1] if len(parts) > 1 else "", humanize(key))
            return f"{what} · {' · '.join(parts[2:])}" if len(parts) > 2 else what
        return humanize(key)

    def capability(self, name: str) -> str:
        spec = getattr(self.kernel.registry, "capabilities", {}).get(name)
        return getattr(spec, "description", "") or humanize(name)

    def resource(self, res: str) -> str:
        """Une ressource réservée par un bail : « la parole avec Adrien », « l'atelier du but n° 3 »."""
        head, _, rest = res.partition(":")
        if head == "floor":
            return f"la parole avec {self.who(rest)}"
        if head == "workshop":
            if rest.startswith("projet-"):
                return f"l'atelier du projet n° {rest[7:]}"
            return f"l'atelier du but n° {rest}"
        return res

    def arbiter_row(self, kind_: str, target: str) -> str:
        """Une ligne de la table de l'arbitre : « initiative envers Adrien »."""
        return f"{kind(kind_)} envers {self.who(target)}" if target not in ("", "none") else kind(kind_)
