"""Formulaires de configuration rendus par le serveur.

Le registre (``configs/registry.py``) décrit déjà chaque réglage : type,
libellé, bornes, choix, caractère sensible. Ce module transforme cette
description en champs HTML, et relit une soumission dans l'autre sens.

L'ancienne interface faisait le même travail en 763 lignes de JavaScript qui
reconstruisaient les formulaires dans le navigateur à partir d'un schéma JSON.
Le déplacer côté serveur supprime trois problèmes d'un coup :

- **la validation n'est plus optionnelle** — on passe forcément par
  ``config_service.set()``, qui coerce, valide et journalise ;
- **le secret ne descend jamais** — un mot de passe ou une clé d'API n'est
  pas envoyé au navigateur, même masqué : le champ part vide et un champ vide
  signifie « inchangé » ;
- **il n'y a plus de jeton CSRF à recoller** à la main sur des ``fetch``, le
  formulaire porte ``{% csrf_token %}``.

Convention de nommage : chaque champ affiché émet aussi un ``__champ`` caché
portant sa clé. La soumission dit donc explicitement *quels réglages étaient à
l'écran*, ce qui règle deux cas que la seule lecture de ``request.POST`` ne
distingue pas — une case décochée (absente du POST, mais bien affichée, donc
c'est un ``False`` à enregistrer) et un réglage simplement absent du
formulaire (qu'il ne faut pas toucher).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from configs.registry import registry
from configs.service import ValidationError, config_service
from configs.types import ConfigItem, choice_options, choice_values

logger = logging.getLogger(__name__)

FIELD_MARKER = "__champ"
UNSET_MARKER = "__reinitialiser"

# type déclaré → gabarit de widget
WIDGETS = {
    "str": "text",
    "text": "textarea",
    "yaml_block": "textarea",
    "int": "number",
    "float": "number",
    "bool": "checkbox",
    "secret": "secret",
    "select": "select",
    "multiselect": "multiselect",
    "list": "list",
}


@dataclass
class BoundField:
    """Un réglage prêt à être affiché."""
    item: ConfigItem
    value: Any = None
    error: str = ""
    submitted: bool = False

    @property
    def name(self) -> str:
        return self.item.key

    @property
    def widget(self) -> str:
        return WIDGETS.get(self.item.type, "text")

    @property
    def label(self) -> str:
        from GestionSysteme.formatting import humanize_key
        return self.item.label or humanize_key(self.item.key)

    @property
    def is_secret(self) -> bool:
        return self.item.type == "secret" or self.item.sensitive

    @property
    def has_secret_value(self) -> bool:
        """Un secret est-il déjà enregistré ? (sans jamais le révéler)"""
        return bool(isinstance(self.value, dict) and self.value.get("has_value"))

    @property
    def secret_preview(self) -> str:
        return str(self.value.get("preview", "")) if isinstance(self.value, dict) else ""

    @property
    def text_value(self) -> str:
        """Valeur telle qu'elle doit apparaître dans un champ texte."""
        if self.is_secret:
            return ""            # jamais réaffiché
        v = self.value
        if v is None:
            return ""
        if isinstance(v, bool):
            return "1" if v else ""
        if isinstance(v, (list, tuple)):
            return ", ".join(str(x) for x in v)
        return str(v)

    @property
    def checked(self) -> bool:
        return bool(self.value)

    @property
    def selected(self) -> list[str]:
        v = self.value
        if isinstance(v, (list, tuple)):
            return [str(x) for x in v]
        return [str(v)] if v not in (None, "") else []

    @property
    def choices(self) -> tuple:
        return choice_values(self.item.choices)

    @property
    def options(self) -> list[tuple[str, str]]:
        """Couples (valeur, libellé) — même forme que pour un champ de ligne,
        pour que le gabarit de champ n'ait qu'un seul chemin de rendu."""
        return choice_options(self.item.choices)

    @property
    def step(self) -> str:
        return "1" if self.item.type == "int" else "any"

    @property
    def is_default(self) -> bool:
        """La valeur affichée est-elle celle du schéma ?

        Sert à marquer les réglages jamais touchés — utile pour distinguer
        « réglé à 0,5 » de « laissé à 0,5 » quand on cherche pourquoi une
        installation se comporte autrement qu'une autre.
        """
        if self.is_secret:
            return not self.has_secret_value
        return self.value == self.item.default


@dataclass
class FormGroup:
    """Sous-titre à l'intérieur d'une section (champ ``group`` d'un item)."""
    label: str
    fields: list[BoundField] = field(default_factory=list)


@dataclass
class ScalarForm:
    """Les réglages scalaires d'une section."""
    fields: list[BoundField] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    saved: list[str] = field(default_factory=list)
    # message d'erreur par clé, reporté sur le champ après rechargement
    errors_by_key: dict[str, str] = field(default_factory=dict)

    @property
    def groups(self) -> list[FormGroup]:
        """Champs regroupés par ``group``, ordre de déclaration conservé."""
        out: list[FormGroup] = []
        index: dict[str, FormGroup] = {}
        for f in self.fields:
            key = f.item.group or ""
            group = index.get(key)
            if group is None:
                group = FormGroup(label=key)
                index[key] = group
                out.append(group)
            group.fields.append(f)
        return out

    @property
    def has_errors(self) -> bool:
        return bool(self.errors) or any(f.error for f in self.fields)


