"""Fenêtre des messages « adressés à quelqu'un » — une seule définition.

Le consolidateur et l'indexeur épisodique lisent tous deux « les messages
qui font partie d'une vraie conversation » : sans machinerie interne
(`is_internal`), sans sources techniques, sans les prompts que la conscience
s'adresse à elle-même. Deux copies de ces exclusions finiraient par dériver —
c'est exactement l'histoire qu'ont déjà vécue les lecteurs d'état interne.
"""

from __future__ import annotations

# Sources dont les messages sont du bruit technique, pas de la conversation.
INTERNAL_MESSAGE_SOURCES = ("module_email", "module_wake")


def user_facing_messages(qs):
    """Applique les exclusions canoniques à un queryset de ``Message``.

    - ``is_internal=True`` : briefs d'INTERNAL_TRIGGER, replis d'un tour
      échoué — personne n'a dit ces phrases.
    - ``source in INTERNAL_MESSAGE_SOURCES`` : plomberie de modules.
    - ``(source="conscience", role="user")`` : le prompt d'action que la
      conscience se donne ; sa *réponse* (ce que Mika a dit) reste incluse.
    """
    return (
        qs.exclude(source__in=INTERNAL_MESSAGE_SOURCES)
        .exclude(is_internal=True)
        .exclude(source="conscience", role="user")
    )
