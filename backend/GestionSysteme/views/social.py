"""Social — identités, revendications, personnes, engagements, politique.

L'ordre des onglets reprend celui du prompt : l'identité **qualifie** la fiche
personne qui la suit (« voici l'historique de Thomas » ne se lit pas pareil
après « quelqu'un *prétend* être Thomas »).

**Toute écriture délègue à ``identity_resolver``.** Aucune arithmétique de
certitude et aucune affectation de ``Identity.entity`` ici : une seconde
implémentation est exactement la façon dont l'interface et le prompt se
mettraient à ne plus être d'accord sur qui parle.

Deux différences assumées avec le chemin outil de Mika :
- une écriture refusée est signalée comme une erreur, pas par un succès
  silencieux — le résolveur est permissif parce qu'il tourne sur des arguments
  produits par un LLM, un formulaire non ;
- un type de preuve inconnu est refusé au lieu d'être compté 0. Depuis une
  liste déroulante fermée c'est un bug, et une écriture qui ne change rien
  sans le dire est pire qu'une erreur.
"""
from __future__ import annotations

import logging

from asgiref.sync import async_to_sync
from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from GestionSysteme import tables
from GestionSysteme.nav import PERSON_TABS, item_for, resolve_tab
from GestionSysteme.shell import page_context
from identity import trust as trust_policy
from identity.trust import Certainty, ChannelTrust

logger = logging.getLogger(__name__)


def social(request, tab: str | None = None):
    item = item_for("social")
    current = item.tab(tab)
    ctx = page_context(
        request, item=item, active_key="social", active_tab=current.key,
    )
    ctx.update({
        "identites": _identities,
        "demandes": _claims,
        "personnes": _persons,
        "engagements": _commitments,
        "politique": _policy,
    }[current.key](request))
    return render(request, f"gestion/social/{current.key}.html", ctx)


# ── Lecture de la politique de confiance ────────────────────────────────

def _as_trust(value) -> ChannelTrust:
    """Convertit une colonne ``trust`` en énumération.

    Une valeur inconnue retombe sur PUBLIC — le même défaut que
    ``trust.channel_trust()`` applique à un transport dont personne n'a écrit
    les garanties : on suppose le plus faible.
    """
    try:
        return ChannelTrust(str(value or "").strip().lower())
    except ValueError:
        return ChannelTrust.PUBLIC


def _best_handle(handles):
    """Le handle qui permet le plus, vu le plus récemment.

    Classé par *plafond* de canal plutôt que par un ordre écrit à la main :
    le plafond encode déjà ce qu'un transport peut valoir au mieux, et une
    seconde table de classement serait une chose de plus à garder synchronisée
    avec ``identity/trust.py``.
    """
    real = [h for h in handles if not h.is_ephemeral] or list(handles)
    if not real:
        return None
    return max(
        real,
        key=lambda h: (trust_policy.ceiling_for(_as_trust(h.trust)), h.last_seen),
    )


def _decide(identity, handles):
    """Confiance et certitude **effectives**, telles que le prompt les voit.

    Reprend ``IdentityResolver._resolve_context_sync`` : la certitude stockée
    est relevée au plancher du canal puis bornée par son plafond. Lire
    ``Identity.certainty`` brut afficherait une session authentifiée fraîche
    comme « inconnu » alors que le prompt la traite comme certaine.
    """
    handle = _best_handle(handles)
    channel_trust = _as_trust(handle.trust) if handle else ChannelTrust.PUBLIC
    stored = float(identity.certainty or 0.0)
    effective = max(stored, trust_policy.floor_for(channel_trust))
    name = (identity.entity.name if identity.entity_id else "") or identity.display_name
    return handle, trust_policy.evaluate(effective, channel_trust, name)


# ── Identités ───────────────────────────────────────────────────────────

