"""La console des serveurs MCP (ADR 0064) : dans « Outils › Venus d'ailleurs », la liste des serveurs branchés, puis la fiche de
chacun — son état, ce qu'il propose, ce que l'opérateur en a approuvé, ses appels.

Les connexions (adresse, jeton, commande) se règlent dans Réglages › Plugins › Outils extérieurs ; un lien y mène et
l'enregistrement ramène ici. Ce qui se décide ici (ADR 0128) : ce que le service fait d'elle (avec qui, quand, ce
qu'elle fait seule, ce qu'elle en garde — d'un coup par un genre) ; outil par outil, l'activer, sa nature, son accord à
lui, la description qu'elle lit, et ses règles par situation et par personne. Ce que le serveur dit de lui-même et de
ses outils est une donnée venue d'ailleurs : montrée à l'opérateur, jamais obéie.
"""

from __future__ import annotations

import shlex
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, create_model

from mika.contracts import identity as identity_c
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
from mika.ports.mcp import (
    AUTONOMIES,
    EPISODES,
    KEEPS,
    NATURES,
    RULE_LEVELS,
    STATES,
    TOOL_AUTONOMIES,
    TOOL_SITUATIONS,
)

SETTINGS = "/inspecteur/reglages/serveurs-mcp"
LIST = "/inspecteur/outils/serveurs"
NO_PORT = "Les outils extérieurs ne sont pas branchés sur ce serveur."
FAILED_SEE_FICHE = "Le test a échoué : l'erreur est sur sa fiche."
STATE_TONES = {"inactif": "muted", "incomplet": "warn", "jamais": "muted", "connecte": "ok", "erreur": "warn",
               "panne": "danger"}
WORDS = {"lecture": "lecture", "action": "action", "service": "comme le service", "seule": "seule",
         "lit": "lit seule, demande pour agir", "carte": "demande à chaque appel", "toi": "te demande à chaque appel",
         "non": "non"}
#: les genres de service (ADR 0128) : les trois réglages d'un coup. Le genre ne se garde pas : il se lit dans les
#: réglages (``genre_of``), et « sur mesure » quand aucun ne leur va
GENRES = (
    ("pro", "Mon travail, sous contrôle", "facturation, devis, tickets",
     {"with_owner": True, "with_accounts": False, "with_people": (), "autonomy": "toi", "keep": "rien",
      "in_conversation": True, "in_work": True}),
    ("avec", "Mon travail, avec elle", "ta boutique, ton site, tes projets",
     {"with_owner": True, "with_accounts": False, "with_people": (), "autonomy": "lit", "keep": "prive",
      "in_conversation": True, "in_work": True}),
    ("prive", "À moi, privé", "ton agenda, tes notes, ta santé",
     {"with_owner": True, "with_accounts": False, "with_people": (), "autonomy": "seule", "keep": "prive",
      "in_conversation": True, "in_work": False}),
    ("public", "Pour tout le monde", "météo, recettes, horaires",
     {"with_owner": True, "with_accounts": True, "with_people": (), "autonomy": "seule", "keep": "public",
      "in_conversation": True, "in_work": False}),
    ("autre", "À quelqu'un d'autre", "le serveur d'un ami, branché pour lui",
     {"with_owner": False, "with_accounts": False, "autonomy": "carte", "keep": "prive", "in_conversation": True,
      "in_work": False}),
)
#: au plus tant de personnes nommées, pour un service comme pour les règles d'un outil (un formulaire sans script)
PEOPLE_SLOTS = 8
ALONE_SAID = {"seule": "Elle s'en sert sans demander.", "lit": "Elle lit seule et demande avant d'agir.",
              "carte": "Elle demande avant chaque appel.", "toi": "Elle te demande avant chaque appel."}
KEEP_SAID = {"public": "Ce qu'elle y lit peut devenir ce qu'elle sait.",
             "perso": "Elle s'en souvient comme de ce qu'on lui dit.",
             "prive": "Ce qu'elle y lit reste une confidence de la personne pour qui elle l'a lu.",
             "rien": "Elle n'en garde rien."}


