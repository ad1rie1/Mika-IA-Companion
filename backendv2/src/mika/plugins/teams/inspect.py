"""La console de Teams (Relations & échanges › Teams) : ses conversations, ses réponses, l'extension.

Sur la fiche d'une réponse, **exactement ce qui partira** (la signature comprise) ; quand elle attend ton accord
(mode « après ton accord »), tu peux l'envoyer telle quelle, la retoucher (c'est alors ta version qui part : ce que
tu as lu), la refuser (elle l'apprend, avec ta note), ou lui demander de la reprendre ; disparue (son compte retiré
des réglages) mais encore à décider, la refuser. Sur la fiche d'une conversation, « Écrire dans cette conversation »
— sur tout compte (ADR 0231) : ton message part aussitôt par l'extension du compte, sous le nom de la personne de ce
compte, ce qu'une note au-dessus du formulaire dit par son nom et que la confirmation redit ; pas quand Teams est coupé
ou le compte décoché (``not_sending``) — et « Lui demander une réponse » au dernier message reçu.

**Un Teams par personne** (ADR 0186) : chaque onglet se lit par propriétaire (« Les comptes de », ``?qui=`` : tout le
monde, toi, elle par son nom, chaque personne qui a un compte Teams) puis par compte (``?compte=``) — un affichage,
pas un droit. Sous « Tout le monde », l'onglet Réponses montre aussi celles d'un compte qui n'est plus réglé (« un
compte retiré ») : ce que son badge compte. L'extension se branche compte par compte : sa clé se crée et se retire
sur l'onglet Extension, qui mène aussi aux réglages du compte (Teams › Paramètres, la roue en haut à droite,
ADR 0206). La fiche d'une personne a l'onglet « Teams » (``teams``) quand un compte est à elle.
"""

from __future__ import annotations

from collections.abc import Iterable
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
    FORGOTTEN,
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
    agree,
    paginate,
    plural,
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
    WRITTEN,
    DraftSeen,
    TeamsParams,
    TeamsState,
    asked_still,
    her,
    latest,
    params_of,
    person_name,
    under_way,
)
from mika.plugins.teams.accounts import Scope
from mika.plugins.teams.reactions import quote_said
from mika.ports.drafts import to_fill
from mika.ports.teams import MODES, OUTBOX_SEND, conversation_key, split_conversation_key
from mika.ports.teams import Draft as TeamsDraft
from mika.vocab.access import PERSON, SELF
from mika.vocab.privacy import Sensitivity

SECTION = "teams"
PAGE = 25
#: le tableau de canal d'un compte (« teams:<clé> », ADR 0134) : pour qui elle prépare, comment ça part
CANALS_PAGE = "canaux"
#: le libellé de la ligne du bloc « Comment ça part » de l'onglet Réponses (et la clé de son aide) ; l'onglet
#: dessiné lit ce bloc par son titre, pas ce libellé
HOW_IT_GOES = "comment ses réponses partent"
#: ses paramètres (« Actif », ses comptes) : une page de réglages, dans Teams, en haut à droite (ADR 0206)
SETTINGS = "teams"
NO_PORT = "Teams n'est pas branché ici."
#: la conversation d'une réponse dont le compte n'est plus réglé (Teams › Réponses, « Tout le monde ») : le port ne la
#: nomme plus
RETIRED = "un compte retiré"
#: le geste qui lui demande une réponse dans une conversation : un seul nom, celui de l'action, que le repli de la
#: fiche reprend (comme au courrier, ADR 0175)
ASK_TITLE = "Lui demander une réponse"
#: le geste qui écrit soi-même dans une conversation (ADR 0189, 0231) : le nom de l'action et du repli de la fiche
WRITE_TITLE = "Écrire dans cette conversation"
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
    """Le badge de l'onglet Réponses : celles qui attendent ton accord, tous comptes — ce que sa liste montre sous
    « Tout le monde » (``_shown_replies``)."""
    n = sum(1 for d in s.drafts.values() if d.state == WAITING)
    return n, agree(n, "réponse Teams à décider", "réponses Teams à décider")


def _to_answer(s: TeamsState, account: str, conversation: str) -> int:
    return sum(1 for m in s.messages.values()
               if m.account == account and m.conversation == conversation and m.needs_reply and not m.answered)


