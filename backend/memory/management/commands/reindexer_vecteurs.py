"""Resynchronise ChromaDB sur SQL — souvenirs et connaissances.

    python manage.py reindexer_vecteurs              # tout
    python manage.py reindexer_vecteurs --sans-purge # ne retire rien de Chroma

SQL est la vérité (étage 0) ; les vecteurs en sont une projection. Après une
restauration (deploy/README.md) — une base d'une date, un tar Chroma d'une
autre, ou pas de tar du tout — cette commande ré-upserte chaque ``Souvenir``
et chaque ``Connaissance`` avec les métadonnées recomposées depuis la ligne
(les mêmes helpers que les écrivains du consolidateur), puis retire de Chroma
les ids que SQL ne connaît plus. Idempotente : l'upsert est par id.

Le rattrapage horaire du consolidateur (``_reindex_missing``) ne regarde que
les 48 dernières heures et ne purge rien ; ceci est la version complète, à
lancer service arrêté (une écriture concurrente du consolidateur n'est pas
dangereuse, mais un souvenir créé pendant la purge pourrait être retiré
avant d'être vu — le tick suivant le réindexe).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from memory.storage.vector_store import (
    VectorStore,
    connaissance_metadata,
    souvenir_metadata,
)

LOT = 200


class Command(BaseCommand):
    help = "Ré-indexe souvenirs et connaissances dans ChromaDB depuis l'ORM (restauration)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--sans-purge", action="store_true",
            help="Ne pas retirer de Chroma les ids absents de SQL.",
        )

    def handle(self, *args, **options):
        from memory.models import Connaissance, Souvenir

        store = VectorStore()

        # ── Souvenirs ────────────────────────────────────────────────
        vus: set[str] = set()
        total = 0
        qs = Souvenir.objects.prefetch_related("themes").order_by("pk")
        lot: list[dict] = []
        for s in qs.iterator(chunk_size=LOT):
            vus.add(str(s.pk))
            lot.append({
                "souvenir_id": s.pk,
                "content": s.content,
                "metadata": souvenir_metadata(
                    importance=s.importance,
                    emotion=s.emotion,
                    occurred_at=(s.occurred_at or s.created_at).isoformat(),
                    themes=[t.name for t in s.themes.all()],
                ),
            })
            if len(lot) >= LOT:
                store.add_souvenirs(lot)
                total += len(lot)
                lot = []
                self.stdout.write(f"  … {total} souvenirs")
        if lot:
            store.add_souvenirs(lot)
            total += len(lot)
        self.stdout.write(f"souvenirs : {total} ré-indexés")

        orphelins = 0
        if not options["sans_purge"]:
            for cid in store.collection_ids("souvenirs") - vus:
                store.remove_souvenir(int(cid))
                orphelins += 1
            self.stdout.write(f"souvenirs : {orphelins} retirés de Chroma (absents de SQL)")

        # ── Connaissances ────────────────────────────────────────────
        vus = set()
        total = 0
        qs = Connaissance.objects.prefetch_related("themes").order_by("pk")
        for c in qs.iterator(chunk_size=LOT):
            vus.add(str(c.pk))
            store.add_connaissance(
                c.pk, c.content,
                metadata=connaissance_metadata(
                    confidence=c.confidence, is_valid=c.is_valid,
                    themes=[t.name for t in c.themes.all()],
                ),
            )
            total += 1
            if total % LOT == 0:
                self.stdout.write(f"  … {total} connaissances")
        self.stdout.write(f"connaissances : {total} ré-indexées")

        orphelins = 0
        if not options["sans_purge"]:
            for cid in store.collection_ids("connaissances") - vus:
                store.remove_connaissance(int(cid))
                orphelins += 1
            self.stdout.write(
                f"connaissances : {orphelins} retirées de Chroma (absentes de SQL)"
            )

        self.stdout.write(self.style.SUCCESS(
            "Resynchronisation terminée. Pour les échanges bruts : "
            "python manage.py backfill_episodic"
        ))
