"""La console des serveurs MCP (ADR 0064) : dans « Outils › Venus d'ailleurs », la liste des serveurs branchés, puis la fiche de
chacun — son état, ce qu'il propose, ce que l'opérateur en a approuvé, ses appels.

Les connexions (adresse, jeton, commande) se règlent dans Réglages › Plugins › Outils extérieurs ; un lien y mène et
l'enregistrement ramène ici. Ce qui se décide ici : qui peut quoi, en lignes d'accès lues de haut en bas comme les
règles d'un pare-feu, et la ligne par défaut (ADR 0131) ; ce qu'il propose de neuf, regardé d'un coup (ADR 0129) ;
outil par outil : l'activer, sa nature (il lit ou il agit), la description qu'elle lit. « Qui peut quoi » se calcule
par la règle du moteur (``access_for``), jamais par une recopie. Ce que le serveur dit de lui-même et de ses outils
est une donnée venue d'ailleurs : montrée à l'opérateur, jamais obéie.
"""

from __future__ import annotations

import shlex
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from mika.contracts import identity as identity_c
from mika.kernel.clock import DAY
from mika.kernel.forms import Knob
from mika.kernel.frame import Audience, Frame
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
from mika.plugins.mcp import (
    ALONE,
    ANSWERED,
    APPROVED,
    CARD,
    EXPIRED,
    EXPIRER,
    FAILED,
    MCP,
    NO,
    REFUSED,
    STATUS,
    WAITING,
    McpState,
    status_drafts,
)
from mika.ports.mcp import (
    KEEPS,
    MOMENTS,
    NATURES,
    POLICIES,
    STATES,
    WHO_ACCOUNTS,
    WHO_OWNER,
    WHO_PERSON,
    Access,
)
from mika.vocab.episodes import Kind, is_work_target
from mika.vocab.privacy import ChannelTrust

SETTINGS = "/inspecteur/reglages/serveurs-mcp"
LIST = "/inspecteur/outils/serveurs"
NO_PORT = "Les outils extérieurs ne sont pas branchés sur ce serveur."
FAILED_SEE_FICHE = "Le test a échoué : l'erreur est sur sa fiche."
STATE_TONES = {"inactif": "muted", "incomplet": "warn", "jamais": "muted", "connecte": "ok", "erreur": "warn",
               "panne": "danger"}
#: ce qu'une ligne d'accès fait d'un outil, en mots (ADR 0131)
POLICY_WORDS = {"seule": "seule", "carte": "demande à la personne", "toi": "ton accord", "non": "non"}
#: quand une ligne vaut, en mots
WHEN_WORDS = dict(MOMENTS)
#: ce qu'elle garde, en mots courts
KEEP_WORDS = {"public": "ce qu'elle sait", "perso": "un souvenir", "prive": "une confidence", "rien": "rien"}
#: la ligne qu'on ajoute : toi, tout le temps ; elle lit seule, te demande avant d'agir, garde en confidence
NEW_ROW: dict[str, Any] = {"who": WHO_OWNER, "when": [], "read": "seule", "act": "toi", "keep": "prive",
                           "tools": []}
#: au plus tant de lignes (un tableau que l'on lit d'un regard)
MAX_ROWS = 40


def name_of(frame: Frame | None, person: str) -> str:
    """Le nom d'une personne nommée (repli : sa clé)."""
    view = frame.get(identity_c.IDENTITY(person)) if frame is not None and person else None
    return str(getattr(view, "name", "") or person)


def who_label(who: str, frame: Frame | None = None) -> str:
    """Qui une ligne d'accès désigne, en mots : toi, les comptes, une personne par son nom ; la ligne par défaut."""
    if not who:
        return "Comportement par défaut"
    if who == WHO_OWNER:
        return "Toi"
    if who == WHO_ACCOUNTS:
        return "Les comptes"
    return name_of(frame, who[len(WHO_PERSON):]) if who.startswith(WHO_PERSON) else who


def when_label(when: Sequence[str]) -> str:
    """Quand une ligne vaut, en mots : « toujours », ou ses moments."""
    if not when:
        return "toujours"
    words = [WHEN_WORDS.get(w, w) for w in when]
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " ou " + words[-1]


def _opens(a: Access) -> bool:
    return a.read != NO or a.act != NO


