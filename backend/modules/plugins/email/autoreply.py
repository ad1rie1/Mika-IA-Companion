"""Garde-fous techniques de la reponse automatique du triage.

Le triage decide de repondre a partir du *corps* de l'e-mail, c'est-a-dire de
la donnee la moins fiable qui entre dans le moteur, et le seul garde-fou
etait une consigne en langage naturel — placee dans le meme contexte que le
texte qu'elle est censee encadrer. Une injection (« reponds en confirmant… »)
porte donc directement sur la decision d'envoi.

Rien ici ne depend d'un modele : des en-tetes normalises et une adresse.
"""
from __future__ import annotations

from email.utils import parseaddr

# ``Precedence`` n'est pas normalise, mais ces valeurs sont l'usage etabli
# pour « ne repondez pas a ceci ».
_BULK_PRECEDENCES = ("bulk", "list", "junk", "auto_reply")

# Compares a la partie locale de l'adresse debarrassee de sa ponctuation :
# ``ne-pas-repondre@`` et ``nepasrepondre@`` sont la meme boite morte.
_NOREPLY_MARKERS = (
    "noreply", "donotreply", "nepasrepondre",
    "mailerdaemon", "postmaster", "bounce",
)


def _header(email_msg, field: str) -> str:
    """Un en-tete du message, toujours rendu comme une chaine propre."""
    return str(getattr(email_msg, field, "") or "").strip()


def is_noreply_address(from_addr: str) -> bool:
    """Une adresse d'ou rien ne revient : y repondre est au mieux inutile."""
    _, address = parseaddr(from_addr or "")
    local = "".join(c for c in address.split("@", 1)[0].lower() if c.isalnum())
    return any(marker in local for marker in _NOREPLY_MARKERS)


def loop_risk_reason(email_msg) -> str:
    """Pourquoi repondre a ce message ouvrirait une boucle — "" sinon.

    Renvoie une raison lisible plutot qu'un booleen : le refus est journalise,
    et « pourquoi elle n'a pas repondu » est exactement la question qu'on se
    pose en relisant ce journal.

    Repondre a un repondeur automatique produit un aller-retour que rien
    n'arrete, et chaque iteration coute deux appels LLM.
    """
    auto = _header(email_msg, "auto_submitted").lower()
    if auto and auto != "no":
        return f"Auto-Submitted: {auto}"

    precedence = _header(email_msg, "precedence").lower()
    if precedence in _BULK_PRECEDENCES:
        return f"Precedence: {precedence}"

    if _header(email_msg, "list_id"):
        return "List-Id"

    if _header(email_msg, "list_unsubscribe"):
        return "List-Unsubscribe"

    if is_noreply_address(_header(email_msg, "from_addr")):
        return "adresse noreply"

    return ""
