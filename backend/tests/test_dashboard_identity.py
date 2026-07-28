"""Dashboard identity page — the half of "who is this person" that had no UI.

The person fiche shows what memory holds about an Entity. Nothing showed
the handle side: which transport handle is bound to it, how sure Mika is,
and whether that certainty clears the disclosure bar. A pending claim
could only ever be resolved by Mika's own MCP tools, so an operator
watching a stranger be greeted by a friend's name had no lever at all.

These tests pin the three properties that make the page trustworthy:

1. it reports the *effective* certainty the prompt uses (floor-raised,
   ceiling-clamped), not the raw column — the two differ exactly where it
   matters, on a channel that grants a floor;
2. ``may_disclose`` matches ``trust.may_disclose_private_context``, since
   that flag is the page's whole reason to exist;
3. every write goes through ``identity_resolver``, so accepting a claim
   from the dashboard produces the same binding, weight and ceiling as
   accepting it from a tool call.
"""
from __future__ import annotations

import json

import pytest
from django.test import Client
from django.urls import reverse

from identity.models import Identity, IdentityClaim, IdentityHandle
from identity.trust import Certainty, ChannelTrust
from memory.models import Entity


pytestmark = pytest.mark.django_db


@pytest.fixture
def client() -> Client:
    return Client()


def _identity(*, name="", entity=None, certainty=0.0):
    return Identity.objects.create(
        display_name=name, entity=entity, certainty=certainty,
    )


def _handle(identity, *, person_id, channel="telegram", trust="account",
            ephemeral=False):
    return IdentityHandle.objects.create(
        identity=identity, person_id=person_id, channel=channel,
        trust=trust, is_ephemeral=ephemeral,
    )


def _claim(identity, handle, *, name="Thomas", kind="self_declared",
           status=IdentityClaim.Status.PENDING, channel="telegram",
           trust="account"):
    return IdentityClaim.objects.create(
        identity=identity, handle=handle, claimed_name=name, kind=kind,
        status=status, channel=channel, trust=trust,
        evidence="moi c'est Thomas",
    )


def _rows(client, url):
    res = client.get(url)
    assert res.status_code == 200
    return json.loads(res.content)


# ── Page + routing ──────────────────────────────────────────────

class TestPage:

    def test_page_renders(self, client):
        res = client.get(reverse("dash-identity"))
        assert res.status_code == 200

    def test_sits_in_the_social_group_before_persons(self):
        """Ordered like the prompt assembles it: identity qualifies the fiche.

        ``--- QUI TU AS EN FACE ---`` is injected immediately before
        ``--- CE QUE TU SAIS DE CETTE PERSONNE ---``; a sidebar that
        reversed them would suggest the fiche stands on its own.
        """
        from dashboard.views.pages import MENU

        social = next(g for g in MENU if g["group"] == "Social")
        keys = [i["key"] for i in social["items"]]
        assert keys.index("identity") < keys.index("persons")

    def test_has_a_title(self):
        from dashboard.views.pages import TITLES

        assert "identity" in TITLES


# ── Listing ─────────────────────────────────────────────────────

