"""Contrat commun des résultats d'outils, indépendant des modules métier."""

from functools import wraps
import time

from old.backend.utils.tool_trace import noter_appel


class BilanOutils(str):
    """Résumé lisible accompagné de preuves ; le texte n'est jamais reparsé."""

    def __new__(cls, journal):
        instance = super().__new__(cls, journal.resume())
        instance.preuves = journal.as_dict()
        return instance

    def permet_aboutissement(self, *, outils_requis=False):
        preuves = self.preuves
        if preuves["tronques"] or preuves["notes_perdues"]:
            return False
        derniers = {a["nom"]: a["ok"] for a in preuves["appels"]}
        # Un nouvel essai réussi du même outil peut réparer son échec.
        return (bool(derniers) or not outils_requis) and all(derniers.values())


def en_echec(resultat) -> bool:
    """Lire les indicateurs structurés, jamais deviner dans le texte affiché."""
    return isinstance(resultat, dict) and bool(
        resultat.get("isError") or resultat.get("is_error")
        or resultat.get("error") or resultat.get("ok") is False
    )


def texte(contenu: str, *, erreur: bool = False) -> dict:
    return {"content": [{"type": "text", "text": contenu}], "isError": erreur}


def instrumenter(nom, handler):
    """Instrumenter aussi les outils locaux ; ne jamais compter deux fois."""
    if getattr(handler, "_mika_instrumente", False) is True:
        return handler

    @wraps(handler)
    async def execute(params):
        debut = time.monotonic()
        try:
            resultat = await handler(params)
        except Exception as exc:
            noter_appel(nom, ok=False, extrait=f"{type(exc).__name__}: {exc}",
                        ms=(time.monotonic() - debut) * 1000)
            raise
        attente = isinstance(resultat, dict) and resultat.get("status") == "pending_approval"
        noter_appel(nom, ok=not en_echec(resultat), extrait=resultat, en_attente=attente,
                    ms=(time.monotonic() - debut) * 1000)
        return resultat

    execute._mika_instrumente = True
    return execute