def serves_nobody(st: Any) -> bool:
    """Le service n'est ouvert à personne : aucune ligne ne laisse servir un outil, et la ligne par défaut est
    fermée."""
    return not any(_opens(a) for a in (*st.access, st.default))


def who_said(st: Any, frame: Frame | None = None) -> str:
    """Avec qui, en quelques mots : qui ses lignes ouvrent (et « tout le monde » si la ligne par défaut l'est)."""
    if _opens(st.default):
        return "tout le monde (en tête-à-tête)"
    parts = list(dict.fromkeys(who_label(a.who, frame).lower() if a.who in (WHO_OWNER, WHO_ACCOUNTS)
                               else who_label(a.who, frame) for a in st.access if _opens(a)))
    if not parts:
        return "personne"
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " et " + parts[-1]


def access_said(st: Any) -> str:
    """Ses lignes d'accès en quelques mots : combien, et ce que fait la ligne par défaut."""
    d = st.default
    default = "fermé" if not _opens(d) else \
        f"lecture {POLICY_WORDS[d.read]}, action {POLICY_WORDS[d.act]}, garde {KEEP_WORDS[d.keep]}"
    n = len(st.access)
    lines = f"{n} ligne{'s' if n > 1 else ''}" if n else "aucune ligne"
    return f"{lines} · par défaut : {default}"


# ── qui peut quoi (ADR 0129, 0131) : la règle du moteur, appliquée à des personnes types ──


def _facing(person: str = "", *, owner: bool = False) -> Audience:
    """Une personne en tête-à-tête, authentifiée, comme le moteur en voit une ; ``person`` vide : un compte que rien
    ne nomme."""
    return Audience(persons=(f"colonne:{person or ('toi' if owner else 'compte')}",), channel="web", public=False,
                    trust=ChannelTrust.AUTHENTICATED.value, owner=owner, person=person)


#: elle travaille seule : personne n'écoute (l'audience que le moteur donne à un pas, une exécution, une tâche)
WORKING = Audience(persons=(), channel="internal", public=False, trust=ChannelTrust.INTERNAL.value, owner=True)


@dataclass(frozen=True, slots=True)
class Face:
    """Une colonne de « qui peut quoi » : qui est en face, et à quel moment — ou personne quand elle travaille
    seule."""

    key: str
    label: str
    audience: Audience
    kind: str


@dataclass(frozen=True, slots=True)
class ToolView:
    """Ce que la règle du moteur (``access_for``) lit d'un outil : sa nature, les lignes de son service qui le
    concernent, dans leur ordre, et la ligne par défaut."""

    nature: str
    access: tuple[Access, ...]
    default: Access


def tool_view(st: Any, remote: str, nature: str) -> ToolView:
    return ToolView(nature, tuple(a for a in st.access if a.concerns(remote)), st.default)


def faces(st: Any, frame: Frame | None = None) -> list[Face]:
    """Les colonnes de « qui peut quoi » : toi quand elle te répond, toi quand elle te parle d'elle-même, chaque
    personne que nomme une ligne, les autres comptes, et quand elle travaille seule pour toi."""
    named = list(dict.fromkeys(a.who[len(WHO_PERSON):] for a in st.access if a.who.startswith(WHO_PERSON)))
    out = [Face("toi", "Toi", _facing(owner=True), Kind.REPLY),
           Face("toi-parle", "Toi, quand elle te parle d'elle-même", _facing(owner=True), Kind.INITIATIVE)]
    out += [Face(f"p:{p}", name_of(frame, p), _facing(p), Kind.REPLY) for p in named]
    out.append(Face("comptes", "Les autres comptes" if named else "Les comptes", _facing(), Kind.REPLY))
    out.append(Face("travail", "Elle travaille seule", WORKING, Kind.STEP))
    return out