def _identities(request) -> dict:
    from identity.models import Identity

    fs = tables.FilterSet(per_page=tables.read_per_page(request))
    search = fs.add(tables.search_filter(
        request, "q", "Recherche", placeholder="nom ou identifiant",
    ))
    scope = fs.add(tables.select_filter(
        request, "portee", "Portée",
        [("liees", "liées à une entité"), ("non_liees", "non liées"),
         ("divulgation", "au-dessus du seuil de divulgation")],
        all_label="Toutes",
    ))
    # Les handles éphémères (`anon_*`) sont masqués par défaut : sur la base
    # de développement il y avait 86 sockets pour 9 identités réelles, et une
    # carte annonçant « 95 » au-dessus d'un tableau de 9 se lit comme un
    # filtre cassé.
    ephemeral = fs.add(tables.select_filter(
        request, "ephemeres", "Éphémères",
        [("oui", "inclure les anon_*")], all_label="masqués",
    ))

    qs = Identity.objects.select_related("entity").prefetch_related("handles")
    if search.value:
        from django.db.models import Q
        # La jointure sur `handles` peut dupliquer une identité qui a plusieurs
        # handles correspondants — d'où le `distinct()`.
        qs = qs.filter(
            Q(display_name__icontains=search.value)
            | Q(entity__name__icontains=search.value)
            | Q(handles__person_id__icontains=search.value)
        ).distinct()
    qs = qs.order_by("-last_seen")

    rows = []
    for identity in qs:
        handles = list(identity.handles.all())
        if ephemeral.value != "oui":
            visible = [h for h in handles if not h.is_ephemeral]
            # Une identité sans aucun handle reste listée : une ligne orpheline
            # est un fait sur la base de données, pas un artefact d'affichage.
            if handles and not visible:
                continue
        handle, decision = _decide(identity, handles)
        if scope.value == "liees" and not identity.entity_id:
            continue
        if scope.value == "non_liees" and identity.entity_id:
            continue
        if scope.value == "divulgation" and not decision.may_disclose:
            continue
        rows.append({
            "obj": identity,
            "handle": handle,
            "decision": decision,
            "stored": float(identity.certainty or 0.0),
            "handles_count": len(handles),
        })

    total = len(rows)
    disclosing = sum(1 for r in rows if r["decision"].may_disclose)
    bound = sum(1 for r in rows if r["obj"].entity_id)

    return {
        "filterset": fs,
        "page": tables.paginate(request, rows, per_page=fs.per_page),
        "summary": {
            "total": total,
            "bound": bound,
            "disclosing": disclosing,
            "threshold": trust_policy.PRIVATE_CONTEXT_THRESHOLD,
        },
    }


def identity_detail(request, identity_id: int):
    from identity.models import Identity

    identity = (
        Identity.objects.select_related("entity")
        .prefetch_related("handles", "claims")
        .filter(pk=identity_id)
        .first()
    )
    if identity is None:
        raise Http404("Identité introuvable")

    handles = list(identity.handles.all())
    handle, decision = _decide(identity, handles)

    item = item_for("social")
    ctx = page_context(
        request, item=item, active_key="social", active_tab="identites",
        title=(identity.entity.name if identity.entity_id else None)
              or identity.display_name or f"Identité #{identity.pk}",
        description="Ce qu'elle croit savoir de cette personne, et pourquoi.",
    )
    ctx.update({
        "identity": identity,
        "handles": handles,
        "primary_handle": handle,
        "decision": decision,
        "stored": float(identity.certainty or 0.0),
        "claims": identity.claims.order_by("-created_at")[:100],
        "evidence_kinds": sorted(
            set(trust_policy.EVIDENCE_WEIGHTS) | set(trust_policy.COUNTER_EVIDENCE_WEIGHTS)
        ),
        "evidence_weights": trust_policy.EVIDENCE_WEIGHTS,
        "counter_weights": trust_policy.COUNTER_EVIDENCE_WEIGHTS,
        "threshold": trust_policy.PRIVATE_CONTEXT_THRESHOLD,
    })
    return render(request, "gestion/social/identite_detail.html", ctx)


# ── Écritures ───────────────────────────────────────────────────────────

