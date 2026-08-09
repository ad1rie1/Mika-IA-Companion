"""Backfill de l'index épisodique — indexe rétroactivement l'historique.

    python manage.py backfill_episodic            # tout l'historique
    python manage.py backfill_episodic --days 60  # les 60 derniers jours

Ré-exécutable sans risque : l'upsert ChromaDB est idempotent par id, et le
checkpoint de l'indexeur n'est écrit que s'il dépasse le courant. La commande
tourne en synchrone (pas de boucle d'événements, pas d'app démarrée requise).
"""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from memory.episodic.chunker import build_chunks
from memory.storage.vector_store import VectorStore, exchange_metadata
from memory.storage.window import user_facing_messages

BATCH = 500


class Command(BaseCommand):
    help = "Indexe rétroactivement les échanges existants dans la collection épisodique."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days", type=int, default=0,
            help="Limiter aux N derniers jours (0 = tout l'historique).",
        )

    def handle(self, *args, **options):
        from memory.models import EpisodicIndexLog, Message

        store = VectorStore()
        now = timezone.now()

        qs = user_facing_messages(Message.objects.all())
        if options["days"]:
            qs = qs.filter(created_at__gte=now - timedelta(days=options["days"]))

        last_id = 0
        total_chunks = 0
        total_msgs = 0
        while True:
            batch = list(
                qs.filter(id__gt=last_id)
                .order_by("created_at", "pk")
                .values(
                    "id", "role", "content", "created_at",
                    "source", "person_id", "conversation_id",
                )[:BATCH]
            )
            if not batch:
                break
            total_msgs += len(batch)
            # Backfill : tout est ancien, la queue non appariée est flushée
            # d'office (flush_age_s=0), aucun message n'est retenu.
            chunks, _ = build_chunks(batch, flush_age_s=0, now=now)
            if chunks:
                store.add_exchanges([
                    {
                        "chunk_id": c.chunk_id,
                        "content": c.text,
                        "metadata": exchange_metadata(
                            conversation_id=c.conversation_id,
                            first_message_id=c.first_message_id,
                            last_message_id=c.last_message_id,
                            handle=c.handle,
                            ts=c.ts,
                        ),
                    }
                    for c in chunks
                ])
                total_chunks += len(chunks)
            last_id = batch[-1]["id"]
            self.stdout.write(f"  … {total_msgs} messages → {total_chunks} chunks")

        # Le checkpoint n'avance que vers l'avant : un backfill partiel
        # (--days) ne doit jamais faire reculer l'indexeur au fil de l'eau.
        if last_id:
            current = (
                EpisodicIndexLog.objects.order_by("-pk")
                .values_list("last_message_id", flat=True)
                .first()
                or 0
            )
            if last_id > current:
                EpisodicIndexLog.objects.create(
                    last_message_id=last_id, chunks_created=total_chunks,
                )

        self.stdout.write(self.style.SUCCESS(
            f"Backfill terminé : {total_msgs} messages, {total_chunks} chunks, "
            f"collection = {store.count_exchanges()} entrées."
        ))
