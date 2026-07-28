"""Configuration — l'espace fixe des paramètres principaux.

Ce que cette page contient : les réglages du **cœur** (accès, IA, mémoire,
conscience, communication). Ce qu'elle ne contient pas : les réglages des
modules — ils vivent dans l'espace de chaque module, à côté de son état et de
ses données, parce que c'est là qu'on les cherche.

Le rendu est entièrement piloté par le registre : ajouter un ``ConfigItem``
dans un ``config_schema.py`` le fait apparaître ici, sans toucher à une vue ni
à un gabarit. Aucun champ n'est codé en dur.

**Les secrets ne descendent jamais.** Un champ sensible part vide et un envoi
vide vaut « inchangé ». La page de configuration peut donc être affichée sans
exposer une seule clé d'API.
"""
from __future__ import annotations

import dataclasses
import logging

from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from configs.registry import registry
from configs.service import ValidationError, config_service
from GestionSysteme import forms
from GestionSysteme.nav import item_for
from GestionSysteme.shell import page_context

logger = logging.getLogger(__name__)

MODULE_SECTION_PREFIX = "module_"

# Regroupement des sections du cœur. L'ordre des groupes est celui-ci ;
# l'ordre à l'intérieur reste celui déclaré au registre (champ ``order``).
GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Accès", ("accounts",)),
    ("Intelligence artificielle", ("ai_providers", "ai_models", "ai_roles")),
    ("Communication", ()),      # rempli par préfixe comm_
    ("Cœur", ()),               # tout le reste
)


def _group_of(section_key: str) -> str:
    for label, keys in GROUPS:
        if section_key in keys:
            return label
    if section_key.startswith("comm_"):
        return "Communication"
    if section_key.startswith("ai_") or section_key.startswith("ai."):
        return "Intelligence artificielle"
    return "Cœur"


def is_module_section(section_key: str) -> bool:
    return section_key.startswith(MODULE_SECTION_PREFIX)


def core_sections() -> list:
    """Sections du cœur, dans l'ordre déclaré, hors sections de modules."""
    return [s for s in registry.sections() if not is_module_section(s.key)]


def grouped_sections() -> list[dict]:
    groups: dict[str, list] = {}
    order: list[str] = []
    for section in core_sections():
        label = _group_of(section.key)
        if label not in groups:
            groups[label] = []
            order.append(label)
        groups[label].append(section)
    # On respecte l'ordre déclaré dans GROUPS pour les groupes connus, puis
    # l'ordre d'apparition pour les autres.
    known = [label for label, _ in GROUPS]
    order.sort(key=lambda label: known.index(label) if label in known else len(known))
    return [{"label": label, "sections": groups[label]} for label in order]


def items_for(section_key: str) -> list:
    """Items déclarés pour une section, dans l'ordre du registre."""
    return [i for i in registry.all_items() if i.section == section_key]


# ── Choix dynamiques ────────────────────────────────────────────────────