def editable_items(items: Iterable[ConfigItem]) -> list[ConfigItem]:
    """Réglages scalaires d'une section (les listes ont leur propre écran)."""
    return [i for i in items if i.type != "record_list"]


def build_form(items: Sequence[ConfigItem]) -> ScalarForm:
    """Formulaire en lecture — valeurs courantes, secrets masqués."""
    snapshot = config_service.snapshot_redacted()
    return ScalarForm(fields=[
        BoundField(item=item, value=snapshot.get(item.key))
        for item in editable_items(items)
    ])


def save_form(request, items: Sequence[ConfigItem], *, actor: str = "") -> ScalarForm:
    """Applique une soumission et renvoie le formulaire rechargé.

    Chaque réglage est enregistré indépendamment : une valeur refusée n'annule
    pas celles qui ont été acceptées, et son message est affiché sur son
    propre champ. Refuser tout le lot parce qu'un nombre est hors bornes
    obligerait à ressaisir des réglages corrects.
    """
    posted = set(request.POST.getlist(FIELD_MARKER))
    by_key = {i.key: i for i in editable_items(items)}

    # Réinitialisation : retire la valeur enregistrée, on retombe sur le
    # défaut du schéma. Traité avant les écritures pour qu'un même envoi
    # « réinitialiser » ne réécrive pas aussitôt le champ.
    for key in request.POST.getlist(UNSET_MARKER):
        item = by_key.get(key)
        if item is None or item.readonly:
            continue
        try:
            config_service.unset(key, actor=actor)
        except Exception as exc:
            logger.warning("réinitialisation de %s impossible : %s", key, exc)

    form = ScalarForm()
    for item in by_key.values():
        if item.key not in posted or item.readonly:
            continue
        raw = _read_raw(request, item)
        try:
            config_service.set(item.key, raw, actor=actor)
            form.saved.append(item.key)
        except ValidationError as exc:
            form.errors.append(f"{item.label or item.key} : {exc}")
            form.errors_by_key[item.key] = str(exc)
        except KeyError as exc:
            form.errors.append(str(exc))
        except Exception as exc:
            logger.exception("écriture de %s impossible", item.key)
            form.errors.append(f"{item.label or item.key} : {exc}")
            form.errors_by_key[item.key] = str(exc)

    # On relit depuis le service plutôt que de réafficher la saisie : ce qui
    # doit apparaître est ce qui est réellement enregistré. Une valeur refusée
    # montre donc l'ancienne, accompagnée de son message d'erreur.
    reloaded = build_form(items)
    for f in reloaded.fields:
        f.error = form.errors_by_key.get(f.item.key, "")
    reloaded.errors = form.errors
    reloaded.saved = form.saved
    reloaded.errors_by_key = form.errors_by_key
    return reloaded


def _read_raw(request, item: ConfigItem):
    """Extrait la valeur brute d'un champ, selon son type déclaré."""
    if item.type == "bool":
        # Une case décochée n'est pas envoyée : sa seule absence, alors que
        # le marqueur de champ est présent, signifie False.
        return request.POST.get(item.key) is not None
    if item.type == "multiselect":
        return request.POST.getlist(item.key)
    value = request.POST.get(item.key, "")
    if item.type == "secret":
        # Vide = inchangé. ``config_service.set`` le traite comme un no-op et
        # renvoie un marqueur masqué plutôt que le secret courant.
        return value
    return value


# ── Listes d'enregistrements ────────────────────────────────────────────

@dataclass
class RecordField:
    """Un champ à l'intérieur d'une ligne de liste."""
    item: ConfigItem
    value: Any = None
    error: str = ""
    # Options chargées à la demande (voir ``GestionSysteme.choices``). Quand
    # elles sont présentes, le champ devient une liste déroulante quel que
    # soit son type déclaré : le registre ne peut pas porter des options qui
    # dépendent d'un autre champ et d'un appel réseau.
    dynamic_options: list[tuple[str, str]] | None = None

    @property
    def name(self) -> str:
        return self.item.key

    @property
    def widget(self) -> str:
        if self.dynamic_options:
            return "select"
        return WIDGETS.get(self.item.type, "text")

    @property
    def options(self) -> list[tuple[str, str]]:
        """Couples (valeur, libellé) à afficher.

        La valeur courante est réinjectée si elle ne figure pas dans la liste
        chargée : modifier une ligne existante ne doit jamais lui faire perdre
        silencieusement son modèle parce que le fournisseur ne le liste plus.
        """
        if self.dynamic_options is None:
            return choice_options(self.item.choices)
        options = list(self.dynamic_options)
        courante = self.text_value
        if courante and courante not in {v for v, _ in options}:
            options.insert(0, (courante, f"{courante} (valeur actuelle)"))
        return options

    @property
    def label(self) -> str:
        from GestionSysteme.formatting import humanize_key
        return self.item.label or humanize_key(self.item.key)

    @property
    def is_secret(self) -> bool:
        return self.item.type == "secret" or self.item.sensitive

    @property
    def has_secret_value(self) -> bool:
        return bool(isinstance(self.value, dict) and self.value.get("has_value"))

    @property
    def text_value(self) -> str:
        if self.is_secret:
            return ""
        v = self.value
        if v is None:
            return ""
        if isinstance(v, bool):
            return "1" if v else ""
        if isinstance(v, (list, tuple)):
            return ", ".join(str(x) for x in v)
        return str(v)

    @property
    def checked(self) -> bool:
        return bool(self.value)

    @property
    def selected(self) -> list[str]:
        v = self.value
        if isinstance(v, (list, tuple)):
            return [str(x) for x in v]
        return [str(v)] if v not in (None, "") else []

    @property
    def choices(self) -> tuple:
        return choice_values(self.item.choices)

    @property
    def step(self) -> str:
        return "1" if self.item.type == "int" else "any"


