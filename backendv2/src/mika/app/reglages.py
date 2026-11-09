"""L'ancien nom d'``app/settings_sections/`` : réexporte ce que ``tests/protocol/test_settings_pages.py`` en lit encore."""

from mika.app.settings_sections import PLUGINS, sections

__all__ = ["PLUGINS", "sections"]
