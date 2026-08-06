"""Formulaires des projets — les seuls objets de l'interface qu'on **crée**.

Le reste de GestionSystème observe des états produits par les boucles de fond
ou édite la configuration déclarée au registre. Un projet, lui, se saisit
entièrement : c'est un engagement de travail confié à Mika.

Ce sont des ``ModelForm`` Django ordinaires, pas le moteur piloté par
``ConfigItem`` : celui-ci décrit des réglages plats du registre, alors qu'ici
on a un vrai modèle ORM avec des relations, des contraintes et des champs
JSON. Réutiliser le moteur de configuration aurait voulu dire décrire un
modèle Django dans un vocabulaire qui n'est pas fait pour ça.

Trois règles que le formulaire ajoute au modèle :

1. **Une cadence invalide est refusée.** ``schedule.parse_rule`` ne lève
   jamais — une règle qu'il ne reconnaît pas devient « manuel ». C'est le bon
   choix pour du texte produit par un LLM, mais depuis un formulaire cela
   signifie qu'une faute de frappe (``interval:5min`` au lieu de ``5m``)
   donne un projet qui n'avancera plus jamais, sans rien dire.
2. **Les modules autorisés sont une liste fermée**, cochée parmi les modules
   enregistrés. Le champ est une liste blanche stricte : un nom mal tapé
   n'ouvre pas un accès, il en ferme un, et silencieusement.
3. **``next_run_at`` est recalculé** dès que la cadence change, sinon un
   projet repasse en attente jusqu'au prochain passage du lanceur.
"""
from __future__ import annotations

from django import forms
from django.utils import timezone

from projects import schedule
from projects.models import Project, ProjectTask


class LineListField(forms.CharField):
    """Champ JSON de type liste, saisi une valeur par ligne.

    Le modèle stocke une ``JSONField(default=list)``. Une saisie ligne par
    ligne est ce qui se rapproche le plus de la lecture qu'on en fait (une
    consigne par point), et évite d'exposer une syntaxe JSON dans un
    formulaire d'usage courant.
    """

    widget = forms.Textarea(attrs={"rows": 4})

    def prepare_value(self, value):
        if isinstance(value, (list, tuple)):
            return "\n".join(str(v) for v in value)
        return value

    def to_python(self, value) -> list[str]:
        if isinstance(value, (list, tuple)):
            return [str(v).strip() for v in value if str(v).strip()]
        if not value:
            return []
        return [ligne.strip() for ligne in str(value).splitlines() if ligne.strip()]


def _modules_disponibles() -> list[tuple[str, str]]:
    """Modules enregistrés, systèmes compris.

    Les modules d'infrastructure (``files``, ``memory_tools``…) n'ont pas
    d'espace dans l'interface mais restent des cibles légitimes pour un
    projet : ce sont eux qui portent les outils.
    """
    try:
        from modules.manager import module_manager
        noms = sorted(info["name"] for info in module_manager.list_all())
    except Exception:
        noms = []
    return [(n, n) for n in noms]


