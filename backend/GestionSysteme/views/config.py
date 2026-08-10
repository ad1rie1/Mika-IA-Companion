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
import unicodedata

from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from configs.registry import registry
from configs.types import ConfigFamily
from configs.service import ValidationError, config_service
from GestionSysteme import forms
from GestionSysteme.families import family_of
from GestionSysteme.nav import item_for
from GestionSysteme.shell import page_context

logger = logging.getLogger(__name__)

MODULE_SECTION_PREFIX = "module_"
# Sections créées à l'exécution par la Forge, une par app forgée. Le préfixe
# est déclaré ici plutôt que dans la vue des apps parce que c'est ici qu'on
# décide ce qui est « du cœur » — et que l'inverse ferait un import circulaire.
FORGE_SECTION_PREFIX = "forge_"


def _cles_modifiees() -> set[str]:
    """Les clés portant une valeur enregistrée, donc différentes du défaut.

    Une seule requête pour tout l'écran. C'est le repère le plus utile sur
    quatre cents réglages : « qu'est-ce que j'ai touché ici ? » n'a pas de
    réponse quand tout se ressemble, et l'opérateur finit par relire chaque
    champ pour comparer mentalement au défaut.

    Illisible (base pas encore migrée, verrou) : on rend un ensemble vide.
    Aucun réglage n'est alors signalé comme modifié — l'écran perd un repère,
    il n'affiche pas un faux.
    """
    try:
        from configs.models import ConfigValue
        return set(ConfigValue.objects.values_list("key", flat=True))
    except Exception:
        logger.debug("lecture des clés modifiées impossible", exc_info=True)
        return set()

def is_module_section(section_key: str) -> bool:
    return section_key.startswith(MODULE_SECTION_PREFIX)


def is_forge_section(section_key: str) -> bool:
    return section_key.startswith(FORGE_SECTION_PREFIX)


def forge_app_of(section_key: str) -> str:
    return section_key[len(FORGE_SECTION_PREFIX):]


def core_sections() -> list:
    """Sections du cœur : ni celles des modules, ni celles des apps forgées.

    Les secondes sont enregistrées **à l'exécution**, par du code que Mika
    écrit elle-même (``ForgeModule._register_config``). Laissées ici, la page
    des réglages du système s'allongeait toute seule, une app venant se
    ranger entre les clés d'API et les seuils de la conscience — et ses
    réglages se lisaient à trois écrans de ses propres pages. Elles vivent
    maintenant dans l'espace de leur app.
    """
    return [
        s for s in registry.sections()
        if not is_module_section(s.key) and not is_forge_section(s.key)
    ]


def grouped_sections(*, modifiees: set[str] | None = None) -> list[dict]:
    """Les sections du cœur, rangées par famille, prêtes pour la barre latérale.

    Chaque section porte son nombre de réglages et son nombre de réglages
    modifiés : la barre latérale devient une carte de l'installation plutôt
    qu'un sommaire, et « où ai-je touché quelque chose ? » se lit sans ouvrir
    les trente et une pages.

    Une famille sans section n'est pas rendue — déclarer une famille en
    prévision ne salit donc pas l'écran.
    """
    modifiees = _cles_modifiees() if modifiees is None else modifiees

    par_section: dict[str, list] = {}
    for item in registry.all_items():
        par_section.setdefault(item.section, []).append(item)

    paniers: dict[str, list] = {}
    for section in core_sections():
        items = par_section.get(section.key, [])
        paniers.setdefault(family_of(section), []).append({
            "section": section,
            "total": len(items),
            "modifies": sum(1 for i in items if i.key in modifiees),
        })

    sorties = []
    for famille in registry.families():
        entrees = paniers.pop(famille.key, None)
        if entrees:
            sorties.append({"famille": famille, "entrees": entrees})
    # Une famille référencée mais jamais déclarée reste visible plutôt que de
    # faire disparaître ses sections de la navigation.
    for cle, entrees in paniers.items():
        sorties.append({
            "famille": ConfigFamily(key=cle, label=cle.capitalize(), order=998),
            "entrees": entrees,
        })
    return sorties


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



# ── Mise en forme d'une section ─────────────────────────────────────────

def _ancre(section_key: str, group_key: str) -> str:
    """Identifiant d'ancre stable pour un groupe.

    Dérivé du libellé, donc lisible dans l'URL — un lien vers un bloc précis
    d'une longue section reste compréhensible quand on le colle ailleurs.
    """
    brut = (group_key or "general").lower()
    garde = [c if c.isalnum() else "-" for c in brut]
    return "g-" + "".join(garde).strip("-").replace("--", "-") or "g-general"


def _sans_accents(texte: str) -> str:
    """Minuscule et sans diacritiques, pour comparer une saisie à du français.

    Sans ça, chercher « reve » ne trouve pas « Rêves » et « energie » ne trouve
    pas « Courbe d'énergie » — c'est-à-dire que la recherche ne marche pas pour
    quelqu'un qui tape vite, ce qui est exactement le cas où on l'utilise. On
    replie donc les deux côtés de la comparaison.
    """
    decompose = unicodedata.normalize("NFKD", texte.lower())
    return "".join(c for c in decompose if not unicodedata.combining(c))


