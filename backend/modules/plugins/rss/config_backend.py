"""Pont entre l'éditeur ``record_list`` générique et le modèle ``RSSFeed``.

Même forme que ``email.accounts`` : le registre décrit les champs, la
configuration les rend, et l'écriture atterrit dans la table du module plutôt
que dans ``ConfigRecordItem``. Le module garde la propriété de ses données et
le tableau de bord n'en devient pas une seconde source de vérité.

Trois règles que le backend générique ne peut pas exprimer :

- **L'URL est obligatoire et unique.** Une contrainte d'unicité violée
  remonterait sinon en 500 ; ici c'est une ``ValueError``, donc un message en
  français au-dessus du formulaire.
- **Le nom est facultatif à la saisie** : coller une URL suffit, l'hôte sert
  d'étiquette en attendant que le premier relevé apporte le vrai titre du flux.
- **``enabled`` pilote ``is_active``**, ce qui suspend le relevé sans perdre
  l'historique — désactiver et supprimer ne sont pas la même intention.
"""
from __future__ import annotations

from configs import backends

# Colonnes éditables. ``etag`` / compteurs d'erreurs / dates de relevé sont
# renseignés par le module et n'ont rien à faire dans un formulaire.
_FIELDS = ("name", "url", "category", "keywords", "emit_events")


class RSSFeedBackend:
    """CRUD sur ``modules.plugins.rss.models.RSSFeed``."""

    def _all(self):
        from modules.plugins.rss.models import RSSFeed
        return RSSFeed.objects.all().order_by("category", "name", "id")

    def _get(self, row_id):
        from modules.plugins.rss.models import RSSFeed
        try:
            pk = int(row_id)
        except (TypeError, ValueError):
            raise KeyError(f"Identifiant de flux invalide : {row_id!r}")
        try:
            return RSSFeed.objects.get(pk=pk)
        except RSSFeed.DoesNotExist:
            raise KeyError(f"Flux {row_id} introuvable")

    # ── Sérialisation ───────────────────────────────────────────

    def _serialize(self, obj) -> dict:
        return {
            "row_id": str(obj.pk),
            "payload": {f: getattr(obj, f) for f in _FIELDS},
            "enabled": obj.is_active,
            "order": obj.pk,
            "updated_at": obj.created_at.isoformat() if obj.created_at else "",
        }

    def _apply(self, obj, item, payload) -> None:
        record = item.record
        for field in (record.fields if record else ()):
            key = field.key
            if key not in _FIELDS:
                continue
            incoming = payload.get(key, None)
            if incoming is None:
                continue
            if field.type == "bool":
                setattr(obj, key, bool(incoming))
                continue
            setattr(obj, key, str(incoming).strip())

        if "enabled" in payload:
            obj.is_active = bool(payload["enabled"])

    def _check(self, obj, *, exclude_pk=None) -> None:
        from modules.plugins.rss.models import RSSFeed

        if not obj.url:
            raise ValueError("L'URL du flux est obligatoire.")
        if not obj.url.lower().startswith(("http://", "https://")):
            raise ValueError("L'URL doit commencer par http:// ou https://")

        clash = RSSFeed.objects.filter(url=obj.url)
        if exclude_pk is not None:
            clash = clash.exclude(pk=exclude_pk)
        if clash.exists():
            raise ValueError("Ce flux est déjà suivi (URL identique).")

        if not obj.name:
            # Coller une URL doit suffire. Le vrai titre remplace celui-ci au
            # premier relevé, si le flux en annonce un.
            obj.name = _host(obj.url)

    # ── API publique ────────────────────────────────────────────

    def list_rows(self, item, *, decrypt_secrets=False):
        return [self._serialize(o) for o in self._all()]

    def add_row(self, item, payload):
        from modules.plugins.rss.models import RSSFeed

        obj = RSSFeed()
        self._apply(obj, item, payload)
        self._check(obj)
        obj.save()
        return self._serialize(obj)

    def update_row(self, item, row_id, payload):
        obj = self._get(row_id)
        ancienne_url = obj.url
        self._apply(obj, item, payload)
        self._check(obj, exclude_pk=obj.pk)
        if obj.url != ancienne_url:
            # Le relevé conditionnel porte sur une ressource précise : garder
            # l'ETag d'une autre URL ferait répondre 304 à tort, et le nouveau
            # flux resterait éternellement vide.
            obj.etag = ""
            obj.http_last_modified = ""
        obj.save()
        return self._serialize(obj)

    def delete_row(self, item, row_id):
        try:
            obj = self._get(row_id)
        except KeyError:
            return          # silencieux sur ligne absente, comme le générique
        obj.delete()


def _host(url: str) -> str:
    from urllib.parse import urlparse
    return (urlparse(url).hostname or url)[:200]


# Enregistrement au chargement du schéma, qui importe ce fichier.
backends.register("rss.feeds", RSSFeedBackend())
