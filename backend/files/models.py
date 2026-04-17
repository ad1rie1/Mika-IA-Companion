import uuid

from django.db import models


class UploadedFile(models.Model):
    """A file uploaded by a user — stored on disk, metadata in DB.

    Historical note: the physical table name is kept as
    ``modules_uploadedfile`` because the model used to live in the
    ``modules`` Django app. The ownership has been transferred to the
    ``files`` app via a state-only migration (no ALTER TABLE) so
    existing data is preserved.
    """

    file_id = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    original_name = models.CharField(max_length=255)
    media_type = models.CharField(max_length=100)
    category = models.CharField(max_length=20)  # image | audio | text | unknown
    file_size = models.PositiveIntegerField(help_text="Taille décodée en octets")
    disk_path = models.CharField(max_length=500, help_text="Chemin absolu sur le disque")
    person_id = models.CharField(max_length=100, default="anonymous")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    is_deleted = models.BooleanField(default=False)

    class Meta:
        app_label = "files"
        db_table = "modules_uploadedfile"
        ordering = ["-uploaded_at"]

    def __str__(self):
        return f"{self.original_name} ({self.file_id})"

    @property
    def size_label(self) -> str:
        if self.file_size >= 1_048_576:
            return f"{self.file_size / 1_048_576:.1f} Mo"
        if self.file_size >= 1024:
            return f"{self.file_size // 1024} Ko"
        return f"{self.file_size} o"
