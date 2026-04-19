"""Module admin registry.

Django autodiscovers this file for the 'modules' app.
Each sub-module defines its own admin classes; we import them here
so Django registers them.
"""

from modules.plugins.email.admin import ContactAdmin, EmailAccountAdmin, EmailAdmin  # noqa: F401
from modules.plugins.wake.admin import WakeRequestAdmin  # noqa: F401