def name_of(frame: Frame | None, person: str) -> str:
    """Le nom d'une personne nommée (repli : sa clé)."""
    view = frame.get(identity_c.IDENTITY(person)) if frame is not None and person else None
    return str(getattr(view, "name", "") or person)


def genre_of(st: Any) -> tuple[str, str]:
    """Le genre que ses réglages dessinent (clé, nom), ou (« », « sur mesure »)."""
    for key, label, _, preset in GENRES:
        same = all(getattr(st, k) == v for k, v in preset.items() if k not in ("in_conversation", "in_work"))
        if same and (key != "autre" or st.with_people):
            return key, label
    return "", "sur mesure"


def who_said(st: Any, frame: Frame | None = None) -> str:
    """Avec qui, en quelques mots."""
    names = [name_of(frame, p) for p in st.with_people]
    parts = (["toi"] if st.with_owner else []) + (["les comptes"] if st.with_accounts else []) + names
    if not parts:
        return "personne"
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " et " + parts[-1]


def sentence(st: Any, frame: Frame | None = None) -> str:
    """Ce que le service fait d'elle, en une phrase (ADR 0128)."""
    names = " et ".join(name_of(frame, p) for p in st.with_people)
    if st.with_accounts:
        who = "Avec toi et toute personne qui a un compte, en tête-à-tête" if st.with_owner else \
            "Avec toute personne qui a un compte, en tête-à-tête, mais pas toi"
    elif st.with_owner:
        who = f"Avec toi et {names}" if names else "Avec toi seulement"
    else:
        who = f"Avec {names} seulement, pas toi" if names else "Avec personne"
    when = [w for e, w in (("conversation", "quand elle répond"), ("initiative", "quand elle prend la parole"),
                           ("travail", "quand elle travaille pour toi")) if e in st.episodes
            and (e != "travail" or st.with_owner)]
    said = ", " + " ou ".join(when) if when else ", mais à aucun moment : il ne sert jamais"
    return f"{who}{said}. {ALONE_SAID.get(st.autonomy, '')} {KEEP_SAID.get(st.keep, '')}".strip()


def _fiche(name: str, tab: str = "") -> Ref:
    return Ref.subject("serveur", name, name, tab)


def _fiche_url(name: str) -> str:
    return f"/inspecteur/fiche/serveur/{name}"


def edit_server(name: str, back: str = LIST) -> Ref:
    return Ref("local", SETTINGS, "Modifier ses réglages",
               (("section", "mcp"), ("enregistrement", "servers"), ("cle", name), ("retour", back)))


def add_server(back: str = LIST) -> Ref:
    """Brancher un service : la page dessinée en trois questions (ADR 0128), dans « Venus d'ailleurs »."""
    return Ref("local", LIST, "Brancher un service", (("brancher", "1"),))


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


@MCP.inspect("serveurs", title="Venus d'ailleurs", section="outils", order=40, badge=_attention,
             description="Les outils qui ne viennent pas d'elle : ceux des services que tu branches (des serveurs "
                         "MCP), puis ceux que ses apps lui donnent.")
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
                         When(st.last_ok_at) if st.last_ok_at else "jamais", Badge(genre_of(st)[1], "info"),
                         who_said(st, frame), WORDS.get(st.autonomy, st.autonomy), _words(KEEPS, st.keep)),
                        href=_fiche(st.name), tone="danger" if st.state == "panne" else "",
                        detail=((Note(st.detail, tone="warn"),) if st.detail else ())
                        + (Fields((("réglages", edit_server(st.name)), ("adresse", Text(st.address or "—", "mono")))),)))
    # brancher un service : trois questions, que la console dessinée met en page (ADR 0128)
    plug = [ActionSlot("mcp.brancher", title="Brancher")] if ctx.params.get("brancher") else []
    # deux liens seuls : la console dessinée en fait des boutons (``app/handmade/tools.py::Elsewhere``)
    return [*plug, Fields((("un nouveau service", add_server()),
                           ("leurs réglages", Ref("local", SETTINGS, "Leurs réglages")))),
            Table(("service", Column("où", "fit"), "à quoi il lui sert", Column("état", "fit"),
                   Column("outils servis / proposés", "num"), Column("à revoir", "num"), Column("joint", "fit"),
                   Column("genre", "fit"), "avec qui", "seule", "garde"),
                  tuple(rows), title="Les services branchés", empty="Aucun service branché : « Brancher un service ».",
                  caption="Un outil n'est servi qu'une fois approuvé sur la fiche de son service ; un outil que le "
                          "service change est suspendu jusqu'à ton nouvel accord.")]