def declared_model_names() -> list[str]:
    """Noms internes des modèles déclarés, actifs uniquement.

    Le registre ne sait pas porter des choix dynamiques ; on les injecte donc
    au moment du rendu. Sans cela, un rôle pourrait viser un modèle qui
    n'existe pas — et ``AIRouter`` lèverait ``UnconfiguredRoleError`` au
    premier appel, bien plus tard et bien plus loin.
    """
    try:
        rows = config_service.list_rows("ai.models", decrypt_secrets=False)
    except Exception:
        return []
    names: list[str] = []
    for row in rows:
        if not row.get("enabled", True):
            continue
        name = ((row.get("payload") or {}).get("internal_name") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def _inject_dynamic_choices(form: forms.ScalarForm) -> None:
    """Remplit les choix des sélecteurs ``ai.role.*``.

    ``ConfigItem`` est un dataclass gelé : on le remplace par une copie plutôt
    que de le muter, sinon l'injection fuiterait dans le registre partagé.
    """
    names = declared_model_names()
    if not names:
        return
    for field in form.fields:
        if field.item.type == "select" and field.item.key.startswith("ai.role."):
            field.item = dataclasses.replace(field.item, choices=tuple(names))


# ── Vues ────────────────────────────────────────────────────────────────

def config_home(request):
    """Renvoie vers la première section — la page n'a pas de contenu propre."""
    sections = core_sections()
    if not sections:
        item = item_for("config")
        ctx = page_context(request, item=item, active_key="config")
        ctx.update({"groups": [], "section": None})
        return render(request, "gestion/config/vide.html", ctx)
    return redirect("gestionsysteme:config-section", section=sections[0].key)


def config_section(request, section: str):
    if is_module_section(section):
        # Une section de module a déménagé dans l'espace du module.
        return redirect(
            "gestionsysteme:module-space",
            module=section[len(MODULE_SECTION_PREFIX):],
        )

    spec = next((s for s in core_sections() if s.key == section), None)
    if spec is None:
        raise Http404(f"Section de configuration inconnue : {section}")

    items = items_for(section)

    if request.method == "POST":
        form = forms.save_form(request, items, actor=forms.actor_for(request))
        if form.errors:
            for message in form.errors:
                messages.error(request, message)
        if form.saved:
            messages.success(
                request,
                f"{len(form.saved)} réglage(s) enregistré(s).",
            )
        if not form.errors:
            # Redirection après POST : recharger la page ne renvoie pas le
            # formulaire une seconde fois.
            return redirect("gestionsysteme:config-section", section=section)
    else:
        form = forms.build_form(items)

    _inject_dynamic_choices(form)

    item = item_for("config")
    ctx = page_context(
        request, item=item, active_key="config",
        title=spec.label, description=spec.description,
    )
    ctx.update({
        "groups": grouped_sections(),
        "section": spec,
        "form": form,
        "record_lists": _record_lists(section, items),
    })
    return render(request, "gestion/config/section.html", ctx)


def _record_lists(section_key: str, items) -> list[dict]:
    out = []
    for item in forms.record_list_items(items):
        try:
            rows = config_service.list_rows(item.key, decrypt_secrets=False)
        except Exception as exc:
            logger.exception("lecture des lignes de %s impossible", item.key)
            out.append({"item": item, "rows": [], "error": str(exc), "columns": []})
            continue
        out.append({
            "item": item,
            "columns": [f.label or f.key for f in item.record.fields],
            "rows": [
                {
                    "row": row,
                    "values": [v for _, v in forms.row_summary(item, row)],
                }
                for row in rows
            ],
            "error": "",
            "full": (
                item.max_items is not None and len(rows) >= item.max_items
            ),
        })
    return out


# ── Lignes de listes ────────────────────────────────────────────────────

def _require_item(section: str, key: str):
    try:
        item = forms.require_record_list(key)
    except LookupError:
        raise Http404(f"Liste inconnue : {key}")
    if item.section != section:
        raise Http404(f"{key} n'appartient pas à la section {section}")
    return item


def _back_to(section: str) -> str:
    """Où revenir après une opération sur une ligne.

    Les listes d'un module réutilisent ces mêmes routes, mais leur écran
    d'origine est le panneau « configuration » de son espace, pas la page de
    configuration du cœur — d'où l'aiguillage ici plutôt qu'un second jeu de
    routes qui ferait exactement la même chose.
    """
    if is_module_section(section):
        return reverse(
            "gestionsysteme:module-panel",
            args=[section[len(MODULE_SECTION_PREFIX):], "configuration"],
        )
    return reverse("gestionsysteme:config-section", args=[section])


# Nom du bouton qui recharge les options d'un champ dynamique au lieu
# d'enregistrer. Il porte la saisie en cours, donc rien n'est perdu.
LOAD_MARKER = "__charger"


def _reload_options(request, item, payload: dict, *, row_id: str = ""):
    """Réaffiche le formulaire avec les options fraîchement chargées.

    Aller-retour serveur ordinaire : pas de JavaScript, et la saisie déjà
    faite est conservée puisqu'elle repart du POST.
    """
    from GestionSysteme import choices

    options, erreur = choices.load(item.key, payload)
    return forms.build_record_form(
        item, {"payload": payload, "row_id": row_id},
        options=options, load_error=erreur,
    )


def record_new(request, section: str, key: str):
    item = _require_item(section, key)

    if request.method == "POST":
        payload = forms.read_record_payload(request, item)

        if LOAD_MARKER in request.POST:
            return _render_record_form(
                request, section, item, _reload_options(request, item, payload),
            )

        try:
            config_service.add_row(key, payload, actor=forms.actor_for(request))
            messages.success(request, "Élément ajouté.")
            return redirect(_back_to(section))
        except ValidationError as exc:
            messages.error(request, str(exc))
            form = forms.build_record_form(item, {"payload": payload})
        except Exception as exc:
            logger.exception("ajout impossible dans %s", key)
            messages.error(request, f"Ajout impossible : {exc}")
            form = forms.build_record_form(item, {"payload": payload})
    else:
        form = forms.build_record_form(item)

    return _render_record_form(request, section, item, form)


def record_edit(request, section: str, key: str, row_id: str):
    item = _require_item(section, key)

    rows = config_service.list_rows(key, decrypt_secrets=False)
    row = next((r for r in rows if str(r.get("row_id")) == str(row_id)), None)
    if row is None:
        raise Http404("Élément introuvable")

    if request.method == "POST":
        payload = forms.read_record_payload(request, item)

        if LOAD_MARKER in request.POST:
            return _render_record_form(
                request, section, item,
                _reload_options(request, item, payload, row_id=str(row_id)),
            )

        try:
            config_service.update_row(key, row_id, payload, actor=forms.actor_for(request))
            messages.success(request, "Élément modifié.")
            return redirect(_back_to(section))
        except ValidationError as exc:
            messages.error(request, str(exc))
        except Exception as exc:
            logger.exception("modification impossible dans %s", key)
            messages.error(request, f"Modification impossible : {exc}")
        form = forms.build_record_form(item, {"payload": payload, "row_id": row_id})
    else:
        form = forms.build_record_form(item, row)

    return _render_record_form(request, section, item, form)


def _render_record_form(request, section: str, item, form):
    spec = next((s for s in core_sections() if s.key == section), None)
    ctx = page_context(
        request, item=item_for("config"), active_key="config",
        title=form.title,
        description=(item.record.description if item.record else ""),
    )
    ctx.update({
        "groups": grouped_sections(),
        "section": spec,
        "form": form,
        "list_item": item,
        "back_url": _back_to(section),
        "post_url": (
            reverse("gestionsysteme:config-record-new", args=[section, item.key])
            if form.is_new else
            reverse("gestionsysteme:config-record-edit", args=[section, item.key, form.row_id])
        ),
    })
    return render(request, "gestion/config/ligne.html", ctx)


@require_POST
def record_delete(request, section: str, key: str, row_id: str):
    item = _require_item(section, key)

    # Contrôle de référence : refuser la suppression d'un modèle déclaré
    # encore associé à un rôle. Sans cela le rôle pointe dans le vide et
    # l'erreur ne surgit qu'au prochain appel IA.
    if key == "ai.models":
        refs = _model_references(key, row_id)
        if refs:
            messages.error(
                request,
                "Modèle utilisé par : " + ", ".join(refs)
                + ". Retire ces associations avant de supprimer.",
            )
            return redirect(_back_to(section))

    try:
        config_service.delete_row(key, row_id, actor=forms.actor_for(request))
        messages.success(request, "Élément supprimé.")
    except ValidationError as exc:
        # Un backend peut refuser catégoriquement (supprimer le dernier
        # administrateur actif enferme tout le monde dehors).
        messages.error(request, str(exc))
    except Exception as exc:
        logger.exception("suppression impossible dans %s", key)
        messages.error(request, f"Suppression impossible : {exc}")
    return redirect(_back_to(section))


def _model_references(key: str, row_id: str) -> list[str]:
    try:
        rows = config_service.list_rows(key, decrypt_secrets=False)
    except Exception:
        return []
    target = next((r for r in rows if str(r.get("row_id")) == str(row_id)), None)
    if target is None:
        return []
    name = ((target.get("payload") or {}).get("internal_name") or "").strip()
    if not name:
        return []

    refs: list[str] = []
    try:
        from ai.router import AIRole
    except Exception:
        return refs
    for role in AIRole:
        try:
            value = (config_service.get(f"ai.role.{role.value}", default="") or "").strip()
        except Exception:
            continue
        if value == name:
            refs.append(f"rôle IA · {role.value}")
    return refs
