"""Filtres et balises de gabarit.

Règle unique : **rien ici ne renvoie de HTML brut.** Tout produit du texte, un
nombre ou un fragment d'attribut ``style`` dont la valeur vient d'une liste
fermée. L'échappement automatique de Django reste donc actif de bout en bout,
et aucun ``mark_safe`` n'a besoin d'être audité.
"""
from __future__ import annotations

from django import template

from GestionSysteme import formatting as fmt

register = template.Library()


@register.filter
def display_text(value):
    """Plafond partagé des textes dépliables, annoncé sans altérer la donnée."""
    return fmt.display_text(str(value) if value is not None else "—", 100_000)


@register.filter
def safe_href(value):
    from GestionSysteme.panel_payload import safe_href as checked
    return checked(value)


@register.filter
def at(values, index):
    try:
        return values[int(index)]
    except (IndexError, KeyError, TypeError, ValueError):
        return None


@register.inclusion_tag("gestion/partials/action.html", takes_context=True)
def panel_action_ui(context, key, initial=None, title=""):
    from django.urls import reverse
    from GestionSysteme.panel_forms import build_form, action_instance

    panel = context.get("panel")
    action = next((a for a in panel.actions if a.key == key), None) if panel else None
    if action is None:
        return {"unavailable": True}
    initial = initial or {}
    instance = action_instance(key, initial)
    request = context["request"]
    invalid = context.get("action_error")
    bound = bool(invalid and invalid.key == key and request.POST.get("_panel_instance") == instance)
    form = build_form(action, data=request.POST if bound else None, initial=initial)
    form.auto_id = f"action-{instance}-%s"
    if bound:
        form.is_valid()
    if context.get("app_name"):
        url = reverse("gestionsysteme:forge-app-action", args=[context["app_name"], panel.key, key])
    else:
        url = reverse("gestionsysteme:module-action", args=[context["module_name"], panel.key, key])
    query = request.GET.urlencode()
    return {"action": action, "action_form": form, "action_url": url + (f"?{query}" if query else ""),
            "instance": instance, "bound": bound, "title": title,
            "csrf_token": context.get("csrf_token")}


@register.simple_tag(takes_context=True)
def panel_has_errors(context, block):
    from GestionSysteme.panels import walk_blocks, ActionForm
    from GestionSysteme.panel_forms import action_instance
    invalid = context.get("action_error")
    if not invalid:
        return False
    instance = context["request"].POST.get("_panel_instance")
    return any(isinstance(b, ActionForm) and b.action == invalid.key
               and action_instance(b.action, b.initial) == instance for b in walk_blocks(block))


# ── Mise en forme ───────────────────────────────────────────────────────

register.filter("pct", fmt.pct)
register.filter("num", fmt.num)
register.filter("dt", fmt.dt)
register.filter("dt_full", fmt.dt_full)
register.filter("ago", fmt.ago)
register.filter("duration", fmt.duration)
register.filter("yes_no", fmt.yes_no)
register.filter("humanize_key", fmt.humanize_key)
register.filter("trend_label", fmt.trend_label)
register.filter("closeness_label", fmt.closeness_label)
register.filter("tone_label", fmt.tone_label)
register.filter("commitment_label", fmt.commitment_label)
register.filter("dream_label", fmt.dream_label)


@register.filter
def clip(value, length=160):
    try:
        length = int(length)
    except (TypeError, ValueError):
        length = 160
    return fmt.clip(value, length)


@register.filter
def emo_style(name):
    """Fragment d'attribut ``style`` portant la couleur d'une émotion.

    Utilisation : ``<span class="emo" style="{{ e|emo_style }}">``. La sortie
    est ``--emo: var(--emo-<nom>)`` avec ``<nom>`` validé contre les 29
    émotions connues, donc jamais une chaîne venue telle quelle de la base.
    """
    return f"--emo: {fmt.emotion_var(name)}"


register.filter("emo_tone", fmt.emotion_tone)
register.filter("emo_fr", fmt.emotion_fr)


@register.filter
def tone_ratio(value, invert=""):
    """Classe de teinte d'une jauge. ``|tone_ratio:"invert"`` inverse."""
    return fmt.tone_for_ratio(value, invert=bool(invert))


@register.filter
def bar_width(value):
    """Ratio 0→1 en pourcentage borné, pour ``style="width:{{ v|bar_width }}%"``."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "0"
    return f"{max(0.0, min(1.0, v)) * 100:.1f}"


@register.filter
def get(mapping, key):
    """Accès par clé variable — impossible avec la syntaxe à points."""
    if mapping is None:
        return None
    try:
        return mapping.get(key)
    except AttributeError:
        return None


@register.filter
def field_value(obj, name):
    """Lecture d'attribut par nom variable, pour les tableaux génériques."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


# ── URL ─────────────────────────────────────────────────────────────────

@register.simple_tag(takes_context=True)
def qs(context, **overrides):
    """Chaîne de requête courante, avec substitutions.

    ``{% qs page=3 %}`` conserve les filtres et le tri en place et ne change
    que la page. Une valeur vide **retire** le paramètre, ce qui donne des
    URL propres (``?statut=`` n'apparaît pas quand aucun statut n'est choisi)
    et évite qu'un filtre neutre reste collé dans les liens de pagination.
    """
    request = context.get("request")
    params = request.GET.copy() if request is not None else {}
    if hasattr(params, "copy"):
        params = params.copy()

    for key, value in overrides.items():
        if value in (None, "", False):
            params.pop(key, None)
        else:
            params[key] = value

    encoded = params.urlencode() if hasattr(params, "urlencode") else ""
    return f"?{encoded}" if encoded else ""


@register.simple_tag(takes_context=True)
def qs_set(context, key, value):
    """Comme ``{% qs %}`` mais avec un nom de paramètre variable.

    Nécessaire pour la pagination : le nom du paramètre de page appartient au
    résultat (``page.param``), parce qu'une même écran peut paginer deux
    listes indépendantes — les instantanés d'émotion et leurs résumés, par
    exemple, qui ne doivent pas se déplacer ensemble.
    """
    request = context.get("request")
    params = request.GET.copy() if request is not None else {}
    if value in (None, "", False):
        params.pop(key, None)
    else:
        params[key] = value
    encoded = params.urlencode()
    return f"?{encoded}" if encoded else ""


@register.simple_tag(takes_context=True)
def qs_toggle(context, key, value):
    """Ajoute le paramètre s'il est absent, le retire s'il vaut déjà ``value``."""
    request = context.get("request")
    params = request.GET.copy() if request is not None else {}
    current = params.get(key)
    if current == str(value):
        params.pop(key, None)
    else:
        params[key] = value
    params.pop("page", None)
    encoded = params.urlencode()
    return f"?{encoded}" if encoded else ""


@register.simple_tag(takes_context=True)
def sort_state(context, key):
    """``asc`` / ``desc`` / ``""`` pour l'attribut ``aria-sort`` d'un en-tête."""
    request = context.get("request")
    if request is None:
        return ""
    current = request.GET.get("tri", "")
    if current == key:
        return "ascending"
    if current == f"-{key}":
        return "descending"
    return ""


@register.simple_tag(takes_context=True)
def sort_next(context, key):
    """Valeur de tri à poser au prochain clic sur cet en-tête."""
    request = context.get("request")
    current = request.GET.get("tri", "") if request is not None else ""
    return key if current == f"-{key}" else f"-{key}"