# ── à qui sont les comptes montrés (ADR 0186) ──

#: le paramètre qui choisit à qui sont les comptes montrés : vide, tout le monde ; « toi » (ses propriétaires) ;
#: « elle » ; « personne:<clé> » — puis celui qui choisit un compte
WHOSE, YOURS, ACCOUNT = "qui", "toi", "compte"
#: les paramètres d'adresse des onglets de Teams


def view_link(view: str, text: str = "", params: Iterable[tuple[str, str]] = ()) -> Ref:
    """Un lien vers un onglet de Teams, avec ses paramètres : la console sait où il vit."""
    return Ref.view("teams", view, text, **dict(params))


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


def _navs(port: Any, ctx: InspectContext, frame: Frame, view: str) -> list[Block]:
    """« Les comptes de » : tout le monde, toi, elle (toujours : une personne comme les autres, ADR 0184), puis chaque
    personne qui a un compte Teams, par son nom ; puis ses comptes, quand il y en a plusieurs à choisir."""
    every = port.port.accounts() if isinstance(port, Scope) else port.accounts()
    people = sorted({a.owner for a in every if a.owner.startswith(PERSON)},
                    key=lambda o: owner_name(frame, o).casefold())
    chosen = whose(ctx)
    items = [NavItem("Tout le monde", view_link(view), active=not chosen)]
    for owner in ("", SELF, *people):  # sans chiffre, comme dans le courrier
        value = YOURS if not owner else owner
        items.append(NavItem(owner_name(frame, owner), view_link(view, "", ((WHOSE, value),)),
                             active=chosen == value))
    out: list[Block] = [Nav(tuple(items), title="Les comptes de")]
    shown = port.accounts()
    if len(shown) > 1:
        account = ctx.param(ACCOUNT)
        mine = [NavItem("Tous les comptes", view_link(view, "", kept(ctx, account=False)), active=not account)]
        mine += [NavItem(a.name, view_link(view, "", (*kept(ctx, account=False), (ACCOUNT, a.key))),
                         active=account == a.key, tone="" if a.last_batch else "warn") for a in shown]
        out.append(Nav(tuple(mine), title="Comptes"))
    return out


def _nothing_for(frame: Frame, ctx: InspectContext) -> Note:
    name = owner_name(frame, "" if whose(ctx) == YOURS else whose(ctx))
    return Note(f"Aucun compte Teams n'est à {name}. Dans Teams › Paramètres (en haut à droite), un compte se donne à "
                "quelqu'un par « À qui ».", title="Aucun compte", tone="info")


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
    navs = _navs(port, ctx, frame, "conversations")
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
                                  Badge(plural(n, "question", "questions"), "warn") if n else "", When(conv.last_at))
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


def _shown_replies(s: TeamsState, port: Any, ctx: InspectContext) -> list[DraftSeen]:
    """Les réponses que l'onglet Réponses montre, celles qui attendent ton accord d'abord : celles du compte choisi
    (``?compte=``, parmi ceux qu'on montre) ; sous « Les comptes de » une personne (``?qui=``), celles de ses comptes ;
    sous « Tout le monde », toutes — celles d'un compte qui n'est plus réglé comprises (``drop_account`` emporte son
    brouillon, sa proposition reste au journal jusqu'à son échéance) : ce que le badge de l'onglet compte. Le seul
    compte montré ne réduit pas la liste : ``chosen_account`` ne sert qu'au lien du pied (audit du 2026-11-05, C4-01)."""
    wanted = ctx.param(ACCOUNT)
    shown = {a.key for a in port.accounts()}
    keys = {wanted} if wanted in shown else shown if whose(ctx) else None
    return sorted((d for d in s.drafts.values() if keys is None or d.account in keys),
                  key=lambda d: (d.state != WAITING, -d.proposal))


@TEAMS.inspect("reponses", title="Réponses", section=SECTION, order=20, badge=_waiting_count,
               description="Ce qu'elle a préparé à la place de la personne de chaque compte, et ce que c'est devenu.")
