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
from GestionSysteme.nav import item_for
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


def person_detail(request, entity_id: int):
    from memory.models import Commitment, Entity, Souvenir

    entity = (
        Entity.objects.filter(entity_type="person", id=entity_id)
        .select_related("profile").first()
    )
    if entity is None:
        raise Http404("Personne introuvable")

    item = item_for("social")
    ctx = page_context(
        request, item=item, active_key="social", active_tab="personnes",
        title=entity.name,
        description="Ce que Mika sait de cette personne, et ce qu'elle lui a promis.",
    )
    ctx.update({
        "entity": entity,
        "profile": getattr(entity, "profile", None),
        "commitments": Commitment.objects.filter(person_id=entity_id).order_by(
            "status", "-created_at",
        )[:50],
        "souvenirs_page": tables.paginate(
            request,
            Souvenir.objects.filter(entities=entity).order_by("-occurred_at"),
            per_page=15,
        ),
        "affect": _live_affect(entity_id),
        "handles": _handles_for_entity(entity.name),
    })
    return render(request, "gestion/social/personne_detail.html", ctx)


def _live_affect(entity_id: int) -> dict | None:
    """Humeur vivante envers cette personne (mémoire vive).

    L'appariement se fait sur une clé fondée sur l'identifiant, jamais sur le
    nom affiché : c'est précisément l'égalité par le nom qui avait laissé la
    théorie de l'esprit renvoyer du vide sur chaque tour.
    """
    try:
        from emotion import pad
        from emotion.engine import emotion_engine

        key = str(entity_id)
        mood = emotion_engine.person_moods.get(key)
        if mood is None:
            return None
        label, intensity = pad.pad_to_label(mood.dynamic.position)
        return {
            "emotion": label.value,
            "intensity": intensity,
            "velocity": pad.norm(mood.dynamic.velocity),
            "history_size": len(getattr(mood, "history", ()) or ()),
        }
    except Exception:
        logger.debug("affect vivant indisponible", exc_info=True)
        return None


def _handles_for_entity(name: str) -> list[dict]:
    try:
        from identity.resolver import identity_resolver
        mapping = async_to_sync(identity_resolver.handles_for_entity_names)([name])
        return mapping.get(name, [])
    except Exception:
        logger.debug("handles de l'entité indisponibles", exc_info=True)
        return []


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
