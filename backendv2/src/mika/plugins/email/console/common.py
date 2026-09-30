"""Ce que partagent les vues de la console du courrier : clés, liens, badges.

Un mail est un texte venu d'ailleurs : il ne s'affiche qu'en texte (cellules,
``Prose``), jamais en balisage ni dans la clé d'un lien. Une clé de la console
est la référence du mail (``compte:Message-ID``) si elle tient dans une
adresse, sinon une empreinte stable.
"""

from __future__ import annotations

import hashlib
import unicodedata
from datetime import datetime
from typing import Any

from mika.contracts import email as c
from mika.kernel.clock import MINUTE, instant
from mika.kernel.frame import Frame
from mika.kernel.inspect import Badge, InspectContext, Meter, Note, Ref
from mika.plugins.email import (
    APPROVED,
    FAILED,
    GONE,
    REFUSED,
    WAITING,
    EmailParams,
    EmailState,
    Seen,
    operator_name,
    params_of,
)
from mika.ports.mail import Mail, split_ref

SECTION = "courrier"
BOX = f"/inspecteur/{SECTION}/reception"
ACCOUNTS = f"/inspecteur/{SECTION}/comptes"
SETTINGS = "/inspecteur/reglages/sens"
#: la console ne relit pas plus que ceci du cache de la boîte (filtres, pages, recherche, contacts)
CACHE_SHOWN = 500
PAGE = 25
#: le texte d'un mail montré à l'opérateur, au plus ; replié au-delà de ``FOLD``
BODY_SHOWN = 20_000
FOLD = 600
#: au-delà, un identifiant ne tient plus dans une adresse de la console : une empreinte le remplace
ID_MAX = 200
DIGEST = "#"
#: les mails remarqués « aujourd'hui » : jamais plus relus que ceci
TODAY_MAX = 500
BATCH = 250
NO_MAIL = "Aucun mail demandé : choisis-en un dans le courrier."
UNKNOWN = "Ce mail n'est ni dans la boîte, ni parmi les envoyés, ni dans ce qu'elle a remarqué."
NOT_CONFIGURED = "Aucune boîte n'est configurée : ajoute un compte (Courrier › Comptes)."
NO_PORT = "Courrier non configuré : aucune boîte aux lettres n'est branchée."
VOICE_LABEL = {"elle": "en son nom", "assistante": "en assistante", "proprietaire": "à ta place"}
#: où en est un brouillon, en toutes lettres (et son ton) : ce qu'elle en sait (sa proposition)…
DRAFT_STATES = {WAITING: ("attend ton accord", "warn"), APPROVED: ("approuvé, en partance", "info"),
                GONE: ("parti", "ok"), REFUSED: ("refusé", "muted"), FAILED: ("échec de l'envoi", "danger"),
                # … et, à défaut, ce qu'en garde la boîte (``Draft.state``)
                "brouillon": ("brouillon", ""), "envoye": ("parti", "ok"), "abandonne": ("abandonné", "muted")}


def draft_state(state: str) -> tuple[str, str]:
    """L'état d'un brouillon en français, et son ton (jamais le code brut)."""
    return DRAFT_STATES.get(state, ("état inconnu", "muted"))


