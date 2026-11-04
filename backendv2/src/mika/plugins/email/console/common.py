"""Ce que partagent les vues de la console du courrier : clés, liens, badges.

Un mail est un document venu d'ailleurs : ses cellules restent du texte et
son corps HTML passe par le lecteur à balises autorisées. Une clé de la console
est la référence du mail (``compte:Message-ID``) si elle tient dans une
adresse, sinon une empreinte stable.
"""

from __future__ import annotations

import unicodedata
from dataclasses import replace
from datetime import datetime
from typing import Any

from mika.contracts import email as c
from mika.contracts import self_ as self_c
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
    is_table_choice,
)
from mika.plugins.email import (
    APPROVED,
    FAILED,
    GONE,
    REFUSED,
    REPLIED,
    WAITING,
    EmailParams,
    EmailState,
    Seen,
    operator_label,
    params_of,
    person_name,
)
from mika.plugins.email.boxes import Boxes
from mika.ports.mail import Mail, MailQuery, reference_key, split_ref
from mika.ports.paging import Page
from mika.vocab.access import PERSON, SELF

SECTION = "courrier"
BOX = f"/inspecteur/{SECTION}/reception"
ACCOUNTS = BOX
SETTINGS = "/inspecteur/courrier/parametres"
PAGE = 25
#: une boîte (réception, envoyés) se lit par douzaine : sa liste tient au-dessus du message ouvert
BOX_PAGE = 12
FOLD = 600
#: au-delà, un identifiant ne tient plus dans une adresse de la console : une empreinte le remplace
ID_MAX = 200
DIGEST = "#"
#: les mails remarqués « aujourd'hui » : jamais plus relus que ceci
TODAY_MAX = 500
BATCH = 250
NO_MAIL = "Aucun mail demandé : choisis-en un dans le courrier."
UNKNOWN = "Ce mail n'est ni dans la boîte, ni parmi les envoyés, ni dans ce qu'elle a remarqué."
NOT_CONFIGURED = "Aucune boîte n'est configurée : ajoute un compte dans Courrier › Paramètres."
NO_PORT = "Courrier non configuré : aucune boîte aux lettres n'est branchée."
#: la réception d'une boîte, quelle que soit sa casse sur le serveur (ADR 0171)
INBOX = "INBOX"
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
    """Pas encore lu **par l'opérateur** (ADR 0175) : le drapeau du serveur, qu'un autre client ou la console posent.
    Ce qu'elle a lu n'y compte pas (``by_her``) ; un mail que la boîte n'a plus ne garde que ce qu'elle en sait."""
    if mail is not None:
        return not mail.seen
    return seen is not None and not seen.read


def state_badge(seen: Seen | None, mail: Mail | None, p: EmailParams) -> Badge:
    if unread(mail, seen):
        if seen is not None and important(seen, p):
            return Badge("important, non lu" + (", signalé" if seen.mentioned else ""), "warn")
        return Badge("non lu" + (", signalé" if seen is not None and seen.mentioned else ""), "info")
    return Badge("lu", "ok")


def her_badge(seen: Seen | None) -> Badge | None:
    """Ce qu'elle en a fait, à part du « lu » de l'opérateur : « lu par elle », « archivé par elle »…"""
    if seen is None or not seen.read or not seen.by_her:
        return None
    return Badge(f"{'lu' if seen.how in ('', 'lu') else seen.how} par elle", "info")


def to_answer(seen: Seen | None) -> bool:
    """Son tri y attend une réponse, et personne n'a encore répondu (ni un brouillon d'elle, ni un autre client)."""
    return seen is not None and seen.needs_reply and seen.how != REPLIED


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
        return Note("Aucun compte n'est prêt à relever (serveur, utilisateur ou compte inactif) : voir "
                    "Courrier › Paramètres.", tone="warn")
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


def box_link(text: str, *, account: str = "", folder: str = "", whose: str = "") -> Ref:
    params = tuple((k, v) for k, v in (("compte", account), ("dossier", folder), (WHOSE, whose)) if v)
    return Ref("local", BOX, text, params)


# ── à qui sont les boîtes montrées (ADR 0185) ──

#: le paramètre qui choisit à qui sont les boîtes montrées : vide, tout le monde ; « toi » (ses propriétaires) ;
#: « elle » ; « personne:<clé> »
WHOSE, YOURS = "qui", "toi"