def _resolver(request, coro_fn, *args, success: str, **kwargs) -> bool:
    """Exécute une coroutine du résolveur et rapporte son verdict.

    Le résolveur renvoie ``{"ok": False, "error": …}`` au lieu de lever :
    il est écrit pour des arguments venus d'un LLM, où une faute de frappe ne
    doit jamais casser un tour. Ici on remonte le refus à l'opérateur.
    """
    try:
        result = async_to_sync(coro_fn)(*args, **kwargs)
    except Exception as exc:
        logger.exception("écriture identité en échec")
        messages.error(request, f"Échec : {exc}")
        return False
    if isinstance(result, dict) and not result.get("ok", True):
        messages.error(request, result.get("error", "Écriture refusée."))
        return False
    if result is None:
        messages.error(request, "Écriture refusée (handle introuvable).")
        return False
    messages.success(request, success)
    return True


def _person_id_for(identity) -> str:
    handle = _best_handle(list(identity.handles.all()))
    return handle.person_id if handle else ""


@require_POST
def identity_action(request, identity_id: int):
    from identity.models import Identity
    from identity.resolver import identity_resolver

    identity = (
        Identity.objects.select_related("entity")
        .prefetch_related("handles").filter(pk=identity_id).first()
    )
    if identity is None:
        raise Http404("Identité introuvable")

    action = request.POST.get("action", "")
    person_id = _person_id_for(identity)
    back = reverse("gestionsysteme:identity-detail", args=[identity.pk])

    if not person_id:
        messages.error(request, "Cette identité n'a aucun handle à manipuler.")
        return redirect(back)

    if action == "lier":
        entity_name = (request.POST.get("entity_name") or "").strip()
        if not entity_name:
            messages.error(request, "Nom d'entité requis.")
            return redirect(back)
        _resolver(
            request, identity_resolver.link_entity, person_id, entity_name,
            success=f"Handle lié à « {entity_name} ».",
        )

    elif action == "preuve":
        kind = (request.POST.get("kind") or "").strip()
        known = set(trust_policy.EVIDENCE_WEIGHTS) | set(trust_policy.COUNTER_EVIDENCE_WEIGHTS)
        if kind not in known:
            messages.error(request, f"Type de preuve inconnu : {kind or '(vide)'}")
            return redirect(back)
        _resolver(
            request, identity_resolver.record_evidence, person_id,
            kind=kind,
            detail=(request.POST.get("detail") or "Saisi depuis Gestion Système"),
            name=(request.POST.get("name") or ""),
            success=f"Preuve « {kind} » enregistrée.",
        )

    elif action == "revoquer":
        # Délibérément pas une suppression : le registre conserve pourquoi
        # elle a cru, et pourquoi elle a cessé.
        _resolver(
            request, identity_resolver.revoke, person_id,
            reason=(request.POST.get("reason") or "Révoqué depuis Gestion Système"),
            success="Liaison révoquée. Le registre de preuves est conservé.",
        )

    else:
        messages.error(request, "Action inconnue.")

    return redirect(back)


@require_POST
def claim_action(request, claim_id: int):
    from identity.resolver import identity_resolver

    action = request.POST.get("action", "")
    back = request.POST.get("retour") or reverse("gestionsysteme:social-tab", args=["demandes"])

    if action == "accepter":
        _resolver(
            request, identity_resolver.accept_claim, claim_id,
            reason=(request.POST.get("reason") or "Accepté depuis Gestion Système"),
            evidence_kind=(request.POST.get("evidence_kind") or ""),
            success="Revendication acceptée.",
        )
    elif action == "rejeter":
        _resolver(
            request, identity_resolver.reject_claim, claim_id,
            reason=(request.POST.get("reason") or "Rejeté depuis Gestion Système"),
            success="Revendication rejetée.",
        )
    else:
        messages.error(request, "Action inconnue.")
    return redirect(back)


# ── Revendications ──────────────────────────────────────────────────────

