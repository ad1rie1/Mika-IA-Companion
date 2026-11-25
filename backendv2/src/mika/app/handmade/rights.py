"""Réglages › Droits (ADR 0133, 0134 ; son onglet est dans ``tabs/settings.py``) : ce qu'elle a, ressource par ressource — sa vie interne (ses
familles d'outils), les apps de la Forge, les services MCP, ses projets, ses canaux, ce que le code fixe —, une
ressource par sous-onglet (ADR 0176), chaque outil par son libellé, et pour chaque ressource un lien vers **le
détail de ses accès** : son tableau de règles, lu tel qu'il est écrit, avec « Modifier » vers la page qui le règle et
« Retour » (vers sa ligne). Les droits exacts, outil par outil, seulement quand on a choisi **qui** et **par quel
canal** : la règle du moteur, appliquée à cette personne par ce canal (les deux portes, le plafond) — jamais une
recopie. Le tableau d'un agenda se règle ici même (ADR 0309, lot 5) : sa part, dans la console de l'agenda
(``TablePart``), dit où mène « Modifier », ce qu'on règle et où le formulaire s'enregistre (``tables``).

Une lecture, sauf **Partages** (ADR 0210) : qui a reçu la boîte, le compte Teams ou le service de qui. Un opérateur y
retire le partage d'une boîte ou d'un compte Teams, par l'écriture de son propriétaire
(``app/me/sharing.py::write_share``), confirmé et audité ; celui d'un service se retire sur ses lignes d'accès. Il n'en
crée aucun : donner reste au propriétaire. Le même geste est sur la fiche d'une personne (Comptes › Partages,
``retiring``), qui y revient (``retour``). Chaque sorte de partage dit ses mots (``SharingPart.word``), si la console le
retire (``SharingPart.write``), où mène sa ressource et où il se retire sinon (sa part de console :
``ConsolePart.shared``, ``ConsolePart.unshared`` — ``share_consoles``).

Une famille se décrit ici pour l'opératrice, à la troisième personne (``FAMILY_ABOUT``) : la phrase que lit le modèle
(sa voix, ``persona/voix.yaml``) lui parle à elle (« tes rappels… »), et la console ne la recopie pas.
"""

from __future__ import annotations

import functools
import re
import secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

from mika.app.domains import DOMAINS, ConsolePart, TablePart, part
from mika.app.handmade.access import people_with_accounts
from mika.app.me import Denied, missing, sharing
from mika.app.me import outside as outside_me
from mika.inspector import render
from mika.inspector.pages import rights
from mika.inspector.pages import tools as catalog
from mika.inspector.pages.actions import safe_back
from mika.inspector.ui import PREFIX, UI, secure
from mika.kernel.frame import Audience
from mika.kernel.inspect import Pager, Ref
from mika.kernel.rights import Grant
from mika.runtime import operations
from mika.vocab.access import (
    INTERNAL,
    INTERNET,
    MOBILE,
    PERSON,
    PRIVATE,
    SELF,
    SHARES,
    TOGETHER,
    WEB,
    canal_key,
)
from mika.vocab.episodes import Kind
from mika.vocab.privacy import ChannelTrust

#: ce que le code fixe et qui n'est pas un outil (les outils, eux, se lisent : ``fixed_tools``)
FIXED = (
    "Ce que le téléphone envoie : toujours ton geste.",
    "À qui elle rend compte (un courrier qui arrive, un réveil, un projet) : toi, selon la confidentialité.",
    "Un réveil par API agit avec tes droits, dans les seuls outils qu'il déclare ; prêter à un agent, avec les tiens "
    "et tes règles d'outils.",
    "Une carte d'accord : la personne à qui elle est adressée la tranche dans son chat ; un opérateur, toutes, dans "
    "la console (« À valider »).",
    "Les plafonds : une inconnue n'obtient au plus que des outils qui lisent, jamais une action ; à plusieurs, un de "
    "ses outils qui lit au plus, rien venu d'ailleurs ; un projet s'y lit, sans plus ; sans personne en face, rien.",
)
#: les canaux qu'on peut choisir pour lire les droits exacts
CANAL_CHOICES = ((f"{WEB}:{PRIVATE}", "le chat web, en privé"), (f"{WEB}:{TOGETHER}", "le chat web, en salon"),
                 (MOBILE, "l'app Android"), (INTERNET, "Internet (un moyen que rien ne prouve)"),
                 (INTERNAL, "elle seule (elle travaille)"))
