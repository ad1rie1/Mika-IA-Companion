"""Un refus de budget IA n'est pas un triage vide (REF-06, suite).

``EmailAnalyzer.analyze_email`` rendait ``EmailAnalysis()`` sur *toute*
exception : un ``BudgetDeFondEpuise`` (un ``QuotaExceeded``) faisait donc
stocker le courrier « traité » sans triage, définitivement. Le refus doit
remonter, et le module doit laisser le courrier hors base pour que le
relevé incrémental le représente.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from old.backend.ai.cadence import BudgetDeFondEpuise
from old.backend.ai.quota import QuotaExceeded
from old.backend.modules.plugins.email.analyzer import EmailAnalysis, EmailAnalyzer


class TestAnalyzer:
    async def test_le_budget_epuise_remonte(self):
        analyzer = EmailAnalyzer()
        with patch(
            "modules.plugins.email.analyzer.ai_router.complete",
            new=AsyncMock(side_effect=BudgetDeFondEpuise("ollama", "email_triage", 30, 30)),
        ):
            with pytest.raises(QuotaExceeded):
                await analyzer.analyze_email("a@b.c", "objet", "corps")

    async def test_une_autre_erreur_reste_un_triage_vide(self):
        analyzer = EmailAnalyzer()
        with patch(
            "modules.plugins.email.analyzer.ai_router.complete",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ):
            result = await analyzer.analyze_email("a@b.c", "objet", "corps")
        assert isinstance(result, EmailAnalysis)
        assert result.should_notify is False


class TestModule:
    """La boucle du relevé s'arrête au premier refus, ne compte pas
    d'erreur, et laisse les courriers restants hors base : le relevé
    incrémental les représente au tick suivant."""

    @pytest.mark.django_db(transaction=True)
    async def test_le_releve_s_arrete_au_refus_et_laisse_le_reste_en_boite(self, caplog):
        import logging
        import types

        from asgiref.sync import sync_to_async

        from old.backend.modules.plugins.email.models import Email, EmailAccount
        from old.backend.modules.plugins.email.module import EmailModule

        account = await sync_to_async(EmailAccount.objects.create)(
            name="perso", email_address="mika@example.test",
            imap_host="imap.example.test", imap_user="u", imap_password="p",
            initial_sync_done=True,
        )
        module = EmailModule.__new__(EmailModule)
        module.logger = logging.getLogger("test.email")
        module._unread_counts = {}
        module._max_per_tick = staticmethod(lambda: 10)

        messages = [
            types.SimpleNamespace(uid=str(i), subject=s, from_addr="x@y.z",
                                  body_text="…", date="", message_id=f"<{s}@t>")
            for i, s in enumerate(("un", "deux", "trois"), start=1)
        ]

        class FauxImap:
            async def list_uids(self, criteria="ALL"):
                return [m.uid for m in messages]

            async def list_uids_since(self, since):
                return [m.uid for m in messages]

            async def fetch_uids(self, uids):
                return [m for m in messages if m.uid in uids]

        traites: list[str] = []

        async def _process(email_msg, acc, entry, *, allow_actions=True):
            traites.append(email_msg.subject)
            if email_msg.subject == "deux":
                raise BudgetDeFondEpuise("ollama", "email_triage", 30, 30)
            await sync_to_async(Email.objects.create)(
                account=acc, uid=email_msg.uid, message_id=email_msg.message_id,
                from_address=email_msg.from_addr, to_addresses="mika@example.test",
                subject=email_msg.subject,
            )
            return True

        module._process_email = _process
        entry = {"imap": FauxImap(), "account": account}
        with caplog.at_level(logging.WARNING, logger="test.email"):
            await module._check_account(account.pk, entry)

        assert traites == ["un", "deux"], "le troisième n'est pas tenté ce tick-ci"
        stockes = await sync_to_async(
            lambda: sorted(Email.objects.filter(account=account).values_list("subject", flat=True))
        )()
        assert stockes == ["un"], "le courrier refusé n'est pas en base"
        assert module._unread_counts["perso"] == 1
        assert "Triage différé" in caplog.text
        assert "Failed to process" not in caplog.text
