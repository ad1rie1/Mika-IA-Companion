"""Module model registry.

Django discovers models through this file via the 'modules' app.
Each module keeps its models in its own folder; this file re-exports
them so Django migrations stay under modules/migrations/.
"""

from modules.plugins.email.models import Contact, Email, EmailAccount  # noqa: F401
from modules.plugins.forge.models import ForgeLog, ForgeRecord  # noqa: F401
from modules.plugins.rss.models import RSSEntry, RSSFeed  # noqa: F401
from modules.state_model import ModuleState  # noqa: F401
from modules.plugins.wake.models import WakeRequest  # noqa: F401