def _claims(request) -> dict:
    from identity.models import IdentityClaim

    fs = tables.FilterSet(per_page=tables.read_per_page(request))
    status = fs.add(tables.select_filter(
        request, "statut", "État",
        [(v, l) for v, l in IdentityClaim.Status.choices],
        default="pending", all_label="Toutes",
    ))
    kind = fs.add(tables.select_filter(
        request, "type", "Type", [(v, l) for v, l in IdentityClaim.Kind.choices],
    ))

    qs = IdentityClaim.objects.select_related("identity", "identity__entity", "handle")
    if status.value:
        qs = qs.filter(status=status.value)
    if kind.value:
        qs = qs.filter(kind=kind.value)
    qs = qs.order_by("-created_at")

    return {
        "filterset": fs,
        "page": tables.paginate(request, qs, per_page=fs.per_page),
        "evidence_kinds": sorted(trust_policy.EVIDENCE_WEIGHTS),
    }


# ── Personnes ───────────────────────────────────────────────────────────

def _persons(request) -> dict:
    from django.db.models import Count

    from memory.models import Commitment, Entity

    fs = tables.FilterSet(per_page=tables.read_per_page(request))
    search = fs.add(tables.search_filter(request, "q", "Recherche", placeholder="nom"))

    qs = (
        Entity.objects.filter(entity_type="person")
        .select_related("profile")
        .order_by("-profile__last_interaction_at", "name")
    )
    if search.value:
        qs = qs.filter(name__icontains=search.value)

    page = tables.paginate(request, qs, per_page=fs.per_page)

    # Engagements en attente par personne, en une agrégation (évite le N+1).
    pending = {
        row["person_id"]: row["n"]
        for row in Commitment.objects.filter(status="pending")
        .values("person_id").annotate(n=Count("id"))
    }
    for entity in page.rows:
        entity.pending_commitments = pending.get(entity.id, 0)

    return {"filterset": fs, "page": page}


def person_detail(request, entity_id: int, tab: str | None = None):
    """Fiche d'une personne, en onglets.

    Une seule page portait tout : théorie de l'esprit, affect, handles,
    engagements et souvenirs empilés, les souvenirs paginés quinze par quinze
    tout en bas. Les trois quarts de ce qu'on sait d'une personne n'y étaient
    pas du tout — ce qu'elle *sait* d'elle (connaissances), ce qu'elles se
    sont *dit* (messages), comment l'humeur a *bougé* (résumés affectifs).

    Découpé en onglets, chacun peut porter ses propres filtres et sa propre
    pagination, et l'onglet est un segment d'URL comme partout ailleurs ici.
    """
    from memory.models import Entity

    entity = (
        Entity.objects.filter(entity_type="person", id=entity_id)
        .select_related("profile").first()
    )
    if entity is None:
        raise Http404("Personne introuvable")

    current = resolve_tab(PERSON_TABS, tab)
    identities = _person_identities(entity_id)
    handles = [h for identity in identities for h in identity.handles.all()]
    # Les tables gardées par identifiant de transport (messages, instantanés
    # d'émotion, humeur vive) ne se joignent pas à une entité mémoire : elles
    # sont indexées par handle. C'est la couche identité qui fait le pont, et
    # c'est le seul pont — l'égalité par le nom est précisément le bug qu'elle
    # existe pour corriger.
    person_ids = sorted({h.person_id for h in handles})

    item = item_for("social")
    ctx = page_context(
        request, item=item, active_key="social", active_tab="personnes",
        title=entity.name,
        description="Ce que Mika sait de cette personne, et ce qu'elle lui a promis.",
    )
    ctx.update({
        "entity": entity,
        "profile": getattr(entity, "profile", None),
        "person_tabs": PERSON_TABS,
        "active_person_tab": current.key,
        "person_counts": _person_counts(entity, person_ids),
        "person_ids": person_ids,
        "orphan": None if person_ids else _orphan_hint(entity),
    })
    ctx.update({
        "synthese": _person_synthese,
        "souvenirs": _person_souvenirs,
        "connaissances": _person_connaissances,
        "echanges": _person_echanges,
        "affect": _person_affect,
        "engagements": _person_engagements,
    }[current.key](request, entity, identities, person_ids))
    return render(request, f"gestion/social/personne/{current.key}.html", ctx)


