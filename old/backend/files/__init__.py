"""Core file storage service.

Uploaded files are a default project capability — not a plugin. The
service persists metadata in the ``files_uploadedfile`` table (kept at
its historical name ``modules_uploadedfile`` for backward compat),
stores binaries under ``UPLOADS_ROOT``, and is consumed by:

  - the ingestion pipeline (pipeline.media) when a user attaches files
  - Mika's tools (MCP-exposed via FilesModule) for list/read/move/etc.
  - any plugin module that wants to read a previously-uploaded file

The service is always available. The FilesModule wrapper registers
the MCP tools and context block with the plugin bus.
"""

default_app_config = "files.apps.FilesConfig"