def _correspond(champ, terme_replie: str) -> bool:
    """Le réglage répond-il à la recherche ?

    On cherche dans le libellé, la clé, la description, l'indice et le nom du
    groupe : la clé parce qu'on arrive souvent depuis un log ou un commentaire
    qui la cite, l'indice parce que c'est là que sont les mots dont on se
    souvient (« coucher », « plafond », « salutation »).

    Tous les mots doivent correspondre, dans n'importe quel ordre : « max
    reve » trouve le plafond de rêves par nuit sans qu'il faille deviner
    comment le libellé est tourné.
    """
    i = champ.item
    foin = _sans_accents(" ".join((
        champ.label or "", i.key, i.description or "", i.hint or "",
        i.group or "",
    )))
    return all(mot in foin for mot in terme_replie.split())


def blocs_de_section(section_key: str, form, *, modifiees: set[str],
                     terme: str = "", modifies_seuls: bool = False) -> list[dict]:
    """Les groupes d'une section, enrichis de leurs métadonnées déclarées.

    Un groupe sans ``ConfigGroup`` déclaré se rend comme avant : un titre et
    ses champs. Ce qu'ajoute une déclaration, c'est une phrase d'explication,
    un ordre choisi, et la possibilité d'être **replié** — ce dernier point
    étant ce qui rend une section de soixante-dix réglages consultable.

    Un bloc replié s'ouvre quand même s'il contient une valeur modifiée ou un
    résultat de recherche : cacher à l'opérateur ce que lui-même a changé, ou
    ce qu'il vient de chercher, serait le seul moyen de rendre le repli
    nuisible.
    """
    terme_replie = _sans_accents(terme) if terme else ""
    blocs: list[dict] = []
    for groupe in form.groups:
        champs = groupe.fields
        if terme_replie:
            champs = [c for c in champs if _correspond(c, terme_replie)]
        if modifies_seuls:
            champs = [c for c in champs if c.item.key in modifiees]
        if not champs:
            continue

        meta = registry.group(section_key, groupe.label)
        n_modifies = sum(1 for c in champs if c.item.key in modifiees)
        replie = bool(meta and meta.advanced)
        blocs.append({
            "cle": groupe.label,
            "titre": (meta.title if meta else groupe.label),
            "description": (meta.description if meta else ""),
            "ancre": _ancre(section_key, groupe.label),
            "champs": champs,
            "total": len(champs),
            "modifies": n_modifies,
            "avance": replie,
            # Replié seulement s'il n'y a aucune raison de l'ouvrir.
            "ouvert": (not replie) or bool(n_modifies) or bool(terme)
                      or modifies_seuls,
            "ordre": (meta.order if meta else 100),
        })
    blocs.sort(key=lambda b: (b["ordre"],))
    return blocs


def contexte_reglages(request, section_key: str, form) -> dict:
    """Tout ce dont le partiel « réglages » a besoin, pour n'importe quel écran.

    Trois pages servent des réglages — le cœur, l'espace d'un module, l'espace
    d'une app forgée — et elles rendaient chacune leur copie du même
    formulaire. La barre de recherche, le sommaire, le repli des blocs avancés
    et la pastille « modifié » n'auraient donc profité qu'à la première, et une
    correction sur l'une aurait laissé les deux autres derrière.

    Un module et une app forgée déclarent leurs ``ConfigGroup`` exactement
    comme le cœur : la mise en forme leur arrive sans qu'ils sachent qu'elle
    existe.
    """
    terme = (request.GET.get("q") or "").strip().lower()
    modifies_seuls = request.GET.get("vue") == "modifies"
    modifiees = _cles_modifiees()

    blocs = blocs_de_section(
        section_key, form, modifiees=modifiees,
        terme=terme, modifies_seuls=modifies_seuls,
    )
    return {
        "blocs": blocs,
        "recherche": request.GET.get("q") or "",
        "modifies_seuls": modifies_seuls,
        "filtre_actif": bool(terme) or modifies_seuls,
        "total_reglages": len(form.fields),
        "total_modifies": sum(1 for f in form.fields if f.item.key in modifiees),
        "affiches": sum(b["total"] for b in blocs),
        # Le sommaire ne sert que s'il y a plusieurs blocs à survoler ; à deux
        # titres il double la hauteur de l'écran pour rien.
        "sommaire": blocs if len(blocs) >= 3 else [],
        "_modifiees": modifiees,
    }


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
    if is_forge_section(section):
        # Idem pour une app forgée — un favori d'avant le déménagement doit
        # atterrir sur la bonne page, pas sur un 404.
        return redirect("gestionsysteme:forge-app-config",
                        app=forge_app_of(section))

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

    # Recherche et filtre vivent dans l'URL, comme partout ailleurs ici : un
    # écran filtré se partage, se met en favori, et le retour arrière le défait.
    reglages = contexte_reglages(request, section, form)

    item = item_for("config")
    ctx = page_context(
        request, item=item, active_key="config",
        title=spec.label, description=spec.description,
    )
    ctx.update(reglages)
    ctx.update({
        "groups": grouped_sections(modifiees=reglages["_modifiees"]),
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
            out.append({"section_key": section_key, "item": item, "rows": [],
                        "error": str(exc), "columns": []})
            continue
        out.append({
            # Exposé comme dans les espaces module et forge : le partiel des
            # listes construit ses URL avec, et n'a donc pas trois façons de
            # savoir à quelle section il appartient.
            "section_key": section_key,
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
    if is_forge_section(section):
        return reverse("gestionsysteme:forge-app-config",
                       args=[forge_app_of(section)])
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