def said_level(level: str, face: Face) -> tuple[str, str, str]:
    """Un accord devant cette colonne, en mots : (ce qu'elle fait, où se décide l'accord, ton). « Toi » et « ton
    accord » reviennent au même quand c'est toi en face ; sans personne en face, la demande t'attend dans la console."""
    if level == NO:
        return "non", "", "muted"
    if level == ALONE:
        return "seule", "", "ok"
    if face.key in ("toi", "toi-parle"):
        return "te demande", "une carte dans ton chat", "info"
    if face.key != "travail" and level == CARD:
        return "lui demande", "une carte dans son chat", "info"
    return "te demande", "dans la console (« À valider »)", "info"


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
                         When(st.last_ok_at) if st.last_ok_at else "jamais", who_said(st, frame), access_said(st)),
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
                   "avec qui", "accès"),
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
              Badge(f"avec {who_said(st, frame)}", "danger" if serves_nobody(st) else "info")]
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
    blocks.append(Fields((
        ("à quoi il sert, pour elle", st.purpose or "—"),
        ("quand s'en servir", st.when_to_use or "—"),
        ("où", Text(st.address or "—", "mono")),
        ("avec qui", f"{who_said(st, frame)} — jamais dans un salon ni avec une inconnue"),
        ("accès", access_said(st)),
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
    return "servi", "ok"


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
             description="Ce que le serveur propose maintenant, et ce que tu en as décidé : activé ou non, s'il lit "
                         "ou s'il agit, la description qu'elle lit.")
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
    if st.new or st.changed:
        blocks.append(ActionSlot("mcp.revoir", title="Enregistrer ces choix"))
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
                ("description", current)), title="Enregistrer", compact=True))
        rows.append(Row((Text(remote, "mono"), Text(said or "—", clamp=140), Badge(word, tone),
                         _words(NATURES, review.nature) if review else "—"),
                        tone="danger" if tone == "danger" else "", detail=tuple(detail)))
    blocks.append(Table(("outil", "ce qu'il dit faire", Column("état", "fit"), Column("nature", "fit")), tuple(rows),
                        title=f"Ce qu'il propose ({len(st.live)})",
                        empty="Rien pour l'instant.",
                        caption="Approuver un outil, c'est approuver ce qu'il dit être maintenant : s'il change, il est "
                                "suspendu. Ce que dit le serveur est une donnée : relis-le avant de l'activer."))
    return blocks


def _tools_of(row: Access) -> str:
    return "tous" if not row.tools else ", ".join(row.tools)


@MCP.inspect("fait", title="Accès aux outils", subject="serveur", order=15,
             description="Qui peut se servir de ses outils, quand, ce qu'elle en fait et ce qu'elle en garde : des "
                         "lignes lues de haut en bas, puis la ligne par défaut.")
