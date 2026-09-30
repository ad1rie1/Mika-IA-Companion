"""Mettre un mail en forme, exactement comme il partira — pur, sans réseau.

- **L'expéditeur** suit la voix du compte : ``Mika <boîte>`` (en son nom),
  ``Mika (pour Adrien) <boîte>`` (en assistante), ``Adrien <boîte>`` (à sa place).
- **Le texte** : ce qui a été écrit, la signature du compte (séparée par
  ``-- ``), puis la citation du mail auquel on répond.
- **Le fil** : ``In-Reply-To`` et ``References`` chaînées.
- **L'aperçu** (``preview``) est ce qu'un opérateur lit avant d'approuver ; son
  condensé épingle l'accord : ce qui partira est ce qui a été lu.
"""

from __future__ import annotations

import email.utils
import hashlib
from datetime import UTC, datetime, tzinfo
from email.message import EmailMessage

from mika.ports.mail import TO_FILL, AccountInfo, Draft, Mail, Preview, addresses

HER_NAME = "Mika"
QUOTE_MAX = 6000


def sender(account: AccountInfo) -> str:
    her = (account.sender_name or HER_NAME).strip()
    owner = account.display_name.strip()
    if account.voice == "proprietaire" and owner:
        name = owner
    elif account.voice == "assistante" and owner:
        name = f"{her} (pour {owner})"
    else:
        name = her
    return email.utils.formataddr((name, account.address))


def _when(at: int, tz: tzinfo) -> str:
    if not at:
        return ""
    dt = datetime.fromtimestamp(at / 1_000_000, tz=UTC).astimezone(tz)
    return f"le {dt:%d/%m/%Y à %H:%M}"


def final_text(body: str, account: AccountInfo, parent: Mail | None, *, quote: bool, tz: tzinfo = UTC) -> str:
    text = body.rstrip()
    signature = account.signature.strip()
    if signature:
        text += "\n\n-- \n" + signature
    if quote and parent is not None and parent.body.strip():
        cited = "\n".join("> " + line for line in parent.body[:QUOTE_MAX].splitlines())
        when = _when(parent.date, tz)
        head = f"{when[:1].upper()}{when[1:]}, {parent.sender} a écrit :" if when else f"{parent.sender} a écrit :"
        text += f"\n\n{head}\n{cited}"
    return text


def digest(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8", "replace")).hexdigest()[:32]


def blocked(draft: Draft, account: AccountInfo | None) -> str:
    """Pourquoi ce brouillon ne peut pas partir tel quel (vide : il peut)."""
    if account is None:
        return "ce compte n'existe plus"
    if not account.can_send:
        return "ce compte ne peut pas envoyer (serveur d'envoi manquant ou compte inactif)"
    if not addresses(draft.to):
        return "aucun destinataire valide"
    if TO_FILL in draft.body or TO_FILL in draft.subject:
        return "il reste des passages à compléter ([À COMPLÉTER …])"
    return ""


def preview(draft: Draft, account: AccountInfo | None, parent: Mail | None, *, tz: tzinfo = UTC) -> Preview:
    who = sender(account) if account is not None else ""
    text = final_text(draft.body, account, parent, quote=draft.quote, tz=tz) if account is not None else draft.body
    parent_id = parent.message_id if parent is not None else ""
    return Preview(sender=who, to=draft.to, cc=draft.cc, subject=draft.subject, text=text,
                   digest=digest(who, draft.to, draft.cc, draft.subject, text, parent_id),
                   blocked=blocked(draft, account))


def message(shown: Preview, parent: Mail | None, message_id: str, *, when: datetime,
            in_reply_to: str = "") -> EmailMessage:
    """Le mail à envoyer, tel que l'aperçu le montre (``in_reply_to`` : le Message-ID
    auquel il répond quand ce mail-là n'est pas dans le cache)."""
    msg = EmailMessage()
    msg["From"] = shown.sender
    msg["To"] = shown.to
    if shown.cc:
        msg["Cc"] = shown.cc
    msg["Subject"] = shown.subject
    msg["Message-ID"] = message_id
    msg["Date"] = email.utils.format_datetime(when)
    if parent is not None:
        msg["In-Reply-To"] = parent.message_id
        refs = " ".join([*parent.references.split(), parent.message_id])
        msg["References"] = " ".join(refs.split()[-20:])
    elif in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.set_content(shown.text)
    return msg


def new_message_id(account: AccountInfo) -> str:
    return email.utils.make_msgid(domain=account.address.split("@")[-1] or "mika.local")
