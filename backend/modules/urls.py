"""Dynamic module URL patterns.

Routes are populated at Django startup by ModulesConfig.ready()
via _populate_urls(). Each module declares its own routes through
get_routes(), auto-mounted under /api/modules/{module_name}/.
"""

urlpatterns: list = []


def _populate_urls() -> None:
    """Called from ModulesConfig.ready() after all modules are registered."""
    from modules.manager import module_manager

    urlpatterns.extend(module_manager.collect_routes())