def _tab_access(s: McpState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = ctx.ports.get("mcp")
    st = port.status(ctx.subject) if port is not None else None
    if st is None:
        return [Note("Ce serveur n'existe plus.", tone="muted")]
    rows = [Row((str(i), who_label(a.who, frame), when_label(a.when), POLICY_WORDS[a.read],
                 POLICY_WORDS[a.act], KEEP_WORDS[a.keep], _tools_of(a)))
            for i, a in enumerate((*st.access, st.default), start=1)]
    return [
        Table((Column("#", "fit"), "qui", "quand", "lecture", "action", "ce qu'elle en garde", "outils"), tuple(rows),
              title="Accès aux outils", caption="De haut en bas : pour un outil, la première ligne qui le concerne "
              "décide ; aucune, c'est la dernière, le comportement par défaut. Jamais dans un salon ni avec une "
              "inconnue."),
        # sans valeurs initiales : celles d'une ligne (``qui.1``…) ne sont pas des champs, la console les reposerait
        # en valeurs fixées, et une case décochée resterait cochée ; le tableau dessiné montre les vraies
        ActionSlot("mcp.acces", (), title="Enregistrer"),
    ]


#: l'issue d'un appel sur accord, son ton
REQUEST_TONES = {WAITING: "info", APPROVED: "info", ANSWERED: "ok", REFUSED: "warn", EXPIRED: "muted",
                 FAILED: "danger"}
#: où l'accord se décidait
ASKED = {"conversation": "une carte dans le chat", "operateur": "dans la console"}
#: ce que l'onglet « Appels » remonte
CALLS_DAYS = 14


def _for(frame: Frame | None, target: str | None) -> str:
    """Pour qui un appel est parti : une personne, par son nom ; « elle travaillait » sans personne en face."""
    if not target or is_work_target(target):
        return "elle travaillait"
    person = frame.get(identity_c.PERSON(target)) if frame is not None else None
    return name_of(frame, str(person or target))


def _decided(frame: Frame | None, req: Any) -> str:
    if req.status == WAITING:
        return ""
    if req.by == EXPIRER:
        return "le délai"
    return _for(frame, req.by) if req.approval == "conversation" else (req.by or "")


@MCP.inspect("appels", title="Appels", subject="serveur", order=30,
             description="Les appels de ses outils (14 jours) : pour qui, comment l'accord s'est décidé, ce qui en est "
                         "sorti, vers l'épisode où les relire.")
def _tab_calls(s: McpState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port, traces = ctx.ports.get("mcp"), ctx.ports.get("traces")
    st = port.status(ctx.subject) if port is not None else None
    if st is None:
        return [Note(NO_PORT if port is None else "Ce serveur n'existe plus.", tone="muted")]
    since = frame.now - CALLS_DAYS * DAY
    asked = [r for r in s.requests.values() if r.server == st.name and r.at >= since]
    # un appel qui demandait un accord a sa ligne à lui : la trace n'en a vu que la proposition
    proposed = {(r.request.split(":", 1)[0], r.remote) for r in asked}
    names = {t.remote: t.name for t in port.offered() if t.server == st.name}
    for remote, review in st.reviews.items():
        names.setdefault(remote, review.name)
    rows: list[tuple[int, Row]] = []
    for remote, name in (names.items() if traces is not None else ()):
        for u in (traces.tool_uses(name, 20) if name else ()):
            if u.at < since or (u.correlation, remote) in proposed:
                continue
            issue = ("rendu", "ok") if u.ok else ("pas lancé", "warn") if not u.executed else ("échec", "danger")
            rows.append((u.at, Row((When(u.at), Text(remote, "mono"), _for(frame, u.target), "seule", Badge(*issue),
                                    "", Ref("episode", u.correlation, "relire", (("onglet", "outils"),))))))
    for r in asked:
        rows.append((r.at, Row((When(r.at), Text(r.remote, "mono"), _for(frame, r.target),
                                ASKED.get(r.approval, r.approval), Badge(r.status, REQUEST_TONES.get(r.status, "")),
                                _decided(frame, r),
                                Ref("episode", r.request.split(":", 1)[0], "relire", (("onglet", "outils"),))))))
    rows.sort(key=lambda r: -r[0])
    return [Table((Column("quand", "fit"), Column("outil", "fit"), Column("pour qui", "fit"),
                   Column("l'accord", "fit"), Column("issue", "fit"), Column("décidé par", "fit"), ""),
                  tuple(r for _, r in rows[:50]), title="Derniers appels",
                  empty=f"Aucun appel de ses outils depuis {CALLS_DAYS} jours.",
                  caption="« seule » : l'appel est parti sans demander. Sur accord, rien ne part avant le oui ; "
                          "« rendue » : il est parti et a répondu.")]


# ── Actions ───────────────────────────────────────────────────────────────


class NoArgs(BaseModel):
    pass


class ToolArgs(BaseModel):
    outil: Annotated[str, Knob(label="Outil", widget="hidden")] = Field(min_length=1, max_length=128)
    actif: Annotated[bool, Knob(label="Activé", advanced=False,
                                help="Coché : elle peut s'en servir, tel que le serveur le décrit maintenant.")] = False
    nature: Annotated[Literal["lecture", "action"], Knob(
        label="Nature", choices=NATURES, advanced=False,
        help="Il lit, ou il agit : la colonne « lecture » ou « action » de ses lignes d'accès s'applique.")] = "lecture"
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


_Policy = Literal["seule", "carte", "toi", "non"]
_Keep = Literal["public", "perso", "prive", "rien"]


class AccessArgs(BaseModel):
    """Le tableau « Accès à ses outils », d'un seul envoi (ADR 0131) : une ligne par numéro (``<champ>.<numéro>``),
    ses moments cochés (``moments.<numéro>|<moment>``, ou ``toujours.<numéro>``), ses outils cochés
    (``prend.<numéro>|<outil>``, ou ``tous.<numéro>``), la ligne par défaut, et ce qu'un bouton demande en plus
    d'enregistrer (``faire`` : ajouter une ligne, en monter, en descendre ou en retirer une)."""

    qui: Annotated[dict[str, str], Knob(label="Qui", advanced=False)] = Field(default_factory=dict)
    toujours: Annotated[dict[str, bool], Knob(label="Toujours", advanced=False)] = Field(default_factory=dict)
    moments: Annotated[dict[str, bool], Knob(label="Quand", advanced=False)] = Field(default_factory=dict)
    lecture: Annotated[dict[str, _Policy], Knob(label="Un outil qui lit", choices=POLICIES, advanced=False)] = \
        Field(default_factory=dict)
    action: Annotated[dict[str, _Policy], Knob(label="Un outil qui agit", choices=POLICIES, advanced=False)] = \
        Field(default_factory=dict)
    garde: Annotated[dict[str, _Keep], Knob(label="Ce qu'elle en garde", choices=KEEPS, advanced=False)] = \
        Field(default_factory=dict)
    tous: Annotated[dict[str, bool], Knob(label="Tous ses outils", advanced=False)] = Field(default_factory=dict)
    prend: Annotated[dict[str, bool], Knob(label="Ses outils", advanced=False)] = Field(default_factory=dict)
    defaut_lecture: Annotated[_Policy, Knob(label="Par défaut, un outil qui lit", choices=POLICIES,
                                            advanced=False)] = "non"
    defaut_action: Annotated[_Policy, Knob(label="Par défaut, un outil qui agit", choices=POLICIES,
                                           advanced=False)] = "non"
    defaut_garde: Annotated[_Keep, Knob(label="Par défaut, ce qu'elle en garde", choices=KEEPS,
                                        advanced=False)] = "rien"
    #: la valeur du bouton pressé (un champ ordinaire : un champ caché ne se lit que dans les valeurs fixées)
    faire: Annotated[str, Knob(label="Et", help="ajouter, monter:n, descendre:n ou retirer:n ; vide : enregistrer")] = \
        Field("", max_length=40)


def _number(key: str) -> int:
    return int(key) if key.isdigit() else 10**6


def access_rows(args: AccessArgs, known: Sequence[str]) -> list[dict[str, Any]]:
    """Les lignes du tableau envoyé, dans leur ordre ; refuse une ligne sans « qui » lisible ou sans outil."""
    rows = []
    for n, key in enumerate(sorted(args.qui, key=_number), start=1):
        who = args.qui[key].strip()
        if not (who in (WHO_OWNER, WHO_ACCOUNTS) or (who.startswith(WHO_PERSON) and who[len(WHO_PERSON):].strip())):
            raise Refused(f"Ligne {n} : choisis qui.")
        when = [] if args.toujours.get(key) else [m for m, _ in MOMENTS if args.moments.get(f"{key}|{m}")]
        if not args.toujours.get(key) and not when:
            raise Refused(f"Ligne {n} : coche au moins un moment, ou « toujours ».")
        tools = [] if args.tous.get(key) else [r for r in known if args.prend.get(f"{key}|{r}")]
        if not args.tous.get(key) and not tools:
            raise Refused(f"Ligne {n} : coche au moins un outil, ou « tous ».")
        rows.append({"who": who, "when": when, "read": args.lecture.get(key, NO),
                     "act": args.action.get(key, NO), "keep": args.garde.get(key, "rien"), "tools": tools})
    return rows


def moved(rows: list[dict[str, Any]], faire: str) -> tuple[list[dict[str, Any]], str]:
    """Ce qu'un bouton du tableau demande : ajouter une ligne (au-dessus de la ligne par défaut), monter, descendre
    ou retirer la ligne ``n`` ; et ce qu'on en dit."""
    op, _, at = faire.partition(":")
    i = int(at) - 1 if at.isdigit() else -1
    rows = list(rows)
    if op == "ajouter":
        if len(rows) >= MAX_ROWS:
            raise Refused(f"{MAX_ROWS} lignes au plus.")
        rows.append(dict(NEW_ROW))
        return rows, f"Ligne {len(rows)} ajoutée : règle-la, puis enregistre."
    if op == "monter" and 0 < i < len(rows):
        rows[i - 1], rows[i] = rows[i], rows[i - 1]
        return rows, f"Ligne {i + 1} montée."
    if op == "descendre" and 0 <= i < len(rows) - 1:
        rows[i], rows[i + 1] = rows[i + 1], rows[i]
        return rows, f"Ligne {i + 1} descendue."
    if op == "retirer" and 0 <= i < len(rows):
        del rows[i]
        return rows, f"Ligne {i + 1} retirée."
    return rows, "Accès enregistrés."


@MCP.action("acces", title="Accès à ses outils", args=AccessArgs, emits=[STATUS], subject="serveur", order=15,
            inline=True, description="Ses lignes d'accès, lues de haut en bas, et la ligne par défaut : qui, quand, "
                                     "ce qu'elle fait d'un outil qui lit et d'un outil qui agit, ce qu'elle en garde, "
                                     "à quels outils.")
async def _access(s: McpState, frame: Frame, args: AccessArgs, ctx: Any) -> Done:
    port = _port(ctx)
    st = port.status(ctx.subject)
    known = list(dict.fromkeys([*(t.remote for t in st.live), *st.reviews])) if st is not None else []
    rows, said = moved(access_rows(args, known), args.faire.strip())
    try:
        await port.settle(ctx.subject, {"access": rows, "default_read": args.defaut_lecture,
                                        "default_act": args.defaut_action, "default_keep": args.defaut_garde})
    except ValueError as exc:
        raise Refused(str(exc).splitlines()[-1][:300]) from None
    return Done(message=said, drafts=status_drafts(s, port))


@MCP.action("regler", title="Régler l'outil", args=ToolArgs, emits=[STATUS], subject="serveur", order=20,
            inline=True, description="L'activer ou non, s'il lit ou s'il agit, ce qu'elle lit de lui. Qui peut s'en "
                                     "servir : « Accès aux outils ».")
async def _review(s: McpState, frame: Frame, args: ToolArgs, ctx: Any) -> Done:
    port = _port(ctx)
    try:
        await port.review(ctx.subject, args.outil, enabled=args.actif, nature=args.nature,
                          description=args.description, by=ctx.by)
    except ValueError as exc:
        raise Refused(str(exc)) from None
    word = "servi" if args.actif else "coupé"
    return Done(message=f"{args.outil} : {word}, il {'lit' if args.nature == 'lecture' else 'agit'}.",
                drafts=status_drafts(s, port))


#: ce qu'on décide d'un outil nouveau ou changé (ADR 0129) : rien ne se sert sans un choix
CHOICES = (("non", "laisser coupé"), ("lecture", "servir : il lit"), ("action", "servir : il agit"))


class DecideArgs(BaseModel):
    outils: Annotated[dict[str, Literal["non", "lecture", "action"]], Knob(
        label="Ses outils", advanced=False, help="Un choix par outil : laisser coupé, ou servir en lecture ou en "
                                                 "action.")] = Field(default_factory=dict)


@MCP.action("revoir", title="Ce qu'il propose de neuf", args=DecideArgs, emits=[STATUS], subject="serveur", order=25,
            inline=True, description="Les outils nouveaux ou changés, d'un coup : laisser coupé, ou servir en lecture "
                                     "ou en action.")
async def _decide(s: McpState, frame: Frame, args: DecideArgs, ctx: Any) -> Done:
    port = _port(ctx)
    try:
        done = await port.decide(ctx.subject, args.outils, by=ctx.by)
    except ValueError as exc:
        raise Refused(str(exc)) from None
    if not done:
        return Done(message="Aucun choix.", drafts=status_drafts(s, port))
    served = [r for r, c in done.items() if c != "non"]
    off = len(done) - len(served)
    said = f"Servis : {', '.join(served)}." if served else "Aucun servi."
    return Done(message=said + (f" {off} laissé{'s' if off > 1 else ''} coupé{'s' if off > 1 else ''}." if off else ""),
                drafts=status_drafts(s, port))


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
            description="À quoi il sert, comment le joindre ; ses outils arrivent coupés, à regarder un par un, et "
                        "personne n'y a accès tant que tu n'as pas ajouté une ligne d'accès.")
async def _plug(s: McpState, frame: Frame, args: BranchArgs, ctx: Any) -> Done:
    port = ctx.ports.get("mcp")
    if port is None:
        raise Refused(NO_PORT)
    name = args.nom.strip().lower()
    # fermé par défaut, comme un pare-feu (ADR 0131) : qui peut quoi s'ajoute ensuite, ligne par ligne
    spec: dict[str, Any] = {"purpose": args.a_quoi.strip(), "transport": args.ou}
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
    return Done(message=f"« {name} » branché. Teste-le, choisis ses outils, puis donne-lui un accès (« Accès aux "
                        "outils »).", drafts=status_drafts(s, port),
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