def _person_identities(entity_id: int) -> list:
    """Les identités liées à cette entité, handles compris.

    Interrogé par ``entity_id``, pas par nom : ``handles_for_entity_names``
    résout par ``entity__name``, ce qui suffit à son appelant (le routage par
    préoccupation part d'un nom) mais ferait dépendre cette page d'une égalité
    de chaîne là où elle tient déjà la clé primaire.
    """
    from identity.models import Identity

    return list(
        Identity.objects.filter(entity_id=entity_id)
        .prefetch_related("handles")
        .order_by("-last_seen")
    )


def _orphan_hint(entity) -> dict | None:
    """Ce qu'il manque, quand rien n'est lié — jamais ce qu'on suppose.

    Sur une base réelle les entités-personnes portent souvent le handle pour
    nom : tant que personne ne s'est présenté, le consolidateur nomme d'après
    l'identifiant de transport. L'égalité de nom **ne résout rien ici** — c'est
    exactement le rapprochement que la couche identité existe pour supprimer,
    et le faire silencieusement rendrait cette page complice du bug.

    Elle sert seulement à *nommer ce qu'il faudrait lier* : « un handle porte
    ce nom, il n'est lié à rien, et voilà combien de messages dorment dessus ».
    Un onglet vide se lit « ils ne se sont jamais parlé » ; ceci se lit
    « personne n'a fait la liaison ».
    """
    from identity.models import IdentityHandle
    from memory.models import Message

    handle = (
        IdentityHandle.objects.select_related("identity")
        .filter(person_id=entity.name)
        .order_by("-last_seen")
        .first()
    )
    if handle is None:
        return None
    return {
        "person_id": handle.person_id,
        "channel": handle.channel,
        "trust": handle.trust,
        "identity_id": handle.identity_id,
        "bound_elsewhere": handle.identity.entity_id,
        "messages": Message.objects.filter(person_id=handle.person_id).count(),
    }


def _person_counts(entity, person_ids: list[str]) -> dict:
    """Volumes par onglet, pour les pastilles de la sous-navigation.

    Six ``COUNT`` sur des colonnes indexées — c'est ce qui évite d'ouvrir un
    onglet pour découvrir qu'il est vide, et de croire qu'un onglet vide
    signifie « rien à dire » alors qu'il signifie souvent « aucun handle lié ».
    """
    from memory.models import Commitment, Connaissance, Message, Souvenir

    counts = {
        "souvenirs": Souvenir.objects.filter(entities=entity).count(),
        "connaissances": Connaissance.objects.filter(entities=entity).count(),
        "engagements": Commitment.objects.filter(person_id=entity.id).count(),
        "echanges": 0,
        "affect": 0,
    }
    if person_ids:
        from memory.models import EmotionSnapshot

        counts["echanges"] = Message.objects.filter(person_id__in=person_ids).count()
        counts["affect"] = EmotionSnapshot.objects.filter(
            person_id__in=person_ids,
        ).count()
    return counts


# ── Onglet : synthèse ───────────────────────────────────────────────────

def _person_synthese(request, entity, identities, person_ids) -> dict:
    from projects.models import Project

    verdicts = []
    for identity in identities:
        handles = list(identity.handles.all())
        handle, decision = _decide(identity, handles)
        verdicts.append({
            "obj": identity,
            "handle": handle,
            "handles": handles,
            "decision": decision,
            "stored": float(identity.certainty or 0.0),
        })

    return {
        "verdicts": verdicts,
        # La divulgation est ce qui décide si la fiche ci-dessus atteint le
        # prompt. Une personne dont aucune identité ne passe le seuil a beau
        # avoir un profil complet, il n'est jamais injecté — et rien ailleurs
        # sur cette page ne le dirait.
        "may_disclose": any(v["decision"].may_disclose for v in verdicts),
        "threshold": trust_policy.PRIVATE_CONTEXT_THRESHOLD,
        "affects": _live_affects(person_ids),
        "projects": list(
            Project.objects.filter(owner=entity).order_by("-updated_at")[:10],
        ),
    }


