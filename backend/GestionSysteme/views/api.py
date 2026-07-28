"""Le seul point d'accès JSON de l'interface.

Il n'alimente que la barre supérieure. Tout le reste est rendu par le
serveur : c'est ce qui permet de supprimer les 29 fichiers de vues
JavaScript, les 125 injections ``innerHTML`` et la couche d'assainissement
qui existait pour les rattraper.

Les valeurs sont déjà mises en forme ici, par les mêmes fonctions que le
rendu initial : un seul endroit décide comment une humeur s'écrit, donc la
barre ne change pas d'apparence entre le chargement et le premier
rafraîchissement.
"""
from __future__ import annotations

from django.http import JsonResponse
from django.views.decorators.http import require_GET

from GestionSysteme import shell


@require_GET
def vitals(request):
    return JsonResponse(shell.vitals())
