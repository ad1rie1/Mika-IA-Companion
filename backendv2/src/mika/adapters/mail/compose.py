"""Mettre un mail en forme, exactement comme il partira — pur, sans réseau.

- **L'expéditeur** suit la voix du compte : ``Elle <boîte>`` (en son nom : son nom
  d'expéditrice, sinon celui de sa persona), ``Elle (pour Adrien) <boîte>`` (en
  assistante), ``Adrien <boîte>`` (à sa place).
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

from mika.contracts.self_ import DEFAULT_NAME
from mika.ports.mail import AccountInfo, Draft, Mail, Preview, addresses, to_fill
from mika.vocab.phrasebook import phrase


def sender(account: AccountInfo, her: str = DEFAULT_NAME) -> str:
    """L'expéditeur tel qu'il partira ; ``her`` : son nom quand le compte ne lui en donne pas (celui de sa persona,
    que l'application passe — un adaptateur ne le lit pas lui-même)."""
    her = (account.sender_name or her).strip()
    owner = account.display_name.strip()
    if account.voice == "proprietaire" and owner:
        name = owner
    elif account.voice == "assistante" and owner:
        name = phrase("mail.sender_for", her=her, owner=owner)
    else:
        name = her
    return email.utils.formataddr((name, account.address))


def _quote_head(sender: str, at: int, tz: tzinfo) -> str:
    """L'en-tête de la citation : « Le 30/09/2026 à 15:00, Adrien a écrit : » (sans date : « Adrien a écrit : »)."""
    if not at:
        return phrase("mail.quote", who=sender)
    dt = datetime.fromtimestamp(at / 1_000_000, tz=UTC).astimezone(tz)
    return phrase("mail.quote_dated", date=f"{dt:%d/%m/%Y}", time=f"{dt:%H:%M}", who=sender)


def final_text(body: str, account: AccountInfo, parent: Mail | None, *, quote: bool, tz: tzinfo = UTC) -> str:
    text = body.rstrip()
    signature = account.signature.strip()
    if signature:
        text += "\n\n-- \n" + signature
    if quote and parent is not None and parent.body.strip():
        cited = "\n".join("> " + line for line in parent.body.splitlines())
        text += f"\n\n{_quote_head(parent.sender, parent.date, tz)}\n{cited}"
    return text


def digest(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8", "replace")).hexdigest()[:32]


def blocked(draft: Draft, account: AccountInfo | None, text: str = "") -> str:
    """Pourquoi ce brouillon ne peut pas partir tel quel (vide : il peut). Un « [À COMPLÉTER »,
    sous n'importe quelle graphie, ne part jamais : ni dans le texte, ni dans l'objet, ni dans ce qui
    partirait vraiment (``text`` : signature et citation comprises)."""
    if account is None:
        return "ce compte n'existe plus"
    if not account.can_send:
        return "ce compte ne peut pas envoyer (serveur d'envoi manquant ou compte inactif)"
    if not addresses(draft.to):
        return "aucun destinataire valide"
    if to_fill(draft.body, draft.subject):
        return "il reste des passages à compléter ([À COMPLÉTER …])"
    if text and to_fill(text):
        return ("il reste un passage « [À COMPLÉTER » dans la signature ou dans le mail cité : retire-le, ou "
                "décoche la citation")
    return ""


def preview(draft: Draft, account: AccountInfo | None, parent: Mail | None, *, tz: tzinfo = UTC,
            her: str = DEFAULT_NAME) -> Preview:
    who = sender(account, her) if account is not None else ""
    text = final_text(draft.body, account, parent, quote=draft.quote, tz=tz) if account is not None else draft.body
    parent_id = parent.message_id if parent is not None else ""
    return Preview(sender=who, to=draft.to, cc=draft.cc, subject=draft.subject, text=text,
                   digest=digest(who, draft.to, draft.cc, draft.subject, text, parent_id),
                   blocked=blocked(draft, account, text) or ("le message cité est incomplet : ouvre sa fiche et charge le message intégral"
                           if draft.quote and parent is not None and not parent.complete else ""))


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