class TestIdentityList:

    def test_lists_identity_with_handles_and_entity(self, client):
        entity = Entity.objects.create(name="Thomas", entity_type="person")
        identity = _identity(name="Thomas", entity=entity, certainty=0.85)
        _handle(identity, person_id="tg_1")

        data = _rows(client, "/dashboard/api/identity")
        assert data["total"] == 1
        row = data["rows"][0]
        assert row["entity"]["name"] == "Thomas"
        assert row["handles"][0]["person_id"] == "tg_1"
        assert row["level"] == "bound"

    def test_reports_effective_certainty_not_the_stored_column(self, client):
        """An authenticated handle is VERIFIED even at certainty 0.

        ``resolve_context`` raises the stored value to the channel floor
        before deciding anything. A page reading the column straight would
        show a freshly bound session as "inconnu" and imply her memory of
        them is locked, while the prompt treats them as certain.
        """
        identity = _identity(name="Alice", certainty=0.0)
        _handle(identity, person_id="user_7", channel="web",
                trust=ChannelTrust.AUTHENTICATED.value)

        row = _rows(client, "/dashboard/api/identity")["rows"][0]
        assert row["certainty_stored"] == 0.0
        assert row["certainty"] == pytest.approx(float(Certainty.VERIFIED))
        assert row["may_disclose"] is True

    def test_public_handle_never_clears_the_disclosure_bar(self, client):
        identity = _identity(name="?", certainty=1.0)
        _handle(identity, person_id="tg_group_9", channel="telegram",
                trust=ChannelTrust.PUBLIC.value)

        row = _rows(client, "/dashboard/api/identity")["rows"][0]
        assert row["ceiling"] == pytest.approx(float(Certainty.CORROBORATED))
        assert row["may_disclose"] is False

    def test_may_disclose_agrees_with_the_trust_policy(self, client):
        """The flag is not recomputed here — this asserts it stayed that way."""
        from identity import trust as trust_policy

        for trust, certainty in [
            (ChannelTrust.ACCOUNT.value, 0.85),
            (ChannelTrust.ACCOUNT.value, 0.45),
            (ChannelTrust.PUBLIC.value, 0.70),
            (ChannelTrust.AUTHENTICATED.value, 0.0),
        ]:
            Identity.objects.all().delete()
            identity = _identity(certainty=certainty)
            _handle(identity, person_id=f"h_{trust}_{certainty}", trust=trust)

            row = _rows(client, "/dashboard/api/identity")["rows"][0]
            assert row["may_disclose"] == trust_policy.may_disclose_private_context(
                row["certainty"], ChannelTrust(trust),
            )

    def test_ephemeral_only_identities_are_hidden_by_default(self, client):
        identity = _identity(name="anon")
        _handle(identity, person_id="anon_abc", channel="web", ephemeral=True)

        assert _rows(client, "/dashboard/api/identity")["total"] == 0
        assert _rows(
            client, "/dashboard/api/identity?include_ephemeral=1",
        )["total"] == 1

    def test_summary_counts_the_same_scope_the_table_shows(self, client):
        """Measured on the dev database: 86 ephemeral rows against 9 real ones.

        A stat card reading "95 identités" above a table of 9 is read as a
        broken filter, not as two different questions.
        """
        durable = _identity(name="Thomas")
        _handle(durable, person_id="tg_2")
        socket = _identity(name="anon")
        _handle(socket, person_id="anon_zz", channel="web", ephemeral=True)

        summary = _rows(client, "/dashboard/api/identity")["summary"]
        assert summary["identities"] == 1
        assert summary["identities_ephemeral_only"] == 1
        assert summary["handles_ephemeral"] == 1

    def test_identity_with_no_handle_at_all_is_still_listed(self, client):
        """An orphan row is a fact about the database, not noise to hide."""
        _identity(name="orpheline")
        assert _rows(client, "/dashboard/api/identity")["total"] == 1

    def test_filters_bound_unbound_and_pending(self, client):
        entity = Entity.objects.create(name="Bob", entity_type="person")
        bound = _identity(name="Bob", entity=entity, certainty=0.85)
        _handle(bound, person_id="tg_bound")
        unbound = _identity(name="?")
        h = _handle(unbound, person_id="tg_unbound")
        _claim(unbound, h)

        assert _rows(client, "/dashboard/api/identity?state=bound")["total"] == 1
        assert _rows(client, "/dashboard/api/identity?state=unbound")["total"] == 1
        pending = _rows(client, "/dashboard/api/identity?state=pending")
        assert pending["total"] == 1
        assert pending["rows"][0]["claims_pending"] == 1

    def test_search_matches_handle_person_id(self, client):
        """Searching by handle is the point: that is what logs show you."""
        identity = _identity(name="Thomas")
        _handle(identity, person_id="tg_998877")

        assert _rows(client, "/dashboard/api/identity?q=998877")["total"] == 1
        assert _rows(client, "/dashboard/api/identity?q=zzz")["total"] == 0

    def test_pending_claims_sort_first(self, client):
        quiet = _identity(name="quiet")
        _handle(quiet, person_id="tg_quiet")
        noisy = _identity(name="noisy")
        h = _handle(noisy, person_id="tg_noisy")
        _claim(noisy, h)

        rows = _rows(client, "/dashboard/api/identity")["rows"]
        assert rows[0]["display_name"] == "noisy"


class TestDetail:

    def test_detail_carries_the_prompt_sentence_and_the_ledger(self, client):
        identity = _identity(name="Thomas", certainty=0.45)
        h = _handle(identity, person_id="tg_5")
        _claim(identity, h)

        data = _rows(client, f"/dashboard/api/identity/{identity.pk}")
        assert data["claims"][0]["kind_label"]
        assert data["claims"][0]["weight"] == 0.20
        # The description is what resolve_context hands the prompt builder.
        assert "Thomas" in data["description"]

    def test_missing_identity_is_404(self, client):
        assert client.get("/dashboard/api/identity/9999").status_code == 404