def _replies(s: TeamsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = scoped(ctx.ports.get("teams"), ctx)
    if port is None:
        return [Note(NO_PORT, tone="muted")]
    navs = _navs(port, ctx, frame, "reponses")
    drafts = _shown_replies(s, port, ctx)
    if not port.accounts() and not drafts:
        return [*navs, _nothing_for(frame, ctx)]
    account = chosen_account(port, ctx)
    # les comptes réglés : une réponse d'un autre vient d'un compte retiré, que ``port.title`` ne nomme plus
    known = {a.key for a in (port.port if isinstance(port, Scope) else port).accounts()}
    page, pager = paginate(drafts, ctx.pager(size=PAGE))

    def row(d: DraftSeen) -> Row:
        got = port.draft(d.draft) if d.draft else None
        title = _clip(port.title(d.account, d.conversation), 60)
        where = Text(title or "—") if d.account in known else Text(RETIRED, "muted")
        # sa fiche, par son brouillon ; une proposition qui n'en nomme aucun n'a pas de fiche : qui attend encore se
        # décide dans la file « À valider »
        href = Ref.subject("reponse_teams", d.draft, title or d.draft) if d.draft else \
            Ref.approvals("À valider › Réponses Teams", "teams") if d.state == WAITING else None
        return Row((where, Text(_clip(got.body, 120) if got else "(disparue)"),
                    Badge("demandée" if d.asked else "d'elle-même", "info" if d.asked else ""), When(d.at),
                    _badge(d.state), Badge("retouchée", "warn") if d.edited else ""),
                   href=href, tone="warn" if d.state == WAITING else "")

    # comment ses réponses partent : le tableau de canal du compte choisi (« teams:<clé> »), sinon celui de Teams
    # (ADR 0134 : « Envoyer à ta place » est fondu dans les canaux) ; l'onglet dessiné le met en pied (ADR 0218)
    canal = Ref.settings(CANALS_PAGE, "le tableau de ce compte (Réglages › Canaux)", canal=f"teams:{account}") \
        if account else Ref.settings(CANALS_PAGE, "le tableau de Teams (Réglages › Canaux)", canal="teams")
    return [*navs,
            Table((Column("conversation", role="title"), Column("réponse", role="body"), Column("pourquoi", "fit"),
                   Column("proposée", "fit"), Column("état", "fit", role="badge"),
                   Column("retouche", "fit", role="badge")), tuple(row(d) for d in page),
                  title=f"Réponses ({len(drafts)})", pager=pager, empty="aucune réponse préparée", layout="cards",
                  link_label="Examiner la réponse"),
            Fields(((HOW_IT_GOES, canal),), title="Comment ça part",
                   hints=((HOW_IT_GOES, "Ce qu'elle prépare d'elle-même et comment ses réponses partent se règlent "
                                        "dans le tableau de chaque compte Teams."),))]


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
    navs = _navs(port, ctx, frame, "extension")
    if not port.accounts():
        return [*navs, _nothing_for(frame, ctx)]
    account = chosen_account(port, ctx)
    if not account:  # plusieurs comptes : un par ligne, chacun mène à son extension
        rows = tuple(Row((Text(a.name), Text(owner_name(frame, a.owner)),
                          Text("inactif" if not a.enabled else _key_words(ctx, a.key)),
                          When(a.last_batch) if a.last_batch else "jamais", Text(a.self_name or "pas encore vu")),
                         href=view_link("extension", a.name, (*kept(ctx, account=False), (ACCOUNT, a.key))),
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
        # son nom court (son identifiant dans les réglages) : « clé » ne dit que le secret de son extension
        ("nom court du compte", Text(account, "mono")),
        ("dernier envoi de l'extension", When(port.last_batch(account)) if plugged else "jamais"),
        ("son nom dans Teams", self_name or "pas encore vu"), ("son identifiant Teams", owner_id or "pas encore vu"),
        ("messages remarqués (en tête)", sum(1 for m in s.messages.values() if m.account == account)),
        ("sa clé", _key_words(ctx, account)),
        # sa voix et sa signature, réglées dans Teams › Paramètres : ce compte-là, qui ramène ici (ADR 0206)
        ("sa voix, sa signature", Ref.settings(SETTINGS, "Modifier ce compte", section=SECTION,
                                               enregistrement="accounts", cle=account).back_to(
                                                   view_link("extension", "", ((ACCOUNT, account),)))),
        # le tableau de canal de ce compte (ADR 0134 : « Envoyer à ta place » est fondu dans les canaux), comme une boîte
        ("ce qu'elle prépare, comment ça part", Ref.settings(CANALS_PAGE, "le tableau de ce compte (Réglages › Canaux)",
                                                             canal=f"teams:{account}")),
    ]
    blocks: list[Block] = [*navs, Fields(tuple(pairs), title="L'extension", columns=1),
                           Note("L'extension lit ce que Teams web reçoit dans le navigateur où ce "
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
               description="Les comptes Teams qui sont à cette personne : elle s'en sert avec elle seulement "
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
                         view_link("conversations", "Ses conversations", ((WHOSE, whose_value), (ACCOUNT, a.key)))),
                        href=view_link("extension", a.name, ((WHOSE, whose_value), (ACCOUNT, a.key))),
                        tone="" if plugged else "warn"))
    return [Table((Column("compte", role="title"), Column("état", "fit", role="badge"),
                   Column("dernier envoi de l'extension", "fit"), Column("lire", "fit")), tuple(rows),
                  title=f"Teams ({len(rows)})", empty="aucun compte Teams à son nom",
                  caption=f"Un compte Teams se donne à {'toi' if not owner else owner_name(frame, owner)} dans "
                          "Teams › Paramètres (« À qui »).")]


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
                back=view_link("conversations", "Retour aux conversations"))


