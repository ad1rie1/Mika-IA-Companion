"""Garde-fous techniques de la reponse automatique du triage.

Le triage decide de repondre a partir du *corps* de l'e-mail, c'est-a-dire de
la donnee la moins fiable qui entre dans le moteur, et le seul garde-fou
etait une consigne en langage naturel — placee dans le meme contexte que le
texte qu'elle est censee encadrer. Une injection (« reponds en confirmant… »)
porte donc directement sur la decision d'envoi.

Rien ici ne depend d'un modele : des en-tetes normalises, une adresse et deux
plafonds.
"""
from __future__ import annotations

from email.utils import parseaddr

from utils.degradation import degradations

# Fenetre du plafond par expediteur. Le cron repasse toutes les 60 s : une
# borne « par passe » n'arrete pas un repondeur automatique qui n'annonce rien
# dans ses en-tetes, il faut une memoire plus longue que le tick.
SENDER_WINDOW_SECONDS = 24 * 3600

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


# ── Reglages ────────────────────────────────────────────────────────


def _setting(key: str, default):
    """Lecture defensive : une configuration illisible rend le defaut.

    Relue a chaque message plutot que mise en cache — les trois reglages sont
    ``hot_reload``, et on coupe l'envoi automatique au moment ou on s'apercoit
    qu'il derape, pas au prochain redemarrage.
    """
    from configs.service import config_service

    try:
        value = config_service.get(key)
    except Exception as exc:
        degradations.record("modules.plugins.email.autoreply._setting", exc)
        return default
    return default if value is None else value


def _cap(key: str, default: int) -> int:
    try:
        return max(0, int(_setting(key, default)))
    except (TypeError, ValueError) as exc:
        degradations.record("modules.plugins.email.autoreply._cap", exc)
        return default


def auto_reply_enabled() -> bool:
    """L'interrupteur general de la reponse automatique."""
    return bool(_setting("email.auto_reply_enabled", True))


def max_per_tick() -> int:
    """Plafond de reponses automatiques sur une passe de releve."""
    return _cap("email.auto_reply_max_per_tick", 3)


def max_per_sender() -> int:
    """Plafond de reponses automatiques par expediteur sur la fenetre."""
    return _cap("email.auto_reply_max_per_sender", 1)