# ── Claims ──────────────────────────────────────────────────────

class TestClaims:

    def test_pending_first_even_when_older(self, client):
        identity = _identity(name="x")
        h = _handle(identity, person_id="tg_x")
        _claim(identity, h, name="Vieux", status=IdentityClaim.Status.PENDING)
        _claim(identity, h, name="Recent", status=IdentityClaim.Status.ACCEPTED)

        data = _rows(client, "/dashboard/api/identity/claims?status=")
        assert data["rows"][0]["claimed_name"] == "Vieux"
        assert data["pending"] == 1

    def test_accept_binds_through_the_resolver(self, client):
        """Same outcome as the MCP tool: entity created, certainty raised."""
        identity = _identity(name="?")
        h = _handle(identity, person_id="tg_7")
        claim = _claim(identity, h, name="Thomas")

        res = client.post(
            f"/dashboard/api/identity/claims/{claim.pk}/accept",
            data=json.dumps({"reason": "il a redit le concert"}),
            content_type="application/json",
        )
        assert res.status_code == 200

        identity.refresh_from_db()
        claim.refresh_from_db()
        assert identity.entity is not None
        assert identity.entity.name == "Thomas"
        assert claim.status == IdentityClaim.Status.ACCEPTED
        assert identity.certainty == pytest.approx(0.20)

    def test_accept_with_corroboration_lands_on_the_disclosure_bar(self, client):
        """The calibration the weights exist for, exercised end-to-end."""
        identity = _identity(name="?")
        h = _handle(identity, person_id="tg_8")
        claim = _claim(identity, h, name="Alice")

        client.post(
            f"/dashboard/api/identity/claims/{claim.pk}/accept",
            data=json.dumps({"evidence_kind": "shared_memory"}),
            content_type="application/json",
        )
        identity.refresh_from_db()
        assert identity.certainty == pytest.approx(
            float(Certainty.CORROBORATED),
        )

    def test_accept_is_capped_by_a_public_channel(self, client):
        identity = _identity(name="?")
        h = _handle(identity, person_id="tg_pub", trust=ChannelTrust.PUBLIC.value)
        claim = _claim(identity, h, name="Alice", channel="telegram",
                       trust=ChannelTrust.PUBLIC.value)

        client.post(
            f"/dashboard/api/identity/claims/{claim.pk}/accept",
            data=json.dumps({"evidence_kind": "shared_memory"}),
            content_type="application/json",
        )
        identity.refresh_from_db()
        assert identity.certainty <= float(Certainty.CORROBORATED)

    def test_reject_records_the_doubt_without_deleting(self, client):
        identity = _identity(name="?")
        h = _handle(identity, person_id="tg_9")
        claim = _claim(identity, h)

        res = client.post(
            f"/dashboard/api/identity/claims/{claim.pk}/reject",
            data=json.dumps({"reason": "il s'est trompé sur la date"}),
            content_type="application/json",
        )
        assert res.status_code == 200
        claim.refresh_from_db()
        assert claim.status == IdentityClaim.Status.REJECTED
        assert "date" in claim.resolution_note

    def test_resolving_twice_is_refused_loudly(self, client):
        """The resolver answers {"ok": false} for LLM callers; a form gets a 4xx.

        A refused write that returns 200 is how a dashboard shows a change
        that never happened.
        """
        identity = _identity(name="?")
        h = _handle(identity, person_id="tg_10")
        claim = _claim(identity, h)

        first = client.post(f"/dashboard/api/identity/claims/{claim.pk}/reject",
                            content_type="application/json")
        second = client.post(f"/dashboard/api/identity/claims/{claim.pk}/reject",
                             content_type="application/json")
        assert first.status_code == 200
        assert second.status_code == 400
        assert "error" in json.loads(second.content)


# ── Bind / evidence / revoke ────────────────────────────────────

