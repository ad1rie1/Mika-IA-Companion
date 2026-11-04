"""La console de Teams (Relations & échanges › Teams) : ses conversations, ses réponses, l'extension.

Sur la fiche d'une réponse, **exactement ce qui partira** (la signature comprise) ; quand elle attend ton accord
(mode « après ton accord »), tu peux l'envoyer telle quelle, la retoucher (c'est alors ta version qui part : ce que
tu as lu), la refuser (elle l'apprend, avec ta note), ou lui demander de la reprendre. Sur la fiche d'une
conversation, tu peux lui demander de préparer une réponse au dernier message reçu.

**Un Teams par personne** (ADR 0186) : chaque onglet se lit par propriétaire (« Les comptes de », ``?qui=`` : tout le
monde, toi, elle par son nom, chaque personne qui a un compte Teams) puis par compte (``?compte=``) — un affichage,
pas un droit. L'extension se branche compte par compte : sa clé se crée et se retire sur l'onglet Extension. La fiche
d'une personne a l'onglet « Teams » (``teams``) quand un compte est à elle.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Annotated, Any

from pydantic import BaseModel, Field

from mika.contracts import identity as identity_c
from mika.contracts import self_ as self_c
from mika.contracts import teams as c
from mika.kernel.events import Content
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    ActionSlot,
    Badge,
    Block,
    Column,
    Disclosure,
    Fields,
    Head,
    InspectContext,
    Nav,
    NavItem,
    Note,
    Prose,
    Ref,
    Row,
    Table,
    Text,
    When,
    paginate,
)
from mika.kernel.operate import Decision, Done, Refused
from mika.plugins.teams import (
    APPROVED,
    EXPIRED,
    FAILED,
    GONE,
    PLACED,
    QUEUED,
    REFUSED,
    TEAMS,
    UNUSED,
    WAITING,
    DraftSeen,
    TeamsState,
    her,
    latest,
    params_of,
    person_name,
    under_way,
)
from mika.plugins.teams.accounts import Scope
from mika.ports.teams import MODES, conversation_key, split_conversation_key, to_fill
from mika.vocab.access import PERSON, SELF
from mika.vocab.privacy import Sensitivity

SECTION = "teams"
PAGE = 25
NO_PORT = "Teams n'est pas branché ici."
KIND_LABEL = {"dm": "tête-à-tête", "group": "groupe", "channel": "canal", "meeting": "réunion", "other": "—"}
STATE_LABEL = {WAITING: ("attend ton accord", "warn"), APPROVED: ("approuvée", "info"), REFUSED: ("refusée", ""),
               EXPIRED: ("pas d'accord à temps", ""),
               QUEUED: ("en file", "info"), PLACED: ("posée dans Teams", "info"), GONE: ("partie", "ok"),
               UNUSED: ("pas servie", ""), FAILED: ("échec", "danger")}
MODE_LABEL = dict(MODES)


def _badge(state: str) -> Badge:
    label, tone = STATE_LABEL.get(state, (state, ""))
    return Badge(label, tone)


def _clip(text: str, n: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _waiting_count(s: TeamsState, frame: Frame) -> tuple[int, str]:
    return sum(1 for d in s.drafts.values() if d.state == WAITING), "réponse(s) Teams à décider"


def _to_answer(s: TeamsState, account: str, conversation: str) -> int:
    return sum(1 for m in s.messages.values()
               if m.account == account and m.conversation == conversation and m.needs_reply and not m.answered)


# ── à qui sont les comptes montrés (ADR 0186) ──

#: le paramètre qui choisit à qui sont les comptes montrés : vide, tout le monde ; « toi » (ses propriétaires) ;
#: « elle » ; « personne:<clé> » — puis celui qui choisit un compte
WHOSE, YOURS, ACCOUNT = "qui", "toi", "compte"
#: les paramètres d'adresse des onglets de Teams


def whose(ctx: InspectContext) -> str:
    """À qui sont les comptes qu'on a choisi de voir (``?qui=``) ; vide : tout le monde."""
    return ctx.param(WHOSE)