def _live_affects(person_ids: list[str]) -> list[dict]:
    """Humeurs vivantes envers cette personne (mémoire vive).

    Une par handle : l'oscillateur est tenu par identifiant de transport, donc
    quelqu'un joint sur le web et sur Telegram en a deux, qui n'ont aucune
    raison d'être au même endroit. Interroger avec la clé primaire de l'entité
    ne renvoyait jamais rien — c'est la même confusion entité/handle que la
    couche identité a été écrite pour supprimer.
    """
    if not person_ids:
        return []
    try:
        from emotion import pad
        from emotion.engine import emotion_engine

        out = []
        for person_id in person_ids:
            mood = emotion_engine.person_moods.get(person_id)
            if mood is None:
                continue
            label, intensity = pad.pad_to_label(mood.dynamic.position)
            out.append({
                "person_id": person_id,
                "emotion": label.value,
                "intensity": intensity,
                "velocity": pad.norm(mood.dynamic.velocity),
                "history_size": len(getattr(mood, "history", ()) or ()),
            })
        return out
    except Exception:
        logger.debug("affect vivant indisponible", exc_info=True)
        return []


# ── Onglet : souvenirs ──────────────────────────────────────────────────

_SOUVENIR_SORTS = {
    "recent": ("-occurred_at",),
    "important": ("-importance", "-occurred_at"),
}


def _person_souvenirs(request, entity, identities, person_ids) -> dict:
    from memory.models import Souvenir

    fs = tables.FilterSet(per_page=tables.read_per_page(request))
    search = fs.add(tables.search_filter(
        request, "q", "Recherche", placeholder="contenu du souvenir",
    ))
    order = fs.add(tables.select_filter(
        request, "tri", "Tri",
        [("recent", "les plus récents"), ("important", "les plus importants")],
        default="recent", all_label="les plus récents",
    ))

    qs = Souvenir.objects.filter(entities=entity).prefetch_related("themes")
    if search.value:
        qs = qs.filter(content__icontains=search.value)
    qs = qs.order_by(*_SOUVENIR_SORTS.get(order.value, _SOUVENIR_SORTS["recent"]))

    return {"filterset": fs, "page": tables.paginate(request, qs, per_page=fs.per_page)}


# ── Onglet : connaissances ──────────────────────────────────────────────

def _person_connaissances(request, entity, identities, person_ids) -> dict:
    from memory.models import Connaissance

    fs = tables.FilterSet(per_page=tables.read_per_page(request))
    search = fs.add(tables.search_filter(
        request, "q", "Recherche", placeholder="contenu du fait",
    ))
    validity = fs.add(tables.select_filter(
        request, "validite", "Validité",
        [("valides", "valides"), ("invalidees", "invalidées")],
        all_label="Toutes",
    ))

    qs = Connaissance.objects.filter(entities=entity).prefetch_related("themes")
    if search.value:
        qs = qs.filter(content__icontains=search.value)
    if validity.value == "valides":
        qs = qs.filter(is_valid=True)
    elif validity.value == "invalidees":
        qs = qs.filter(is_valid=False)
    qs = qs.order_by("-confidence", "-updated_at")

    return {"filterset": fs, "page": tables.paginate(request, qs, per_page=fs.per_page)}


# ── Onglet : échanges ───────────────────────────────────────────────────

def _person_echanges(request, entity, identities, person_ids) -> dict:
    from memory.models import Message

    fs = tables.FilterSet(per_page=tables.read_per_page(request))
    search = fs.add(tables.search_filter(
        request, "q", "Recherche", placeholder="contenu du message",
    ))
    role = fs.add(tables.select_filter(
        request, "role", "Rôle",
        [("user", "elle/lui"), ("assistant", "Mika")],
    ))
    handle = fs.add(tables.select_filter(
        request, "handle", "Handle",
        [(p, p) for p in person_ids],
        all_label="Tous",
    ))

    if not person_ids:
        # Sans handle lié, la question n'a pas de réponse — et une liste vide
        # se lirait comme « ils ne se sont jamais parlé », ce qui est faux.
        return {"filterset": None, "page": None, "no_handle": True}

    qs = Message.objects.filter(person_id__in=[handle.value] if handle.value else person_ids)
    if search.value:
        qs = qs.filter(content__icontains=search.value)
    if role.value:
        qs = qs.filter(role=role.value)
    qs = qs.order_by("-created_at")

    return {
        "filterset": fs,
        "page": tables.paginate(request, qs, per_page=fs.per_page),
        "no_handle": False,
    }