#: elle travaille seule : personne n'écoute (l'audience d'un pas, d'une exécution, d'une tâche)
WORKING = Audience(persons=(), channel="internal", public=False, trust=ChannelTrust.INTERNAL.value, owner=True)
_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")
#: la page, et où « Retirer » un partage envoie son formulaire (ADR 0210)
PAGE = f"{PREFIX}/reglages/droits"
UNSHARE = f"{PAGE}/partages"


@dataclass(frozen=True, slots=True)
class Who:
    """Une personne type : qui est en face, et à quel moment."""

    key: str
    label: str
    person: str = ""
    owner: bool = False
    kind: str = Kind.REPLY
    unknown: bool = False


def whos(ui: UI) -> list[Who]:
    """Qui on peut choisir : toi (quand elle te répond, quand elle te parle d'elle-même), chaque personne qui a un
    compte, un autre compte, une inconnue, elle seule."""
    out = [Who("toi", "toi, quand elle te répond", "toi", True),
           Who("toi-parle", "toi, quand elle te parle d'elle-même", "toi", True, Kind.INITIATIVE)]
    out += [Who(f"p:{x['key']}", x["name"], x["key"]) for x in people_with_accounts(ui)]
    out += [Who("compte", "un autre compte", "compte"), Who("inconnue", "une inconnue", "", unknown=True),
            Who("seule", "elle seule, quand elle travaille", kind=Kind.WORK)]
    return out


def audience_for(who: Who, canal: str) -> tuple[Audience, str]:
    """L'audience qu'une personne type a par ce canal, et la sorte d'épisode : la règle du moteur la lira comme le
    pipeline. Elle seule, par tout canal, c'est elle qui travaille ; dans un salon, personne n'est reconnu, même
    toi ; par Internet ou sans session, rien ne prouve qui parle, sauf un moyen relié à toi."""
    kind_, instance = canal_key(canal)
    if who.key == "seule" or kind_ == INTERNAL:
        return WORKING, Kind.WORK
    together = instance == TOGETHER
    channel = {WEB: "web", MOBILE: "mobile"}.get(kind_, "external")
    if who.unknown:
        trust = ChannelTrust.PUBLIC if kind_ == WEB else ChannelTrust.ACCOUNT
    else:
        trust = ChannelTrust.AUTHENTICATED if kind_ in (WEB, MOBILE) else ChannelTrust.ACCOUNT
    if together:
        trust = ChannelTrust.PUBLIC
    return Audience(persons=(f"droits:{who.key}",), channel=channel, room="salon" if together else None,
                    public=together, trust=trust.value, owner=who.owner and not together,
                    person="" if who.unknown else who.person), who.kind


def _tool_of(ui: UI, spec: Any, g: Grant) -> str:
    """Le nom chez elle de l'outil qu'un droit désigne : ses familles (« Mémoire · memory_search »), un service
    (« « meteo » · echo » : ``mcp_<serveur>_<outil>``), une app (le nom même)."""
    kind = spec.key.rsplit(".", 1)[-1]
    if kind == "familles":
        return g.title.rsplit(" · ", 1)[-1]
    if kind == "services":
        server, remote = g.resource.partition(":")[2], g.title.rsplit(" · ", 1)[-1]
        base = f"mcp_{server}_{_UNSAFE.sub('_', remote)}"
        if base in ui.kernel.registry.tools:
            return base
        return next((n for n in ui.kernel.registry.tools if n.startswith(f"mcp_{server}_")
                     and n.endswith(_UNSAFE.sub("_", remote)[-20:])), base)
    return g.title