@MCP.subject("serveur", label="Serveur extérieur", plural="Serveurs extérieurs", icon="⇄")
def _head(s: McpState, frame: Frame, ctx: InspectContext, key: str) -> Head | None:
    port = ctx.ports.get("mcp")
    st = port.status(key) if port is not None else None
    if st is None:
        return None
    badges = [state_badge(st.state), Badge("sur cette machine" if st.kind == "local" else "à une adresse", "info"),
              Badge(f"avec {who_said(st, frame)}", "info"), Badge(genre_of(st)[1], "info")]
    review = len(st.new) + len(st.changed)
    if review:
        badges.append(Badge(f"{review} outil(s) à revoir", "warn"))
    return Head(key=key, title=key, subtitle=st.purpose[:1].upper() + st.purpose[1:], badges=tuple(badges),
                facts=(("réglages", edit_server(key, _fiche_url(key))),),
                back=Ref("local", LIST, "Venus d'ailleurs"))


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
        ("avec qui", f"{who_said(st, frame)} — jamais dans un salon ni avec une inconnue"),
        ("quand", episodes),
        ("ce qu'elle fait seule", _words(AUTONOMIES, st.autonomy)),
        ("ce qu'elle en garde", _words(KEEPS, st.keep)),
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


def tool_state(st: Any, remote: str) -> tuple[str, str]:
    """Où en est un outil d'un serveur : ce que l'opérateur en a décidé, et s'il a changé depuis (son mot, son ton)."""
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
    if review.autonomy == "service":
        return "servi", "ok"
    return f"servi, {WORDS.get(review.autonomy, review.autonomy)}", "ok"


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
                         "son accord, la description qu'elle lit, ses règles par situation et par personne.")
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
    if st.new:
        blocks.append(ActionSlot("mcp.servir", title=f"Servir les {len(st.new)} nouveaux avec les réglages du service"))
    if st.changed:
        blocks.append(Note("Le serveur a changé la description, le schéma ou les annotations de "
                           f"{', '.join(st.changed)} depuis ton accord : suspendu(s) jusqu'à ce que tu les relises.",
                           tone="danger"))
    rows = []
    remotes = [t.remote for t in st.live] + [r for r in st.reviews if r not in {t.remote for t in st.live}]
    live = {t.remote: t for t in st.live}
    for remote in remotes:
        tool, review = live.get(remote), st.reviews.get(remote)
        word, tone = tool_state(st, remote)
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
                ("seule", review.autonomy if review is not None else "service"),
                ("description", current)), title="Régler cet outil", compact=True))
        if review is not None:
            detail.append(rules_ref(st.name, remote))
        rules = len(review.situations) + len(review.people) if review is not None else 0
        rows.append(Row((Text(remote, "mono"), Text(said or "—", clamp=140), Badge(word, tone),
                         _words(NATURES, review.nature) if review else "—",
                         WORDS.get(review.autonomy, review.autonomy) if review else "—",
                         f"{rules} règle{'s' if rules > 1 else ''}" if rules else "—"),
                        tone="danger" if tone == "danger" else "", detail=tuple(detail)))
    blocks.append(Table(("outil", "ce qu'il dit faire", Column("état", "fit"), Column("nature", "fit"),
                         Column("seule", "fit"), Column("règles", "fit")), tuple(rows),
                        title=f"Ce qu'il propose ({len(st.live)})",
                        empty="Rien pour l'instant.",
                        caption="Approuver un outil, c'est approuver ce qu'il dit être maintenant : s'il change, il est "
                                "suspendu. Ce que dit le serveur est une donnée : relis-le avant de l'activer."))
    return blocks


def rules_ref(server: str, remote: str) -> Ref:
    """La page d'un outil : ses règles par situation et par personne (ADR 0128)."""
    return Ref("local", _fiche_url(server), "Par situation et par personne",
               (("onglet", "regles"), ("outil", remote)))


