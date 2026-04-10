"""Module model registry.

Django discovers models through this file via the 'modules' app.
Each module keeps its models in its own folder; this file re-exports
them so Django migrations stay under modules/migrations/.
"""

from modules.email.models import Contact, Email, EmailAccount  # noqa: F401
from modules.rss.models import RSSEntry, RSSFeed  # noqa: F401
from modules.wake.models import WakeRequest  # noqa: F401