def exact(ui: UI, who: Who, canal: str) -> dict[str, Any]:
    """Les droits exacts de cette personne par ce canal : par outil (son niveau, sa garde, pourquoi), par projet, et
    ce que le canal laisse au plus."""
    audience, kind = audience_for(who, canal)
    tools: dict[str, Grant] = {}
    projects: dict[str, Grant] = {}
    agendas: dict[str, Grant] = {}
    through: Grant | None = None
    for spec, found in rights.grants(ui, audience, kind):
        sort = spec.key.rsplit(".", 1)[-1]
        for g in found:
            if sort == "canaux":
                through = g
            elif sort == "projets":
                projects[g.resource] = g
            elif sort == "agendas":  # une ressource, comme un projet (ADR 0309) : ce qu'elle en fait, pas un outil
                agendas[g.resource] = g
            else:
                tools[_tool_of(ui, spec, g)] = g
    return {"tools": tools, "projects": projects, "agendas": agendas, "canal": through, "kind": kind}


def what_of(g: Grant | None) -> str:
    """Un droit en une phrase : ses actions et leurs réponses, et la ligne qui en décide."""
    if g is None:
        return "rien ici"
    said = " · ".join(f"{k} : {v}" for k, v in g.what)
    return f"{said} — {g.why}" if g.why else said


def _tool_row(ui: UI, spec: Any, got: Mapping[str, Grant] | None) -> dict[str, Any]:
    """Un outil sous sa ressource : ce qu'il fait par son libellé (``ToolSpec.label``, ADR 0208), dit à qui lit —
    sa description, écrite pour le modèle (« tu » la désigne), seulement pour un outil venu d'ailleurs, qui n'a pas de
    libellé (comme la liste d'une famille, ``inspector/pages/families.py`` ; audit du 2026-11-05, C6-10)."""
    return {"name": spec.name, "label": spec.label, "description": spec.description,
            "nature": "agit" if spec.acts else "lit",
            "href": f"{catalog.BASE}/tous?outil={spec.name}",
            "exact": what_of(got.get(spec.name)) if got is not None else "",
            "closed": got is not None and (got.get(spec.name) is None or got[spec.name].closed)}


#: ce que fait chaque famille de ses propres outils, dit à l'opératrice (sa vie interne) ; une famille absente n'a pas
#: de description, jamais celle de sa voix, écrite pour le modèle
FAMILY_ABOUT: Mapping[str, str] = {
    "agenda": "lire les agendas de la personne qui lui parle, lui trouver un créneau, y ajouter, modifier ou supprimer "
              "un rendez-vous, répondre à une invitation — selon le tableau de chaque agenda",
    "attachments": "retrouver, rouvrir et relier ce qu'on lui a envoyé (photos, documents, messages vocaux)",
    "attention": "ce qui lui trotte dans la tête en ce moment",
    "camera": "regarder par la caméra, sur le moment",
    "contacts": "retrouver ce qu'elle sait d'un contact qu'elle lit pour la personne (où elle le voit, ce qu'elle a "
                "compris de ses derniers messages), seulement ce que les comptes de cette personne en montrent",
    "email": "lister, chercher et lire le courrier des boîtes qu'elle lit, le ranger, préparer une réponse",
    "forge": "se fabriquer une app qui surveille ou relève pour elle : l'écrire, la tester, la commander",
    "forge_signals": "lire la file de signaux d'une de ses apps, et dire ce qu'elle en fait",
    "goals": "ses rappels et ses explorations ; noter une séance et en rendre compte",
    "identity": "douter d'une identité, défaire un lien",
    "imaging": "dessiner pour la personne (quelques minutes par image), montrer un dessin prêt",
    "location": "savoir où est la personne qui lui parle, d'après ce que son téléphone en a dit",
    "memory": "fouiller ses souvenirs et ce qu'elle sait ; dire qu'une promesse est tenue",
    "phone": "lire les messages (WhatsApp, Messenger, SMS) du téléphone de la personne, préparer une réponse "
             "à sa place",
    "projects": "ouvrir, accepter ou clore un projet ; en l'exécutant, son carnet, ses décisions, ses objectifs",
    "rss": "ses flux d'actualité : les derniers titres, lire un article",
    "self": "relire ce qu'elle a écrit dans son journal un jour passé",
    "shares": "envoyer à la personne un texte qu'elle écrit ou un fichier d'un projet ; relire un envoi",
    "social": "relire qui lui écrit et ce qu'elle sait de cette personne, quand son état ne le dit pas déjà",
    "teams": "lister et relire les conversations Teams des comptes qu'elle lit, préparer une réponse",
    "trips": "la carte : chercher un lieu, calculer un trajet, préparer un voyage avec la personne",
    "wakeup": "conclure un réveil par API : le compte rendu de ce que l'appel lui a fait faire",
    "project_review": "relire le travail d'un projet avant qu'il sorte : lire le commit relu, y lancer une "
                      "commande (dans une copie, à part de l'atelier), rendre un verdict — rien qui écrit (une "
                      "exécution à part, ADR 0276)",
    "workshop": "l'atelier d'un projet : lire, écrire, lancer des programmes isolés, son dépôt git",
    "world": "se déplacer et faire des choses dans sa chambre (on la voit le faire)",
}