@dataclass
class RecordForm:
    """Formulaire d'une ligne de ``record_list`` (création ou édition)."""
    item: ConfigItem
    fields: list[RecordField] = field(default_factory=list)
    row_id: str = ""
    enabled: bool = True
    errors: list[str] = field(default_factory=list)
    # Champ à options chargeables, s'il y en a un pour cette liste.
    dynamic: Any = None                 # choices.DynamicField | None
    load_error: str = ""
    loaded: bool = False

    @property
    def is_new(self) -> bool:
        return not self.row_id

    @property
    def title(self) -> str:
        label = self.item.record.label if self.item.record else "Élément"
        return f"Nouvel élément · {label}" if self.is_new else f"Modifier · {label}"


def build_record_form(
    item: ConfigItem,
    row: dict | None = None,
    *,
    options: list[tuple[str, str]] | None = None,
    load_error: str = "",
) -> RecordForm:
    """Construit le formulaire d'une ligne.

    ``options`` porte les choix fraîchement chargés pour le champ dynamique de
    cette liste (voir ``GestionSysteme.choices``) ; ils ne sont jamais résolus
    ici, parce que les charger à chaque affichage ferait un appel réseau vers
    un service tiers pour ouvrir une page.
    """
    from GestionSysteme import choices as dyn

    payload = dict((row or {}).get("payload") or {})
    dynamic = dyn.for_list(item.key)

    fields = []
    for f in (item.record.fields if item.record else ()):
        champ = RecordField(item=f, value=payload.get(f.key, f.default))
        if dynamic is not None and f.key == dynamic.field_key and options:
            champ.dynamic_options = options
        fields.append(champ)

    return RecordForm(
        item=item,
        fields=fields,
        row_id=str((row or {}).get("row_id") or ""),
        enabled=bool((row or {}).get("enabled", True)),
        dynamic=dynamic,
        load_error=load_error,
        loaded=bool(options),
    )


def read_record_payload(request, item: ConfigItem) -> dict:
    """Reconstitue la charge utile d'une ligne depuis un POST."""
    payload: dict[str, Any] = {}
    for f in (item.record.fields if item.record else ()):
        if f.readonly:
            continue
        if f.type == "bool":
            payload[f.key] = request.POST.get(f.key) is not None
        elif f.type == "multiselect":
            payload[f.key] = request.POST.getlist(f.key)
        else:
            value = request.POST.get(f.key, "")
            if f.type == "secret" and value == "":
                # Champ laissé vide : on n'envoie pas la clé, ce qui vaut
                # « garder l'actuel » pour les backends d'enregistrement.
                continue
            payload[f.key] = value
    return payload


def record_list_items(items: Iterable[ConfigItem]) -> list[ConfigItem]:
    return [i for i in items if i.type == "record_list" and i.record is not None]


def require_record_list(key: str) -> ConfigItem:
    item = registry.get(key)
    if item is None or item.type != "record_list" or item.record is None:
        raise LookupError(key)
    return item


def row_summary(item: ConfigItem, row: dict) -> list[tuple[str, str]]:
    """Résumé lisible d'une ligne, pour le tableau récapitulatif.

    Les champs sensibles ne sont jamais rendus en clair — le backend les
    remonte déjà masqués, on n'affiche donc que « défini » / « non défini ».
    """
    payload = row.get("payload") or {}
    out: list[tuple[str, str]] = []
    for f in item.record.fields:
        raw = payload.get(f.key)
        if f.type == "secret" or f.sensitive:
            has = bool(isinstance(raw, dict) and raw.get("has_value")) or bool(
                raw and not isinstance(raw, dict)
            )
            out.append((f.label or f.key, "défini" if has else "—"))
            continue
        if isinstance(raw, bool):
            out.append((f.label or f.key, "oui" if raw else "non"))
        elif isinstance(raw, (list, tuple)):
            out.append((f.label or f.key, ", ".join(str(x) for x in raw) or "—"))
        else:
            out.append((f.label or f.key, str(raw) if raw not in (None, "") else "—"))
    return out


def actor_for(request) -> str:
    """Qui a écrit — repris dans le journal de configuration."""
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        return str(user)
    return request.META.get("REMOTE_ADDR", "anonyme")
