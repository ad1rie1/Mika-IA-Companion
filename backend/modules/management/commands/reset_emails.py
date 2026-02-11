"""Management command to wipe all emails/contacts and reset sync state."""

from django.core.management.base import BaseCommand

from modules.email.models import Contact, Email, EmailAccount


class Command(BaseCommand):
    help = "Delete all emails and contacts, reset initial_sync_done on all accounts"

    def handle(self, *args, **options):
        email_count, _ = Email.objects.all().delete()
        contact_count, _ = Contact.objects.all().delete()
        account_count = EmailAccount.objects.update(initial_sync_done=False, last_fetch=None)

        self.stdout.write(
            f"Deleted {email_count} email(s), {contact_count} contact(s). "
            f"Reset sync state on {account_count} account(s)."
        )