def sections(ui: UI, got: Mapping[str, Any] | None, query: str) -> list[dict[str, Any]]:
    """Les ressources, par sorte : sa vie interne (ses familles, par lot), les apps de la Forge, les services MCP,
    ses projets, ses canaux, les agendas (ADR 0309) — chacune avec ses outils décrits et le lien de son détail."""
    registry, frame = ui.kernel.registry, ui.kernel.mind.frame()
    tables = {t.resource: t for _spec, found in rights.tables(ui) for t in found}
    by_bundle: dict[str, list[Any]] = {}
    for spec in sorted(registry.tools.values(), key=lambda t: t.name):
        by_bundle.setdefault(spec.bundle, []).append(spec)
    tools_got = got["tools"] if got else None

    def entry(key: str, label: str, description: str, specs: Sequence[Any], detail: str,
              exact_: str = "") -> dict[str, Any]:
        table = tables.get(detail)
        tools = [_tool_row(ui, s, tools_got) for s in specs]
        return {"key": key, "id": row_id(key), "label": label, "description": description, "tools": tools,
                "open": sum(not t["closed"] for t in tools),
                "detail": "?" + "&".join(filter(None, (f"detail={detail}", query))) if table is not None else "",
                "detail_key": detail if table is not None else "",
                "edit": render.href(table.href) if table is not None and table.href is not None else "",
                "exact": exact_}

    internal = [entry(b, ui.names.bundle(b), FAMILY_ABOUT.get(b, ""), specs, f"famille:{b}")
                for b, specs in sorted(by_bundle.items(), key=lambda kv: ui.names.bundle(kv[0]).casefold())
                if not any(registry.is_dynamic(s.name) for s in specs)]
    def outside(sort: str) -> list[dict[str, Any]]:
        # les familles d'une sorte venue d'ailleurs (une app, un service), chacune sur sa ligne : son libellé et le
        # détail de ses accès, tels que sa part les dit (``OutsidePart.row``)
        found = outside_me.parts()[sort]
        out = []
        for b, specs in sorted(by_bundle.items()):
            if b.startswith(found.bundle):
                label, detail = found.row(frame, b.partition(".")[2])
                out.append(entry(b, label, registry.bundles.get(b, ""), specs, detail))
        return out

    forged, services = outside("apps"), outside("services")
    projects_got = got["projects"] if got else {}
    projects = [entry(t.resource, t.title, t.note, (), t.resource, what_of(projects_got.get(t.resource)) if got else "")
                for t in tables.values() if t.resource.startswith("project:")]
    canals = [entry(t.resource, t.title, t.note, (), t.resource) for t in tables.values()
              if t.resource.startswith("canal:")]
    agendas_got = got.get("agendas", {}) if got else {}
    agendas = [entry(t.resource, t.title, t.note, (), t.resource, what_of(agendas_got.get(t.resource)) if got else "")
               for t in tables.values() if t.resource.startswith("agenda:")]
    # un sous-onglet par sorte (ADR 0176) : celles qui ont des outils les replient sous la ligne de leur ressource
    out = [{"id": "d-vie", "title": "Vie interne", "hint": "ses propres outils, famille par famille",
            "rows": internal, "folds": True},
           {"id": "d-forge", "title": "Apps de la Forge",
            "hint": "une app suit son projet ; sans projet, ses propres lignes", "rows": forged, "folds": True},
           {"id": "d-services", "title": "Services MCP", "hint": "les outils venus d'ailleurs, service par service",
            "rows": services, "folds": True},
           {"id": "d-projets", "title": "Projets", "hint": "le voir, le piloter, ses fichiers, ses apps",
            "rows": projects, "folds": False},
           {"id": "d-canaux", "title": "Canaux", "hint": "par où ça lui arrive : ce que chaque canal laisse au plus",
            "rows": canals, "folds": False},
           # chaque agenda, son tableau (ADR 0309) : le lire, y écrire, répondre à ses invitations, ce qu'elle en garde
           {"id": "d-agendas", "title": "Agendas",
            "hint": "le lire, y écrire, répondre à ses invitations : son propriétaire et ses partages",
            "rows": agendas, "folds": False}]
    for s in out:
        s["pager"] = one_page(len(s["rows"]))
    return out


