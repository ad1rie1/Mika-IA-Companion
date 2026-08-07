"""IdentityResolver — async R/W interface over the identity layer.

Turns the names conversation teaches into deliverable handles, and vice-versa,
and keeps track of how sure Mika is that the two belong together.

Three ways an identity gets established, in decreasing order of trust:

1. **Authenticated** — the web consumer verified a Django session. The link is
   proven and bound on the spot; no claim, no deliberation.
2. **Passive** — ``ingest_message`` reads "moi c'est Thomas" off a normal turn
   and files a claim. Nothing changes yet; the prompt tells Mika someone is
   asserting a name and she decides.
3. **Active** — Mika calls the ``identity_*`` tools to accept, reject, or
   revoke. Accepting is what actually binds the handle to a memory ``Entity``,
   which is what makes the whole theory-of-mind layer resolve.

Before this, ``link_entity`` existed but nothing ever called it: every
``Identity`` row carried ``entity_id = NULL``, so ``PersonProfile`` lookups
(``entity__name=person_id``) could never match — memory accumulated under
"Thomas" while the prompt asked about "web_6f3e22ccb0ae".

All ORM access is wrapped in ``sync_to_async`` (called from the async pipeline).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta

from asgiref.sync import sync_to_async
from django.utils import timezone

from identity import trust as trust_policy
from identity.detection import NameClaim, corroboration_score, detect_name_claim
from identity.trust import (
    Certainty,
    ChannelTrust,
    is_internal_person,
)
from utils.degradation import degradations

logger = logging.getLogger(__name__)

#: Facts pulled from memory to test a claim against. Small on purpose — this
#: runs inside a conversation turn.
MAX_CORROBORATION_FACTS = 12

#: Revendications presentees simultanement dans le prompt. Au-dela, la liste
#: n'aide plus Mika a trancher : elle noie le bloc identite (chaque ligne
#: coute ~50 tokens, renvoyes a chaque tour).
MAX_PENDING_CLAIMS_SHOWN = 3


@dataclass
class IdentityContext:
    """Everything the pipeline needs to know about who is on the other end.

    Built once per turn by ``resolve_context`` and threaded through the
    conversation context, so the prompt layer never has to re-query.
    """

    person_id: str
    channel: str = ""
    trust: ChannelTrust = ChannelTrust.PUBLIC
    certainty: float = 0.0
    #: Memory entity this handle is bound to, when Mika has settled on one.
    entity_id: int | None = None
    entity_name: str = ""
    #: Best display name available, bound or merely claimed.
    display_name: str = ""
    identity_id: int | None = None
    #: Unresolved claims Mika should be told about ("someone says they're X").
    pending_claims: list[dict] = field(default_factory=list)
    #: Whether per-person private memory may be injected this turn.
    may_disclose: bool = False
    #: French prompt line describing the situation.
    description: str = ""

    @property
    def is_identified(self) -> bool:
        """True when there is a memory entity to hang per-person context on."""
        return self.entity_id is not None

    @property
    def is_internal(self) -> bool:
        return is_internal_person(self.person_id)

    @property
    def known_as(self) -> str:
        """What to call them: bound name first, then claim, then handle."""
        return self.entity_name or self.display_name or self.person_id


class IdentityResolver:
    """Links transport handles ↔ canonical identities ↔ memory entities."""

    # ── Handle registration ───────────────────────────────────────

    async def link_handle(
        self,
        person_id: str,
        channel: str,
        kind: str = "module",
        delivery_ref: str = "",
        display_name: str = "",
        *,
        trust: ChannelTrust | str = ChannelTrust.PUBLIC,
        ephemeral: bool = False,
    ):
        """Persist that ``person_id`` is reachable on ``channel``.

        Upserts the handle (keyed by channel+person_id) and ensures it is
        attached to an Identity. Returns the Identity, or None on failure.
        Called when a consumer connects or a module sees a user.

        ``ephemeral`` marks a per-connection throwaway id (``anon_*``) so the
        retention sweep can reclaim it. Without the flag these accumulated
        forever: every reconnect minted a fresh Identity + handle that
        represented nobody.
        """
        return await sync_to_async(self._link_handle_sync)(
            person_id, channel, kind, delivery_ref, display_name,
            str(getattr(trust, "value", trust)), ephemeral,
        )

    def _link_handle_sync(
        self, person_id, channel, kind, delivery_ref, display_name,
        trust_value, ephemeral,
    ):
        from identity.models import Identity, IdentityHandle

        try:
            handle = IdentityHandle.objects.filter(
                channel=channel, person_id=person_id
            ).select_related("identity").first()

            if handle:
                if delivery_ref:
                    handle.delivery_ref = delivery_ref
                if display_name:
                    handle.display_name = display_name
                # Trust can be *raised* by a later connection (an anonymous
                # visitor logs in) but never silently lowered: a handle that
                # once authenticated stays trusted for proactive outreach.
                if _trust_rank(trust_value) > _trust_rank(handle.trust):
                    handle.trust = trust_value
                    handle.is_ephemeral = ephemeral
                handle.save(update_fields=[
                    "delivery_ref", "display_name", "trust", "is_ephemeral",
                    "last_seen",
                ])
                return handle.identity

            identity = Identity.objects.create(display_name=display_name)
            IdentityHandle.objects.create(
                identity=identity,
                channel=channel,
                person_id=person_id,
                kind=kind,
                delivery_ref=delivery_ref,
                display_name=display_name,
                trust=trust_value,
                is_ephemeral=ephemeral,
            )
            return identity
        except Exception as exc:
            degradations.record("identity.resolver.link_handle", exc)
            logger.warning(
                "link_handle failed for %s@%s", person_id, channel, exc_info=True
            )
            return None

    # ── Authenticated binding ─────────────────────────────────────

    async def bind_authenticated(
        self, person_id: str, channel: str, entity_name: str,
    ):
        """Bind a handle whose session the transport already verified.

        This is the one path that needs no deliberation: the browser proved
        it holds credentials we issued, so the handle *is* that account. The
        memory Entity is created eagerly under the account's display name so
        souvenirs and PersonProfile have something real to attach to from the
        very first turn.
        """
        return await sync_to_async(self._bind_authenticated_sync)(
            person_id, channel, entity_name,
        )

    def _bind_authenticated_sync(self, person_id, channel, entity_name):
        from identity.models import IdentityClaim, IdentityHandle
        from memory.models import Entity

        try:
            handle = IdentityHandle.objects.select_related("identity").filter(
                channel=channel, person_id=person_id,
            ).first()
            if handle is None:
                return None

            entity, _ = Entity.objects.get_or_create(
                name=entity_name, entity_type="person",
            )
            identity = handle.identity
            identity.entity = entity
            identity.certainty = float(Certainty.VERIFIED)
            identity.bound_at = timezone.now()
            identity.bound_via = channel
            identity.binding_reason = "Session authentifiee"
            if not identity.display_name:
                identity.display_name = entity_name
            identity.save(update_fields=[
                "entity", "certainty", "bound_at", "bound_via",
                "binding_reason", "display_name", "last_seen",
            ])

            # Recorded as an accepted claim too, so the ledger explains the
            # certainty rather than it appearing out of nowhere.
            IdentityClaim.objects.get_or_create(
                identity=identity,
                claimed_name=entity_name,
                kind=IdentityClaim.Kind.AUTHENTICATED,
                defaults={
                    "handle": handle,
                    "status": IdentityClaim.Status.ACCEPTED,
                    "evidence": f"Connexion authentifiee sur {channel}",
                    "channel": channel,
                    "trust": ChannelTrust.AUTHENTICATED.value,
                    "applied_weight": float(Certainty.VERIFIED),
                    "resolved_at": timezone.now(),
                },
            )
            return identity
        except Exception as exc:
            degradations.record("identity.resolver.bind_authenticated", exc)
            logger.warning(
                "bind_authenticated failed for %s@%s", person_id, channel,
                exc_info=True,
            )
            return None

    async def link_entity(self, person_id: str, entity_name: str):
        """Bind an identity (by one of its handles) to a memory person-entity.

        This is how "the handle tg_123" becomes known as "the person Bob" in
        memory, enabling concern-based routing from entity names to handles.
        Kept for callers that already know the answer; the deliberate path is
        ``accept_claim``.
        """
        return await sync_to_async(self._link_entity_sync)(
            person_id, entity_name, float(Certainty.BOUND), "",
        )

    def _link_entity_sync(self, person_id, entity_name, certainty, reason):
        from identity.models import IdentityHandle
        from memory.models import Entity

        try:
            handle = IdentityHandle.objects.select_related("identity").filter(
                person_id=person_id
            ).first()
            if not handle:
                return None
            entity, _ = Entity.objects.get_or_create(
                name=entity_name, entity_type="person"
            )
            identity = handle.identity
            identity.entity = entity
            identity.certainty = trust_policy.clamp(
                certainty, trust=_as_trust(handle.trust),
            )
            identity.bound_at = timezone.now()
            identity.bound_via = handle.channel
            if reason:
                identity.binding_reason = reason
            if not identity.display_name:
                identity.display_name = entity_name
            identity.save(update_fields=[
                "entity", "certainty", "bound_at", "bound_via",
                "binding_reason", "display_name", "last_seen",
            ])
            return identity
        except Exception as exc:
            degradations.record("identity.resolver.link_entity", exc)
            logger.warning(
                "link_entity failed for %s/%s", person_id, entity_name,
                exc_info=True,
            )
            return None

    # ── Per-turn resolution ───────────────────────────────────────

    async def resolve_context(
        self, person_id: str, *, channel: str = "", authenticated: bool = False,
        is_public: bool = False,
    ) -> IdentityContext:
        """Who is Mika talking to, and how sure is she — for one turn.

        Never raises: an identity failure must degrade to "unknown visitor",
        not break the conversation.
        """
        ctx = IdentityContext(person_id=person_id, channel=channel)
        if is_internal_person(person_id):
            ctx.trust = ChannelTrust.INTERNAL
            return ctx

        try:
            return await sync_to_async(self._resolve_context_sync)(
                person_id, channel, authenticated, is_public,
            )
        except Exception as exc:
            degradations.record("identity.resolver.resolve_context", exc)
            logger.debug("resolve_context failed for %s", person_id, exc_info=True)
            decision = trust_policy.evaluate(0.0, ChannelTrust.PUBLIC)
            ctx.may_disclose = decision.may_disclose
            ctx.description = decision.description
            return ctx

    def _resolve_context_sync(
        self, person_id, channel, authenticated, is_public=False,
    ) -> IdentityContext:
        from identity.models import IdentityClaim, IdentityHandle

        handle = IdentityHandle.objects.select_related(
            "identity", "identity__entity",
        ).filter(person_id=person_id).order_by("-last_seen").first()

        stored_trust = _as_trust(handle.trust) if handle else None
        resolved_trust = trust_policy.channel_trust(
            channel=channel or (handle.channel if handle else ""),
            authenticated=authenticated,
            is_group=is_public,
        )
        # The handle remembers what it was established with; the live request
        # may know better (a session just authenticated). Take the stronger —
        # except when *this* turn is happening in public, which is a property
        # of the room and overrides whatever the DM handle earned. Someone
        # Mika knows well from private messages is still just a voice in a
        # crowded room here, and her private history with them stays shut.
        if (
            stored_trust
            and not is_public
            and _trust_rank(stored_trust.value) > _trust_rank(resolved_trust.value)
        ):
            resolved_trust = stored_trust

        ctx = IdentityContext(
            person_id=person_id,
            channel=channel or (handle.channel if handle else ""),
            trust=resolved_trust,
        )

        if handle is None:
            decision = trust_policy.evaluate(
                trust_policy.floor_for(resolved_trust), resolved_trust,
            )
            ctx.certainty = decision.certainty
            ctx.may_disclose = decision.may_disclose
            ctx.description = decision.description
            return ctx

        identity = handle.identity
        ctx.identity_id = identity.pk
        ctx.display_name = identity.display_name or handle.display_name
        entity = identity.entity
        if entity is not None:
            ctx.entity_id = entity.pk
            ctx.entity_name = entity.name

        certainty = max(
            float(identity.certainty or 0.0),
            trust_policy.floor_for(resolved_trust),
        )

        # Une revendication qu'on n'a pas tranchee finit par se perimer : elle
        # cesse d'etre presentee au-dela de PENDING_CLAIM_TTL_DAYS, et le
        # balayage de retention la classe alors « rejetee ». Sans cette borne
        # elle revenait dans le prompt a chaque tour indefiniment, et faisait
        # basculer la description en niveau CLAIMED avec elle.
        cutoff = timezone.now() - timedelta(
            days=trust_policy.PENDING_CLAIM_TTL_DAYS,
        )
        ctx.pending_claims = [
            {
                "id": c.pk,
                "name": c.claimed_name,
                "kind": c.kind,
                "evidence": c.evidence,
                "created_at": c.created_at.isoformat(),
            }
            for c in IdentityClaim.objects.filter(
                identity=identity, status=IdentityClaim.Status.PENDING,
                created_at__gte=cutoff,
            ).order_by("-created_at")[:MAX_PENDING_CLAIMS_SHOWN]
        ]

        # Name her the person by the strongest label available: the binding
        # if there is one, else what they say they are called.
        claimed_name = ctx.pending_claims[0]["name"] if ctx.pending_claims else ""
        name = ctx.entity_name or ctx.display_name or claimed_name

        decision = trust_policy.evaluate(certainty, resolved_trust, name)
        ctx.certainty = decision.certainty
        ctx.may_disclose = decision.may_disclose
        ctx.description = decision.description

        # An unresolved claim *is* the CLAIMED situation, whatever the stored
        # certainty says — the claim is deliberately not scored until Mika
        # accepts it. Describing that as "you think you can guess" would be
        # wrong: she isn't guessing, she was told and hasn't decided yet.
        # Only the wording changes; may_disclose still answers to the real
        # certainty, so being told a name unlocks nothing.
        if ctx.pending_claims and certainty < float(Certainty.CLAIMED):
            ctx.description = trust_policy.describe_fr(
                float(Certainty.CLAIMED), resolved_trust, name,
            )
        return ctx

    # ── Passive ingestion ─────────────────────────────────────────

    async def ingest_message(
        self, person_id: str, message: str, *, channel: str = "",
        authenticated: bool = False,
    ) -> NameClaim | None:
        """Read a turn for self-identification and file a claim if found.

        Called on every inbound message. Returns the detected claim (for
        logging/tests) or None, which is the normal case.

        On an authenticated channel a name claim is not evidence of identity
        — we already know who this is — but it *is* how Mika learns what to
        call someone, so the display name is updated and nothing else moves.
        """
        if is_internal_person(person_id) or not message:
            return None

        claim = detect_name_claim(message)
        if claim is None:
            return None

        try:
            await sync_to_async(self._file_claim_sync)(
                person_id, channel, authenticated, claim, message,
            )
        except Exception as exc:
            degradations.record("identity.resolver.ingest_message", exc)
            logger.debug("ingest_message failed for %s", person_id, exc_info=True)
        return claim

    def _file_claim_sync(
        self, person_id, channel, authenticated, claim: NameClaim, message: str,
    ) -> None:
        from identity.models import IdentityClaim, IdentityHandle

        handle = IdentityHandle.objects.select_related("identity").filter(
            person_id=person_id
        ).order_by("-last_seen").first()
        if handle is None:
            return
        identity = handle.identity
        resolved_trust = _as_trust(handle.trust)
        if authenticated:
            resolved_trust = ChannelTrust.AUTHENTICATED

        if claim.is_denial:
            self._apply_denial(identity, handle, claim, resolved_trust, channel)
            return

        # Authenticated: the identity is settled, so this is a naming
        # preference, not a claim to weigh.
        if resolved_trust is ChannelTrust.AUTHENTICATED:
            if identity.display_name != claim.name:
                identity.display_name = claim.name
                identity.save(update_fields=["display_name", "last_seen"])
            return

        # Already bound to this very name — re-asserting it proves nothing new.
        if identity.entity and identity.entity.name.lower() == claim.name.lower():
            return

        # Don't stack duplicates: the same pending assertion re-sent every
        # message would otherwise fill the ledger and the prompt.
        existing = IdentityClaim.objects.filter(
            identity=identity,
            claimed_name__iexact=claim.name,
            status=IdentityClaim.Status.PENDING,
        ).first()
        if existing:
            return

        IdentityClaim.objects.create(
            identity=identity,
            handle=handle,
            claimed_name=claim.name,
            kind=IdentityClaim.Kind.SELF_DECLARED,
            evidence=claim.evidence or message[:280],
            channel=channel or handle.channel,
            trust=resolved_trust.value,
        )
        logger.info(
            "Identity claim filed: %s says they are %r (%s, trust=%s)",
            person_id, claim.name, claim.kind, resolved_trust.value,
        )

    @staticmethod
    def _apply_denial(identity, handle, claim, resolved_trust, channel) -> None:
        """Someone rejecting the name Mika uses for them.

        Denial is cheap to make and expensive to ignore — if she is calling a
        stranger by a friend's name, everything downstream is wrong. So it
        applies immediately rather than waiting for Mika to deliberate, and
        it unbinds when it targets the current binding.
        """
        from identity.models import IdentityClaim

        IdentityClaim.objects.create(
            identity=identity,
            handle=handle,
            claimed_name=claim.name,
            kind=IdentityClaim.Kind.DENIED,
            status=IdentityClaim.Status.ACCEPTED,
            evidence=claim.evidence,
            channel=channel or handle.channel,
            trust=resolved_trust.value,
            applied_weight=trust_policy.COUNTER_EVIDENCE_WEIGHTS["denied"],
            resolution_note="Denegation prise en compte immediatement",
            resolved_at=timezone.now(),
        )
        identity.certainty = trust_policy.apply_evidence(
            float(identity.certainty or 0.0), "denied", trust=resolved_trust,
        )
        fields = ["certainty", "last_seen"]
        bound_name = identity.entity.name.lower() if identity.entity else ""
        if bound_name and bound_name == claim.name.lower():
            identity.entity = None
            identity.binding_reason = f"Denegation: « {claim.evidence} »"
            fields += ["entity", "binding_reason"]
        identity.save(update_fields=fields)
        logger.info(
            "Identity denial recorded for %s (not %r) — certainty now %.2f",
            handle.person_id, claim.name, identity.certainty,
        )

    # ── Corroboration ─────────────────────────────────────────────

    async def check_corroboration(
        self, message: str, claimed_name: str,
    ) -> tuple[float, str]:
        """Does this message line up with what Mika knows about ``claimed_name``?

        The honest way to earn trust without a login: mention something only
        that person would bring up. Returns ``(score, reason)`` — a hint for
        Mika, never an automatic promotion.

        Deliberately independent of who is speaking: it scores the *text*
        against what memory holds about a name. Who said it is the caller's
        business, and threading a person_id through here only ever looked
        like it mattered.
        """
        if not message or not claimed_name:
            return 0.0, ""
        try:
            facts = await sync_to_async(self._facts_about)(claimed_name)
        except Exception as exc:
            degradations.record("identity.resolver.check_corroboration", exc)
            logger.debug("corroboration lookup failed", exc_info=True)
            return 0.0, ""
        return corroboration_score(message, facts)

    @staticmethod
    def _facts_about(entity_name: str) -> list[str]:
        from memory.models import Connaissance, Entity, Souvenir

        entity = Entity.objects.filter(
            name__iexact=entity_name, entity_type="person",
        ).first()
        if entity is None:
            return []
        facts = list(
            Connaissance.objects.filter(entities=entity, is_valid=True)
            .order_by("-confidence")
            .values_list("content", flat=True)[:MAX_CORROBORATION_FACTS]
        )
        remaining = MAX_CORROBORATION_FACTS - len(facts)
        if remaining > 0:
            facts += list(
                Souvenir.objects.filter(entities=entity)
                .order_by("-importance")
                .values_list("content", flat=True)[:remaining]
            )
        return facts

    # ── Active resolution (driven by Mika's tools) ────────────────

    async def accept_claim(
        self, claim_id: int, *, reason: str = "", evidence_kind: str = "",
    ) -> dict:
        """Mika decides to believe a pending claim — the "convince me" outcome.

        Binds the handle to the memory Entity named in the claim (creating it
        if conversation hasn't produced one yet) and raises certainty by the
        weight of the evidence, capped by the channel ceiling. A public-room
        claim therefore lands lower than the same claim in a DM, which is the
        whole point.
        """
        return await sync_to_async(self._accept_claim_sync)(
            claim_id, reason, evidence_kind,
        )

    def _accept_claim_sync(self, claim_id, reason, evidence_kind) -> dict:
        from identity.models import IdentityClaim
        from memory.models import Entity

        try:
            claim = IdentityClaim.objects.select_related(
                "identity", "handle",
            ).get(pk=claim_id)
        except IdentityClaim.DoesNotExist:
            return {"ok": False, "error": "claim introuvable"}
        if claim.status != IdentityClaim.Status.PENDING:
            return {"ok": False, "error": f"claim deja {claim.status}"}

        identity = claim.identity
        claim_trust = _as_trust(claim.trust)
        before = float(identity.certainty or 0.0)

        # The claim was filed but never scored — pending means "not counted
        # yet". Accepting it counts the assertion itself, and then whatever
        # convinced her on top. That pairing is the calibration the weights
        # were chosen for: a bare claim stays under the disclosure bar, while
        # "they said who they are AND proved something only that person would
        # know" lands exactly on it. Scoring the corroboration alone left Mika
        # bound to a person whose history she still wasn't allowed to recall.
        after = trust_policy.apply_evidence(before, claim.kind, trust=claim_trust)
        if evidence_kind and evidence_kind != claim.kind:
            after = trust_policy.apply_evidence(
                after, evidence_kind, trust=claim_trust,
            )

        entity, _ = Entity.objects.get_or_create(
            name=claim.claimed_name, entity_type="person",
        )
        identity.entity = entity
        identity.certainty = after
        identity.bound_at = timezone.now()
        identity.bound_via = claim.channel or identity.bound_via
        identity.binding_reason = reason or f"Claim #{claim.pk} acceptee"
        if not identity.display_name:
            identity.display_name = claim.claimed_name
        identity.save(update_fields=[
            "entity", "certainty", "bound_at", "bound_via",
            "binding_reason", "display_name", "last_seen",
        ])

        claim.status = IdentityClaim.Status.ACCEPTED
        claim.applied_weight = round(after - before, 4)
        claim.resolution_note = reason
        claim.resolved_at = timezone.now()
        if evidence_kind:
            claim.kind = evidence_kind
        claim.save(update_fields=[
            "status", "applied_weight", "resolution_note", "resolved_at", "kind",
        ])

        logger.info(
            "Identity claim #%d accepted: %s ← %s (certainty %.2f → %.2f)",
            claim.pk, claim.claimed_name,
            claim.handle.person_id if claim.handle else "?", before, after,
        )
        return {
            "ok": True,
            "name": claim.claimed_name,
            "entity_id": entity.pk,
            "certainty": round(after, 3),
            "level": trust_policy.label_for(after).name.lower(),
            "capped_by_channel": after >= trust_policy.ceiling_for(claim_trust),
        }

    async def reject_claim(self, claim_id: int, *, reason: str = "") -> dict:
        """Mika decides not to believe a claim. Records the doubt."""
        return await sync_to_async(self._reject_claim_sync)(claim_id, reason)

    def _reject_claim_sync(self, claim_id, reason) -> dict:
        from identity.models import IdentityClaim

        try:
            claim = IdentityClaim.objects.select_related("identity").get(pk=claim_id)
        except IdentityClaim.DoesNotExist:
            return {"ok": False, "error": "claim introuvable"}
        if claim.status != IdentityClaim.Status.PENDING:
            return {"ok": False, "error": f"claim deja {claim.status}"}

        claim.status = IdentityClaim.Status.REJECTED
        claim.resolution_note = reason
        claim.resolved_at = timezone.now()
        claim.save(update_fields=["status", "resolution_note", "resolved_at"])
        logger.info("Identity claim #%d rejected: %s", claim.pk, reason or "(sans raison)")
        return {"ok": True, "name": claim.claimed_name}

    async def record_evidence(
        self, person_id: str, *, kind: str, detail: str, name: str = "",
    ) -> dict:
        """Add a piece of evidence for or against the current binding.

        This is how corroboration ("elle a mentionne le concert dont seule
        Alice m'avait parle") and contradiction ("il ne sait pas de quoi je
        parle") move certainty outside the accept/reject flow.
        """
        return await sync_to_async(self._record_evidence_sync)(
            person_id, kind, detail, name,
        )

    def _record_evidence_sync(self, person_id, kind, detail, name) -> dict:
        from identity.models import IdentityClaim, IdentityHandle

        handle = IdentityHandle.objects.select_related(
            "identity", "identity__entity",
        ).filter(person_id=person_id).order_by("-last_seen").first()
        if handle is None:
            return {"ok": False, "error": f"aucun contact connu pour {person_id}"}

        identity = handle.identity
        handle_trust = _as_trust(handle.trust)
        target = name or (identity.entity.name if identity.entity else "")
        if not target:
            return {"ok": False, "error": "aucun nom a corroborer — precise `name`"}

        before = float(identity.certainty or 0.0)
        after = trust_policy.apply_evidence(before, kind, trust=handle_trust)

        status = IdentityClaim.Status.ACCEPTED
        IdentityClaim.objects.create(
            identity=identity, handle=handle, claimed_name=target,
            kind=kind if kind in dict(IdentityClaim.Kind.choices)
            else IdentityClaim.Kind.PASSIVE_INFERENCE,
            status=status,
            evidence=detail, channel=handle.channel, trust=handle_trust.value,
            applied_weight=round(after - before, 4),
            resolved_at=timezone.now(),
        )

        identity.certainty = after
        fields = ["certainty", "last_seen"]
        # Strong counter-evidence unbinds: keeping the link while saying "she
        # is probably not who I thought" is how private context leaks.
        if after < float(Certainty.CLAIMED) and identity.entity_id:
            identity.entity = None
            identity.binding_reason = f"Doute: {detail[:200]}"
            fields += ["entity", "binding_reason"]
        identity.save(update_fields=fields)

        return {
            "ok": True, "name": target,
            "certainty": round(after, 3),
            "level": trust_policy.label_for(after).name.lower(),
            "unbound": "entity" in fields,
        }

    async def revoke(self, person_id: str, *, reason: str = "") -> dict:
        """Drop the binding entirely — "ce n'est pas qui je croyais"."""
        return await self.record_evidence(
            person_id, kind="revoked", detail=reason or "Revocation manuelle",
        )

    # ── Lookups (delivery routing) ────────────────────────────────

    async def handles_for_person(self, person_id: str) -> list[dict]:
        """All persisted handles for the identity owning ``person_id``."""
        return await sync_to_async(self._handles_for_person_sync)(person_id)

    def _handles_for_person_sync(self, person_id) -> list[dict]:
        from identity.models import IdentityHandle

        handle = IdentityHandle.objects.select_related("identity").filter(
            person_id=person_id
        ).first()
        if not handle:
            return []
        return [
            {
                "person_id": h.person_id,
                "channel": h.channel,
                "kind": h.kind,
                "delivery_ref": h.delivery_ref,
                "display_name": h.display_name,
            }
            for h in handle.identity.handles.all()
        ]

    async def handles_for_entity_names(self, names: list[str]) -> dict[str, list[dict]]:
        """Map each person-entity name → its reachable handles (durable view).

        Used by concern-based routing: memory says "X is concerned", this returns
        how to reach X. Reachability *now* is then filtered via the presence
        registry by the caller.
        """
        if not names:
            return {}
        return await sync_to_async(self._handles_for_entity_names_sync)(names)

    def _handles_for_entity_names_sync(self, names) -> dict[str, list[dict]]:
        from identity.models import Identity

        out: dict[str, list[dict]] = {}
        identities = Identity.objects.filter(
            entity__name__in=names, entity__entity_type="person"
        ).select_related("entity").prefetch_related("handles")
        for ident in identities:
            key = ident.entity.name if ident.entity else ident.display_name
            handles = [
                {
                    "person_id": h.person_id,
                    "channel": h.channel,
                    "kind": h.kind,
                    "delivery_ref": h.delivery_ref,
                    "display_name": h.display_name,
                }
                for h in ident.handles.all()
            ]
            out.setdefault(key, []).extend(handles)
        return out

    async def display_names_for(self, person_ids: list[str]) -> dict[str, str]:
        """Nom lisible de chaque handle — « Alice », pas ``web_6f3e22ccb0ae``.

        Pour l'historique conversationnel : le tampon court terme est
        deliberement partage par tout le monde, donc un tour peut venir de
        quelqu'un d'autre que l'interlocuteur courant, et le designer par son
        handle n'apprend rien au modele.

        Une seule requete pour tous les handles demandes. Un handle dont
        personne ne connait le nom est simplement absent du resultat :
        l'appelant decide quoi dire d'un inconnu, cette couche ne fabrique
        pas de nom.
        """
        ids = [p for p in person_ids if p and not is_internal_person(p)]
        if not ids:
            return {}
        return await sync_to_async(self._display_names_for_sync)(ids)

    @staticmethod
    def _display_names_for_sync(person_ids) -> dict[str, str]:
        from identity.models import IdentityHandle

        out: dict[str, str] = {}
        # Ordre croissant sur `last_seen` : quand deux handles partagent un
        # person_id, le plus recent ecrase le precedent — meme regle que
        # `_entity_for_person_sync`, exprimee dans l'autre sens parce qu'ici
        # on remplit un dictionnaire au lieu de prendre le premier.
        handles = IdentityHandle.objects.select_related(
            "identity", "identity__entity",
        ).filter(person_id__in=person_ids).order_by("last_seen")
        for handle in handles:
            entity = handle.identity.entity
            name = (
                (entity.name if entity else "")
                or handle.identity.display_name
                or handle.display_name
            )
            if name:
                out[handle.person_id] = name
        return out

    async def entity_for_person(self, person_id: str):
        """The memory Entity bound to this handle, or None.

        The single lookup every per-person memory read should go through —
        ``entity__name=person_id`` only ever worked by accident.
        """
        if is_internal_person(person_id):
            return None
        return await sync_to_async(self._entity_for_person_sync)(person_id)

    @staticmethod
    def _entity_for_person_sync(person_id):
        from identity.models import IdentityHandle

        handle = IdentityHandle.objects.select_related(
            "identity", "identity__entity",
        ).filter(person_id=person_id).order_by("-last_seen").first()
        if handle is None or handle.identity.entity_id is None:
            return None
        return handle.identity.entity

    # ── Presence (restauration au demarrage) ──────────────────────

    async def restore_module_presence(self) -> int:
        """Reinscrit les handles durables de type module dans la presence.

        Deux definitions de « joignable » cohabitaient et divergeaient apres
        chaque redemarrage : le routage par concernement lit la couche
        durable (« external API : joignable tant qu'on tient le chat_id »),
        la livraison lit le registre de presence, qui est en RAM et
        process-local et n'etait alimente qu'a la reception d'un message
        entrant. Resultat : un message proactif compose pour un contact
        Telegram qui n'avait pas ecrit depuis le boot etait persiste puis
        abandonne, sans rattrapage possible — le curseur ``sync`` est un
        mecanisme WebSocket, Telegram ne le rejoue jamais.

        Les consumers ne sont deliberement pas restaures : un WebSocket
        n'est joignable que tant qu'il est connecte, et son handle ne prouve
        rien apres un redemarrage.

        Retourne le nombre de handles reinscrits.
        """
        return await sync_to_async(self._restore_module_presence_sync)()

    @staticmethod
    def _restore_module_presence_sync() -> int:
        from communication.presence import presence_registry
        from identity.models import IdentityHandle

        restored = 0
        handles = IdentityHandle.objects.filter(
            kind="module", is_ephemeral=False,
        ).order_by("last_seen")
        for handle in handles:
            presence_registry.register(
                person_id=handle.person_id,
                channel=handle.channel,
                kind="module",
                delivery_ref=handle.delivery_ref,
                display_name=handle.display_name,
            )
            restored += 1
        return restored


def _as_trust(value: str | ChannelTrust | None) -> ChannelTrust:
    """Coerce a stored trust string into the enum, defaulting to PUBLIC."""
    if isinstance(value, ChannelTrust):
        return value
    try:
        return ChannelTrust(value)
    except (ValueError, TypeError):
        return ChannelTrust.PUBLIC


_TRUST_ORDER = {
    ChannelTrust.INTERNAL.value: 0,
    ChannelTrust.PUBLIC.value: 1,
    ChannelTrust.ACCOUNT.value: 2,
    ChannelTrust.AUTHENTICATED.value: 3,
}


def _trust_rank(value: str | ChannelTrust | None) -> int:
    return _TRUST_ORDER.get(str(getattr(value, "value", value)), 1)


identity_resolver = IdentityResolver()