def service_initial(st: Any) -> tuple[tuple[str, str], ...]:
    """Ce que le formulaire « Ce qu'elle en fait » montre d'abord : les réglages du service."""
    slots = [(f"qui{i + 1}", p) for i, p in enumerate(st.with_people[:PEOPLE_SLOTS])]
    return (("avec_toi", "1" if st.with_owner else ""), ("avec_les_comptes", "1" if st.with_accounts else ""), *slots,
            ("repond", "1" if "conversation" in st.episodes else ""),
            ("parle", "1" if "initiative" in st.episodes else ""),
            ("travaille", "1" if "travail" in st.episodes else ""), ("seule", st.autonomy), ("garde", st.keep))


def rules_initial(remote: str, review: Any) -> tuple[tuple[str, str], ...]:
    """Ce que le formulaire des règles d'un outil montre d'abord : ses règles, une personne par emplacement."""
    named = list(review.people.items())[:PEOPLE_SLOTS] if review is not None else []
    rules = review.situations if review is not None else {}
    return (("outil", remote), *((f"s_{k}", rules.get(k, AS_SERVICE)) for k, _ in TOOL_SITUATIONS),
            *(pair for i, (who, level) in enumerate(named) for pair in ((f"p{i + 1}", who), (f"r{i + 1}", level))))


@MCP.inspect("fait", title="Ce qu'elle en fait", subject="serveur", order=15,
             description="Avec qui, quand, ce qu'elle fait seule et ce qu'elle en garde — d'un coup par un genre.")