def row_id(key: str) -> str:
    """L'ancre de la ligne d'une ressource : « Retour » y ramène, et son sous-onglet s'ouvre avec elle."""
    return "r-" + _UNSAFE.sub("-", key)


def one_page(rows: int) -> Any:
    return render._pager(Pager(size=max(1, rows), total=max(1, rows)), {})


@functools.cache
def tables() -> tuple[TablePart, ...]:
    """Les tableaux de droits que les domaines règlent ici (``ConsolePart.table`` : celui d'un agenda), dans l'ordre des
    fiches. Lus à la demande, une fois : une part importe ce module (``PAGE``, ``one_page``)."""
    consoles = (part(d.console, "CONSOLE") for d in DOMAINS if d.console is not None)
    return tuple(c.table for c in consoles if c.table is not None)


def table_of(key: str) -> TablePart | None:
    """La part qui règle ici le tableau de cette ressource (sa clé commence par son ``prefix``), s'il y en a une."""
    return next((t for t in tables() if key.startswith(t.prefix)), None)


def editor(ui: UI, key: str, csrf: str) -> dict[str, Any] | None:
    """Le tableau d'une ressource qui se règle ici, à régler (``TablePart.editor`` : celui d'un agenda) ; ``None`` :
    aucune part ne règle le sien ici."""
    ruled = table_of(key)
    return ruled.editor(ui, key, csrf) if ruled is not None else None


def detail(ui: UI, key: str) -> dict[str, Any] | None:
    """Le détail des accès d'une ressource : son tableau tel qu'il est écrit, ses planchers, où il se règle — un
    agenda, ici même (« Modifier », ADR 0309, lot 5)."""
    for spec, found in rights.tables(ui):
        for t in found:
            if t.resource == key:
                edit = render.href(t.href) if t.href is not None else ""
                ruled = table_of(key)
                if ruled is not None:  # un tableau qui se règle ici même (``TablePart.edit``)
                    edit = ruled.edit(key)
                return {"kind": spec.title, "title": t.title, "columns": t.columns,
                        "rows": [(str(i), *r) for i, r in enumerate(t.rows, start=1)], "default": t.default,
                        "floors": t.floors, "note": t.note, "edit": edit,
                        "pager": one_page(len(t.rows) + 1)}
    return None