@TEAMS.inspect("fil", title="Fil", subject="conversation_teams", order=10,
               description="Les derniers messages, du plus ancien au plus récent.")
def _thread(s: TeamsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = ctx.ports.get("teams")
    account, conversation = split_conversation_key(ctx.subject)
    if port is None or port.conversation(account, conversation) is None:
        return [Note("Cette conversation n'est plus là.", tone="muted")]
    thread = port.thread(account, conversation, 60)
    rows = tuple(Row((When(m.at), Text("toi" if m.own else _clip(m.author, 60)), Text(quote_said(m.quote) + m.text, clamp=600),
                      Badge("question", "warn") if (seen := s.messages.get(m.ref)) and seen.needs_reply else "")
                     ) for m in thread)
    blocks: list[Block] = [Table((Column("quand", "fit"), Column("qui", "fit", role="title"), Column("message", role="body"), Column("question", "fit", role="badge")), rows,
                                 title="Le fil", empty="aucun message", layout="feed")]
    received = [m for m in thread if not m.own]
    # écrire soi-même, sur tout compte (ADR 0231) : la note dit sous quel nom il part, la confirmation le redit ;
    # Teams coupé ou ce compte décoché, rien ne part (``_write`` le refuserait) : la fiche dit pourquoi
    off = not_sending(params_of(frame), account)
    if off:
        blocks.append(Note(off, tone="muted"))
    else:
        initial = (("conversation", ctx.subject),) + ((("reply_to", received[-1].ref),) if received else ())
        blocks.append(Disclosure(WRITE_TITLE, (sent_as(frame, port.account(account)),
                                               ActionSlot("teams.ecrire", initial))))
    if received and not under_way(s, account, conversation):
        last = received[-1]
        # le nom de l'action, comme au courrier (ADR 0175) : le formulaire prend son titre
        blocks.append(Disclosure(ASK_TITLE, (ActionSlot("teams.rediger", (("message", last.ref),)),)))
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
                back=view_link("reponses", "Retour aux réponses"))


@TEAMS.inspect("reponse", title="Réponse", subject="reponse_teams", order=10,
               description="Exactement ce qui part (ou est parti), et ce que tu peux en faire.")