def owner_name(frame: Frame | None, owner: str) -> str:
    """Le propriétaire d'un compte en mots : « Toi », son nom à elle, le nom d'une personne."""
    if not owner:
        return "Toi"
    if owner == SELF:
        return (self_c.name_of(frame.get(self_c.PERSONA)) if frame is not None else "") or "Elle"
    key = owner[len(PERSON):]
    return (person_name(frame, key) if frame is not None else "") or key


def scoped(port: Any, ctx: InspectContext) -> Any:
    """Le port, réduit aux comptes de qui on a choisi ; tel quel pour tout le monde."""
    chosen = whose(ctx)
    if port is None or not chosen:
        return port
    owner = "" if chosen == YOURS else chosen
    return Scope(port, [a.key for a in port.accounts() if a.owner == owner])


def chosen_account(port: Any, ctx: InspectContext) -> str:
    """Le compte choisi (``?compte=``), s'il est parmi ceux qu'on montre ; sinon, le seul qu'on montre ; sinon rien
    (tous)."""
    accounts = [a.key for a in port.accounts()] if port is not None else []
    wanted = ctx.param(ACCOUNT)
    if wanted in accounts:
        return wanted
    return accounts[0] if len(accounts) == 1 else ""


def kept(ctx: InspectContext, *, account: bool = True) -> tuple[tuple[str, str], ...]:
    """Ce qu'un lien des onglets de Teams garde du choix : ``?qui=`` et ``?compte=``, s'il y en a."""
    names = (WHOSE, ACCOUNT) if account else (WHOSE,)
    return tuple((k, ctx.param(k)) for k in names if ctx.param(k))


def _navs(port: Any, ctx: InspectContext, frame: Frame, base: str) -> list[Block]:
    """« Les comptes de » : tout le monde, toi, elle (toujours : une personne comme les autres, ADR 0184), puis chaque
    personne qui a un compte Teams, par son nom ; puis ses comptes, quand il y en a plusieurs à choisir."""
    every = port.port.accounts() if isinstance(port, Scope) else port.accounts()
    people = sorted({a.owner for a in every if a.owner.startswith(PERSON)},
                    key=lambda o: owner_name(frame, o).casefold())
    chosen = whose(ctx)
    items = [NavItem("Tout le monde", Ref("local", base, ""), active=not chosen)]
    for owner in ("", SELF, *people):  # sans chiffre, comme dans le courrier
        value = YOURS if not owner else owner
        items.append(NavItem(owner_name(frame, owner), Ref("local", base, "", ((WHOSE, value),)),
                             active=chosen == value))
    out: list[Block] = [Nav(tuple(items), title="Les comptes de")]
    shown = port.accounts()
    if len(shown) > 1:
        account = ctx.param(ACCOUNT)
        mine = [NavItem("Tous les comptes", Ref("local", base, "", kept(ctx, account=False)), active=not account)]
        mine += [NavItem(a.name, Ref("local", base, "", (*kept(ctx, account=False), (ACCOUNT, a.key))),
                         active=account == a.key, tone="" if a.last_batch else "warn") for a in shown]
        out.append(Nav(tuple(mine), title="Comptes"))
    return out


def _nothing_for(frame: Frame, ctx: InspectContext) -> Note:
    name = owner_name(frame, "" if whose(ctx) == YOURS else whose(ctx))
    return Note(f"Aucun compte Teams n'est à {name}. Dans Réglages › Plugins › Teams, un compte se donne à quelqu'un "
                "par « À qui ».", title="Aucun compte", tone="info")


def _unplugged(port: Any, account: str) -> Note | None:
    """Ce que dit un onglet quand aucune extension n'a encore rien apporté (de ce compte, ou de ceux qu'on montre)."""
    if port.configured(account) if account else port.configured():
        return None
    return Note("L'extension n'a encore rien apporté. Installe-la dans le navigateur où ce Teams est ouvert, colle "
                "la clé de son compte (Teams › Extension), et ouvre Teams.", tone="info")


@TEAMS.inspect("conversations", title="Conversations", section=SECTION, order=10,
               description="Les conversations Teams que l'extension de chaque compte lui a apportées, la plus récente "
                           "d'abord.")
