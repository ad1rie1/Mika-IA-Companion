"""La console des serveurs MCP (ADR 0064) : dans « Ses outils », la liste des serveurs branchés, puis la fiche de
chacun — son état, ce qu'il propose, ce que l'opérateur en a approuvé, ses appels.

Les connexions (adresse, jeton, commande, pour qui, quand) se règlent dans Configuration › Plugins › Outils
extérieurs ; un lien y mène et l'enregistrement ramène ici. Ce qui se décide ici, outil par outil : l'activer, sa
nature, l'accord qu'il demande, la description qu'elle lit. Ce que le serveur dit de lui-même et de ses outils est
une donnée venue d'ailleurs : montrée à l'opérateur, jamais obéie.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    ActionSlot,
    Badge,
    Block,
    Code,
    Column,
    Fields,
    Found,
    Head,
    InspectContext,
    Note,
    Prose,
    Ref,
    Row,
    Table,
    Text,
    Vital,
    When,
)
from mika.kernel.operate import Done, Refused
from mika.plugins.mcp import MCP, STATUS, McpState, status_drafts
from mika.ports.mcp import APPROVALS, AUDIENCES, EPISODES, NATURES, STATES

SETTINGS = "/inspecteur/reglages/serveurs-mcp"
LIST = "/inspecteur/outils/serveurs"
NO_PORT = "Les outils extérieurs ne sont pas branchés sur ce serveur."
STATE_TONES = {"inactif": "muted", "incomplet": "warn", "jamais": "muted", "connecte": "ok", "erreur": "warn",
               "panne": "danger"}
WORDS = {"lecture": "lecture", "action": "action", "aucun": "sans accord", "conversation": "accord dans la conversation",
         "operateur": "accord de l'opérateur"}


def _fiche(name: str, tab: str = "") -> Ref:
    return Ref.subject("serveur", name, name, tab)


def _fiche_url(name: str) -> str:
    return f"/inspecteur/fiche/serveur/{name}"


def edit_server(name: str, back: str = LIST) -> Ref:
    return Ref("local", SETTINGS, "Modifier ses réglages",
               (("section", "mcp"), ("enregistrement", "servers"), ("cle", name), ("retour", back)))


def add_server(back: str = LIST) -> Ref:
    return Ref("local", SETTINGS, "Brancher un serveur",
               (("section", "mcp"), ("enregistrement", "servers"), ("cle", ""), ("nouveau", "1"), ("retour", back)))


def state_badge(state: str) -> Badge:
    return Badge(STATES.get(state, state), STATE_TONES.get(state, ""))


def _words(choices: tuple[tuple[str, str], ...], value: str) -> str:
    return next((label.split(" — ")[0] for key, label in choices if key == value), value)


def _attention(s: McpState, frame: Frame | None = None) -> tuple[int, str] | None:
    """Ce qui attend l'opérateur : des outils à regarder, un serveur en panne."""
    review = sum(x.review for x in s.servers)
    broken = sum(1 for x in s.servers if x.state == "panne")
    if not review and not broken:
        return None
    return review + broken, "danger" if broken else "warn"


@MCP.inspect("serveurs", title="Serveurs extérieurs", section="outils", order=40, badge=_attention,
             description="Les serveurs MCP dont elle peut utiliser les outils : leur état, ce qu'ils proposent, ce "
                         "qui attend ton regard. Les connexions se règlent dans Configuration.")