def clip(text: str, n: int = 120) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def fold(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", str(text).lower()) if not unicodedata.combining(ch))


def mail_key(ref: str) -> str:
    """La clé d'un mail dans la console : sa référence si elle tient dans une
    adresse (bornée, imprimable, sans « / »), sinon une empreinte stable."""
    if 0 < len(ref) <= ID_MAX and ref.isprintable() and "/" not in ref and not ref.startswith(DIGEST):
        return ref
    return DIGEST + hashlib.sha256(ref.encode("utf-8", "replace")).hexdigest()[:24]


def ready(port: Any) -> bool:
    return port is not None and port.configured()


def can_send(port: Any) -> bool:
    return port is not None and any(a.can_send for a in port.accounts())


def gone(port: Any, limit: int = CACHE_SHOWN, account: str = "") -> list[Any]:
    return port.sent_mails(limit, account=account) if port is not None else []


def resolve(s: EmailState, port: Any, key: str) -> str | None:
    """La référence du mail (reçu ou parti) derrière une clé de la console, s'il est connu."""
    key = key.strip()
    if not key or len(key) > 4 * ID_MAX:
        return None
    if key in s.mails or key in s.sent:
        return key
    if port is not None:
        found = port.cached_one(key)
        if found is not None:
            return found.ref
        if port.sent_mail(key) is not None:
            return key
    if key.startswith(DIGEST):
        known = [*s.mails, *s.sent, *(m.ref for m in (port.cached(CACHE_SHOWN) if port is not None else ())),
                 *(m.message_id for m in gone(port))]
        return next((ref for ref in known if mail_key(ref) == key), None)
    return None


def resolve_state(s: EmailState, key: str) -> str | None:
    """Comme ``resolve``, sans la boîte (ce qu'une action offerte peut savoir de son état)."""
    if key in s.mails:
        return key
    if key.startswith(DIGEST):
        return next((ref for ref in s.mails if mail_key(ref) == key), None)
    bare = split_ref(key)[1]
    return next((ref for ref in s.mails if split_ref(ref)[1] == bare), None)


def important(seen: Seen, p: EmailParams) -> bool:
    return seen.importance >= p.mention_from


def unread(mail: Mail | None, seen: Seen | None) -> bool:
    """Pas encore lu : ni sur le serveur (quand on le sait), ni par elle."""
    if mail is not None:
        return not mail.seen and (seen is None or not seen.read)
    return seen is not None and not seen.read


def state_badge(seen: Seen | None, mail: Mail | None, p: EmailParams) -> Badge:
    if unread(mail, seen):
        if seen is not None and important(seen, p):
            return Badge("important, non lu" + (", signalé" if seen.mentioned else ""), "warn")
        return Badge("non lu" + (", signalé" if seen is not None and seen.mentioned else ""), "info")
    how = seen.how if seen is not None and seen.read and seen.how not in ("", "lu") else ""
    return Badge(f"lu ({how})" if how else "lu", "ok")


def pertinence(seen: Seen | None) -> Meter | None:
    return Meter(seen.importance, f"{seen.importance:.2f}") if seen is not None else None


def author(frame: Frame, by: str, *, edited: bool = False) -> Badge:
    if edited:
        return Badge(f"écrit par elle, retouché par {operator_name(frame, by)}".replace("ton opérateur", "l'opérateur"),
                     "warn")
    return Badge(f"écrit par {operator_name(frame, by)}".replace("ton opérateur", "l'opérateur"), "warn") if by \
        else Badge("écrit par elle", "info")


def day_start(frame: Frame) -> int:
    """Minuit, aujourd'hui, à son heure à elle."""
    tz = frame.env.tz_of(frame.root)
    today = frame.local().date()
    return instant(datetime(today.year, today.month, today.day, tzinfo=tz))


def since(ctx: InspectContext, event_type: Any, start: int, cap: int) -> list[Any]:
    """Les événements de ce type depuis cet instant (du plus récent au plus ancien), bornés."""
    out: list[Any] = []
    before = None
    while len(out) < cap:
        want = min(BATCH, cap - len(out))
        batch = ctx.events([event_type], want, before=before)
        for e in batch:
            if e.at < start:
                return out
            out.append(e)
        if len(batch) < want:
            break
        before = batch[-1].seq
    return out


def box_note(port: Any, p: EmailParams) -> Note:
    if port is None:
        return Note(NO_PORT, tone="muted")
    if not port.accounts():
        return Note(NOT_CONFIGURED, tone="warn")
    if not port.configured():
        return Note("Aucun compte n'est prêt à relever (serveur, utilisateur ou compte inactif) : voir Courrier › "
                    "Comptes.", tone="warn")
    n = sum(1 for a in port.accounts() if a.ready)
    boxes = "Boîte aux lettres configurée" if n == 1 else f"{n} boîtes aux lettres configurées"
    return Note(f"{boxes} : relevée(s) toutes les {p.poll_every_us // MINUTE} min quand elle est éveillée "
                "(« Relever maintenant » pour ne pas attendre).", tone="ok")


def edit_account(key: str, back: str = ACCOUNTS) -> Ref:
    """Le lien vers le réglage d'un compte (et le retour au courrier une fois enregistré)."""
    return Ref("local", SETTINGS, "Modifier ce compte",
               (("section", "courrier"), ("enregistrement", "accounts"), ("cle", key), ("retour", back)))


def add_account(back: str = ACCOUNTS) -> Ref:
    return Ref("local", SETTINGS, "Ajouter un compte",
               (("section", "courrier"), ("enregistrement", "accounts"), ("cle", ""), ("nouveau", "1"),
                ("retour", back)))


def box_link(text: str, *, account: str = "", folder: str = "") -> Ref:
    params = tuple((k, v) for k, v in (("compte", account), ("dossier", folder)) if v)
    return Ref("local", BOX, text, params)


def fresh_important(s: EmailState, frame: Frame) -> tuple[int, str]:
    """Le badge du courrier : les mails importants arrivés récemment qu'elle n'a pas encore lus."""
    p = params_of(frame)
    n = sum(1 for m in frame.get(c.UNREAD) if m.importance >= p.mention_from and frame.now - m.at <= p.mention_within_us)
    return n, "mail(s) important(s) pas encore lu(s)"
