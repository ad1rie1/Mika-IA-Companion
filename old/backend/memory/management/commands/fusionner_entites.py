"""Fusionne les entités mémoire dupliquées par la casse.

``_resolve_tags`` créait « adrien » à côté de « Adrien » (création exacte
sur le nom, là où la couche identité cherche en ``iexact``) : une fiche de
personne scindée, des souvenirs répartis sur deux lignes, et le filtre intime
traitant le doublon comme un tiers. L'écriture est corrigée ; ceci répare
l'existant.

Pour chaque groupe (nom en minuscules, type), une entité est GARDÉE — celle
liée à une identité, sinon celle qui porte le plus de souvenirs, sinon la
plus ancienne — et les autres lui sont rattachées : souvenirs, connaissances,
engagements, identités, projets, fiche de personne. Puis supprimées.

    python manage.py fusionner_entites            # applique
    python manage.py fusionner_entites --dry-run  # montre sans toucher
"""
from __future__ import annotations

from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count


class Command(BaseCommand):
    help = "Fusionne les entités mémoire qui ne diffèrent que par la casse."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Liste les fusions sans rien écrire.")

    def handle(self, *args, **options):
        from old.backend.memory.models import Entity

        groupes: dict[tuple[str, str], list] = defaultdict(list)
        for e in Entity.objects.annotate(n_souvenirs=Count("souvenirs")).order_by("pk"):
            groupes[(e.name.strip().lower(), e.entity_type)].append(e)

        doublons = {cle: rows for cle, rows in groupes.items() if len(rows) > 1}
        if not doublons:
            self.stdout.write("Aucune entité dupliquée par la casse.")
            return

        total = 0
        for (nom, genre), rows in sorted(doublons.items()):
            gardee = self._choisir(rows)
            perdantes = [r for r in rows if r.pk != gardee.pk]
            self.stdout.write(
                f"{genre} « {nom} » : garder #{gardee.pk} « {gardee.name} », "
                f"fusionner {', '.join(f'#{r.pk} « {r.name} »' for r in perdantes)}"
            )
            if options["dry_run"]:
                continue
            # Le nom affiché : une majuscule initiale gagne sur la forme
            # basse, quelle que soit la ligne gardée — c'est la richesse
            # (identité, souvenirs) qui choisit la ligne, la casse choisit
            # le nom.
            nom_prefere = next(
                (r.name for r in rows if r.name[:1].isupper()), gardee.name,
            )
            with transaction.atomic():
                for perdante in perdantes:
                    self._rattacher(perdante, gardee)
                    perdante.delete()
                if gardee.name != nom_prefere:
                    gardee.name = nom_prefere
                    gardee.save(update_fields=["name"])
            total += len(perdantes)

        if options["dry_run"]:
            self.stdout.write("(dry-run : rien n'a été écrit)")
        else:
            self.stdout.write(self.style.SUCCESS(f"{total} entité(s) fusionnée(s)."))

    @staticmethod
    def _choisir(rows):
        """Celle liée à une identité, sinon la plus riche, sinon la plus ancienne."""
        def cle(e):
            liee = e.identities.exists() if hasattr(e, "identities") else False
            return (1 if liee else 0, e.n_souvenirs, -e.pk)
        return max(rows, key=cle)

    @staticmethod
    def _rattacher(perdante, gardee) -> None:
        from old.backend.memory.models import Commitment, Connaissance, PersonProfile, Souvenir

        for s in Souvenir.objects.filter(entities=perdante):
            s.entities.add(gardee)
        for c in Connaissance.objects.filter(entities=perdante):
            c.entities.add(gardee)
        Commitment.objects.filter(person=perdante).update(person=gardee)
        try:
            from old.backend.identity.models import Identity
            Identity.objects.filter(entity=perdante).update(entity=gardee)
        except Exception:
            pass
        try:
            from old.backend.projects.models import Project
            Project.objects.filter(owner=perdante).update(owner=gardee)
        except Exception:
            pass
        # Fiche : une seule par entité (OneToOne). Celle de la gardée gagne ;
        # sinon la fiche de la perdante est déplacée.
        fiche_perdante = PersonProfile.objects.filter(entity=perdante).first()
        if fiche_perdante is not None:
            if PersonProfile.objects.filter(entity=gardee).exists():
                fiche_perdante.delete()
            else:
                fiche_perdante.entity = gardee
                fiche_perdante.save(update_fields=["entity"])