class ProjectForm(forms.ModelForm):
    keywords = LineListField(
        required=False, label="Mots-clés",
        help_text="Un par ligne. Servent à détecter qu'un tour de conversation concerne ce projet.",
    )
    instructions = LineListField(
        required=False, label="Consignes",
        help_text="Une par ligne. Directives positives, injectées dans le prompt quand le projet est actif.",
    )
    out_of_scope = LineListField(
        required=False, label="Hors périmètre",
        help_text="Une par ligne. Sujets ou actions explicitement interdits.",
    )
    resource_paths = LineListField(
        required=False, label="Chemins",
        help_text="Un par ligne.",
    )
    contacts = LineListField(
        required=False, label="Contacts",
        help_text="Un par ligne. Adresses ou identifiants dans le périmètre.",
    )
    allowed_modules = forms.MultipleChoiceField(
        required=False, label="Modules autorisés",
        choices=_modules_disponibles,
        widget=forms.SelectMultiple(attrs={"size": 8}),
        help_text="Périmètre annoncé au lanceur : son passage est texte seul, "
                  "il ne les appelle pas lui-même — il peut seulement proposer "
                  "une action qui les utilise. Ne rien sélectionner signifie "
                  "« aucun outil ».",
    )

    class Meta:
        model = Project
        fields = (
            "title", "description", "keywords",
            "origin", "status", "priority", "owner",
            "tone_directive", "emotion_policy",
            "instructions", "out_of_scope",
            "requires_approval",
            "allowed_modules", "resource_paths", "contacts",
            "schedule_rule", "monthly_token_budget",
        )
        labels = {
            "title": "Titre",
            "description": "Description",
            "origin": "Origine",
            "status": "État",
            "priority": "Priorité",
            "owner": "Confié par",
            "tone_directive": "Ton imposé",
            "emotion_policy": "Politique émotionnelle",
            "requires_approval": "Exiger mon accord avant tout effet de bord",
            "schedule_rule": "Cadence",
            "monthly_token_budget": "Budget mensuel (jetons)",
        }
        help_texts = {
            "tone_directive": "Comment écrire pendant ce projet. Ex. « Langage soutenu, factuel, pas d'abréviations ».",
            "emotion_policy": (
                "« off » est le défaut : pendant un tour qui concerne ce projet, "
                "Mika supprime son étiquette d'émotion, son bloc de variabilité "
                "et l'impulsion affective envers la personne. C'est le mode "
                "professionnel — le rallumer est un choix explicite."
            ),
            "requires_approval": "Les actions à effet de bord sont mises en file au lieu d'être exécutées.",
            "monthly_token_budget": "0 = illimité. Un dépassement défère le prochain passage du lanceur.",
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "tone_directive": forms.Textarea(attrs={"rows": 2}),
            "schedule_rule": forms.TextInput(attrs={
                "placeholder": "manual · interval:30m · cron:0 9 * * MON-FRI · idle:30m · event:email.received",
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["title"].required = True
        # Seules les entités de type personne peuvent posséder un projet ;
        # le modèle le déclare via ``limit_choices_to``, on le reflète ici
        # pour que la liste déroulante ne propose pas le reste.
        self.fields["owner"].required = False
        self.fields["owner"].empty_label = "— personne —"
        self.fields["schedule_rule"].required = False
        self.fields["schedule_rule"].help_text = (
            "Vide ou « manual » : le projet n'avance que sur demande. "
            "Sinon : interval:30m · cron:0 9 * * MON-FRI · idle:30m · event:email.received"
        )

    def clean_schedule_rule(self) -> str:
        brut = (self.cleaned_data.get("schedule_rule") or "").strip()
        if not brut or brut.lower() == "manual":
            return brut

        regle = schedule.parse_rule(brut)
        if regle.kind == "none":
            # parse_rule retombe silencieusement sur « manuel ». Accepter
            # cela ici donnerait un projet qui n'avance plus jamais sans que
            # rien ne le signale.
            raise forms.ValidationError(
                "Cadence non reconnue. Formes acceptées : « manual », "
                "« interval:30m » (s/m/h/d), « cron:0 9 * * MON-FRI », "
                "« idle:30m », « event:email.received »."
            )
        return brut

    def save(self, commit: bool = True) -> Project:
        projet = super().save(commit=False)

        # Recalculé à chaque enregistrement : sans cela, changer la cadence
        # laisse l'ancienne échéance en place jusqu'au prochain passage.
        regle = projet.schedule_rule or ""
        if schedule.parse_rule(regle).kind in ("interval", "cron"):
            try:
                projet.next_run_at = schedule.compute_next_run(regle, timezone.now())
            except Exception:
                projet.next_run_at = None
        elif schedule.parse_rule(regle).kind == "idle":
            # Une règle « idle » exige aussi que l'échéance soit passée, sinon
            # elle se déclencherait à chaque passage du lanceur une fois la
            # fenêtre atteinte.
            projet.next_run_at = timezone.now()
        else:
            projet.next_run_at = None

        if commit:
            projet.save()
        return projet


class ProjectTaskForm(forms.ModelForm):
    class Meta:
        model = ProjectTask
        fields = ("description", "status", "order", "result", "blocked_reason")
        labels = {
            "description": "Description",
            "status": "État",
            "order": "Ordre",
            "result": "Résultat",
            "blocked_reason": "Motif de blocage",
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 2}),
            "result": forms.Textarea(attrs={"rows": 2}),
            "blocked_reason": forms.TextInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["description"].required = True
        # ``order`` est numéroté automatiquement à la création : l'exiger
        # dans le formulaire d'ajout rapide obligerait à connaître le rang
        # suivant pour ajouter une simple ligne.
        for nom in ("result", "blocked_reason", "order"):
            self.fields[nom].required = False