class Scope(Boxes):
    """La console réduite aux boîtes de qui on a choisi : un affichage, pas un droit — le reste du port passe tel
    quel (ses outils, eux, ont ``Boxes``, sans rien qui passe à côté)."""

    def __getattr__(self, name: str) -> Any:
        return getattr(self.port, name)

    def outgoing_page(self, query: MailQuery, page: int = 1, size: int = 25) -> Any:
        if query.account and not self._mine(query.account):
            return Page.of([], page, size)
        return self.port.outgoing_page(replace(query, accounts=self.keys), page, size)


def whose(ctx: InspectContext) -> str:
    """À qui sont les boîtes qu'on a choisi de voir (``?qui=``) ; vide : tout le monde."""
    return ctx.param(WHOSE)


def scoped(port: Any, ctx: InspectContext) -> Any:
    """Le port, réduit aux boîtes de qui on a choisi ; tel quel pour tout le monde."""
    chosen = whose(ctx)
    if port is None or not chosen:
        return port
    owner = "" if chosen == YOURS else chosen
    return Scope(port, [a.key for a in port.accounts() if a.owner == owner])


def kept(ctx: InspectContext) -> tuple[tuple[str, str], ...]:
    """Ce qu'un lien de l'espace courrier garde du choix de qui : ``?qui=``, s'il y en a un."""
    return ((WHOSE, whose(ctx)),) if whose(ctx) else ()


def owner_name(frame: Frame | None, owner: str) -> str:
    """Le propriétaire d'une boîte en mots : « Toi », son nom à elle, le nom d'une personne."""
    if not owner:
        return "Toi"
    if owner == SELF:
        return (self_c.name_of(frame.get(self_c.PERSONA)) if frame is not None else "") or "Elle"
    key = owner[len(PERSON):]
    return (person_name(frame, key) if frame is not None else "") or key


def _owners(port: Any, ctx: InspectContext, base: str, frame: Frame | None) -> Nav:
    """« Les boîtes de » : tout le monde, toi, elle (toujours : une personne comme les autres, ADR 0184), puis chaque
    personne qui a une boîte, par son nom."""
    every = port.port.accounts() if isinstance(port, Scope) else port.accounts() if port is not None else []
    people = sorted({a.owner for a in every if a.owner.startswith(PERSON)}, key=lambda o: owner_name(frame, o).casefold())
    chosen = whose(ctx)
    items = [NavItem("Tout le monde", Ref("local", base, ""), active=not chosen)]
    for owner in ("", SELF, *people):  # sans chiffre : à côté, les chiffres disent des non-lus
        value = YOURS if not owner else owner
        items.append(NavItem(owner_name(frame, owner), Ref("local", base, "", ((WHOSE, value),)),
                             active=chosen == value))
    return Nav(tuple(items), title="Les boîtes de")


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


#: les vues de la réception que la barre de côté nomme (``?etat=``), dans tous les dossiers
VIEWS = {"a_traiter": "À traiter", "suivis": "Suivis"}


def answered(port: Any, ref: str) -> bool:
    """Le serveur dit qu'on y a répondu (depuis la console, un autre client ou un brouillon d'elle parti)."""
    m = port.cached_one(ref) if port is not None else None
    return bool(m is not None and m.answered)


def _views(port: Any, ctx: InspectContext, s: EmailState | None, view: str, account: str) -> Nav:
    """Ce qu'on lit (ADR 0175) : la réception, ce qui attend une réponse, les suivis, ses brouillons à décider, les
    envoyés, les contacts — à la place des onglets, dans le compte choisi."""
    keep = ((("compte", ctx.param("compte")),) if ctx.param("compte") else ()) + kept(ctx)
    state = ctx.param("etat") if view == "reception" else ""
    folder = ctx.param("dossier") or INBOX
    mine = [(k, m) for k, m in (s.mails.items() if s is not None else ()) if not account or m.account == account]
    inbox = sum(f.unseen for a in port.accounts() if not account or a.key == account
                for f in port.folders(a.key) if f.role == "inbox")
    pending = sum(1 for d in (s.drafts.values() if s is not None else ()) if d.state == WAITING
                  and (not account or d.account == account))

    def box(text: str, state_: str = "", count: int | None = None) -> NavItem:
        params = keep + ((("etat", state_), ("dossier", "*")) if state_ else ())
        on = view == "reception" and (state == state_ if state_ else state not in VIEWS and folder == INBOX)
        return NavItem(text, Ref("local", BOX, "", params), count=count or None, active=on)

    def tab(text: str, slug: str, count: int | None = None) -> NavItem:
        return NavItem(text, Ref("local", f"/inspecteur/{SECTION}/{slug}", "", keep), count=count or None,
                       active=view == slug, tone="warn" if count else "")

    return Nav((box("Réception", count=inbox),
                box(VIEWS["a_traiter"], "a_traiter", sum(1 for k, m in mine if to_answer(m) and not answered(port, k))),
                box(VIEWS["suivis"], "suivis"), tab("Ses brouillons", "brouillons", pending), tab("Envoyés", "envoyes"),
                tab("Contacts", "contacts")), title="Courrier")