def _reply(s: TeamsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = ctx.ports.get("teams")
    got = port.draft(ctx.subject) if port is not None else None
    if got is None:
        # disparue (son compte retiré des réglages) mais encore à décider : le refus ne lit que l'état (``_refuse``),
        # et la retire de ce qui attend ton accord (audit du 2026-11-05, C4-R3)
        gone = latest(s, ctx.subject)
        if gone is not None and gone.state == WAITING:
            return [Note("Cette réponse n'existe plus : elle ne partira pas. La refuser la retire de ce qui attend ton "
                         "accord.", tone="warn"),
                    Disclosure("La refuser", (ActionSlot("teams.refuser", (("draft", ctx.subject),), title="Refuser"),),
                               open=True)]
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
            note = ctx.store.content([seen.note_ref]).get(seen.note_ref, FORGOTTEN)
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


def not_preparing(p: TeamsParams, account: str) -> str:
    """Pourquoi elle ne prépare rien dans ce compte, ou vide : Teams coupé, ce compte décoché — ses tâches l'écartent
    (``tasks._prepare``). Le refus de l'action, que « Préremplir » de ``/api/moi`` rend tel quel ; un texte de console,
    gardé ici (audit du 2026-11-05, K10-03)."""
    if not p.enabled:
        return "Teams est désactivé : elle n'y prépare rien."
    if account in p.accounts_off:
        return "Ce compte Teams est décoché : elle n'y prépare rien."
    return ""


def not_sending(p: TeamsParams, account: str) -> str:
    """Pourquoi rien ne part de ce compte, ou vide : Teams coupé, ce compte décoché. Le refus d'« Écrire dans cette
    conversation » (``_write``) ; la fiche d'une conversation ne l'offre pas alors, et le dit."""
    if not p.enabled:
        return "Teams est désactivé : rien ne part."
    if account in p.accounts_off:
        return "Ce compte Teams est décoché : rien n'en part."
    return ""


def sent_as(frame: Frame, info: Any) -> Note:
    """Sous quel nom part ce qu'on écrit dans une conversation (ADR 0189, 0231) : celui de la personne connectée à Teams
    dans le navigateur de ce compte — toi pour un compte à toi ; sinon son propriétaire, nommé, que la note met en
    garde (le message part sous un autre nom que le tien). ``info`` : le compte (``AccountInfo``), ou ``None``."""
    if info is None:
        return Note("Il part sous le nom de la personne connectée à Teams dans le navigateur de ce compte.",
                    tone="warn")
    teams = f" (« {info.self_name} » dans Teams)" if info.self_name else ""
    if not info.owner:
        return Note(f"Il part sous ton nom{teams} : ce compte Teams est à toi.", tone="info")
    return Note(f"Il part sous le nom de {owner_name(frame, info.owner)}{teams}, à qui est ce compte Teams, pas sous "
                "le tien.", tone="warn")


def _prepares_here(frame: Frame, account: str) -> None:
    """Une demande de réponse ne se pose que là où elle prépare (``not_preparing``) : Teams coupé ou ce compte
    décoché, elle ne s'y mettrait jamais (ses tâches l'écartent) et la demande resterait « en cours » sans fin."""
    said = not_preparing(params_of(frame), account)
    if said:
        raise Refused(said)


@TEAMS.action("reprendre", title="Lui demander de la reprendre", args=RedoArgs, emits=[c.DRAFT_ASKED],
              description="Refuse celle-ci ; elle en écrira une autre, en tenant compte de ce que tu dis.")
def _redo(s: TeamsState, frame: Frame, args: RedoArgs, ctx: Any) -> Done:
    seen = _waiting(s, args.draft)
    if not seen.message:
        raise Refused("Ce n'est pas une réponse à un message : refuse-la.")
    _prepares_here(frame, seen.account)
    port = ctx.ports.get("teams")
    if port is not None:
        port.discard_draft(args.draft)
    asked = c.DRAFT_ASKED.draft(message=seen.message, conversation=seen.conversation, by=ctx.by,
                                instruction=Content.of(args.instruction.strip(), level=int(Sensitivity.PERSONAL)),
                                about=(ctx.by,) if ctx.by else (), account=seen.account)
    return Done(drafts=(asked,), decide=(Decision(seen.proposal, False, note=f"à reprendre : {args.instruction}"[:500]),),
                message="Demandé : elle la reprend tout de suite.",
                go=view_link("reponses"))


@TEAMS.action("rediger", title=ASK_TITLE, args=AskArgs, emits=[c.DRAFT_ASKED],
              subject="conversation_teams",
              description="Elle préparera une réponse au dernier message reçu, selon le mode réglé.")
def _ask(s: TeamsState, frame: Frame, args: AskArgs, ctx: Any) -> Done:
    port = ctx.ports.get("teams")
    m = port.message(args.message) if port is not None else None
    if m is None:
        raise Refused("Ce message n'est plus là.")
    _prepares_here(frame, m.account)
    if under_way(s, m.account, m.conversation) or asked_still(s, m.ref, params_of(frame)):
        raise Refused("Une réponse est déjà en chemin dans cette conversation.")
    instruction = args.instruction.strip()
    asked = c.DRAFT_ASKED.draft(message=m.ref, conversation=m.conversation, by=ctx.by,
                                instruction=Content.of(instruction, level=int(Sensitivity.PERSONAL)) if instruction
                                else None, about=(ctx.by,) if ctx.by else (), account=m.account)
    return Done(drafts=(asked,), message="Demandé : elle s'y met tout de suite.",
                go=view_link("reponses"))


class WriteArgs(BaseModel):
    #: la conversation (``<compte>~<identifiant>``) : posée par la page, jamais tapée
    conversation: Annotated[str, Knob(label="Conversation", widget="hidden")] = Field(min_length=3, max_length=400)
    body: Annotated[str, Knob(label="Message", widget="textarea", advanced=False)] = \
        Field(min_length=1, max_length=4000)
    #: le message auquel on répond, s'il y en a un
    reply_to: Annotated[str, Knob(label="En réponse à", widget="hidden")] = Field(default="", max_length=400)


# ton geste est l'envoi (ADR 0189), sous le nom de la personne de ce compte — la tienne, ou celle de son
# propriétaire quand un opérateur écrit depuis la console dans le compte d'un autre (ADR 0231) : la note de la fiche
# le dit par son nom (``sent_as``), la confirmation le redit ; ses réponses en attente n'ont plus lieu (ADR 0199)
@TEAMS.action("ecrire", title=WRITE_TITLE, args=WriteArgs, emits=[WRITTEN],
              description="Ton message part tout de suite par l'extension de ce compte, sous le nom de la personne de "
                          "ce compte, sans sa signature : ton geste est l'envoi. Elle le verra parti, comme les autres "
                          "messages ; ses réponses qui attendaient un accord ici ne partiront plus.",
              confirm="L'envoyer dans Teams maintenant, sous le nom de la personne de ce compte, sans sa signature ?")
def _write(s: TeamsState, frame: Frame, args: WriteArgs, ctx: Any) -> Done:
    """Ce que la personne écrit elle-même : un brouillon à son nom (``author``), aussitôt en file pour être envoyé —
    son geste est l'envoi, aucun accord n'est à demander. L'extension le relève, l'envoie et l'accuse ; ses messages
    à elle reviennent ensuite dans le fil (``own``), comme ce qu'elle tape dans Teams. Le journal le sait aussitôt
    (``teams.written``, sans texte) : ses réponses qui attendaient un accord dans cette conversation n'ont plus lieu
    d'être (ADR 0199) — refusées par ``teams.answered``, jamais par ce geste, qui ne peut donc pas échouer à cause
    d'elles une fois le message en file. Le même geste sert l'espace de la personne (``app/me/teams.py``, après sa
    garde du niveau « s'en servir ») et la console, où un opérateur écrit aussi dans le compte d'une autre personne
    (ADR 0231) : le message part sous le nom de celle-ci, le brouillon garde qui l'a écrit, l'audit aussi."""
    port = ctx.ports.get("teams")
    if port is None:
        raise Refused(NO_PORT)
    p = params_of(frame)
    account, conversation = split_conversation_key(args.conversation)
    off = not_sending(p, account)
    if off:
        raise Refused(off)
    if port.conversation(account, conversation) is None:
        raise Refused("Cette conversation n'est plus là.")
    body = args.body.strip()
    if to_fill(body):
        raise Refused("Il reste des passages [À COMPLÉTER] à remplir.", {"body": "un passage à compléter"})
    draft = port.save_draft(TeamsDraft(id="", conversation=conversation, body=body, reply_to=args.reply_to,
                                       author=ctx.by, account=account))
    why = port.enqueue(draft.id, mode=OUTBOX_SEND, digest="", expires_at=frame.now + p.queue_ttl_us, now=frame.now)
    if why:
        port.discard_draft(draft.id)
        raise Refused(f"Il n'a pas pu partir : {why}.")
    return Done(drafts=(WRITTEN.draft(conversation=conversation, account=account),),
                message="En file : l'extension de ce compte l'enverra dans Teams.")


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
    if not await _keys(ctx).revoke_key(args.compte):
        raise Refused("Ce compte n'avait pas de clé.")
    return Done(message=f"La clé du compte « {args.compte} » est retirée : son extension est refusée jusqu'à une clé "
                        "neuve.", tone="warn")