# ── Onglet : affect ─────────────────────────────────────────────────────

def _person_affect(request, entity, identities, person_ids) -> dict:
    from memory.models import EmotionalSummary, EmotionSnapshot

    if not person_ids:
        return {"no_handle": True, "summaries": [], "snapshots_page": None,
                "affects": []}

    period = tables.read_choice(request, "periode", ("daily", "weekly"), default="weekly")

    return {
        "no_handle": False,
        "affects": _live_affects(person_ids),
        "period": period,
        "summaries": list(
            EmotionalSummary.objects.filter(
                person_id__in=person_ids, period_type=period,
            ).order_by("-period_start")[:30],
        ),
        # Paginé sous son propre paramètre : les deux listes de cet onglet ne
        # doivent pas se déplacer ensemble.
        "snapshots_page": tables.paginate(
            request,
            EmotionSnapshot.objects.filter(person_id__in=person_ids),
            per_page=25, page_param="instantanes",
        ),
    }


# ── Onglet : engagements ────────────────────────────────────────────────

def _person_engagements(request, entity, identities, person_ids) -> dict:
    from memory.models import Commitment

    fs = tables.FilterSet(per_page=tables.read_per_page(request))
    status = fs.add(tables.select_filter(
        request, "statut", "État",
        [("pending", "en attente"), ("honored", "tenu"), ("dropped", "abandonné")],
        all_label="Tous",
    ))

    qs = Commitment.objects.filter(person_id=entity.id).select_related("source_souvenir")
    if status.value:
        qs = qs.filter(status=status.value)
    qs = qs.order_by("status", "-created_at")

    return {"filterset": fs, "page": tables.paginate(request, qs, per_page=fs.per_page)}


# ── Engagements ─────────────────────────────────────────────────────────

def _commitments(request) -> dict:
    from memory.models import Commitment

    fs = tables.FilterSet(per_page=tables.read_per_page(request))
    status = fs.add(tables.select_filter(
        request, "statut", "État",
        [("pending", "en attente"), ("honored", "tenu"), ("dropped", "abandonné")],
        default="pending", all_label="Tous",
    ))

    qs = Commitment.objects.select_related("person")
    if status.value:
        qs = qs.filter(status=status.value)
    qs = qs.order_by("status", "-created_at")

    return {"filterset": fs, "page": tables.paginate(request, qs, per_page=fs.per_page)}


# ── Politique ───────────────────────────────────────────────────────────

def _policy(request) -> dict:
    """Servi **depuis le module de politique**, jamais recopié.

    La page explique ses propres verdicts, et l'explication ne peut pas
    diverger de la politique qui tourne réellement.
    """
    from identity.models import IdentityClaim

    return {
        "levels": [
            {"name": level.name.lower(), "value": float(level)}
            for level in Certainty
        ],
        "evidence_weights": sorted(
            trust_policy.EVIDENCE_WEIGHTS.items(), key=lambda kv: -kv[1],
        ),
        "counter_weights": sorted(
            trust_policy.COUNTER_EVIDENCE_WEIGHTS.items(), key=lambda kv: kv[1],
        ),
        "channels": [
            {
                "trust": t.value,
                "floor": trust_policy.floor_for(t),
                "ceiling": trust_policy.ceiling_for(t),
            }
            for t in ChannelTrust
        ],
        "confident_threshold": trust_policy.CONFIDENT_THRESHOLD,
        "private_threshold": trust_policy.PRIVATE_CONTEXT_THRESHOLD,
        "claim_kinds": list(IdentityClaim.Kind.choices),
        "internal_ids": sorted(p for p in trust_policy.INTERNAL_PERSON_IDS if p),
        "ephemeral_prefix": trust_policy.EPHEMERAL_PERSON_PREFIX,
    }