def _conversations(s: TeamsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = scoped(ctx.ports.get("teams"), ctx)
    if port is None:
        return [Note(NO_PORT, tone="muted")]
    navs = _navs(port, ctx, frame, f"/inspecteur/{SECTION}/conversations")
    if not port.accounts():
        return [*navs, _nothing_for(frame, ctx)]
    account = chosen_account(port, ctx)
    unplugged = _unplugged(port, account)
    if unplugged is not None:
        return [*navs, unplugged]
    keys = [account] if account else [a.key for a in port.accounts()]
    names = {a.key: a.name for a in port.accounts()}
    several = len(keys) > 1
    found = port.conversations(200, accounts=keys)
    page, pager = paginate(found, ctx.pager(size=PAGE))

    def row(conv: Any) -> Row:
        title = _clip(port.title(conv.account, conv.id), 80) or "sans nom"
        n = _to_answer(s, conv.account, conv.id)
        cells: tuple[Any, ...] = (Text(title), Text(KIND_LABEL.get(conv.kind, "—"), "muted"), conv.messages,
                                  Badge(f"{n} question(s)", "warn") if n else "", When(conv.last_at))
        if several:
            cells += (Text(names.get(conv.account, conv.account), "muted"),)
        return Row(cells, href=Ref.subject("conversation_teams", conversation_key(conv.account, conv.id),
                                           _clip(title, 60)))

    columns: tuple[Any, ...] = (Column("conversation", role="title"), Column("sorte", "fit"), Column("messages", "num"),
                                Column("questions", "fit", role="badge"), Column("le dernier", "fit"))
    if several:
        columns += (Column("compte", "fit"),)
    return [*navs, Table(columns, tuple(row(conv) for conv in page), title=f"Conversations ({len(found)})",
                         pager=pager, empty="aucune conversation", layout="list", link_label="Lire la conversation")]


@TEAMS.inspect("reponses", title="Réponses", section=SECTION, order=20, badge=_waiting_count,
               description="Ce qu'elle a préparé à la place de la personne de chaque compte, et ce que c'est devenu.")
def _replies(s: TeamsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = scoped(ctx.ports.get("teams"), ctx)
    if port is None:
        return [Note(NO_PORT, tone="muted")]
    navs = _navs(port, ctx, frame, f"/inspecteur/{SECTION}/reponses")
    if not port.accounts():
        return [*navs, _nothing_for(frame, ctx)]
    account = chosen_account(port, ctx)
    keys = {account} if account else {a.key for a in port.accounts()}
    drafts = sorted((d for d in s.drafts.values() if d.account in keys), key=lambda d: (d.state != WAITING, -d.proposal))
    page, pager = paginate(drafts, ctx.pager(size=PAGE))

    def row(d: DraftSeen) -> Row:
        got = port.draft(d.draft)
        title = _clip(port.title(d.account, d.conversation), 60)
        return Row((Text(title or "—"), Text(_clip(got.body, 120) if got else "(disparue)"),
                    Badge("demandée" if d.asked else "d'elle-même", "info" if d.asked else ""), When(d.at),
                    _badge(d.state), Badge("retouchée", "warn") if d.edited else ""),
                   href=Ref.subject("reponse_teams", d.draft, title or d.draft),
                   tone="warn" if d.state == WAITING else "")

    return [*navs, Note("Ce qu'elle prépare d'elle-même et comment ses réponses partent, conversation par "
                        "conversation : Relations & échanges › Envoyer à ta place.", tone="info"),
            Table((Column("conversation", role="title"), Column("réponse", role="body"), Column("pourquoi", "fit"),
                   Column("proposée", "fit"), Column("état", "fit", role="badge"),
                   Column("retouche", "fit", role="badge")), tuple(row(d) for d in page),
                  title=f"Réponses ({len(drafts)})", pager=pager, empty="aucune réponse préparée", layout="cards",
                  link_label="Examiner la réponse")]


def _key_state(ctx: InspectContext, account: str) -> Any:
    keys = ctx.ports.get("teams_keys")
    return keys.key_state(account) if keys is not None else None


def _key_words(ctx: InspectContext, account: str) -> str:
    state = _key_state(ctx, account)
    return f"définie ({state.hint}…), le {ctx.when(state.created_at)}" if state is not None else "aucune"


@TEAMS.inspect("extension", title="Extension", section=SECTION, order=30,
               description="L'extension de navigateur de chaque compte : ce qu'elle a apporté, sa clé, comment la "
                           "brancher.")
def _extension(s: TeamsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = scoped(ctx.ports.get("teams"), ctx)
    if port is None:
        return [Note(NO_PORT, tone="muted")]
    navs = _navs(port, ctx, frame, f"/inspecteur/{SECTION}/extension")
    if not port.accounts():
        return [*navs, _nothing_for(frame, ctx)]
    account = chosen_account(port, ctx)
    if not account:  # plusieurs comptes : un par ligne, chacun mène à son extension
        rows = tuple(Row((Text(a.name), Text(owner_name(frame, a.owner)),
                          Text("inactif" if not a.enabled else _key_words(ctx, a.key)),
                          When(a.last_batch) if a.last_batch else "jamais", Text(a.self_name or "pas encore vu")),
                         href=Ref("local", f"/inspecteur/{SECTION}/extension", a.name,
                                  (*kept(ctx, account=False), (ACCOUNT, a.key))),
                         tone="muted" if not a.enabled else "" if a.last_batch else "warn") for a in port.accounts())
        return [*navs, Table((Column("compte", role="title"), Column("à qui", "fit"), Column("clé", "fit"),
                              Column("dernier envoi", "fit"), Column("son nom dans Teams", "fit")), rows,
                             title=f"Comptes Teams ({len(rows)})", empty="aucun compte", layout="list",
                             link_label="Brancher son extension")]
    info = port.account(account)
    owner_id, self_name = port.owner(account)
    plugged = port.configured(account)
    pairs: list[tuple[str, Any]] = [
        ("le compte", f"{info.name}, à {'toi' if not info.owner else owner_name(frame, info.owner)}"
         + ("" if info.enabled else " — inactif : son extension est refusée")
         if info is not None else account),
        ("clé du compte", Text(account, "mono")),
        ("dernier envoi de l'extension", When(port.last_batch(account)) if plugged else "jamais"),
        ("son nom dans Teams", self_name or "pas encore vu"), ("son identifiant Teams", owner_id or "pas encore vu"),
        ("messages remarqués (en tête)", sum(1 for m in s.messages.values() if m.account == account)),
        ("sa clé", _key_words(ctx, account)),
        ("clé, signature", Ref("local", "/inspecteur/reglages/teams", "Réglages › Plugins › Teams")),
        ("ce qu'elle prépare, comment ça part", Ref("local", "/inspecteur/envoi", "Envoyer à ta place")),
    ]
    blocks: list[Block] = [*navs, Fields(tuple(pairs), title="L'extension", columns=1),
                           Note("L'extension (frontend/Extension) lit ce que Teams web reçoit dans le navigateur où ce "
                                "compte est ouvert et l'apporte ici ; elle relève ce qui doit repartir de lui (un "
                                "brouillon à poser, un message à envoyer). Rien ne parle à Microsoft depuis ce "
                                "serveur.", tone="muted")]
    if ctx.ports.get("teams_keys") is not None:
        actions: list[Block] = [ActionSlot("teams.cle", ((ACCOUNT, account),), title="Nouvelle clé",
                                           presentation="button")]
        if _key_state(ctx, account) is not None:
            actions.append(ActionSlot("teams.retirer_cle", ((ACCOUNT, account),), title="Retirer la clé",
                                      presentation="button"))
        blocks.append(Disclosure("Sa clé", tuple(actions), open=not plugged))
    return blocks


# ── Les comptes Teams d'une personne (sa fiche, ADR 0186) ─────────────────


def _owner_of_person(frame: Frame, person: str) -> str:
    """Le propriétaire qu'une personne est pour un compte : ses propriétaires (toi) sont « à toi » (vide), une autre
    personne ``personne:<clé>``."""
    return "" if frame.get(identity_c.IS_OWNER(person)) else PERSON + person


def _owns_accounts(s: TeamsState, person: str, frame: Frame) -> bool:
    """La fiche d'une personne a l'onglet Teams si un compte est à elle (ses propriétaires : un compte sans
    propriétaire nommé)."""
    owner = _owner_of_person(frame, person)
    owners = params_of(frame).owners
    return (owner in owners.values()) if owner else (not owners or "" in owners.values())


@TEAMS.inspect("teams", title="Teams", subject="person", order=65, shown=_owns_accounts,
               description="Les comptes Teams qui sont à cette personne (ADR 0186) : elle s'en sert avec elle seulement "
                           "— en tête-à-tête, reconnue ; les tiens, avec toi et quand elle travaille.")
def _person_accounts(s: TeamsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = ctx.ports.get("teams")
    if port is None:
        return [Note(NO_PORT, tone="muted")]
    owner = _owner_of_person(frame, ctx.subject)
    whose_value = YOURS if not owner else owner
    rows = []
    for a in (a for a in port.accounts() if a.owner == owner):
        plugged = port.configured(a.key)
        state = Badge("inactif", "muted") if not a.enabled else Badge("branché", "ok") if plugged else \
            Badge("jamais branché" if _key_state(ctx, a.key) is not None else "clé à créer", "warn")
        rows.append(Row((Text(a.name), state, When(a.last_batch) if a.last_batch else "jamais",
                         Ref("local", f"/inspecteur/{SECTION}/conversations", "Ses conversations",
                             ((WHOSE, whose_value), (ACCOUNT, a.key)))),
                        href=Ref("local", f"/inspecteur/{SECTION}/extension", a.name,
                                 ((WHOSE, whose_value), (ACCOUNT, a.key))),
                        tone="" if plugged else "warn"))
    return [Table((Column("compte", role="title"), Column("état", "fit", role="badge"),
                   Column("dernier envoi de l'extension", "fit"), Column("lire", "fit")), tuple(rows),
                  title=f"Teams ({len(rows)})", empty="aucun compte Teams à son nom",
                  caption=f"Un compte Teams se donne à {'toi' if not owner else owner_name(frame, owner)} dans "
                          "Réglages › Plugins › Teams (« À qui »).")]


# ── Une conversation ──────────────────────────────────────────────────────


@TEAMS.subject("conversation_teams", label="Conversation Teams", plural="Conversations Teams", icon="✆")
def _conversation_head(s: TeamsState, frame: Frame, ctx: InspectContext, key: str) -> Head | None:
    port = ctx.ports.get("teams")
    account, conversation = split_conversation_key(key)
    found = port.conversation(account, conversation) if port is not None else None
    if found is None:
        return None
    return Head(key=key, title=_clip(port.title(account, conversation), 200) or "Une conversation",
                subtitle=KIND_LABEL.get(found.kind, ""),
                facts=(("messages", str(found.messages)), ("le dernier", ctx.when(found.last_at))),
                back=Ref("local", f"/inspecteur/{SECTION}/conversations", "Retour aux conversations"))


@TEAMS.inspect("fil", title="Fil", subject="conversation_teams", order=10,
               description="Les derniers messages, du plus ancien au plus récent.")
def _thread(s: TeamsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = ctx.ports.get("teams")
    account, conversation = split_conversation_key(ctx.subject)
    if port is None or port.conversation(account, conversation) is None:
        return [Note("Cette conversation n'est plus là.", tone="muted")]
    thread = port.thread(account, conversation, 60)
    rows = tuple(Row((When(m.at), Text("toi" if m.own else _clip(m.author, 60)), Text(m.text, clamp=600),
                      Badge("question", "warn") if (seen := s.messages.get(m.ref)) and seen.needs_reply else "")
                     ) for m in thread)
    blocks: list[Block] = [Table((Column("quand", "fit"), Column("qui", "fit", role="title"), Column("message", role="body"), Column("question", "fit", role="badge")), rows,
                                 title="Le fil", empty="aucun message", layout="feed")]
    received = [m for m in thread if not m.own]
    if received and not under_way(s, account, conversation):
        last = received[-1]
        blocks.append(Disclosure("Lui demander de préparer une réponse", (ActionSlot("teams.rediger", (
            ("message", last.ref),), title="Préparer une réponse au dernier message"),)))
    return blocks


# ── Une réponse ───────────────────────────────────────────────────────────


@TEAMS.subject("reponse_teams", label="Réponse Teams", plural="Réponses Teams", icon="✎")
def _reply_head(s: TeamsState, frame: Frame, ctx: InspectContext, key: str) -> Head | None:
    port = ctx.ports.get("teams")
    got = port.draft(key) if port is not None else None
    seen = latest(s, key)
    if got is None and seen is None:
        return None
    badges = [_badge(seen.state)] if seen is not None else []
    if got is not None and to_fill(got.body):
        badges.append(Badge("à compléter", "warn"))
    title = _clip(port.title(got.account, got.conversation), 120) if got is not None and port is not None else ""
    return Head(key=key, title=f"Réponse dans « {title or 'une conversation'} »", badges=tuple(badges),
                facts=(("proposée", ctx.when(seen.at)),) if seen is not None else (),
                back=Ref("local", f"/inspecteur/{SECTION}/reponses", "Retour aux réponses"))


@TEAMS.inspect("reponse", title="Réponse", subject="reponse_teams", order=10,
               description="Exactement ce qui part (ou est parti), et ce que tu peux en faire.")
def _reply(s: TeamsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = ctx.ports.get("teams")
    got = port.draft(ctx.subject) if port is not None else None
    if got is None:
        return [Note("Cette réponse n'est plus là.", tone="muted")]
    seen = latest(s, got.id)
    shown = port.preview(got.id, her=her(frame))
    answered = port.message(got.reply_to) if got.reply_to else None
    pairs: list[tuple[str, Any]] = [
        ("conversation", Ref.subject("conversation_teams", conversation_key(got.account, got.conversation),
                                     _clip(port.title(got.account, got.conversation), 80) or "ouvrir")),
        ("en réponse à", Text(f"{answered.author} : {_clip(answered.text, 200)}") if answered is not None else "—"),
        ("mode", MODE_LABEL.get(seen.mode, seen.mode) if seen is not None else "—"),
    ]
    if got.sent_text and got.edited:
        pairs.append(("ce qui est vraiment parti", Text(got.sent_text, clamp=600)))
    if got.reason:
        pairs.append(("pourquoi", got.reason))
    blocks: list[Block] = [Fields(tuple(pairs), title="Où elle va", columns=1)]
    text = got.final or (shown.text if shown is not None else got.body)
    blocks.append(Prose(text, title="Le texte, tel qu'il part (signature comprise)"))
    if seen is not None and seen.state == WAITING and got.state == "brouillon":
        if shown is not None and not shown.blocked:
            blocks.append(ActionSlot("teams.envoyer", (("draft", got.id), ("seen", shown.digest),
                                                       ("_bouton", "Envoyer telle quelle")), compact=True))
        elif shown is not None:
            blocks.append(Note(f"Elle ne peut pas partir telle quelle : {shown.blocked}. Retouche-la.", tone="warn"))
        blocks.append(Disclosure("La retoucher", (ActionSlot("teams.retoucher", (("draft", got.id), ("body", got.body)),
                                                             title="Retoucher"),), open=bool(shown and shown.blocked)))
        blocks.append(Disclosure("La refuser", (ActionSlot("teams.refuser", (("draft", got.id),), title="Refuser"),)))
        if got.reply_to:
            blocks.append(Disclosure("Lui demander de la reprendre", (ActionSlot("teams.reprendre", (
                ("draft", got.id),), title="La reprendre"),)))
    elif seen is not None:
        label = STATE_LABEL.get(seen.state, (seen.state, ""))[0]
        note = ""
        if seen.note_ref:
            note = ctx.store.content([seen.note_ref]).get(seen.note_ref, "(oublié)")
        blocks.append(Note(f"État : {label}." + (f" Note : « {note or seen.note} »." if note or seen.note else ""),
                           tone="info"))
    return blocks


# ── Décider, demander ─────────────────────────────────────────────────────


class SendArgs(BaseModel):
    draft: Annotated[str, Knob(label="Réponse", widget="hidden")] = Field(min_length=1, max_length=100)
    #: le condensé de ce qui était montré (l'accord porte sur ce qui a été lu)
    seen: Annotated[str, Knob(label="Lu", widget="hidden")] = Field(default="", max_length=100)


class RetouchArgs(BaseModel):
    draft: Annotated[str, Knob(label="Réponse", widget="hidden")] = Field(min_length=1, max_length=100)
    body: Annotated[str, Knob(label="Message", widget="textarea", advanced=False,
                              help="Sans signature : elle est ajoutée.")] = Field(min_length=1, max_length=4000)


class RefuseArgs(BaseModel):
    draft: Annotated[str, Knob(label="Réponse", widget="hidden")] = Field(min_length=1, max_length=100)
    note: Annotated[str, Knob(label="Pourquoi", widget="textarea", advanced=False,
                              help="Facultatif : elle le saura.")] = Field(default="", max_length=500)


class RedoArgs(BaseModel):
    draft: Annotated[str, Knob(label="Réponse", widget="hidden")] = Field(min_length=1, max_length=100)
    instruction: Annotated[str, Knob(label="Ce qu'il faut changer", widget="textarea", advanced=False)] = \
        Field(min_length=2, max_length=4000)


class AskArgs(BaseModel):
    message: Annotated[str, Knob(label="Message", widget="hidden")] = Field(min_length=1, max_length=40)
    instruction: Annotated[str, Knob(label="Ce qu'il faut y dire", widget="textarea", advanced=False,
                                     help="Facultatif : sinon, elle répond comme elle l'entend.")] = \
        Field(default="", max_length=4000)


def _waiting(s: TeamsState, draft_id: str) -> DraftSeen:
    seen = latest(s, draft_id)
    if seen is None or seen.state != WAITING:
        raise Refused("Cette réponse n'attend plus de décision.")
    return seen


@TEAMS.action("envoyer", title="Envoyer cette réponse", args=SendArgs, emits=[],
              confirm="L'envoyer dans Teams, sous ton nom, telle qu'elle est montrée ?")
def _send(s: TeamsState, frame: Frame, args: SendArgs, ctx: Any) -> Done:
    seen = _waiting(s, args.draft)
    return Done(decide=(Decision(seen.proposal, True, seen=args.seen),),
                message="Approuvée : l'extension l'enverra (telle que tu l'as lue).",
                go=Ref.subject("reponse_teams", args.draft, ""))


@TEAMS.action("retoucher", title="Retoucher cette réponse", args=RetouchArgs, emits=[],
              description="Ta version remplace la sienne ; relis-la, puis envoie-la.")
def _retouch(s: TeamsState, frame: Frame, args: RetouchArgs, ctx: Any) -> Done:
    _waiting(s, args.draft)
    port = ctx.ports.get("teams")
    got = port.draft(args.draft) if port is not None else None
    if got is None or got.state != "brouillon":
        raise Refused("Cette réponse n'est plus modifiable.")
    port.save_draft(replace(got, body=args.body.strip(), edited_by=ctx.by))
    return Done(message="Retouchée : relis ce qui partira, puis envoie-la.", go=Ref.subject("reponse_teams", got.id, ""))


@TEAMS.action("refuser", title="Refuser cette réponse", args=RefuseArgs, emits=[],
              confirm="Refuser cette réponse ? Elle ne partira pas.")
def _refuse(s: TeamsState, frame: Frame, args: RefuseArgs, ctx: Any) -> Done:
    seen = _waiting(s, args.draft)
    port = ctx.ports.get("teams")
    if port is not None:
        port.discard_draft(args.draft)
    return Done(decide=(Decision(seen.proposal, False, note=args.note.strip()),), message="Refusée : elle le saura.",
                go=Ref.subject("reponse_teams", args.draft, ""))


@TEAMS.action("reprendre", title="Lui demander de la reprendre", args=RedoArgs, emits=[c.DRAFT_ASKED],
              description="Refuse celle-ci ; elle en écrira une autre, en tenant compte de ce que tu dis.")
def _redo(s: TeamsState, frame: Frame, args: RedoArgs, ctx: Any) -> Done:
    seen = _waiting(s, args.draft)
    if not seen.message:
        raise Refused("Ce n'est pas une réponse à un message : refuse-la.")
    port = ctx.ports.get("teams")
    if port is not None:
        port.discard_draft(args.draft)
    asked = c.DRAFT_ASKED.draft(message=seen.message, conversation=seen.conversation, by=ctx.by,
                                instruction=Content.of(args.instruction.strip(), level=int(Sensitivity.PERSONAL)),
                                about=(ctx.by,) if ctx.by else (), account=seen.account)
    return Done(drafts=(asked,), decide=(Decision(seen.proposal, False, note=f"à reprendre : {args.instruction}"[:500]),),
                message="Demandé : elle la reprendra à son prochain moment de travail.",
                go=Ref("local", f"/inspecteur/{SECTION}/reponses", ""))


@TEAMS.action("rediger", title="Lui demander une réponse", args=AskArgs, emits=[c.DRAFT_ASKED],
              subject="conversation_teams",
              description="Elle préparera une réponse au dernier message reçu, selon le mode réglé.")
def _ask(s: TeamsState, frame: Frame, args: AskArgs, ctx: Any) -> Done:
    port = ctx.ports.get("teams")
    m = port.message(args.message) if port is not None else None
    if m is None:
        raise Refused("Ce message n'est plus là.")
    asked_still = m.ref in s.asked and s.attempts.get(m.ref, 0) < params_of(frame).draft_attempts_max
    if under_way(s, m.account, m.conversation) or asked_still:
        raise Refused("Une réponse est déjà en chemin dans cette conversation.")
    instruction = args.instruction.strip()
    asked = c.DRAFT_ASKED.draft(message=m.ref, conversation=m.conversation, by=ctx.by,
                                instruction=Content.of(instruction, level=int(Sensitivity.PERSONAL)) if instruction
                                else None, about=(ctx.by,) if ctx.by else (), account=m.account)
    return Done(drafts=(asked,), message="Demandé : elle la préparera à son prochain moment de travail.",
                go=Ref("local", f"/inspecteur/{SECTION}/reponses", ""))


# ── La clé de l'extension d'un compte ─────────────────────────────────────


class KeyArgs(BaseModel):
    compte: Annotated[str, Knob(label="Compte", widget="hidden")] = Field(min_length=1, max_length=40)


def _keys(ctx: Any) -> Any:
    keys = ctx.ports.get("teams_keys")
    if keys is None:
        raise Refused(NO_PORT)
    return keys


@TEAMS.action("cle", title="Nouvelle clé", args=KeyArgs, emits=[], order=10, inline=True,
              confirm="L'ancienne clé de ce compte ne vaudra plus rien : son extension devra recevoir la nouvelle.",
              description="Une clé neuve pour l'extension de ce compte, montrée une seule fois : copie-la tout de "
                          "suite. L'ancienne ne vaut plus.")
async def _new_key(s: TeamsState, frame: Frame, args: KeyArgs, ctx: Any) -> Done:
    try:
        key = await _keys(ctx).new_key(args.compte, ctx.by)
    except ValueError as exc:
        raise Refused(str(exc)) from None
    return Done(message=f"Clé neuve du compte « {args.compte} » (montrée une seule fois ; l'ancienne ne vaut plus) — "
                        f"colle-la dans son extension : {key}")


@TEAMS.action("retirer_cle", title="Retirer la clé", args=KeyArgs, emits=[], order=20, inline=True, danger=True,
              confirm="L'extension de ce compte sera refusée jusqu'à une clé neuve.",
              description="Sans clé, l'extension de ce compte est refusée (rien n'est reçu, rien ne part) jusqu'à ce "
                          "qu'on en crée une.")
async def _revoke_key(s: TeamsState, frame: Frame, args: KeyArgs, ctx: Any) -> Done:
    if not await _keys(ctx).revoke_key(args.compte, ctx.by):
        raise Refused("Ce compte n'avait pas de clé.")
    return Done(message=f"La clé du compte « {args.compte} » est retirée : son extension est refusée jusqu'à une clé "
                        "neuve.", tone="warn")