def fixed_tools(ui: UI) -> dict[str, Any]:
    """Ce que le code déclare, lu des outils mêmes : ceux dont le minimum vital est à toi et elle seule
    (``owner_only``), par famille ; ceux qu'une condition garde (``when``), regroupés par sa phrase. Un outil réservé
    peut être gardé aussi : une ligne qui l'ouvre ne lève pas sa condition (ADR 0148)."""
    reserved: dict[str, list[str]] = {}
    guarded: dict[str, list[str]] = {}
    for spec in sorted(ui.kernel.registry.tools.values(), key=lambda t: t.name):
        if spec.owner_only:
            reserved.setdefault(ui.names.bundle(spec.bundle), []).append(spec.name)
        if spec.when is not None:
            guarded.setdefault(catalog.condition(spec), []).append(spec.name)
    return {"reserved": sorted(reserved.items()), "guarded": sorted(guarded.items(), key=lambda x: -len(x[1])),
            "count": sum(len(n) for n in reserved.values()), "guarded_count": sum(len(n) for n in guarded.values())}


def retired_here(kind: str) -> bool:
    """La console retire-t-elle elle-même un partage de cette sorte ? Oui quand sa part l'écrit
    (``SharingPart.write``) ; un service, non : il se retire sur ses lignes d'accès."""
    found = sharing.parts().get(kind)
    return found is not None and found.write is not None


@functools.cache
def share_consoles() -> dict[str, ConsolePart]:
    """La part de console de chaque sorte de partage, par sa sorte (dans l'ordre de ``app/me/sharing.py::KINDS``) :
    celle du domaine qui la partage — où mène sa ressource (``ConsolePart.shared``) et, quand la console ne le retire
    pas elle-même, où il se retire (``ConsolePart.unshared``). Lue à la demande, une fois ; chaque sorte a la sienne."""
    found = {part(d.sharing, "SHARING").kind: part(d.console, "CONSOLE") for d in DOMAINS
             if d.sharing is not None and d.console is not None}
    lacking = sorted(kind for kind in sharing.KINDS if kind not in found or found[kind].shared is None
                     or (not retired_here(kind) and found[kind].unshared is None))
    if lacking:
        raise ValueError(f"Partages : chaque sorte dit dans sa part de console où mène sa ressource — {lacking}")
    return {kind: found[kind] for kind in sharing.KINDS}


def _resource(s: sharing.Shared) -> str:
    article = "la " if s.kind == "mail" else "l'" if s.kind == "agenda" else "le "
    return f"{article}{sharing.parts()[s.kind].word} « {s.title} »"


def _owner(ui: UI, owner: str) -> str:
    """Le propriétaire d'une ressource, en mots : toi (vide), elle, ou la personne."""
    if owner == SELF:
        return ui.her_name()
    return ui.names.who(owner[len(PERSON):]) if owner.startswith(PERSON) else "toi"


def retiring(ui: UI, s: sharing.Shared) -> dict[str, Any]:
    """Comment retirer ce partage, là où il se montre (Partages ici ; Comptes › Partages, sur la fiche d'une personne) :
    ce que le formulaire « Retirer » envoie (sa sorte, sa clé, la personne qui le reçoit), la question qui le confirme
    et le nom de cette personne ; un service, lui, mène à ses lignes d'accès (``access``), où il se retire. Écrit une
    fois, pour que les deux endroits posent le même geste."""
    name = ui.names.who(s.person)
    return {"kind": s.kind, "key": s.key, "person": s.person, "name": name,
            "access": "" if retired_here(s.kind) else share_consoles()[s.kind].unshared(s),
            "ask": f"Retirer à {name} son accès à {_resource(s)} ? Il disparaît de son espace ; seul son "
                   "propriétaire peut le lui redonner."}


