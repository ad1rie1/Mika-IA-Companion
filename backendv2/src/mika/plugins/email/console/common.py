"""Ce que partagent les vues de la console du courrier : clés, liens, badges.

Un mail est un document venu d'ailleurs : ses cellules restent du texte et
son corps HTML passe par le lecteur à balises autorisées. Une clé de la console
est la référence du mail (``compte:Message-ID``) si elle tient dans une
adresse, sinon une empreinte stable.
"""

from __future__ import annotations

import unicodedata
from datetime import datetime
from typing import Any

from mika.contracts import email as c
from mika.kernel.clock import MINUTE, instant
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    ActionSlot,
    Badge,
    Block,
    Filters,
    InspectContext,
    Meter,
    Nav,
    NavItem,
    Note,
    Param,
    Ref,
    Toolbar,
    Workspace,
)
from mika.plugins.email import (
    APPROVED,
    FAILED,
    GONE,
    REFUSED,
    WAITING,
    EmailParams,
    EmailState,
    Seen,
    operator_label,
    params_of,
)
from mika.ports.mail import Mail, reference_key, split_ref

SECTION = "courrier"
BOX = f"/inspecteur/{SECTION}/reception"
ACCOUNTS = BOX
SETTINGS = "/inspecteur/reglages/boites"
PAGE = 25
FOLD = 600
#: au-delà, un identifiant ne tient plus dans une adresse de la console : une empreinte le remplace
ID_MAX = 200
DIGEST = "#"
#: les mails remarqués « aujourd'hui » : jamais plus relus que ceci
TODAY_MAX = 500
BATCH = 250
NO_MAIL = "Aucun mail demandé : choisis-en un dans le courrier."
UNKNOWN = "Ce mail n'est ni dans la boîte, ni parmi les envoyés, ni dans ce qu'elle a remarqué."
NOT_CONFIGURED = "Aucune boîte n'est configurée : ajoute un compte dans Configuration › Plugins › Boîtes aux lettres."
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
    return reference_key(ref)


def ready(port: Any) -> bool:
    return port is not None and port.configured()


def can_send(port: Any) -> bool:
    return port is not None and any(a.can_send for a in port.accounts())


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
        known = next((ref for ref in (*s.mails, *s.sent) if mail_key(ref) == key), None)
        return known or (port.find_ref(key) if port is not None else None)
    return None


def resolve_state(s: EmailState, key: str) -> str | None:
    """Comme ``resolve``, sans la boîte (ce qu'une action offerte peut savoir de son état)."""
    if key in s.mails:
        return key
    if key.startswith(DIGEST):
        return next((ref for ref in s.mails if mail_key(ref) == key), None)
    account, bare = split_ref(key)
    if account:
        return None
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
        return Badge(f"écrit par elle, retouché par {operator_label(frame, by)}", "warn")
    return Badge(f"écrit par {operator_label(frame, by)}", "warn") if by else Badge("écrit par elle", "info")


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
                    "Configuration › Plugins › Boîtes aux lettres.", tone="warn")
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


ACCOUNT_PARAM = Param("compte", "Compte", kind="hidden")


def account_scope(port: Any, ctx: InspectContext) -> str:
    """Un compte explicite, ou le seul compte connu. Jamais de repli sur une autre boîte."""
    key = ctx.param("compte")
    accounts = port.accounts() if port is not None else []
    return key or (accounts[0].key if len(accounts) == 1 else "")


def workspace(port: Any, ctx: InspectContext, items: list[Block], *, view: str = "reception",
              filters: tuple[Param, ...] = (), folders: bool = False) -> Workspace:
    """Le même espace courrier pour réception, brouillons, envoyés et contacts."""
    accounts = port.accounts() if port is not None else []
    account = account_scope(port, ctx)
    base = f"/inspecteur/{SECTION}/{view}"
    nav = [NavItem("Toutes les boîtes", Ref("local", base, ""), active=not ctx.param("compte"))]
    for a in accounts:
        inbox = next((f for f in port.folders(a.key) if f.role == "inbox"), None)
        nav.append(NavItem(a.name, Ref("local", base, "", (("compte", a.key),)),
                           count=inbox.unseen if inbox else None, active=ctx.param("compte") == a.key,
                           tone="" if a.ready else "warn"))
    side: list[Block] = [Nav(tuple(nav), title="Comptes")]
    chosen = port.account(account) if port is not None else None
    if chosen:
        side.append(Note(chosen.address, tone="muted"))
    if folders and accounts:
        folder = ctx.param("dossier") or "INBOX"
        known = port.folders(account) if chosen else []
        entries = [NavItem(f.label + " (serveur)" if f.role == "drafts" else f.label, box_link(f.label, account=account, folder=f.name),
                           count=f.unseen or None, active=folder == f.name) for f in known]
        if not known:
            entries.append(NavItem("Réception", box_link("Réception", account=account), active=folder == "INBOX"))
        entries.append(NavItem("Tous les dossiers", box_link("Tous les dossiers", account=account, folder="*"),
                               active=folder == "*"))
        side.append(Nav(tuple(entries), title="Dossiers"))
    side.append(Nav((NavItem("Gérer les comptes", Ref("local", SETTINGS, "")),), title="Configuration"))
    actions: list[Block] = []
    if can_send(port) and (not account or (chosen is not None and chosen.can_send)):
        initial = ((("account", account),) if chosen and chosen.can_send else ()) + (("_bouton", "Envoyer le message"),)
        actions.append(ActionSlot("email.ecrire", initial, title="Nouveau message", presentation="button"))
    if folders and chosen and chosen.ready and ctx.param("dossier") != "*":
        actions.append(ActionSlot("email.relire", (("compte", account), ("dossier", ctx.param("dossier") or "INBOX")),
                                  title="Actualiser le dossier", presentation="button"))
        actions.append(ActionSlot("email.historique", (("compte", account), ("dossier", ctx.param("dossier") or "INBOX")),
                                  title="Charger des messages plus anciens", presentation="button"))
    elif folders and ready(port):
        actions.append(ActionSlot("email.relever", title="Actualiser les boîtes", presentation="button"))
    content: list[Block] = [Toolbar(tuple(actions))] if actions else []
    if filters:
        keep = tuple((k, v) for k, v in (("compte", account), ("dossier", ctx.param("dossier") if folders else "")) if v)
        content.append(Filters(filters, tuple(ctx.params.items()), keep=keep, title="Rechercher"))
    if chosen:
        status = port.status(account)
        if status.error:
            content.append(Note(f"{chosen.name} : {status.error}", tone="danger", title="Synchronisation en échec"))
        elif not chosen.ready:
            content.append(Note("Ce compte est inactif ou incomplet. Ouvre « Gérer les comptes » pour le configurer.",
                                tone="warn"))
    content.extend(items)
    return Workspace(tuple(side), tuple(content))
