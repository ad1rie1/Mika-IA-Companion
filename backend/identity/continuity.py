"""Clés de continuité personnelle, jamais adresses de livraison ni permissions."""


def cle_relation(person_id: str) -> tuple[str, list[str]]:
    from identity.models import IdentityHandle
    from identity.trust import is_identifiable_person

    if not is_identifiable_person(person_id):
        return person_id, [person_id]
    handle = IdentityHandle.objects.select_related("identity").filter(
        person_id=person_id, is_ephemeral=False,
    ).first()
    if handle is None:
        return person_id, [person_id]
    # Une entité peut réunir plusieurs Identity créées sur des canaux distincts.
    entity_id = handle.identity.entity_id
    filtres = ({"identity__entity_id": entity_id} if entity_id
               else {"identity_id": handle.identity_id})
    aliases = list(IdentityHandle.objects.filter(
        **filtres, is_ephemeral=False,
    ).values_list("person_id", flat=True))
    identity_ids = (
        IdentityHandle.objects.filter(**filtres, is_ephemeral=False)
        .values_list("identity_id", flat=True).distinct()
    )
    aliases.extend(f"relation_identity_{pk}" for pk in identity_ids)
    cle = f"relation_entity_{entity_id}" if entity_id else f"relation_identity_{handle.identity_id}"
    return cle, aliases