def shared(ui: UI) -> list[dict[str, Any]]:
    """Partages (ADR 0210) : une ligne chacun, en mots — sa ressource et sa sorte, son propriétaire, qui le reçoit, son
    niveau, et comment le retirer (``retiring``). La date n'y est pas : un partage ne la garde pas."""
    settings = ui.deps.settings
    if settings is None:
        return []
    out = []
    for s in sharing.every_share(settings, sharing.resource_names(ui.kernel.ports.get)):
        row = retiring(ui, s)
        out.append({**row, "title": s.title, "sort": sharing.parts()[s.kind].word, "owner": _owner(ui, s.owner),
                    "level": dict(SHARES).get(s.level, s.level),
                    "href": render.href(Ref.subject("person", ui.names.person_of(s.person), row["name"]))})
    return out


async def _unshared(ui: UI, data: Mapping[str, Any], by: str) -> tuple[str, str]:
    """Retirer ce partage : ce qu'il faut en dire. Il a pu partir entre-temps (un autre onglet, son propriétaire) : rien
    n'est alors écrit ni audité."""
    kind, key, person = (str(data.get(k, "")) for k in ("kind", "key", "person"))
    if not retired_here(kind):
        return "warn", "Un service se retire sur ses lignes d'accès : rien n'a été retiré ici."
    found = next((s for s in sharing.every_share(ui.deps.settings)
                  if (s.kind, s.key, s.person) == (kind, key, person)), None)

    def there(spec: Any) -> None:
        if PERSON + person not in spec.shares:
            raise missing()

    try:
        await sharing.write_share(ui.deps.settings, ui.deps.reconfigure, kind, key, person, "", there)
    except Denied as exc:
        return "warn", "Ce partage n'est plus là : rien à retirer." if exc.status == 404 else exc.message
    await operations.audit(ui.kernel, "console.droits.partage_retire", by=by,
                           **sharing.audited_share(kind, key, person))
    what = _resource(found) if found is not None else f"« {key} »"
    return "ok", f"Partage retiré : {ui.names.who(person)} n'a plus accès à {what}."


def _back(asked: str, token: str) -> str:
    """Où revenir, le message en tête : ``retour`` s'il est une adresse de la console (``safe_back`` : la fiche d'une
    personne, son sous-onglet Partages), sinon la liste des partages. Le message se pose avant l'ancre."""
    target = asked if asked and safe_back(asked) == asked else f"{PAGE}#d-partages"
    path, _, anchor = target.partition("#")
    flashed = f"{path}{'&' if '?' in path else '?'}flash={quote(token, safe='')}"
    return f"{flashed}#{anchor}" if anchor else flashed


async def unshare(ui: UI, request: Request) -> Response:
    """« Retirer », dans Partages ou sur la fiche d'une personne (Comptes › Partages, ``retour``) : confirmé par la
    page, audité ; on revient d'où l'on vient (``_back``), le message en tête — même quand le jeton est refusé."""
    data = await ui.form(request)
    account = ui.operator(request)
    token = secrets.token_urlsafe(9)
    if data is None or account is None:
        ui.flash(token, "danger", "Jeton de formulaire invalide : recharge la page.")
    elif ui.deps.settings is None:
        ui.flash(token, "warn", "Les réglages ne sont pas joignables : rien n'a été retiré.")
    else:
        ui.flash(token, *await _unshared(ui, data, account.handle))
    asked = str((await request.form()).get("retour") or "")  # le formulaire déjà lu (Starlette le garde)
    return secure(RedirectResponse(_back(asked, token), status_code=303))


def routes(ui: UI) -> list[Route]:
    async def post(request: Request) -> Response:
        return await unshare(ui, request)

    # puis où s'enregistre un tableau qu'un domaine règle ici (``TablePart.routes`` : celui d'un agenda)
    return [Route(UNSHARE, ui.guarded(post), methods=["POST"]), *(route for t in tables() for route in t.routes(ui))]