def workspace(port: Any, ctx: InspectContext, items: list[Block], *, view: str = "reception",
              filters: tuple[Param, ...] = (), folders: bool = False, state: EmailState | None = None,
              frame: Frame | None = None) -> Workspace:
    """Le même espace courrier pour réception, brouillons, envoyés et contacts : à côté, à qui sont les boîtes
    montrées (``?qui=``, ADR 0185), ce qu'on lit, les comptes et les dossiers du compte choisi ; au-dessus, écrire et
    actualiser, puis la recherche. ``folders`` : cette vue montre un dossier (la réception) ; ``port`` : déjà réduit
    (``scoped``) aux boîtes de qui on a choisi."""
    accounts = port.accounts() if port is not None else []
    account = account_scope(port, ctx)
    base = f"/inspecteur/{SECTION}/{view}"
    side: list[Block] = [_owners(port, ctx, base, frame)] if port is not None and (accounts or whose(ctx)) else []
    side += [_views(port, ctx, state, view, account)] if accounts else []
    nav = [NavItem("Toutes les boîtes", Ref("local", base, "", kept(ctx)), active=not ctx.param("compte"))]
    for a in accounts:
        inbox = next((f for f in port.folders(a.key) if f.role == "inbox"), None)
        nav.append(NavItem(a.name, Ref("local", base, "", (("compte", a.key), *kept(ctx))),
                           count=inbox.unseen if inbox else None, active=ctx.param("compte") == a.key,
                           tone="" if a.ready else "warn"))
    side.append(Nav(tuple(nav), title="Comptes"))
    chosen = port.account(account) if port is not None else None
    if chosen:
        side.append(Note(chosen.address, tone="muted"))
    if accounts:
        listed = folders and ctx.param("etat") not in VIEWS
        folder = ctx.param("dossier") or INBOX
        # la réception est en tête de ce qu'on lit : les dossiers disent les autres
        known = [f for f in port.folders(account) if f.role != "inbox" and f.name != INBOX] if chosen else []
        entries = [NavItem(f.label + " (serveur)" if f.role == "drafts" else f.label,
                           box_link(f.label, account=account, folder=f.name, whose=whose(ctx)),
                           count=f.unseen or None, active=listed and folder == f.name) for f in known]
        entries.append(NavItem("Tous les dossiers", box_link("Tous les dossiers", account=account, folder="*",
                                                             whose=whose(ctx)),
                               active=listed and folder == "*"))
        side.append(Nav(tuple(entries), title="Dossiers"))
    actions: list[Block] = []
    if can_send(port) and (not account or (chosen is not None and chosen.can_send)):
        initial = ((("account", account),) if chosen and chosen.can_send else ()) + (("_bouton", "Envoyer le message"),)
        actions.append(ActionSlot("email.ecrire", initial, title="Nouveau message", presentation="button"))
    if folders and chosen and chosen.ready and ctx.param("dossier") != "*":
        actions.append(ActionSlot("email.relire", (("compte", account), ("dossier", ctx.param("dossier") or INBOX)),
                                  title="Actualiser le dossier", presentation="button"))
    elif folders and ready(port):
        actions.append(ActionSlot("email.relever", title="Actualiser les boîtes", presentation="button"))
    content: list[Block] = [Toolbar(tuple(actions))] if actions else []
    if filters:
        keep = tuple((k, v) for k, v in (("compte", account), ("dossier", ctx.param("dossier") if folders else ""),
                                          (WHOSE, whose(ctx))) if v)
        keep += tuple((k, v) for k, v in ctx.params.items() if is_table_choice(k, v))
        content.append(Filters(filters, tuple(ctx.params.items()), keep=keep, title="Rechercher"))
    if chosen:
        status = port.status(account)
        if status.error:
            content.append(Note(f"{chosen.name} : {status.error}", tone="danger", title="Synchronisation en échec"))
        elif not chosen.ready:
            content.append(Note("Ce compte est inactif ou incomplet : règle-le dans Courrier › Paramètres, en haut à droite.",
                                tone="warn"))
    content.extend(items)
    return Workspace(tuple(side), tuple(content))
