"""Flag pre-existing anonymous handles so retention can reclaim them.

``is_ephemeral`` defaults to False, which is right for handles created from
now on (the consumer sets it explicitly). But every ``anon_*`` row that
already exists predates the flag and would be protected forever by the
retention policy's ``protect={"is_ephemeral": False}``.

Those rows are per-connection sockets, not people: one was minted on every
connect — including every reconnect from the frontend's backoff loop — so an
install with zero messages had already accumulated dozens of them.
"""
from django.db import migrations


def flag_ephemeral(apps, schema_editor):
    IdentityHandle = apps.get_model("identity", "IdentityHandle")
    IdentityHandle.objects.filter(person_id__startswith="anon_").update(
        is_ephemeral=True,
    )


def unflag_ephemeral(apps, schema_editor):
    IdentityHandle = apps.get_model("identity", "IdentityHandle")
    IdentityHandle.objects.filter(person_id__startswith="anon_").update(
        is_ephemeral=False,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("identity", "0002_identityclaim_identity_binding_reason_and_more"),
    ]

    operations = [
        migrations.RunPython(flag_ephemeral, unflag_ephemeral),
    ]