def _servers(s: McpState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = ctx.ports.get("mcp")
    if port is None:
        return [Note(NO_PORT, tone="muted")]
    offered: dict[str, int] = {}
    for t in port.offered():
        offered[t.server] = offered.get(t.server, 0) + 1
    rows = []
    for st in port.statuses():
        review = len(st.new) + len(st.changed)
        rows.append(Row((_fiche(st.name), Badge("sur cette machine" if st.kind == "local" else "à une adresse", "info"),
                         Text(st.purpose or "—", clamp=160), state_badge(st.state),
                         Text(f"{offered.get(st.name, 0)} / {len(st.live)}", "num"),
                         Badge(str(review), "warn") if review else Text("0", "muted"),
                         When(st.last_ok_at) if st.last_ok_at else "jamais"),
                        href=_fiche(st.name), tone="danger" if st.state == "panne" else "",
                        detail=((Note(st.detail, tone="warn"),) if st.detail else ())
                        + (Fields((("réglages", edit_server(st.name)), ("adresse", Text(st.address or "—", "mono")))),)))
    return [Fields((("nouveau serveur", add_server()),
                    ("tous les réglages", Ref("local", SETTINGS, "Configuration › Plugins › Outils extérieurs")))),
            Table(("serveur", Column("où", "fit"), "à quoi il sert, pour elle", Column("état", "fit"),
                   Column("servis / proposés", "num"), Column("à revoir", "num"), Column("joint", "fit")),
                  tuple(rows), title="Serveurs", empty="Aucun serveur branché : « Brancher un serveur ».",
                  caption="Un outil n'est servi qu'une fois approuvé sur la fiche de son serveur ; un outil que le "
                          "serveur change est suspendu jusqu'à ton nouvel accord.")]


@MCP.subject("serveur", label="Serveur extérieur", plural="Serveurs extérieurs", icon="⇄")
def _head(s: McpState, frame: Frame, ctx: InspectContext, key: str) -> Head | None:
    port = ctx.ports.get("mcp")
    st = port.status(key) if port is not None else None
    if st is None:
        return None
    badges = [state_badge(st.state), Badge("sur cette machine" if st.kind == "local" else "à une adresse", "info"),
              Badge(_words(AUDIENCES, st.audience), "info")]
    review = len(st.new) + len(st.changed)
    if review:
        badges.append(Badge(f"{review} outil(s) à revoir", "warn"))
    return Head(key=key, title=key, subtitle=st.purpose, badges=tuple(badges),
                facts=(("réglages", edit_server(key, _fiche_url(key))),
                       ("joint", ctx.when(st.last_ok_at) if st.last_ok_at else "jamais")),
                back=Ref("local", LIST, "Serveurs extérieurs"))


@MCP.search("serveur")
def _search(s: McpState, frame: Frame, ctx: InspectContext, text: str, limit: int) -> list[Found]:
    port = ctx.ports.get("mcp")
    query = text.casefold().strip()
    return [Found(st.name, st.name, st.purpose[:120]) for st in (port.statuses() if port is not None else ())
            if not query or query in f"{st.name} {st.purpose}".casefold()][:limit]


@MCP.inspect("etat", title="État", subject="serveur", order=10,
             description="Ce qui a été déclaré, si le serveur répond, et ce qu'il dit de lui-même.")
def _tab_state(s: McpState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = ctx.ports.get("mcp")
    st = port.status(ctx.subject) if port is not None else None
    if st is None:
        return [Note("Ce serveur n'existe plus.", tone="muted")]
    blocks: list[Block] = []
    if st.detail:
        blocks.append(Note(st.detail, tone="danger" if st.state == "panne" else "warn",
                           title=STATES.get(st.state, st.state)))
    if st.state == "panne":
        blocks.append(Note("Ses outils ne lui sont plus offerts. « Tester la connexion » le relance s'il répond.",
                           tone="danger"))
    episodes = ", ".join(_words(EPISODES, e) for e in st.episodes) or "jamais"
    blocks.append(Fields((
        ("à quoi il sert, pour elle", st.purpose or "—"),
        ("quand s'en servir", st.when_to_use or "—"),
        ("où", Text(st.address or "—", "mono")),
        ("pour qui", f"{_words(AUDIENCES, st.audience)} — jamais dans un salon"),
        ("quand", episodes),
        ("ses outils", "en main" if st.in_hand else "à la demande (elle les cherche par ce qu'ils font)"),
        ("réglages", edit_server(st.name, _fiche_url(st.name))),
    ), title="Ce que tu as déclaré", columns=2))
    blocks.append(Fields((
        ("serveur", f"{st.server_name} {st.server_version}".strip() or "—"),
        ("protocole", st.protocol or "—"),
        ("joint", ctx.when(st.last_ok_at) if st.last_ok_at else "jamais"),
        ("dernière panne", ctx.when(st.last_error_at) if st.last_error_at else "aucune"),
        ("appels", f"{st.calls} ({st.failures} en échec)"),
        ("pannes d'affilée", str(st.consecutive)),
    ), title="Ce qu'il répond", columns=2))
    if st.log:
        blocks.append(Code("\n".join(st.log), title="La fin de sa sortie d'erreur, quand il est tombé (secrets masqués)"))
    if st.instructions:
        blocks.append(Prose(st.instructions, title="Ce que le serveur dit de lui-même (elle ne le lit jamais)",
                            clamp=600))
    blocks.append(ActionSlot("mcp.tester", title="Tester la connexion"))
    return blocks


def _tool_state(st: Any, remote: str) -> tuple[str, str]:
    live = {t.remote: t for t in st.live}
    review = st.reviews.get(remote)
    tool = live.get(remote)
    if tool is None:
        return ("disparu", "muted") if review is None or not review.enabled else ("approuvé, disparu", "warn")
    if review is None:
        return "à regarder", "warn"
    if not review.enabled:
        return "désactivé", "muted"
    if review.fingerprint != tool.fingerprint:
        return "changé : suspendu", "danger"
    return "servi" if review.approval == "aucun" else f"servi, {WORDS.get(review.approval, review.approval)}", "ok"


def _schema_rows(schema: Any) -> tuple[tuple[Any, ...], ...]:
    props = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(props, dict):
        return ()
    required = set(schema.get("required") or ())
    return tuple((Text(str(k), "mono"), str(v.get("type", "—")) if isinstance(v, dict) else "—",
                  "oui" if k in required else "non",
                  Text(str(v.get("description", "")) if isinstance(v, dict) else "", clamp=200))
                 for k, v in props.items())


@MCP.inspect("outils", title="Ses outils", subject="serveur", order=20,
             description="Ce que le serveur propose maintenant, et ce que tu en as décidé : activé ou non, sa nature, "
                         "l'accord qu'il demande, la description qu'elle lit.")
def _tab_tools(s: McpState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = ctx.ports.get("mcp")
    st = port.status(ctx.subject) if port is not None else None
    if st is None:
        return [Note("Ce serveur n'existe plus.", tone="muted")]
    names = {t.remote: t.name for t in port.offered() if t.server == st.name}
    blocks: list[Block] = []
    if not st.live:
        blocks.append(Note("La liste de ses outils n'est pas connue : « Tester la connexion » la charge.",
                           tone="muted"))
    if st.changed:
        blocks.append(Note("Le serveur a changé la description, le schéma ou les annotations de "
                           f"{', '.join(st.changed)} depuis ton accord : suspendu(s) jusqu'à ce que tu les relises.",
                           tone="danger"))
    rows = []
    remotes = [t.remote for t in st.live] + [r for r in st.reviews if r not in {t.remote for t in st.live}]
    live = {t.remote: t for t in st.live}
    for remote in remotes:
        tool, review = live.get(remote), st.reviews.get(remote)
        word, tone = _tool_state(st, remote)
        current = review.description if review is not None else ""
        said = tool.description if tool is not None else (review.server_description if review else "")
        detail: list[Any] = [
            Fields((("son nom chez elle", Text(names.get(remote, "— (pas servi)"), "mono")),
                    ("ce que dit le serveur", Text(said or "—")),
                    ("ce qu'elle lit", Text(current or "(la description du serveur)")),
                    ("lecture seule selon lui", "oui" if tool is not None and tool.read_only_hint else "non dit"),
                    ("décidé", f"par {review.by}" if review is not None and review.by else "—")), columns=1),
        ]
        rows_schema = _schema_rows(tool.schema if tool is not None else (review.schema if review else {}))
        if rows_schema:
            detail.append(Table(("argument", Column("type", "fit"), Column("requis", "fit"), "ce que c'est"),
                                rows_schema, title="Ses arguments"))
        if tool is not None:
            detail.append(ActionSlot("mcp.regler", (
                ("outil", remote), ("actif", "1" if review is None or review.enabled else ""),
                ("nature", review.nature if review is not None else ("lecture" if tool.read_only_hint else "action")),
                ("accord", review.approval if review is not None else "conversation"),
                ("description", current)), title="Régler cet outil", compact=True))
        rows.append(Row((Text(remote, "mono"), Text(said or "—", clamp=140), Badge(word, tone),
                         _words(NATURES, review.nature) if review else "—",
                         WORDS.get(review.approval, review.approval) if review else "—"),
                        tone="danger" if tone == "danger" else "", detail=tuple(detail)))
    blocks.append(Table(("outil", "ce qu'il dit faire", Column("état", "fit"), Column("nature", "fit"),
                         Column("accord", "fit")), tuple(rows), title=f"Ce qu'il propose ({len(st.live)})",
                        empty="Rien pour l'instant.",
                        caption="Approuver un outil, c'est approuver ce qu'il dit être maintenant : s'il change, il est "
                                "suspendu. Ce que dit le serveur est une donnée : relis-le avant de l'activer."))
    return blocks


@MCP.inspect("appels", title="Appels", subject="serveur", order=30,
             description="Les derniers appels de ses outils (14 jours), vers l'épisode où les relire.")
def _tab_calls(s: McpState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port, traces = ctx.ports.get("mcp"), ctx.ports.get("traces")
    if port is None or traces is None:
        return [Note(NO_PORT, tone="muted")]
    rows = []
    for t in (x for x in port.offered() if x.server == ctx.subject):
        for u in traces.tool_uses(t.name, 20):
            rows.append((u.at, Row((When(u.at), Text(t.remote, "mono"),
                                    Badge("réussi" if u.ok else "refusé" if not u.executed else "échec",
                                          "ok" if u.ok else "warn" if not u.executed else "danger"),
                                    Ref("episode", u.correlation, "relire", (("onglet", "outils"),))))))
    rows.sort(key=lambda r: -r[0])
    return [Table((Column("quand", "fit"), Column("outil", "fit"), Column("issue", "fit"), ""),
                  tuple(r for _, r in rows[:50]), title="Derniers appels",
                  empty="Aucun appel de ses outils servis depuis 14 jours.")]


# ── Actions ───────────────────────────────────────────────────────────────


class NoArgs(BaseModel):
    pass


class ReviewArgs(BaseModel):
    outil: Annotated[str, Knob(label="Outil", widget="hidden")] = Field(min_length=1, max_length=128)
    actif: Annotated[bool, Knob(label="Activé", advanced=False,
                                help="Coché : elle peut s'en servir, tel que le serveur le décrit maintenant.")] = False
    nature: Annotated[Literal["lecture", "action"], Knob(label="Nature", choices=NATURES, advanced=False)] = "lecture"
    accord: Annotated[Literal["aucun", "conversation", "operateur"], Knob(
        label="Accord", choices=APPROVALS, advanced=False,
        help="Sans accord, l'appel part aussitôt et ses arguments sortent de la machine.")] = "conversation"
    description: Annotated[str, Knob(
        label="Ce qu'elle lit", widget="textarea", advanced=False,
        help="Vide : la description du serveur. Une phrase à toi si la sienne est floue ou trop longue.")] = \
        Field("", max_length=1024)


def _port(ctx: Any) -> Any:
    port = ctx.ports.get("mcp")
    if port is None:
        raise Refused(NO_PORT)
    if port.status(ctx.subject) is None:
        raise Refused("Serveur inconnu.")
    return port


@MCP.action("tester", title="Tester la connexion", args=NoArgs, emits=[STATUS], subject="serveur", order=10,
            description="Rouvre une session et relit la liste de ses outils (rien n'est approuvé par là).")
async def _test(s: McpState, frame: Frame, args: NoArgs, ctx: Any) -> Done:
    port = _port(ctx)
    ok, said = await port.test(ctx.subject)
    return Done(message=said, tone="ok" if ok else "danger", drafts=status_drafts(s, port))


@MCP.action("regler", title="Régler l'outil", args=ReviewArgs, emits=[STATUS], subject="serveur", order=20,
            inline=True, description="L'activer ou non, sa nature, l'accord qu'il demande, ce qu'elle lit.")
async def _review(s: McpState, frame: Frame, args: ReviewArgs, ctx: Any) -> Done:
    port = _port(ctx)
    try:
        await port.review(ctx.subject, args.outil, enabled=args.actif, nature=args.nature, approval=args.accord,
                          description=args.description, by=ctx.by)
    except ValueError as exc:
        raise Refused(str(exc)) from None
    word = "activé" if args.actif else "désactivé"
    return Done(message=f"{args.outil} : {word}, {WORDS.get(args.accord, args.accord)}.",
                drafts=status_drafts(s, port))


@MCP.vital("outils", label="Outils extérieurs", order=80)
def _vital(s: McpState, frame: Frame) -> Vital | None:
    got = _attention(s)
    if got is None:
        return None
    n, tone = got
    broken = [x.name for x in s.servers if x.state == "panne"]
    text = f"{len(broken)} en panne" if broken else f"{n} à revoir"
    return Vital(text, tone, hint=", ".join(broken) or "des outils attendent ton regard",
                 href=Ref("local", LIST, "Serveurs extérieurs"))