class TestBindings:

    def test_bind_links_an_identity_that_never_had_a_claim(self, client):
        identity = _identity(name="?")
        _handle(identity, person_id="tg_11")

        res = client.post(
            f"/dashboard/api/identity/{identity.pk}/bind",
            data=json.dumps({"entity_name": "Camille"}),
            content_type="application/json",
        )
        assert res.status_code == 200
        identity.refresh_from_db()
        assert identity.entity.name == "Camille"

    def test_bind_requires_a_name(self, client):
        identity = _identity(name="?")
        _handle(identity, person_id="tg_12")
        res = client.post(
            f"/dashboard/api/identity/{identity.pk}/bind",
            data=json.dumps({"entity_name": "   "}),
            content_type="application/json",
        )
        assert res.status_code == 400

    def test_revoke_unbinds_and_keeps_the_trail(self, client):
        entity = Entity.objects.create(name="Thomas", entity_type="person")
        identity = _identity(name="Thomas", entity=entity, certainty=0.85)
        _handle(identity, person_id="tg_13")

        res = client.post(
            f"/dashboard/api/identity/{identity.pk}/revoke",
            data=json.dumps({"reason": "ce n'était pas lui"}),
            content_type="application/json",
        )
        assert res.status_code == 200
        identity.refresh_from_db()
        assert identity.entity_id is None
        assert identity.certainty == 0.0
        # Deliberately not a delete: why she stopped believing is a row.
        assert IdentityClaim.objects.filter(
            identity=identity, kind="revoked",
        ).exists()

    def test_evidence_rejects_an_unknown_kind(self, client):
        """The resolver scores an unknown kind as 0 on purpose (LLM args).

        From a fixed dropdown that can only be a bug, and a write that
        silently changes nothing is worse than a refusal.
        """
        identity = _identity(name="?")
        _handle(identity, person_id="tg_14")

        res = client.post(
            f"/dashboard/api/identity/{identity.pk}/evidence",
            data=json.dumps({"kind": "vibes", "detail": "je le sens bien"}),
            content_type="application/json",
        )
        assert res.status_code == 400

    def test_counter_evidence_lowers_certainty(self, client):
        entity = Entity.objects.create(name="Thomas", entity_type="person")
        identity = _identity(name="Thomas", entity=entity, certainty=0.85)
        _handle(identity, person_id="tg_15")

        res = client.post(
            f"/dashboard/api/identity/{identity.pk}/evidence",
            data=json.dumps({"kind": "contradicted", "detail": "faux souvenir"}),
            content_type="application/json",
        )
        assert res.status_code == 200
        identity.refresh_from_db()
        assert identity.certainty == pytest.approx(0.50)

    def test_write_on_a_handleless_identity_is_refused(self, client):
        identity = _identity(name="orpheline")
        for path in ("bind", "evidence", "revoke"):
            res = client.post(
                f"/dashboard/api/identity/{identity.pk}/{path}",
                data=json.dumps({"entity_name": "X", "kind": "vouched",
                                 "detail": "x"}),
                content_type="application/json",
            )
            assert res.status_code == 400, path

    def test_writes_require_post(self, client):
        identity = _identity(name="?")
        assert client.get(
            f"/dashboard/api/identity/{identity.pk}/revoke",
        ).status_code == 405


# ── Policy ──────────────────────────────────────────────────────

class TestPolicy:

    def test_policy_is_read_from_the_trust_module(self, client):
        """The page explains its own verdicts — from the constants that run.

        A hand-written copy in the template would keep saying 0.70 long
        after somebody moved the bar.
        """
        from identity import trust as trust_policy

        data = _rows(client, "/dashboard/api/identity/policy")
        assert data["evidence_weights"] == trust_policy.EVIDENCE_WEIGHTS
        assert data["counter_evidence_weights"] == (
            trust_policy.COUNTER_EVIDENCE_WEIGHTS
        )
        assert data["thresholds"]["private_context"] == (
            trust_policy.PRIVATE_CONTEXT_THRESHOLD
        )

    def test_policy_exposes_every_channel_ceiling(self, client):
        from identity import trust as trust_policy

        data = _rows(client, "/dashboard/api/identity/policy")
        by_trust = {c["trust"]: c for c in data["channels"]}
        for t in ChannelTrust:
            assert by_trust[t.value]["ceiling"] == pytest.approx(
                trust_policy.ceiling_for(t),
            )

    def test_claim_kinds_are_offered_with_their_weights(self, client):
        """The evidence dropdown is built from this — an unlisted kind
        would be a form option the write endpoint then refuses."""
        data = _rows(client, "/dashboard/api/identity/policy")
        kinds = {k["value"] for k in data["kinds"]}
        weighted = set(data["evidence_weights"]) | set(
            data["counter_evidence_weights"]
        )
        assert weighted <= kinds


# ── Sidebar wiring ──────────────────────────────────────────────

class TestOverviewCount:

    def test_pending_claims_badge_the_sidebar(self, client):
        identity = _identity(name="?")
        h = _handle(identity, person_id="tg_16")
        _claim(identity, h)

        data = _rows(client, "/dashboard/api/overview")
        assert data["counts"]["identity"] == 1
        assert data["counts"]["identities_unbound"] == 1