def _tab_service(s: McpState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = ctx.ports.get("mcp")
    st = port.status(ctx.subject) if port is not None else None
    if st is None:
        return [Note("Ce serveur n'existe plus.", tone="muted")]
    return [
        Prose(sentence(st, frame), title="En une phrase"),
        Fields((("genre", genre_of(st)[1]), ("avec qui", who_said(st, frame)),
                ("ce qu'elle fait seule", _words(AUTONOMIES, st.autonomy)),
                ("ce qu'elle en garde", _words(KEEPS, st.keep))), columns=2),
        ActionSlot("mcp.genre", (("genre", genre_of(st)[0] or "pro"),), title="Choisir un genre"),
        ActionSlot("mcp.service", service_initial(st), title="Enregistrer"),
    ]


@MCP.inspect("regles", title="Par situation et par personne", subject="serveur", order=25,
             description="Un outil : avec qui il sert et l'accord qu'il demande, par situation et pour des personnes "
                         "nommées — dans ce que son service permet.")
def _tab_rules(s: McpState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = ctx.ports.get("mcp")
    st = port.status(ctx.subject) if port is not None else None
    if st is None:
        return [Note("Ce serveur n'existe plus.", tone="muted")]
    remote = str(ctx.params.get("outil", "") or "")
    if remote not in st.reviews:
        rows = tuple(Row((rules_ref(st.name, r), Text(v.description or v.server_description or "—", clamp=140),
                          WORDS.get(v.autonomy, v.autonomy)))
                     for r, v in st.reviews.items() if v.enabled)
        return [Table(("outil", "ce qu'il fait", Column("seule", "fit")), rows, title="Choisis un outil",
                      empty="Aucun outil servi : approuve-les d'abord dans « Ses outils ».")]
    review = st.reviews[remote]
    return [ActionSlot("mcp.regles", rules_initial(remote, review), title="Enregistrer")]


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
    seule: Annotated[Literal["service", "seule", "carte", "toi"], Knob(
        label="Ce qu'il fait seul", choices=TOOL_AUTONOMIES, advanced=False,
        help="Seul, l'appel part aussitôt et ses arguments sortent de la machine. Une règle par situation ou par "
             "personne passe avant (onglet « Par situation et par personne »).")] = "service"
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
    st = port.status(ctx.subject)
    if not ok and st is not None and st.detail:
        said = FAILED_SEE_FICHE  # sa fiche, où l'on revient, montre déjà l'erreur : le bandeau ne la recopie pas
    return Done(message=said, tone="ok" if ok else "danger", drafts=status_drafts(s, port))


@MCP.action("regler", title="Régler l'outil", args=ReviewArgs, emits=[STATUS], subject="serveur", order=20,
            inline=True, description="L'activer ou non, sa nature, l'accord qu'il demande, ce qu'elle lit.")
async def _review(s: McpState, frame: Frame, args: ReviewArgs, ctx: Any) -> Done:
    port = _port(ctx)
    try:
        await port.review(ctx.subject, args.outil, enabled=args.actif, nature=args.nature, autonomy=args.seule,
                          description=args.description, by=ctx.by)
    except ValueError as exc:
        raise Refused(str(exc)) from None
    word = "activé" if args.actif else "désactivé"
    return Done(message=f"{args.outil} : {word}, {WORDS.get(args.seule, args.seule)}.",
                drafts=status_drafts(s, port))


class GenreArgs(BaseModel):
    genre: Annotated[Literal["pro", "avec", "prive", "public", "autre"], Knob(
        label="Genre", choices=tuple((k, f"{label} — {example}") for k, label, example, _ in GENRES),
        advanced=False)] = "pro"


class _ServiceBase(BaseModel):
    avec_toi: Annotated[bool, Knob(label="Toi", advanced=False, help="Sa propriétaire.")] = True
    avec_les_comptes: Annotated[bool, Knob(label="Toutes les personnes qui ont un compte", advanced=False,
                                           help="En tête-à-tête, authentifiées.")] = False
    repond: Annotated[bool, Knob(label="Quand elle répond", advanced=False)] = True
    parle: Annotated[bool, Knob(label="Quand elle prend la parole d'elle-même", advanced=False)] = False
    travaille: Annotated[bool, Knob(label="Quand elle travaille seule (un projet, un but)", advanced=False)] = False
    seule: Annotated[Literal["seule", "lit", "carte", "toi"], Knob(
        label="Ce qu'elle fait seule", choices=AUTONOMIES, advanced=False)] = "carte"
    garde: Annotated[Literal["public", "perso", "prive", "rien"], Knob(
        label="Ce qu'elle en garde", choices=KEEPS, advanced=False)] = "prive"


#: les réglages d'un service, avec ses personnes nommées (un emplacement chacune : un formulaire sans script)
ServiceArgs = create_model("ServiceArgs", __base__=_ServiceBase, **{
    f"qui{i}": (Annotated[str, Knob(label=f"Personne nommée {i}", advanced=False,
                                    help="Sa clé de personne ; vide : personne.")], Field("", max_length=200))
    for i in range(1, PEOPLE_SLOTS + 1)})

#: pas de règle : l'outil suit son service (une situation), ou sa situation (une personne) — une valeur, pas un vide
AS_SERVICE, AS_SITUATION = "service", "situation"
_SITUATION_LEVELS = ((AS_SERVICE, "comme le service"), *RULE_LEVELS)
_PERSON_LEVELS = ((AS_SITUATION, "comme sa situation"), *RULE_LEVELS)
_SituationLevel = Literal["service", "seule", "carte", "toi", "non"]
_PersonLevel = Literal["situation", "seule", "carte", "toi", "non"]


class _RulesBase(BaseModel):
    outil: Annotated[str, Knob(label="Outil", widget="hidden")] = Field(min_length=1, max_length=128)


#: les règles d'un outil : une par situation, et une par personne nommée (un emplacement chacune)
RulesArgs = create_model("RulesArgs", __base__=_RulesBase, **{
    **{f"s_{k}": (Annotated[_SituationLevel, Knob(label=label[:1].upper() + label[1:], choices=_SITUATION_LEVELS,
                                                  advanced=False)], AS_SERVICE) for k, label in TOOL_SITUATIONS},
    **{f"p{i}": (Annotated[str, Knob(label=f"Personne nommée {i}", advanced=False)], Field("", max_length=200))
       for i in range(1, PEOPLE_SLOTS + 1)},
    **{f"r{i}": (Annotated[_PersonLevel, Knob(label=f"Sa règle {i}", choices=_PERSON_LEVELS, advanced=False)],
                 AS_SITUATION) for i in range(1, PEOPLE_SLOTS + 1)}})


def _people(args: BaseModel, prefix: str) -> tuple[str, ...]:
    """Les personnes nommées d'un formulaire, dans l'ordre, sans doublon ni vide."""
    got = (str(getattr(args, f"{prefix}{i}", "") or "").strip() for i in range(1, PEOPLE_SLOTS + 1))
    return tuple(dict.fromkeys(p for p in got if p))


@MCP.action("genre", title="Choisir un genre", args=GenreArgs, emits=[STATUS], subject="serveur", order=30,
            inline=True, description="Les trois réglages d'un coup : avec qui, ce qu'elle fait seule, ce qu'elle en "
                                     "garde.")
async def _genre(s: McpState, frame: Frame, args: GenreArgs, ctx: Any) -> Done:
    port = _port(ctx)
    key, label, _, preset = next(g for g in GENRES if g[0] == args.genre)
    try:
        await port.settle(ctx.subject, preset)
    except ValueError as exc:
        raise Refused(str(exc)) from None
    return Done(message=f"{ctx.subject} : « {label} ».", drafts=status_drafts(s, port))


@MCP.action("service", title="Ce qu'elle en fait", args=ServiceArgs, emits=[STATUS], subject="serveur", order=40,
            inline=True, description="Avec qui, quand, ce qu'elle fait seule, ce qu'elle en garde.")
async def _service(s: McpState, frame: Frame, args: Any, ctx: Any) -> Done:
    port = _port(ctx)
    changes = {"with_owner": args.avec_toi, "with_accounts": args.avec_les_comptes, "with_people": _people(args, "qui"),
               "in_conversation": args.repond, "in_initiative": args.parle, "in_work": args.travaille,
               "autonomy": args.seule, "keep": args.garde}
    try:
        await port.settle(ctx.subject, changes)
    except ValueError as exc:
        raise Refused(str(exc)) from None
    st = port.status(ctx.subject)
    return Done(message=sentence(st, frame) if st is not None else "Enregistré.", drafts=status_drafts(s, port))


@MCP.action("regles", title="Ses règles", args=RulesArgs, emits=[STATUS], subject="serveur", order=50, inline=True,
            description="Par situation et par personne nommée : non, seule, sur accord de la personne, avec ton accord.")
async def _rules(s: McpState, frame: Frame, args: Any, ctx: Any) -> Done:
    port = _port(ctx)
    situations = {k: v for k, _ in TOOL_SITUATIONS if (v := getattr(args, f"s_{k}")) != AS_SERVICE}
    people: dict[str, str] = {}
    for i in range(1, PEOPLE_SLOTS + 1):
        who, level = str(getattr(args, f"p{i}") or "").strip(), getattr(args, f"r{i}")
        if who and level != AS_SITUATION:
            people.setdefault(who, level)
    try:
        await port.rule(ctx.subject, args.outil, situations=situations, people=people, by=ctx.by)
    except ValueError as exc:
        raise Refused(str(exc)) from None
    n = len(situations) + len(people)
    return Done(message=f"{args.outil} : {n} règle{'s' if n > 1 else ''}.", drafts=status_drafts(s, port))


@MCP.action("servir", title="Servir les nouveaux outils", args=NoArgs, emits=[STATUS], subject="serveur", order=25,
            inline=True, description="Les outils que personne n'a regardés, servis avec les réglages du service.")
async def _serve_new(s: McpState, frame: Frame, args: NoArgs, ctx: Any) -> Done:
    port = _port(ctx)
    served = await port.serve_new(ctx.subject, by=ctx.by)
    if not served:
        return Done(message="Aucun outil nouveau.", drafts=status_drafts(s, port))
    return Done(message=f"Servis avec les réglages du service : {', '.join(served)}.", drafts=status_drafts(s, port))


#: où tourne un serveur qu'on branche (comme Claude Code ; l'ancien transport SSE seul n'est pas pris, ADR 0064)
WHERE = (("local", "sur cette machine (stdio) — lance une commande ici, isolée"),
         ("distant", "à une adresse (HTTP) — se connecte à un serveur par son URL"))


class BranchArgs(BaseModel):
    nom: Annotated[str, Knob(label="Son nom", advanced=False,
                             help="Court : des minuscules, chiffres et _, en commençant par une lettre. Il entre dans "
                                  "le nom de ses outils.")] = Field(min_length=1, max_length=24)
    a_quoi: Annotated[str, Knob(label="À quoi il lui sert", widget="textarea", advanced=False,
                                help="Une phrase qu'elle lira pour savoir quand s'en servir.")] = \
        Field(min_length=8, max_length=1024)
    genre: Annotated[Literal["pro", "avec", "prive", "public", "autre"], Knob(
        label="Genre", choices=tuple((k, f"{label} — {example}") for k, label, example, _ in GENRES),
        advanced=False)] = "pro"
    ou: Annotated[Literal["local", "distant"], Knob(label="Transport", choices=WHERE, advanced=False)] = "local"
    commande: Annotated[str, Knob(label="Commande", advanced=False, help="Le programme : npx, uvx, python3…")] = \
        Field("", max_length=500)
    arguments: Annotated[str, Knob(label="Arguments (un par ligne)", widget="textarea", advanced=False)] = \
        Field("", max_length=4000)
    variables: Annotated[str, Knob(label="Variables d'environnement (NOM=valeur, une par ligne)", widget="textarea",
                                   secret=True, advanced=False, help="Chiffrées, jamais réaffichées.")] = \
        Field("", max_length=8000)
    adresse: Annotated[str, Knob(label="URL", advanced=False,
                                 help="L'adresse MCP « streamable HTTP » (https://…/mcp).")] = Field("", max_length=500)
    entetes: Annotated[str, Knob(label="En-têtes (Nom: valeur, un par ligne)", widget="textarea", secret=True,
                                 advanced=False, help="Chiffrés, jamais réaffichés.")] = Field("", max_length=8000)


def lines(text: str) -> list[str]:
    """Les lignes non vides d'une saisie, une valeur par ligne."""
    return [x.strip() for x in str(text or "").splitlines() if x.strip()]


@MCP.action("brancher", title="Brancher un service", args=BranchArgs, emits=[STATUS], order=5, inline=True,
            description="À quoi il sert, son genre, comment le joindre ; ses outils arrivent coupés, à servir en un "
                        "clic.")
async def _plug(s: McpState, frame: Frame, args: BranchArgs, ctx: Any) -> Done:
    port = ctx.ports.get("mcp")
    if port is None:
        raise Refused(NO_PORT)
    name = args.nom.strip().lower()
    preset = next(g for g in GENRES if g[0] == args.genre)[3]
    spec: dict[str, Any] = {"purpose": args.a_quoi.strip(), "transport": args.ou, **preset}
    if args.ou == "distant":
        bad = [x for x in lines(args.entetes) if ":" not in x or not x.partition(":")[0].strip()]
        if bad:
            raise Refused(f"En-tête illisible : « {bad[0][:40]} » — écris « Nom: valeur ».")
        spec.update(url=args.adresse.strip(), auth="aucune", secret_headers="\n".join(lines(args.entetes)))
    else:
        try:
            argv = shlex.split(args.commande)
        except ValueError:
            raise Refused("La commande est illisible (un guillemet sans sa paire ?).") from None
        bad = [x for x in lines(args.variables) if "=" not in x or not x.partition("=")[0].strip()]
        if bad:
            raise Refused(f"Variable illisible : « {bad[0].partition('=')[0][:40]} » — écris « NOM=valeur ».")
        spec.update(command=argv[0] if argv else "", args=(*argv[1:], *lines(args.arguments)),
                    secret_env="; ".join(lines(args.variables)))
    try:
        await port.plug(name, spec)
    except ValueError as exc:
        raise Refused(str(exc).splitlines()[-1][:300]) from None
    return Done(message=f"« {name} » branché. Teste-le, puis sers ses outils.", drafts=status_drafts(s, port),
                go=Ref.subject("serveur", name, name, "outils"))


@MCP.vital("outils", label="Outils extérieurs", order=80)
def _vital(s: McpState, frame: Frame) -> Vital | None:
    got = _attention(s)
    if got is None:
        return None
    n, tone = got
    broken = [x.name for x in s.servers if x.state == "panne"]
    text = f"{len(broken)} en panne" if broken else f"{n} à revoir"
    return Vital(text, tone, hint=", ".join(broken) or "des outils attendent ton regard",
                 href=Ref("local", LIST, "Venus d'ailleurs"))
